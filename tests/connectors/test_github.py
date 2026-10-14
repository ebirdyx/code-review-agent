"""Stage 6 tests: the read-only GitHub connector.

MOCKED: `httpx.MockTransport` plays GitHub, so these run offline. They prove our
parsing, pagination, error handling and honesty rules, not that GitHub behaves as
modelled. The separate real-API check is done by hand with `fetch-pr`.
"""

import json
from pathlib import Path

import httpx
import pytest

from code_review_agent.app import cli, clients
from code_review_agent.connectors.github import (
    GitHubClient,
    GitHubError,
    parse_pr_reference,
)
from code_review_agent.connectors.snapshot import load_example, save_snapshot
from code_review_agent.context.builder import build_context, split_diff
from code_review_agent.llm.client import ModelSettings
from code_review_agent.pipeline.single import run_review
from code_review_agent.pipeline.validation import _index_diff, finalize_review
from code_review_agent.reporting.report import render_markdown
from code_review_agent.schemas import SupportingFile

HEAD = "a" * 40
BASE = "b" * 40
PATCH = "@@ -1,2 +1,3 @@\n def f():\n-    return 1\n+    x = 2\n+    return x"


def pr_json(head=HEAD, state="open", changed=1):
    return {"title": "Fix f", "body": "Implements SHOP-1", "state": state, "merged": False,
            "changed_files": changed, "html_url": "https://github.com/o/r/pull/7",
            "head": {"sha": head}, "base": {"sha": BASE}}


def file_json(name="app.py", status="modified", patch=PATCH, **extra):
    return {"filename": name, "status": status, "patch": patch, "changes": 3, **extra}


class FakeGitHub:
    """Routes by path. `calls` records every request for assertions."""

    def __init__(self, files=None, contents=None, pr_sequence=None, status=None, rules=None):
        self.files = files if files is not None else [file_json()]
        self.contents = contents or {"app.py": "def f():\n    x = 2\n    return x\n"}
        self.rules = rules or {}  # team rules by path, served at the BASE commit only
        self.pr_sequence = list(pr_sequence or [pr_json(changed=len(self.files))])
        self.status = status  # force one HTTP error for every request
        self.calls: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        path = request.url.path
        if self.status:
            code, headers = self.status
            return httpx.Response(code, headers=headers, json={"message": "x"})
        if path.endswith("/pulls/7"):
            body = self.pr_sequence.pop(0) if len(self.pr_sequence) > 1 else self.pr_sequence[0]
            return httpx.Response(200, json=body)
        if path.endswith("/pulls/7/files"):
            page = int(request.url.params.get("page", 1))
            per = 2  # tiny pages to exercise pagination
            chunk = self.files[(page - 1) * per: page * per]
            headers = {}
            if page * per < len(self.files):
                headers["Link"] = f'<https://api.github.com/repos/o/r/pulls/7/files?per_page=2&page={page + 1}>; rel="next"'
            return httpx.Response(200, json=chunk, headers=headers)
        if "/contents/" in path:
            name = path.split("/contents/", 1)[1]
            assert request.headers["Accept"] == "application/vnd.github.raw+json"
            if name in (".review-agent/rules.md", "review-rules.md"):
                assert request.url.params["ref"] == BASE  # rules come from the base commit, never from the PR
                if name in self.rules:
                    return httpx.Response(200, content=self.rules[name].encode())
                return httpx.Response(404, json={"message": "Not Found"})
            assert request.url.params["ref"] == HEAD  # source is pinned to the reviewed commit
            if name in self.contents:
                value = self.contents[name]
                return httpx.Response(200, content=value if isinstance(value, bytes) else value.encode())
            return httpx.Response(404, json={"message": "Not Found"})
        return httpx.Response(404, json={"message": "unexpected " + path})


def client(fake, token=None):
    return GitHubClient(token=token, transport=httpx.MockTransport(fake))


# ------------------------------------------------------------------ rate limit


def test_rate_limit_reports_what_is_left_and_proves_the_connection():
    def handler(request):
        assert request.url.path == "/rate_limit"
        return httpx.Response(200, json={"resources": {"core": {"remaining": 42, "limit": 5000}}})

    assert GitHubClient(token="t", transport=httpx.MockTransport(handler)).rate_limit() == (42, 5000)


def test_rate_limit_with_a_bad_token_is_an_actionable_error():
    with pytest.raises(GitHubError, match="refused the token"):
        GitHubClient(token="bad", transport=httpx.MockTransport(lambda r: httpx.Response(401))).rate_limit()


# ------------------------------------------------------------- reference parsing


