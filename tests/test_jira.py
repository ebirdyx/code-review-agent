"""Stage 7 tests: the read-only Jira connector.

MOCKED: `httpx.MockTransport` plays Jira Cloud, so these run offline. They prove our
parsing, field detection, error handling and honesty rules. They do NOT prove that a
real Jira site returns exactly these shapes: run `review-agent fetch-ticket KEY`
against your site for that.
"""

import base64
import json

import httpx
import pytest
from test_github import HEAD, FakeGitHub  # reuse the fake GitHub from the Stage 6 tests

from code_review_agent.app import cli, clients
from code_review_agent.connectors.jira import (
    JiraClient,
    JiraError,
    adf_to_text,
    criteria_from_description,
    extract_issue_keys,
    merge_tickets,
    resolve_ticket,
    split_criteria,
)
from code_review_agent.connectors.snapshot import load_example
from code_review_agent.context.builder import build_context
from code_review_agent.pipeline.validation import check_grounding
from code_review_agent.schemas import (
    Finding,
    PullRequestMetadata,
    SupportingFile,
    Ticket,
)

# ------------------------------------------------------------------ ADF builders


def text(t):
    return {"type": "text", "text": t}


def para(t):
    return {"type": "paragraph", "content": [text(t)]}


def bullets(*items, kind="bulletList"):
    return {"type": kind, "content": [{"type": "listItem", "content": [para(i)]} for i in items]}


def doc(*blocks):
    return {"type": "doc", "version": 1, "content": list(blocks)}


def heading(t):
    return {"type": "heading", "attrs": {"level": 2}, "content": [text(t)]}


# ------------------------------------------------------------------- ADF -> text


def test_adf_paragraphs_lists_and_headings():
    node = doc(heading("Goal"), para("Free shipping."), bullets("one", "two"), bullets("a", "b", kind="orderedList"))
    assert adf_to_text(node) == "Goal\nFree shipping.\n- one\n- two\n1. a\n2. b"


def test_adf_nested_list_and_inline_nodes():
    nested = {"type": "bulletList", "content": [{"type": "listItem", "content": [
        para("parent"), bullets("child")]}]}
    assert adf_to_text(doc(nested)) == "- parent\n  - child"
    inline = {"type": "paragraph", "content": [text("ping "), {"type": "mention", "attrs": {"text": "@ann"}},
                                               {"type": "hardBreak"}, {"type": "inlineCard", "attrs": {"url": "https://x.y"}}]}
    assert adf_to_text(doc(inline)) == "ping @ann\nhttps://x.y"


def test_adf_table_and_unknown_nodes_keep_their_text():
    table = {"type": "table", "content": [{"type": "tableRow", "content": [
        {"type": "tableCell", "content": [para("A")]}, {"type": "tableCell", "content": [para("B")]}]}]}
    assert adf_to_text(doc(table)) == "A | B"
    panel = {"type": "panel", "attrs": {"panelType": "info"}, "content": [para("inside a panel")]}
    assert adf_to_text(doc(panel)) == "inside a panel"


def test_adf_accepts_none_plain_strings_and_garbage():
    assert adf_to_text(None) == "" and adf_to_text("plain") == "plain"
    assert adf_to_text(42) == "42"


# --------------------------------------------------------------------- criteria


def test_split_criteria_removes_bullets_and_numbers():
    assert split_criteria("- one\n* two\n\n3. three\n4) four\nplain") == ["one", "two", "three", "four", "plain"]


@pytest.mark.parametrize(
    "description",
    [
        "Intro\n\nAcceptance criteria:\n- A\n- B\n\nNotes\nmore",
        "Intro\n## Acceptance criteria\n1. A\n2. B\n## Notes\n- not a criterion",
        "Intro\nh3. Acceptance Criteria\n* A\n* B",
        "Intro\n**Acceptance criteria**\n- A\n- B\nText right after",
        "Contexte\nCritères d'acceptation :\n- A\n- B",
        "Contexte\nCritères d’acceptation\n- A\n- B",
    ],
)
def test_criteria_section_in_description(description):
    assert criteria_from_description(description) == ["A", "B"]


def test_no_criteria_section_means_no_criteria_not_guessed_ones():
    assert criteria_from_description("The cart should be fast.\n- not under a heading") == []
    assert criteria_from_description("Acceptance criteria:\n\nNotes") == []


# ---------------------------------------------------------------------- linking


