"""Commands that need no model: check-examples, schema, build-context, validate."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from ...connectors.snapshot import load_example, load_expected
from ...context.builder import DEFAULT_MAX_CHARS, build_context
from ...llm.client import (
    ModelSettings,
)
from ...pipeline.records import RunRecord
from ...schemas import (
    ModelReview,
    ReviewInput,
    ReviewResult,
    Ticket,
    public_schema,
)
from ..service import finish_run
from .options import EXPECTED_DIR

SCHEMAS = {
    "ticket": Ticket,
    "review-input": ReviewInput,
    "model-review": ModelReview,
    "review-result": ReviewResult,
}


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


def build_context_command(args: argparse.Namespace) -> int:
    example, out, max_chars = args.example, args.out, args.max_chars
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


def _finish(record, sent, ticket, review_input, runs_dir: Path) -> int:
    folder, result, report = finish_run(record, sent, ticket, review_input, runs_dir)
    print(report)
    print(f"Saved in {folder}: run.json, context.txt, raw_response.txt, result.json, report.md")
    return 0 if result.status == "completed" else 2


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


def check_examples_command(args: argparse.Namespace) -> int:
    return check_examples(args.examples, args.expected)


def schema_command(args: argparse.Namespace) -> int:
    print(json.dumps(public_schema(SCHEMAS[args.name]), indent=2))
    return 0



def register(sub: argparse._SubParsersAction) -> None:
    """Add this group's subcommands to the parser."""
    check = sub.add_parser("check-examples", help="validate example inputs and expected answers")
    check.add_argument("--examples", type=Path, default=Path("examples"))
    check.add_argument("--expected", type=Path, default=EXPECTED_DIR)
    check.set_defaults(handler=check_examples_command)

    schema = sub.add_parser("schema", help="print a JSON Schema")
    schema.add_argument("name", choices=sorted(SCHEMAS))
    schema.set_defaults(handler=schema_command)

    ctx = sub.add_parser("build-context", help="print or save the context sent to the model")
    ctx.add_argument("example", type=Path, help="example folder, e.g. examples/free-shipping-faulty")
    ctx.add_argument("--out", type=Path, help="save to this file instead of printing")
    ctx.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    ctx.set_defaults(handler=build_context_command)

    val = sub.add_parser("validate", help="validate raw model text from a file (no model call)")
    val.add_argument("example", type=Path, help="example folder the text is supposed to review")
    val.add_argument("raw", type=Path, help="file containing the raw model response")
    val.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    val.add_argument("--runs", type=Path, default=Path("runs"))
    val.set_defaults(handler=validate_command)
