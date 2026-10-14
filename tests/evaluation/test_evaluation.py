"""Stage 5 tests: benchmark data integrity and scoring maths.

No real model is used. `test_eval_run_*` use the fake local Ollama server from
test_model_client (MOCKED) to prove the plumbing, not review quality.
"""

import json
from pathlib import Path

import pytest

from code_review_agent.app.cli import main
from code_review_agent.connectors.snapshot import load_example, load_expected
from code_review_agent.context.builder import build_context
from code_review_agent.evaluation.scoring import (
    EvaluationError,
    FindingLabel,
    LabelFile,
    LoadedRun,
    Split,
    Verdict,
    build_label_template,
    discover_runs,
    render_scoreboard,
    score_run,
    suggest_labels,
    totals,
)
from code_review_agent.llm.client import ModelSettings
from code_review_agent.pipeline.records import (
    RunRecord,
    save_result,
    save_run,
    sent_text,
)
from code_review_agent.pipeline.validation import _index_diff
from code_review_agent.schemas import (
    Coverage,
    ExpectedFinding,
    ExpectedReview,
    FailureKind,
    Finding,
    ProblemKind,
    ReviewFailure,
    ReviewResult,
    ValidationProblem,
)
from tests.llm.test_model_client import FakeOllama

ROOT = Path(__file__).resolve().parents[2]
CASES = ROOT / "evaluation" / "cases"
EXAMPLES = ROOT / "examples"
EXPECTED = ROOT / "evaluation" / "expected"
SPLIT = ROOT / "evaluation" / "split.json"

CORE_GROUPS = {"boundary", "logic", "requirement", "error_handling", "security", "correct"}


def case_dir(case_id: str) -> Path:
    return CASES / case_id if (CASES / case_id).is_dir() else EXAMPLES / case_id


@pytest.fixture(scope="module")
def split() -> Split:
    return Split.model_validate_json(SPLIT.read_text(encoding="utf-8"))


# ============================================================ benchmark data tests


def test_split_is_disjoint_and_covers_every_case_folder(split):
    on_disk = {p.name for p in CASES.iterdir() if p.is_dir()} | {p.name for p in EXAMPLES.iterdir() if p.is_dir()}
    assert set(split.dev) | set(split.heldout) == on_disk
    assert not set(split.dev) & set(split.heldout)
    assert len(split.dev) == len(set(split.dev)) and len(split.heldout) == len(set(split.heldout))


def test_split_model_rejects_overlap():
    with pytest.raises(ValueError):
        Split(dev=["a", "b"], heldout=["b"])


def test_every_case_loads_and_has_a_matching_expected_file(split):
    for case_id in split.dev + split.heldout:
        ticket, review_input = load_example(case_dir(case_id))
        expected = load_expected(EXPECTED / f"{case_id}.json")
        assert expected.case_id == case_id
        assert ticket is not None and review_input.diff.strip()
        assert expected.group, f"{case_id} has no group"


def test_both_splits_cover_all_core_groups(split):
    def groups(ids):
        return {load_expected(EXPECTED / f"{i}.json").group for i in ids}

    assert CORE_GROUPS <= groups(split.dev)
    assert CORE_GROUPS <= groups(split.heldout)


def test_expected_lines_point_at_the_anchor_text_in_the_diff(split):
    checked = 0
    for case_id in split.dev + split.heldout:
        _, review_input = load_example(case_dir(case_id))
        shown, _ = _index_diff(review_input.diff)
        for exp in load_expected(EXPECTED / f"{case_id}.json").expected_findings:
            assert exp.line is not None and exp.code_anchor, f"{case_id}: needs line and anchor"
            assert exp.file in shown, f"{case_id}: {exp.file} not in diff"
            assert exp.line in shown[exp.file], f"{case_id}: line {exp.line} not shown in diff"
            assert exp.code_anchor in shown[exp.file][exp.line], f"{case_id}: anchor not on line {exp.line}"
            checked += 1
    assert checked >= 15  # a vacuous pass must not be possible


def test_case_folders_contain_only_model_inputs(split):
    # `analysis` holds full "after" files for the static-analysis tools only (never shown to the model);
    # `rules.md` would be team rules. Expected answers must still never live here.
    allowed = {"ticket.json", "pr.json", "change.diff", "supporting", "analysis", "rules.md"}
    for case_id in split.dev + split.heldout:
        assert {p.name for p in case_dir(case_id).iterdir()} <= allowed