def pr(title="", body=""):
    return PullRequestMetadata(title=title or "t", description=body)


def test_projects_filter_keeps_only_real_ticket_keys():
    p = pr("SHOP-1: fix", "Uses UTF-8 and SHA-256. Also relates to APP-7 and SHOP-1 again, OTHER-3.")
    assert extract_issue_keys(p, ["SHOP", "APP"]) == ["SHOP-1", "APP-7"]


def test_without_projects_only_explicit_links_count():
    assert extract_issue_keys(pr("Fix UTF-8 handling", "Hashes with SHA-256. See OTHER-3.")) == []
    assert extract_issue_keys(pr("SHOP-1: fix", "")) == ["SHOP-1"]
    assert extract_issue_keys(pr("[SHOP-2] fix", "")) == ["SHOP-2"]
    assert extract_issue_keys(pr("fix", "text\nJira: SHOP-3, SHOP-4\nmore")) == ["SHOP-3", "SHOP-4"]
    assert extract_issue_keys(pr("SHOP-1: fix", "Ticket: SHOP-1; APP-9")) == ["SHOP-1", "APP-9"]


# ----------------------------------------------------------------------- client


def issue_json(key="SHOP-1", summary="Free shipping", description=None, fields=None, names=None):
    all_fields = {"summary": summary, "description": description, **(fields or {})}
    return {"key": key, "fields": all_fields, "names": {"summary": "Summary", "description": "Description", **(names or {})}}


class FakeJira:
    def __init__(self, issues=None, status=None):
        self.issues = issues or {}
        self.status = status  # (code, headers) for every request
        self.calls: list[httpx.Request] = []

    def __call__(self, request):
        self.calls.append(request)
        if self.status:
            code, headers = self.status
            return httpx.Response(code, headers=headers, json={"errorMessages": ["x"]})
        key = request.url.path.rsplit("/", 1)[-1]
        if key in self.issues:
            return httpx.Response(200, json=self.issues[key])
        return httpx.Response(404, json={"errorMessages": ["Issue does not exist"]})


def jira(fake, **kwargs):
    return JiraClient(base_url="https://site.atlassian.net", email="me@x.org", token="tok-secret",
                      transport=httpx.MockTransport(fake), **kwargs)


def test_request_shape_and_basic_auth():
    fake = FakeJira({"SHOP-1": issue_json()})
    jira(fake).fetch_issue("SHOP-1")
    req = fake.calls[0]
    assert req.url.path == "/rest/api/3/issue/SHOP-1"
    assert req.url.params["expand"] == "names"
    expected = base64.b64encode(b"me@x.org:tok-secret").decode()
    assert req.headers["authorization"] == f"Basic {expected}"


def test_criteria_from_a_field_found_by_its_display_name():
    data = issue_json(fields={"customfield_10042": doc(bullets("Orders of $100 ship free", "Under $100 pay"))},
                      names={"customfield_10042": "Acceptance Criteria"})
    got = jira(FakeJira({"SHOP-1": data})).fetch_issue("SHOP-1")
    assert got.ticket.acceptance_criteria == ["Orders of $100 ship free", "Under $100 pay"]
    assert got.criteria_source == "field 'Acceptance Criteria' (customfield_10042)"
    assert got.ticket.key == "SHOP-1" and got.ticket.title == "Free shipping"


def test_configured_field_by_id_and_by_name():
    data = issue_json(fields={"customfield_9": "- X\n- Y"}, names={"customfield_9": "Definition of done"})
    by_id = jira(FakeJira({"SHOP-1": data}), acceptance_field="customfield_9").fetch_issue("SHOP-1")
    by_name = jira(FakeJira({"SHOP-1": data}), acceptance_field="definition of done").fetch_issue("SHOP-1")
    assert by_id.ticket.acceptance_criteria == by_name.ticket.acceptance_criteria == ["X", "Y"]


def test_configured_field_that_does_not_exist_is_reported_not_ignored():
    got = jira(FakeJira({"SHOP-1": issue_json()}), acceptance_field="customfield_404").fetch_issue("SHOP-1")
    assert got.ticket.acceptance_criteria == []
    assert "does not exist on this issue" in got.criteria_source