@pytest.mark.parametrize("text", ["o/r#7", "https://github.com/o/r/pull/7", "https://github.com/o/r/pull/7/", " o/r#7 "])
def test_pr_reference_forms(text):
    assert parse_pr_reference(text) == ("o/r", 7)


@pytest.mark.parametrize("text", ["", "o/r", "o/r#", "7", "https://example.com/o/r/pull/7", "o/r#x"])
def test_bad_pr_reference_is_rejected(text):
    with pytest.raises(GitHubError):
        parse_pr_reference(text)


# ------------------------------------------------------------------ happy path


def test_snapshot_has_revision_diff_and_pinned_source():
    snap = client(FakeGitHub()).fetch_pull_request("o/r", 7)
    assert snap.metadata.head_sha == HEAD and snap.metadata.base_sha == BASE
    assert (snap.metadata.repository, snap.metadata.number) == ("o/r", 7)
    assert snap.metadata.title == "Fix f" and "SHOP-1" in snap.metadata.description
    assert [s.path for s in snap.supporting_files] == ["app.py"]
    assert snap.notes == []


def test_built_diff_is_understood_by_the_context_builder_and_line_index():
    snap = client(FakeGitHub()).fetch_pull_request("o/r", 7)
    assert [f.path for f in split_diff(snap.diff)] == ["app.py"]
    shown, _ = _index_diff(snap.diff)
    assert shown["app.py"] == {1: "def f():", 2: "    x = 2", 3: "    return x"}
    ctx = build_context(None, snap.to_review_input())
    assert "    2 | +    x = 2" in ctx.user  # numbered by the same code as local diffs


def test_multiple_pages_are_followed():
    files = [file_json(f"m{i}.py") for i in range(5)]
    fake = FakeGitHub(files=files, contents={f"m{i}.py": "x = 1\n" for i in range(5)})
    snap = client(fake).fetch_pull_request("o/r", 7, max_files=100, with_source=False)
    assert snap.diff.count("diff --git") == 5
    assert sum(r.url.path.endswith("/files") for r in fake.calls) == 3  # 2 + 2 + 1


def test_oversized_pr_is_cut_at_max_files_and_says_so():
    files = [file_json(f"m{i}.py") for i in range(5)]
    snap = client(FakeGitHub(files=files, pr_sequence=[pr_json(changed=5)])).fetch_pull_request(
        "o/r", 7, max_files=2, with_source=False)
    assert snap.diff.count("diff --git") == 2
    assert any("first 2 of 5" in n for n in snap.notes)


def test_no_token_means_no_authorization_header_and_token_means_bearer():
    fake = FakeGitHub()
    client(fake, token="").fetch_pull_request("o/r", 7, with_source=False)
    assert all("authorization" not in r.headers for r in fake.calls)
    fake = FakeGitHub()
    client(fake, token="ghp_secret").fetch_pull_request("o/r", 7, with_source=False)
    assert all(r.headers["authorization"] == "Bearer ghp_secret" for r in fake.calls)
    assert all(r.headers["x-github-api-version"] == "2022-11-28" for r in fake.calls)


# ----------------------------------------------------------- unavailable content


def test_file_without_patch_is_reported_not_silently_skipped():
    files = [file_json("a.py"), file_json("logo.bin", status="added", patch=None, changes=0)]
    snap = client(FakeGitHub(files=files)).fetch_pull_request("o/r", 7, with_source=False)
    assert "logo.bin" not in snap.diff
    assert any("logo.bin" in n and "No textual patch" in n for n in snap.notes)


def test_pure_rename_is_not_flagged_as_missing():
    files = [file_json("a.py"), file_json("new.py", status="renamed", patch=None, changes=0, previous_filename="old.py")]
    snap = client(FakeGitHub(files=files)).fetch_pull_request("o/r", 7, with_source=False)
    assert "rename from old.py" in snap.diff and snap.notes == []


def test_added_and_removed_files_use_dev_null():
    files = [file_json("new.py", status="added", patch="@@ -0,0 +1 @@\n+x = 1"),
             file_json("gone.py", status="removed", patch="@@ -1 +0,0 @@\n-x = 1")]
    snap = client(FakeGitHub(files=files)).fetch_pull_request("o/r", 7, with_source=False)
    assert "--- /dev/null\n+++ b/new.py" in snap.diff
    assert "--- a/gone.py\n+++ /dev/null" in snap.diff
    assert [f.path for f in split_diff(snap.diff)] == ["new.py", "gone.py"]


def test_no_reviewable_diff_at_all_is_an_error():
    with pytest.raises(GitHubError, match="no textual diff"):
        client(FakeGitHub(files=[file_json("x.bin", patch=None, changes=0)])).fetch_pull_request("o/r", 7)


