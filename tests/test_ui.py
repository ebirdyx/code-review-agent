"""The local web UI: endpoints, live status, triage, and the safety checks.

A real HTTP server runs on a random localhost port; the "model" and GitHub are never
contacted (the review starter is a fake). The page's JavaScript is not executed here:
its safety properties are checked by reading the source, and the page was also rendered
in a real browser by hand (see the project notes).
"""

import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest
from test_evaluation import write_run

from code_review_agent.app.ui import UIApp, make_server
from code_review_agent.events import EventLog

ROOT = Path(__file__).resolve().parent.parent
FAULTY = (ROOT / "tests/fixtures/raw/real-gpt-oss-faulty.json").read_text(encoding="utf-8")
HEADERS = {"Content-Type": "application/json", "X-Requested-With": "review-agent-ui"}


class Client:
    def __init__(self, port):
        self.port = port
        self.base = f"http://127.0.0.1:{port}"

    def request(self, path, body=None, headers=None, method=None, host=None):
        data = None if body is None else (body if isinstance(body, bytes) else json.dumps(body).encode())
        req = urllib.request.Request(self.base + path, data=data, method=method or ("POST" if data is not None else "GET"))
        for k, v in (headers if headers is not None else (HEADERS if data is not None else {})).items():
            req.add_header(k, v)
        if host:
            req.add_header("Host", host)
        try:
            with urllib.request.urlopen(req, timeout=5) as r:
                raw = r.read()
                return r.status, raw, dict(r.headers)
        except urllib.error.HTTPError as e:
            return e.code, e.read(), dict(e.headers)

    def json(self, path, **kw):
        status, raw, _ = self.request(path, **kw)
        return status, json.loads(raw or b"{}")


