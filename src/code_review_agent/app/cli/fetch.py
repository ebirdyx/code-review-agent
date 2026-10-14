"""fetch-ticket and fetch-pr: read a Jira ticket or a GitHub pull request (read-only) and save it."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from pydantic import ValidationError

from ...connectors.github import GitHubError
from ...connectors.jira import FIELD_ENV, JiraError
from ...events import EventLog, echo_to_stderr
from .. import clients
from ..service import PRFetchOptions, fetch_snapshot
from .options import add_pr_args


def fetch_pr_snapshot(args: argparse.Namespace, events: EventLog | None = None) -> Path | None:
    """Download a PR (read-only) and save it as an example folder. Returns the folder."""
    try:
        options = PRFetchOptions.from_cli(
            jira=args.jira, jira_projects=args.jira_projects, ticket_keys=args.ticket_key,
            ticket_file=args.ticket, max_files=args.max_files, no_source=args.no_source,
            no_tools=getattr(args, "no_tools", False), no_context=getattr(args, "no_context", False),
        )
        # The lambdas look the classes up when called, so tests can substitute them on this module.
        folder, snapshot = fetch_snapshot(
            args.pr, args.snapshots, options,
            github=lambda: clients.github_client(), jira=lambda: clients.jira_client(),
            events=events or EventLog(echo=echo_to_stderr),
        )
        meta = snapshot.metadata
        repository, number = meta.repository, meta.number
    except (GitHubError, JiraError, OSError, ValidationError, ValueError) as exc:
        print(f"Cannot fetch the pull request: {exc}", file=sys.stderr)
        return None
    print(f"Fetched {repository}#{number}: head {meta.head_sha}, base {meta.base_sha}")
    print(f"  {snapshot.diff.count('diff --git')} file diff(s), {len(snapshot.supporting_files)} source file(s) -> {folder}")
    for line in snapshot.info:
        print(f"  info: {line}")
    for note in snapshot.notes:
        print(f"  not retrieved: {note}")
    return folder


def fetch_ticket_command(args: argparse.Namespace) -> int:
    """Check the Jira setup: fetch one ticket and show what was understood."""
    try:
        issue = clients.jira_client().fetch_issue(args.key)
    except JiraError as exc:
        print(f"Cannot fetch the ticket: {exc}", file=sys.stderr)
        return 1
    t = issue.ticket
    print(f"{t.key}: {t.title}")
    print(f"  description: {len(t.description)} characters")
    print(f"  acceptance criteria: {len(t.acceptance_criteria)} (from {issue.criteria_source})")
    for i, c in enumerate(t.acceptance_criteria, 1):
        print(f"    {i}. {c}")
    if not t.acceptance_criteria:
        print("  warning: no acceptance criteria found; reviews will say the requirements are incomplete.")
        print(f"  hint: set {FIELD_ENV} to the field id or name that holds them.")
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(t.model_dump_json(indent=2), encoding="utf-8")
        print(f"  saved to {args.out}")
    return 0


def fetch_pr_command(args: argparse.Namespace) -> int:
    return 0 if fetch_pr_snapshot(args) else 1



def register(sub: argparse._SubParsersAction) -> None:
    """Add this group's subcommands to the parser."""
    ftk = sub.add_parser("fetch-ticket", help="fetch one Jira ticket (checks your Jira setup)")
    ftk.add_argument("key", help="Jira issue key, e.g. SHOP-42")
    ftk.add_argument("--out", type=Path, help="save it as a ticket.json")
    ftk.set_defaults(handler=fetch_ticket_command)

    fpr = sub.add_parser("fetch-pr", help="download a GitHub pull request (read-only) as an example folder")
    add_pr_args(fpr)
    fpr.add_argument("--no-context", action="store_true", help="do not build the repository context (callers, callees, tests)")
    fpr.set_defaults(handler=fetch_pr_command)
