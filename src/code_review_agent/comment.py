"""Render a ReviewResult as ONE short pull-request comment.

The comment is published to a place where other people read it, so everything the model wrote
(and everything copied from the PR or ticket) is untrusted text. `_clean` removes what could
notify strangers (@mentions), inject HTML, or make clickable links and images. Quotes go inside
code fences. The comment starts with a hidden marker so the next run can find it and update it
instead of adding a new one.
"""

from __future__ import annotations

import re

from .report import DISCLAIMER, _fence, _location
from .schemas import Finding, ProblemKind, ReviewResult, Severity

MARKER = "<!-- code-review-agent -->"
MAX_COMMENT_CHARS = 60_000  # GitHub's limit is 65,536
MAX_LISTED_FINDINGS = 15
_ORDER = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2, Severity.LOW: 3}
_VERDICT = {"met": "MET", "not_met": "NOT MET", "cannot_determine": "CANNOT DETERMINE"}
_ZWSP = "​"


def _clean(text: str, limit: int = 600) -> str:
    """Single-line, mention-free, link-free, HTML-free text."""
    text = " ".join(text.split())
    text = text if len(text) <= limit else text[: limit - 1] + "…"
    # Inside `code spans` GitHub shows text literally (no mentions, HTML or links), so only the rest is rewritten.
    # Only plain single-backtick spans count; escaped or doubled backticks are not trusted as code.
    parts = re.split(r"((?<!`)`[^`]+`(?!`))", text.replace("\\`", "'"))
    for i, part in enumerate(parts):
        if i % 2 == 0:
            part = part.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            part = part.replace("@", "@" + _ZWSP).replace("[", "\\[").replace("]", "\\]")
            part = re.sub(r"(?i)\b(https?|ftp)://", lambda m: m.group(1) + _ZWSP + "://", part)  # no autolinks
        parts[i] = part.replace("|", "\\|")  # table cells, everywhere
    return "".join(parts)


def _link(text: str) -> str | None:
    """A web address the workflow itself supplied (not model text): kept clickable only if it is plain."""
    text = text.strip()
    return text if re.fullmatch(r"https://[^\s<>()\[\]`|]+", text) else None


def _finding_lines(rank: int, f: Finding) -> list[str]:
    tag = " (static analysis)" if f.source == "tool" else ""
    lines = [f"{rank}. **[{f.severity.value.upper()}]** {_clean(f.title, 160)} — `{_clean(_location(f), 200).replace('`', '')}`{tag}"]
    lines.append(f"   {_clean(f.explanation)}")
    if f.verification:
        lines.append(f"   _Second look: {f.verification}._")
    return lines


def render_pr_comment(result: ReviewResult, *, report_hint: str | None = None) -> str:
    out: list[str] = [MARKER, "## Automated code review", ""]
    run = result.run
    rev = run.revision if run else None
    if rev:
        out.append(f"Reviewed commit `{_clean(rev.head_sha, 40).replace('`', '')}`"
                   + (f" against ticket **{_clean(run.ticket, 200)}**." if run and run.ticket else " (no ticket linked: requirements unknown)."))
    elif run and run.ticket:
        out.append(f"Ticket: **{_clean(run.ticket, 200)}**.")
    out.append("")

    if result.status == "failed":
        message = result.error.message if result.error else "unknown error"
        out += ["**The review did not run to completion, so nothing can be concluded about this change.**", "",
                f"Reason: {_clean(message)}", ""]
    else:
        n = len(result.findings)
        out.append(f"**{n} finding(s)**" if n else "**No findings.** This is not a proof that the change is correct.")
        if result.coverage and not result.coverage.complete:
            out.append("")
            out.append("_Partial coverage: " + _clean("; ".join(result.coverage.omitted) or "some input was not reviewed", 400) + "_")
        failed = [p for p in result.passes if p.status == "failed"]
        if failed:
            out.append("")
            out.append("_Passes that failed (their findings are missing): " + _clean(", ".join(p.name for p in failed)) + "_")
        out.append("")

        if result.criteria:
            out += ["### Requirements", "", "| # | Criterion | Verdict |", "|--:|---|---|"]
            conflicting = {p.criterion_index for p in result.problems if p.kind == ProblemKind.INCONSISTENT_VERDICT}
            for index, c in enumerate(result.criteria):
                note = " (check: a finding disagrees)" if index in conflicting else ""
                out.append(f"| {c.number} | {_clean(c.text, 200)} | {_VERDICT.get(c.verdict, c.verdict)}{note} |")
            out.append("")

        if result.findings:
            ordered = sorted(result.findings, key=lambda f: _ORDER[f.severity])
            out += ["### Findings", ""]
            for rank, f in enumerate(ordered[:MAX_LISTED_FINDINGS], 1):
                out += _finding_lines(rank, f)
            if len(ordered) > MAX_LISTED_FINDINGS:
                out.append(f"\n_{len(ordered) - MAX_LISTED_FINDINGS} more finding(s) are in the full report._")
            out.append("")
            evidence = ordered[0].evidence
            quote = next((e for e in evidence if e.source == "code"), evidence[0]).quote  # one quote is enough here
            out += ["<details><summary>Evidence for the first finding</summary>\n", _fence(quote[:800]), "\n</details>", ""]

    if report_hint and (link := _link(report_hint)):
        out += [f"Full report (downloadable artifact of the workflow run): {link}", ""]
    out += [DISCLAIMER]
    text = "\n".join(out)
    if len(text) > MAX_COMMENT_CHARS:
        text = text[:MAX_COMMENT_CHARS].rsplit("\n", 1)[0] + "\n\n_(comment shortened)_\n\n" + DISCLAIMER
    return text
