"""Running the multi-pass review: static analysis, the specialist passes, then the verifier.

Why several passes? A small model does better on a narrow job than on "review everything":
  compliance  checks every acceptance criterion of the ticket, one verdict each (a checklist);
  defects     looks for logic, boundary, error-handling and maintainability problems;
  security    looks only for security weaknesses;
  standards   checks the changed lines against the team's rules;
  verify      gives every candidate finding a second, independent look and may dismiss it.

This module only CALLS the model (`run_multi`) and records each raw answer in `RunRecord.passes`. Everything that turns
those answers into a result lives elsewhere and needs no model: `passes` (prompts and schemas), `blocks` (what the model
is shown), `merge`, `consistency` and `assemble` (the final `ReviewResult`).

Honesty rules: a pass that fails or returns unusable output is reported (partial coverage), a finding the verifier
dismisses stays visible with the reason, and a criterion nobody judged is shown as "cannot determine".
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime

from .assemble import multi_context_text, prepare_candidates
from .blocks import shared_blocks, verify_user_message
from .context import DEFAULT_MAX_CHARS, build_user_message
from .events import EventLog
from .evidence import (
    DEFAULT_TOOLS,
    RUFF_SELECT,
    run_static_analysis,
)
from .model_client import ModelClient, ModelError
from .passes import (
    DEFAULT_PASSES,
    MULTI_PROMPT_VERSION,
    PASS_MODELS,
    load_pass_system,
    schema_for,
)
from .review import PassRecord, RunRecord
from .schemas import (
    ComplianceReview,
    ReviewedRevision,
    ReviewFailure,
    ReviewInput,
    Ticket,
    VerifyReview,
)
from .validation import InvalidOutput, parse_json_output


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
        response = client.complete(system, user, schema=schema_for(name))
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
            prepared = prepare_candidates(record, ticket, review_input)
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
