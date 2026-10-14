"""Command-line entry point.

Commands: check-examples, schema, build-context, review, fetch-ticket, fetch-pr, review-pr, validate,
          eval-run, eval-compare, eval-revalidate, eval-template, eval-score.
"""

from __future__ import annotations

import argparse
import json
import os
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
from .comment import MARKER, render_pr_comment
from .comparison import (
    EvalConfig, EvalRunEntry, auto_label, compare, current_commit, now_iso, save_config,
)
from .events import EventLog, echo_to_stderr
from .github import GitHubClient, GitHubError
from .jira import FIELD_ENV, JiraClient, JiraError
from .loading import load_example, load_expected
from .evidence import DEFAULT_TOOLS, RUFF_SELECT
from .pipeline import DEFAULT_PASSES, MULTI_PROMPT_VERSION, multi_context_text
from .service import PRFetchOptions, fetch_snapshot, finish_run, review_folder
from .ui import UIApp, make_server
from .model_client import DEFAULT_HOST, ModelClient, ModelError, ModelSettings, make_client
from .profiles import PROFILE_ENV, ProfileError, load_profiles, resolve_settings
from .report import render_markdown
from .review import RunRecord, run_review, save_result, save_run, sent_text
from .schemas import FailureKind, ModelReview, ReviewInput, ReviewResult, Ticket, public_schema
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
    parser.add_argument("--profile", help="model profile from models.toml (see `review-agent profiles`)")
    parser.add_argument("--profiles-file", type=Path, help="extra profiles file (default: ./models.toml if present)")
    parser.add_argument("--host", help=f"override the profile's address (default {DEFAULT_HOST}, or $OLLAMA_HOST)")
    parser.add_argument("--model", help="override the profile's model id (or $OLLAMA_MODEL)")
    parser.add_argument("--timeout", type=float, help="seconds before giving up (default 180)")
    parser.add_argument("--temperature", type=float)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--num-ctx", type=int, help="context window in tokens")
    parser.add_argument("--no-structured-output", action="store_true", help="do not send the JSON Schema")
    parser.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    parser.add_argument("--pipeline", choices=["multi", "single"], default="multi",
                        help="multi: specialist passes + verifier (default); single: one prompt, one model call")
    parser.add_argument("--prompt-version",
                        help=f"prompt set to use (default: {MULTI_PROMPT_VERSION} for multi, {DEFAULT_PROMPT_VERSION} for single)")
    parser.add_argument("--passes", help=f"multi only: comma-separated subset of {','.join(DEFAULT_PASSES)}")
    parser.add_argument("--no-verify", action="store_true", help="multi only: skip the verification pass")
    parser.add_argument("--verifier-profile", help="multi only: use another model profile for verification")
    parser.add_argument("--tools", help=f"multi only: static-analysis tools to run, comma-separated (default {','.join(DEFAULT_TOOLS)})")
    parser.add_argument("--no-tools", action="store_true", help="multi only: do not run static analysis")
    parser.add_argument("--ruff-select", default=RUFF_SELECT, help=f"Ruff rule families to run (default {RUFF_SELECT})")
    parser.add_argument("--rules", type=Path, help="team coding rules file (default: .review-agent/rules.md from the PR's base branch)")
    parser.add_argument("--no-context", action="store_true",
                        help="do not use (or, for a pull request, do not build) the repository context: callers, callees, tests")


def _pipeline_kwargs(args: argparse.Namespace) -> dict:
    """Pipeline options for `review_folder`, from the command line."""
    verifier = None
    if args.verifier_profile:
        try:
            verifier = make_client(resolve_settings(args.verifier_profile, profiles_file=args.profiles_file))
        except ProfileError as exc:
            raise ModelError(FailureKind.INPUT_ERROR, str(exc)) from exc
    return {
        "pipeline": args.pipeline,
        "prompt_version": args.prompt_version,
        "passes": [p.strip() for p in args.passes.split(",") if p.strip()] if args.passes else None,
        "verify": not args.no_verify,
        "verifier_client": verifier,
        "tools": () if args.no_tools else (tuple(t.strip() for t in args.tools.split(",") if t.strip()) if args.tools else DEFAULT_TOOLS),
        "ruff_select": args.ruff_select,
        "rules_file": args.rules,
        "use_context": not getattr(args, "no_context", False),
    }