def test_expected_answers_never_reach_the_prompt(split):
    for case_id in split.dev + split.heldout:
        ticket, review_input = load_example(case_dir(case_id))
        expected = load_expected(EXPECTED / f"{case_id}.json")
        ctx = build_context(ticket, review_input)
        text = ctx.system + ctx.user
        secrets = [e.description for e in expected.expected_findings] + expected.must_not_report
        secrets += expected.expected_limitations + ([expected.notes] if expected.notes else [])
        for s in secrets:
            assert s not in text, f"{case_id}: expected text leaked into the prompt"


def test_correct_cases_expect_nothing_and_defect_cases_expect_something(split):
    for case_id in split.dev + split.heldout:
        exp = load_expected(EXPECTED / f"{case_id}.json")
        if exp.group in {"correct", "ambiguous"}:
            assert exp.expected_findings == []
        else:
            assert len(exp.expected_findings) >= 1


# ================================================================ scoring helpers


def make_finding(file="a.py", line=5, category="logic_defect", title="t") -> Finding:
    return Finding.model_validate({
        "category": category, "severity": "medium", "file": file, "line": line, "title": title,
        "explanation": "x", "evidence": [{"source": "code", "quote": "q"}],
    })


def make_run(findings=None, expected=None, name="run1", failed=False, duration=2.0, group="logic") -> LoadedRun:
    record = RunRecord(
        case_id="case1", created_at="2026-10-05T00:00:00+00:00", prompt_version="review_v1",
        settings=ModelSettings(model="m"), max_chars=1000, coverage=Coverage(complete=True),
        duration_s=duration, wall_clock_s=duration + 0.5, prompt_tokens=100, completion_tokens=20,
    )
    if failed:
        result = ReviewResult(status="failed", error=ReviewFailure(kind=FailureKind.TIMEOUT, message="x"))
    else:
        result = ReviewResult(status="completed", findings=findings or [])
    exp = ExpectedReview(case_id="case1", group=group, expected_findings=expected or [])
    return LoadedRun(name, record, result, exp)


def expect(file="a.py", line=5, category="logic_defect") -> ExpectedFinding:
    return ExpectedFinding(category=category, file=file, line=line, description="d")


def lab(i, verdict, matches=None, **kw) -> FindingLabel:
    return FindingLabel(finding_index=i, verdict=verdict, matches=matches, **kw)


# ==================================================================== scoring maths


def test_perfect_review_scores_one():
    run = make_run([make_finding()], [expect()])
    s = score_run(run, [lab(0, Verdict.TP, 0)])
    t = totals([s])
    assert (s.tp, s.fp, s.fn) == (1, 0, 0)
    assert (t.precision, t.recall, t.f1) == (1.0, 1.0, 1.0)


def test_false_positive_on_correct_change_lowers_precision():
    s = score_run(make_run([make_finding()], []), [lab(0, Verdict.FP)])
    t = totals([s])
    assert (s.tp, s.fp, s.fn) == (0, 1, 0)
    assert t.precision == 0.0 and t.recall is None and t.f1 is None


def test_missed_defect_is_a_false_negative():
    s = score_run(make_run([], [expect()]), [])
    t = totals([s])
    assert (s.tp, s.fp, s.fn) == (0, 0, 1)
    assert t.recall == 0.0 and t.precision is None


def test_precision_recall_f1_arithmetic():
    # 3 TP, 1 FP, 2 FN across runs -> P=3/4, R=3/5, F1=2PR/(P+R)
    a = score_run(make_run([make_finding(), make_finding(line=9)], [expect(), expect(line=9), expect(line=20)], name="a"),
                  [lab(0, Verdict.TP, 0), lab(1, Verdict.TP, 1)])
    b = score_run(make_run([make_finding(), make_finding(line=50)], [expect(), expect(line=30)], name="b"),
                  [lab(0, Verdict.TP, 0), lab(1, Verdict.FP)])
    t = totals([a, b])
    assert (t.tp, t.fp, t.fn) == (3, 1, 2)
    assert t.precision == pytest.approx(0.75) and t.recall == pytest.approx(0.6)
    assert t.f1 == pytest.approx(2 * 0.75 * 0.6 / (0.75 + 0.6))


def test_f1_is_zero_when_precision_and_recall_are_zero():
    s = score_run(make_run([make_finding()], [expect(line=40)]), [lab(0, Verdict.FP)])
    assert totals([s]).f1 == 0.0


def test_duplicate_report_counts_once():
    run = make_run([make_finding(), make_finding(title="same defect again")], [expect()])
    s = score_run(run, [lab(0, Verdict.TP, 0), lab(1, Verdict.DUPLICATE, 0)])
    assert (s.tp, s.fp, s.duplicate) == (1, 0, 1)


