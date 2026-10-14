"""Model profiles and the OpenAI-compatible client.

MOCKED: a fake server on localhost speaks the OpenAI chat-completions format. This proves our
request shape, error handling and settings; it does not prove a given hosted provider behaves
identically (run `review-agent review ... --profile qwen25-coder-32b-openrouter` for that).
"""

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from code_review_agent.app.cli import main
from code_review_agent.llm.client import (
    ModelError,
    ModelSettings,
    OllamaClient,
    OpenAICompatibleClient,
    make_client,
)
from code_review_agent.llm.profiles import ProfileError, load_profiles, resolve_settings
from code_review_agent.schemas import FailureKind


class FakeOpenAI:
    def __init__(self, mode="ok", content='{"findings": [], "limitations": []}'):
        self.mode, self.content, self.requests = mode, content, []
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
                if outer.mode == "slow":
                    time.sleep(2)
                if outer.mode in {"401", "403", "404", "402", "429", "500", "400"}:
                    payload = json.dumps({"error": {"message": f"fake {outer.mode}", "type": "x"}}).encode()
                    self.send_response(int(outer.mode))
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(payload)
                    return
                payload = json.dumps({
                    "id": "chatcmpl-1", "object": "chat.completion", "created": 1, "model": body["model"],
                    "choices": [{"index": 0, "message": {"role": "assistant", "content": outer.content}, "finish_reason": "stop"}],
                    "usage": {"prompt_tokens": 111, "completion_tokens": 22, "total_tokens": 133},
                }).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(payload)

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        self.base_url = f"http://127.0.0.1:{self.server.server_port}/v1"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()


@pytest.fixture
def fake_openai():
    servers = []

    def make(**kw):
        servers.append(FakeOpenAI(**kw))
        return servers[-1]

    yield make
    for s in servers:
        s.close()


def settings_for(server, **kw):
    return ModelSettings(provider="openai-compatible", host=server.base_url, model="qwen/test", key_env="TEST_KEY", **kw)


# ------------------------------------------------------------------ profiles file


def test_builtin_profiles_are_valid_documented_and_include_the_team_model():
    profiles = load_profiles()
    assert profiles.default in profiles.profiles
    assert "qwen25-coder-14b-local" in profiles.profiles  # the model named in the team plan
    for name, p in profiles.profiles.items():
        assert p.licence, f"{name} must state the licence of its weights"
        assert p.notes, f"{name} must explain itself"
        if p.provider == "openai-compatible":
            assert p.key_env, f"{name} needs a key_env"
    local = profiles.profiles["qwen25-coder-14b-local"]
    assert local.num_ctx and local.num_ctx >= 8192  # Ollama silently truncates a small default context


def test_profiles_contain_no_secrets():
    text = open(__import__("importlib").resources.files("code_review_agent.llm").joinpath("models.toml"), encoding="utf-8").read()
    for marker in ("sk-", "api_key =", "token =", "Bearer"):
        assert marker not in text


def test_user_file_adds_and_overrides_profiles(tmp_path):
    extra = tmp_path / "models.toml"
    extra.write_text('default = "mine"\n[profiles.mine]\nmodel = "my-model"\nlicence = "MIT"\n'
                     '[profiles.gpt-oss-cloud]\nmodel = "gpt-oss:20b"\n', encoding="utf-8")
    profiles = load_profiles(extra)
    assert profiles.default == "mine" and profiles.profiles["mine"].model == "my-model"
    assert profiles.profiles["gpt-oss-cloud"].model == "gpt-oss:20b"  # overridden
    assert "qwen25-coder-14b-local" in profiles.profiles  # built-ins are kept


@pytest.mark.parametrize(
    "content",
    ['default = "nope"\n', "this is not toml [", '[profiles.x]\nprovider = "carrier-pigeon"\nmodel = "m"\n',
     '[profiles.x]\nmodel = "m"\nsurprise = 1\n'],
)
def test_broken_user_files_fail_with_a_clear_message(tmp_path, content):
    path = tmp_path / "models.toml"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ProfileError):
        load_profiles(path)