def _settings(args: argparse.Namespace) -> ModelSettings:
    try:
        return resolve_settings(
            args.profile,
            {
                "host": args.host,
                "model": args.model,
                "timeout_s": args.timeout,
                "temperature": args.temperature,
                "seed": args.seed,
                "num_ctx": args.num_ctx,
                "structured_output": False if args.no_structured_output else None,
            },
            args.profiles_file,
        )
    except ProfileError as exc:
        raise ModelError(FailureKind.INPUT_ERROR, str(exc)) from exc


def _make_client(args: argparse.Namespace) -> ModelClient:
    return make_client(_settings(args))


def profiles_command(args: argparse.Namespace) -> int:
    """List the model profiles, their licences and whether their API key is set (never the key)."""
    try:
        available = load_profiles(args.profiles_file)
    except ProfileError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    chosen = args.profile or os.environ.get(PROFILE_ENV) or available.default
    for name, p in sorted(available.profiles.items()):
        mark = "*" if name == chosen else " "
        key = "no key needed" if p.key_env is None and "ollama.com" not in p.host else (
            f"{p.key_env or 'OLLAMA_API_KEY'}: " + ("set" if os.environ.get(p.key_env or "OLLAMA_API_KEY") else "NOT set"))
        print(f"{mark} {name}")
        print(f"    {p.provider}  {p.model}  @ {p.host}")
        print(f"    licence of the weights: {p.licence or 'not stated'}   key: {key}   parallel requests: {p.max_concurrency}")
        if p.notes:
            print(f"    {p.notes}")
    print(f"\n* = in use. Choose another with --profile NAME or REVIEW_AGENT_PROFILE=NAME.")
    return 0


def _finish(record, sent, ticket, review_input, runs_dir: Path) -> int:
    folder, result, report = finish_run(record, sent, ticket, review_input, runs_dir)
    print(report)
    print(f"Saved in {folder}: run.json, context.txt, raw_response.txt, result.json, report.md")
    return 0 if result.status == "completed" else 2


