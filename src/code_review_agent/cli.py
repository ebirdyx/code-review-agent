"""Command-line entry point.

Commands: check-examples, schema, build-context, review, fetch-ticket, fetch-pr, review-pr, validate,
          eval-run, eval-revalidate, eval-template, eval-score.
"""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from .context import DEFAULT_MAX_CHARS, DEFAULT_PROMPT_VERSION, build_context
from .evaluation import (
    EvaluationError,
    LabelFile,
    build_label_template,
    discover_runs,
    find_case_dir,
    load_split,
    render_scoreboard,
    score_run,
)
from .events import EventLog, echo_to_stderr
from .github import GitHubClient, GitHubError
from .jira import FIELD_ENV, JiraClient, JiraError
from .loading import load_example, load_expected
from .service import PRFetchOptions, fetch_snapshot, finish_run, review_folder
from .ui import UIApp, make_server
from .model_client import DEFAULT_HOST, ModelError, ModelSettings, OllamaClient
from .report import render_markdown
from .review import RunRecord, run_review, save_result, save_run, sent_text
from .schemas import ModelReview, ReviewInput, ReviewResult, Ticket
from .validation import finalize_review

SCHEMAS = {
    "ticket": Ticket,
    "review-input": ReviewInput,
    "model-review": ModelReview,
    "review-result": ReviewResult,
}

CASE_ROOTS = [Path("evaluation/cases"), Path("examples")]
EXPECTED_DIR = Path("evaluation/expected")
SPLIT_FILE = Path("evaluation/split.json")


def check_examples(examples_dir: Path, expected_dir: Path) -> int:
    """Validate every example and its expected answer; print a summary."""
    folders = sorted(p for p in examples_dir.iterdir() if p.is_dir())
    if not folders:
        print(f"No examples found in {examples_dir}", file=sys.stderr)
        return 1

    problems = 0
    for folder in folders:
        case_id = folder.name
        try:
            ticket, review_input = load_example(folder)
            expected = load_expected(expected_dir / f"{case_id}.json")
        except (OSError, ValidationError) as exc:
            problems += 1
            print(f"[FAIL] {case_id}: {exc}")
            continue
        if expected.case_id != case_id:
            problems += 1
            print(f"[FAIL] {case_id}: expected file says case_id={expected.case_id!r}")
            continue
        ticket_info = (
            f"ticket {ticket.key} ({len(ticket.acceptance_criteria)} criteria)"
            if ticket
            else "no ticket"
        )
        print(
            f"[ OK ] {case_id}: {ticket_info}, "
            f"diff {len(review_input.diff.splitlines())} lines, "
            f"{len(expected.expected_findings)} expected finding(s), "
            f"{len(expected.expected_limitations)} expected limitation(s)"
        )
    return 1 if problems else 0


def build_context_command(example: Path, out: Path | None, max_chars: int) -> int:
    """Assemble the model context for one example; print it or save it. No model call."""
    try:
        ticket, review_input = load_example(example)
    except (OSError, ValidationError) as exc:
        print(f"Cannot load {example}: {exc}", file=sys.stderr)
        return 1
    context = build_context(ticket, review_input, max_chars=max_chars)

    text = f"=== SYSTEM MESSAGE ===\n{context.system}\n=== USER MESSAGE ===\n{context.user}\n"
    if out:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        print(f"Context saved to {out}")
    else:
        print(text)
    print(
        f"prompt={context.prompt_version}  system={len(context.system)} chars  "
        f"user={len(context.user)} chars  coverage_complete={context.coverage.complete}",
        file=sys.stderr,
    )
    for item in context.missing_inputs:
        print(f"  missing: {item}", file=sys.stderr)
    for item in context.coverage.omitted:
        print(f"  omitted: {item}", file=sys.stderr)
    return 0


# ----------------------------------------------------------------- model options


def _add_model_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--host", help=f"Ollama address (default {DEFAULT_HOST}, or $OLLAMA_HOST)")
    parser.add_argument("--model", help="model id (default gpt-oss:120b, or $OLLAMA_MODEL)")
    parser.add_argument("--timeout", type=float, help="seconds before giving up (default 180)")
    parser.add_argument("--temperature", type=float)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--num-ctx", type=int, help="context window in tokens")
    parser.add_argument("--no-structured-output", action="store_true", help="do not send the JSON Schema")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    parser.add_argument("--prompt-version", default=DEFAULT_PROMPT_VERSION,
                        help=f"instructions file in prompts/ (default {DEFAULT_PROMPT_VERSION})")