def test_extra_findings_do_not_affect_precision():
    run = make_run([make_finding(), make_finding(line=9, category="maintainability")], [expect()])
    s = score_run(run, [lab(0, Verdict.TP, 0), lab(1, Verdict.EXTRA)])
    t = totals([s])
    assert (s.tp, s.fp, s.extra) == (1, 0, 1) and t.precision == 1.0


def test_failed_review_counts_expected_defects_as_missed():
    s = score_run(make_run(failed=True, expected=[expect(), expect(line=9)]), None)
    assert s.failed and (s.tp, s.fp, s.fn) == (0, 0, 2)
    assert totals([s]).failed == 1


def test_category_and_location_accuracy_on_true_positives():
    run = make_run([make_finding(line=6, category="requirement_mismatch"), make_finding(line=30, file="b.py")],
                   [expect(line=5), expect(file="b.py", line=9)])
    s = score_run(run, [lab(0, Verdict.TP, 0), lab(1, Verdict.TP, 1)])
    assert s.tp == 2
    assert s.cat_ok == 1  # first finding has another category, still a TP
    assert (s.loc_exact, s.loc_near) == (0, 1)  # line 6 vs 5 is near; 30 vs 9 is not


def test_usefulness_is_collected():
    s = score_run(make_run([make_finding()], [expect()]), [lab(0, Verdict.TP, 0, usefulness=2)])
    assert s.usefulness == [2]


@pytest.mark.parametrize(
    "labels",
    [
        [],  # unlabelled finding
        [lab(0, Verdict.TP, 0), lab(1, Verdict.TP, 0)],  # one defect matched twice
        [lab(0, Verdict.DUPLICATE, 0), lab(1, Verdict.FP)],  # duplicate without a tp
        [lab(0, Verdict.TP, 3), lab(1, Verdict.FP)],  # expected index out of range
        [lab(0, Verdict.FP), lab(0, Verdict.FP), lab(1, Verdict.FP)],  # same index twice
        [lab(0, Verdict.FP), lab(1, Verdict.FP), lab(7, Verdict.FP)],  # label for no finding
    ],
)
def test_inconsistent_labels_are_rejected(labels):
    run = make_run([make_finding(), make_finding(line=9)], [expect()])
    with pytest.raises(EvaluationError):
        score_run(run, labels)


def test_label_validation_rules():
    with pytest.raises(ValueError):
        FindingLabel(finding_index=0, verdict=Verdict.TP)  # tp needs `matches`
    with pytest.raises(ValueError):
        FindingLabel(finding_index=0, verdict=Verdict.FP, matches=0)  # fp cannot have `matches`
    with pytest.raises(ValueError):
        FindingLabel(finding_index=0, verdict=Verdict.EXTRA, usefulness=3)


# ============================================================== suggestions + files


def test_suggestions_from_location():
    run = make_run([make_finding(line=5), make_finding(line=6, title="again"), make_finding(file="other.py")],
                   [expect(line=5)])
    got = [(label.verdict, label.matches) for label in suggest_labels(run)]
    assert got == [(Verdict.TP, 0), (Verdict.DUPLICATE, 0), (Verdict.FP, None)]


def test_template_keeps_existing_human_labels():
    run = make_run([make_finding()], [expect()])
    existing = LabelFile(reviewed_by="", labels={"run1": [lab(0, Verdict.EXTRA, note="human decision")]})
    merged = build_label_template([run], existing)
    assert merged.labels["run1"][0].verdict == Verdict.EXTRA


def test_scoreboard_is_provisional_until_a_human_is_named():
    run = make_run([make_finding()], [expect()])
    scores = [score_run(run, [lab(0, Verdict.TP, 0)])]
    draft = render_scoreboard(scores, LabelFile(draft_by="assistant"), "dev", [run])
    final = render_scoreboard(scores, LabelFile(reviewed_by="A. Student"), "dev", [run])
    assert "PROVISIONAL" in draft and "draft by: assistant" in draft
    assert "PROVISIONAL" not in final and "A. Student" in final
    assert "not measured" in final  # cost is never invented
    assert "Precision: 1.00" in final


def write_run(runs_dir: Path, model="gpt-test", case_id="free-shipping-faulty", raw='{"findings": []}') -> Path:
    ticket, review_input = load_example(EXAMPLES / case_id)
    ctx = build_context(ticket, review_input)
    record = RunRecord(
        case_id=case_id, created_at="2026-10-05T00:00:00+00:00", prompt_version="review_v1",
        settings=ModelSettings(model=model), max_chars=30000, coverage=ctx.coverage, raw_response=raw,
    )
    from code_review_agent.pipeline.validation import finalize_review
    from code_review_agent.reporting.report import render_markdown

    folder = save_run(record, sent_text(ctx.system, ctx.user), runs_dir)
    result = finalize_review(record, ticket, review_input)
    save_result(folder, result.model_dump_json(), render_markdown(result))
    return folder


