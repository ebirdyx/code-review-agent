"""Jira connector: read-only access to tickets (Jira Cloud REST API v3).

Turns a Jira issue into the `Ticket` the rest of the program already uses.

Rules (the same honesty rules as for GitHub):
  - never guess a requirement: whatever cannot be found is reported as missing;
  - an unreachable ticket is a visible gap in the report, never a silent skip;
  - credentials come from environment variables, are sent only in the Authorization
    header, and never appear in files or error messages; redirects are not followed.

Where do acceptance criteria live? That differs between Jira sites, so we look in
this order and say which one was used:
  1. the field named by JIRA_ACCEPTANCE_FIELD (a field id such as customfield_10042,
     or a display name);
  2. any field whose display name is "Acceptance Criteria" (or the French equivalent);
  3. a section titled "Acceptance criteria" inside the description.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

import httpx

from ..schemas import PullRequestMetadata, Ticket

BASE_URL_ENV, EMAIL_ENV, TOKEN_ENV = "JIRA_BASE_URL", "JIRA_EMAIL", "JIRA_API_TOKEN"
FIELD_ENV, PROJECTS_ENV = "JIRA_ACCEPTANCE_FIELD", "JIRA_PROJECTS"
MAX_TICKETS = 5

AC_NAMES = {
    "acceptance criteria", "acceptance criterion", "acceptance criteria (ac)",
    "critères d'acceptation", "critères d’acceptation", "criteres d'acceptation", "critère d'acceptation",
}
_AC_HEADING = re.compile(
    r"^\s*(?:#+\s*|h\d\.\s*|\*\*)?(?:acceptance criteria|crit[èe]res? d['’]acceptation)\s*(?:\*\*)?\s*:?\s*(?:\*\*)?\s*$",
    re.IGNORECASE,
)
_LIST_ITEM = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+(?P<text>.+?)\s*$")
_HEADINGISH = re.compile(r"^\s*(?:#+\s|h\d\.\s)")
_KEY = r"[A-Z][A-Z0-9]{1,9}-\d{1,6}"
_KEY_RE = re.compile(rf"\b({_KEY})\b")
_MARKER_LINE = re.compile(rf"(?im)^\s*(?:jira|ticket|issue)\s*[:#]\s*(?P<keys>{_KEY}(?:[\s,;]+{_KEY})*)")
_TITLE_KEY = re.compile(rf"^\s*(?:\[({_KEY})\]|({_KEY})\s*[:\-–])")


class JiraError(Exception):
    """A Jira request failed in a way the user can act on. The message says how."""


# ---------------------------------------------------------------------- text helpers


def adf_to_text(node) -> str:
    """Flatten Atlassian Document Format (or a plain string) into readable text.

    Lists become '- item' / '1. item' lines so acceptance criteria stay recognisable.
    Unknown node types are not dropped: their children are still read.
    """
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if not isinstance(node, dict):
        return str(node)
    return _block(node).strip("\n")


def _inline(node: dict) -> str:
    kind = node.get("type")
    if kind == "text":
        return node.get("text", "")
    if kind == "hardBreak":
        return "\n"
    attrs = node.get("attrs") or {}
    if kind in ("mention", "emoji", "status"):
        return attrs.get("text") or attrs.get("shortName") or ""
    if kind in ("inlineCard", "blockCard", "embedCard"):
        return attrs.get("url", "")
    return "".join(_inline(c) for c in node.get("content", []) if isinstance(c, dict))


def _block(node: dict, indent: int = 0) -> str:
    kind = node.get("type")
    children = [c for c in node.get("content", []) if isinstance(c, dict)]
    pad = "  " * indent
    if kind in ("bulletList", "orderedList"):
        lines = []
        for i, item in enumerate(children, 1):
            marker = "-" if kind == "bulletList" else f"{i}."
            parts = [c for c in item.get("content", []) if isinstance(c, dict)]
            nested = [c for c in parts if c.get("type") in ("bulletList", "orderedList")]
            own = "".join(_inline(c) if c.get("type") not in ("bulletList", "orderedList") else "" for c in parts)
            lines.append(f"{pad}{marker} {own.strip()}")
            lines += [_block(n, indent + 1) for n in nested]
        return "\n".join(lines) + "\n"
    if kind == "table":
        rows = [" | ".join(_inline(cell).strip() for cell in row.get("content", []) if isinstance(cell, dict))
                for row in children]
        return "\n".join(rows) + "\n"
    if kind in ("paragraph", "heading", "codeBlock"):
        return pad + _inline(node) + "\n"
    if kind in ("text", "hardBreak", "mention", "emoji", "status", "inlineCard"):
        return _inline(node)
    return "".join(_block(c, indent) for c in children)  # doc, panel, blockquote, unknown


def split_criteria(text: str) -> list[str]:
    """One criterion per line; leading bullets and numbers are removed."""
    out = []
    for line in text.splitlines():
        if not line.strip():
            continue
        m = _LIST_ITEM.match(line)
        out.append((m["text"] if m else line.strip()))
    return out


def criteria_from_description(description: str) -> list[str]:
    """Items under an 'Acceptance criteria' heading inside the description (if any)."""
    lines = description.splitlines()
    for i, line in enumerate(lines):
        if not _AC_HEADING.match(line):
            continue
        items: list[str] = []
        after_blank = False
        for nxt in lines[i + 1:]:
            if not nxt.strip():
                if items:
                    break
                after_blank = True
                continue
            if _HEADINGISH.match(nxt):
                break
            m = _LIST_ITEM.match(nxt)
            if m:
                items.append(m["text"])
            elif items or after_blank:
                break  # prose after a blank line is not a criterion: do not guess
            else:
                items.append(nxt.strip())  # plain line directly under the heading
        return items
    return []


# --------------------------------------------------------------------- ticket links


def extract_issue_keys(pr: PullRequestMetadata, projects: list[str] | None = None) -> list[str]:
    """Jira keys linked from a pull request, in order of appearance, without duplicates.

    Link convention (documented in the README):
      - with a project list (JIRA_PROJECTS=SHOP,APP): any key of those projects in the
        PR title or description counts;
      - without one, only EXPLICIT links count: a line "Jira: SHOP-1[, SHOP-2]" (or
        "Ticket:" / "Issue:") in the description, or a title starting with the key
        ("SHOP-1: ..."). This avoids mistaking text such as "UTF-8" for a ticket.
    """
    title, body = pr.title or "", pr.description or ""
    found: list[str] = []
    if projects:
        wanted = {p.strip().upper() for p in projects if p.strip()}
        found = [k for k in _KEY_RE.findall(f"{title}\n{body}") if k.split("-")[0] in wanted]
    else:
        if m := _TITLE_KEY.match(title):
            found.append(m.group(1) or m.group(2))
        for line in _MARKER_LINE.finditer(body):
            found += _KEY_RE.findall(line["keys"])
    return list(dict.fromkeys(found))


# ------------------------------------------------------------------------- client


@dataclass
class JiraIssue:
    ticket: Ticket
    criteria_source: str  # where the acceptance criteria came from, or why there are none


class JiraClient:
    def __init__(
        self,
        base_url: str | None = None,
        email: str | None = None,
        token: str | None = None,
        acceptance_field: str | None = None,
        timeout_s: float = 30.0,
        transport: httpx.BaseTransport | None = None,
    ):
        base_url = base_url or os.environ.get(BASE_URL_ENV)
        email = email or os.environ.get(EMAIL_ENV)
        token = token or os.environ.get(TOKEN_ENV)
        missing = [n for n, v in ((BASE_URL_ENV, base_url), (EMAIL_ENV, email), (TOKEN_ENV, token)) if not v]
        if missing:
            raise JiraError(f"Jira is not configured: set {', '.join(missing)}. See the README, section Jira.")
        self.acceptance_field = acceptance_field or os.environ.get(FIELD_ENV) or None
        base_url = base_url.strip().rstrip("/")
        try:
            parsed = httpx.URL(base_url)
        except httpx.InvalidURL as exc:
            raise JiraError(f"{BASE_URL_ENV} is not a valid address: {base_url!r}.") from exc
        if parsed.scheme not in ("http", "https") or not parsed.host or any(c in base_url for c in "<>{} "):
            raise JiraError(
                f"{BASE_URL_ENV} is {base_url!r}, which is not a usable address. "
                "Use the real site URL, for example https://myteam.atlassian.net (no placeholders, with https://)."
            )
        self._host = parsed.host
        self._http = httpx.Client(
            base_url=base_url, auth=(email, token), timeout=timeout_s,
            headers={"Accept": "application/json", "User-Agent": "code-review-agent"},
            transport=transport,
            follow_redirects=False,  # never forward credentials to another host
        )

    def _get(self, path: str, params: dict | None, what: str) -> httpx.Response:
        """One GET. Network problems become a JiraError that says what is probably wrong."""
        try:
            return self._http.get(path, params=params)
        except httpx.TimeoutException as exc:
            raise JiraError(f"Jira did not answer in time for {what}.") from exc
        except httpx.HTTPError as exc:
            reason = str(exc) or type(exc).__name__
            if "CERTIFICATE_VERIFY_FAILED" in reason or "Hostname mismatch" in reason or "certificate" in reason.lower():
                hint = (f" The address does not match a real Jira site: the site name in {BASE_URL_ENV} is probably misspelled "
                        "(compare it letter by letter, dots included, with the address in your browser).")
            elif "getaddrinfo" in reason or "Name or service not known" in reason or "11001" in reason:
                hint = (f" The host name could not be resolved: check the spelling of the site name in "
                        f"{BASE_URL_ENV}, or your network/VPN/proxy.")
            else:
                hint = f" Check {BASE_URL_ENV}, your network, VPN or proxy."
            raise JiraError(f"Cannot reach Jira at {self._host} ({type(exc).__name__}: {reason}).{hint}") from exc

    def whoami(self) -> str:
        """Check the address and credentials without touching any ticket. Returns the account's display name."""
        response = self._get("/rest/api/3/myself", None, "your account")
        if response.status_code == 401:
            raise JiraError(f"Jira refused the credentials (401). Check {EMAIL_ENV} and {TOKEN_ENV}.")
        if response.status_code in (403, 404):
            raise JiraError(f"{self._host} answered {response.status_code} for the account check: is {BASE_URL_ENV} the exact site URL?")
        if response.status_code >= 300:
            raise JiraError(f"Jira returned HTTP {response.status_code} for the account check.")
        try:
            return str(response.json().get("displayName") or "(unnamed account)")
        except ValueError as exc:
            raise JiraError(f"Jira returned something that is not JSON. Check {BASE_URL_ENV} (it must be the site URL).") from exc

    def fetch_issue(self, key: str) -> JiraIssue:
        if not re.fullmatch(_KEY, key):
            raise JiraError(f"'{key}' is not a Jira issue key (expected something like SHOP-42).")
        response = self._get(f"/rest/api/3/issue/{key}", {"fields": "*all", "expand": "names"}, key)
        if response.status_code >= 300:
            raise self._error(key, response)
        try:
            data = response.json()
        except ValueError as exc:
            raise JiraError("Jira returned something that is not JSON. Check JIRA_BASE_URL (it must be the site URL).") from exc
        return self._to_issue(key, data)

    def _error(self, key: str, response: httpx.Response) -> JiraError:
        code = response.status_code
        if code == 401:
            return JiraError(f"Jira refused the credentials (401). Check {EMAIL_ENV} and {TOKEN_ENV}.")
        if code == 403:
            return JiraError(f"Access to {key} is forbidden (403): the account lacks permission.")
        if code == 404:
            return JiraError(f"{key} not found (404): it does not exist, or this account cannot see it.")
        if code == 429:
            wait = response.headers.get("Retry-After")
            return JiraError("Jira rate limit reached" + (f"; retry after {wait} s." if wait else "."))
        if code < 400:
            return JiraError(f"Unexpected redirect (HTTP {code}) from Jira. {BASE_URL_ENV} should be the exact site URL.")
        return JiraError(f"Jira returned HTTP {code} for {key}.")

    def _to_issue(self, key: str, data: dict) -> JiraIssue:
        fields = data.get("fields") or {}
        names: dict[str, str] = data.get("names") or {}
        description = adf_to_text(fields.get("description"))

        criteria, source = self._find_criteria(fields, names, description)
        ticket = Ticket(
            key=data.get("key") or key,
            title=(fields.get("summary") or "").strip() or "(no summary)",
            description=description,
            acceptance_criteria=criteria,
        )
        return JiraIssue(ticket=ticket, criteria_source=source)

    def _find_criteria(self, fields: dict, names: dict[str, str], description: str) -> tuple[list[str], str]:
        configured = self.acceptance_field
        candidates: list[tuple[str, str]] = []  # (field id, display name)
        if configured:
            by_name = [fid for fid, n in names.items() if n.lower() == configured.lower()]
            fid = configured if configured in fields else (by_name[0] if by_name else None)
            if fid is None:
                return [], f"configured field '{configured}' does not exist on this issue"
            candidates.append((fid, names.get(fid, fid)))
        else:
            candidates = [(fid, n) for fid, n in names.items() if n.lower() in AC_NAMES and fid in fields]
        for fid, display in candidates:
            items = split_criteria(adf_to_text(fields.get(fid)))
            if items:
                return items, f"field '{display}' ({fid})"
        items = criteria_from_description(description)
        if items:
            return items, "section 'Acceptance criteria' of the description"
        if candidates:
            return [], f"field '{candidates[0][1]}' exists but is empty, and the description has no such section"
        return [], "no acceptance-criteria field or description section found"


