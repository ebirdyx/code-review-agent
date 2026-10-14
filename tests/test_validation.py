"""Stage 4 tests: parsing, validation, dedupe, grounding checks and the report.

Raw-text fixtures live in tests/fixtures/raw. `real-gpt-oss-faulty.json` is an
actual response from gpt-oss:120b (Ollama Cloud); the others are hand-written to
trigger specific problems. No model is called in these tests.
"""

import json
from pathlib import Path

import pytest

from code_review_agent.app.cli import main
from code_review_agent.connectors.snapshot import load_example
from code_review_agent.llm.client import ModelSettings
from code_review_agent.pipeline.records import RunRecord
from code_review_agent.pipeline.validation import (
    InvalidOutput,
    check_grounding,
    deduplicate,
    finalize_review,
    parse_model_output,
)
from code_review_agent.reporting.report import render_markdown
from code_review_agent.schemas import (
    Coverage,
    FailureKind,
    Finding,
    ProblemKind,
    ReviewFailure,
    ReviewResult,
    SupportingFile,
)

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "tests" / "fixtures" / "raw"
EXAMPLES = ROOT / "examples"


def raw(name: str) -> str:
    return (RAW / name).read_text(encoding="utf-8")


def record(raw_text: str | None = None, **kwargs) -> RunRecord:
    return RunRecord(
        case_id="free-shipping-faulty",
        created_at="2026-10-05T00:00:00+00:00",
        prompt_version="review_v1",
        settings=ModelSettings(model="test-model"),
        max_chars=30000,
        coverage=Coverage(complete=True),
        raw_response=raw_text,
        **kwargs,
    )


def finalize(raw_text: str, case: str = "free-shipping-faulty", **kwargs) -> ReviewResult:
    ticket, review_input = load_example(EXAMPLES / case)
    return finalize_review(record(raw_text, **kwargs), ticket, review_input)


def finding(**overrides) -> Finding:
    data = {
        "category": "boundary_condition",
        "severity": "medium",
        "file": "shop/shipping.py",
        "line": 6,
        "title": "Boundary excluded",
        "explanation": "Orders of exactly 100 pay shipping.",
        "evidence": [{"source": "code", "quote": "if total > 100:"}],
    }
    return Finding.model_validate({**data, **overrides})


# ------------------------------------------------------------------- parsing


def test_real_model_output_parses_and_is_fully_grounded():
    result = finalize(raw("real-gpt-oss-faulty.json"))
    assert result.status == "completed"
    assert len(result.findings) == 1
    assert result.findings[0].line == 6
    assert result.problems == []  # file, line and both quotes exist in the input


def test_empty_findings_is_a_completed_review():
    result = finalize(raw("empty-findings.json"), case="free-shipping-fixed")
    assert result.status == "completed"
    assert result.findings == [] and result.error is None


def test_markdown_fence_is_tolerated_but_flagged():
    review, warnings = parse_model_output(raw("duplicates-in-fence.txt"))
    assert len(review.findings) == 2
    assert [w.kind for w in warnings] == [ProblemKind.FORMAT_WARNING]


def test_malformed_json_fails_with_a_clear_reason():
    result = finalize(raw("malformed.txt"))
    assert result.status == "failed"
    assert result.error.kind == FailureKind.INVALID_OUTPUT
    assert "not valid JSON" in result.error.message
    assert result.findings == []


def test_truncated_output_mentions_token_limit():
    result = finalize('{"findings": [', done_reason="length")
    assert result.status == "failed"
    assert "token limit" in result.error.message


def test_empty_response_fails():
    assert finalize("   ").status == "failed"


@pytest.mark.parametrize(
    ("text", "expected_in_message"),
    [
        ('{"limitations": [], "findings": "none"}', "findings"),  # wrong type
        ('{"findings": [{"category": "style"}]}', "category"),  # disallowed value
        ('{"findings": [], "verdict": "approve"}', "verdict"),  # extra field
        ("[1, 2]", "(root)"),  # JSON, but not an object
    ],
)
def test_schema_violations_fail_and_name_the_problem(text, expected_in_message):
    with pytest.raises(InvalidOutput) as info:
        parse_model_output(text)
    assert expected_in_message in str(info.value)


def test_failed_model_call_stays_failed_with_its_original_error():
    error = ReviewFailure(kind=FailureKind.TIMEOUT, message="no answer in 60 s")
    result = finalize_review(record(error=error), None, load_example(EXAMPLES / "free-shipping-faulty")[1])
    assert result.status == "failed" and result.error.kind == FailureKind.TIMEOUT


