"""Stage 3 tests.

MOCKED: these talk to a fake Ollama server running in a thread on localhost.
They prove our error handling, settings and record-keeping. They do NOT prove
that a real model produces a good review; only `review-agent review` against a
real server does that.
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from code_review_agent.connectors.snapshot import load_example
from code_review_agent.llm.client import ModelError, ModelSettings, OllamaClient
from code_review_agent.pipeline.records import save_run
from code_review_agent.pipeline.single import run_review
from code_review_agent.schemas import FailureKind

ROOT = Path(__file__).resolve().parent.parent


class FakeOllama:
    """Fake Ollama server. `mode` picks the behaviour; requests are recorded."""

    def __init__(self, mode: str = "ok", content: str = '{"findings": [], "limitations": []}'):
        self.mode, self.content, self.requests = mode, content, []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # silence test output
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append({"path": self.path, "headers": dict(self.headers), "body": body})
                if outer.mode == "slow":
                    time.sleep(2)
                if outer.mode in {"401", "404", "429", "500"}:
                    payload = json.dumps({"error": f"fake {outer.mode}"}).encode()
                    self.send_response(int(outer.mode))
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                chunk = {
                    "model": body["model"],
                    "created_at": "2026-01-01T00:00:00Z",
                    "message": {"role": "assistant", "content": outer.content},
                    "done": True,
                    "done_reason": "stop",
                    "total_duration": 2_500_000_000,
                    "prompt_eval_count": 111,
                    "eval_count": 22,
                }
                self.send_response(200)
                self.send_header("Content-Type", "application/x-ndjson")
                self.end_headers()
                self.wfile.write((json.dumps(chunk) + "\n").encode())

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.host = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


@pytest.fixture
def fake():
    servers = []

    def make(**kwargs):
        servers.append(FakeOllama(**kwargs))
        return servers[-1]

    yield make
    for s in servers:
        s.close()


def client_for(server, **overrides):
    return OllamaClient(ModelSettings(host=server.host, model="test-model", **overrides), api_key="k-test")


def complete(client):
    return client.complete("system text", "user text")


# --------------------------------------------------------------------- success


def test_success_returns_raw_text_and_metadata(fake):
    server = fake(content="RAW OUTPUT, not even JSON")
    response = complete(client_for(server))
    assert response.text == "RAW OUTPUT, not even JSON"  # preserved, not parsed
    assert response.duration_s == 2.5
    assert (response.prompt_tokens, response.completion_tokens) == (111, 22)
    assert response.done_reason == "stop"


def test_settings_and_auth_header_reach_the_server(fake):
    server = fake()
    complete(client_for(server, temperature=0.3, seed=7, num_ctx=4096))
    sent = server.requests[0]
    assert sent["path"] == "/api/chat"
    headers = {k.lower(): v for k, v in sent["headers"].items()}  # header names are case-insensitive
    assert headers["authorization"] == "Bearer k-test"
    assert sent["body"]["model"] == "test-model"
    assert sent["body"]["options"]["temperature"] == 0.3
    assert sent["body"]["options"]["seed"] == 7
    assert sent["body"]["options"]["num_ctx"] == 4096
    roles = [m["role"] for m in sent["body"]["messages"]]
    assert roles == ["system", "user"]


def test_json_schema_is_sent_when_structured_output_on(fake):
    server = fake()
    complete(client_for(server))
    fmt = server.requests[0]["body"]["format"]
    assert isinstance(fmt, dict) and "findings" in fmt["properties"]


def test_json_schema_not_sent_when_structured_output_off(fake):
    server = fake()
    complete(client_for(server, structured_output=False))
    assert not server.requests[0]["body"].get("format")


# ---------------------------------------------------------------------- errors


@pytest.mark.parametrize(
    ("mode", "kind"),
    [
        ("401", FailureKind.AUTH_ERROR),
        ("404", FailureKind.MODEL_UNAVAILABLE),
        ("429", FailureKind.RATE_LIMITED),
        ("500", FailureKind.MODEL_UNAVAILABLE),
    ],
)
def test_http_errors_are_classified(fake, mode, kind):
    with pytest.raises(ModelError) as info:
        complete(client_for(fake(mode=mode)))
    assert info.value.kind == kind


def test_unknown_model_message_names_the_model(fake):
    with pytest.raises(ModelError) as info:
        complete(client_for(fake(mode="404")))
    assert "test-model" in info.value.message


def test_timeout_is_classified(fake):
    with pytest.raises(ModelError) as info:
        complete(client_for(fake(mode="slow"), timeout_s=0.3))
    assert info.value.kind == FailureKind.TIMEOUT


def test_unreachable_server_is_classified():
    # REAL network failure (nothing listens on port 9): no fake involved.
    client = OllamaClient(ModelSettings(host="http://127.0.0.1:9", model="m", timeout_s=3), api_key="k")
    with pytest.raises(ModelError) as info:
        complete(client)
    assert info.value.kind == FailureKind.CONNECTION_ERROR


def test_cloud_without_api_key_fails_clearly(monkeypatch):
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    with pytest.raises(ModelError) as info:
        OllamaClient(ModelSettings())  # default host is Ollama Cloud
    assert info.value.kind == FailureKind.AUTH_ERROR
    assert "OLLAMA_API_KEY" in info.value.message


def test_local_server_needs_no_api_key(monkeypatch):
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    OllamaClient(ModelSettings(host="http://localhost:11434"))  # must not raise


def test_settings_from_env_and_override(monkeypatch):
    monkeypatch.setenv("OLLAMA_MODEL", "from-env")
    monkeypatch.setenv("OLLAMA_TIMEOUT", "12")
    assert ModelSettings.from_env().model == "from-env"
    assert ModelSettings.from_env().timeout_s == 12
    assert ModelSettings.from_env(model="from-flag").model == "from-flag"
    assert ModelSettings.from_env(model=None).model == "from-env"  # None = not given


# ----------------------------------------------------------------- run records


def test_run_record_keeps_settings_prompt_version_and_raw_response(fake, tmp_path):
    ticket, review_input = load_example(ROOT / "examples" / "free-shipping-faulty")
    client = client_for(fake(content="not json at all"))
    record, sent = run_review("free-shipping-faulty", ticket, review_input, client, max_chars=30000)
    folder = save_run(record, sent, tmp_path)

    saved = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    assert saved["prompt_version"] == "review_v1"
    assert saved["settings"]["model"] == "test-model"
    assert saved["settings"]["temperature"] == 0.0
    assert saved["raw_response"] == "not json at all"
    assert (folder / "raw_response.txt").read_text(encoding="utf-8") == "not json at all"
    assert "SYSTEM MESSAGE" in (folder / "context.txt").read_text(encoding="utf-8")
    assert "k-test" not in json.dumps(saved)  # the API key is never written to disk


def test_failed_call_is_recorded_not_raised(fake, tmp_path):
    ticket, review_input = load_example(ROOT / "examples" / "free-shipping-faulty")
    record, sent = run_review("c", ticket, review_input, client_for(fake(mode="404")), 30000)
    assert record.raw_response is None
    assert record.error is not None and record.error.kind == FailureKind.MODEL_UNAVAILABLE
    folder = save_run(record, sent, tmp_path)
    assert not (folder / "raw_response.txt").exists()
    assert (folder / "run.json").exists()
