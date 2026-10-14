"""The evaluation harness: recorded configurations and side-by-side comparison.

No real model: `FakeOllama` (MOCKED) answers with a fixed review, so these tests prove the plumbing, the recorded
configuration, the scoring and the table, not review quality.
"""

import json
import shutil
from pathlib import Path

import pytest

from code_review_agent.app.cli import main
from code_review_agent.evaluation.comparison import (
    CONFIG_NAME,
    ConfigResult,
    EvalConfig,
    EvalRunEntry,
    auto_label,
    compare,
    load_config,
    per_repeat_totals,
    render_comparison,
    save_config,
)
from code_review_agent.evaluation.scoring import (
    EvaluationError,
    LabelFile,
    RunScore,
    build_label_template,
    discover_runs,
)
from tests.llm.test_model_client import FakeOllama

ROOT = Path(__file__).resolve().parents[2]
EXPECTED = ROOT / "evaluation" / "expected"
CASES = "free-shipping-faulty,free-shipping-fixed"

FINDING = {
    "findings": [{
        "category": "boundary_condition", "severity": "high", "file": "shop/shipping.py", "line": 6,
        "title": "Boundary excluded", "explanation": "total > 100 excludes exactly 100.",
        "evidence": [{"source": "code", "quote": "if total > 100:"}],
    }],
    "limitations": [],
}
NOTHING = {"findings": [], "limitations": []}


def run_eval(tmp_path, name, content, *extra, cases=CASES, repeat=1):
    server = FakeOllama(content=json.dumps(content))
    try:
        code = main(["eval-run", "--cases", cases, "--repeat", str(repeat), "--host", server.host, "--model", "fake",
                     "--runs", str(tmp_path / name), *extra])
    finally:
        server.close()
    assert code == 0
    return tmp_path / name


# ----------------------------------------------------------------- recorded configuration


def test_eval_run_records_the_configuration_and_every_run(tmp_path):
    folder = run_eval(tmp_path, "single", FINDING, "--pipeline", "single", repeat=2)
    config = load_config(folder)
    assert config.label == "single-pass" and config.pipeline == "single" and config.repeat == 2
    assert config.model == "fake" and config.split == "dev" and config.cases == CASES.split(",")
    assert len(config.runs) == 4 and {e.rep for e in config.runs} == {1, 2} and {e.status for e in config.runs} == {"completed"}
    assert all((folder / e.folder).is_dir() for e in config.runs)  # the index points at real run folders
    assert config.created_at and (config.agent_commit is None or len(config.agent_commit) >= 4)


def test_the_single_pipeline_records_tools_context_and_verifier_as_off(tmp_path):
    config = load_config(run_eval(tmp_path, "single", NOTHING, "--pipeline", "single"))
    assert (config.tools, config.context, config.verify, config.passes) == ([], False, False, None)
    assert config.prompt_version == "review_v1"


def test_multi_flags_are_recorded_as_they_will_run_and_make_the_label(tmp_path):
    folder = run_eval(tmp_path, "m", NOTHING, "--pipeline", "multi", "--passes", "defects", "--no-verify", "--no-tools", "--no-context")
    config = load_config(folder)
    assert config.label == "multi-no-tools-no-context-no-verify"
    assert (config.tools, config.context, config.verify, config.passes) == ([], False, False, ["defects"])
    assert config.prompt_version.startswith("multi_")


def test_a_label_can_be_chosen_and_the_default_multi_run_is_called_multi(tmp_path):
    assert load_config(run_eval(tmp_path, "a", NOTHING, "--passes", "defects", "--no-verify", "--label", "my-test")).label == "my-test"
    config = load_config(run_eval(tmp_path, "b", NOTHING, "--passes", "defects", "--no-verify"))
    assert config.label == "multi-no-verify" and config.tools and config.context  # tools and context default on


def test_auto_labels_name_what_differs_from_the_full_pipeline():
    assert auto_label("single", True, ["ruff"], True) == "single-pass"
    assert auto_label("multi", True, ["ruff", "bandit"], True) == "multi"
    assert auto_label("multi", False, [], False) == "multi-no-tools-no-context-no-verify"