# ---------------------------------------------------------------- PR -> ticket(s)


def merge_tickets(tickets: list[Ticket]) -> Ticket | None:
    """One Ticket from several. Each criterion keeps its ticket key so it stays traceable."""
    if not tickets:
        return None
    if len(tickets) == 1:
        return tickets[0]
    return Ticket(
        key=tickets[0].key,
        title=" | ".join(f"{t.key}: {t.title}" for t in tickets),
        description="\n\n".join(f"[{t.key}] {t.title}\n{t.description}".strip() for t in tickets),
        acceptance_criteria=[f"[{t.key}] {c}" for t in tickets for c in t.acceptance_criteria],
    )


@dataclass
class TicketResolution:
    ticket: Ticket | None
    keys: list[str] = field(default_factory=list)
    info: list[str] = field(default_factory=list)  # for the user
    notes: list[str] = field(default_factory=list)  # gaps that belong in the report


def resolve_ticket(
    client: JiraClient,
    pr: PullRequestMetadata,
    projects: list[str] | None = None,
    explicit_keys: list[str] | None = None,
) -> TicketResolution:
    """Find the tickets linked from a PR and fetch them. Never invents anything."""
    keys = list(dict.fromkeys(explicit_keys or extract_issue_keys(pr, projects)))
    res = TicketResolution(ticket=None, keys=keys)
    if not keys:
        res.notes.append(
            "No Jira key was found in the pull request title or description, so no requirements were available. "
            "Link convention: a line 'Jira: KEY-123' in the description, or a title starting with 'KEY-123:'."
        )
        return res
    if len(keys) > MAX_TICKETS:
        res.notes.append(f"{len(keys)} Jira keys are linked; only the first {MAX_TICKETS} were fetched ({', '.join(keys[MAX_TICKETS:])} ignored).")
        keys = keys[:MAX_TICKETS]
    if len(keys) > 1:
        res.info.append(f"Several tickets are linked ({', '.join(keys)}); their requirements are combined, each criterion tagged with its key.")

    fetched: list[Ticket] = []
    for key in keys:
        try:
            issue = client.fetch_issue(key)
        except JiraError as exc:
            res.notes.append(f"Jira ticket {key} could not be retrieved ({exc}); its requirements were not used.")
            continue
        fetched.append(issue.ticket)
        res.info.append(f"{key}: {len(issue.ticket.acceptance_criteria)} acceptance criteria (from {issue.criteria_source})")
        if not issue.ticket.acceptance_criteria and len(keys) > 1:
            res.notes.append(f"Ticket {key} has no acceptance criteria ({issue.criteria_source}).")
    res.ticket = merge_tickets(fetched)
    return res
