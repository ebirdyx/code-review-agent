"""Prompt versions are selectable, recorded, and respected when re-validating."""

from pathlib import Path

import pytest

from code_review_agent.cli import main
from code_review_agent.context import (
    DEFAULT_PROMPT_VERSION,
    available_prompt_versions,
    build_context,
    load_system_prompt,
)
from code_review_agent.loading import load_example
from test_evaluation import write_run  # helper that builds a saved run folder

ROOT = Path(__file__).resolve().parent.parent
EXAMPLE = ROOT / "examples" / "free-shipping-faulty"


def test_both_versions_exist_and_default_is_v1_until_a_dev_comparison_says_otherwise():
    assert {"review_v1", "review_v2"} <= set(available_prompt_versions())
    assert DEFAULT_PROMPT_VERSION == "review_v1"


def test_v2_adds_rules_and_keeps_everything_else():
    v1, v2 = load_system_prompt("review_v1"), load_system_prompt("review_v2")
    assert "MOST SPECIFIC" in v2 and "MOST SPECIFIC" not in v1
    assert "must NOT also be reported" in v2
    # Every line of v1 is still present in v2: v2 only adds.
    v2_lines = set(v2.splitlines())
    assert all(line in v2_lines for line in v1.splitlines())


def test_unknown_version_is_rejected_with_the_available_ones():
    with pytest.raises(ValueError, match="review_v1"):
        load_system_prompt("review_v99")


def test_context_records_the_requested_version():
    ticket, review_input = load_example(EXAMPLE)
    ctx = build_context(ticket, review_input, prompt_version="review_v2")
    assert ctx.prompt_version == "review_v2" and "MOST SPECIFIC" in ctx.system
    assert build_context(ticket, review_input).prompt_version == "review_v1"


def test_build_context_cli_does_not_change_default(tmp_path):
    out = tmp_path / "c.txt"
    assert main(["build-context", str(EXAMPLE), "--out", str(out)]) == 0
    assert "MOST SPECIFIC" not in out.read_text(encoding="utf-8")


def test_revalidate_uses_the_prompt_version_of_the_run(tmp_path):
    # A run made with v2 must still be re-validated (its saved context is the v2 one).
    from code_review_agent.model_client import ModelSettings
    from code_review_agent.report import render_markdown
    from code_review_agent.review import RunRecord, save_result, save_run, sent_text
    from code_review_agent.validation import finalize_review

    ticket, review_input = load_example(EXAMPLE)
    ctx = build_context(ticket, review_input, prompt_version="review_v2")
    record = RunRecord(
        case_id="free-shipping-faulty", created_at="2026-10-12T00:00:00+00:00",
        prompt_version="review_v2", settings=ModelSettings(model="m"), max_chars=30000,
        coverage=ctx.coverage, raw_response='{"findings": []}',
    )
    folder = save_run(record, sent_text(ctx.system, ctx.user), tmp_path)
    result = finalize_review(record, ticket, review_input)
    save_result(folder, result.model_dump_json(), render_markdown(result))
    assert main(["eval-revalidate", str(tmp_path)]) == 0

    # And a v1 run in the same folder is still fine.
    write_run(tmp_path / "v1")
    assert main(["eval-revalidate", str(tmp_path)]) == 0


# ---------------------------------------------------------------------------- multi_v3


def test_multi_v3_is_the_default_and_v2_stays_loadable_and_unchanged():
    from code_review_agent.pipeline import MULTI_PROMPT_VERSION, available_multi_versions, load_pass_system

    assert MULTI_PROMPT_VERSION == "multi_v3"
    assert {"multi_v1", "multi_v2", "multi_v3"} <= set(available_multi_versions())
    # Old runs must stay reproducible: the new guidance exists only in v3.
    assert "satisfies the rule in substance" not in load_pass_system("multi_v2", "standards")
    assert "Vague criteria" not in load_pass_system("multi_v2", "compliance")
    assert "outside your scope" not in load_pass_system("multi_v2", "verify")


def test_multi_v3_adds_the_three_guidance_texts_and_keeps_the_rest():
    from code_review_agent.pipeline import load_pass_system

    standards = load_pass_system("multi_v3", "standards")
    assert "satisfies the rule in substance" in standards and "TEAM RULES" in standards and '"rules"' in standards
    compliance = load_pass_system("multi_v3", "compliance")
    assert "Vague criteria" in compliance and "cannot_determine" in compliance and "Read numbers and operators literally" in compliance
    verify = load_pass_system("multi_v3", "verify")
    assert "Never answer that a candidate is outside your scope" in verify and "CANDIDATE FINDINGS" in verify
    for name in ("compliance", "defects", "security"):
        assert '"rules"' not in load_pass_system("multi_v3", name), name  # only the standards pass may cite rules
