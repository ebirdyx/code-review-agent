"""The pull-request comment: safe to publish, one per PR, updated in place."""

import json

import httpx
import pytest

from code_review_agent.app import clients
from code_review_agent.app.cli import review as review_commands
from code_review_agent.connectors.github import GitHubClient, GitHubError
from code_review_agent.reporting.comment import (
    MARKER,
    MAX_COMMENT_CHARS,
    render_pr_comment,
)
from code_review_agent.schemas import (
    CriterionCheck,
    Evidence,
    Finding,
    PassSummary,
    ReviewedRevision,
    ReviewFailure,
    ReviewResult,
    RunSummary,
)


def finding(title="Boundary is wrong", explanation="`>` should be `>=`.", severity="high", quote="if total > 100:", **kw):
    return Finding(category="boundary_condition", severity=severity, file="shop/shipping.py", line=6, title=title,
                   explanation=explanation, evidence=[Evidence(source="code", quote=quote)], **kw)


def run(ticket="KAN-4: Free shipping"):
    return RunSummary(
        revision=ReviewedRevision(repository="o/r", pr_number=3, head_sha="a" * 40, url="https://github.com/o/r/pull/3"),
        case_id="c", created_at="2026-10-13T00:00:00+00:00", prompt_version="multi_v2", model="m", host="h", ticket=ticket)


def result(**kw):
    kw.setdefault("status", "completed")
    kw.setdefault("run", run())
    return ReviewResult(**kw)


# ------------------------------------------------------------------- rendering


def test_comment_starts_with_the_marker_and_lists_findings_and_criteria():
    r = result(findings=[finding()], criteria=[
        CriterionCheck(number=1, text="Orders of $100 or more ship free.", verdict="not_met", explanation="x")])
    text = render_pr_comment(r)
    assert text.startswith(MARKER)
    assert "KAN-4: Free shipping" in text and "**1 finding(s)**" in text
    assert "| 1 | Orders of $100 or more ship free. | NOT MET |" in text
    assert "**[HIGH]** Boundary is wrong" in text and "`shop/shipping.py:6`" in text
    assert "if total > 100:" in text and "can be wrong" in text  # evidence + disclaimer


def test_no_findings_is_not_presented_as_a_proof():
    text = render_pr_comment(result())
    assert "No findings." in text and "not a proof" in text


def test_a_failed_review_says_nothing_can_be_concluded():
    r = result(status="failed", error=ReviewFailure(kind="timeout", message="The model did not answer."))
    text = render_pr_comment(r)
    assert "did not run to completion" in text and "The model did not answer." in text
    assert "No findings" not in text


def test_failed_passes_and_missing_ticket_are_visible():
    r = result(run=run(ticket=None), passes=[PassSummary(name="security", status="failed", message="boom")])
    text = render_pr_comment(r)
    assert "no ticket linked" in text and "security" in text and "their findings are missing" in text


def test_findings_are_sorted_by_severity_and_capped():
    many = [finding(title=f"low {i}", severity="low") for i in range(20)] + [finding(title="the critical one", severity="critical")]
    text = render_pr_comment(result(findings=many))
    assert text.index("the critical one") < text.index("low 0")
    assert "6 more finding(s) are in the full report" in text


def test_tool_findings_are_labelled():
    assert "(static analysis)" in render_pr_comment(result(findings=[finding(source="tool")]))


# ---------------------------------------------------------------------- safety


def test_model_text_cannot_ping_people_inject_html_or_make_links():
    hostile = finding(
        title="Ping @octocat <img src=x onerror=alert(1)>",
        explanation="See [click](https://evil.example/x) ![p](https://evil.example/p.png) and https://evil.example @everyone | x",
    )
    text = render_pr_comment(result(findings=[hostile], run=run(ticket="KAN-1 @admin <b>x</b>")))
    assert "@octocat" not in text and "@everyone" not in text and "@admin" not in text
    assert "<img" not in text and "<b>" not in text
    assert "](https://evil" not in text and "https://evil" not in text and "![" not in text.replace("\\[", "")
    assert text.count("<details>") == 1  # only ours


def test_code_spans_stay_readable_but_tricks_with_backticks_do_not_hide_mentions():
    text = render_pr_comment(result(findings=[finding(
        explanation="Use `total >= 100` and `a<b`. Tricks: \\`@alice\\` and ``@bob` end")]))
    assert "`total >= 100`" in text and "`a<b`" in text and "&gt;" not in text
    assert "@alice" not in text and "@bob" not in text


def test_the_report_link_is_kept_only_when_it_is_a_plain_https_address():
    assert "https://github.com/o/r/actions/runs/1" in render_pr_comment(result(), report_hint="https://github.com/o/r/actions/runs/1")
    assert "evil" not in render_pr_comment(result(), report_hint="javascript:evil()")
    assert "evil" not in render_pr_comment(result(), report_hint="https://evil.example/)[x](https://evil2")


def test_a_quote_with_backticks_and_html_cannot_leave_its_code_fence():
    quote = "```\n</details>\n@octocat\n```"
    text = render_pr_comment(result(findings=[finding(quote=quote)]))
    start = text.index("<summary>")
    fence = next(line for line in text[start:].split("\n")[1:] if line)
    assert fence.startswith("````")  # longer than the quote's own backtick run


