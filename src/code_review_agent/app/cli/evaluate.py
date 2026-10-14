"""eval-run, eval-compare, eval-revalidate, eval-template, eval-score: measure the agent."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from ...connectors.snapshot import load_example
from ...context.builder import DEFAULT_PROMPT_VERSION, build_context
from ...evaluation.comparison import (
    EvalConfig,
    EvalRunEntry,
    auto_label,
    compare,
    current_commit,
    now_iso,
    save_config,
)
from ...evaluation.scoring import (
    EvaluationError,
    LabelFile,
    build_label_template,
    discover_runs,
    find_case_dir,
    load_split,
    render_scoreboard,
    score_run,
)
from ...events import EventLog
from ...llm.client import (
    ModelError,
    ModelSettings,
)
from ...pipeline.assemble import multi_context_text
from ...pipeline.passes import MULTI_PROMPT_VERSION
from ...pipeline.records import RunRecord, save_result, sent_text
from ...pipeline.validation import finalize_review
from ...reporting.report import render_markdown
from ...schemas import (
    ReviewResult,
)
from ..service import review_folder
from .options import (
    CASE_ROOTS,
    EXPECTED_DIR,
    SPLIT_FILE,
    add_model_args,
    make_model_client,
    pipeline_kwargs,
)


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
        client = make_model_client(args)
        kwargs = pipeline_kwargs(args)
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



def register(sub: argparse._SubParsersAction) -> None:
    """Add this group's subcommands to the parser."""
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
    add_model_args(erun)
    erun.set_defaults(handler=eval_run_command)

    erev = sub.add_parser("eval-revalidate", help="re-run validation on saved responses (no model call)")
    erev.add_argument("runs_dir", type=Path)
    erev.add_argument("--cases-dir", type=Path, action="append", help="where the cases are, if not evaluation/cases and examples")
    erev.set_defaults(handler=eval_revalidate_command)

    etpl = sub.add_parser("eval-template", help="create a labels file with suggested labels")
    etpl.add_argument("runs_dir", type=Path)
    etpl.add_argument("--out", type=Path, default=Path("evaluation/labels/labels.json"))
    etpl.add_argument("--expected", type=Path, default=EXPECTED_DIR)
    etpl.set_defaults(handler=eval_template_command)

    ecmp = sub.add_parser("eval-compare", help="compare evaluation folders side by side (no model call)")
    ecmp.add_argument("runs_dirs", type=Path, nargs="+", help="folders made by eval-run (each has an eval-config.json)")
    ecmp.add_argument("--labels", type=Path, help="one labels file for all folders (default: <folder>/labels.json, else suggested from location)")
    ecmp.add_argument("--expected", type=Path, default=EXPECTED_DIR, help="expected answers (default evaluation/expected)")
    ecmp.add_argument("--out", type=Path, help="also save the comparison as Markdown")
    ecmp.set_defaults(handler=eval_compare_command)

    escore = sub.add_parser("eval-score", help="compute precision, recall, F1 from labelled runs")
    escore.add_argument("runs_dir", type=Path)
    escore.add_argument("--labels", type=Path, required=True)
    escore.add_argument("--split", choices=["dev", "heldout", "all"], default="all")
    escore.add_argument("--out", type=Path, help="also save the table as Markdown")
    escore.add_argument("--expected", type=Path, default=EXPECTED_DIR)
    escore.add_argument("--split-file", type=Path, default=SPLIT_FILE)
    escore.set_defaults(handler=eval_score_command)
