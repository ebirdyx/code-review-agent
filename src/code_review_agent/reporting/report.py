"""Render a ReviewResult as a Markdown report for a human reviewer.

Everything the model wrote is untrusted text. Quotes go inside code fences (with a
fence longer than any backtick run inside them) and single-line fields have their
newlines removed, so model output cannot break out of the report layout.
"""

from __future__ import annotations

import re

from ..schemas import Finding, ReviewResult, Severity, TriageFile, ValidationProblem

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
            f"- **Ticket:** {_line(r.ticket) if r.ticket else 'none: no requirements were available'}",
            f"- **Model:** {_line(r.model)} at {_line(r.host)}",
            f"- **Prompt version:** {_line(r.prompt_version)}",
            f"- **Date (UTC):** {_line(r.created_at)}",
            f"- **Model time:** {stats}; tokens: {tokens}",
        ]
        if result.pipeline == "multi":
            names = ", ".join(p.name for p in result.passes)
            out.append(f"- **Pipeline:** multi-pass ({_line(names)})")

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

    # --- what kind of change this is (computed without any model)
    prof = result.change_profile
    if prof is not None and prof.files_changed:
        langs = ", ".join(f"{ext} x{n}" for ext, n in sorted(prof.languages.items(), key=lambda kv: -kv[1])[:6])
        out += ["## Change profile", "",
                f"{prof.files_changed} file(s) changed, +{prof.lines_added} / -{prof.lines_removed} lines "
                f"({prof.source_files} source, {prof.test_files} test); file types: {_line(langs)}."]
        out += [f"- {_line(h)}" for h in prof.hints] + [""]

    # --- repository context that was provided (callers, callees, tests)
    if result.context:
        out += ["## Repository context", "",
                "Code outside the change that the model was shown, found by matching function names (it can match the wrong function).", ""]
        out += [f"- {_line(c)}" for c in result.context] + [""]

    # --- static-analysis tools
    if result.tools:
        out += ["## Automated checks (static analysis)", "",
                "Deterministic tools, not a model. A warning on a line this pull request changed is reported as a finding; "
                "warnings on untouched lines are counted but not blamed on this change.", "",
                "| Tool | Status | Files | Warnings | On changed lines | Note |", "|---|---|--:|--:|--:|---|"]
        for t in result.tools:
            out.append(f"| {_line(t.name)} {_line(t.version or '')} | {t.status} | {t.files_checked} | {t.total_findings} | "
                       f"{t.findings_on_changed_lines} | {_line(t.message).replace('|', '/')} |")
        out.append("")

    # --- what each specialist pass did (multi-pass pipeline)
    if result.passes:
        out += ["## Specialist passes", "", "| Pass | Status | Model time | Tokens | Result |", "|---|---|--:|--:|---|"]
        for p in result.passes:
            took = f"{p.duration_s:.1f} s" if p.duration_s is not None else "n/a"
            toks = f"{p.prompt_tokens} / {p.completion_tokens}" if p.prompt_tokens is not None else "n/a"
            detail = _line(p.message) if p.message else (
                f"{p.findings} dismissed" if p.name == "verify" else f"{p.findings} candidate finding(s)")
            out.append(f"| {_line(p.name)} | {p.status} | {took} | {toks} | {detail.replace('|', '/')} |")
        out.append("")

    # --- requirements checklist
    if result.criteria:
        crit_problems: dict[int, list[ValidationProblem]] = {}
        for p in result.problems:
            if p.criterion_index is not None:
                crit_problems.setdefault(p.criterion_index, []).append(p)
        out += ["## Requirements checklist", "",
                "Each acceptance criterion of the ticket, with the model's verdict. "
                "\"Cannot determine\" means the provided content did not allow a judgement.", ""]
        for i, c in enumerate(result.criteria):
            label = {"met": "MET", "not_met": "NOT MET", "cannot_determine": "CANNOT DETERMINE"}[c.verdict]
            out += [f"### {c.number}. {label}: {_line(c.text)}", "", _line_wrap(c.explanation), ""]
            for ev in c.evidence:
                out += [f"From {ev.source}:", "", _fence(ev.quote), ""]
            if c.file:
                out += [f"Where: `{_line(c.file)}{':' + str(c.line) if c.line else ''}`", ""]
            if crit_problems.get(i):
                out += ["**Validation problems**", ""]
                out += [f"- `{p.kind}`: {_line(p.message)}" for p in crit_problems[i]] + [""]

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
            what = "merged into another finding" if result.pipeline == "multi" else "removed"
            out += [f"_{result.duplicates_removed} duplicate finding(s) {what}._", ""]

        if result.dismissed:
            out += ["## Dismissed by verification", "",
                    "These candidates were judged unsupported by the verification pass. They are listed "
                    "so nothing disappears silently; the human reviewer can overrule the verifier.", ""]
            for d in result.dismissed:
                f = d.finding
                where = f"{f.file}:{f.line}" if f.line else f.file
                out.append(f"- **{_line(f.title)}** (`{_line(where)}`, found by {_line(', '.join(f.found_by) or 'a pass')}): "
                           f"{_line(d.reason)}")
            out.append("")

        if result.limitations:
            out += ["## Limitations stated by the model", ""]
            out += [f"- {_line(x)}" for x in result.limitations] + [""]

        general = [p for p in by_index.get(None, []) if p.criterion_index is None]
        if general:
            out += ["## Output format notes", ""] + [f"- {_line(p.message)}" for p in general] + [""]

    return "\n".join(out).rstrip() + "\n"


def render_triage_section(result: ReviewResult, triage: TriageFile) -> str:
    """Markdown block recording what the human reviewer decided about each finding."""
    who = _line(triage.reviewer) or "unnamed reviewer"
    out = ["", f"## Human triage (reviewer: {who})", ""]
    if not result.findings:
        return "\n".join(out + ["No findings to triage.", ""])
    by_index = {d.finding_index: d for d in triage.decisions}
    for i, f in enumerate(result.findings):
        d = by_index.get(i)
        state = d.decision.upper() if d else "NOT REVIEWED"
        note = f": {_line(d.note)}" if d and d.note.strip() else ""
        out.append(f"- Finding {i + 1} ({_line(f.title)}): **{state}**{note}")
    decided = sum(1 for i in range(len(result.findings)) if i in by_index)
    out += ["", f"{decided} of {len(result.findings)} finding(s) reviewed by a human.", ""]
    return "\n".join(out)


def _render_finding(rank: int, f: Finding, problems: list[ValidationProblem]) -> list[str]:
    out = [
        f"### {rank}. [{f.severity.upper()}] {_line(f.title)}",
        "",
        f"- **Category:** {f.category}",
        f"- **Location:** `{_location(f)}`",
        "- **Location and quotes:** "
        + ("checked against the input" if not problems else "**NOT FULLY CONFIRMED**, see below"),
    ]
    if f.found_by:
        out.append(f"- **Found by:** {_line(', '.join(f.found_by))}")
    if f.source == "tool":
        out.append("- **Backed by:** a static-analysis tool (a deterministic check, not put to the verifier's vote)")
    elif f.verification:
        out.append(f"- **Verification:** {f.verification}" + (f" ({_line(f.verification_note)})" if f.verification_note else ""))
    elif f.verification_note:
        out.append(f"- **Verification:** not verified ({_line(f.verification_note)})")
    out += [
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