def test_two_runs_in_the_same_second_do_not_overwrite_each_other(tmp_path):
    first = write_run(tmp_path)
    second = write_run(tmp_path)  # identical timestamp
    assert first != second and first.exists() and second.exists()
    assert len(list(tmp_path.rglob("run.json"))) == 2


def test_discover_runs_skips_file_validation_runs_and_unknown_cases(tmp_path):
    write_run(tmp_path / "a")
    write_run(tmp_path / "b", model="(none: text supplied from a file)")
    write_run(tmp_path / "c", case_id="free-shipping-faulty")
    runs, notes = discover_runs(tmp_path, EXPECTED)
    assert len(runs) == 2
    assert any("no model ran" in n for n in notes)


def test_revalidate_recomputes_results_from_saved_responses(tmp_path):
    raw_numbered = json.dumps({"findings": [{
        "category": "boundary_condition", "severity": "medium", "file": "shop/shipping.py", "line": 6,
        "title": "t", "explanation": "e",
        "evidence": [{"source": "ticket", "quote": "1. Orders of $100 or more ship for free."}],
    }], "limitations": []})
    folder = write_run(tmp_path, raw=raw_numbered)
    # Simulate a result produced by an older, stricter validator (a false alarm).
    result = ReviewResult.model_validate_json((folder / "result.json").read_text(encoding="utf-8"))
    result.problems = [ValidationProblem(finding_index=0, kind=ProblemKind.QUOTE_NOT_FOUND, message="old false alarm")]
    save_result(folder, result.model_dump_json(), "old report")
    assert main(["eval-revalidate", str(tmp_path)]) == 0
    fresh = ReviewResult.model_validate_json((folder / "result.json").read_text(encoding="utf-8"))
    assert fresh.problems == []


def test_revalidate_refuses_when_case_inputs_changed(tmp_path, capsys):
    folder = write_run(tmp_path)
    (folder / "context.txt").write_text("a different context than the case produces now", encoding="utf-8")
    assert main(["eval-revalidate", str(tmp_path)]) == 1
    assert "changed since this run" in capsys.readouterr().out


def test_eval_score_cli_end_to_end(tmp_path, capsys):
    folder = write_run(tmp_path / "runs", raw=(ROOT / "tests/fixtures/raw/real-gpt-oss-faulty.json").read_text(encoding="utf-8"))
    labels = tmp_path / "labels.json"
    assert main(["eval-template", str(tmp_path / "runs"), "--out", str(labels)]) == 0
    data = json.loads(labels.read_text(encoding="utf-8"))
    assert data["labels"][folder.name][0]["verdict"] == "tp"  # suggested from location
    data["reviewed_by"] = "Test Reviewer"
    labels.write_text(json.dumps(data), encoding="utf-8")
    capsys.readouterr()
    out = tmp_path / "results.md"
    assert main(["eval-score", str(tmp_path / "runs"), "--labels", str(labels), "--split", "dev", "--out", str(out)]) == 0
    text = out.read_text(encoding="utf-8")
    assert "Precision: 1.00" in text and "Recall: 1.00" in text and "PROVISIONAL" not in text


def test_eval_score_cli_rejects_missing_labels(tmp_path, capsys):
    write_run(tmp_path / "runs", raw=(ROOT / "tests/fixtures/raw/real-gpt-oss-faulty.json").read_text(encoding="utf-8"))
    labels = tmp_path / "labels.json"
    labels.write_text(LabelFile().model_dump_json(), encoding="utf-8")
    assert main(["eval-score", str(tmp_path / "runs"), "--labels", str(labels)]) == 1
    assert "Label problem" in capsys.readouterr().err


# ==================================================================== eval-run CLI


def test_heldout_requires_explicit_freeze_confirmation(tmp_path, capsys):
    code = main(["eval-run", "--split", "heldout", "--runs", str(tmp_path)])
    assert code == 1 and "frozen" in capsys.readouterr().err
    assert not any(tmp_path.iterdir())  # nothing was run


def test_eval_run_repeats_each_case_MOCKED(tmp_path):
    server = FakeOllama(content='{"findings": [], "limitations": []}')
    try:
        code = main(["eval-run", "--cases", "free-shipping-fixed,free-shipping-faulty", "--repeat", "2",
                     "--pipeline", "single", "--host", server.host, "--model", "fake", "--runs", str(tmp_path)])
    finally:
        server.close()
    assert code == 0
    assert len(server.requests) == 4
    assert len(list(tmp_path.rglob("result.json"))) == 4
