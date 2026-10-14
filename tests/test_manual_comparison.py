"""Comparing with an advanced agent used through a chat: export the prompts, import the pasted answers, compare.

No model is called anywhere here: the answers are written by the tests, standing in for what a person pastes back.
"""

import json
from pathlib import Path

import pytest

from code_review_agent.app.cli import main
from code_review_agent.connectors.snapshot import load_example
from code_review_agent.context.builder import build_context
from code_review_agent.evaluation.comparison import load_config
from code_review_agent.evaluation.manual import (
    MANUAL_HOST,
    export_prompt,
    extract_json_object,
)

ROOT = Path(__file__).resolve().parent.parent
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


def write_answers(folder: Path, answers: dict[str, object]) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for case, content in answers.items():
        (folder / f"{case}.txt").write_text(content if isinstance(content, str) else json.dumps(content), encoding="utf-8")
    return folder


def do_import(tmp_path, name, answers, *extra, model="Test Chat 1", cases=CASES):
    folder = write_answers(tmp_path / f"answers-{name}", answers)
    code = main(["eval-import", str(folder), "--cases", cases, "--label", name, "--model", model, "--runs", str(tmp_path / name), *extra])
    return code, tmp_path / name


# -------------------------------------------------------------------- extracting the JSON


def test_a_clean_answer_is_left_alone():
    text = json.dumps(NOTHING)
    assert extract_json_object(text) == (text, False)
    fenced = "```json\n" + text + "\n```"
    assert extract_json_object(fenced) == (fenced, False)  # a fence is tolerated, and reported, by the validator


def test_prose_around_the_json_is_removed_and_counted():
    answer = 'Sure! Here is my review:\n\n{"findings": [], "limitations": ["a {brace} in a string"]}\n\nLet me know if you need more.'
    extracted, changed = extract_json_object(answer)
    assert changed and json.loads(extracted) == {"findings": [], "limitations": ["a {brace} in a string"]}


def test_a_brace_that_does_not_start_the_answer_is_skipped():
    answer = 'Note {not json} first. Then {"findings": [], "limitations": []} done.'
    extracted, changed = extract_json_object(answer)
    assert changed and json.loads(extracted) == NOTHING


def test_an_answer_with_no_json_is_left_as_it_is_so_it_is_reported_as_broken():
    for text in ("I found nothing wrong.", "{ broken json", "", "[1, 2, 3]"):
        assert extract_json_object(text) == (text, False)


# --------------------------------------------------------------------------- the export


def test_the_exported_prompt_contains_exactly_what_the_single_pass_pipeline_sends():
    ticket, review_input = load_example(ROOT / "examples" / "free-shipping-faulty")
    exported = export_prompt(ticket, review_input, 24_000)
    context = build_context(ticket, review_input, max_chars=24_000)
    assert context.system in exported and context.user in exported
    assert exported.index(context.system) < exported.index(context.user)
    assert "<<<BEGIN UNTRUSTED" in exported and "if total > 100:" in exported


def test_eval_export_writes_one_file_per_case_with_instructions(tmp_path, capsys):
    out = tmp_path / "chat"
    assert main(["eval-export", "--cases", CASES, "--out", str(out)]) == 0
    assert sorted(p.name for p in out.glob("*.txt")) == ["INSTRUCTIONS.txt", "free-shipping-faulty.txt", "free-shipping-fixed.txt"]
    assert (out / "answers").is_dir()
    assert "NEW chat for every case" in (out / "INSTRUCTIONS.txt").read_text(encoding="utf-8")
    assert "if total >= 100:" in (out / "free-shipping-fixed.txt").read_text(encoding="utf-8")
    assert "Wrote 2 prompt file(s)" in capsys.readouterr().out


def test_the_export_does_not_leak_the_expected_answers(tmp_path):
    out = tmp_path / "chat"
    assert main(["eval-export", "--cases", "free-shipping-faulty", "--out", str(out)]) == 0
    text = (out / "free-shipping-faulty.txt").read_text(encoding="utf-8")
    expected = json.loads((EXPECTED / "free-shipping-faulty.json").read_text(encoding="utf-8"))
    assert expected["expected_findings"][0]["description"] not in text


def test_the_held_out_split_still_needs_confirmation_for_export(tmp_path, capsys):
    assert main(["eval-export", "--split", "heldout", "--out", str(tmp_path / "x")]) == 1
    assert "--confirm-frozen" in capsys.readouterr().err
    assert not (tmp_path / "x").exists()


# --------------------------------------------------------------------------- the import


def test_imported_answers_become_a_scored_evaluation_folder(tmp_path, capsys):
    code, folder = do_import(tmp_path, "chat-a", {"free-shipping-faulty": FINDING, "free-shipping-fixed": NOTHING}, model="Test Chat 1 (2026-10-15)")
    assert code == 0
    config = load_config(folder)
    assert (config.label, config.pipeline, config.model, config.host) == ("chat-a", "single", "Test Chat 1 (2026-10-15)", MANUAL_HOST)
    assert (config.tools, config.context, config.verify) == ([], False, False)
    assert len(config.runs) == 2 and all((folder / e.folder / "result.json").exists() for e in config.runs)
    assert any("outside the tool" in n for n in config.notes)
    capsys.readouterr()
    assert main(["eval-compare", str(folder), "--expected", str(EXPECTED)]) == 0
    text = capsys.readouterr().out
    assert "| chat-a |" in text and "Test Chat 1 (2026-10-15)" in text and "outside the tool" in text
    assert "| 2 (0) | 1 | 0 | 0 | 1.00 | 1.00 | 1.00 |" in text  # one defect found, no false alarm on the correct case


