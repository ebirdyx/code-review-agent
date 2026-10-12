"""Read example folders and expected answers from disk into validated models."""

from __future__ import annotations

import json
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

    supporting: list[SupportingFile] = []
    supporting_dir = folder / "supporting"
    if supporting_dir.is_dir():
        for path in sorted(p for p in supporting_dir.rglob("*") if p.is_file()):
            relative = path.relative_to(supporting_dir).as_posix()
            supporting.append(
                SupportingFile(path=relative, content=path.read_text(encoding="utf-8"))
            )

    notes: list[str] = []
    source_path = folder / "source.json"  # written by `fetch-pr`: what could not be retrieved
    if source_path.exists():
        notes = list(json.loads(source_path.read_text(encoding="utf-8")).get("notes", []))

    return ticket, ReviewInput(pr=pr, diff=diff, supporting_files=supporting, input_notes=notes)


def save_snapshot(snapshot, folder: Path) -> None:
    """Write a fetched pull request as an example folder (pr.json, change.diff, supporting/, source.json)."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "pr.json").write_text(snapshot.metadata.model_dump_json(indent=2, exclude_none=True), encoding="utf-8")
    (folder / "change.diff").write_text(snapshot.diff, encoding="utf-8")
    for sf in snapshot.supporting_files:
        target = folder / "supporting" / sf.path
        # Paths come from an untrusted pull request: never write outside the snapshot folder.
        if not target.resolve().is_relative_to((folder / "supporting").resolve()):
            raise ValueError(f"Refusing to write outside the snapshot folder: {sf.path!r}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(sf.content, encoding="utf-8")
    (folder / "source.json").write_text(
        json.dumps({"fetched_at": datetime.now(UTC).isoformat(timespec="seconds"), "notes": snapshot.notes}, indent=2),
        encoding="utf-8",
    )


def load_expected(path: Path) -> ExpectedReview:
    return ExpectedReview.model_validate_json(path.read_text(encoding="utf-8"))