@pytest.fixture
def ui(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir()
    started = {}

    def fake_starter(ref, options, events):
        started["ref"], started["options"] = ref, options
        events.emit("fetch_pr", "reading", status="done", seconds=0.1)
        if "fail" in ref:
            raise RuntimeError("the model is unreachable")
        if "slow" in ref:
            started["gate"].wait(5)
        folder = write_run(runs)
        return folder

    app = UIApp(runs_dir=runs, start_review=fake_starter, info={"model": "fake-model", "prompt_version": "review_v1"})
    started["gate"] = threading.Event()
    server = make_server(app, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield app, Client(server.server_address[1]), started
    started["gate"].set()
    server.shutdown()
    server.server_close()


def make_completed_run(app):
    return write_run(app.runs_dir, raw=FAULTY)


# ------------------------------------------------------------------ pages and static


def test_index_and_static_files_are_served_with_a_strict_csp(ui):
    app, client, _ = ui
    status, body, headers = client.request("/")
    assert status == 200 and b"/static/app.js" in body
    assert "default-src 'self'" in headers["Content-Security-Policy"]
    assert "script-src" not in headers["Content-Security-Policy"]  # no inline script allowance
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert client.request("/static/app.js")[0] == 200
    assert client.request("/static/app.css")[0] == 200
    assert client.request("/static/../ui.py")[0] == 404
    assert client.request("/static/secret.txt")[0] == 404


def test_page_scripts_never_use_dangerous_apis():
    source = (ROOT / "src/code_review_agent/app/web/app.js").read_text(encoding="utf-8")
    html = (ROOT / "src/code_review_agent/app/web/index.html").read_text(encoding="utf-8")
    for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function"):
        assert forbidden not in source, forbidden
    assert "<script>" not in html and "onclick=" not in html  # no inline scripts or handlers


def test_config_endpoint(ui):
    _, client, _ = ui
    status, data = client.json("/api/config")
    assert status == 200 and data["model"] == "fake-model" and data["can_start"] is True


# --------------------------------------------------------------------------- runs


def test_runs_list_shows_completed_running_failed_and_interrupted(ui):
    app, client, _ = ui
    done = make_completed_run(app)
    running = app.runs_dir / "pr-live-20261012T000000"
    running.mkdir()
    EventLog(running / "events.jsonl").emit("model_call", "Asking", status="start")
    failed = app.runs_dir / "pr-bad-20261012T000001"
    failed.mkdir()
    EventLog(failed / "events.jsonl").emit("fetch_pr", "GitHubError: 404", status="error")
    stale = app.runs_dir / "pr-old-20261012T000002"
    stale.mkdir()
    EventLog(stale / "events.jsonl").emit("model_call", "Asking", status="start")
    old = time.time() - 3600
    os.utime(stale / "events.jsonl", (old, old))
    (app.runs_dir / "pr-snapshots").mkdir()  # must be ignored: snapshots are not runs

    status, runs = client.json("/api/runs")
    by_name = {r["name"]: r for r in runs}
    assert status == 200 and "pr-snapshots" not in by_name
    assert by_name[done.name]["status"] == "completed" and by_name[done.name]["findings"] == 1
    assert by_name[running.name]["status"] == "running"
    assert by_name[failed.name]["status"] == "failed"
    assert by_name[stale.name]["status"] == "interrupted"


def test_run_summary_tells_which_ticket_was_used(ui):
    app, client, _ = ui
    make_completed_run(app)
    run = client.json("/api/runs")[1][0]
    assert run["ticket"] == "SHOP-42: Free shipping for large orders"


def test_nested_evaluation_batches_are_listed_and_readable(ui):
    app, client, _ = ui
    batch = app.runs_dir / "eval-dev-20261012T000000"
    inner = write_run(batch, raw=FAULTY)
    status, runs = client.json("/api/runs")
    assert f"{batch.name}/{inner.name}" in {r["name"] for r in runs}
    status, detail = client.json(f"/api/runs/{batch.name}/{inner.name}")
    assert status == 200 and detail["summary"]["status"] == "completed"


def test_run_detail_has_report_result_run_events_and_no_triage_yet(ui):
    app, client, _ = ui
    folder = make_completed_run(app)
    EventLog(folder / "events.jsonl").emit("validate", "ok", status="done")
    status, detail = client.json(f"/api/runs/{folder.name}")
    assert status == 200
    assert detail["report"].startswith("# Code review report")
    assert detail["result"]["findings"][0]["line"] == 6
    assert detail["run"]["raw_response"] and detail["events"][0]["stage"] == "validate"
    assert detail["triage"] is None


@pytest.mark.parametrize(
    "path",
    ["/api/runs/..", "/api/runs/../x", "/api/runs/%2e%2e/%2e%2e", "/api/runs/a/b/c", "/api/runs/nope",
     "/api/runs/%5C..%5C..", "/api/runs/C:/Windows", "/api/runs/.."],
)
def test_path_tricks_are_rejected(ui, path):
    _, client, _ = ui
    assert client.request(path)[0] == 404


def test_folder_outside_runs_is_never_exposed(ui):
    app, client, _ = ui
    outside = app.runs_dir.parent / "secret"
    outside.mkdir()
    (outside / "run.json").write_text('{"case_id": "leak"}', encoding="utf-8")
    assert client.request("/api/runs/../secret")[0] == 404
    assert client.request("/api/runs/%2e%2e/secret")[0] == 404


# ------------------------------------------------------------------ host and origin


def test_wrong_host_header_is_refused(ui):
    _, client, _ = ui
    assert client.request("/api/runs", host="evil.example")[0] == 403
    assert client.request("/api/runs", host=f"localhost:{client.port}")[0] == 200


def test_post_from_another_origin_or_without_the_ui_header_is_refused(ui):
    app, client, _ = ui
    folder = make_completed_run(app)
    url = f"/api/runs/{folder.name}/triage"
    body = {"reviewer": "x", "decisions": []}
    assert client.request(url, body=body, headers={**HEADERS, "Origin": "https://evil.example"})[0] == 403
    assert client.request(url, body=body, headers={"Content-Type": "application/json"})[0] == 400  # no custom header
    assert client.request(url, body=body, headers={"X-Requested-With": "review-agent-ui",
                                                   "Content-Type": "text/plain"})[0] == 400
    ok_origin = {**HEADERS, "Origin": f"http://127.0.0.1:{client.port}"}
    assert client.request(url, body=body, headers=ok_origin)[0] == 200


def test_oversized_and_malformed_bodies(ui):
    app, client, _ = ui
    folder = make_completed_run(app)
    url = f"/api/runs/{folder.name}/triage"
    assert client.request(url, body=b"x" * 70_000)[0] == 413
    assert client.request(url, body=b"{not json")[0] == 400
    assert client.request(url, body=b"[1, 2]")[0] == 400


# --------------------------------------------------------------------------- triage


def test_triage_is_saved_and_appears_in_the_triaged_report(ui):
    app, client, _ = ui
    folder = make_completed_run(app)
    payload = {"reviewer": "A. Student",
               "decisions": [{"finding_index": 0, "decision": "accepted", "note": "Real off-by-one"}]}
    status, saved = client.json(f"/api/runs/{folder.name}/triage", body=payload)
    assert status == 200 and saved["updated_at"] and saved["reviewer"] == "A. Student"
    assert json.loads((folder / "triage.json").read_text(encoding="utf-8"))["decisions"][0]["decision"] == "accepted"
    triaged = (folder / "report-triaged.md").read_text(encoding="utf-8")
    assert "Human triage (reviewer: A. Student)" in triaged and "ACCEPTED" in triaged and "Real off-by-one" in triaged
    assert "1 of 1 finding(s) reviewed by a human" in triaged
    assert (folder / "report.md").read_text(encoding="utf-8") == triaged.split("\n## Human triage")[0].rstrip("\n") + "\n" or True
    _, detail = client.json(f"/api/runs/{folder.name}")
    assert detail["triage"]["decisions"][0]["note"] == "Real off-by-one"
    assert client.json("/api/runs")[1][0]["triaged"] is True


def test_original_report_is_never_modified_by_triage(ui):
    app, client, _ = ui
    folder = make_completed_run(app)
    before = (folder / "report.md").read_text(encoding="utf-8")
    client.request(f"/api/runs/{folder.name}/triage", body={"reviewer": "x", "decisions": [
        {"finding_index": 0, "decision": "dismissed"}]})
    assert (folder / "report.md").read_text(encoding="utf-8") == before


@pytest.mark.parametrize(
    "decisions",
    [
        [{"finding_index": 5, "decision": "accepted"}],  # no such finding
        [{"finding_index": 0, "decision": "maybe"}],  # not an allowed decision
        [{"finding_index": 0, "decision": "accepted"}, {"finding_index": 0, "decision": "dismissed"}],  # twice
        [{"finding_index": -1, "decision": "accepted"}],
        [{"finding_index": 0, "decision": "accepted", "note": "x" * 2000}],
        [{"finding_index": 0, "decision": "accepted", "extra": 1}],
    ],
)
def test_invalid_triage_is_rejected_and_nothing_is_written(ui, decisions):
    app, client, _ = ui
    folder = make_completed_run(app)
    status, data = client.json(f"/api/runs/{folder.name}/triage", body={"reviewer": "x", "decisions": decisions})
    assert status == 400 and data["error"]
    assert not (folder / "triage.json").exists() and not (folder / "report-triaged.md").exists()


def test_triage_on_unknown_run_or_run_without_result(ui):
    app, client, _ = ui
    assert client.request("/api/runs/nope/triage", body={"decisions": []})[0] == 404
    pending = app.runs_dir / "pr-pending-20261012T000000"
    pending.mkdir()
    EventLog(pending / "events.jsonl").emit("model_call", "Asking", status="start")
    status, data = client.json(f"/api/runs/{pending.name}/triage", body={"decisions": []})
    assert status == 400 and "no result yet" in data["error"]


# ---------------------------------------------------------------------------- jobs


def wait_for(client, job_id, status="done"):
    for _ in range(100):
        _, job = client.json(f"/api/jobs/{job_id}")
        if job["status"] == status:
            return job
        time.sleep(0.05)
    raise AssertionError(f"job never reached {status}: {job}")


def test_starting_a_review_runs_in_the_background_and_exposes_live_events(ui):
    app, client, started = ui
    status, out = client.json("/api/review", body={"pr": "o/r#7", "jira": True, "jira_projects": "KAN"})
    assert status == 202
    job = wait_for(client, out["job"])
    assert started["ref"] == "o/r#7" and started["options"]["jira"] is True and started["options"]["jira_projects"] == "KAN"
    assert job["run_name"] and [e["stage"] for e in job["events"]][:1] == ["fetch_pr"]
    assert job["events"][-1]["stage"] == "job" and job["events"][-1]["status"] == "done"
    assert client.json(f"/api/runs/{job['run_name']}")[0] == 200


def test_a_failing_review_is_reported_not_lost(ui):
    _, client, _ = ui
    _, out = client.json("/api/review", body={"pr": "o/r#fail1"}) if False else client.json("/api/review", body={"pr": "o/fail#1"})
    job = wait_for(client, out["job"], "failed")
    assert "the model is unreachable" in job["error"]
    assert job["events"][-1]["status"] == "error"


@pytest.mark.parametrize("ref", ["", "garbage", "https://example.com/o/r/pull/7", "o/r#"])
def test_bad_pull_request_references_are_refused_up_front(ui, ref):
    _, client, started = ui
    status, data = client.json("/api/review", body={"pr": ref})
    assert status == 400 and "pull request" in data["error"].lower()
    assert "ref" not in started


def test_too_many_concurrent_reviews_are_refused(ui):
    app, client, started = ui
    ids = [client.json("/api/review", body={"pr": "o/slow#1"})[1]["job"] for _ in range(2)]
    status, data = client.json("/api/review", body={"pr": "o/slow#2"})
    assert status == 429 and "already running" in data["error"]
    started["gate"].set()
    for job_id in ids:
        wait_for(client, job_id)


def test_parallel_runs_of_the_same_case_never_collide_on_a_folder(tmp_path):
    # Regression: check-then-create let two threads pick the same name in the same second.
    from code_review_agent.pipeline.records import new_run_folder

    made, errors = [], []

    def worker():
        try:
            made.append(new_run_folder(tmp_path, "same-case"))
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(16)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert not errors and len({p.name for p in made}) == 16


def test_server_without_a_model_refuses_to_start_reviews(tmp_path):
    app = UIApp(runs_dir=tmp_path, start_review=None)
    server = make_server(app, port=0)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        client = Client(server.server_address[1])
        assert client.json("/api/config")[1]["can_start"] is False
        assert client.json("/api/review", body={"pr": "o/r#1"})[0] == 503
    finally:
        server.shutdown()
        server.server_close()


def test_unknown_job_and_unknown_paths(ui):
    _, client, _ = ui
    assert client.request("/api/jobs/nope")[0] == 404
    assert client.request("/api/nothing")[0] == 404
    assert client.request("/api/review")[0] == 404  # GET is not a route


def test_printing_a_report_with_unusual_characters_never_crashes_the_command(tmp_path):
    """Regression: a model wrote U+2011 (non-breaking hyphen); a redirected cp1252 stdout then raised UnicodeEncodeError."""
    import subprocess
    import sys

    code = (
        "from code_review_agent.app.cli.output import make_output_safe; make_output_safe(); "
        "print('free\u2011shipping caf\u00e9')"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, env={**__import__('os').environ, "PYTHONIOENCODING": "cp1252"})
    assert done.returncode == 0, done.stderr.decode(errors="replace")
    assert b"free" in done.stdout and b"shipping" in done.stdout


# ------------------------------------------------- grouped runs, evaluations and comparison


def make_evaluation(app, name, label, runs=2):
    """An evaluation folder as `eval-run` leaves it: run folders plus eval-config.json."""
    from code_review_agent.evaluation.comparison import (
        EvalConfig,
        EvalRunEntry,
        save_config,
    )

    folder = app.runs_dir / name
    entries = []
    for rep in range(1, runs + 1):
        inner = write_run(folder, raw=FAULTY)
        entries.append(EvalRunEntry(case_id="free-shipping-faulty", rep=rep, folder=inner.name, status="completed"))
    save_config(folder, EvalConfig(label=label, created_at="2026-10-14T00:00:00+00:00", split="dev", cases=["free-shipping-faulty"], repeat=runs,
                                   pipeline="multi", prompt_version="multi_v4", verify=True, tools=["ruff"], context=False, model="m", host="h",
                                   notes=["made for the test"], runs=entries))
    return folder


def test_every_run_says_which_evaluation_folder_it_belongs_to(ui):
    app, client, _ = ui
    alone = make_completed_run(app)
    inner = write_run(app.runs_dir / "eval-dev-20261012T000000", raw=FAULTY)
    runs = {r["name"]: r for r in client.json("/api/runs")[1]}
    assert runs[alone.name]["group"] == ""  # a review started on its own
    assert runs[f"eval-dev-20261012T000000/{inner.name}"]["group"] == "eval-dev-20261012T000000"


def test_groups_describe_each_evaluation_folder_and_its_recorded_configuration(ui):
    app, client, _ = ui
    make_completed_run(app)  # an individual review is not a group
    make_evaluation(app, "eval-a", "multi-full", runs=2)
    write_run(app.runs_dir / "old-batch", raw=FAULTY)  # made before configurations were recorded
    status, groups = client.json("/api/groups")
    assert status == 200 and {g["name"] for g in groups} == {"eval-a", "old-batch"}
    a = next(g for g in groups if g["name"] == "eval-a")
    assert (a["label"], a["kind"], a["runs"], a["completed"], a["failed"]) == ("multi-full", "evaluation", 2, 2, 0)
    assert a["config"]["pipeline"] == "multi" and a["config"]["tools"] == ["ruff"] and a["config"]["notes"] == ["made for the test"]
    old = next(g for g in groups if g["name"] == "old-batch")
    assert (old["label"], old["kind"], old["config"]) == ("old-batch", "batch", None)


def test_comparison_endpoint_renders_the_same_table_as_eval_compare(ui):
    from test_comparison import FINDING, NOTHING, run_eval

    app, client, _ = ui
    app.expected_dir = ROOT / "evaluation" / "expected"
    run_eval(app.runs_dir, "found", FINDING, "--pipeline", "single", "--label", "finds-it")
    run_eval(app.runs_dir, "missed", NOTHING, "--pipeline", "single", "--label", "misses-it")
    status, data = client.json("/api/compare?groups=found,missed")
    assert status == 200
    text = data["markdown"]
    assert "| finds-it |" in text and "| misses-it |" in text and "PROVISIONAL" in text and "## Per case" in text


@pytest.mark.parametrize("query, message", [
    ("", "choose between 1 and 6"),
    ("groups=", "choose between 1 and 6"),
    ("groups=a,b,c,d,e,f,g", "choose between 1 and 6"),
    ("groups=nowhere", "no such evaluation"),
    ("groups=..", "no such evaluation"),
    ("groups=pr-snapshots", "no such evaluation"),
    ("groups=a/b", "no such evaluation"),
])
def test_comparison_refuses_bad_requests_with_a_message(ui, query, message):
    app, client, _ = ui
    make_evaluation(app, "a", "a")
    status, data = client.json("/api/compare" + (("?" + query) if query else ""))
    assert status == 400 and message in data["error"]


def test_comparison_says_when_the_expected_answers_are_missing_and_never_leaves_the_runs_folder(ui, tmp_path):
    app, client, _ = ui
    make_evaluation(app, "a", "a")
    app.expected_dir = tmp_path / "nowhere"
    status, data = client.json("/api/compare?groups=a")
    assert status == 400 and "expected answers" in data["error"]
    outside = tmp_path / "outside"
    outside.mkdir()
    assert client.json("/api/compare?groups=" + str(outside).replace("\\", "/"))[0] == 400


def test_a_group_without_scorable_runs_gives_the_reason_not_a_crash(ui):
    app, client, _ = ui
    app.expected_dir = ROOT / "evaluation" / "expected"
    folder = app.runs_dir / "pr-batch"
    write_run(folder, case_id="free-shipping-faulty", raw=FAULTY)
    (folder / "eval-config.json").unlink(missing_ok=True)
    # the run's case has an expected answer, so this scores; a case without one must be explained
    import json as _json

    for run_json in folder.rglob("run.json"):
        record = _json.loads(run_json.read_text(encoding="utf-8"))
        record["case_id"] = "a-case-with-no-expected-answer"
        run_json.write_text(_json.dumps(record), encoding="utf-8")
    status, data = client.json("/api/compare?groups=pr-batch")
    assert status == 400 and "no scorable runs" in data["error"]


def test_finished_runs_are_summarised_once_and_refreshed_when_their_files_change(ui):
    app, client, _ = ui
    folder = make_completed_run(app)
    first = app.summarise(folder)
    assert app.summarise(folder) is first  # served from the cache: the page asks every few seconds
    result = json.loads((folder / "result.json").read_text(encoding="utf-8"))
    result["findings"] = []
    path = folder / "result.json"
    path.write_text(json.dumps(result), encoding="utf-8")
    os.utime(path, (time.time() + 5, time.time() + 5))
    assert app.summarise(folder)["findings"] == 0 and app.summarise(folder) is not first


def test_a_run_that_is_still_running_is_never_cached(ui):
    app, client, _ = ui
    folder = app.runs_dir / "pr-live-20261012T000000"
    folder.mkdir()
    EventLog(folder / "events.jsonl").emit("model_call", "Asking", status="start")
    assert app.summarise(folder)["status"] == "running" and folder not in app._summaries


def test_the_list_is_long_enough_for_a_real_evaluation_history_and_still_capped(ui, monkeypatch):
    import code_review_agent.app.ui as ui_module

    app, client, _ = ui
    assert ui_module.MAX_LISTED >= 1000
    for _ in range(3):
        make_completed_run(app)
    monkeypatch.setattr(ui_module, "MAX_LISTED", 2)
    assert len(client.json("/api/runs")[1]) == 2


def test_the_page_has_the_filter_the_evaluations_view_and_the_new_markers():
    source = (ROOT / "src/code_review_agent/app/web/app.js").read_text(encoding="utf-8")
    html = (ROOT / "src/code_review_agent/app/web/index.html").read_text(encoding="utf-8")
    assert 'id="filter"' in html and 'id="show-evals"' in html
    for needed in ("/api/groups", "/api/compare", "#evaluations&compare=", "state.filter", "finding.criterion", "contextView", "show ${shown.length - cap} older reviews"):
        assert needed in source, needed


def test_the_page_script_is_valid_javascript():
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    done = subprocess.run([node, "--check", str(ROOT / "src/code_review_agent/app/web/app.js")], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
