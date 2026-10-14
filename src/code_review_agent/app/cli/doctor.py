"""doctor and profiles: check the setup (model key, Jira, GitHub, tools) and list the model profiles."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from ...connectors.github import GitHubError
from ...connectors.jira import JiraError
from ...context.evidence import DEFAULT_TOOLS
from ...llm.client import (
    ModelError,
)
from ...llm.profiles import PROFILE_ENV, ProfileError, load_profiles
from .. import clients
from .options import add_model_args, model_settings


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
    print("\n* = in use. Choose another with --profile NAME or REVIEW_AGENT_PROFILE=NAME.")
    return 0


def doctor_command(args: argparse.Namespace) -> int:
    """Check every connection in one go: model key, Jira login, GitHub access, tools. Never prints a secret."""
    failures = 0

    def line(ok: bool | None, name: str, text: str) -> None:
        nonlocal failures
        mark = {True: "OK     ", False: "FAILED ", None: "n/a    "}[ok]
        failures += ok is False
        print(f"{mark}{name:<13} {text}")

    try:
        s = model_settings(args)
        key_env = s.key_env or ("OLLAMA_API_KEY" if "ollama.com" in s.host else None)
        needs_key = key_env is not None
        have = bool(os.environ.get(key_env)) if needs_key else True
        line(have, "Model", f"profile '{s.profile}': {s.model} ({s.provider}) at {s.host}"
             + (f"; key {key_env} is {'set' if have else 'NOT set'}" if needs_key else "; no key needed"))
    except ModelError as exc:
        line(False, "Model", exc.message)

    try:
        jira = clients.jira_client()
    except JiraError as exc:
        line(None, "Jira", f"not configured (optional): {exc}")
    else:
        try:
            line(True, "Jira", f"logged in as '{jira.whoami()}' at {jira._host}")
        except JiraError as exc:
            line(False, "Jira", str(exc))

    try:
        gh = clients.github_client()
        remaining, limit = gh.rate_limit()
        line(True, "GitHub", f"reachable, {'token set' if gh.authenticated else 'no token (public repositories only)'}; "
             f"{remaining}/{limit} requests left this hour")
    except GitHubError as exc:
        line(False, "GitHub", str(exc))

    versions = {t: __import__("importlib.metadata", fromlist=["version"]).version(t) for t in DEFAULT_TOOLS}
    line(True, "Static tools", ", ".join(f"{t} {v}" for t, v in versions.items()))
    print("\nAll connections OK." if not failures else f"\n{failures} problem(s): fix the lines marked FAILED.")
    return 1 if failures else 0



def register(sub: argparse._SubParsersAction) -> None:
    """Add this group's subcommands to the parser."""
    doc = sub.add_parser("doctor", help="check the model key, Jira login, GitHub access and tools in one go")
    add_model_args(doc)
    doc.set_defaults(handler=doctor_command)

    prof = sub.add_parser("profiles", help="list model profiles (provider, model, licence, key set or not)")
    prof.add_argument("--profile", help="highlight this profile")
    prof.add_argument("--profiles-file", type=Path)
    prof.set_defaults(handler=profiles_command)