def test_a_chat_configuration_sits_next_to_an_open_model_configuration(tmp_path, capsys):
    from test_comparison import (
        run_eval,  # the open-model side: the fake model server of the other tests
    )

    open_model = run_eval(tmp_path, "open", NOTHING, "--pipeline", "single", "--label", "open-single")
    _, chat = do_import(tmp_path, "chat-a", {"free-shipping-faulty": FINDING, "free-shipping-fixed": NOTHING})
    capsys.readouterr()
    assert main(["eval-compare", str(open_model), str(chat), "--expected", str(EXPECTED)]) == 0
    text = capsys.readouterr().out
    assert "| open-single |" in text and "| chat-a |" in text
    assert "Configurations differ in:" in text and "model" in text.split("Configurations differ in:")[1].split("\n")[0]
    per_case = text.split("## Per case")[1]
    assert "| free-shipping-faulty | 1 | 0/1 found, 0 FP | 1/1 found, 0 FP |" in per_case


def test_prose_around_the_json_is_a_failure_unless_lenient_and_is_then_counted(tmp_path, capsys):
    chatty = "Here is my review:\n" + json.dumps(FINDING) + "\nHope this helps!"
    code, strict = do_import(tmp_path, "strict", {"free-shipping-faulty": chatty, "free-shipping-fixed": NOTHING})
    assert code == 0
    assert [e.status for e in load_config(strict).runs] == ["failed", "completed"]
    code, lenient = do_import(tmp_path, "lenient", {"free-shipping-faulty": chatty, "free-shipping-fixed": NOTHING}, "--lenient")
    assert code == 0
    config = load_config(lenient)
    assert [e.status for e in config.runs] == ["completed", "completed"]
    assert any("1 of 2 answer(s) had text around the JSON" in n for n in config.notes)
    capsys.readouterr()
    assert main(["eval-compare", str(strict), str(lenient), "--expected", str(EXPECTED)]) == 0
    text = capsys.readouterr().out
    assert "had text around the JSON, which was removed" in text  # the repair is visible in the comparison


def test_missing_and_unexpected_answer_files_are_reported(tmp_path, capsys):
    code, folder = do_import(tmp_path, "partial", {"free-shipping-faulty": FINDING, "something-else": NOTHING})
    assert code == 0
    err = capsys.readouterr()
    assert "something-else is not one of the selected cases" in err.err
    assert any("No answer for: free-shipping-fixed" in n for n in load_config(folder).notes)
    assert len(load_config(folder).runs) == 1


def test_import_errors_are_actionable(tmp_path, capsys):
    folder = write_answers(tmp_path / "a", {"free-shipping-faulty": FINDING})
    assert main(["eval-import", str(folder), "--cases", CASES, "--label", "x", "--model", "(none: a file)"]) == 1
    assert "exact model name" in capsys.readouterr().err
    empty = tmp_path / "empty"
    empty.mkdir()
    assert main(["eval-import", str(empty), "--cases", CASES, "--label", "x", "--model", "M"]) == 1
    assert "No answer file matched a case" in capsys.readouterr().err
    assert main(["eval-import", str(tmp_path / "nowhere"), "--cases", CASES, "--label", "x", "--model", "M"]) == 1
    assert "Cannot import" in capsys.readouterr().err


def test_a_pasted_answer_is_validated_like_any_other(tmp_path):
    invented = dict(FINDING)
    invented["findings"] = [{**FINDING["findings"][0], "file": "shop/does_not_exist.py"}]
    code, folder = do_import(tmp_path, "inv", {"free-shipping-faulty": invented, "free-shipping-fixed": NOTHING})
    assert code == 0
    run = next(e for e in load_config(folder).runs if e.case_id == "free-shipping-faulty")
    result = json.loads((folder / run.folder / "result.json").read_text(encoding="utf-8"))
    assert any(p["kind"] == "unknown_file" for p in result["problems"])  # an invented file is flagged, never accepted silently
    assert result["run"]["model"] == "Test Chat 1" and result["run"]["host"] == MANUAL_HOST


@pytest.mark.parametrize("name", ["answers.json", "answers.md"])
def test_other_answer_file_extensions_are_accepted(tmp_path, name):
    folder = tmp_path / "ext"
    folder.mkdir()
    (folder / f"free-shipping-faulty{Path(name).suffix}").write_text(json.dumps(FINDING), encoding="utf-8")
    assert main(["eval-import", str(folder), "--cases", "free-shipping-faulty", "--label", "ext", "--model", "M", "--runs", str(tmp_path / "o")]) == 0
