"""Merging reports of the same issue into one finding.

Specialists look at a problem from different angles, so one defect often comes back several times (and a static-analysis
tool may report it too). `merge_candidates` folds those reports into one finding that keeps every quote and remembers
every pass that reported it. Unrelated remarks that merely share a line stay separate: see `_same_subject`.
"""

from __future__ import annotations

import re

from .schemas import (
    WHOLE_CHANGE,
    Category,
    Evidence,
    Finding,
    Severity,
)
from .textutil import short

_SEVERITY_RANK = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2, Severity.LOW: 3}
# When two reports describe one issue, the more specific category wins (security before logic, and so on).
_SPECIFICITY = [Category.SECURITY, Category.BOUNDARY_CONDITION, Category.ERROR_HANDLING,
                Category.LOGIC_DEFECT, Category.MAINTAINABILITY, Category.REQUIREMENT_MISMATCH]
NEARBY_LINES = 3  # a criterion finding may sit this many lines from the defect it describes
RELATED_WORD_OVERLAP = 0.30  # share of the shorter text's content words that two reports must have in common
_STOPWORDS = frozenset(
    "the a an of to in is are be it this that for and or not with by as on at from if its which than then so no can may will "
    "should would does do has have been was were their there into only also but".split())


def _content_words(f: Finding) -> set[str]:
    text = f"{f.title} {f.explanation}".lower()
    return {w for w in re.findall(r"[a-z_][a-z0-9_]{3,}", text) if w not in _STOPWORDS}


def _same_subject(a: Finding, b: Finding) -> bool:
    """Do two reports on the same spot talk about the same thing? Specialists look at a problem from different angles
    (the ticket, bugs, security, the team rules), so the same defect comes back under different categories. But two
    UNRELATED remarks can sit on one line too (a speculative security worry and a missing test), and merging those makes
    the verifier judge a mixed claim and dismiss both. So reports of different categories are folded only when they quote
    the same code, use much the same words, or one is backed by a static-analysis tool (a deterministic fact about the line).
    """
    if "tool" in (a.source, b.source):
        return True
    if code_quotes(a.evidence) & code_quotes(b.evidence):
        return True
    words_a, words_b = _content_words(a), _content_words(b)
    if not words_a or not words_b:
        return False
    return len(words_a & words_b) / min(len(words_a), len(words_b)) >= RELATED_WORD_OVERLAP


def _same_issue(a: Finding, b: Finding) -> bool:
    """One report per issue: the same file and line (or, for a criterion finding, a few lines apart), and, when the
    categories differ, the same subject (see `_same_subject`). `merge_candidates` keeps every explanation and quote."""
    if a.file != b.file or a.file == WHOLE_CHANGE:
        return False
    if a.line is not None and a.line == b.line:
        return a.category == b.category or _same_subject(a, b)
    # A criterion that is not met points at "where the code concerned is" (often the whole function), while the
    # defects pass points at the exact line: a few lines apart can still be the same problem. Style findings stay apart.
    if a.line is not None and b.line is not None and abs(a.line - b.line) <= NEARBY_LINES:
        pair = {a.category, b.category}
        if Category.REQUIREMENT_MISMATCH in pair and Category.MAINTAINABILITY not in pair:
            return _same_subject(a, b)
    return a.category == b.category and _norm(a.title) == _norm(b.title)


def _norm(title: str) -> str:
    return " ".join("".join(c if c.isalnum() else " " for c in title.lower()).split())


def merge_candidates(findings: list[Finding]) -> tuple[list[Finding], int]:
    """Fold reports of the same issue into one finding; order by severity.

    Two reports are the same issue when they cite the same file and line, whatever their categories, or share
    file, category and title. The merged finding keeps the more specific category, the higher severity, all
    evidence, remembers every pass that reported it, and, when the other report comes from another category, adds its
    explanation ("Also reported by ...") so a second, different problem on the same line is not hidden.
    """
    merged: list[Finding] = []
    for f in findings:
        for i, g in enumerate(merged):
            if not _same_issue(g, f):
                continue
            primary, other = (g, f) if _SPECIFICITY.index(g.category) <= _SPECIFICITY.index(f.category) else (f, g)
            seen = {(e.source, e.quote) for e in primary.evidence}
            evidence = list(primary.evidence) + [e for e in other.evidence if (e.source, e.quote) not in seen]
            explanation = primary.explanation
            if _norm(other.explanation) not in _norm(explanation) and other.category != primary.category:
                who = ", ".join(other.found_by) or "another pass"
                explanation += f" Also reported by {who} as {other.category.value}: {short(other.explanation, 400)}"
            merged[i] = primary.model_copy(update={
                "severity": min(g.severity, f.severity, key=_SEVERITY_RANK.__getitem__),
                "explanation": explanation,
                "evidence": evidence,
                "found_by": list(dict.fromkeys([*g.found_by, *f.found_by])),
                "source": "tool" if "tool" in (g.source, f.source) else "llm",  # one tool report makes it tool-backed
            })
            break
        else:
            merged.append(f)
    order = sorted(range(len(merged)), key=lambda i: (_SEVERITY_RANK[merged[i].severity], i))
    return [merged[i] for i in order], len(findings) - len(merged)


def code_quotes(evidence: list[Evidence]) -> set[str]:
    return {" ".join(e.quote.split()) for e in evidence if e.source == "code" and e.quote.strip()}
