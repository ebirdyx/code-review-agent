"""A small local web UI: see what the agent is doing, read reports, record decisions.

Standard library only. It listens on the loopback address and nothing else, serves static
files from the package, and exposes a few JSON endpoints over the run folders:

  GET  /api/config                 which model / prompt this server will use
  GET  /api/runs                   list of runs (live status for running ones), each with its evaluation `group`
  GET  /api/groups                 the evaluation folders: runs, outcome, recorded configuration
  GET  /api/compare?groups=a,b     the side-by-side comparison of evaluation folders (same as `eval-compare`)
  GET  /api/stats?scope=all        what the runs found, in numbers (scope: all | reviews | evaluations)
  GET  /api/runs/<name>            report, result, run record, events, triage of one run
  POST /api/runs/<name>/triage     save accept/dismiss decisions for the findings
  POST /api/review                 start a review of a pull request in the background
  GET  /api/jobs/<id>              live events of a review started from the UI

Safety: loopback only; Host and Origin checks (against DNS rebinding and other web pages
calling localhost); POSTs need a JSON body and a custom header; run names are validated
against path tricks; no inline scripts (a strict Content-Security-Policy); the page never
puts model or ticket text into HTML (it builds DOM text nodes).
"""

from __future__ import annotations

import json
import re
import threading
import time
import uuid
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from pydantic import ValidationError

from ..connectors.github import GitHubError, parse_pr_reference
from ..evaluation.comparison import CONFIG_NAME, compare
from ..evaluation.scoring import EvaluationError, totals
from ..events import EventLog, read_events
from ..reporting.report import render_triage_section
from ..schemas import ReviewResult, TriageFile

SEGMENT = re.compile(r"^[\w.-]{1,200}$")
MAX_BODY = 64 * 1024
MAX_RUNNING_JOBS = 2
MAX_LISTED = 1000  # runs returned by /api/runs (the page groups and filters them)
MAX_COMPARED = 6  # evaluation folders in one comparison
SCOPES = ("all", "reviews", "evaluations")  # which runs the overview counts
SEVERITY_ORDER = ("critical", "high", "medium", "low")
CONFIG_FIELDS = ("pipeline", "prompt_version", "passes", "model", "tools", "context", "verify", "repeat", "split", "agent_commit", "notes")
RUNNING_FRESH_SECONDS = 600  # a run with no result and no activity for this long is "interrupted"
STATIC = {"app.js": "text/javascript; charset=utf-8", "app.css": "text/css; charset=utf-8"}
CSP = "default-src 'self'; img-src 'self' data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"

# (pr reference, options, events) -> run folder. Supplied by the CLI; tests pass a fake.
ReviewStarter = Callable[[str, dict, EventLog], Path]


@dataclass
class Job:
    id: str
    ref: str
    events: EventLog
    status: str = "running"  # running | done | failed
    run_name: str | None = None
    error: str | None = None