# ---------------------------------------------------------------------- resolution


def test_default_profile_and_legacy_environment_variables(monkeypatch):
    for name in ("REVIEW_AGENT_PROFILE", "OLLAMA_HOST", "OLLAMA_MODEL", "OLLAMA_TIMEOUT"):
        monkeypatch.delenv(name, raising=False)
    s = resolve_settings()
    assert (s.profile, s.model, s.provider) == ("gpt-oss-cloud", "gpt-oss:120b", "ollama")
    monkeypatch.setenv("OLLAMA_MODEL", "custom:1b")
    monkeypatch.setenv("OLLAMA_TIMEOUT", "9")
    s = resolve_settings()
    assert s.model == "custom:1b" and s.timeout_s == 9  # legacy mode: env applies to the default profile


def test_explicit_profile_ignores_legacy_environment_variables(monkeypatch):
    monkeypatch.delenv("REVIEW_AGENT_PROFILE", raising=False)
    monkeypatch.setenv("OLLAMA_MODEL", "custom:1b")
    s = resolve_settings("qwen25-coder-14b-local")
    assert s.model == "qwen2.5-coder:14b" and s.num_ctx == 16384  # a chosen profile means what it says


def test_profile_from_environment_and_flag_overrides(monkeypatch):
    monkeypatch.setenv("REVIEW_AGENT_PROFILE", "qwen25-coder-7b-local")
    assert resolve_settings().model == "qwen2.5-coder:7b"
    s = resolve_settings("qwen25-coder-14b-local", {"model": "qwen2.5-coder:32b", "temperature": 0.2, "seed": None})
    assert s.model == "qwen2.5-coder:32b" and s.temperature == 0.2 and s.seed == 42  # None = not given


def test_unknown_profile_lists_the_available_ones():
    with pytest.raises(ProfileError, match="qwen25-coder-14b-local"):
        resolve_settings("does-not-exist")


