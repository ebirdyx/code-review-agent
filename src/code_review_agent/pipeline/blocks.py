"""What the model is shown, besides the ticket, the pull request and the diff.

The extra blocks every pass receives (static-analysis leads, team rules, related code), the report's one-line summary of
that context, and the verifier's user message. All pure functions of the run record and the inputs.
"""

from __future__ import annotations

from ..context.builder import NUM_WIDTH, build_user_message
from ..context.evidence import render_leads
from ..schemas import Finding, ReviewInput, Ticket
from .passes import render_candidates
from .records import RunRecord


def render_related(review_input: ReviewInput) -> str:
    """The RELATED CODE block: repository code outside the change, numbered like the diff, with plain facts."""
    lines = ["Code from the repository that is NOT part of this change. It was found by matching function names, so it can "
             "match the wrong function. Use it to understand how the changed code is used and tested. Report a problem in "
             "it only if this change causes or worsens it."]
    if review_input.related_facts:
        lines += ["", "Facts:"] + [f"- {f}" for f in review_input.related_facts]
    for s in review_input.related_code:
        lines += ["", f"--- {s.kind} of `{s.symbol}`: {s.path} (lines {s.start_line}-{s.end_line}) ---"]
        lines += [f"{n:>{NUM_WIDTH}} | {text}" for n, text in enumerate(s.text.splitlines(), s.start_line)]
    return "\n".join(lines)


def context_summary(review_input: ReviewInput) -> list[str]:
    """Short lines for the report: what repository context the model was given."""
    lines = list(review_input.related_facts)
    lines += [f"{s.kind} of `{s.symbol}`: {s.path}:{s.start_line}-{s.end_line} (`{s.name}`)" for s in review_input.related_code]
    return lines


def shared_blocks(record: RunRecord, review_input: ReviewInput) -> dict[str, str]:
    """Extra fenced blocks every pass receives: the tools' leads, and the team's rules (when there are any)."""
    blocks: dict[str, str] = {}
    if record.tool_runs:
        blocks["STATIC ANALYSIS RESULTS"] = render_leads(record.tool_findings, record.tool_runs)
    if review_input.rules and review_input.rules.strip():
        source = f"(from {review_input.rules_source})\n" if review_input.rules_source else ""
        blocks["TEAM RULES"] = source + review_input.rules.strip()
    if review_input.related_code or review_input.related_facts:
        blocks["RELATED CODE"] = render_related(review_input)
    return blocks


def verify_user_message(ticket: Ticket | None, review_input: ReviewInput, max_chars: int,
                        candidates: list[Finding], blocks: dict[str, str] | None = None) -> str:
    user, _, _ = build_user_message(ticket, review_input, max_chars,
                                    extra_blocks={**(blocks or {}), "CANDIDATE FINDINGS": render_candidates(candidates)})
    return user