def test_cases_dir_evaluates_every_example_folder_found_and_ignores_the_split(tmp_path):
    cases = tmp_path / "pr-cases"
    shutil.copytree(ROOT / "examples" / "free-shipping-faulty", cases / "case-a")
    shutil.copytree(ROOT / "examples" / "free-shipping-faulty", cases / "case-b")
    (cases / "not-a-case").mkdir()  # no pr.json: ignored
    server = FakeOllama(content=json.dumps(NOTHING))
    try:
        code = main(["eval-run", "--cases-dir", str(cases), "--pipeline", "single", "--host", server.host, "--model", "fake",
                     "--runs", str(tmp_path / "out")])
    finally:
        server.close()
    config = load_config(tmp_path / "out")
    assert code == 0 and config.split == "custom" and config.cases == ["case-a", "case-b"]


def test_an_empty_cases_dir_is_an_actionable_error(tmp_path, capsys):
    (tmp_path / "empty").mkdir()
    assert main(["eval-run", "--cases-dir", str(tmp_path / "empty"), "--pipeline", "single", "--host", "http://127.0.0.1:1",
                 "--model", "fake", "--runs", str(tmp_path / "o")]) == 1
    assert "No example folders" in capsys.readouterr().err


# ------------------------------------------------------------------------------- comparison


def test_compare_puts_two_configurations_side_by_side(tmp_path, capsys):
    found = run_eval(tmp_path, "found", FINDING, "--pipeline", "single", "--label", "finds-it")
    missed = run_eval(tmp_path, "missed", NOTHING, "--passes", "defects", "--no-verify", "--no-tools", "--label", "misses-it")
    out_file = tmp_path / "cmp.md"
    capsys.readouterr()  # drop what the two evaluations printed
    assert main(["eval-compare", str(found), str(missed), "--expected", str(EXPECTED), "--out", str(out_file)]) == 0
    text = capsys.readouterr().out
    assert out_file.read_text(encoding="utf-8").strip() == text.strip()
    assert "| finds-it |" in text and "| misses-it |" in text
    differing = text.split("Configurations differ in:")[1].split("\n")[0]
    assert "pipeline" in differing and "prompt_version" in differing and "context" in differing
    assert "tools" not in differing and "verify" not in differing  # both have tools and the verifier off: not a difference
    # The first configuration reports the boundary on both cases: it finds the real defect (TP) and also raises it on the
    # correct case (FP). The second reports nothing: it misses the defect (FN) and raises no false alarm.
    results = text.split("## Results")[1].split("## Per case")[0]
    finds = next(line for line in results.splitlines() if line.startswith("| finds-it |"))
    misses = next(line for line in results.splitlines() if line.startswith("| misses-it |"))
    assert "| 1 | 1 | 0 | 0.50 | 1.00 | 0.67 |" in finds  # TP 1, FP 1, FN 0
    assert "| 0 | 0 | 1 | n/a | 0.00 | n/a |" in misses  # TP 0, FP 0, FN 1; nothing reported, so precision and F1 are undefined
    per_case = text.split("## Per case")[1]
    assert "| free-shipping-faulty | 1 | 1/1 found, 0 FP | 0/1 found, 0 FP |" in per_case
    assert "| free-shipping-fixed | 0 | 1 FP | 0 FP |" in per_case


def test_a_correct_case_counts_false_alarms_and_the_table_says_labels_are_provisional(tmp_path, capsys):
    folder = run_eval(tmp_path, "noisy", FINDING, "--pipeline", "single")  # also "finds" the boundary in the fixed case
    assert main(["eval-compare", str(folder), "--expected", str(EXPECTED)]) == 0
    text = capsys.readouterr().out
    assert "| free-shipping-fixed | 0 | 1 FP |" in text
    assert "PROVISIONAL" in text and "suggested from location only" in text


def test_a_reviewed_label_file_replaces_the_suggestions_and_names_the_reviewer(tmp_path, capsys):
    folder = run_eval(tmp_path, "noisy", FINDING, "--pipeline", "single")
    runs, _ = discover_runs(folder, EXPECTED)
    labels = build_label_template(runs)
    labels.reviewed_by = "Pamela B."
    (folder / "labels.json").write_text(labels.model_dump_json(indent=2), encoding="utf-8")
    assert main(["eval-compare", str(folder), "--expected", str(EXPECTED)]) == 0
    text = capsys.readouterr().out
    assert "labels confirmed by Pamela B." in text and "PROVISIONAL" not in text


def test_a_provisional_label_file_is_reported_as_such(tmp_path, capsys):
    folder = run_eval(tmp_path, "x", FINDING, "--pipeline", "single")
    runs, _ = discover_runs(folder, EXPECTED)
    (folder / "labels.json").write_text(build_label_template(runs).model_dump_json(indent=2), encoding="utf-8")  # no reviewer
    assert main(["eval-compare", str(folder), "--expected", str(EXPECTED)]) == 0
    assert "PROVISIONAL label file" in capsys.readouterr().out