def _make_client(args: argparse.Namespace) -> OllamaClient:
    settings = ModelSettings.from_env(
        host=args.host,
        model=args.model,
        timeout_s=args.timeout,
        temperature=args.temperature,
        seed=args.seed,
        num_ctx=args.num_ctx,
        structured_output=False if args.no_structured_output else None,
    )
    return OllamaClient(settings)


def _finish(record, sent, ticket, review_input, runs_dir: Path) -> int:
    folder, result, report = finish_run(record, sent, ticket, review_input, runs_dir)
    print(report)
    print(f"Saved in {folder}: run.json, context.txt, raw_response.txt, result.json, report.md")
    return 0 if result.status == "completed" else 2


def review_command(args: argparse.Namespace, events: EventLog | None = None) -> int:
    """Send one example to the model, validate the answer and write a report."""
    events = events or EventLog(echo=echo_to_stderr)
    try:
        client = _make_client(args)
    except ModelError as exc:
        print(f"[{exc.kind}] {exc.message}", file=sys.stderr)
        return 1

    s = client.settings
    print(f"Reviewing {args.example.name} with {s.model} at {s.host} ...")
    try:
        folder, result, report = review_folder(
            args.example, client=client, runs_dir=args.runs, max_chars=args.max_chars,
            prompt_version=args.prompt_version, events=events,
        )
    except (OSError, ValidationError) as exc:
        print(f"Cannot start review: {exc}", file=sys.stderr)
        return 1
    print(report)
    print(f"Saved in {folder}: run.json, context.txt, raw_response.txt, result.json, report.md, events.jsonl")
    return 0 if result.status == "completed" else 2


def _add_pr_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("pr", help="owner/repo#12 or https://github.com/owner/repo/pull/12")
    parser.add_argument("--ticket", type=Path, help="ticket.json to review against (overrides --jira)")
    parser.add_argument("--jira", action="store_true", help="find the Jira ticket(s) linked from the PR and fetch them")
    parser.add_argument("--jira-projects", help="comma-separated Jira project keys, e.g. SHOP,APP (or $JIRA_PROJECTS)")
    parser.add_argument("--ticket-key", action="append", help="fetch this Jira key instead of searching the PR (repeatable)")
    parser.add_argument("--max-files", type=int, default=100, help="changed files to fetch (default 100)")
    parser.add_argument("--no-source", action="store_true", help="do not fetch full source of changed files")
    parser.add_argument("--snapshots", type=Path, default=Path("runs/pr-snapshots"),
                        help="where fetched pull requests are saved as example folders")


