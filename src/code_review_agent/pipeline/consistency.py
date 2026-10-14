"""Does the requirements checklist agree with the findings?

Weaker models sometimes mark a criterion `met` while a finding says the code it cites is wrong. We never change a
verdict by guessing; `check_consistency` points the human at the disagreement.
"""

from __future__ import annotations

from ..schemas import Category, CriterionCheck, Finding, ProblemKind, ValidationProblem
from .merge import code_quotes
from .textutil import short

# Findings that say "the behaviour is wrong". A security or style finding on the code a `met` verdict cites is a
# different matter (the requirement can be met by insecure code), so only these can contradict a `met`.
_BEHAVIOUR_CATEGORIES = {Category.LOGIC_DEFECT, Category.BOUNDARY_CONDITION, Category.REQUIREMENT_MISMATCH}


def check_consistency(criteria: list[CriterionCheck], findings: list[Finding]) -> list[ValidationProblem]:
    """Flag a criterion marked `met` when a finding reports a problem in the code that verdict cites.

    Weaker models sometimes contradict themselves (checklist says met, a finding says the same line is wrong).
    We never change a verdict by guessing; we point the human at the disagreement. A finding counts when it sits on
    the verdict's own file and line, or quotes the same code, and says the behaviour is wrong (see
    `_BEHAVIOUR_CATEGORIES`): security and style findings do not contradict a met requirement.
    """
    problems = []
    for index, check in enumerate(criteria):
        if check.verdict != "met":
            continue
        cited = code_quotes(check.evidence)
        for number, f in enumerate(findings, 1):
            if f.category not in _BEHAVIOUR_CATEGORIES:
                continue
            same_place = bool(check.file) and f.file == check.file and check.line is not None and f.line == check.line
            if same_place or (cited & code_quotes(f.evidence)):
                problems.append(ValidationProblem(
                    criterion_index=index, kind=ProblemKind.INCONSISTENT_VERDICT,
                    message=f"Marked met, but finding {number} ('{short(f.title, 70)}') reports a problem in the code "
                            "this verdict cites. Check this verdict yourself."))
                break
    return problems
