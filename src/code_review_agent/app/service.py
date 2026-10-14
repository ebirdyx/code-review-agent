"""The review workflow as plain functions, shared by the command line and the web UI.

Nothing in here prints: progress goes to an `EventLog`, results come back as values,
and clients are passed in (so tests and the UI can substitute them).
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from ..connectors.github import GitHubClient, PullRequestSnapshot, parse_pr_reference
from ..connectors.jira import PROJECTS_ENV, JiraClient, resolve_ticket
from ..connectors.snapshot import load_example, save_snapshot
from ..context.builder import DEFAULT_PROMPT_VERSION
from ..context.evidence import DEFAULT_TOOLS, RUFF_SELECT
from ..events import EventLog
from ..llm.client import ModelClient
from ..pipeline.multi import run_multi
from ..pipeline.passes import MULTI_PROMPT_VERSION
from ..pipeline.records import RunRecord, new_run_folder, save_result, save_run
from ..pipeline.single import run_review
from ..pipeline.validation import finalize_review
from ..reporting.report import render_markdown
from ..schemas import ReviewInput, ReviewResult, Ticket


@dataclass
class PRFetchOptions:
    jira: bool = False
    jira_projects: list[str] = field(default_factory=list)
    ticket_keys: list[str] | None = None
    ticket_file: Path | None = None
    max_files: int = 100
    with_source: bool = True
    with_analysis: bool = True  # also download full changed Python files for the static-analysis tools
    with_rules: bool = True  # read team rules from the base commit
    with_context: bool = True  # build the code graph (callers, callees, tests) from one repository download

    @classmethod
    def from_cli(cls, jira=False, jira_projects: str | None = None, ticket_keys=None, ticket_file=None,
                 max_files=100, no_source=False, no_tools=False, no_context=False) -> PRFetchOptions:
        raw = jira_projects or os.environ.get(PROJECTS_ENV, "")
        return cls(
            jira=jira, jira_projects=[p.strip() for p in raw.split(",") if p.strip()],
            ticket_keys=ticket_keys, ticket_file=ticket_file, max_files=max_files, with_source=not no_source,
            with_analysis=not no_tools, with_context=not no_context,
        )


def fetch_snapshot(
    ref: str,
    snapshots_dir: Path,
    options: PRFetchOptions,
    *,
    github: Callable[[], GitHubClient] = GitHubClient,
    jira: Callable[[], JiraClient] = JiraClient,
    events: EventLog | None = None,
) -> tuple[Path, PullRequestSnapshot]:
    """Download a PR (and, if asked, its Jira ticket) into an example folder.

    Raises GitHubError, JiraError, OSError, ValidationError or ValueError with a message
    that says what to do.
    """
    events = events or EventLog()
    repository, number = parse_pr_reference(ref)
    ticket: Ticket | None = None
    if options.ticket_file:
        ticket = Ticket.model_validate_json(options.ticket_file.read_text(encoding="utf-8"))
    jira_client = jira() if (options.jira or options.ticket_keys) and not options.ticket_file else None

    with events.step("fetch_pr", f"Reading {repository}#{number} from GitHub", repository=repository, number=number) as info:
        snapshot = github().fetch_pull_request(
            repository, number, max_files=options.max_files, with_source=options.with_source,
            with_analysis=options.with_analysis, with_rules=options.with_rules, with_context=options.with_context,
        )
        meta = snapshot.metadata
        info.update(head_sha=meta.head_sha, files=snapshot.diff.count("diff --git"),
                    source_files=len(snapshot.supporting_files), analysis_files=len(snapshot.analysis_files),
                    team_rules=bool(snapshot.rules), not_retrieved=len(snapshot.notes),
                    related_snippets=len(snapshot.related_code))
    for note in snapshot.notes:
        events.emit("fetch_pr", note, status="warn")

    if jira_client:
        with events.step("fetch_ticket", "Looking for the linked Jira ticket(s)") as info:
            resolution = resolve_ticket(jira_client, meta, options.jira_projects, options.ticket_keys)
            ticket = resolution.ticket
            snapshot.notes += resolution.notes
            snapshot.info += resolution.info
            info.update(keys=resolution.keys, found=bool(ticket),
                        criteria=len(ticket.acceptance_criteria) if ticket else 0)
        for note in resolution.notes:
            events.emit("fetch_ticket", note, status="warn")
        for line in resolution.info:
            events.emit("fetch_ticket", line)
    elif ticket:
        events.emit("fetch_ticket", f"Using ticket file {options.ticket_file} ({ticket.key})")
    else:
        events.emit("fetch_ticket", "No ticket requested (use --jira or --ticket)", status="warn")

    folder = snapshots_dir / f"{repository.replace('/', '-')}-pr{number}-{meta.head_sha[:7]}"
    save_snapshot(snapshot, folder)
    if ticket:
        (folder / "ticket.json").write_text(ticket.model_dump_json(indent=2), encoding="utf-8")
    return folder, snapshot


def finish_run(
    record: RunRecord,
    sent: str,
    ticket: Ticket | None,
    review_input: ReviewInput,
    runs_dir: Path,
    folder: Path | None = None,
    events: EventLog | None = None,
) -> tuple[Path, ReviewResult, str]:
    """Save the run, validate the output, write result.json and report.md."""
    events = events or EventLog()
    folder = save_run(record, sent, runs_dir, folder=folder)
    with events.step("validate", "Checking the model's answer (schema, files, lines, quotes)") as info:
        result = finalize_review(record, ticket, review_input)
        info.update(status=result.status, findings=len(result.findings), problems=len(result.problems),
                    duplicates_removed=result.duplicates_removed)
    with events.step("report", "Writing the report") as info:
        report = render_markdown(result)
        save_result(folder, result.model_dump_json(indent=2), report)
        info.update(folder=str(folder))
    return folder, result, report


def review_folder(
    example: Path,
    *,
    client: ModelClient,
    runs_dir: Path,
    max_chars: int,
    prompt_version: str | None = None,
    events: EventLog | None = None,
    case_id: str | None = None,
    pipeline: str = "multi",
    passes: list[str] | None = None,
    verify: bool = True,
    verifier_client: ModelClient | None = None,
    tools: tuple[str, ...] | list[str] = DEFAULT_TOOLS,
    ruff_select: str = RUFF_SELECT,
    rules_file: Path | None = None,
    use_context: bool = True,
) -> tuple[Path, ReviewResult, str]:
    """Review one example folder (a local example or a downloaded PR) and save everything.

    pipeline "multi": static analysis, specialist passes (compliance, defects, security, team rules)
                      and a verifier.
    pipeline "single": one model call with one prompt (the baseline used for the first evaluation).
    `rules_file` overrides the team rules found in the folder (local use). `use_context=False` ignores the saved
    repository context (callers, callees, tests), to measure what it adds.
    """
    if pipeline not in ("single", "multi"):
        raise ValueError(f"Unknown pipeline '{pipeline}' (choose single or multi)")
    events = events or EventLog()
    case_id = case_id or example.name
    with events.step("load_input", f"Loading {example.name}") as info:
        ticket, review_input = load_example(example)
        if rules_file is not None:
            review_input = review_input.model_copy(
                update={"rules": rules_file.read_text(encoding="utf-8"), "rules_source": str(rules_file)})
        if not use_context:
            review_input = review_input.model_copy(update={"related_code": [], "related_facts": []})
        info.update(ticket=ticket.key if ticket else None, diff_lines=len(review_input.diff.splitlines()),
                    supporting_files=len(review_input.supporting_files), analysis_files=len(review_input.analysis_files),
                    team_rules=bool(review_input.rules))
    folder = new_run_folder(runs_dir, case_id)
    events.attach(folder / "events.jsonl")
    if pipeline == "multi":
        record, sent = run_multi(case_id, ticket, review_input, client, max_chars,
                                 prompt_version or MULTI_PROMPT_VERSION, passes, verify, verifier_client, events,
                                 tools=tools, ruff_select=ruff_select)
    else:
        record, sent = run_review(case_id, ticket, review_input, client, max_chars,
                                  prompt_version or DEFAULT_PROMPT_VERSION, events=events)
    return finish_run(record, sent, ticket, review_input, runs_dir, folder=folder, events=events)
