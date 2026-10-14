"""The single-pass pipeline: one prompt, one model call, the raw answer recorded.

This is the baseline the multi-pass pipeline is compared with (`--pipeline single`). It stops at the RAW output: parsing
and validating it is `validation.py`, so nothing here claims the answer is correct, or even valid JSON.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ..context.builder import DEFAULT_PROMPT_VERSION, build_context
from ..events import EventLog
from ..llm.client import ModelClient, ModelError
from ..schemas import ReviewedRevision, ReviewFailure, ReviewInput, Ticket
from .records import RunRecord, sent_text


def run_review(
    case_id: str,
    ticket: Ticket | None,
    review_input: ReviewInput,
    client: ModelClient,
    max_chars: int,
    prompt_version: str = DEFAULT_PROMPT_VERSION,
    events: EventLog | None = None,
) -> tuple[RunRecord, str]:
    """Returns the record and the exact context text that was sent."""
    events = events or EventLog()
    with events.step("build_context", "Assembling the review context") as info:
        context = build_context(ticket, review_input, max_chars=max_chars, prompt_version=prompt_version)
        info.update(
            prompt_version=context.prompt_version,
            characters=len(context.system) + len(context.user),
            missing_inputs=len(context.missing_inputs),
            omitted=len(context.coverage.omitted),
            ticket=ticket.key if ticket else None,
        )
    pr = review_input.pr
    record = RunRecord(
        case_id=case_id,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        prompt_version=context.prompt_version,
        settings=client.settings,
        max_chars=max_chars,
        revision=ReviewedRevision(
            repository=pr.repository, pr_number=pr.number, url=pr.url,
            base_sha=pr.base_sha, head_sha=pr.head_sha,
        ) if pr.head_sha else None,
        coverage=context.coverage,
        missing_inputs=context.missing_inputs,
    )
    sent = sent_text(context.system, context.user)

    s = client.settings
    events.emit("model_call", f"Asking {s.model}", status="start", model=s.model, host=s.host)
    started = datetime.now(UTC)
    try:
        response = client.complete(context.system, context.user)
    except ModelError as exc:
        record.error = ReviewFailure(kind=exc.kind, message=exc.message)
    else:
        record.raw_response = response.text
        record.duration_s = response.duration_s
        record.prompt_tokens = response.prompt_tokens
        record.completion_tokens = response.completion_tokens
        record.done_reason = response.done_reason
    record.wall_clock_s = round((datetime.now(UTC) - started).total_seconds(), 2)
    if record.error:
        events.emit("model_call", f"{record.error.kind}: {record.error.message}", status="error",
                    seconds=record.wall_clock_s, model=s.model)
    else:
        events.emit("model_call", f"{s.model} answered", status="done", seconds=record.wall_clock_s, model=s.model,
                    prompt_tokens=record.prompt_tokens, completion_tokens=record.completion_tokens,
                    done_reason=record.done_reason)
    return record, sent
