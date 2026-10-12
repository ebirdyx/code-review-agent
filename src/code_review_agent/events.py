"""Progress events: what the agent is doing, step by step.

Every stage of a review (fetching the PR, fetching the ticket, building the context, each
model call, validation, report) emits an event. The same events are shown live in the
terminal, saved to `events.jsonl` in the run folder, and read by the web UI.

Events carry only our own short messages and counters, never prompts, model output or
credentials.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

MAX_MESSAGE = 300


@dataclass
class Event:
    ts: str  # UTC, ISO 8601
    stage: str  # e.g. fetch_pr, fetch_ticket, build_context, model_call, validate, report
    status: str  # start | done | error | warn | info
    message: str
    seconds: float | None = None  # duration, on done/error events
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _short(text: str) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= MAX_MESSAGE else text[: MAX_MESSAGE - 1] + "…"


class EventLog:
    """Collects events in memory and, once a path is attached, in a JSON-lines file."""

    def __init__(self, path: Path | None = None, echo: Callable[[Event], None] | None = None):
        self._events: list[Event] = []
        self._path: Path | None = None
        self._echo = echo
        self._lock = threading.Lock()
        if path is not None:
            self.attach(path)

    @property
    def events(self) -> list[Event]:
        with self._lock:
            return list(self._events)

    def attach(self, path: Path) -> None:
        """Start writing to `path`; events recorded before this are written first."""
        with self._lock:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._path = path
            with path.open("w", encoding="utf-8") as f:
                for event in self._events:
                    f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")

    def emit(self, stage: str, message: str, status: str = "info", seconds: float | None = None, **data) -> Event:
        return self._record(stage, message, status, seconds, data)

    def _record(self, stage: str, message: str, status: str, seconds: float | None, data: dict) -> Event:
        """Dict-based so a data key named like a parameter (e.g. 'status') can never collide."""
        event = Event(
            ts=datetime.now(UTC).isoformat(timespec="seconds"),
            stage=stage, status=status, message=_short(message),
            seconds=None if seconds is None else round(seconds, 2), data=data,
        )
        with self._lock:
            self._events.append(event)
            if self._path is not None:
                with self._path.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(event.to_dict(), ensure_ascii=False) + "\n")
        if self._echo is not None:
            self._echo(event)
        return event

    @contextmanager
    def step(self, stage: str, message: str, **data) -> Iterator[dict]:
        """Emit start, then done (or error, re-raising). The caller may add result data to the yielded dict."""
        self._record(stage, message, "start", None, dict(data))
        extra: dict = {}
        started = time.monotonic()
        try:
            yield extra
        except Exception as exc:
            self._record(stage, f"{type(exc).__name__}: {exc}", "error", time.monotonic() - started, dict(data))
            raise
        self._record(stage, message, "done", time.monotonic() - started, {**data, **extra})


def read_events(path: Path) -> list[dict]:
    """Read an events file. A half-written last line (a run in progress) is ignored."""
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def echo_to_stderr(event: Event) -> None:
    """Terminal progress line, e.g. '[20:01:03] model_call  done  Asking gpt-oss (1.6s)'."""
    if event.status == "start" and not event.stage.startswith("model"):
        return  # quick steps: the done/error line says it all. Model calls are slow, so show their start.
    clock = event.ts[11:19]
    took = f" ({event.seconds:g}s)" if event.seconds is not None else ""
    print(f"[{clock}] {event.stage:<14} {event.status:<5} {event.message}{took}", file=sys.stderr, flush=True)
