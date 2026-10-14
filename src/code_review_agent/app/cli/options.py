"""Options and helpers shared by every command: the model and pipeline arguments, the pull-request arguments, and how
arguments become a model client and pipeline settings."""

from __future__ import annotations

import argparse
from pathlib import Path

from ...context.builder import DEFAULT_MAX_CHARS, DEFAULT_PROMPT_VERSION
from ...context.evidence import DEFAULT_TOOLS, RUFF_SELECT
from ...llm.client import (
    DEFAULT_HOST,
    ModelClient,
    ModelError,
    ModelSettings,
    make_client,
)
from ...llm.profiles import ProfileError, resolve_settings
from ...pipeline.passes import DEFAULT_PASSES, MULTI_PROMPT_VERSION
from ...schemas import (
    FailureKind,
)

CASE_ROOTS = [Path("evaluation/cases"), Path("examples")]


EXPECTED_DIR = Path("evaluation/expected")


SPLIT_FILE = Path("evaluation/split.json")


def add_model_args(parser: argparse.ArgumentParser) -> None:
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


def pipeline_kwargs(args: argparse.Namespace) -> dict:
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


def model_settings(args: argparse.Namespace) -> ModelSettings:
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


def make_model_client(args: argparse.Namespace) -> ModelClient:
    return make_client(model_settings(args))


def add_pr_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("pr", help="owner/repo#12 or https://github.com/owner/repo/pull/12")
    parser.add_argument("--ticket", type=Path, help="ticket.json to review against (overrides --jira)")
    parser.add_argument("--jira", action="store_true", help="find the Jira ticket(s) linked from the PR and fetch them")
    parser.add_argument("--jira-projects", help="comma-separated Jira project keys, e.g. SHOP,APP (or $JIRA_PROJECTS)")
    parser.add_argument("--ticket-key", action="append", help="fetch this Jira key instead of searching the PR (repeatable)")
    parser.add_argument("--max-files", type=int, default=100, help="changed files to fetch (default 100)")
    parser.add_argument("--no-source", action="store_true", help="do not fetch full source of changed files")
    parser.add_argument("--snapshots", type=Path, default=Path("runs/pr-snapshots"),
                        help="where fetched pull requests are saved as example folders")