# ------------------------------------------------- one bad item must not cost the good ones


def test_real_model_output_with_one_malformed_finding_keeps_the_valid_one():
    # REAL gpt-oss:120b output: finding 0 is the correct boundary bug, finding 1 cites the invalid
    # evidence source "team_rules". The whole answer used to be thrown away.
    from code_review_agent.pipeline.validation import DROPPED, parse_json_output
    from code_review_agent.schemas import ModelReview

    review, warnings = parse_json_output(raw("real-gpt-oss-defects-one-bad-source.json"), ModelReview)
    assert [f.line for f in review.findings] == [11]  # the correct finding survived
    assert review.findings[0].category == "boundary_condition"
    assert len(warnings) == 1 and warnings[0].message.startswith(DROPPED)
    assert "findings[1]" in warnings[0].message and "Docstring does not describe return value" in warnings[0].message
    assert "evidence.1.source" in warnings[0].message


def test_when_every_item_is_malformed_the_answer_still_fails():
    with pytest.raises(InvalidOutput, match="category"):
        parse_model_output('{"findings": [{"category": "style"}, {"category": "taste"}]}')


def test_a_problem_outside_the_items_is_not_papered_over():
    with pytest.raises(InvalidOutput, match="verdict"):
        parse_model_output(j({"findings": [], "verdict": "approve"}))
    good = json.dumps(make_valid_finding())
    with pytest.raises(InvalidOutput):  # one good item, but the object itself has a stray field
        parse_model_output('{"findings": [' + good + '], "verdict": "approve"}')


def make_valid_finding():
    return {"category": "boundary_condition", "severity": "medium", "file": "shop/shipping.py", "line": 6, "title": "t",
            "explanation": "e", "evidence": [{"source": "code", "quote": "if total > 100:"}]}


def j(obj) -> str:
    return json.dumps(obj)


def test_dropped_items_are_lost_coverage_in_the_single_pass_result_not_a_silent_empty():
    text = j({"findings": [make_valid_finding(), {"category": "style"}], "limitations": []})
    result = finalize(text)
    assert result.status == "completed" and len(result.findings) == 1
    assert result.coverage.complete is False
    assert any(o.startswith("model output: Dropped findings[1]") for o in result.coverage.omitted)
    assert not any(p.message.startswith("Dropped") for p in result.problems)  # reported once, as coverage
    assert "Partial coverage" in render_markdown(result)


def test_the_real_malformed_answer_through_the_whole_single_pass_pipeline():
    result = finalize(raw("real-gpt-oss-defects-one-bad-source.json"))  # graded against the wrong case on purpose
    assert result.status == "completed" and [f.line for f in result.findings] == [11]
    assert any("Dropped" in o for o in result.coverage.omitted)
    assert any(p.kind == ProblemKind.UNKNOWN_FILE for p in result.problems)  # wrong case: the file is not in its diff


# ---------------------------------------------------------------- duplicates


def test_same_place_and_category_is_a_duplicate():
    kept, removed = deduplicate([finding(), finding(title="Different wording")])
    assert len(kept) == 1 and removed == 1


def test_same_title_in_different_wording_of_case_is_a_duplicate():
    kept, removed = deduplicate([finding(line=6), finding(line=None, title="BOUNDARY  excluded!")])
    assert (len(kept), removed) == (1, 1)


def test_different_problems_are_both_kept():
    kept, removed = deduplicate([finding(), finding(line=7, title="Other issue", category="logic_defect")])
    assert (len(kept), removed) == (2, 0)


def test_duplicates_in_pipeline_are_counted():
    result = finalize(raw("duplicates-in-fence.txt"))
    assert len(result.findings) == 1 and result.duplicates_removed == 1


# ----------------------------------------------------------------- grounding


def test_bad_locations_and_quotes_are_reported_not_repaired():
    result = finalize(raw("bad-grounding.json"))
    assert result.status == "completed"
    kinds = [(p.finding_index, p.kind) for p in result.problems]
    assert (0, ProblemKind.LINE_NOT_IN_DIFF) in kinds  # line 99
    assert (0, ProblemKind.QUOTE_NOT_FOUND) in kinds  # invented ticket quote
    assert (1, ProblemKind.UNKNOWN_FILE) in kinds
    assert (1, ProblemKind.QUOTE_NOT_FOUND) in kinds
    # The findings themselves are untouched: line 99 was not "corrected" to 6.
    assert result.findings[0].line == 99
    assert result.findings[1].file == "shop/payments.py"


