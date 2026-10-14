"""Repository context (callers, callees, tests): the archive download, the snapshot files, grounding and rendering.

MOCKED: `httpx.MockTransport` plays GitHub and codeload. The real download is checked by hand with `fetch-pr`.
"""

import io
import zipfile
from types import SimpleNamespace

import httpx
import pytest
from test_github import BASE, HEAD, FakeGitHub, client, file_json

from code_review_agent.github import (
    ARCHIVE_HOSTS,
    MAX_ARCHIVE_BYTES,
    MAX_CONTEXT_FILE_CHARS,
    GitHubClient,
    GitHubError,
)
from code_review_agent.loading import load_example, save_snapshot
from code_review_agent.pipeline import context_summary, render_related, shared_blocks
from code_review_agent.report import render_markdown
from code_review_agent.schemas import (
    Evidence,
    Finding,
    PullRequestMetadata,
    RelatedSnippet,
    ReviewInput,
    ReviewResult,
)
from code_review_agent.validation import check_grounding

SERVICE = "def f():\n    x = 2\n    return x\n"
CALLER = "from app import f\n\n\ndef job():\n    return f()\n"
TEST = "from app import f\n\n\ndef test_f():\n    assert f() == 2\n"


def make_zip(entries: dict[str, bytes | str], root="o-r-abc123") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in entries.items():
            archive.writestr(f"{root}/{name}" if root else name, content)
    return buffer.getvalue()


class Codeload:
    """GitHub's zipball endpoint: redirects to codeload, which serves the archive. Records every request."""

    def __init__(self, archive: bytes, location="https://codeload.github.com/o/r/legacy.zip/abc?token=signed", status=302):
        self.archive, self.location, self.status = archive, location, status
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if "/zipball/" in request.url.path:
            return httpx.Response(self.status, headers={"Location": self.location}) if self.status in (301, 302) \
                else httpx.Response(self.status, json={"message": "x"})
        if request.url.host == "codeload.github.com":
            return httpx.Response(200, content=self.archive, headers={"Content-Length": str(len(self.archive))})
        return httpx.Response(404, json={"message": "unexpected " + request.url.path})


def gh(fake, token="secret-token"):
    return GitHubClient(token=token, transport=httpx.MockTransport(fake))


# --------------------------------------------------------------------------- the download


def test_python_files_come_from_one_archive_and_the_token_never_reaches_codeload():
    fake = Codeload(make_zip({"app.py": SERVICE, "tests/test_app.py": TEST, "README.md": "hi"}))
    files, notes = gh(fake).fetch_python_sources("o/r", HEAD)
    assert files == {"app.py": SERVICE, "tests/test_app.py": TEST} and notes == []
    assert [c.url.host for c in fake.calls] == ["api.github.com", "codeload.github.com"]  # two requests in all
    assert fake.calls[0].headers["Authorization"] == "Bearer secret-token"
    assert "Authorization" not in fake.calls[1].headers  # the signed address needs no credentials