def test_source_that_is_too_large_binary_missing_or_a_lockfile_is_noted_or_skipped():
    files = [file_json("big.py"), file_json("bin.py"), file_json("gone.py"), file_json("uv.lock"), file_json("ok.py")]
    fake = FakeGitHub(files=files, pr_sequence=[pr_json(changed=5)], contents={
        "big.py": "x" * 25_000, "bin.py": b"\xff\xfe\x00bad", "ok.py": "y = 1\n"})
    snap = client(fake).fetch_pull_request("o/r", 7)
    assert [s.path for s in snap.supporting_files] == ["ok.py"]
    text = " ".join(snap.notes)
    assert "big.py" in text and "bin.py" in text and "gone.py" in text
    assert "uv.lock" not in text  # silently excluded from source fetching, still in the diff
    assert "uv.lock" in snap.diff


def test_source_file_limit_is_reported():
    files = [file_json(f"m{i}.py") for i in range(4)]
    fake = FakeGitHub(files=files, pr_sequence=[pr_json(changed=4)], contents={f"m{i}.py": "x\n" for i in range(4)})
    snap = client(fake).fetch_pull_request("o/r", 7, max_source_files=2)
    assert len(snap.supporting_files) == 2
    assert any("2 changed file(s) not fetched" in n for n in snap.notes)


def test_closed_pr_is_noted():
    snap = client(FakeGitHub(pr_sequence=[pr_json(state="closed")])).fetch_pull_request("o/r", 7, with_source=False)
    assert any("closed" in line for line in snap.info)
    assert snap.notes == []  # information, not missing content: coverage stays complete
    assert build_context(None, snap.to_review_input()).coverage.complete


# ------------------------------------------------------------- consistency + errors


def test_push_during_read_is_refused():
    fake = FakeGitHub(pr_sequence=[pr_json(head=HEAD), pr_json(head="c" * 40)])
    with pytest.raises(GitHubError, match="changed while it was being read"):
        client(fake).fetch_pull_request("o/r", 7, with_source=False)


@pytest.mark.parametrize(
    ("status", "headers", "token", "expected"),
    [
        (404, {}, None, "Private repositories need GITHUB_TOKEN"),
        (404, {}, "t", "does not exist or is not visible"),
        (401, {}, "t", "refused the token"),
        (403, {"X-RateLimit-Remaining": "0"}, None, "60 requests/hour"),
        (403, {"X-RateLimit-Remaining": "0"}, "t", "rate limit"),
        (500, {}, None, "HTTP 500"),
    ],
)
def test_http_errors_have_actionable_messages(status, headers, token, expected):
    with pytest.raises(GitHubError) as info:
        client(FakeGitHub(status=(status, headers)), token=token).fetch_pull_request("o/r", 7)
    assert expected in str(info.value)


def test_timeout_and_network_errors_are_clear():
    def boom(request):
        raise httpx.ConnectTimeout("slow")

    with pytest.raises(GitHubError, match="did not answer in time"):
        GitHubClient(transport=httpx.MockTransport(boom)).fetch_pull_request("o/r", 7)

    def down(request):
        raise httpx.ConnectError("no route")

    with pytest.raises(GitHubError, match="Cannot reach GitHub"):
        GitHubClient(transport=httpx.MockTransport(down)).fetch_pull_request("o/r", 7)


def test_redirects_are_not_followed_so_the_token_cannot_leak_elsewhere():
    def redirect(request):
        return httpx.Response(302, headers={"Location": "https://evil.example/steal"})

    with pytest.raises(GitHubError, match="HTTP 302"):
        GitHubClient(token="ghp_secret", transport=httpx.MockTransport(redirect)).fetch_pull_request("o/r", 7)


def test_non_json_answer_is_a_clear_error():
    def html(request):
        return httpx.Response(200, content=b"<html>proxy login</html>")

    with pytest.raises(GitHubError, match="not JSON"):
        GitHubClient(transport=httpx.MockTransport(html)).fetch_pull_request("o/r", 7)


def test_token_never_appears_in_error_messages():
    with pytest.raises(GitHubError) as info:
        client(FakeGitHub(status=(401, {})), token="ghp_topsecret").fetch_pull_request("o/r", 7)
    assert "ghp_topsecret" not in str(info.value)


# ----------------------------------------------------- snapshot, review and report


