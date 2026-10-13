"""Read example folders and expected answers from disk into validated models."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime
from pathlib import Path

from .schemas import ExpectedReview, PullRequestMetadata, ReviewInput, SupportingFile, Ticket


def load_example(folder: Path) -> tuple[Ticket | None, ReviewInput]:
    """Load one example folder.

    Expected files: pr.json, change.diff.
    Optional: ticket.json (None if absent: a review without a ticket is allowed,
    the context builder will say so), supporting/ directory (supporting code).
    Pydantic raises ValidationError if a file does not match the schema.
    """
    ticket_path = folder / "ticket.json"
    ticket = (
        Ticket.model_validate_json(ticket_path.read_text(encoding="utf-8"))
        if ticket_path.exists()
        else None
    )
    pr = PullRequestMetadata.model_validate_json((folder / "pr.json").read_text(encoding="utf-8"))
    diff = (folder / "change.diff").read_text(encoding="utf-8")

    supporting = _read_files(folder / "supporting")  # shown to the model
    analysis = _read_files(folder / "analysis")  # full changed files, for the static-analysis tools only

    notes: list[str] = []
    rules: str | None = None
    rules_source: str | None = None
    source_path = folder / "source.json"  # written by `fetch-pr`: what could not be retrieved
    if source_path.exists():
        source = json.loads(source_path.read_text(encoding="utf-8"))
        notes = list(source.get("notes", []))
        rules_source = source.get("rules_source")
    rules_path = folder / "rules.md"  # team coding rules (for a PR: read from the base branch)
    if rules_path.exists():
        rules = rules_path.read_text(encoding="utf-8")
        rules_source = rules_source or "rules.md"

    return ticket, ReviewInput(
        pr=pr, diff=diff, supporting_files=supporting, input_notes=notes,
        analysis_files=analysis, rules=rules, rules_source=rules_source,
    )


def _read_files(directory: Path) -> list[SupportingFile]:
    if not directory.is_dir():
        return []
    return [
        SupportingFile(path=p.relative_to(directory).as_posix(), content=p.read_text(encoding="utf-8"))
        for p in sorted(p for p in directory.rglob("*") if p.is_file())
    ]


def _write_files(folder: Path, name: str, files) -> None:
    for sf in files:
        target = folder / name / sf.path
        # Paths come from an untrusted pull request: never write outside the snapshot folder.
        if not target.resolve().is_relative_to((folder / name).resolve()):
            raise ValueError(f"Refusing to write outside the snapshot folder: {sf.path!r}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(sf.content, encoding="utf-8")


def save_snapshot(snapshot, folder: Path) -> None:
    """Write a fetched pull request as an example folder (pr.json, change.diff, supporting/, analysis/,
    rules.md, source.json)."""
    folder.mkdir(parents=True, exist_ok=True)
    # Start clean. The folder is named after the reviewed commit, so a second fetch of the same PR reuses it:
    # leftovers from the first fetch (a ticket, rules, files) must never be mistaken for this fetch's result.
    for name in ("pr.json", "change.diff", "source.json", "ticket.json", "rules.md"):
        (folder / name).unlink(missing_ok=True)
    for name in ("supporting", "analysis"):
        shutil.rmtree(folder / name, ignore_errors=True)
    (folder / "pr.json").write_text(snapshot.metadata.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")
    (folder / "change.diff").write_text(snapshot.diff, encoding="utf-8")
    _write_files(folder, "supporting", snapshot.supporting_files)
    _write_files(folder, "analysis", getattr(snapshot, "analysis_files", []))
    if getattr(snapshot, "rules", None):
        (folder / "rules.md").write_text(snapshot.rules, encoding="utf-8")
    (folder / "source.json").write_text(
        json.dumps({"fetched_at": datetime.now(UTC).isoformat(timespec="seconds"), "notes": snapshot.notes,
                    "rules_source": getattr(snapshot, "rules_source", None)}, indent=2),
        encoding="utf-8",
    )


def load_expected(path: Path) -> ExpectedReview:
    return ExpectedReview.model_validate_json(path.read_text(encoding="utf-8"))
