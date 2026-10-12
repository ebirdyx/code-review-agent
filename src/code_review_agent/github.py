"""GitHub connector: read-only access to a pull request.

It turns a PR into the same `PullRequestMetadata` + `ReviewInput` the rest of the
program already uses, so nothing downstream knows whether the data came from files
or from GitHub. It never writes anything to GitHub.

Honesty rules (the same as for local inputs):
  - everything that cannot be retrieved is recorded in `input_notes`, which end up in
    the report as partial coverage;
  - the head commit is read first and verified again at the end: if someone pushed
    while we were reading, we refuse to mix two revisions;
  - the token is read from the GITHUB_TOKEN environment variable, sent only in the
    Authorization header, and never stored or printed.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath

import httpx

from .schemas import PullRequestMetadata, ReviewInput, SupportingFile

API_URL = "https://api.github.com"
TOKEN_ENV = "GITHUB_TOKEN"
PAGE_SIZE = 100
MAX_SOURCE_CHARS = 20_000  # per supporting file
SKIP_SOURCE_SUFFIXES = (".lock", ".min.js", ".min.css", ".map", ".svg", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip")
SKIP_SOURCE_NAMES = {"package-lock.json", "yarn.lock", "poetry.lock", "uv.lock", "pnpm-lock.yaml"}

_PR_REF = re.compile(r"^(?:https://github\.com/)?(?P<repo>[\w.-]+/[\w.-]+?)(?:/pull/|#)(?P<n>\d+)/?$")


class GitHubError(Exception):
    """A GitHub request failed in a way the user can act on. The message says how."""


def parse_pr_reference(text: str) -> tuple[str, int]:
    """Accept 'owner/repo#12' or 'https://github.com/owner/repo/pull/12'."""
    match = _PR_REF.match(text.strip())
    if not match:
        raise GitHubError(f"Cannot read '{text}' as a pull request. Use owner/repo#12 or the PR URL.")
    return match["repo"], int(match["n"])


@dataclass
class PullRequestSnapshot:
    """Everything fetched for one pull request, pinned to one head commit."""

    metadata: PullRequestMetadata
    diff: str
    supporting_files: list[SupportingFile] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # what could not be retrieved
    info: list[str] = field(default_factory=list)  # shown to the user only (e.g. the PR is closed)

    def to_review_input(self) -> ReviewInput:
        return ReviewInput(
            pr=self.metadata, diff=self.diff,
            supporting_files=self.supporting_files, input_notes=self.notes,
        )


class GitHubClient:
    def __init__(
        self,
        token: str | None = None,
        api_url: str = API_URL,
        timeout_s: float = 30.0,
        transport: httpx.BaseTransport | None = None,  # tests inject a fake transport
    ):
        token = token if token is not None else os.environ.get(TOKEN_ENV)
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "code-review-agent",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self.authenticated = bool(token)
        self._http = httpx.Client(
            base_url=api_url, headers=headers, timeout=timeout_s, transport=transport,
            follow_redirects=False,  # never forward the token to another host
        )

    # ------------------------------------------------------------------ requests

    def _get(self, path: str, params: dict | None = None, raw: bool = False) -> httpx.Response:
        headers = {"Accept": "application/vnd.github.raw+json"} if raw else None
        try:
            response = self._http.get(path, params=params, headers=headers)
        except httpx.TimeoutException as exc:
            raise GitHubError("GitHub did not answer in time.") from exc
        except httpx.HTTPError as exc:
            raise GitHubError(f"Cannot reach GitHub: {type(exc).__name__}.") from exc
        if response.status_code < 300:
            return response
        raise self._error(response)  # includes 3xx: redirects are not followed

    def _get_json(self, path: str, params: dict | None = None) -> httpx.Response:
        response = self._get(path, params)
        try:
            response.json()
        except ValueError as exc:
            raise GitHubError("GitHub returned something that is not JSON.") from exc
        return response

    def _error(self, response: httpx.Response) -> GitHubError:
        code = response.status_code
        if code == 401:
            return GitHubError(f"GitHub refused the token (401). Check {TOKEN_ENV}.")
        if code in (403, 429) and response.headers.get("X-RateLimit-Remaining") == "0":
            hint = "" if self.authenticated else f" Set {TOKEN_ENV} to raise the limit (60 requests/hour without a token)."
            return GitHubError(f"GitHub rate limit reached.{hint}")
        if code == 404:
            hint = "" if self.authenticated else f" Private repositories need {TOKEN_ENV}."
            return GitHubError(f"Not found (404): the repository or pull request does not exist or is not visible.{hint}")
        return GitHubError(f"GitHub returned HTTP {code}.")

    def _paginate(self, path: str, limit: int) -> tuple[list[dict], bool]:
        """Follow Link: rel=next pages. Returns (items, more_exist_beyond_limit)."""
        items: list[dict] = []
        url: str | None = path
        params: dict | None = {"per_page": PAGE_SIZE}
        while url:
            response = self._get_json(url, params)
            items.extend(response.json())
            params = None  # the next link already carries its query
            next_link = response.links.get("next", {}).get("url")
            if len(items) >= limit:
                return items[:limit], bool(next_link) or len(items) > limit
            url = next_link
        return items, False

    # --------------------------------------------------------------------- public

    def fetch_pull_request(
        self,
        repository: str,
        number: int,
        max_files: int = 100,
        with_source: bool = True,
        max_source_files: int = 10,
    ) -> PullRequestSnapshot:
        pr = self._get_json(f"/repos/{repository}/pulls/{number}").json()
        head_sha, base_sha = pr["head"]["sha"], pr["base"]["sha"]
        notes: list[str] = []  # content we could not retrieve -> partial coverage
        info: list[str] = []  # facts worth showing the user that do not reduce coverage
        if pr.get("state") != "open":
            info.append(f"The pull request is {pr.get('state')} (merged={pr.get('merged')}); the reviewed revision is its last head commit.")

        files, truncated = self._paginate(f"/repos/{repository}/pulls/{number}/files", max_files)
        total_files = pr.get("changed_files")
        if truncated or (total_files is not None and total_files > len(files)):
            notes.append(
                f"Only the first {len(files)} of {total_files if total_files is not None else 'more'} changed files were fetched."
            )

        diff_parts: list[str] = []
        for f in files:
            part, note = _file_diff(f)
            if part:
                diff_parts.append(part)
            if note:
                notes.append(note)
        if not diff_parts:
            raise GitHubError("The pull request has no textual diff to review (no patches available).")

        supporting: list[SupportingFile] = []
        if with_source:
            candidates = [f for f in files if f["status"] != "removed" and _is_source(f["filename"])]
            for f in candidates[:max_source_files]:
                content, note = self._fetch_source(repository, f["filename"], head_sha)
                if content is not None:
                    supporting.append(SupportingFile(path=f["filename"], content=content))
                if note:
                    notes.append(note)
            if len(candidates) > max_source_files:
                notes.append(f"Full source of {len(candidates) - max_source_files} changed file(s) not fetched (limit {max_source_files}); only their diffs are visible.")

        # The PR may have received a push while we were reading. Never mix two revisions.
        again = self._get_json(f"/repos/{repository}/pulls/{number}").json()
        if again["head"]["sha"] != head_sha:
            raise GitHubError(
                f"The pull request changed while it was being read (head {head_sha[:7]} -> {again['head']['sha'][:7]}). Run the command again."
            )

        return PullRequestSnapshot(
            metadata=PullRequestMetadata(
                title=pr.get("title") or "(no title)",
                description=pr.get("body") or "",
                base_sha=base_sha, head_sha=head_sha,
                repository=repository, number=number, url=pr.get("html_url"),
            ),
            diff="\n".join(diff_parts) + "\n",
            supporting_files=supporting,
            notes=notes,
            info=info,
        )

    def _fetch_source(self, repository: str, path: str, sha: str) -> tuple[str | None, str | None]:
        try:
            response = self._get(f"/repos/{repository}/contents/{path}", {"ref": sha}, raw=True)
        except GitHubError as exc:
            return None, f"Source of {path} at {sha[:7]} could not be fetched ({exc})."
        try:
            text = response.content.decode("utf-8")
        except UnicodeDecodeError:
            return None, f"Source of {path} is not UTF-8 text; skipped."
        if len(text) > MAX_SOURCE_CHARS:
            return None, f"Source of {path} is {len(text)} characters (limit {MAX_SOURCE_CHARS}); only its diff is visible."
        return text, None


def _is_source(path: str) -> bool:
    name = PurePosixPath(path).name
    return name not in SKIP_SOURCE_NAMES and not name.lower().endswith(SKIP_SOURCE_SUFFIXES)


def _file_diff(f: dict) -> tuple[str | None, str | None]:
    """Build a git-style diff block for one entry of the 'list pull request files' API."""
    path, status = f["filename"], f["status"]
    old = f.get("previous_filename") or path
    patch = f.get("patch")
    if not patch:
        pure_rename = status in ("renamed", "copied") and f.get("changes", 0) == 0
        if pure_rename:
            return f"diff --git a/{old} b/{path}\nrename from {old}\nrename to {path}", None
        return None, f"No textual patch for {path} ({status}); it may be binary or too large, so it was not reviewed."
    header = [f"diff --git a/{old} b/{path}"]
    if status == "renamed":
        header += [f"rename from {old}", f"rename to {path}"]
    header.append("--- /dev/null" if status == "added" else f"--- a/{old}")
    header.append("+++ /dev/null" if status == "removed" else f"+++ b/{path}")
    return "\n".join(header + [patch]), None