def test_line_none_is_acceptable():
    ticket, review_input = load_example(EXAMPLES / "free-shipping-faulty")
    assert check_grounding([finding(line=None)], ticket, review_input) == []


def test_context_line_counts_as_shown_but_unlisted_line_does_not():
    ticket, review_input = load_example(EXAMPLES / "free-shipping-faulty")
    assert check_grounding([finding(line=4)], ticket, review_input) == []  # context line
    problems = check_grounding([finding(line=3)], ticket, review_input)  # outside the hunk
    assert problems[0].kind == ProblemKind.LINE_NOT_IN_DIFF


def test_quote_matching_ignores_indentation_differences():
    ticket, review_input = load_example(EXAMPLES / "free-shipping-faulty")
    f = finding(evidence=[{"source": "code", "quote": "if   total >  100:"}])
    assert check_grounding([f], ticket, review_input) == []


def test_quote_with_the_list_number_the_model_was_shown_is_accepted():
    # Regression: the context builder numbers acceptance criteria ("1. ..."). Real models
    # quote them with the number; that is NOT a hallucination.
    ticket, review_input = load_example(EXAMPLES / "free-shipping-faulty")
    f = finding(evidence=[{"source": "ticket", "quote": "1. Orders of $100 or more ship for free."}])
    assert check_grounding([f], ticket, review_input) == []


def test_invented_ticket_quote_is_still_flagged():
    ticket, review_input = load_example(EXAMPLES / "free-shipping-faulty")
    f = finding(evidence=[{"source": "ticket", "quote": "3. Orders ship for free on Sundays."}])
    assert check_grounding([f], ticket, review_input)[0].kind == ProblemKind.QUOTE_NOT_FOUND


def test_ticket_quote_without_ticket_is_flagged():
    _, review_input = load_example(EXAMPLES / "free-shipping-faulty")
    f = finding(evidence=[{"source": "ticket", "quote": "Orders of $100 or more ship for free."}])
    problems = check_grounding([f], None, review_input)
    assert problems[0].kind == ProblemKind.QUOTE_NOT_FOUND and "no ticket" in problems[0].message


def test_supporting_file_lines_are_checked_against_its_length():
    ticket, review_input = load_example(EXAMPLES / "free-shipping-faulty")
    review_input.supporting_files.append(SupportingFile(path="shop/cart.py", content="a\nb\nc\n"))
    ok = finding(file="shop/cart.py", line=3, evidence=[{"source": "code", "quote": "b"}])
    far = finding(file="shop/cart.py", line=4, evidence=[{"source": "code", "quote": "b"}])
    assert check_grounding([ok], ticket, review_input) == []
    assert check_grounding([far], ticket, review_input)[0].kind == ProblemKind.LINE_OUT_OF_RANGE


def test_a_grounded_finding_can_still_be_wrong():
    # Real file, real line, real quotes, but the conclusion is false for the FIXED code.
    # Nothing in validation can detect this: that is the human reviewer's job.
    fixed = (EXAMPLES / "free-shipping-fixed" / "change.diff").read_text(encoding="utf-8")
    assert "total >= 100" in fixed
    wrong = json.dumps(
        {
            "findings": [
                {
                    "category": "boundary_condition",
                    "severity": "high",
                    "file": "shop/shipping.py",
                    "line": 6,
                    "title": "Exact $100 orders are charged",
                    "explanation": "False claim.",
                    "evidence": [{"source": "code", "quote": "if total >= 100:"}],
                }
            ],
            "limitations": [],
        }
    )
    result = finalize(wrong, case="free-shipping-fixed")
    assert result.problems == []  # validation is satisfied...
    assert len(result.findings) == 1  # ...although the finding is a false positive


# -------------------------------------------------------------------- report


def test_report_for_valid_review_shows_location_evidence_and_limitation():
    text = render_markdown(finalize(raw("real-gpt-oss-faulty.json")))
    assert "Status: completed, 1 finding" in text
    assert "`shop/shipping.py:6`" in text
    assert "if total > 100:" in text
    assert "checked against the input" in text
    assert "Limitations stated by the model" in text
    assert "test-model" in text  # model id is taken from the run record
    assert "final decision" in text


def test_report_for_empty_findings_is_not_a_guarantee():
    text = render_markdown(finalize(raw("empty-findings.json"), case="free-shipping-fixed"))
    assert "completed, 0 findings" in text
    assert "not a guarantee" in text and "REVIEW FAILED" not in text