def _fetch_snapshot(args: argparse.Namespace, events: EventLog | None = None) -> Path | None:
    """Download a PR (read-only) and save it as an example folder. Returns the folder."""
    try:
        options = PRFetchOptions.from_cli(
            jira=args.jira, jira_projects=args.jira_projects, ticket_keys=args.ticket_key,
            ticket_file=args.ticket, max_files=args.max_files, no_source=args.no_source,
        )
        # The lambdas look the classes up when called, so tests can substitute them on this module.
        folder, snapshot = fetch_snapshot(
            args.pr, args.snapshots, options,
            github=lambda: GitHubClient(), jira=lambda: JiraClient(),
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
        issue = JiraClient().fetch_issue(args.key)
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
    return 0 if _fetch_snapshot(args) else 1


def review_pr_command(args: argparse.Namespace) -> int:
    events = EventLog(echo=echo_to_stderr)
    folder = _fetch_snapshot(args, events)
    if folder is None:
        return 1
    args.example = folder
    return review_command(args, events)


def validate_command(args: argparse.Namespace) -> int:
    """Validate raw model text from a file against an example. No model is called."""
    try:
        ticket, review_input = load_example(args.example)
        raw = args.raw.read_text(encoding="utf-8")
    except (OSError, ValidationError) as exc:
        print(f"Cannot validate: {exc}", file=sys.stderr)
        return 1
    context = build_context(ticket, review_input, max_chars=args.max_chars)
    record = RunRecord(
        case_id=args.example.name,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        prompt_version=context.prompt_version,
        settings=ModelSettings(model="(none: text supplied from a file)", host=str(args.raw)),
        max_chars=args.max_chars,
        coverage=context.coverage,
        missing_inputs=context.missing_inputs,
        raw_response=raw,
    )
    sent = f"=== SYSTEM MESSAGE ===\n{context.system}\n=== USER MESSAGE ===\n{context.user}\n"
    return _finish(record, sent, ticket, review_input, args.runs)


def ui_command(args: argparse.Namespace) -> int:
    """Start the local web UI: watch reviews live, read reports, record decisions."""
    settings = ModelSettings.from_env(host=args.host, model=args.model)

    def start_review(ref: str, options: dict, events: EventLog) -> Path:
        client = _make_client(args)  # raises ModelError (e.g. missing key) -> shown in the UI
        keys = [options["ticket_key"]] if options.get("ticket_key") else None
        folder, _ = fetch_snapshot(
            ref, args.snapshots,
            PRFetchOptions.from_cli(jira=options.get("jira", False), jira_projects=options.get("jira_projects"),
                                    ticket_keys=keys),
            github=lambda: GitHubClient(), jira=lambda: JiraClient(), events=events,
        )
        run_folder, _, _ = review_folder(
            folder, client=client, runs_dir=args.runs, max_chars=args.max_chars,
            prompt_version=args.prompt_version, events=events,
        )
        return run_folder

    app = UIApp(
        runs_dir=args.runs, start_review=start_review,
        info={"model": settings.model, "host": settings.host, "prompt_version": args.prompt_version},
    )
    try:
        server = make_server(app, port=args.port)
    except OSError as exc:
        print(f"Cannot listen on port {args.port}: {exc}. Try --port 8766.", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Code Review Agent UI: {url}   (Ctrl+C to stop)")
    print(f"  runs folder: {args.runs}   model: {settings.model} at {settings.host}")
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        server.server_close()
    return 0


# -------------------------------------------------------------------- evaluation


def eval_run_command(args: argparse.Namespace) -> int:
    """Run the model on every case of a split, `--repeat` times. Needs the API key."""
    try:
        split = load_split(args.split_file)
        if args.split == "heldout" and not args.confirm_frozen:
            print(
                "Held-out cases must only be run once the prompt is frozen, otherwise they stop "
                "being held out. Re-run with --confirm-frozen to confirm.",
                file=sys.stderr,
            )
            return 1
        case_ids = args.cases.split(",") if args.cases else split.cases(args.split)
        client = _make_client(args)
    except (OSError, ValidationError) as exc:
        print(f"Cannot start evaluation: {exc}", file=sys.stderr)
        return 1
    except ModelError as exc:
        print(f"[{exc.kind}] {exc.message}", file=sys.stderr)
        return 1

    runs_dir = args.runs or Path("runs") / f"eval-{args.split}-{datetime.now(UTC):%Y%m%dT%H%M%S}"
    s = client.settings
    print(f"Evaluating {len(case_ids)} case(s) x {args.repeat} with {s.model}; saving to {runs_dir}")
    failures = 0
    for case_id in case_ids:
        try:
            example = find_case_dir(case_id, CASE_ROOTS)
        except EvaluationError as exc:
            print(f"  {case_id}: cannot load ({exc})", file=sys.stderr)
            failures += 1
            continue
        for rep in range(1, args.repeat + 1):
            try:
                folder, result, _ = review_folder(
                    example, client=client, runs_dir=runs_dir, max_chars=args.max_chars,
                    prompt_version=args.prompt_version, events=EventLog(), case_id=case_id,
                )
            except (OSError, ValidationError) as exc:
                print(f"  {case_id}: cannot load ({exc})", file=sys.stderr)
                failures += 1
                break
            if result.status == "completed":
                detail = f"{len(result.findings)} finding(s), {len(result.problems)} unconfirmed"
            else:
                failures += 1
                detail = f"FAILED [{result.error.kind}] {result.error.message}"
            print(f"  {case_id} #{rep}: {result.status}, {detail}  ({folder.name})")
    print(f"Done. Next: review-agent eval-template {runs_dir}")
    return 1 if failures else 0


def eval_revalidate_command(args: argparse.Namespace) -> int:
    """Re-run validation on saved raw responses. No model call.

    Use after improving the validator. A run is only re-validated if the case inputs and
    prompt still produce exactly the context.txt that was sent; otherwise it is skipped.
    """
    done = skipped = 0
    for run_json in sorted(args.runs_dir.rglob("run.json")):
        folder = run_json.parent
        try:
            record = RunRecord.model_validate_json(run_json.read_text(encoding="utf-8"))
            ticket, review_input = load_example(find_case_dir(record.case_id, CASE_ROOTS))
            context = build_context(
                ticket, review_input, max_chars=record.max_chars, prompt_version=record.prompt_version
            )
            saved = (folder / "context.txt").read_text(encoding="utf-8")
            if saved != sent_text(context.system, context.user):
                print(f"  skipped {folder.name}: case inputs or prompt changed since this run")
                skipped += 1
                continue
            result = finalize_review(record, ticket, review_input)
        except (OSError, ValidationError, EvaluationError) as exc:
            print(f"  skipped {folder.name}: {exc}")
            skipped += 1
            continue
        old = ReviewResult.model_validate_json((folder / "result.json").read_text(encoding="utf-8")) if (folder / "result.json").exists() else None
        save_result(folder, result.model_dump_json(indent=2), render_markdown(result))
        done += 1
        if old is not None and len(old.problems) != len(result.problems):
            print(f"  {folder.name}: problems {len(old.problems)} -> {len(result.problems)}")
    print(f"Re-validated {done} run(s), skipped {skipped}.")
    return 1 if skipped else 0


def eval_template_command(args: argparse.Namespace) -> int:
    """Create (or extend) a labels file with SUGGESTED labels for a human to confirm."""
    runs, notes = discover_runs(args.runs_dir, args.expected)
    for note in notes:
        print(f"  note: {note}", file=sys.stderr)
    if not runs:
        print(f"No scorable runs found under {args.runs_dir}", file=sys.stderr)
        return 1
    existing = None
    if args.out.exists():
        existing = LabelFile.model_validate_json(args.out.read_text(encoding="utf-8"))
    labels = build_label_template(runs, existing)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(labels.model_dump_json(indent=2), encoding="utf-8")
    total = sum(len(v) for v in labels.labels.values())
    print(f"Wrote {args.out}: {len(labels.labels)} run(s), {total} suggested label(s).")
    print("Open it, correct each label (tp / fp / duplicate / extra), then set `reviewed_by` to a human name.")
    return 0


def eval_score_command(args: argparse.Namespace) -> int:
    """Compute metrics from run folders and a confirmed labels file."""
    try:
        labels = LabelFile.model_validate_json(args.labels.read_text(encoding="utf-8"))
        split = load_split(args.split_file)
    except (OSError, ValidationError) as exc:
        print(f"Cannot read labels or split: {exc}", file=sys.stderr)
        return 1
    runs, notes = discover_runs(args.runs_dir, args.expected)
    for note in notes:
        print(f"  note: {note}", file=sys.stderr)
    wanted = set(split.cases(args.split))
    runs = [r for r in runs if r.record.case_id in wanted]
    if not runs:
        print(f"No runs of the '{args.split}' split under {args.runs_dir}", file=sys.stderr)
        return 1
    try:
        scores = [score_run(r, labels.labels.get(r.name)) for r in runs]
    except EvaluationError as exc:
        print(f"Label problem: {exc}", file=sys.stderr)
        return 1
    text = render_scoreboard(scores, labels, args.split, runs)
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"Saved to {args.out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="review-agent", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    check = sub.add_parser("check-examples", help="validate example inputs and expected answers")
    check.add_argument("--examples", type=Path, default=Path("examples"))
    check.add_argument("--expected", type=Path, default=EXPECTED_DIR)

    schema = sub.add_parser("schema", help="print a JSON Schema")
    schema.add_argument("name", choices=sorted(SCHEMAS))

    ctx = sub.add_parser("build-context", help="print or save the context sent to the model")
    ctx.add_argument("example", type=Path, help="example folder, e.g. examples/free-shipping-faulty")
    ctx.add_argument("--out", type=Path, help="save to this file instead of printing")
    ctx.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)

    rev = sub.add_parser("review", help="run a real model review on an example")
    rev.add_argument("example", type=Path)
    _add_model_args(rev)
    rev.add_argument("--runs", type=Path, default=Path("runs"), help="where to save run folders")

    ftk = sub.add_parser("fetch-ticket", help="fetch one Jira ticket (checks your Jira setup)")
    ftk.add_argument("key", help="Jira issue key, e.g. SHOP-42")
    ftk.add_argument("--out", type=Path, help="save it as a ticket.json")

    fpr = sub.add_parser("fetch-pr", help="download a GitHub pull request (read-only) as an example folder")
    _add_pr_args(fpr)

    rpr = sub.add_parser("review-pr", help="download a GitHub pull request, then review it with the model")
    _add_pr_args(rpr)
    _add_model_args(rpr)
    rpr.add_argument("--runs", type=Path, default=Path("runs"), help="where to save run folders")

    uip = sub.add_parser("ui", help="start the local web UI (live progress, reports, accept/dismiss findings)")
    _add_model_args(uip)
    uip.add_argument("--runs", type=Path, default=Path("runs"), help="folder holding the run folders")
    uip.add_argument("--snapshots", type=Path, default=Path("runs/pr-snapshots"))
    uip.add_argument("--port", type=int, default=8765)
    uip.add_argument("--open", action="store_true", help="open the page in your browser")

    val = sub.add_parser("validate", help="validate raw model text from a file (no model call)")
    val.add_argument("example", type=Path, help="example folder the text is supposed to review")
    val.add_argument("raw", type=Path, help="file containing the raw model response")
    val.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    val.add_argument("--runs", type=Path, default=Path("runs"))

    erun = sub.add_parser("eval-run", help="run the model on a whole split (needs the API key)")
    erun.add_argument("--split", choices=["dev", "heldout", "all"], default="dev")
    erun.add_argument("--cases", help="comma-separated case ids instead of a whole split")
    erun.add_argument("--repeat", type=int, default=1, help="runs per case (model output varies)")
    erun.add_argument("--runs", type=Path, help="output folder (default runs/eval-<split>-<time>)")
    erun.add_argument("--split-file", type=Path, default=SPLIT_FILE)
    erun.add_argument("--confirm-frozen", action="store_true", help="required for the held-out split")
    _add_model_args(erun)

    erev = sub.add_parser("eval-revalidate", help="re-run validation on saved responses (no model call)")
    erev.add_argument("runs_dir", type=Path)

    etpl = sub.add_parser("eval-template", help="create a labels file with suggested labels")
    etpl.add_argument("runs_dir", type=Path)
    etpl.add_argument("--out", type=Path, default=Path("evaluation/labels/labels.json"))
    etpl.add_argument("--expected", type=Path, default=EXPECTED_DIR)

    escore = sub.add_parser("eval-score", help="compute precision, recall, F1 from labelled runs")
    escore.add_argument("runs_dir", type=Path)
    escore.add_argument("--labels", type=Path, required=True)
    escore.add_argument("--split", choices=["dev", "heldout", "all"], default="all")
    escore.add_argument("--out", type=Path, help="also save the table as Markdown")
    escore.add_argument("--expected", type=Path, default=EXPECTED_DIR)
    escore.add_argument("--split-file", type=Path, default=SPLIT_FILE)

    args = parser.parse_args(argv)
    if args.command == "check-examples":
        return check_examples(args.examples, args.expected)
    if args.command == "build-context":
        return build_context_command(args.example, args.out, args.max_chars)
    if args.command == "ui":
        return ui_command(args)
    if args.command == "fetch-ticket":
        return fetch_ticket_command(args)
    if args.command == "fetch-pr":
        return fetch_pr_command(args)
    if args.command == "review-pr":
        return review_pr_command(args)
    if args.command == "validate":
        return validate_command(args)
    if args.command == "review":
        return review_command(args)
    if args.command == "eval-run":
        return eval_run_command(args)
    if args.command == "eval-revalidate":
        return eval_revalidate_command(args)
    if args.command == "eval-template":
        return eval_template_command(args)
    if args.command == "eval-score":
        return eval_score_command(args)
    print(json.dumps(SCHEMAS[args.name].model_json_schema(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
