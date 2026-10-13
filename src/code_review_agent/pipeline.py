"""Multi-pass review pipeline: several specialists, merged, then verified.

Why several passes? A small model does better on a narrow job than on "review everything":
  compliance  checks every acceptance criterion of the ticket, one verdict each (a checklist);
  defects     looks for logic, boundary, error-handling and maintainability problems;
  security    looks only for security weaknesses;
  verify      gives every candidate finding a second, independent look and may dismiss it.

Two halves:
  * `run_multi` CALLS the model once per pass and records each raw answer (`RunRecord.passes`).
  * `assemble_multi` turns the recorded answers into the final `ReviewResult`. It is a pure,
    deterministic function of the record and the inputs, so a saved run can be re-validated
    later without calling any model, and it is tested without one.

Honesty rules carried over from the single-pass pipeline: a pass that fails or returns
unusable output is reported (partial coverage), a finding the verifier dismisses stays
visible with the reason, and a criterion nobody judged is shown as "cannot determine".
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib import resources

from pydantic import BaseModel

from .context import DEFAULT_MAX_CHARS, build_user_message
from .events import EventLog
from .evidence import (
    DEFAULT_TOOLS,
    MAX_REPORTED_FINDINGS,
    RUFF_SELECT,
    compute_profile,
    render_leads,
    run_static_analysis,
    select_reportable,
    tool_findings_to_findings,
)
from .model_client import ModelClient, ModelError
from .review import PassRecord, RunRecord
from .schemas import (
    WHOLE_CHANGE,
    Category,
    ComplianceReview,
    Coverage,
    CriterionCheck,
    CriterionVerdict,
    DismissedFinding,
    Evidence,
    FailureKind,
    Finding,
    ModelReview,
    PassSummary,
    ProblemKind,
    ReviewedRevision,
    ReviewFailure,
    ReviewInput,
    ReviewResult,
    RunSummary,
    Severity,
    Ticket,
    ValidationProblem,
    VerifyReview,
    public_schema,
)
from .validation import DROPPED, InvalidOutput, check_criteria, check_grounding, parse_json_output

MULTI_PROMPT_VERSION = "multi_v2"  # v1 had no static-analysis or team-rules blocks; it stays loadable
DEFAULT_PASSES = ("compliance", "defects", "security", "standards")
PASS_MODELS: dict[str, type[BaseModel]] = {
    "compliance": ComplianceReview,
    "defects": ModelReview,
    "security": ModelReview,
    "standards": ModelReview,
    "verify": VerifyReview,
}


def _schema_for(name: str) -> dict:
    """The JSON Schema one pass must follow (only the standards pass may cite the team rules)."""
    return public_schema(PASS_MODELS[name], allow_rules=(name == "standards"))

_SEVERITY_RANK = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2, Severity.LOW: 3}
# When two reports describe one issue, the more specific category wins.
_SPECIFICITY = [Category.SECURITY, Category.BOUNDARY_CONDITION, Category.ERROR_HANDLING,
                Category.LOGIC_DEFECT, Category.MAINTAINABILITY, Category.REQUIREMENT_MISMATCH]


# ---------------------------------------------------------------------------- prompts


def available_multi_versions() -> list[str]:
    root = resources.files("code_review_agent").joinpath("prompts")
    return sorted(p.name for p in root.iterdir() if p.is_dir() and p.joinpath("common.md").is_file())


def load_pass_system(version: str, name: str) -> str:
    """System prompt of one pass: shared rules + the pass's focus + the JSON Schema of its output."""
    if version not in available_multi_versions():
        raise ValueError(f"Unknown multi-pass prompt version '{version}'. Available: {', '.join(available_multi_versions())}")
    if name not in PASS_MODELS:
        raise ValueError(f"Unknown pass '{name}'. Available: {', '.join(PASS_MODELS)}")
    base = resources.files("code_review_agent").joinpath("prompts", version)
    common = base.joinpath("common.md").read_text(encoding="utf-8").rstrip()
    focus = base.joinpath(f"{name}.md").read_text(encoding="utf-8").rstrip()
    schema = json.dumps(_schema_for(name), indent=1)
    return (
        f"{common}\n\n{focus}\n\n## Output format\n\n"
        "Reply with a single JSON object and nothing else (no Markdown fences, no commentary). "
        f"It must follow this JSON Schema:\n```json\n{schema}\n```\n"
    )


