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

import io
import os
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from urllib.parse import urlparse

import httpx

from ..context.codegraph import build_pack
from ..context.evidence import added_lines
from ..schemas import PullRequestMetadata, RelatedSnippet, ReviewInput, SupportingFile

API_URL = "https://api.github.com"
TOKEN_ENV = "GITHUB_TOKEN"
PAGE_SIZE = 100
MAX_SOURCE_CHARS = 20_000  # per supporting file (what the model sees)
MAX_ANALYSIS_CHARS = 500_000  # per file given to the static-analysis tools
MAX_ANALYSIS_FILES = 40
MAX_RULES_CHARS = 20_000
MAX_ARCHIVE_BYTES = 40_000_000  # repository download for the code graph
MAX_CONTEXT_FILE_CHARS = 300_000  # per Python file read from the archive
MAX_CONTEXT_TOTAL_CHARS = 8_000_000
MAX_CONTEXT_FILES = 3000
ARCHIVE_HOSTS = {"codeload.github.com"}  # the only host a repository download may be redirected to
SKIP_CONTEXT_DIRS = {".git", ".venv", "venv", "env", "node_modules", "site-packages", "__pycache__", "build", "dist", ".tox", ".mypy_cache"}
RULES_PATHS = (".review-agent/rules.md", "review-rules.md")  # looked up at the base commit, in this order
SKIP_SOURCE_SUFFIXES = (".lock", ".min.js", ".min.css", ".map", ".svg", ".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip")
SKIP_SOURCE_NAMES = {"package-lock.json", "yarn.lock", "poetry.lock", "uv.lock", "pnpm-lock.yaml"}

_PR_REF = re.compile(r"^(?:https://github\.com/)?(?P<repo>[\w.-]+/[\w.-]+?)(?:/pull/|#)(?P<n>\d+)/?$")