def test_vendored_directories_traversal_and_binary_files_are_skipped():
    big = "x = 1\n" * (MAX_CONTEXT_FILE_CHARS // 4)
    entries = {"pkg/a.py": "a = 1\n", "node_modules/x.py": "b = 1\n", ".venv/lib/y.py": "c = 1\n", "pkg/__pycache__/z.py": "d = 1\n",
               "big.py": big, "bin.py": b"\xff\xfe\x00bad", "pkg/q.egg-info/w.py": "e = 1\n", "../evil.py": "f = 1\n"}
    files, notes = gh(Codeload(make_zip(entries))).fetch_python_sources("o/r", HEAD)
    assert list(files) == ["pkg/a.py"]
    assert any("1 Python file(s) larger than" in n for n in notes)


def test_a_redirect_to_another_host_or_plain_http_is_not_followed():
    for location in ("https://evil.example/o/r.zip", "http://codeload.github.com/o/r.zip", "https://codeload.github.com.evil.example/x"):
        fake = Codeload(make_zip({"a.py": "a = 1\n"}), location=location)
        with pytest.raises(GitHubError, match="unexpected address"):
            gh(fake).fetch_python_sources("o/r", HEAD)
        assert [c.url.host for c in fake.calls] == ["api.github.com"]  # nothing was requested from the other host
    assert ARCHIVE_HOSTS == {"codeload.github.com"}


def test_an_oversized_download_is_refused_by_header_and_by_actual_size(monkeypatch):
    data = make_zip({"a.py": "a = 1\n"})
    monkeypatch.setattr("code_review_agent.github.MAX_ARCHIVE_BYTES", len(data) - 1)
    with pytest.raises(GitHubError, match="larger than"):
        gh(Codeload(data)).fetch_python_sources("o/r", HEAD)

    class NoLength(Codeload):  # a server that does not announce its size
        def __call__(self, request):
            response = super().__call__(request)
            response.headers.pop("Content-Length", None)
            return response

    with pytest.raises(GitHubError, match="larger than"):
        gh(NoLength(data)).fetch_python_sources("o/r", HEAD)
    assert MAX_ARCHIVE_BYTES == 40_000_000


def test_bad_archives_and_http_errors_become_actionable_errors():
    with pytest.raises(GitHubError, match="not a valid archive"):
        gh(Codeload(b"this is not a zip")).fetch_python_sources("o/r", HEAD)
    with pytest.raises(GitHubError, match="Not found"):
        gh(Codeload(b"", status=404)).fetch_python_sources("o/r", HEAD)


# ------------------------------------------------------------ inside fetch_pull_request


class FakeWithArchive(FakeGitHub):
    def __init__(self, archive: bytes | None, **kwargs):
        super().__init__(**kwargs)
        self.archive = archive

    def __call__(self, request):
        if "/zipball/" in request.url.path:
            self.calls.append(request)
            assert request.url.path.endswith(HEAD)  # pinned to the reviewed commit
            if self.archive is None:
                return httpx.Response(404, json={"message": "Not Found"})
            return httpx.Response(302, headers={"Location": "https://codeload.github.com/o/r/legacy.zip/x"})
        if request.url.host == "codeload.github.com":
            self.calls.append(request)
            return httpx.Response(200, content=self.archive)
        return super().__call__(request)


def test_a_pull_request_gets_its_related_code_and_facts():
    fake = FakeWithArchive(make_zip({"app.py": SERVICE, "job.py": CALLER, "tests/test_app.py": TEST}))
    snapshot = client(fake).fetch_pull_request("o/r", 7)
    assert {(s.kind, s.name) for s in snapshot.related_code} == {("caller", "job"), ("test", "test_f")}
    assert snapshot.related_facts == ["`f` (app.py) is called by 1 other repository function(s) and mentioned in 1 test function(s)."]
    assert snapshot.to_review_input().related_code == snapshot.related_code


def test_without_context_no_archive_is_requested():
    fake = FakeWithArchive(make_zip({"app.py": SERVICE}))
    snapshot = client(fake).fetch_pull_request("o/r", 7, with_context=False)
    assert snapshot.related_code == [] and not any("/zipball/" in c.url.path for c in fake.calls)


def test_a_failed_download_is_said_and_never_fails_the_review():
    snapshot = client(FakeWithArchive(None)).fetch_pull_request("o/r", 7)
    assert snapshot.related_code == [] and snapshot.diff
    assert any("Repository context" in line and "could not be retrieved" in line for line in snapshot.info)
    assert not any("Repository context" in n for n in snapshot.notes)  # it is not lost input, so not partial coverage


# --------------------------------------------------------------- the snapshot on disk


def related(path="job.py", start=4, end=5, kind="caller", symbol="f", name="job", text="def job():\n    return f()"):
    return RelatedSnippet(path=path, start_line=start, end_line=end, kind=kind, symbol=symbol, name=name, text=text)


def snapshot_with(related_code, facts):
    return SimpleNamespace(
        metadata=PullRequestMetadata(title="t", description="d", base_sha=BASE, head_sha=HEAD, repository="o/r", number=7),
        diff="diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1 @@\n-x\n+y\n",
        supporting_files=[], analysis_files=[], notes=[], rules=None, rules_source=None,
        related_code=related_code, related_facts=facts)


def test_related_code_survives_a_round_trip_through_the_snapshot_folder(tmp_path):
    save_snapshot(snapshot_with([related()], ["`f` is called by 1 other repository function(s)."]), tmp_path)
    _, review_input = load_example(tmp_path)
    assert review_input.related_code == [related()] and review_input.related_facts == ["`f` is called by 1 other repository function(s)."]


def test_a_second_fetch_without_context_leaves_no_stale_related_code(tmp_path):
    save_snapshot(snapshot_with([related()], ["fact"]), tmp_path)
    save_snapshot(snapshot_with([], []), tmp_path)
    assert not (tmp_path / "related.json").exists()
    assert load_example(tmp_path)[1].related_code == []


# ------------------------------------------------------------ what the model is shown


def review_input(snippets=(), facts=()):
    return ReviewInput(pr=PullRequestMetadata(title="t"), diff="diff --git a/app.py b/app.py\n--- a/app.py\n+++ b/app.py\n@@ -1 +1,2 @@\n x\n+y\n",
                       related_code=list(snippets), related_facts=list(facts))


def test_the_related_code_block_is_numbered_like_the_diff_and_says_what_it_is():
    text = render_related(review_input([related(start=4)], ["`f` is mentioned in no test function."]))
    assert "NOT part of this change" in text and "can match the wrong function" in text
    assert "- `f` is mentioned in no test function." in text
    assert "--- caller of `f`: job.py (lines 4-5) ---" in text
    assert "    4 | def job():" in text and "    5 |     return f()" in text


def test_the_block_is_shared_with_every_pass_only_when_there_is_something_to_show():
    record = SimpleNamespace(tool_runs=[], tool_findings=[])
    assert "RELATED CODE" not in shared_blocks(record, review_input())
    assert "RELATED CODE" in shared_blocks(record, review_input([related()]))
    assert "RELATED CODE" in shared_blocks(record, review_input(facts=["a fact"]))


def test_the_result_lists_the_context_and_the_report_shows_it():
    lines = context_summary(review_input([related()], ["a fact"]))
    assert lines == ["a fact", "caller of `f`: job.py:4-5 (`job`)"]
    text = render_markdown(ReviewResult(status="completed", context=lines))
    assert "## Repository context" in text and "- caller of `f`: job.py:4-5 (`job`)" in text
    assert "## Repository context" not in render_markdown(ReviewResult(status="completed"))


# --------------------------------------------------------------------------- grounding


def finding(file, line, quote="return f()"):
    return Finding(category="logic_defect", severity="low", file=file, line=line, title="t", explanation="e",
                   evidence=[Evidence(source="code", quote=quote)])


def test_a_finding_may_cite_related_code_that_was_shown():
    ri = review_input([related()])
    assert check_grounding([finding("job.py", 5)], None, ri) == []  # right file, line inside the snippet, quote in the snippet


def test_a_line_outside_the_snippet_or_an_unknown_file_is_still_flagged():
    ri = review_input([related()])
    outside = check_grounding([finding("job.py", 40)], None, ri)
    assert [p.kind.value for p in outside] == ["line_out_of_range"] and "outside the related code" in outside[0].message
    unknown = check_grounding([finding("other.py", 1)], None, ri)
    assert unknown[0].kind.value == "unknown_file" and "job.py" in unknown[0].message  # related files are listed as known


def test_a_changed_file_may_also_cite_an_unchanged_function_shown_as_related_code():
    other = related(path="app.py", start=10, end=11, kind="callee", text="def g():\n    return 1")
    ri = review_input([other])
    assert check_grounding([finding("app.py", 11, quote="return 1")], None, ri) == []
    assert check_grounding([finding("app.py", 30, quote="return 1")], None, ri)[0].kind.value == "line_not_in_diff"


def test_quotes_that_appear_nowhere_are_still_flagged_with_related_code_present():
    problems = check_grounding([finding("job.py", 5, quote="return something_invented()")], None, review_input([related()]))
    assert [p.kind.value for p in problems] == ["quote_not_found"]