def test_a_huge_comment_is_shortened_below_the_github_limit():
    r = result(findings=[finding(explanation="x " * 5000) for _ in range(15)])
    assert len(render_pr_comment(r)) <= MAX_COMMENT_CHARS + 2000


# -------------------------------------------------------------- upsert on GitHub


class FakeGitHub:
    def __init__(self, comments=None, patch_status=200):
        self.comments = comments or []
        self.patch_status = patch_status
        self.calls = []

    def __call__(self, request):
        self.calls.append((request.method, request.url.path, json.loads(request.content) if request.content else None))
        if request.method == "GET":
            return httpx.Response(200, json=self.comments)
        if request.method == "PATCH":
            return httpx.Response(self.patch_status, json={"html_url": "https://github.com/o/r/pull/3#c1"})
        return httpx.Response(201, json={"html_url": "https://github.com/o/r/pull/3#c2"})


def client(fake, token="t"):
    return GitHubClient(token=token, transport=httpx.MockTransport(fake))


def test_first_run_creates_the_comment():
    fake = FakeGitHub(comments=[{"id": 9, "body": "someone else's remark"}])
    assert client(fake).upsert_comment("o/r", 3, MARKER + "\nhi", MARKER) == ("created", "https://github.com/o/r/pull/3#c2")
    assert [c[0] for c in fake.calls] == ["GET", "POST"] and fake.calls[1][1] == "/repos/o/r/issues/3/comments"


def test_next_run_updates_our_comment_instead_of_adding_another():
    fake = FakeGitHub(comments=[{"id": 9, "body": "remark"}, {"id": 12, "body": MARKER + "\nold review"}])
    assert client(fake).upsert_comment("o/r", 3, MARKER + "\nnew", MARKER)[0] == "updated"
    assert fake.calls[-1][:2] == ("PATCH", "/repos/o/r/issues/comments/12") and fake.calls[-1][2] == {"body": MARKER + "\nnew"}
    assert "POST" not in [c[0] for c in fake.calls]


def test_a_foreign_comment_copying_our_marker_is_not_edited_and_we_write_our_own():
    fake = FakeGitHub(comments=[{"id": 5, "body": MARKER + " fake"}], patch_status=403)
    assert client(fake).upsert_comment("o/r", 3, MARKER + "\nmine", MARKER)[0] == "created"


def test_posting_without_a_token_is_refused_before_any_write():
    fake = FakeGitHub()
    with pytest.raises(GitHubError, match="needs a token"):
        client(fake, token="").upsert_comment("o/r", 3, "x", MARKER)
    assert all(c[0] == "GET" for c in fake.calls)


def test_missing_permission_is_explained():
    def forbidden(request):
        return httpx.Response(200, json=[]) if request.method == "GET" else httpx.Response(403, json={})

    with pytest.raises(GitHubError, match="pull-requests: write"):
        GitHubClient(token="t", transport=httpx.MockTransport(forbidden)).upsert_comment("o/r", 3, "x", MARKER)


# --------------------------------------------------------------------- the CLI


class Args:
    def __init__(self, post):
        self.post_comment, self.report_link = post, "https://example.test/run/1"


def test_dry_run_writes_comment_md_and_never_calls_github(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(clients, "github_client", lambda: pytest.fail("must not contact GitHub in dry-run"))
    assert review_commands.publish_comment(Args(False), tmp_path, result(findings=[finding()])) is True
    assert (tmp_path / "comment.md").read_text(encoding="utf-8").startswith(MARKER)
    assert "not posted" in capsys.readouterr().out


def test_post_comment_publishes_and_reports_the_outcome(tmp_path, monkeypatch, capsys):
    fake = FakeGitHub()
    monkeypatch.setattr(clients, "github_client", lambda: client(fake))
    assert review_commands.publish_comment(Args(True), tmp_path, result(findings=[finding()])) is True
    assert "Comment created on o/r#3" in capsys.readouterr().out
    posted = fake.calls[-1][2]["body"]
    assert posted == (tmp_path / "comment.md").read_text(encoding="utf-8") and "example.test/run/1" in posted


def test_post_comment_failure_returns_false_with_a_message(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(clients, "github_client", lambda: client(FakeGitHub(), token=""))
    assert review_commands.publish_comment(Args(True), tmp_path, result()) is False
    assert "Cannot post the comment" in capsys.readouterr().err


def test_post_comment_needs_to_know_which_pull_request(tmp_path, capsys):
    local = result(run=RunSummary(case_id="c", created_at="t", prompt_version="p", model="m", host="h"))
    assert review_commands.publish_comment(Args(True), tmp_path, local) is False
    assert "does not identify a pull request" in capsys.readouterr().err


def test_a_met_criterion_that_a_finding_disagrees_with_carries_a_note():
    from code_review_agent.schemas import ProblemKind, ValidationProblem

    r = result(findings=[finding()], criteria=[
        CriterionCheck(number=1, text="Orders of $100 or more ship free.", verdict="met", explanation="x"),
        CriterionCheck(number=2, text="Under $100 pays the fee.", verdict="met", explanation="y")],
        problems=[ValidationProblem(criterion_index=0, kind=ProblemKind.INCONSISTENT_VERDICT, message="m")])
    text = render_pr_comment(r)
    assert "| 1 | Orders of $100 or more ship free. | MET (check: a finding disagrees) |" in text
    assert "| 2 | Under $100 pays the fee. | MET |" in text
