"""Stage 1 tests. All pure data validation: no model, no network, no mocks."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from code_review_agent.cli import check_examples
from code_review_agent.loading import load_example, load_expected
from code_review_agent.schemas import (
    FailureKind,
    Finding,
    ModelReview,
    ReviewFailure,
    ReviewResult,
    Ticket,
)

ROOT = Path(__file__).resolve().parent.parent


def make_finding(**overrides):
    data = {
        "category": "boundary_condition",
        "severity": "medium",
        "file": "shop/shipping.py",
        "line": 6,
        "title": "Boundary excluded",
        "explanation": "Orders of exactly 100 pay shipping.",
        "evidence": [{"source": "code", "quote": "if total > 100:"}],
    }
    return {**data, **overrides}


def test_valid_finding_parses():
    finding = Finding.model_validate(make_finding())
    assert finding.line == 6


def test_line_is_optional():
    assert Finding.model_validate(make_finding(line=None)).line is None


@pytest.mark.parametrize(
    "override",
    [
        {"category": "style"},  # not an allowed category
        {"severity": "urgent"},  # not an allowed severity
        {"line": 0},  # lines start at 1
        {"evidence": []},  # a finding needs support
        {"title": ""},
        {"unexpected_field": 1},  # extra fields are rejected
    ],
)
def test_invalid_finding_rejected(override):
    with pytest.raises(ValidationError):
        Finding.model_validate(make_finding(**override))


def test_empty_findings_is_a_valid_review():
    review = ModelReview.model_validate({"findings": []})
    assert review.findings == []


def test_completed_with_no_findings_is_valid():
    result = ReviewResult(status="completed")
    assert result.findings == [] and result.error is None


def test_failed_review_requires_error():
    with pytest.raises(ValidationError):
        ReviewResult(status="failed")


def test_failed_review_cannot_carry_findings():
    error = ReviewFailure(kind=FailureKind.TIMEOUT, message="no answer in 60 s")
    with pytest.raises(ValidationError):
        ReviewResult(status="failed", error=error, findings=[Finding.model_validate(make_finding())])


def test_completed_review_cannot_carry_error():
    error = ReviewFailure(kind=FailureKind.TIMEOUT, message="x")
    with pytest.raises(ValidationError):
        ReviewResult(status="completed", error=error)


def test_ticket_key_format_and_empty_criteria():
    assert Ticket(key="SHOP-1", title="t").acceptance_criteria == []
    with pytest.raises(ValidationError):
        Ticket(key="shop-1", title="t")


def test_examples_load_and_diff_matches_expected_line():
    _, review_input = load_example(ROOT / "examples" / "free-shipping-faulty")
    assert "+    if total > 100:" in review_input.diff
    expected = load_expected(ROOT / "evaluation" / "expected" / "free-shipping-faulty.json")
    # The expected line must really be the line added by the diff:
    # hunk starts at new line 4 -> def (4), docstring (5), added `if` (6).
    assert expected.expected_findings[0].line == 6


def test_all_shipped_examples_validate():
    assert check_examples(ROOT / "examples", ROOT / "evaluation" / "expected") == 0


def test_missing_expected_file_is_reported(tmp_path):
    (tmp_path / "examples").mkdir()
    (tmp_path / "expected").mkdir()
    src = ROOT / "examples" / "free-shipping-fixed"
    dst = tmp_path / "examples" / "free-shipping-fixed"
    dst.mkdir()
    for f in src.iterdir():
        (dst / f.name).write_bytes(f.read_bytes())
    assert check_examples(tmp_path / "examples", tmp_path / "expected") == 1
