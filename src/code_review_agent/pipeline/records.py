"""What a run recorded, and where it is saved.

`RunRecord` keeps everything about one review (the exact context sent, every raw model answer, the settings, the
revision reviewed) so it can be re-validated later without calling a model. `save_run` and `save_result` write it to a
run folder.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import Field

from ..context.builder import Coverage
from ..llm.client import ModelSettings
from ..schemas import ReviewedRevision, ReviewFailure, StrictModel, ToolFinding, ToolRun


class PassRecord(StrictModel):
    """One specialist pass of the multi-pass pipeline (compliance, defects, security, verify)."""

    name: str
    prompt_version: str
    settings: ModelSettings
    skipped: str | None = None  # reason, when the pass was not run
    raw_response: str | None = None  # exactly what the model returned
    error: ReviewFailure | None = None  # set when the model call failed
    duration_s: float | None = None
    wall_clock_s: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    done_reason: str | None = None


class RunRecord(StrictModel):
    """Everything needed to understand (and rerun) one review attempt."""

    case_id: str
    created_at: str  # UTC, ISO 8601
    prompt_version: str
    settings: ModelSettings
    max_chars: int
    pipeline: Literal["single", "multi"] = "single"
    passes: list[PassRecord] = Field(default_factory=list)  # multi-pass pipeline only
    tool_runs: list[ToolRun] = Field(default_factory=list)  # static-analysis tools (multi-pass only)
    tool_findings: list[ToolFinding] = Field(default_factory=list)  # every warning they raised, changed line or not
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
    for p in record.passes:  # multi-pass: one raw answer per specialist, handy for debugging
        if p.raw_response is not None:
            (folder / "passes").mkdir(exist_ok=True)
            (folder / "passes" / f"{p.name}.raw.txt").write_text(p.raw_response, encoding="utf-8")
    return folder