@dataclass
class UIApp:
    runs_dir: Path
    start_review: ReviewStarter | None = None
    info: dict = field(default_factory=dict)  # shown in the page header (model, prompt, ...)
    jobs: dict[str, Job] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)
    expected_dir: Path = Path("evaluation/expected")  # expected answers, needed to score a comparison
    _summaries: dict = field(default_factory=dict)  # finished runs only: folder -> (file signature, summary)
    _stats: dict = field(default_factory=dict)  # finished runs only: folder -> (file signature, what its findings were)

    # ------------------------------------------------------------------ runs

    def resolve_run(self, rel: str) -> Path | None:
        parts = rel.split("/")
        if not 1 <= len(parts) <= 2 or not all(SEGMENT.match(p) and p not in (".", "..") for p in parts):
            return None
        path = self.runs_dir.joinpath(*parts)
        try:
            inside = path.resolve().is_relative_to(self.runs_dir.resolve())
        except OSError:
            return None
        if not inside or not path.is_dir():
            return None
        if not ((path / "run.json").exists() or (path / "events.jsonl").exists()):
            return None
        return path

    def run_folders(self) -> list[Path]:
        if not self.runs_dir.is_dir():
            return []
        found = []
        for child in self.runs_dir.iterdir():
            if not child.is_dir() or child.name == "pr-snapshots":
                continue
            if (child / "run.json").exists() or (child / "events.jsonl").exists():
                found.append(child)
            else:  # evaluation batches hold runs one level deeper
                found += [g for g in child.iterdir() if g.is_dir() and ((g / "run.json").exists() or (g / "events.jsonl").exists())]
        return found

    def rel(self, folder: Path) -> str:
        return folder.relative_to(self.runs_dir).as_posix()

    def summarise(self, folder: Path) -> dict:
        signature = _signature(folder)
        cached = self._summaries.get(folder)
        if cached and cached[0] == signature:  # the page asks every few seconds: do not re-read finished runs
            return cached[1]
        summary = self._summarise(folder)
        if summary["status"] in ("completed", "failed") and (folder / "result.json").exists():
            self._summaries[folder] = (signature, summary)
        return summary

    def _summarise(self, folder: Path) -> dict:
        run = _read_json(folder / "run.json") or {}
        result = _read_json(folder / "result.json")
        events = read_events(folder / "events.jsonl")
        if result is not None:
            status = result.get("status", "unknown")
        elif events and events[-1].get("status") == "error":
            status = "failed"
        elif events or (folder / "events.jsonl").exists():
            fresh = time.time() - (folder / "events.jsonl").stat().st_mtime < RUNNING_FRESH_SECONDS
            status = "running" if fresh else "interrupted"
        else:
            status = "incomplete"
        revision = run.get("revision") or ((result or {}).get("run") or {}).get("revision")
        settings = run.get("settings") or {}
        name = self.rel(folder)
        return {
            "name": name,
            "group": name.split("/")[0] if "/" in name else "",  # the evaluation folder, or "" for an individual review
            "case_id": run.get("case_id") or folder.name,
            "created_at": run.get("created_at") or (events[0]["ts"] if events else ""),
            "status": status,
            "model": settings.get("model", ""),
            "prompt_version": run.get("prompt_version", ""),
            "findings": len(result.get("findings", [])) if result else None,
            "problems": len(result.get("problems", [])) if result else None,
            "head_sha": (revision or {}).get("head_sha", "")[:7] if revision else "",
            "duration_s": run.get("duration_s"),
            "pipeline": run.get("pipeline") or (result or {}).get("pipeline") or "single",
            "ticket": ((result or {}).get("run") or {}).get("ticket"),
            "dismissed": len(result.get("dismissed", [])) if result else None,
            "triaged": (folder / "triage.json").exists(),
        }

    def list_runs(self) -> list[dict]:
        runs = [self.summarise(f) for f in self.run_folders()]
        return sorted(runs, key=lambda r: r["created_at"], reverse=True)[:MAX_LISTED]

    def groups(self) -> list[dict]:
        """The evaluation folders (runs one level deeper than the runs folder): outcome and recorded configuration."""
        by_group: dict[str, list[dict]] = {}
        for run in self.list_runs():
            if run["group"]:
                by_group.setdefault(run["group"], []).append(run)
        out = []
        for name, runs in by_group.items():
            config = _read_json(self.runs_dir / name / CONFIG_NAME)
            out.append({
                "name": name,
                "label": (config or {}).get("label") or name,
                "kind": "evaluation" if config else "batch",  # a batch has no recorded configuration (made before eval-run did)
                "runs": len(runs),
                "latest": max(r["created_at"] for r in runs),
                "completed": sum(r["status"] == "completed" for r in runs),
                "failed": sum(r["status"] == "failed" for r in runs),
                "findings": sum(r["findings"] or 0 for r in runs),
                "config": {k: config.get(k) for k in CONFIG_FIELDS} if config else None,
            })
        return sorted(out, key=lambda g: g["latest"], reverse=True)

    def resolve_group(self, name: str) -> Path | None:
        if not SEGMENT.match(name) or name in (".", "..", "pr-snapshots"):
            return None
        path = self.runs_dir / name
        try:
            inside = path.resolve().is_relative_to(self.runs_dir.resolve())
        except OSError:
            return None
        return path if inside and path.is_dir() else None

    def compare_groups(self, names: list[str]) -> tuple[str, list[dict]]:
        """The comparison table (Markdown) of evaluation folders, and one summary per configuration (for the cards).

        Raises ValueError with a message for the user.
        """
        if not 1 <= len(names) <= MAX_COMPARED:
            raise ValueError(f"choose between 1 and {MAX_COMPARED} evaluations")
        folders = []
        for name in names:
            folder = self.resolve_group(name)
            if folder is None:
                raise ValueError(f"no such evaluation: {name[:80]}")
            folders.append(folder)
        if not self.expected_dir.is_dir():
            raise ValueError(f"the expected answers ({self.expected_dir}) were not found: start the UI from the repository root")
        try:
            text, results = compare(folders, self.expected_dir)
        except (EvaluationError, OSError, ValidationError) as exc:
            raise ValueError(str(exc).splitlines()[0][:400]) from exc
        configs = []
        for r in results:
            t = totals(r.scores)
            configs.append({
                "label": r.label, "model": r.config.model if r.config else "", "runs": t.runs, "failed": t.failed,
                "tp": t.tp, "fp": t.fp, "fn": t.fn, "precision": t.precision, "recall": t.recall, "f1": t.f1,
                "provisional": "confirmed by" not in r.label_basis,
            })
        return text, configs

    # ------------------------------------------------------------------ overview numbers

    def run_stats(self, folder: Path) -> dict | None:
        """What one finished run found, with the human decisions on it. Cached until its files change."""
        signature = _signature(folder)
        cached = self._stats.get(folder)
        if cached and cached[0] == signature:
            return cached[1]
        result = _read_json(folder / "result.json")
        if result is None:
            return None
        decisions = {d.get("finding_index"): d.get("decision") for d in (_read_json(folder / "triage.json") or {}).get("decisions", [])}
        stats = {
            "findings": [{"severity": f.get("severity"), "category": f.get("category"), "found_by": f.get("found_by") or [],
                          "tool": f.get("source") == "tool", "decision": decisions.get(i)}
                         for i, f in enumerate(result.get("findings", []))],
            "dismissed": len(result.get("dismissed", [])),
        }
        self._stats[folder] = (signature, stats)
        return stats

    def stats(self, scope: str) -> dict:
        """Numbers over the finished runs: how many, what they found, how serious, what people accepted."""
        if scope not in SCOPES:
            raise ValueError(f"scope must be one of: {', '.join(SCOPES)}")
        counters = {k: {} for k in ("severity", "category", "found_by")}
        total = {"runs": 0, "individual": 0, "evaluation": 0, "findings": 0, "tool": 0, "verifier_dismissed": 0, "accepted": 0, "rejected": 0}

        def count(kind: str, name: str, decision: str | None) -> None:
            entry = counters[kind].setdefault(name, Counter())
            entry["n"] += 1
            if decision in ("accepted", "dismissed"):
                entry[decision] += 1

        for folder in self.run_folders():
            nested = "/" in self.rel(folder)
            if (scope == "reviews" and nested) or (scope == "evaluations" and not nested):
                continue
            run = self.run_stats(folder)
            if run is None:
                continue
            total["runs"] += 1
            total["evaluation" if nested else "individual"] += 1
            total["verifier_dismissed"] += run["dismissed"]
            for f in run["findings"]:
                total["findings"] += 1
                total["tool"] += f["tool"]
                total["accepted"] += f["decision"] == "accepted"
                total["rejected"] += f["decision"] == "dismissed"
                count("severity", f["severity"] or "unknown", f["decision"])
                count("category", f["category"] or "unknown", f["decision"])
                for who in f["found_by"] or ["not recorded"]:
                    count("found_by", who, f["decision"])

        def rows(kind: str, order: tuple[str, ...] | None = None) -> list[dict]:
            names = sorted(counters[kind], key=lambda n: (-counters[kind][n]["n"], n))
            if order:
                names = [n for n in order if n in counters[kind]] + [n for n in names if n not in order]
            return [{"name": n, "n": counters[kind][n]["n"], "accepted": counters[kind][n]["accepted"],
                     "dismissed": counters[kind][n]["dismissed"]} for n in names]

        by_severity = rows("severity", SEVERITY_ORDER)
        return {
            "scope": scope, "runs": total["runs"], "individual_runs": total["individual"], "evaluation_runs": total["evaluation"],
            "findings": total["findings"], "high": sum(r["n"] for r in by_severity if r["name"] in ("critical", "high")),
            "tool_backed": total["tool"], "verifier_dismissed": total["verifier_dismissed"],
            "accepted": total["accepted"], "triaged": total["accepted"] + total["rejected"],
            "by_severity": by_severity, "by_category": rows("category"), "by_found_by": rows("found_by"),
        }

    def run_detail(self, folder: Path) -> dict:
        return {
            "summary": self.summarise(folder),
            "run": _read_json(folder / "run.json"),
            "result": _read_json(folder / "result.json"),
            "report": _read_text(folder / "report.md"),
            "events": read_events(folder / "events.jsonl"),
            "triage": _read_json(folder / "triage.json"),
        }

    def save_triage(self, folder: Path, payload: dict) -> TriageFile:
        result_path = folder / "result.json"
        if not result_path.exists():
            raise ValueError("this run has no result yet")
        result = ReviewResult.model_validate_json(result_path.read_text(encoding="utf-8"))
        triage = TriageFile.model_validate(
            {**payload, "updated_at": datetime.now(UTC).isoformat(timespec="seconds")}
        )
        bad = [d.finding_index for d in triage.decisions if d.finding_index >= len(result.findings)]
        if bad:
            raise ValueError(f"no such finding: {bad}")
        tmp = folder / "triage.json.tmp"
        tmp.write_text(triage.model_dump_json(indent=2), encoding="utf-8")
        tmp.replace(folder / "triage.json")
        report = _read_text(folder / "report.md") or ""
        (folder / "report-triaged.md").write_text(report + render_triage_section(result, triage), encoding="utf-8")
        return triage

    # ------------------------------------------------------------------ jobs

    def start_job(self, ref: str, options: dict) -> Job:
        if self.start_review is None:
            raise RuntimeError("this server was started without a model; restart it with the usual model options")
        parse_pr_reference(ref)  # raises GitHubError with a clear message for bad input
        with self.lock:
            if sum(j.status == "running" for j in self.jobs.values()) >= MAX_RUNNING_JOBS:
                raise BusyError(f"{MAX_RUNNING_JOBS} reviews are already running")
            job = Job(id=uuid.uuid4().hex[:12], ref=ref, events=EventLog())
            self.jobs[job.id] = job
        threading.Thread(target=self._work, args=(job, options), daemon=True).start()
        return job

    def _work(self, job: Job, options: dict) -> None:
        try:
            folder = self.start_review(job.ref, options, job.events)  # type: ignore[misc]
            job.run_name = self.rel(folder)
            job.status = "done"
            job.events.emit("job", "Review finished", status="done", run=job.run_name)
        except Exception as exc:  # noqa: BLE001 - shown to the user, never swallowed
            job.error = f"{type(exc).__name__}: {exc}"[:500]
            job.status = "failed"
            job.events.emit("job", job.error, status="error")

    def job_detail(self, job: Job) -> dict:
        return {"id": job.id, "ref": job.ref, "status": job.status, "run_name": job.run_name,
                "error": job.error, "events": [e.to_dict() for e in job.events.events]}


