"""Run one review: build context, call the model, record everything.

Stage 3 stops at the RAW model output. Parsing and validating it is Stage 4, so
nothing here claims the output is correct, or even valid JSON.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from pydantic import Field

from .context import DEFAULT_PROMPT_VERSION, Coverage, build_context
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
) -> tuple[RunRecord, str]:
    """Returns the record and the exact context text that was sent."""
    context = build_context(ticket, review_input, max_chars=max_chars, prompt_version=prompt_version)
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
    return record, sent


def save_result(folder: Path, result_json: str, report_md: str) -> None:
    """Add the validated result and the readable report next to the run files."""
    (folder / "result.json").write_text(result_json, encoding="utf-8")
    (folder / "report.md").write_text(report_md, encoding="utf-8")


def save_run(record: RunRecord, sent_context: str, runs_dir: Path) -> Path:
    """Write run.json, context.txt and raw_response.txt into a new folder."""
    stamp = record.created_at.replace(":", "").replace("-", "").replace("+0000", "")[:15]
    folder = runs_dir / f"{record.case_id}-{stamp}"
    suffix = 1
    while folder.exists():  # never overwrite an earlier run made in the same second
        suffix += 1
        folder = runs_dir / f"{record.case_id}-{stamp}-{suffix}"
    folder.mkdir(parents=True)
    (folder / "run.json").write_text(record.model_dump_json(indent=2), encoding="utf-8")
    (folder / "context.txt").write_text(sent_context, encoding="utf-8")
    if record.raw_response is not None:
        (folder / "raw_response.txt").write_text(record.raw_response, encoding="utf-8")
    return folder