def test_falls_back_to_a_description_section():
    desc = doc(para("Context."), para("Acceptance criteria:"), bullets("A", "B"))
    got = jira(FakeJira({"SHOP-1": issue_json(description=desc)})).fetch_issue("SHOP-1")
    assert got.ticket.acceptance_criteria == ["A", "B"]
    assert "description" in got.criteria_source
    assert "Acceptance criteria:" in got.ticket.description  # description is kept intact


def test_empty_field_falls_back_to_description_and_then_to_nothing():
    names = {"customfield_1": "Acceptance Criteria"}
    desc = doc(para("Acceptance criteria:"), bullets("From description"))
    data = issue_json(description=desc, fields={"customfield_1": None}, names=names)
    assert jira(FakeJira({"SHOP-1": data})).fetch_issue("SHOP-1").ticket.acceptance_criteria == ["From description"]
    nothing = issue_json(description=doc(para("Just text.")), fields={"customfield_1": None}, names=names)
    got = jira(FakeJira({"SHOP-1": nothing})).fetch_issue("SHOP-1")
    assert got.ticket.acceptance_criteria == [] and "exists but is empty" in got.criteria_source


def test_missing_everything_is_reported_as_empty_criteria_with_a_reason():
    got = jira(FakeJira({"SHOP-1": issue_json(description=None)})).fetch_issue("SHOP-1")
    assert got.ticket.acceptance_criteria == [] and got.ticket.description == ""
    assert "no acceptance-criteria field" in got.criteria_source


# ----------------------------------------------------------------------- errors


@pytest.mark.parametrize(
    ("status", "headers", "expected"),
    [
        (401, {}, "refused the credentials"),
        (403, {}, "forbidden"),
        (404, {}, "not found (404)"),
        (429, {"Retry-After": "30"}, "retry after 30 s"),
        (500, {}, "HTTP 500"),
        (302, {"Location": "https://evil.example"}, "redirect"),
    ],
)
def test_http_errors_are_actionable(status, headers, expected):
    with pytest.raises(JiraError) as info:
        jira(FakeJira(status=(status, headers))).fetch_issue("SHOP-1")
    assert expected in str(info.value)
    assert "tok-secret" not in str(info.value)


def test_timeout_connection_and_non_json():
    def slow(request):
        raise httpx.ReadTimeout("slow")

    def down(request):
        raise httpx.ConnectError("no route")

    def html(request):
        return httpx.Response(200, content=b"<html>login</html>")

    for handler, expected in ((slow, "did not answer in time"), (down, "Cannot reach Jira"), (html, "not JSON")):
        client = JiraClient("https://site.atlassian.net", "a@b.c", "t", transport=httpx.MockTransport(handler))
        with pytest.raises(JiraError, match=expected):
            client.fetch_issue("SHOP-1")


@pytest.mark.parametrize(
    "url",
    ["https://<name>.atlassian.net", "myteam.atlassian.net", "https://my team.atlassian.net", "ftp://x.atlassian.net", "https://"],
)
def test_placeholder_or_malformed_base_url_is_rejected_before_any_request(url):
    with pytest.raises(JiraError, match="JIRA_BASE_URL"):
        JiraClient(base_url=url, email="a@b.c", token="t")


def test_unreachable_host_error_names_the_host_the_reason_and_hides_credentials():
    def dns_failure(request):
        raise httpx.ConnectError("[Errno 11001] getaddrinfo failed")

    client = JiraClient("https://wrong-name.atlassian.net", "me@x.org", "tok-secret", transport=httpx.MockTransport(dns_failure))
    with pytest.raises(JiraError) as info:
        client.fetch_issue("SHOP-1")
    message = str(info.value)
    assert "wrong-name.atlassian.net" in message and "getaddrinfo" in message
    assert "spelling of the site name" in message
    assert "tok-secret" not in message and "me@x.org" not in message


def test_a_certificate_error_is_explained_as_a_misspelled_site_name():
    # The real typo we hit: "pami.braholli" instead of "pamibraholli" gives a cryptic SSL error.
    def bad_cert(request):
        raise httpx.ConnectError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: Hostname mismatch")

    client = JiraClient("https://pami.braholli.atlassian.net", "a@b.c", "t", transport=httpx.MockTransport(bad_cert))
    with pytest.raises(JiraError) as info:
        client.fetch_issue("KAN-4")
    assert "probably misspelled" in str(info.value) and "dots included" in str(info.value)


