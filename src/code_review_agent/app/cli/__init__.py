"""Command-line entry point (`review-agent`, also `python -m code_review_agent`).

Commands: check-examples, schema, build-context, validate, fetch-ticket, fetch-pr, review, review-pr, doctor, profiles, ui,
          eval-run, eval-compare, eval-revalidate, eval-template, eval-score.

Each command group lives in its own module and registers its own subcommands; this file only builds the parser and
dispatches.
"""

from __future__ import annotations

import argparse

from . import doctor, evaluate, fetch, offline, review, serve
from .output import make_output_safe


def main(argv: list[str] | None = None) -> int:
    make_output_safe()
    parser = argparse.ArgumentParser(prog="review-agent", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for group in (offline, fetch, review, doctor, serve, evaluate):
        group.register(sub)
    args = parser.parse_args(argv)
    return args.handler(args)