def test_report_for_failed_review_is_clearly_not_empty_findings():
    text = render_markdown(finalize(raw("malformed.txt")))
    assert "REVIEW FAILED" in text and "invalid_output" in text
    assert "not** the same as" in text and "## Findings" not in text


def test_report_flags_unconfirmed_locations():
    text = render_markdown(finalize(raw("bad-grounding.json")))
    assert "NOT FULLY CONFIRMED" in text
    assert "line_not_in_diff" in text and "unknown_file" in text


def test_report_shows_missing_inputs_and_partial_coverage():
    result = finalize(raw("empty-findings.json"), case="free-shipping-fixed")
    result.coverage = Coverage(complete=False, omitted=["diff of big.py: omitted"])
    result.missing_inputs = ["No supporting code was provided; only the diff is visible."]
    text = render_markdown(result)
    assert "Partial coverage" in text and "Not reviewed: diff of big.py" in text
    assert "No supporting code was provided" in text


def test_model_text_cannot_break_out_of_its_code_fence():
    nasty = "```\n# INJECTED HEADING\n```"
    f = finding(evidence=[{"source": "code", "quote": nasty}])
    text = render_markdown(ReviewResult(status="completed", findings=[f]))
    assert "````" in text  # fence is longer than the backticks inside the quote


def test_explanation_is_flattened_into_a_quote():
    f = finding(explanation="line one\n\n# Heading\n- bullet")
    text = render_markdown(ReviewResult(status="completed", findings=[f]))
    assert "> line one # Heading - bullet" in text


# ----------------------------------------------------- the ticket is named in the result


def test_the_report_and_result_name_the_ticket_whose_requirements_were_used():
    with_ticket = finalize(raw("real-gpt-oss-faulty.json"))
    assert with_ticket.run.ticket == "SHOP-42: Free shipping for large orders"
    assert "- **Ticket:** SHOP-42: Free shipping for large orders" in render_markdown(with_ticket)


def test_without_a_ticket_the_report_says_no_requirements_were_available():
    _, review_input = load_example(EXAMPLES / "free-shipping-faulty")
    result = finalize_review(record(raw("real-gpt-oss-faulty.json")), None, review_input)
    assert result.run.ticket is None
    assert "- **Ticket:** none: no requirements were available" in render_markdown(result)


# ----------------------------------------------------------------------- CLI


def test_cli_validate_writes_result_and_report(tmp_path):
    code = main(
        ["validate", str(EXAMPLES / "free-shipping-faulty"), str(RAW / "real-gpt-oss-faulty.json"),
         "--runs", str(tmp_path)]
    )
    assert code == 0
    folder = next(tmp_path.iterdir())
    result = ReviewResult.model_validate_json((folder / "result.json").read_text(encoding="utf-8"))
    assert result.status == "completed" and len(result.findings) == 1
    assert (folder / "report.md").read_text(encoding="utf-8").startswith("# Code review report")
    assert (folder / "raw_response.txt").exists()  # raw text preserved for debugging


def test_cli_validate_returns_error_code_for_failed_review(tmp_path):
    code = main(["validate", str(EXAMPLES / "free-shipping-faulty"), str(RAW / "malformed.txt"),
                 "--runs", str(tmp_path)])
    assert code == 2


# ------------------------------------------------- unquoted field names (seen from real Qwen output)


def test_unquoted_field_names_are_quoted_and_flagged():
    from code_review_agent.pipeline.validation import parse_json_output
    from code_review_agent.schemas import VerifyReview

    review, warnings = parse_json_output(raw("real-qwen-verify-bare-key.txt"), VerifyReview)
    assert review.verdicts[0].verdict == "supported" and review.verdicts[0].index == 1
    assert any("without quotes" in w.message for w in warnings)


def test_the_repair_never_touches_text_inside_strings_and_other_breakage_stays_invalid():
    from code_review_agent.pipeline.validation import InvalidOutput, parse_json_output
    from code_review_agent.schemas import VerifyReview

    note = "a note,\nverdict: not a key"  # json.dumps escapes the newline, so no line can start with a bare word
    ok = '{\n  "verdicts": [],\n  "limitations": [' + json.dumps(note) + "]\n}"
    review, warnings = parse_json_output(ok, VerifyReview)
    assert review.limitations == [note] and not warnings
    with pytest.raises(InvalidOutput, match="not valid JSON"):
        parse_json_output('{\n  "verdicts": [\n    foo bar\n  ]\n}', VerifyReview)