def test_whoami_returns_the_account_name_without_touching_a_ticket():
    fake = FakeJira()
    fake.issues = {}

    def handler(request):
        fake.calls.append(request)
        return httpx.Response(200, json={"displayName": "Pamela B.", "accountId": "123"})

    client = JiraClient("https://site.atlassian.net", "a@b.c", "t", transport=httpx.MockTransport(handler))
    assert client.whoami() == "Pamela B."
    assert fake.calls[0].url.path == "/rest/api/3/myself" and len(fake.calls) == 1


@pytest.mark.parametrize(("status", "expected"), [(401, "refused the credentials"), (404, "exact site URL"),
                                                   (403, "exact site URL"), (500, "HTTP 500")])
def test_whoami_errors_are_actionable(status, expected):
    with pytest.raises(JiraError, match=expected):
        jira(FakeJira(status=(status, {}))).whoami()


def test_whoami_with_a_non_json_answer_and_an_unreachable_host():
    def html(request):
        return httpx.Response(200, content=b"<html>login</html>")

    with pytest.raises(JiraError, match="not JSON"):
        JiraClient("https://site.atlassian.net", "a@b.c", "t", transport=httpx.MockTransport(html)).whoami()

    def down(request):
        raise httpx.ConnectError("no route")

    with pytest.raises(JiraError, match="Cannot reach Jira"):
        JiraClient("https://site.atlassian.net", "a@b.c", "t", transport=httpx.MockTransport(down)).whoami()


def test_doctor_reports_each_connection_and_the_exit_code_follows(monkeypatch, capsys):
    from code_review_agent.connectors.github import GitHubClient as RealGitHub

    monkeypatch.setenv("OLLAMA_API_KEY", "k")
    monkeypatch.setattr(clients, "jira_client", lambda: JiraClient("https://site.atlassian.net", "a@b.c", "t", transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"displayName": "Pamela B."}))))
    monkeypatch.setattr(clients, "github_client", lambda: RealGitHub(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"resources": {"core": {"remaining": 57, "limit": 60}}}))))
    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert "OK     Model" in out and "key OLLAMA_API_KEY is set" in out
    assert "logged in as 'Pamela B.' at site.atlassian.net" in out
    assert "57/60 requests left" in out and "no token (public repositories only)" in out
    assert "ruff" in out and "bandit" in out and "All connections OK." in out
    assert "t" != "Pamela B."  # the token never appears
    assert "k\n" not in out


def test_doctor_flags_a_missing_key_a_bad_jira_login_and_unreachable_github(monkeypatch, capsys):
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    monkeypatch.setattr(clients, "jira_client", lambda: JiraClient("https://site.atlassian.net", "a@b.c", "secret-token",
                                                              transport=httpx.MockTransport(lambda r: httpx.Response(401))))

    def github_down(request):
        raise httpx.ConnectError("no route")

    from code_review_agent.connectors.github import GitHubClient as RealGitHub

    monkeypatch.setattr(clients, "github_client", lambda: RealGitHub(transport=httpx.MockTransport(github_down)))
    assert cli.main(["doctor"]) == 1
    out = capsys.readouterr().out
    assert "FAILED Model" in out and "NOT set" in out
    assert "FAILED Jira" in out and "refused the credentials" in out
    assert "FAILED GitHub" in out and "Cannot reach GitHub" in out
    assert "3 problem(s)" in out and "secret-token" not in out


def test_doctor_treats_missing_jira_settings_as_optional(monkeypatch, capsys):
    from code_review_agent.connectors.github import GitHubClient as RealGitHub

    monkeypatch.setenv("OLLAMA_API_KEY", "k")
    for name in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(clients, "github_client", lambda: RealGitHub(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"resources": {"core": {"remaining": 1, "limit": 60}}}))))
    assert cli.main(["doctor"]) == 0  # not configured is not a failure
    assert "n/a    Jira" in capsys.readouterr().out


def test_bad_key_syntax_never_reaches_the_network():
    fake = FakeJira()
    with pytest.raises(JiraError, match="not a Jira issue key"):
        jira(fake).fetch_issue("../../admin")
    assert fake.calls == []