def _review(args: argparse.Namespace, events: EventLog | None = None) -> tuple[int, Path | None, ReviewResult | None]:
    """Run one review. Returns (exit code, run folder, result); folder and result are None if it never started."""
    events = events or EventLog(echo=echo_to_stderr)
    try:
        client = _make_client(args)
    except ModelError as exc:
        print(f"[{exc.kind}] {exc.message}", file=sys.stderr)
        return 1, None, None

    s = client.settings
    print(f"Reviewing {args.example.name} with {s.model} at {s.host} ...")
    try:
        folder, result, report = review_folder(
            args.example, client=client, runs_dir=args.runs, max_chars=args.max_chars,
            events=events, **_pipeline_kwargs(args),
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


def _publish_comment(args: argparse.Namespace, folder: Path, result: ReviewResult) -> bool:
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
        action, url = GitHubClient().upsert_comment(rev.repository, rev.pr_number, body, MARKER)
    except GitHubError as exc:
        print(f"Cannot post the comment: {exc}", file=sys.stderr)
        return False
    print(f"Comment {action} on {rev.repository}#{rev.pr_number}: {url}")
    return True


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
            no_tools=getattr(args, "no_tools", False), no_context=getattr(args, "no_context", False),
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


def doctor_command(args: argparse.Namespace) -> int:
    """Check every connection in one go: model key, Jira login, GitHub access, tools. Never prints a secret."""
    failures = 0

    def line(ok: bool | None, name: str, text: str) -> None:
        nonlocal failures
        mark = {True: "OK     ", False: "FAILED ", None: "n/a    "}[ok]
        failures += ok is False
        print(f"{mark}{name:<13} {text}")

    try:
        s = _settings(args)
        key_env = s.key_env or ("OLLAMA_API_KEY" if "ollama.com" in s.host else None)
        needs_key = key_env is not None
        have = bool(os.environ.get(key_env)) if needs_key else True
        line(have, "Model", f"profile '{s.profile}': {s.model} ({s.provider}) at {s.host}"
             + (f"; key {key_env} is {'set' if have else 'NOT set'}" if needs_key else "; no key needed"))
    except ModelError as exc:
        line(False, "Model", exc.message)

    try:
        jira = JiraClient()
    except JiraError as exc:
        line(None, "Jira", f"not configured (optional): {exc}")
    else:
        try:
            line(True, "Jira", f"logged in as '{jira.whoami()}' at {jira._host}")
        except JiraError as exc:
            line(False, "Jira", str(exc))

    try:
        gh = GitHubClient()
        remaining, limit = gh.rate_limit()
        line(True, "GitHub", f"reachable, {'token set' if gh.authenticated else 'no token (public repositories only)'}; "
             f"{remaining}/{limit} requests left this hour")
    except GitHubError as exc:
        line(False, "GitHub", str(exc))

    versions = {t: __import__("importlib.metadata", fromlist=["version"]).version(t) for t in DEFAULT_TOOLS}
    line(True, "Static tools", ", ".join(f"{t} {v}" for t, v in versions.items()))
    print("\nAll connections OK." if not failures else f"\n{failures} problem(s): fix the lines marked FAILED.")
    return 1 if failures else 0


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
    code, run_folder, result = _review(args, events)
    if result is not None and run_folder is not None and not _publish_comment(args, run_folder, result):
        return 1
    # A failed review is still published (it says "did not run"), so a silent pipeline is never mistaken for a clean one.
    return code


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
    try:
        settings = _settings(args)
    except ModelError as exc:
        print(f"[{exc.kind}] {exc.message}", file=sys.stderr)
        return 1

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
            events=events, **_pipeline_kwargs(args),
        )
        return run_folder

    app = UIApp(
        runs_dir=args.runs, start_review=start_review,
        info={"model": settings.model, "host": settings.host, "profile": settings.profile, "pipeline": args.pipeline,
              "prompt_version": args.prompt_version or (MULTI_PROMPT_VERSION if args.pipeline == "multi" else DEFAULT_PROMPT_VERSION)},
    )
    try:
        server = make_server(app, port=args.port)
    except OSError as exc:
        print(f"Cannot listen on port {args.port}: {exc}. Try --port 8766.", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Code Review Agent UI: {url}   (Ctrl+C to stop)")
    print(f"  runs folder: {args.runs}   profile: {settings.profile}   model: {settings.model} at {settings.host}")
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


def _case_folders(roots: list[Path]) -> list[str]:
    """Names of the example folders (they contain pr.json) found directly inside each root."""
    return sorted({p.name for root in roots if root.is_dir() for p in root.iterdir() if (p / "pr.json").exists()})


def _eval_config(args: argparse.Namespace, settings: ModelSettings, kwargs: dict, split_name: str, case_ids: list[str]) -> EvalConfig:
    """The effective configuration of this evaluation, as it will actually run (the single pipeline ignores tools,
    context and the verifier, so they are recorded as off)."""
    multi = kwargs["pipeline"] == "multi"
    tools = list(kwargs["tools"]) if multi else []
    context = bool(kwargs["use_context"]) if multi else False
    verify = bool(kwargs["verify"]) if multi else False
    prompt = kwargs["prompt_version"] or (MULTI_PROMPT_VERSION if multi else DEFAULT_PROMPT_VERSION)
    return EvalConfig(
        label=getattr(args, "label", None) or auto_label(kwargs["pipeline"], verify, tools, context),
        created_at=now_iso(), split=split_name, cases=case_ids, repeat=args.repeat,
        pipeline=kwargs["pipeline"], prompt_version=prompt, passes=kwargs["passes"] if multi else None,
        verify=verify, tools=tools, context=context, ruff_select=kwargs["ruff_select"] if multi else None,
        model=settings.model, host=settings.host, profile=settings.profile,
        temperature=settings.temperature, seed=settings.seed, agent_commit=current_commit(),
    )


def eval_run_command(args: argparse.Namespace) -> int:
    """Run the model on every case of a split (or of --cases-dir), `--repeat` times, and record the configuration."""
    roots = list(args.cases_dir) if args.cases_dir else CASE_ROOTS
    try:
        if args.cases_dir:  # custom cases: no split file applies, every example folder found is a case
            split_name = "custom"
            case_ids = args.cases.split(",") if args.cases else _case_folders(roots)
            if not case_ids:
                raise EvaluationError(f"No example folders (with a pr.json) found in {', '.join(map(str, roots))}")
        else:
            split = load_split(args.split_file)
            split_name = args.split
            if args.split == "heldout" and not args.confirm_frozen:
                print(
                    "Held-out cases must only be run once the prompt is frozen, otherwise they stop "
                    "being held out. Re-run with --confirm-frozen to confirm.",
                    file=sys.stderr,
                )
                return 1
            case_ids = args.cases.split(",") if args.cases else split.cases(args.split)
        client = _make_client(args)
        kwargs = _pipeline_kwargs(args)
    except (OSError, ValidationError, EvaluationError) as exc:
        print(f"Cannot start evaluation: {exc}", file=sys.stderr)
        return 1
    except ModelError as exc:
        print(f"[{exc.kind}] {exc.message}", file=sys.stderr)
        return 1

    s = client.settings
    config = _eval_config(args, s, kwargs, split_name, case_ids)
    stamp = datetime.now(UTC)
    runs_dir = args.runs or Path("runs") / f"eval-{config.label}-{stamp:%Y%m%dT%H%M%S}"
    save_config(runs_dir, config)
    print(f"Evaluating {len(case_ids)} case(s) x {args.repeat} as '{config.label}' with {s.model}; saving to {runs_dir}")
    failures = 0
    for case_id in case_ids:
        try:
            example = find_case_dir(case_id, roots)
        except EvaluationError as exc:
            print(f"  {case_id}: cannot load ({exc})", file=sys.stderr)
            failures += 1
            continue
        for rep in range(1, args.repeat + 1):
            try:
                folder, result, _ = review_folder(
                    example, client=client, runs_dir=runs_dir, max_chars=args.max_chars,
                    events=EventLog(), case_id=case_id, **kwargs,
                )
            except (OSError, ValidationError, ValueError) as exc:
                print(f"  {case_id}: cannot load ({exc})", file=sys.stderr)
                failures += 1
                break
            config.runs.append(EvalRunEntry(case_id=case_id, rep=rep, folder=folder.name, status=result.status))
            save_config(runs_dir, config)  # kept up to date, so an interrupted evaluation can still be compared
            if result.status == "completed":
                detail = f"{len(result.findings)} finding(s), {len(result.problems)} unconfirmed"
            else:
                failures += 1
                detail = f"FAILED [{result.error.kind}] {result.error.message}"
            print(f"  {case_id} #{rep}: {result.status}, {detail}  ({folder.name})")
    print(f"Done. Next: review-agent eval-compare {runs_dir} [other folders...]  (or eval-template / eval-score for hand labels)")
    return 1 if failures else 0


def eval_compare_command(args: argparse.Namespace) -> int:
    """Put several evaluation folders side by side (configurations, results, per-case matrix). No model is called."""
    try:
        text, _ = compare(list(args.runs_dirs), args.expected, args.labels)
    except (EvaluationError, OSError, ValidationError) as exc:
        print(f"Cannot compare: {exc}", file=sys.stderr)
        return 1
    print(text)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
        print(f"Saved to {args.out}", file=sys.stderr)
    return 0


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
            ticket, review_input = load_example(find_case_dir(record.case_id, list(args.cases_dir) if args.cases_dir else CASE_ROOTS))
            if record.pipeline == "multi":
                rebuilt = multi_context_text(record, ticket, review_input)
            else:
                context = build_context(
                    ticket, review_input, max_chars=record.max_chars, prompt_version=record.prompt_version
                )
                rebuilt = sent_text(context.system, context.user)
            saved = (folder / "context.txt").read_text(encoding="utf-8")
            if saved != rebuilt:
                print(f"  skipped {folder.name}: case inputs or prompt changed since this run")
                skipped += 1
                continue
            result = finalize_review(record, ticket, review_input)
        except (OSError, ValidationError, EvaluationError, ValueError) as exc:
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


def _make_output_safe() -> None:
    """Reports contain whatever characters the model wrote (non-breaking hyphens, accents...).

    A Windows console or a redirected file uses a legacy code page by default, and printing such a character
    would crash the command after the review has finished. Keep the text; replace only what cannot be shown.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):  # not a text stream that can be reconfigured (for example in tests)
            pass


def main(argv: list[str] | None = None) -> int:
    _make_output_safe()
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
    fpr.add_argument("--no-context", action="store_true", help="do not build the repository context (callers, callees, tests)")

    rpr = sub.add_parser("review-pr", help="download a GitHub pull request, then review it with the model")
    _add_pr_args(rpr)
    _add_model_args(rpr)
    rpr.add_argument("--runs", type=Path, default=Path("runs"), help="where to save run folders")
    rpr.add_argument("--post-comment", action="store_true",
                     help="publish the review as ONE comment on the pull request (updated on every run). "
                          "Needs GITHUB_TOKEN with write access to pull requests. Without this flag, comment.md is only written")
    rpr.add_argument("--report-link", help="address to mention in the comment as the place of the full report (e.g. the workflow run)")

    doc = sub.add_parser("doctor", help="check the model key, Jira login, GitHub access and tools in one go")
    _add_model_args(doc)

    prof = sub.add_parser("profiles", help="list model profiles (provider, model, licence, key set or not)")
    prof.add_argument("--profile", help="highlight this profile")
    prof.add_argument("--profiles-file", type=Path)

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
    erun.add_argument("--label", help="name of this configuration in comparisons (default: made from the flags, e.g. multi-no-context)")
    erun.add_argument("--cases-dir", type=Path, action="append",
                      help="folder of example folders to evaluate instead of the split (repeatable); every folder with a pr.json is a case")
    _add_model_args(erun)

    erev = sub.add_parser("eval-revalidate", help="re-run validation on saved responses (no model call)")
    erev.add_argument("runs_dir", type=Path)
    erev.add_argument("--cases-dir", type=Path, action="append", help="where the cases are, if not evaluation/cases and examples")

    etpl = sub.add_parser("eval-template", help="create a labels file with suggested labels")
    etpl.add_argument("runs_dir", type=Path)
    etpl.add_argument("--out", type=Path, default=Path("evaluation/labels/labels.json"))
    etpl.add_argument("--expected", type=Path, default=EXPECTED_DIR)

    ecmp = sub.add_parser("eval-compare", help="compare evaluation folders side by side (no model call)")
    ecmp.add_argument("runs_dirs", type=Path, nargs="+", help="folders made by eval-run (each has an eval-config.json)")
    ecmp.add_argument("--labels", type=Path, help="one labels file for all folders (default: <folder>/labels.json, else suggested from location)")
    ecmp.add_argument("--expected", type=Path, default=EXPECTED_DIR, help="expected answers (default evaluation/expected)")
    ecmp.add_argument("--out", type=Path, help="also save the comparison as Markdown")

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
    if args.command == "doctor":
        return doctor_command(args)
    if args.command == "profiles":
        return profiles_command(args)
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
    if args.command == "eval-compare":
        return eval_compare_command(args)
    print(json.dumps(public_schema(SCHEMAS[args.name]), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
