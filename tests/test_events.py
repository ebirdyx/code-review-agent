"""Progress events: recorded, saved, safe, and visible while a review runs."""

import json
import threading

import pytest

from code_review_agent.events import EventLog, echo_to_stderr, read_events


def test_step_emits_start_then_done_with_duration_and_result_data():
    log = EventLog()
    with log.step("build_context", "Assembling", ticket="KAN-4") as info:
        info["characters"] = 1234
    start, done = log.events
    assert (start.status, done.status) == ("start", "done")
    assert done.seconds is not None and done.data == {"ticket": "KAN-4", "characters": 1234}


def test_step_records_the_error_and_reraises():
    log = EventLog()
    with pytest.raises(ValueError, match="boom"):
        with log.step("fetch_pr", "Reading"):
            raise ValueError("boom")
    assert [e.status for e in log.events] == ["start", "error"]
    assert "ValueError: boom" in log.events[-1].message


def test_data_keys_named_like_parameters_cannot_break_logging():
    # Regression: a data field called "status" used to crash the pipeline.
    log = EventLog()
    with log.step("validate", "Checking") as info:
        info.update(status="completed", stage="x", message="y", seconds=1)
    assert log.events[-1].status == "done"
    assert log.events[-1].data["status"] == "completed"


def test_events_are_saved_as_json_lines_and_buffered_events_are_flushed_on_attach(tmp_path):
    log = EventLog()
    log.emit("fetch_pr", "before the folder existed")
    path = tmp_path / "run" / "events.jsonl"
    log.attach(path)
    log.emit("model_call", "after")
    lines = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert [e["message"] for e in lines] == ["before the folder existed", "after"]
    assert read_events(path) == lines


def test_reading_a_half_written_file_and_a_missing_file():
    assert read_events(__import__("pathlib").Path("does-not-exist.jsonl")) == []


def test_half_written_last_line_is_ignored(tmp_path):
    path = tmp_path / "e.jsonl"
    path.write_text('{"stage": "a", "status": "done"}\n{"stage": "b", "sta', encoding="utf-8")
    assert [e["stage"] for e in read_events(path)] == ["a"]


def test_long_messages_are_shortened_and_whitespace_collapsed():
    log = EventLog()
    log.emit("x", "a\n  b " + "z" * 1000)
    assert len(log.events[0].message) <= 300 and "\n" not in log.events[0].message


def test_concurrent_writers_do_not_corrupt_the_file(tmp_path):
    log = EventLog(tmp_path / "e.jsonl")
    threads = [threading.Thread(target=lambda i=i: [log.emit("t", f"{i}-{n}") for n in range(50)]) for i in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(read_events(tmp_path / "e.jsonl")) == 400


def test_terminal_echo_shows_model_start_but_hides_other_starts(capsys):
    log = EventLog(echo=echo_to_stderr)
    log.emit("fetch_pr", "reading", status="start")
    log.emit("model_call", "Asking gpt-oss", status="start")
    log.emit("model_call", "gpt-oss answered", status="done", seconds=1.6)
    err = capsys.readouterr().err
    assert "reading" not in err
    assert "Asking gpt-oss" in err and "gpt-oss answered" in err and "(1.6s)" in err