def test_settings_record_only_the_key_variable_name_never_a_key(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-very-secret")
    saved = resolve_settings("qwen25-coder-32b-openrouter").model_dump_json()
    assert "OPENROUTER_API_KEY" in saved and "sk-or-very-secret" not in saved


def test_make_client_picks_the_provider(monkeypatch, fake_openai):
    server = fake_openai()
    monkeypatch.setenv("TEST_KEY", "k")
    assert isinstance(make_client(settings_for(server)), OpenAICompatibleClient)
    assert isinstance(make_client(ModelSettings(host="http://localhost:11434")), OllamaClient)


# ------------------------------------------------------------ OpenAI-compatible client


def test_success_returns_text_tokens_and_finish_reason(fake_openai):
    server = fake_openai(content="RAW TEXT")
    r = OpenAICompatibleClient(settings_for(server), api_key="k").complete("sys", "usr")
    assert r.text == "RAW TEXT" and (r.prompt_tokens, r.completion_tokens) == (111, 22)
    assert r.done_reason == "stop" and r.duration_s is None


def test_request_shape_auth_json_mode_and_settings(fake_openai):
    server = fake_openai()
    OpenAICompatibleClient(settings_for(server, temperature=0.3, seed=7, num_predict=500), api_key="k-test").complete("SYS", "USR")
    sent = server.requests[0]
    assert sent["path"] == "/v1/chat/completions"
    assert sent["headers"]["authorization"] == "Bearer k-test"
    body = sent["body"]
    assert body["model"] == "qwen/test" and body["temperature"] == 0.3 and body["seed"] == 7
    assert body["max_tokens"] == 500 and body["response_format"] == {"type": "json_object"}
    assert [m["role"] for m in body["messages"]] == ["system", "user"]


def test_json_mode_can_be_turned_off(fake_openai):
    server = fake_openai()
    OpenAICompatibleClient(settings_for(server, json_mode=False), api_key="k").complete("s", "u")
    assert "response_format" not in server.requests[0]["body"]


def test_missing_key_names_the_variable(monkeypatch, fake_openai):
    monkeypatch.delenv("TEST_KEY", raising=False)
    with pytest.raises(ModelError) as info:
        OpenAICompatibleClient(settings_for(fake_openai()))
    assert info.value.kind == FailureKind.AUTH_ERROR and "TEST_KEY" in info.value.message


@pytest.mark.parametrize(
    ("mode", "kind"),
    [("401", FailureKind.AUTH_ERROR), ("403", FailureKind.AUTH_ERROR), ("404", FailureKind.MODEL_UNAVAILABLE),
     ("429", FailureKind.RATE_LIMITED), ("402", FailureKind.RATE_LIMITED), ("500", FailureKind.MODEL_UNAVAILABLE),
     ("400", FailureKind.MODEL_UNAVAILABLE)],
)
def test_http_errors_are_classified(fake_openai, mode, kind):
    with pytest.raises(ModelError) as info:
        OpenAICompatibleClient(settings_for(fake_openai(mode=mode)), api_key="k-secret").complete("s", "u")
    assert info.value.kind == kind and "k-secret" not in info.value.message


def test_credit_error_message_says_what_to_do(fake_openai):
    with pytest.raises(ModelError, match="credit"):
        OpenAICompatibleClient(settings_for(fake_openai(mode="402")), api_key="k").complete("s", "u")


def test_timeout_and_unreachable(fake_openai):
    with pytest.raises(ModelError) as info:
        OpenAICompatibleClient(settings_for(fake_openai(mode="slow"), timeout_s=0.3), api_key="k").complete("s", "u")
    assert info.value.kind == FailureKind.TIMEOUT
    dead = ModelSettings(provider="openai-compatible", host="http://127.0.0.1:9/v1", model="m", key_env="X", timeout_s=3)
    with pytest.raises(ModelError) as info:
        OpenAICompatibleClient(dead, api_key="k").complete("s", "u")
    assert info.value.kind == FailureKind.CONNECTION_ERROR  # a REAL refused connection


def test_no_silent_retries(fake_openai):
    server = fake_openai(mode="500")
    with pytest.raises(ModelError):
        OpenAICompatibleClient(settings_for(server), api_key="k").complete("s", "u")
    assert len(server.requests) == 1  # a failed call is reported once, not repeated behind your back


# ------------------------------------------------------------------ per-call schema


def test_ollama_receives_the_schema_given_per_call():
    from tests.llm.test_model_client import FakeOllama

    server = FakeOllama()
    try:
        client = OllamaClient(ModelSettings(host=server.host, model="m"), api_key="k")
        client.complete("s", "u")  # default: the single-pass review schema
        client.complete("s", "u", schema={"type": "object", "properties": {"verdicts": {}}})
    finally:
        server.close()
    assert "findings" in server.requests[0]["body"]["format"]["properties"]
    assert "verdicts" in server.requests[1]["body"]["format"]["properties"]


# ------------------------------------------------------------------------------ CLI


def test_profiles_command_lists_profiles_and_never_prints_a_key(monkeypatch, capsys):
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-very-secret")
    assert main(["profiles"]) == 0
    out = capsys.readouterr().out
    assert "qwen25-coder-32b-openrouter" in out and "OPENROUTER_API_KEY: set" in out
    assert "sk-or-very-secret" not in out and "Apache-2.0" in out


def test_review_with_an_unknown_profile_stops_with_a_clear_message(capsys, tmp_path):
    from pathlib import Path

    example = Path(__file__).resolve().parents[2] / "examples" / "free-shipping-faulty"
    assert main(["review", str(example), "--profile", "nope", "--runs", str(tmp_path)]) == 1
    assert "Unknown profile 'nope'" in capsys.readouterr().err
