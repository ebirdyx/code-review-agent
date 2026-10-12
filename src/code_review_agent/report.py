"""Render a ReviewResult as a Markdown report for a human reviewer.

Everything the model wrote is untrusted text. Quotes go inside code fences (with a
fence longer than any backtick run inside them) and single-line fields have their
newlines removed, so model output cannot break out of the report layout.
"""

from __future__ import annotations

import re

from .schemas import Finding, ReviewResult, Severity, ValidationProblem

_SEVERITY_ORDER = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2, Severity.LOW: 3}

DISCLAIMER = (
    "> Automated review by a language model. It can be wrong or miss problems. "
    "\"Checked\" below means only that cited files, lines and quotes exist in the input; "
    "it does not mean a finding is correct. The human reviewer makes the final decision."
)


def _line(text: str) -> str:
    return " ".join(text.split())


def _fence(text: str) -> str:
    longest = max((len(m) for m in re.findall(r"`+", text)), default=0)
    ticks = "`" * max(3, longest + 1)
    return f"{ticks}\n{text}\n{ticks}"


def _location(f: Finding) -> str:
    return f"{f.file}:{f.line}" if f.line else f"{f.file} (no line given)"


def render_markdown(result: ReviewResult) -> str:
    out: list[str] = ["# Code review report", "", DISCLAIMER, ""]

    if result.run:
        r = result.run
        stats = f"{r.duration_s:.1f} s" if r.duration_s is not None else "n/a"
        tokens = (
            f"{r.prompt_tokens} in / {r.completion_tokens} out"
            if r.prompt_tokens is not None
            else "n/a"
        )
        rev = r.revision
        if rev:
            where = f"{rev.repository}#{rev.pr_number}" if rev.repository and rev.pr_number else "pull request"
            out += [f"- **Revision reviewed:** {_line(where)}, head `{rev.head_sha}`"
                    + (f", base `{rev.base_sha}`" if rev.base_sha else "")
                    + (f" ({_line(rev.url)})" if rev.url else "")]
        out += [
            f"- **Case:** {_line(r.case_id)}",
            f"- **Model:** {_line(r.model)} at {_line(r.host)}",
            f"- **Prompt version:** {_line(r.prompt_version)}",
            f"- **Date (UTC):** {_line(r.created_at)}",
            f"- **Model time:** {stats}; tokens: {tokens}",
        ]

    if result.status == "failed":
        err = result.error
        out += [
            "",
            "## Status: REVIEW FAILED",
            "",
            "No conclusion can be drawn about this change: the review did not complete.",
            "This is **not** the same as \"no findings\".",
            "",
            f"- **Reason:** `{err.kind}`" if err else "",
            f"- **Details:** {_line(err.message)}" if err else "",
            "",
        ]
    else:
        n = len(result.findings)
        out += ["", f"## Status: completed, {n} finding{'s' if n != 1 else ''}", ""]

    # --- coverage and missing context
    cov_notes = [f"- {_line(m)}" for m in result.missing_inputs]
    if result.coverage is not None:
        cov_notes += [f"- Not reviewed: {_line(o)}" for o in result.coverage.omitted]
    out += ["## Coverage", ""]
    if result.coverage is not None and result.coverage.complete:
        out.append("All provided input was included in full.")
    elif result.coverage is not None:
        out.append("**Partial coverage.** Some content was not shown to the model.")
    out += [""] + (cov_notes or ["- No missing inputs."]) + [""]

    # --- findings
    if result.status == "completed":
        out += ["## Findings", ""]
        if not result.findings:
            out += [
                "No findings were reported. This is the model's claim, not a guarantee "
                "that the change is correct.",
                "",
            ]
        by_index = {}
        for p in result.problems:
            by_index.setdefault(p.finding_index, []).append(p)
        order = sorted(
            range(len(result.findings)),
            key=lambda i: (_SEVERITY_ORDER[result.findings[i].severity], i),
        )
        for rank, i in enumerate(order, 1):
            out += _render_finding(rank, result.findings[i], by_index.get(i, []))

        if result.duplicates_removed:
            out += [f"_{result.duplicates_removed} duplicate finding(s) removed._", ""]

        if result.limitations:
            out += ["## Limitations stated by the model", ""]
            out += [f"- {_line(x)}" for x in result.limitations] + [""]

        general = by_index.get(None, [])
        if general:
            out += ["## Output format notes", ""] + [f"- {_line(p.message)}" for p in general] + [""]

    return "\n".join(out).rstrip() + "\n"


def _render_finding(rank: int, f: Finding, problems: list[ValidationProblem]) -> list[str]:
    out = [
        f"### {rank}. [{f.severity.upper()}] {_line(f.title)}",
        "",
        f"- **Category:** {f.category}",
        f"- **Location:** `{_location(f)}`",
        f"- **Location and quotes:** "
        + ("checked against the input" if not problems else "**NOT FULLY CONFIRMED**, see below"),
        "",
        _line_wrap(f.explanation),
        "",
        "**Evidence**",
        "",
    ]
    for ev in f.evidence:
        out += [f"From {ev.source}:", "", _fence(ev.quote), ""]
    if problems:
        out += ["**Validation problems**", ""]
        out += [f"- `{p.kind}`: {_line(p.message)}" for p in problems] + [""]
    return out


def _line_wrap(text: str) -> str:
    # Prose from the model: flatten to one line and quote it, so markup it contains
    # (headings, lists) stays inside the quote instead of changing the report layout.
    return "> " + _line(text)