def test_snapshot_roundtrip_keeps_revision_and_notes_and_marks_partial_coverage(tmp_path):
    files = [file_json("a.py"), file_json("logo.bin", status="added", patch=None, changes=0)]
    snap = client(FakeGitHub(files=files, contents={"a.py": "def f(): ...\n"})).fetch_pull_request("o/r", 7)
    save_snapshot(snap, tmp_path / "snap")
    ticket, review_input = load_example(tmp_path / "snap")
    assert ticket is None
    assert review_input.pr.head_sha == HEAD and review_input.pr.repository == "o/r"
    assert review_input.input_notes == snap.notes
    ctx = build_context(None, review_input)
    assert not ctx.coverage.complete
    assert any("logo.bin" in o for o in ctx.coverage.omitted)
    assert "OMITTED: No textual patch for logo.bin" in ctx.user  # the model is told too


def test_snapshot_refuses_to_write_outside_its_folder(tmp_path):
    snap = client(FakeGitHub()).fetch_pull_request("o/r", 7, with_source=False)
    snap.supporting_files.append(SupportingFile(path="../../evil.py", content="x"))
    with pytest.raises(ValueError, match="outside the snapshot folder"):
        save_snapshot(snap, tmp_path / "snap")
    assert not (tmp_path / "evil.py").exists()


class _Recorder:
    settings = ModelSettings(model="fake")

    def complete(self, system, user):
        from code_review_agent.llm.client import ModelResponse
        return ModelResponse('{"findings": [], "limitations": []}', 1.0, 10, 5, "stop")


def test_report_names_the_exact_revision_reviewed(tmp_path):
    snap = client(FakeGitHub()).fetch_pull_request("o/r", 7)
    review_input = snap.to_review_input()
    record, _ = run_review("o-r-pr7", None, review_input, _Recorder(), 30000)
    assert record.revision.head_sha == HEAD and record.revision.base_sha == BASE
    text = render_markdown(finalize_review(record, None, review_input))
    assert f"**Revision reviewed:** o/r#7, head `{HEAD}`, base `{BASE}`" in text
    assert "https://github.com/o/r/pull/7" in text
    assert "No Jira ticket was provided" in text  # a PR without a ticket stays visible


def test_local_examples_have_no_revision():
    ticket, review_input = load_example(Path(__file__).resolve().parents[2] / "examples" / "free-shipping-faulty")
    record, _ = run_review("c", ticket, review_input, _Recorder(), 30000)
    assert record.revision is None
    assert "Revision reviewed" not in render_markdown(finalize_review(record, ticket, review_input))


# ----------------------------------------------------------------------------- CLI


def test_fetch_pr_cli_saves_a_reviewable_snapshot(tmp_path, monkeypatch, capsys):
    fake = FakeGitHub()
    monkeypatch.setattr(clients, "github_client", lambda: GitHubClient(transport=httpx.MockTransport(fake)))
    ticket_file = tmp_path / "t.json"
    ticket_file.write_text(json.dumps({"key": "SHOP-1", "title": "T", "acceptance_criteria": ["f returns 2"]}), encoding="utf-8")
    code = cli.main(["fetch-pr", "o/r#7", "--snapshots", str(tmp_path / "snaps"), "--ticket", str(ticket_file)])
    assert code == 0
    folder = tmp_path / "snaps" / f"o-r-pr7-{HEAD[:7]}"
    assert (folder / "change.diff").exists() and (folder / "ticket.json").exists()
    ticket, review_input = load_example(folder)
    assert ticket.key == "SHOP-1" and review_input.pr.head_sha == HEAD
    assert HEAD in capsys.readouterr().out


def test_fetch_pr_cli_reports_errors_without_traceback(tmp_path, monkeypatch, capsys):
    fake = FakeGitHub(status=(404, {}))
    monkeypatch.setattr(clients, "github_client", lambda: GitHubClient(transport=httpx.MockTransport(fake)))
    assert cli.main(["fetch-pr", "o/r#7", "--snapshots", str(tmp_path)]) == 1
    assert "Cannot fetch the pull request" in capsys.readouterr().err
    assert cli.main(["fetch-pr", "garbage", "--snapshots", str(tmp_path)]) == 1


def test_review_pr_cli_end_to_end_with_fake_github_and_fake_ollama(tmp_path, monkeypatch):
    from tests.llm.test_model_client import FakeOllama

    fake = FakeGitHub()
    monkeypatch.setattr(clients, "github_client", lambda: GitHubClient(transport=httpx.MockTransport(fake)))
    server = FakeOllama(content='{"findings": [], "limitations": []}')
    try:
        code = cli.main(["review-pr", "o/r#7", "--snapshots", str(tmp_path / "s"), "--runs", str(tmp_path / "r"),
                         "--host", server.host, "--model", "fake"])
    finally:
        server.close()
    assert code == 0
    report = next((tmp_path / "r").rglob("report.md")).read_text(encoding="utf-8")
    assert HEAD in report