class BusyError(Exception):
    pass


def _signature(folder: Path) -> tuple:
    """Modification times of the files a run summary is made from: unchanged files, unchanged summary."""
    out = []
    for name in ("run.json", "result.json", "events.jsonl", "triage.json"):
        try:
            out.append((folder / name).stat().st_mtime_ns)
        except OSError:
            out.append(None)
    return tuple(out)


def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _read_json(path: Path) -> dict | None:
    text = _read_text(path)
    if text is None:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


# --------------------------------------------------------------------------- HTTP


def make_server(app: UIApp, port: int = 8765, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        server_version = "review-agent-ui"

        def log_message(self, *args):  # keep the terminal quiet
            pass

        # -- helpers
        def _origin_ok(self) -> bool:
            port_now = self.server.server_address[1]
            allowed = {f"127.0.0.1:{port_now}", f"localhost:{port_now}"}
            if self.headers.get("Host", "") not in allowed:  # DNS-rebinding defence
                return False
            origin = self.headers.get("Origin")
            return origin is None or urlparse(origin).netloc in allowed

        def _send(self, status: int, body: bytes, content_type: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", CSP)
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, payload) -> None:
            self._send(status, json.dumps(payload, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def _error(self, status: int, message: str) -> None:
            self._json(status, {"error": message})

        def _static(self, name: str) -> None:
            try:
                data = resources.files("code_review_agent.app").joinpath("web", name).read_bytes()
            except OSError:
                return self._error(HTTPStatus.NOT_FOUND, "not found")
            ctype = STATIC.get(name, "text/html; charset=utf-8")
            self._send(HTTPStatus.OK, data, ctype)

        # -- routes
        def do_GET(self):  # noqa: N802
            if not self._origin_ok():
                return self._error(HTTPStatus.FORBIDDEN, "forbidden host")
            parsed = urlparse(self.path)
            path = parsed.path
            if path in ("/", "/index.html"):
                return self._static("index.html")
            if path.startswith("/static/") and path[8:] in STATIC:
                return self._static(path[8:])
            if path == "/api/config":
                return self._json(HTTPStatus.OK, {**app.info, "can_start": app.start_review is not None})
            if path == "/api/runs":
                return self._json(HTTPStatus.OK, app.list_runs())
            if path == "/api/groups":
                return self._json(HTTPStatus.OK, app.groups())
            if path == "/api/compare":
                names = [n for n in parse_qs(parsed.query).get("groups", [""])[0].split(",") if n]
                try:
                    markdown, configs = app.compare_groups(names)
                    return self._json(HTTPStatus.OK, {"markdown": markdown, "configs": configs})
                except ValueError as exc:
                    return self._error(HTTPStatus.BAD_REQUEST, str(exc))
            if path == "/api/stats":
                try:
                    return self._json(HTTPStatus.OK, app.stats(parse_qs(parsed.query).get("scope", ["all"])[0]))
                except ValueError as exc:
                    return self._error(HTTPStatus.BAD_REQUEST, str(exc))
            if path.startswith("/api/runs/"):
                folder = app.resolve_run(path[len("/api/runs/"):].strip("/"))
                if folder is None:
                    return self._error(HTTPStatus.NOT_FOUND, "no such run")
                return self._json(HTTPStatus.OK, app.run_detail(folder))
            if path.startswith("/api/jobs/"):
                job = app.jobs.get(path[len("/api/jobs/"):])
                if job is None:
                    return self._error(HTTPStatus.NOT_FOUND, "no such job")
                return self._json(HTTPStatus.OK, app.job_detail(job))
            return self._error(HTTPStatus.NOT_FOUND, "not found")

        def _read_json_body(self):
            if not self._origin_ok():
                self._error(HTTPStatus.FORBIDDEN, "forbidden host or origin")
                return None
            if self.headers.get("X-Requested-With") != "review-agent-ui" or \
                    "application/json" not in self.headers.get("Content-Type", ""):
                self._error(HTTPStatus.BAD_REQUEST, "expected a JSON request from the UI")
                return None
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                length = -1
            if not 0 < length <= MAX_BODY:
                self._error(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "body missing or too large")
                return None
            try:
                data = json.loads(self.rfile.read(length))
            except ValueError:
                self._error(HTTPStatus.BAD_REQUEST, "invalid JSON")
                return None
            if not isinstance(data, dict):
                self._error(HTTPStatus.BAD_REQUEST, "expected a JSON object")
                return None
            return data

        def do_POST(self):  # noqa: N802
            path = urlparse(self.path).path
            payload = self._read_json_body()
            if payload is None:
                return
            if path == "/api/review":
                ref = str(payload.get("pr", "")).strip()
                options = {
                    "jira": bool(payload.get("jira")),
                    "jira_projects": str(payload.get("jira_projects", ""))[:200],
                    "ticket_key": str(payload.get("ticket_key", ""))[:40],
                }
                try:
                    job = app.start_job(ref, options)
                except GitHubError as exc:
                    return self._error(HTTPStatus.BAD_REQUEST, str(exc))
                except BusyError as exc:
                    return self._error(HTTPStatus.TOO_MANY_REQUESTS, str(exc))
                except RuntimeError as exc:
                    return self._error(HTTPStatus.SERVICE_UNAVAILABLE, str(exc))
                return self._json(HTTPStatus.ACCEPTED, {"job": job.id})
            if path.startswith("/api/runs/") and path.endswith("/triage"):
                folder = app.resolve_run(path[len("/api/runs/"):-len("/triage")].strip("/"))
                if folder is None:
                    return self._error(HTTPStatus.NOT_FOUND, "no such run")
                try:
                    triage = app.save_triage(folder, payload)
                except (ValueError, ValidationError) as exc:
                    return self._error(HTTPStatus.BAD_REQUEST, str(exc).splitlines()[0][:300])
                return self._json(HTTPStatus.OK, triage.model_dump())
            return self._error(HTTPStatus.NOT_FOUND, "not found")

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server