class GitHubError(Exception):
    """A GitHub request failed in a way the user can act on. The message says how."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status  # the HTTP status, when the failure was an HTTP one


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
    analysis_files: list[SupportingFile] = field(default_factory=list)  # full changed .py files, for the tools
    rules: str | None = None  # team rules read from the BASE commit
    rules_source: str | None = None
    related_code: list[RelatedSnippet] = field(default_factory=list)  # callers, callees, tests, class (code graph)
    related_facts: list[str] = field(default_factory=list)

    def to_review_input(self) -> ReviewInput:
        return ReviewInput(
            pr=self.metadata, diff=self.diff,
            supporting_files=self.supporting_files, input_notes=self.notes,
            analysis_files=self.analysis_files, rules=self.rules, rules_source=self.rules_source,
            related_code=self.related_code, related_facts=self.related_facts,
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
        self._transport = transport
        self._timeout = timeout_s
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
            return GitHubError(f"GitHub refused the token (401). Check {TOKEN_ENV}.", code)
        if code in (403, 429) and response.headers.get("X-RateLimit-Remaining") == "0":
            hint = "" if self.authenticated else f" Set {TOKEN_ENV} to raise the limit (60 requests/hour without a token)."
            return GitHubError(f"GitHub rate limit reached.{hint}", code)
        if code == 404:
            hint = "" if self.authenticated else f" Private repositories need {TOKEN_ENV}."
            return GitHubError(f"Not found (404): the repository or pull request does not exist or is not visible.{hint}", code)
        return GitHubError(f"GitHub returned HTTP {code}.", code)

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

    def _send(self, method: str, path: str, payload: dict) -> httpx.Response:
        """The only write path of this client (comments). Needs a token with permission to comment."""
        if not self.authenticated:
            raise GitHubError(f"Posting a comment needs a token: set {TOKEN_ENV}.")
        try:
            response = self._http.request(method, path, json=payload)
        except httpx.TimeoutException as exc:
            raise GitHubError("GitHub did not answer in time.") from exc
        except httpx.HTTPError as exc:
            raise GitHubError(f"Cannot reach GitHub: {type(exc).__name__}.") from exc
        if response.status_code < 300:
            return response
        if response.status_code == 403:
            raise GitHubError("GitHub refused to write the comment (403): the token needs 'pull-requests: write' "
                              "(in a workflow, add it under `permissions:`).", 403)
        raise self._error(response)

    def upsert_comment(self, repository: str, number: int, body: str, marker: str) -> tuple[str, str]:
        """Create the review comment, or update the one this tool wrote earlier (found by its hidden `marker`).

        Returns ("created" | "updated", comment url). Never touches comments that do not start with the marker.
        """
        base = f"/repos/{repository}/issues"
        comments, _ = self._paginate(f"{base}/{number}/comments", limit=1000)
        for c in comments:
            if str(c.get("body", "")).startswith(marker) and c.get("id"):
                try:
                    done = self._send("PATCH", f"{base}/comments/{c['id']}", {"body": body})
                    return "updated", str(done.json().get("html_url", ""))
                except GitHubError as exc:
                    if exc.status != 403:  # somebody else's comment that copies our marker: leave it, write our own
                        raise
        done = self._send("POST", f"{base}/{number}/comments", {"body": body})
        return "created", str(done.json().get("html_url", ""))

    def rate_limit(self) -> tuple[int, int]:
        """(requests left, requests allowed per hour). Also proves that GitHub is reachable and the token works."""
        core = self._get_json("/rate_limit").json()["resources"]["core"]
        return int(core["remaining"]), int(core["limit"])

    def fetch_pull_request(
        self,
        repository: str,
        number: int,
        max_files: int = 100,
        with_source: bool = True,
        max_source_files: int = 10,
        with_analysis: bool = True,
        with_rules: bool = True,
        with_context: bool = True,
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
        fulltext: dict[str, str] = {}  # every file we downloaded, so nothing is fetched twice
        if with_source:
            candidates = [f for f in files if f["status"] != "removed" and _is_source(f["filename"])]
            for f in candidates[:max_source_files]:
                path = f["filename"]
                try:
                    text = self._fetch_text(repository, path, head_sha)
                except GitHubError as exc:
                    notes.append(f"Source of {path} at {head_sha[:7]} could not be fetched ({exc}).")
                    continue
                fulltext[path] = text
                if len(text) <= MAX_SOURCE_CHARS:
                    supporting.append(SupportingFile(path=path, content=text))
                else:
                    notes.append(f"Source of {path} is {len(text)} characters (limit {MAX_SOURCE_CHARS}); only its diff is visible.")
            if len(candidates) > max_source_files:
                notes.append(f"Full source of {len(candidates) - max_source_files} changed file(s) not fetched (limit {max_source_files}); only their diffs are visible.")

        # Full changed Python files for the static-analysis tools. The model does not see these.
        analysis: list[SupportingFile] = []
        if with_analysis:
            python_files = [f["filename"] for f in files if f["status"] != "removed" and f["filename"].endswith(".py")]
            for path in python_files[:MAX_ANALYSIS_FILES]:
                text = fulltext.get(path)
                if text is None:
                    try:
                        text = self._fetch_text(repository, path, head_sha)
                    except GitHubError as exc:
                        info.append(f"{path} could not be fetched for static analysis ({exc}).")
                        continue
                if len(text) <= MAX_ANALYSIS_CHARS:
                    analysis.append(SupportingFile(path=path, content=text))
                else:
                    info.append(f"{path} is {len(text)} characters: too large for static analysis (limit {MAX_ANALYSIS_CHARS}).")

        # Team rules come from the BASE commit: a pull request must not be able to rewrite its own rules.
        rules, rules_source = None, None
        if with_rules:
            for rules_path in RULES_PATHS:
                try:
                    rules = self._fetch_text(repository, rules_path, base_sha)
                except GitHubError as exc:
                    if exc.status != 404:  # a missing rules file is normal; anything else is worth saying
                        info.append(f"Team rules ({rules_path}) could not be read ({exc}).")
                    continue
                if len(rules) > MAX_RULES_CHARS:
                    info.append(f"{rules_path} is {len(rules)} characters (limit {MAX_RULES_CHARS}); the rules were not used.")
                    rules = None
                    continue
                rules_source = f"{rules_path} at base commit {base_sha[:7]}"
                break

        # Repository context beyond the diff: one archive download, parsed in memory (see codegraph.py).
        related: list[RelatedSnippet] = []
        facts: list[str] = []
        if with_context:
            try:
                sources, archive_notes = self.fetch_python_sources(repository, head_sha)
                info += archive_notes
                related, facts = build_pack(added_lines("\n".join(diff_parts)), sources)
            except GitHubError as exc:
                info.append(f"Repository context (callers, callees, tests) could not be retrieved ({exc}).")

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
            analysis_files=analysis,
            rules=rules,
            rules_source=rules_source,
            related_code=related,
            related_facts=facts,
        )

    def fetch_python_sources(self, repository: str, sha: str) -> tuple[dict[str, str], list[str]]:
        """Every Python file of the repository at one commit, from ONE archive download (two requests in all).

        The API answers with a redirect to codeload.github.com. We follow it by hand, to that host only, over https and
        WITHOUT the Authorization header, so the token never leaves api.github.com. Size limits protect memory.
        Returns (path -> source, notes).
        """
        response = self._get_without_redirect(f"/repos/{repository}/zipball/{sha}")
        if response.status_code in (301, 302, 303, 307, 308):
            target = urlparse(response.headers.get("Location", ""))
            if target.scheme != "https" or target.hostname not in ARCHIVE_HOSTS:
                raise GitHubError("GitHub redirected the download to an unexpected address; it was not followed.")
            data = self._download(target.geturl())
        elif response.status_code >= 300:
            raise self._error(response)
        else:
            data = response.content
        return _python_files_from_zip(data)

    def _get_without_redirect(self, path: str) -> httpx.Response:
        try:
            return self._http.get(path)
        except httpx.TimeoutException as exc:
            raise GitHubError("GitHub did not answer in time.") from exc
        except httpx.HTTPError as exc:
            raise GitHubError(f"Cannot reach GitHub: {type(exc).__name__}.") from exc

    def _download(self, url: str) -> bytes:
        """GET a signed download address with a size limit and no credentials."""
        too_big = GitHubError(f"The repository is larger than {MAX_ARCHIVE_BYTES // 1_000_000} MB; no code context was built.")
        chunks, size = [], 0
        try:
            with httpx.Client(timeout=self._timeout * 4, transport=self._transport, follow_redirects=False) as plain:
                with plain.stream("GET", url) as stream:
                    if stream.status_code >= 300:
                        raise GitHubError(f"The repository download failed (HTTP {stream.status_code}).", stream.status_code)
                    if int(stream.headers.get("Content-Length", 0) or 0) > MAX_ARCHIVE_BYTES:
                        raise too_big
                    for chunk in stream.iter_bytes():
                        size += len(chunk)
                        if size > MAX_ARCHIVE_BYTES:
                            raise too_big
                        chunks.append(chunk)
        except httpx.TimeoutException as exc:
            raise GitHubError("The repository download timed out.") from exc
        except httpx.HTTPError as exc:
            raise GitHubError(f"The repository download failed: {type(exc).__name__}.") from exc
        return b"".join(chunks)

    def _fetch_text(self, repository: str, path: str, sha: str) -> str:
        """Raw text of one file at one commit. Raises GitHubError (with .status) when it cannot be read."""
        response = self._get(f"/repos/{repository}/contents/{path}", {"ref": sha}, raw=True)
        try:
            return response.content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise GitHubError(f"{path} is not UTF-8 text") from exc


def _python_files_from_zip(data: bytes) -> tuple[dict[str, str], list[str]]:
    """Python sources from a GitHub zipball (entries sit under one `owner-repo-sha/` folder). In memory only."""
    notes: list[str] = []
    files: dict[str, str] = {}
    total = 0
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise GitHubError("The repository download is not a valid archive.") from exc
    skipped_big = 0
    for entry in archive.infolist():
        if entry.is_dir() or not entry.filename.endswith(".py"):
            continue
        parts = PurePosixPath(entry.filename).parts[1:]  # drop the archive's root folder
        if not parts or ".." in parts or any(p in SKIP_CONTEXT_DIRS or p.endswith(".egg-info") for p in parts[:-1]):
            continue
        if entry.file_size > MAX_CONTEXT_FILE_CHARS:
            skipped_big += 1
            continue
        if len(files) >= MAX_CONTEXT_FILES or total >= MAX_CONTEXT_TOTAL_CHARS:
            notes.append(f"Repository context is partial: only the first {len(files)} Python files were read.")
            break
        try:
            with archive.open(entry) as handle:
                raw = handle.read(MAX_CONTEXT_FILE_CHARS + 1)  # never trust the declared size
            text = raw.decode("utf-8")
        except (UnicodeDecodeError, OSError, RuntimeError):
            continue
        if len(raw) > MAX_CONTEXT_FILE_CHARS:
            skipped_big += 1
            continue
        files["/".join(parts)] = text
        total += len(text)
    if skipped_big:
        notes.append(f"{skipped_big} Python file(s) larger than {MAX_CONTEXT_FILE_CHARS} characters were left out of the repository context.")
    return files, notes


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
