"""review and review-pr: run the review, write the report and (for review-pr) optionally publish the pull-request comment."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from ...connectors.github import GitHubError
from ...events import EventLog, echo_to_stderr
from ...llm.client import (
    ModelError,
)
from ...reporting.comment import MARKER, render_pr_comment
from ...schemas import (
    ReviewResult,
)
from .. import clients
from ..service import review_folder
from .fetch import fetch_pr_snapshot
from .options import add_model_args, add_pr_args, make_model_client, pipeline_kwargs


def _review(args: argparse.Namespace, events: EventLog | None = None) -> tuple[int, Path | None, ReviewResult | None]:
    """Run one review. Returns (exit code, run folder, result); folder and result are None if it never started."""
    events = events or EventLog(echo=echo_to_stderr)
    try:
        client = make_model_client(args)
    except ModelError as exc:
        print(f"[{exc.kind}] {exc.message}", file=sys.stderr)
        return 1, None, None

    s = client.settings
    print(f"Reviewing {args.example.name} with {s.model} at {s.host} ...")
    try:
        folder, result, report = review_folder(
            args.example, client=client, runs_dir=args.runs, max_chars=args.max_chars,
            events=events, **pipeline_kwargs(args),
        )
    except (OSError, ValidationError, ValueError) as exc:
        print(f"Cannot start review: {exc}", file=sys.stderr)
        return 1, None, None
    except ModelError as exc:
        print(f"[{exc.kind}] {exc.message}", file=sys.stderr)
        return 1, None, None
    print(report)
    answers = "passes/*.raw.txt" if result.pipeline == "multi" else "raw_response.txt"
    print(f"Saved in {folder}: run.json, context.txt, {answers}, result.json, report.md, events.jsonl")
    return (0 if result.status == "completed" else 2), folder, result


def review_command(args: argparse.Namespace, events: EventLog | None = None) -> int:
    """Send one example to the model, validate the answer and write a report."""
    return _review(args, events)[0]


def publish_comment(args: argparse.Namespace, folder: Path, result: ReviewResult) -> bool:
    """Write comment.md next to the report and, only with --post-comment, publish it on the pull request."""
    body = render_pr_comment(result, report_hint=args.report_link)
    (folder / "comment.md").write_text(body, encoding="utf-8")
    rev = result.run.revision if result.run else None
    if not args.post_comment:
        print(f"Pull-request comment written to {folder / 'comment.md'} (not posted: add --post-comment to publish it).")
        return True
    if not rev or not rev.repository or not rev.pr_number:
        print("Cannot post: the review does not identify a pull request.", file=sys.stderr)
        return False
    try:
        action, url = clients.github_client().upsert_comment(rev.repository, rev.pr_number, body, MARKER)
    except GitHubError as exc:
        print(f"Cannot post the comment: {exc}", file=sys.stderr)
        return False
    print(f"Comment {action} on {rev.repository}#{rev.pr_number}: {url}")
    return True


def review_pr_command(args: argparse.Namespace) -> int:
    events = EventLog(echo=echo_to_stderr)
    folder = fetch_pr_snapshot(args, events)
    if folder is None:
        return 1
    args.example = folder
    code, run_folder, result = _review(args, events)
    if result is not None and run_folder is not None and not publish_comment(args, run_folder, result):
        return 1
    # A failed review is still published (it says "did not run"), so a silent pipeline is never mistaken for a clean one.
    return code



def register(sub: argparse._SubParsersAction) -> None:
    """Add this group's subcommands to the parser."""
    rev = sub.add_parser("review", help="run a real model review on an example")
    rev.add_argument("example", type=Path)
    add_model_args(rev)
    rev.add_argument("--runs", type=Path, default=Path("runs"), help="where to save run folders")
    rev.set_defaults(handler=review_command)

    rpr = sub.add_parser("review-pr", help="download a GitHub pull request, then review it with the model")
    add_pr_args(rpr)
    add_model_args(rpr)
    rpr.add_argument("--runs", type=Path, default=Path("runs"), help="where to save run folders")
    rpr.add_argument("--post-comment", action="store_true",
                         help="publish the review as ONE comment on the pull request (updated on every run). "
                              "Needs GITHUB_TOKEN with write access to pull requests. Without this flag, comment.md is only written")
    rpr.add_argument("--report-link", help="address to mention in the comment as the place of the full report (e.g. the workflow run)")
    rpr.set_defaults(handler=review_pr_command)