def test_missing_configuration_lists_what_to_set(monkeypatch):
    for name in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(JiraError) as info:
        JiraClient()
    assert all(n in str(info.value) for n in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"))


# --------------------------------------------------------- PR -> tickets (resolve)


def ticket(key, *criteria, title=None):
    return Ticket(key=key, title=title or f"Title {key}", description=f"About {key}", acceptance_criteria=list(criteria))


def test_merge_keeps_each_criterion_traceable():
    merged = merge_tickets([ticket("SHOP-1", "A"), ticket("APP-2", "B", "C")])
    assert merged.key == "SHOP-1"
    assert merged.acceptance_criteria == ["[SHOP-1] A", "[APP-2] B", "[APP-2] C"]
    assert "SHOP-1: Title SHOP-1 | APP-2: Title APP-2" == merged.title
    assert merge_tickets([]) is None
    single = ticket("SHOP-1", "A")
    assert merge_tickets([single]) is single


def issues_for(*keys, criteria=("Crit",)):
    return {k: issue_json(key=k, summary=f"Title {k}", description=doc(para("Acceptance criteria:"), bullets(*criteria)))
            for k in keys}


def test_no_link_is_a_visible_gap_not_a_guess():
    res = resolve_ticket(jira(FakeJira()), pr("Fix things", "no ticket here"))
    assert res.ticket is None and res.keys == []
    assert "No Jira key was found" in res.notes[0] and "Jira: KEY-123" in res.notes[0]


def test_single_linked_ticket():
    res = resolve_ticket(jira(FakeJira(issues_for("SHOP-1"))), pr("SHOP-1: fix"))
    assert res.ticket.key == "SHOP-1" and res.ticket.acceptance_criteria == ["Crit"]
    assert res.notes == [] and "from section" in res.info[0]


def test_multiple_tickets_are_combined_and_announced():
    res = resolve_ticket(jira(FakeJira(issues_for("SHOP-1", "SHOP-2"))), pr("x", "Jira: SHOP-1, SHOP-2"))
    assert res.ticket.acceptance_criteria == ["[SHOP-1] Crit", "[SHOP-2] Crit"]
    assert any("Several tickets" in line for line in res.info)


def test_one_unavailable_ticket_is_reported_and_the_other_still_used():
    res = resolve_ticket(jira(FakeJira(issues_for("SHOP-1"))), pr("x", "Jira: SHOP-1, SHOP-9"))
    assert res.ticket.key == "SHOP-1"
    assert any("SHOP-9 could not be retrieved" in n and "404" in n for n in res.notes)


def test_all_tickets_unavailable_leaves_no_ticket_and_says_why():
    res = resolve_ticket(jira(FakeJira(status=(401, {}))), pr("SHOP-1: fix"))
    assert res.ticket is None
    assert any("SHOP-1 could not be retrieved" in n and "credentials" in n for n in res.notes)


def test_too_many_tickets_are_capped_and_reported():
    keys = [f"SHOP-{i}" for i in range(1, 8)]
    res = resolve_ticket(jira(FakeJira(issues_for(*keys))), pr("x", "Jira: " + ", ".join(keys)))
    assert len(res.ticket.acceptance_criteria) == 5
    assert any("SHOP-6, SHOP-7 ignored" in n for n in res.notes)


def test_explicit_keys_override_the_pr_text():
    fake = FakeJira(issues_for("APP-5", "SHOP-1"))
    res = resolve_ticket(jira(fake), pr("SHOP-1: fix"), explicit_keys=["APP-5"])
    assert res.ticket.key == "APP-5" and len(fake.calls) == 1


def test_ticket_without_criteria_among_several_is_flagged():
    issues = {**issues_for("SHOP-1"), "SHOP-2": issue_json(key="SHOP-2", description=doc(para("no list")))}
    res = resolve_ticket(jira(FakeJira(issues)), pr("x", "Jira: SHOP-1, SHOP-2"))
    assert any("SHOP-2 has no acceptance criteria" in n for n in res.notes)


# ---------------------------------------------------- context, grounding, reports


def test_unavailable_ticket_appears_in_the_prompt_and_as_partial_coverage():
    res = resolve_ticket(jira(FakeJira(status=(404, {}))), pr("SHOP-1: fix"))
    snap = FakeGitHub()
    from code_review_agent.connectors.github import GitHubClient
    snapshot = GitHubClient(transport=httpx.MockTransport(snap)).fetch_pull_request("o/r", 7, with_source=False)
    snapshot.notes += res.notes
    ctx = build_context(res.ticket, snapshot.to_review_input())
    assert "MISSING: No Jira ticket was provided" in ctx.user
    assert "OMITTED: Jira ticket SHOP-1 could not be retrieved" in ctx.user
    assert not ctx.coverage.complete


def test_quote_of_a_merged_criterion_without_its_tag_is_still_grounded():
    merged = merge_tickets([ticket("SHOP-1", "Orders ship free"), ticket("APP-2", "Under 100 pay")])
    _, review_input = load_example(__import__("pathlib").Path(__file__).resolve().parent.parent / "examples" / "free-shipping-faulty")
    f = Finding.model_validate({
        "category": "requirement_mismatch", "severity": "low", "file": "shop/shipping.py", "line": 6,
        "title": "t", "explanation": "e", "evidence": [{"source": "ticket", "quote": "Under 100 pay"}]})
    assert check_grounding([f], merged, review_input) == []


# --------------------------------------------------------------------------- CLI


@pytest.fixture
def cli_with_fakes(monkeypatch):
    def install(fake_jira=None, fake_github=None):
        monkeypatch.setenv("JIRA_BASE_URL", "https://site.atlassian.net")
        monkeypatch.setenv("JIRA_EMAIL", "me@x.org")
        monkeypatch.setenv("JIRA_API_TOKEN", "tok-secret")
        if fake_jira is not None:
            monkeypatch.setattr(clients, "jira_client", lambda: JiraClient(transport=httpx.MockTransport(fake_jira)))
        if fake_github is not None:
            from code_review_agent.connectors.github import GitHubClient
            monkeypatch.setattr(clients, "github_client", lambda: GitHubClient(transport=httpx.MockTransport(fake_github)))
    return install


def test_fetch_ticket_cli_shows_what_was_understood_and_saves(tmp_path, cli_with_fakes, capsys):
    cli_with_fakes(fake_jira=FakeJira(issues_for("SHOP-1", criteria=("A", "B"))))
    out = tmp_path / "t.json"
    assert cli.main(["fetch-ticket", "SHOP-1", "--out", str(out)]) == 0
    shown = capsys.readouterr().out
    assert "SHOP-1: Title SHOP-1" in shown and "acceptance criteria: 2" in shown and "1. A" in shown
    assert Ticket.model_validate_json(out.read_text(encoding="utf-8")).acceptance_criteria == ["A", "B"]


def test_fetch_ticket_cli_warns_when_criteria_are_missing(cli_with_fakes, capsys):
    cli_with_fakes(fake_jira=FakeJira({"SHOP-1": issue_json()}))
    assert cli.main(["fetch-ticket", "SHOP-1"]) == 0
    assert "no acceptance criteria found" in capsys.readouterr().out


def test_fetch_ticket_cli_error_has_no_traceback(cli_with_fakes, capsys):
    cli_with_fakes(fake_jira=FakeJira(status=(401, {})))
    assert cli.main(["fetch-ticket", "SHOP-1"]) == 1
    assert "refused the credentials" in capsys.readouterr().err


def test_fetch_pr_with_jira_saves_pr_and_its_ticket(tmp_path, cli_with_fakes):
    gh = FakeGitHub()  # PR body is "Implements SHOP-1"
    cli_with_fakes(fake_jira=FakeJira(issues_for("SHOP-1", criteria=("f returns 2",))), fake_github=gh)
    assert cli.main(["fetch-pr", "o/r#7", "--jira", "--jira-projects", "SHOP", "--snapshots", str(tmp_path)]) == 0
    ticket_, review_input = load_example(next(tmp_path.iterdir()))
    assert ticket_.key == "SHOP-1" and ticket_.acceptance_criteria == ["f returns 2"]
    assert review_input.pr.head_sha == HEAD


def test_a_failed_jira_lookup_never_reuses_the_ticket_of_an_earlier_fetch(tmp_path, cli_with_fakes, capsys):
    # Regression (found on a real run): the snapshot folder is named after the commit, so fetching the same PR
    # twice reuses it. A failing second lookup left the first fetch's ticket.json in place, and the review used
    # those requirements while its own report claimed they were not used.
    snaps = tmp_path / "snaps"
    cli_with_fakes(fake_jira=FakeJira(issues_for("SHOP-1", criteria=("f returns 2",))), fake_github=FakeGitHub())
    assert cli.main(["fetch-pr", "o/r#7", "--jira", "--jira-projects", "SHOP", "--snapshots", str(snaps)]) == 0
    folder = next(snaps.iterdir())
    assert load_example(folder)[0].key == "SHOP-1"

    cli_with_fakes(fake_jira=FakeJira(status=(401, {})), fake_github=FakeGitHub())  # same PR, Jira now broken
    assert cli.main(["fetch-pr", "o/r#7", "--jira", "--jira-projects", "SHOP", "--snapshots", str(snaps)]) == 0
    ticket_, review_input = load_example(folder)
    assert ticket_ is None and not (folder / "ticket.json").exists()  # the stale requirements are gone
    assert any("SHOP-1 could not be retrieved" in n for n in review_input.input_notes)


def test_a_new_fetch_removes_every_leftover_of_the_previous_one(tmp_path):
    from code_review_agent.connectors.github import PullRequestSnapshot

    folder = tmp_path / "snap"
    old = PullRequestSnapshot(
        metadata=PullRequestMetadata(title="old", head_sha="a" * 40), diff="diff --git a/a.py b/a.py\n",
        supporting_files=[SupportingFile(path="old_support.py", content="x")],
        analysis_files=[SupportingFile(path="old_analysis.py", content="x")], rules="- old rule\n")
    from code_review_agent.connectors.snapshot import save_snapshot

    save_snapshot(old, folder)
    (folder / "ticket.json").write_text('{"key": "OLD-1", "title": "stale"}', encoding="utf-8")
    new = PullRequestSnapshot(metadata=PullRequestMetadata(title="new", head_sha="a" * 40), diff="diff --git a/b.py b/b.py\n")
    save_snapshot(new, folder)
    ticket_, review_input = load_example(folder)
    assert ticket_ is None and review_input.rules is None and review_input.pr.title == "new"
    assert review_input.supporting_files == [] and review_input.analysis_files == []


def test_fetch_pr_with_jira_but_no_link_still_works_and_records_the_gap(tmp_path, cli_with_fakes):
    cli_with_fakes(fake_jira=FakeJira(), fake_github=FakeGitHub())  # no --jira-projects: "Implements SHOP-1" is not explicit
    assert cli.main(["fetch-pr", "o/r#7", "--jira", "--snapshots", str(tmp_path)]) == 0
    ticket_, review_input = load_example(next(tmp_path.iterdir()))
    assert ticket_ is None
    assert any("No Jira key was found" in n for n in review_input.input_notes)


def test_jira_flag_without_configuration_stops_instead_of_reviewing_blind(tmp_path, monkeypatch, capsys):
    for name in ("JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"):
        monkeypatch.delenv(name, raising=False)
    assert cli.main(["fetch-pr", "o/r#7", "--jira", "--snapshots", str(tmp_path)]) == 1
    assert "Jira is not configured" in capsys.readouterr().err
    assert not any(tmp_path.iterdir())


def test_explicit_ticket_file_wins_over_jira(tmp_path, cli_with_fakes):
    fake_jira = FakeJira(issues_for("SHOP-1"))
    cli_with_fakes(fake_jira=fake_jira, fake_github=FakeGitHub())
    f = tmp_path / "t.json"
    f.write_text(json.dumps({"key": "LOCAL-1", "title": "Local", "acceptance_criteria": ["x"]}), encoding="utf-8")
    assert cli.main(["fetch-pr", "o/r#7", "--jira", "--ticket", str(f), "--snapshots", str(tmp_path / "s")]) == 0
    assert load_example(next((tmp_path / "s").iterdir()))[0].key == "LOCAL-1"
    assert fake_jira.calls == []


def test_review_pr_end_to_end_with_pr_ticket_and_model_all_faked(tmp_path, cli_with_fakes):
    from test_model_client import FakeOllama

    cli_with_fakes(fake_jira=FakeJira({**issues_for("SHOP-1", criteria=("f returns 2",))}), fake_github=FakeGitHub())
    server = FakeOllama(content='{"findings": [], "limitations": []}')
    try:
        code = cli.main(["review-pr", "o/r#7", "--jira", "--jira-projects", "SHOP", "--snapshots", str(tmp_path / "s"),
                         "--runs", str(tmp_path / "r"), "--host", server.host, "--model", "fake"])
    finally:
        server.close()
    assert code == 0
    sent = server.requests[0]["body"]["messages"][1]["content"]
    assert "f returns 2" in sent and "SHOP-1" in sent  # the Jira requirements reached the model
    report = next((tmp_path / "r").rglob("report.md")).read_text(encoding="utf-8")
    assert HEAD in report and "No Jira ticket was provided" not in report
