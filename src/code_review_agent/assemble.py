"""Assembling the final `ReviewResult` from a recorded multi-pass run.

`assemble_multi` is a pure, deterministic function of the run record and the inputs: it parses every pass, merges the
candidates, applies the verifier's verdicts, checks grounding and consistency, and reports what is missing. A saved run can
therefore be re-validated later without calling any model, and it is tested without one. `multi_context_text` rebuilds, from the
same record, the exact text that was sent to the model (`context.txt`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .blocks import context_summary, shared_blocks, verify_user_message
from .consistency import check_consistency
from .context import build_user_message
from .evidence import (
    MAX_REPORTED_FINDINGS,
    compute_profile,
    select_reportable,
    tool_findings_to_findings,
)
from .merge import merge_candidates
from .passes import PASS_MODELS, load_pass_system
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
    PassSummary,
    ProblemKind,
    ReviewFailure,
    ReviewInput,
    ReviewResult,
    RunSummary,
    Ticket,
    ValidationProblem,
    VerifyReview,
)
from .textutil import short
from .validation import (
    DROPPED,
    InvalidOutput,
    check_criteria,
    check_grounding,
    parse_json_output,
)


@dataclass
class Prepared:
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


def _finding_from_criterion(check: CriterionCheck) -> Finding:
    evidence = list(check.evidence) or [Evidence(source="ticket", quote=check.text)]
    return Finding(
        category=Category.REQUIREMENT_MISMATCH,
        severity=check.severity,
        file=check.file or WHOLE_CHANGE,
        line=check.line if check.file else None,
        title=short(f"Criterion {check.number} not met: {check.text}", 120),
        explanation=check.explanation,
        evidence=evidence,
        found_by=["compliance"],
    )


def _criteria_checks(ticket: Ticket | None, verdicts: list[CriterionVerdict], out: Prepared) -> list[CriterionCheck]:
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


def prepare_candidates(record: RunRecord, ticket: Ticket | None, review_input: ReviewInput) -> Prepared:
    """Parse every specialist pass and build the merged candidate list (verify pass excluded)."""
    out = Prepared()
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
    prepared: Prepared, verify: PassRecord | None
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
                                              message=f"The verifier gave no verdict on candidate {i} ('{short(f.title, 60)}'); it is kept, unverified."))
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
    prepared = prepare_candidates(record, ticket, review_input)
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
              "change_profile": compute_profile(review_input), "context": context_summary(review_input)}

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
    consistency = check_consistency(prepared.criteria, kept)
    problems = prepared.problems + verify_problems + grounding + criteria_problems + consistency
    return ReviewResult(
        status="completed", findings=kept, limitations=prepared.limitations, problems=problems,
        duplicates_removed=prepared.merged_away, criteria=prepared.criteria, dismissed=dismissed, **common,
    )


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
        candidates = prepare_candidates(record, ticket, review_input).verifiable
        parts += ["=== SYSTEM MESSAGE: verify ===", load_pass_system(verify.prompt_version, "verify"),
                  "=== USER MESSAGE: verify ===",
                  verify_user_message(ticket, review_input, record.max_chars, candidates, blocks)]
    return "\n".join(parts) + "\n"