def render_candidates(findings: list[Finding]) -> str:
    """The numbered candidate list shown to the verifier (one compact entry per finding)."""
    entries = []
    for i, f in enumerate(findings, 1):
        where = f"{f.file}:{f.line}" if f.line else f.file
        claim = " ".join(f.explanation.split())
        quotes = "; ".join(f'{e.source}: "{" ".join(e.quote.split())}"' for e in f.evidence)
        entries.append(f"{i}. [{f.severity}] {f.category} at {where}: {' '.join(f.title.split())}\n"
                       f"   Claim: {claim}\n   Evidence: {quotes}")
    return "\n".join(entries)


# ------------------------------------------------------------------------ assembling


@dataclass
class _Prepared:
    """State after the specialist passes, before verification."""

    candidates: list[Finding] = field(default_factory=list)
    verifiable: list[Finding] = field(default_factory=list)  # the model-only candidates: the verifier's list
    criteria: list[CriterionCheck] = field(default_factory=list)
    summaries: list[PassSummary] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    problems: list[ValidationProblem] = field(default_factory=list)  # not tied to a final finding
    omitted: list[str] = field(default_factory=list)  # what is missing because a pass failed
    merged_away: int = 0
    errors: list[ReviewFailure] = field(default_factory=list)


def _short(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _finding_from_criterion(check: CriterionCheck) -> Finding:
    evidence = list(check.evidence) or [Evidence(source="ticket", quote=check.text)]
    return Finding(
        category=Category.REQUIREMENT_MISMATCH,
        severity=check.severity,
        file=check.file or WHOLE_CHANGE,
        line=check.line if check.file else None,
        title=_short(f"Criterion {check.number} not met: {check.text}", 120),
        explanation=check.explanation,
        evidence=evidence,
        found_by=["compliance"],
    )


def _same_issue(a: Finding, b: Finding) -> bool:
    if a.file != b.file or a.file == WHOLE_CHANGE:
        return False
    same_place = a.line is not None and a.line == b.line
    compatible = a.category == b.category or Category.REQUIREMENT_MISMATCH in (a.category, b.category)
    if same_place and compatible:
        return True
    return a.category == b.category and _norm(a.title) == _norm(b.title)


def _norm(title: str) -> str:
    return " ".join("".join(c if c.isalnum() else " " for c in title.lower()).split())


def merge_candidates(findings: list[Finding]) -> tuple[list[Finding], int]:
    """Fold reports of the same issue into one finding; order by severity.

    Two reports are the same issue when they cite the same file and line (and their categories are
    compatible: equal, or one is the generic requirement_mismatch), or share file, category and title.
    The merged finding keeps the more specific category, the higher severity, all evidence, and
    remembers every pass that reported it.
    """
    merged: list[Finding] = []
    for f in findings:
        for i, g in enumerate(merged):
            if not _same_issue(g, f):
                continue
            primary, other = (g, f) if _SPECIFICITY.index(g.category) <= _SPECIFICITY.index(f.category) else (f, g)
            seen = {(e.source, e.quote) for e in primary.evidence}
            evidence = list(primary.evidence) + [e for e in other.evidence if (e.source, e.quote) not in seen]
            merged[i] = primary.model_copy(update={
                "severity": min(g.severity, f.severity, key=_SEVERITY_RANK.__getitem__),
                "evidence": evidence,
                "found_by": list(dict.fromkeys([*g.found_by, *f.found_by])),
                "source": "tool" if "tool" in (g.source, f.source) else "llm",  # one tool report makes it tool-backed
            })
            break
        else:
            merged.append(f)
    order = sorted(range(len(merged)), key=lambda i: (_SEVERITY_RANK[merged[i].severity], i))
    return [merged[i] for i in order], len(findings) - len(merged)


def _criteria_checks(ticket: Ticket | None, verdicts: list[CriterionVerdict], out: _Prepared) -> list[CriterionCheck]:
    criteria = ticket.acceptance_criteria if ticket else []
    by_number: dict[int, CriterionVerdict] = {}
    for v in verdicts:
        if not 1 <= v.number <= len(criteria):
            out.problems.append(ValidationProblem(
                kind=ProblemKind.UNKNOWN_CRITERION,
                message=f"The compliance pass gave a verdict for criterion {v.number}, but the ticket has {len(criteria)}; it was ignored."))
        else:
            by_number.setdefault(v.number, v)  # the first verdict for a criterion wins
    checks = []
    for n, text in enumerate(criteria, 1):
        v = by_number.get(n)
        if v is None:
            checks.append(CriterionCheck(number=n, text=text, verdict="cannot_determine",
                                         explanation="The compliance pass gave no verdict for this criterion."))
            out.problems.append(ValidationProblem(
                criterion_index=n - 1, kind=ProblemKind.MISSING_VERDICT,
                message=f"No verdict was given for criterion {n}; it is shown as cannot determine."))
        else:
            checks.append(CriterionCheck(number=n, text=text, verdict=v.verdict, explanation=v.explanation,
                                         evidence=v.evidence, file=v.file, line=v.line, severity=v.severity))
    return checks


def _prepare(record: RunRecord, ticket: Ticket | None, review_input: ReviewInput) -> _Prepared:
    """Parse every specialist pass and build the merged candidate list (verify pass excluded)."""
    out = _Prepared()
    # Static-analysis warnings on lines the PR changed are findings from the start (deterministic).
    raw_candidates: list[Finding] = tool_findings_to_findings(record.tool_findings)
    _, left_out = select_reportable(record.tool_findings)
    if left_out:
        out.omitted.append(f"{left_out} further static-analysis warning(s) on changed lines were not reported "
                           f"(the most serious {MAX_REPORTED_FINDINGS} are shown)")
    for p in record.passes:
        if p.name == "verify":
            continue
        if p.skipped:
            out.summaries.append(PassSummary(name=p.name, status="skipped", message=p.skipped))
            continue
        model_name = p.settings.model
        if p.error is not None:
            out.errors.append(p.error)
            out.summaries.append(PassSummary(name=p.name, status="failed", model=model_name, message=f"{p.error.kind}: {p.error.message}",
                                             duration_s=p.wall_clock_s))
            out.omitted.append(f"specialist pass '{p.name}' failed ({p.error.kind}); its findings are missing")
            continue
        try:
            parsed, warnings = parse_json_output(p.raw_response or "", PASS_MODELS[p.name], p.done_reason)
        except InvalidOutput as exc:
            out.errors.append(ReviewFailure(kind=FailureKind.INVALID_OUTPUT, message=f"{p.name}: {exc}"))
            out.summaries.append(PassSummary(name=p.name, status="failed", model=model_name, message=f"invalid output: {exc}",
                                             duration_s=p.wall_clock_s, prompt_tokens=p.prompt_tokens,
                                             completion_tokens=p.completion_tokens))
            out.omitted.append(f"specialist pass '{p.name}' returned unusable output; its findings are missing")
            continue
        for w in warnings:
            if w.message.startswith(DROPPED):  # malformed items we discarded: lost coverage, said out loud
                out.omitted.append(f"specialist pass '{p.name}': {w.message}")
            else:
                out.problems.append(w)
        contributed: list[Finding] = []
        if isinstance(parsed, ComplianceReview):
            out.criteria = _criteria_checks(ticket, parsed.criteria, out)
            contributed += [f.model_copy(update={"found_by": [p.name]}) for f in parsed.scope_findings]
            contributed += [_finding_from_criterion(c) for c in out.criteria if c.verdict == "not_met"]
        else:
            contributed += [f.model_copy(update={"found_by": [p.name]}) for f in parsed.findings]
        raw_candidates += contributed
        for text in parsed.limitations:
            if text not in out.limitations:
                out.limitations.append(text)
        out.summaries.append(PassSummary(name=p.name, status="ok", model=model_name, findings=len(contributed),
                                         duration_s=p.wall_clock_s, prompt_tokens=p.prompt_tokens,
                                         completion_tokens=p.completion_tokens))
    out.candidates, out.merged_away = merge_candidates(raw_candidates)
    out.verifiable = [f for f in out.candidates if f.source == "llm"]  # a tool-backed finding is not up for a vote
    return out


def _apply_verification(
    prepared: _Prepared, verify: PassRecord | None
) -> tuple[list[Finding], list[DismissedFinding], PassSummary | None, list[ValidationProblem], list[str]]:
    """Apply the verifier's verdicts. Returns kept findings, dismissed ones, a summary, problems, omissions."""
    candidates = prepared.candidates
    if verify is None:
        return candidates, [], None, [], []
    if verify.skipped:
        return candidates, [], PassSummary(name="verify", status="skipped", message=verify.skipped), [], []
    summary = PassSummary(name="verify", status="ok", model=verify.settings.model, duration_s=verify.wall_clock_s,
                          prompt_tokens=verify.prompt_tokens, completion_tokens=verify.completion_tokens)
    if verify.error is not None:
        summary.status, summary.message = "failed", f"{verify.error.kind}: {verify.error.message}"
        return candidates, [], summary, [], ["verification failed; the findings below were NOT double-checked"]
    try:
        parsed, warnings = parse_json_output(verify.raw_response or "", VerifyReview, verify.done_reason)
    except InvalidOutput as exc:
        summary.status, summary.message = "failed", f"invalid output: {exc}"
        return candidates, [], summary, [], ["verification returned unusable output; the findings below were NOT double-checked"]

    problems = list(warnings)  # includes any verdicts the parser had to drop: shown as notes
    verdicts: dict[int, object] = {}
    for v in parsed.verdicts:
        if not 1 <= v.index <= len(prepared.verifiable):
            problems.append(ValidationProblem(kind=ProblemKind.FORMAT_WARNING,
                                              message=f"The verifier judged candidate {v.index}, which does not exist; ignored."))
        else:
            verdicts.setdefault(v.index, v)
    kept: list[Finding] = []
    dismissed: list[DismissedFinding] = []
    i = 0  # the verifier's numbering counts only the model's own candidates
    for f in candidates:
        if f.source == "tool":
            kept.append(f)  # confirmed by a static-analysis tool: not put to a vote
            continue
        i += 1
        v = verdicts.get(i)
        if v is None:
            kept.append(f.model_copy(update={"verification_note": "The verifier gave no verdict on this finding."}))
            problems.append(ValidationProblem(kind=ProblemKind.FORMAT_WARNING,
                                              message=f"The verifier gave no verdict on candidate {i} ('{_short(f.title, 60)}'); it is kept, unverified."))
        elif v.verdict == "unsupported":
            dismissed.append(DismissedFinding(finding=f, reason=v.reason))
        else:
            kept.append(f.model_copy(update={"verification": v.verdict, "verification_note": v.reason}))
    summary.findings = len(dismissed)  # for the verifier: how many it dismissed
    return kept, dismissed, summary, problems, []


def assemble_multi(record: RunRecord, ticket: Ticket | None, review_input: ReviewInput) -> ReviewResult:
    """Build the final ReviewResult from a multi-pass run record. Pure and deterministic."""
    run = RunSummary(
        revision=record.revision, case_id=record.case_id, created_at=record.created_at,
        prompt_version=record.prompt_version, model=record.settings.model, host=record.settings.host,
        duration_s=record.duration_s, prompt_tokens=record.prompt_tokens, completion_tokens=record.completion_tokens,
        ticket=f"{ticket.key}: {ticket.title}" if ticket else None,
    )
    prepared = _prepare(record, ticket, review_input)
    verify_record = next((p for p in record.passes if p.name == "verify"), None)
    kept, dismissed, verify_summary, verify_problems, verify_omitted = _apply_verification(prepared, verify_record)

    summaries = prepared.summaries + ([verify_summary] if verify_summary else [])
    omitted = prepared.omitted + verify_omitted + [
        f"static-analysis tool '{t.name}' failed ({t.message}); its findings are missing"
        for t in record.tool_runs if t.status == "failed"
    ]
    coverage = Coverage(complete=record.coverage.complete and not omitted, omitted=[*record.coverage.omitted, *omitted])
    common = {"run": run, "coverage": coverage, "missing_inputs": record.missing_inputs,
              "pipeline": "multi", "passes": summaries, "tools": record.tool_runs,
              "change_profile": compute_profile(review_input)}

    attempted = [s for s in prepared.summaries if s.status != "skipped"]
    # Every model pass failed AND no tool produced a finding: nothing can be concluded. (If a tool did
    # find something, that deterministic result is still worth reporting, with the gap made visible.)
    if attempted and all(s.status == "failed" for s in attempted) and not prepared.candidates:
        kind = next((e.kind for e in prepared.errors if e.kind != FailureKind.INVALID_OUTPUT),
                    FailureKind.INVALID_OUTPUT)
        detail = "; ".join(f"{s.name}: {s.message}" for s in attempted)
        return ReviewResult(status="failed", error=ReviewFailure(kind=kind, message=f"All specialist passes failed. {detail}"),
                            **common)

    grounding = check_grounding(kept, ticket, review_input)
    criteria_problems = check_criteria(prepared.criteria, ticket, review_input)
    # check_criteria numbers rows by list position, which is the same as the position kept in `criteria`
    problems = prepared.problems + verify_problems + grounding + criteria_problems
    return ReviewResult(
        status="completed", findings=kept, limitations=prepared.limitations, problems=problems,
        duplicates_removed=prepared.merged_away, criteria=prepared.criteria, dismissed=dismissed, **common,
    )


# ------------------------------------------------------------------------- context text


def shared_blocks(record: RunRecord, review_input: ReviewInput) -> dict[str, str]:
    """Extra fenced blocks every pass receives: the tools' leads, and the team's rules (when there are any)."""
    blocks: dict[str, str] = {}
    if record.tool_runs:
        blocks["STATIC ANALYSIS RESULTS"] = render_leads(record.tool_findings, record.tool_runs)
    if review_input.rules and review_input.rules.strip():
        source = f"(from {review_input.rules_source})\n" if review_input.rules_source else ""
        blocks["TEAM RULES"] = source + review_input.rules.strip()
    return blocks


def verify_user_message(ticket: Ticket | None, review_input: ReviewInput, max_chars: int,
                        candidates: list[Finding], blocks: dict[str, str] | None = None) -> str:
    user, _, _ = build_user_message(ticket, review_input, max_chars,
                                    extra_blocks={**(blocks or {}), "CANDIDATE FINDINGS": render_candidates(candidates)})
    return user


def multi_context_text(record: RunRecord, ticket: Ticket | None, review_input: ReviewInput) -> str:
    """Everything the model was shown, as saved in context.txt. A pure function of record + inputs."""
    blocks = shared_blocks(record, review_input)
    user, _, _ = build_user_message(ticket, review_input, record.max_chars, extra_blocks=blocks)
    parts = [f"=== PIPELINE multi ({record.prompt_version}) ===",
             "=== USER MESSAGE (shared by the specialist passes) ===", user]
    for p in record.passes:
        if p.name != "verify" and not p.skipped:
            parts += [f"=== SYSTEM MESSAGE: {p.name} ===", load_pass_system(p.prompt_version, p.name)]
    verify = next((p for p in record.passes if p.name == "verify" and not p.skipped), None)
    if verify is not None:
        candidates = _prepare(record, ticket, review_input).verifiable
        parts += ["=== SYSTEM MESSAGE: verify ===", load_pass_system(verify.prompt_version, "verify"),
                  "=== USER MESSAGE: verify ===",
                  verify_user_message(ticket, review_input, record.max_chars, candidates, blocks)]
    return "\n".join(parts) + "\n"


# ------------------------------------------------------------------------------ running


@dataclass
class _BlockSource:
    """The two fields of a run record that `shared_blocks` reads, before the record exists."""

    tool_findings: list
    tool_runs: list


def _peek(name: str, raw: str | None, done_reason: str | None) -> tuple[int | None, str | None]:
    """For the live event: how many candidates the answer holds, or why it is unusable."""
    try:
        parsed, _ = parse_json_output(raw or "", PASS_MODELS[name], done_reason)
    except InvalidOutput as exc:
        return None, str(exc)
    if isinstance(parsed, ComplianceReview):
        return sum(c.verdict == "not_met" for c in parsed.criteria) + len(parsed.scope_findings), None
    if isinstance(parsed, VerifyReview):
        return sum(v.verdict == "unsupported" for v in parsed.verdicts), None
    return len(parsed.findings), None


def _call_pass(name: str, client: ModelClient, system: str, user: str, version: str, events: EventLog) -> PassRecord:
    s = client.settings
    stage = f"pass:{name}"
    record = PassRecord(name=name, prompt_version=version, settings=s)
    events.emit(stage, f"{name}: asking {s.model}", status="start", model=s.model)
    started = time.monotonic()
    try:
        response = client.complete(system, user, schema=_schema_for(name))
    except ModelError as exc:
        record.error = ReviewFailure(kind=exc.kind, message=exc.message)
    else:
        record.raw_response = response.text
        record.duration_s = response.duration_s
        record.prompt_tokens, record.completion_tokens = response.prompt_tokens, response.completion_tokens
        record.done_reason = response.done_reason
    record.wall_clock_s = round(time.monotonic() - started, 2)
    if record.error:
        events.emit(stage, f"{name}: {record.error.kind}: {record.error.message}", status="error",
                    seconds=record.wall_clock_s, model=s.model)
        return record
    count, problem = _peek(name, record.raw_response, record.done_reason)
    if problem:
        events.emit(stage, f"{name}: the answer is unusable ({problem})", status="warn", seconds=record.wall_clock_s,
                    model=s.model, prompt_tokens=record.prompt_tokens, completion_tokens=record.completion_tokens)
    else:
        what = "dismissed" if name == "verify" else "candidate finding(s)"
        events.emit(stage, f"{name}: {count} {what}", status="done", seconds=record.wall_clock_s, model=s.model,
                    prompt_tokens=record.prompt_tokens, completion_tokens=record.completion_tokens, count=count)
    return record


def run_multi(
    case_id: str,
    ticket: Ticket | None,
    review_input: ReviewInput,
    client: ModelClient,
    max_chars: int = DEFAULT_MAX_CHARS,
    prompt_version: str = MULTI_PROMPT_VERSION,
    passes: tuple[str, ...] | list[str] | None = None,
    verify: bool = True,
    verifier_client: ModelClient | None = None,
    events: EventLog | None = None,
    tools: tuple[str, ...] | list[str] = DEFAULT_TOOLS,
    ruff_select: str = RUFF_SELECT,
) -> tuple[RunRecord, str]:
    """Static analysis, then the specialist passes (in parallel up to the provider's limit), then the verifier.

    Returns the run record (with every raw answer) and the exact context text that was sent.
    """
    events = events or EventLog()
    names = list(passes or DEFAULT_PASSES)
    unknown = [n for n in names if n not in DEFAULT_PASSES]
    if unknown:
        raise ValueError(f"Unknown pass(es) {unknown}. Choose from: {', '.join(DEFAULT_PASSES)}")

    tool_findings, tool_runs = [], []
    if tools:
        with events.step("static_analysis", f"Running static analysis ({', '.join(tools)})") as info:
            tool_findings, tool_runs = run_static_analysis(review_input, tools, ruff_select)
            info.update(tools={t.name: t.status for t in tool_runs}, warnings=len(tool_findings),
                        on_changed_lines=sum(f.on_changed_line for f in tool_findings))
        for t in tool_runs:
            if t.status != "ok":
                events.emit("static_analysis", f"{t.name}: {t.status}, {t.message}", status="warn")

    # A throw-away record only to build the shared blocks; the real one is created below.
    shared = shared_blocks(_BlockSource(tool_findings, tool_runs), review_input)
    with events.step("build_context", "Assembling the review context") as info:
        user, missing, coverage = build_user_message(ticket, review_input, max_chars, extra_blocks=shared)
        info.update(prompt_version=prompt_version, characters=len(user), passes=names,
                    missing_inputs=len(missing), omitted=len(coverage.omitted), ticket=ticket.key if ticket else None,
                    blocks=list(shared))

    plan: list[tuple[str, str | None]] = []  # (pass name, reason to skip)
    for name in names:
        reason = None
        if name == "compliance" and (ticket is None or not ticket.acceptance_criteria):
            reason = "no ticket was provided" if ticket is None else f"ticket {ticket.key} has no acceptance criteria to check"
        if name == "standards" and not (review_input.rules and review_input.rules.strip()):
            reason = "no team rules were provided (add .review-agent/rules.md to the base branch, or use --rules)"
        plan.append((name, reason))

    started = time.monotonic()
    runnable = [(n, load_pass_system(prompt_version, n)) for n, reason in plan if reason is None]
    workers = max(1, min(client.settings.max_concurrency, len(runnable)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        done = dict(zip([n for n, _ in runnable],
                        pool.map(lambda item: _call_pass(item[0], client, item[1], user, prompt_version, events), runnable),
                        strict=True))
    records: list[PassRecord] = []
    for name, reason in plan:
        if reason is not None:
            events.emit(f"pass:{name}", f"{name}: skipped, {reason}", status="warn")
            records.append(PassRecord(name=name, prompt_version=prompt_version, settings=client.settings, skipped=reason))
        else:
            records.append(done[name])

    pr = review_input.pr
    record = RunRecord(
        case_id=case_id, created_at=datetime.now(UTC).isoformat(timespec="seconds"), prompt_version=prompt_version,
        settings=client.settings, max_chars=max_chars, pipeline="multi", passes=records,
        revision=ReviewedRevision(repository=pr.repository, pr_number=pr.number, url=pr.url,
                                  base_sha=pr.base_sha, head_sha=pr.head_sha) if pr.head_sha else None,
        coverage=coverage, missing_inputs=missing, tool_findings=tool_findings, tool_runs=tool_runs,
    )

    if verify:
        with events.step("merge", "Merging the specialists' findings") as info:
            prepared = _prepare(record, ticket, review_input)
            info.update(candidates=len(prepared.candidates), tool_backed=len(prepared.candidates) - len(prepared.verifiable),
                        merged_duplicates=prepared.merged_away)
        vclient = verifier_client or client
        if prepared.verifiable:
            system = load_pass_system(prompt_version, "verify")
            vuser = verify_user_message(ticket, review_input, max_chars, prepared.verifiable, shared)
            record.passes.append(_call_pass("verify", vclient, system, vuser, prompt_version, events))
        else:
            reason = "no model-reported candidate findings to verify"
            events.emit("pass:verify", f"verify: skipped, {reason}", status="warn")
            record.passes.append(PassRecord(name="verify", prompt_version=prompt_version, settings=vclient.settings, skipped=reason))

    # Totals over all passes, so evaluation and the report can treat both pipelines alike.
    record.duration_s = round(sum(p.duration_s or 0 for p in record.passes), 3) if any(p.duration_s for p in record.passes) else None
    record.wall_clock_s = round(time.monotonic() - started, 2)
    record.prompt_tokens = sum(p.prompt_tokens or 0 for p in record.passes) or None
    record.completion_tokens = sum(p.completion_tokens or 0 for p in record.passes) or None
    return record, multi_context_text(record, ticket, review_input)