def test_folders_without_a_config_file_are_still_comparable_and_say_so(tmp_path, capsys):
    folder = run_eval(tmp_path, "old", FINDING, "--pipeline", "single")
    (folder / CONFIG_NAME).unlink()  # an evaluation made before configurations were recorded
    assert main(["eval-compare", str(folder), "--expected", str(EXPECTED)]) == 0
    text = capsys.readouterr().out
    assert "| old | (no eval-config.json) |" in text


def test_two_folders_with_the_same_label_stay_distinguishable(tmp_path, capsys):
    a = run_eval(tmp_path, "first", NOTHING, "--pipeline", "single")
    b = run_eval(tmp_path, "second", FINDING, "--pipeline", "single")
    assert main(["eval-compare", str(a), str(b), "--expected", str(EXPECTED)]) == 0
    text = capsys.readouterr().out
    assert "| single-pass (first) |" in text and "| single-pass (second) |" in text
    assert "identical in every recorded setting" in text


def test_compare_errors_are_actionable(tmp_path, capsys):
    assert main(["eval-compare", str(tmp_path / "nope"), "--expected", str(EXPECTED)]) == 1
    assert "is not a folder" in capsys.readouterr().err
    empty = tmp_path / "empty"
    empty.mkdir()
    assert main(["eval-compare", str(empty), "--expected", str(EXPECTED)]) == 1
    assert "no scorable runs" in capsys.readouterr().err
    with pytest.raises(EvaluationError):
        compare([], EXPECTED)


# ------------------------------------------------------------------ variance between repeats


def score(name, tp, fp, fn):
    return RunScore(name=name, case_id="c", group="g", failed=False, tp=tp, fp=fp, fn=fn)


def test_the_spread_between_repeats_is_computed_per_repetition():
    scores = [score("r1a", 1, 0, 1), score("r1b", 1, 0, 0), score("r2a", 0, 1, 2), score("r2b", 1, 0, 0)]
    result = ConfigResult("x", None, [], scores, "basis", rep_of={"r1a": 1, "r1b": 1, "r2a": 2, "r2b": 2})
    first, second = per_repeat_totals(result)
    assert (first.tp, first.fn) == (2, 1) and (second.tp, second.fn) == (1, 2)
    assert round(first.recall, 2) == 0.67 and round(second.recall, 2) == 0.33


def test_without_an_index_all_runs_count_as_one_repetition():
    result = ConfigResult("x", None, [], [score("a", 1, 0, 0), score("b", 0, 0, 1)], "basis")
    assert len(per_repeat_totals(result)) == 1


def test_eval_config_round_trips_and_keeps_run_entries(tmp_path):
    config = EvalConfig(label="l", created_at="t", split="dev", cases=["a"], repeat=1, pipeline="multi", prompt_version="multi_v4",
                        verify=True, tools=["ruff"], context=True, model="m", host="h",
                        runs=[EvalRunEntry(case_id="a", rep=1, folder="a-1", status="completed")])
    save_config(tmp_path / "d", config)
    assert load_config(tmp_path / "d") == config
    assert load_config(tmp_path) is None
    assert isinstance(LabelFile(), LabelFile) and render_comparison is not None


# ------------------------------------------------------------------------- reproducibility


def test_the_recorded_commit_says_when_the_code_that_ran_was_not_committed(monkeypatch):
    import subprocess
    from types import SimpleNamespace

    from code_review_agent.evaluation import comparison

    def fake_run(command, **kwargs):
        if command[:2] == ["git", "rev-parse"]:
            return SimpleNamespace(returncode=0, stdout="abc1234\n")
        return SimpleNamespace(returncode=0, stdout=fake_run.status)

    monkeypatch.setattr(subprocess, "run", fake_run)
    fake_run.status = ""
    assert comparison.current_commit() == "abc1234"
    fake_run.status = " M src/code_review_agent/pipeline/multi.py\n"
    assert comparison.current_commit() == "abc1234+uncommitted"


def test_no_git_means_no_commit_not_a_crash(monkeypatch):
    import subprocess

    from code_review_agent.evaluation import comparison

    def boom(*args, **kwargs):
        raise FileNotFoundError("git")

    monkeypatch.setattr(subprocess, "run", boom)
    assert comparison.current_commit() is None
