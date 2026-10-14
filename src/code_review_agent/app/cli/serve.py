"""ui: the local web interface."""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from ...context.builder import DEFAULT_PROMPT_VERSION
from ...events import EventLog
from ...llm.client import (
    ModelError,
)
from ...pipeline.passes import MULTI_PROMPT_VERSION
from .. import clients
from ..service import PRFetchOptions, fetch_snapshot, review_folder
from ..ui import UIApp, make_server
from .options import add_model_args, make_model_client, model_settings, pipeline_kwargs


def ui_command(args: argparse.Namespace) -> int:
    """Start the local web UI: watch reviews live, read reports, record decisions."""
    try:
        settings = model_settings(args)
    except ModelError as exc:
        print(f"[{exc.kind}] {exc.message}", file=sys.stderr)
        return 1

    def start_review(ref: str, options: dict, events: EventLog) -> Path:
        client = make_model_client(args)  # raises ModelError (e.g. missing key) -> shown in the UI
        keys = [options["ticket_key"]] if options.get("ticket_key") else None
        folder, _ = fetch_snapshot(
            ref, args.snapshots,
            PRFetchOptions.from_cli(jira=options.get("jira", False), jira_projects=options.get("jira_projects"),
                                    ticket_keys=keys),
            github=lambda: clients.github_client(), jira=lambda: clients.jira_client(), events=events,
        )
        run_folder, _, _ = review_folder(
            folder, client=client, runs_dir=args.runs, max_chars=args.max_chars,
            events=events, **pipeline_kwargs(args),
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



def register(sub: argparse._SubParsersAction) -> None:
    """Add this group's subcommands to the parser."""
    uip = sub.add_parser("ui", help="start the local web UI (live progress, reports, accept/dismiss findings)")
    add_model_args(uip)
    uip.add_argument("--runs", type=Path, default=Path("runs"), help="folder holding the run folders")
    uip.add_argument("--snapshots", type=Path, default=Path("runs/pr-snapshots"))
    uip.add_argument("--port", type=int, default=8765)
    uip.add_argument("--open", action="store_true", help="open the page in your browser")
    uip.set_defaults(handler=ui_command)
