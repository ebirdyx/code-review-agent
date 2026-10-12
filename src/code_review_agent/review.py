"""Run one review: build context, call the model, record everything.

Stage 3 stops at the RAW model output. Parsing and validating it is Stage 4, so
nothing here claims the output is correct, or even valid JSON.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import Field

from .context import DEFAULT_PROMPT_VERSION, Coverage, build_context
from .events import EventLog
from .model_client import ModelClient, ModelError, ModelSettings
from .schemas import ReviewedRevision, ReviewFailure, ReviewInput, StrictModel, Ticket


class RunRecord(StrictModel):
    """Everything needed to understand (and rerun) one review attempt."""

    case_id: str
    created_at: str  # UTC, ISO 8601
    prompt_version: str
    settings: ModelSettings
    max_chars: int
    revision: ReviewedRevision | None = None  # set for pull-request reviews
    coverage: Coverage
    missing_inputs: list[str] = Field(default_factory=list)
    duration_s: float | None = None  # model-reported total time
    wall_clock_s: float | None = None  # measured by us, includes network
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    done_reason: str | None = None
    raw_response: str | None = None  # exactly what the model returned
    error: ReviewFailure | None = None  # set when the model call failed


def sent_text(system: str, user: str) -> str:
    """The exact context saved as context.txt for every run."""
    return f"=== SYSTEM MESSAGE ===\n{system}\n=== USER MESSAGE ===\n{user}\n"


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


def save_result(folder: Path, result_json: str, report_md: str) -> None:
    """Add the validated result and the readable report next to the run files."""
    (folder / "result.json").write_text(result_json, encoding="utf-8")
    (folder / "report.md").write_text(report_md, encoding="utf-8")


def _create_unique_folder(runs_dir: Path, base: str) -> Path:
    """Atomically create `runs_dir/base`, or `base-2`, `base-3`... if taken (safe across threads)."""
    runs_dir.mkdir(parents=True, exist_ok=True)
    suffix = 1
    while True:
        folder = runs_dir / (base if suffix == 1 else f"{base}-{suffix}")
        try:
            folder.mkdir()  # fails if it exists: no check-then-create race
            return folder
        except FileExistsError:
            suffix += 1


def new_run_folder(runs_dir: Path, case_id: str) -> Path:
    """Create a fresh run folder (never reusing one made in the same second)."""
    return _create_unique_folder(runs_dir, f"{case_id}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%S')}")


def save_run(record: RunRecord, sent_context: str, runs_dir: Path, folder: Path | None = None) -> Path:
    """Write run.json, context.txt and raw_response.txt into `folder` (or a new run folder)."""
    if folder is None:
        stamp = record.created_at.replace(":", "").replace("-", "").replace("+0000", "")[:15]
        folder = _create_unique_folder(runs_dir, f"{record.case_id}-{stamp}")
    (folder / "run.json").write_text(record.model_dump_json(indent=2), encoding="utf-8")
    (folder / "context.txt").write_text(sent_context, encoding="utf-8")
    if record.raw_response is not None:
        (folder / "raw_response.txt").write_text(record.raw_response, encoding="utf-8")
    return folder
