"""Model client: the only module that knows how to talk to a language model.

The rest of the program depends on the small `ModelClient` interface below, so
the model or provider can be replaced (another Ollama model, a remote server, or
later an OpenAI-compatible API) without touching the context builder or reports.

LangChain's `ChatOllama` is used as the transport. It gives us one uniform
"chat model" object (send messages, receive an AIMessage with metadata).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx
import ollama
import openai
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI
from pydantic import Field

from ..schemas import FailureKind, ModelReview, StrictModel, public_schema

DEFAULT_HOST = "https://ollama.com"  # Ollama Cloud. Local Ollama: http://localhost:11434
API_KEY_ENV = "OLLAMA_API_KEY"


class ModelSettings(StrictModel):
    """Everything that can change a model's answer. Saved with every review.

    The API key is deliberately NOT here: this object is written to disk. Only the NAME of
    the environment variable that holds it (`key_env`) is recorded.
    """

    provider: Literal["ollama", "openai-compatible"] = "ollama"
    profile: str | None = None  # name of the profile these settings came from
    host: str = DEFAULT_HOST  # Ollama address, or the base URL of an OpenAI-compatible API
    model: str = "gpt-oss:120b"
    key_env: str | None = None  # environment variable holding the API key
    timeout_s: float = Field(default=180.0, gt=0)
    temperature: float = Field(default=0.0, ge=0)  # 0 = as repeatable as possible
    seed: int | None = 42
    num_ctx: int | None = None  # context window (Ollama); None = server default
    num_predict: int | None = None  # max tokens to generate; None = server default
    # Ask Ollama to constrain the answer to our JSON Schema.
    structured_output: bool = True
    # OpenAI-compatible APIs: ask for "a JSON object" (our parser validates the schema anyway).
    json_mode: bool = True
    max_concurrency: int = Field(default=1, ge=1, le=8)  # simultaneous requests the provider allows

    @classmethod
    def from_env(cls, **overrides: Any) -> ModelSettings:
        """Defaults < environment variables < explicit overrides (e.g. CLI flags)."""
        values: dict[str, Any] = {}
        if v := os.environ.get("OLLAMA_HOST"):
            values["host"] = v
        if v := os.environ.get("OLLAMA_MODEL"):
            values["model"] = v
        if v := os.environ.get("OLLAMA_TIMEOUT"):
            values["timeout_s"] = float(v)
        values.update({k: v for k, v in overrides.items() if v is not None})
        return cls(**values)


@dataclass(frozen=True)
class ModelResponse:
    text: str  # raw model output, not validated
    duration_s: float | None
    prompt_tokens: int | None
    completion_tokens: int | None
    done_reason: str | None


class ModelError(Exception):
    """A model call failed in a way we can classify. Carries a FailureKind."""

    def __init__(self, kind: FailureKind, message: str):
        super().__init__(message)
        self.kind = kind
        self.message = message


class ModelClient(Protocol):
    settings: ModelSettings

    def complete(self, system: str, user: str, schema: dict | None = None) -> ModelResponse:
        """Send one system + user message. `schema` is the JSON Schema the answer must follow
        (used by providers that can constrain output; defaults to the single-pass review schema)."""
        ...


class OllamaClient:
    """Talks to an Ollama server (local or Ollama Cloud) through LangChain."""

    def __init__(self, settings: ModelSettings, api_key: str | None = None):
        self.settings = settings
        key_env = settings.key_env or API_KEY_ENV
        api_key = api_key if api_key is not None else os.environ.get(key_env)
        is_cloud = "ollama.com" in settings.host
        if is_cloud and not api_key:
            raise ModelError(
                FailureKind.AUTH_ERROR,
                f"{key_env} is not set. Ollama Cloud needs an API key "
                "(create one at https://ollama.com/settings/keys).",
            )
        client_kwargs: dict[str, Any] = {"timeout": settings.timeout_s}
        if api_key:
            client_kwargs["headers"] = {"Authorization": f"Bearer {api_key}"}
        self._chat = ChatOllama(
            model=settings.model,
            base_url=settings.host,
            temperature=settings.temperature,
            seed=settings.seed,
            num_ctx=settings.num_ctx,
            num_predict=settings.num_predict,
            client_kwargs=client_kwargs,
        )

    def complete(self, system: str, user: str, schema: dict | None = None) -> ModelResponse:
        extra: dict[str, Any] = {}
        if self.settings.structured_output:
            extra["format"] = schema if schema is not None else public_schema(ModelReview)
        try:
            message = self._chat.invoke([SystemMessage(system), HumanMessage(user)], **extra)
        except Exception as exc:  # noqa: BLE001 - classified below, never swallowed
            raise self._classify(exc) from exc

        meta = message.response_metadata or {}
        total_ns = meta.get("total_duration")
        return ModelResponse(
            text=message.text,
            duration_s=total_ns / 1e9 if total_ns else None,
            prompt_tokens=meta.get("prompt_eval_count"),
            completion_tokens=meta.get("eval_count"),
            done_reason=meta.get("done_reason"),
        )

    def _classify(self, exc: Exception) -> ModelError:
        s = self.settings
        if isinstance(exc, httpx.TimeoutException):
            return ModelError(
                FailureKind.TIMEOUT, f"No answer from {s.host} within {s.timeout_s:g} s."
            )
        if isinstance(exc, (ConnectionError, httpx.ConnectError)):
            return ModelError(
                FailureKind.CONNECTION_ERROR,
                f"Cannot reach Ollama at {s.host}. Is the server running / the address right?",
            )
        if isinstance(exc, ollama.ResponseError):
            code = exc.status_code
            detail = str(exc)
            if code in (401, 403):
                return ModelError(FailureKind.AUTH_ERROR, f"Ollama refused the API key ({code}).")
            if code == 429:
                return ModelError(FailureKind.RATE_LIMITED, f"Rate limit or quota reached: {detail}")
            if code == 404:
                return ModelError(
                    FailureKind.MODEL_UNAVAILABLE,
                    f"Model '{s.model}' not found on {s.host}. Check the name"
                    " (local: `ollama pull <model>`).",
                )
            return ModelError(FailureKind.MODEL_UNAVAILABLE, f"Ollama error {code}: {detail}")
        return ModelError(FailureKind.CONNECTION_ERROR, f"Unexpected {type(exc).__name__}: {exc}")


class OpenAICompatibleClient:
    """Talks to any OpenAI-compatible chat API (OpenRouter, Together, a vLLM server...) through LangChain.

    This is how hosted Qwen models are reached without a GPU of our own.
    """

    def __init__(self, settings: ModelSettings, api_key: str | None = None):
        self.settings = settings
        key_env = settings.key_env or "OPENAI_API_KEY"
        api_key = api_key if api_key is not None else os.environ.get(key_env)
        if not api_key:
            raise ModelError(
                FailureKind.AUTH_ERROR,
                f"{key_env} is not set. The profile '{settings.profile or settings.model}' needs an API key "
                f"for {settings.host}.",
            )
        self._chat = ChatOpenAI(
            model=settings.model,
            openai_api_base=settings.host,
            openai_api_key=api_key,
            temperature=settings.temperature,
            seed=settings.seed,
            request_timeout=settings.timeout_s,
            # `max_tokens` (understood by every OpenAI-style host) rather than the newer
            # `max_completion_tokens` that LangChain would send for its own `max_tokens` argument.
            extra_body={"max_tokens": settings.num_predict} if settings.num_predict else None,
            max_retries=0,  # a failed call is reported, not silently repeated
            model_kwargs={"response_format": {"type": "json_object"}} if settings.json_mode else {},
        )

    def complete(self, system: str, user: str, schema: dict | None = None) -> ModelResponse:
        try:
            message = self._chat.invoke([SystemMessage(system), HumanMessage(user)])
        except Exception as exc:  # noqa: BLE001 - classified below, never swallowed
            raise self._classify(exc) from exc
        meta = message.response_metadata or {}
        usage = meta.get("token_usage") or {}
        return ModelResponse(
            text=message.text,
            duration_s=None,  # OpenAI-style APIs do not report a server-side duration
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            done_reason=meta.get("finish_reason"),
        )

    def _classify(self, exc: Exception) -> ModelError:
        s = self.settings
        if isinstance(exc, openai.APITimeoutError):
            return ModelError(FailureKind.TIMEOUT, f"No answer from {s.host} within {s.timeout_s:g} s.")
        if isinstance(exc, openai.APIConnectionError):
            return ModelError(FailureKind.CONNECTION_ERROR, f"Cannot reach {s.host}. Check the address and your network.")
        if isinstance(exc, (openai.AuthenticationError, openai.PermissionDeniedError)):
            return ModelError(FailureKind.AUTH_ERROR, f"{s.host} refused the API key. Check {s.key_env or 'the key'}.")
        if isinstance(exc, openai.NotFoundError):
            return ModelError(FailureKind.MODEL_UNAVAILABLE, f"Model '{s.model}' not found on {s.host}. Check the model id.")
        if isinstance(exc, openai.RateLimitError):
            return ModelError(FailureKind.RATE_LIMITED, f"Rate limit or quota reached at {s.host}.")
        if isinstance(exc, openai.APIStatusError):
            if exc.status_code == 402:
                return ModelError(FailureKind.RATE_LIMITED, f"{s.host} says credits are insufficient (402). Add credit to the account.")
            return ModelError(FailureKind.MODEL_UNAVAILABLE, f"{s.host} returned HTTP {exc.status_code} for '{s.model}'.")
        return ModelError(FailureKind.CONNECTION_ERROR, f"Unexpected {type(exc).__name__}: {exc}")


def make_client(settings: ModelSettings, api_key: str | None = None) -> ModelClient:
    """The right client for a provider. Add a branch here to support another kind of server."""
    if settings.provider == "openai-compatible":
        return OpenAICompatibleClient(settings, api_key)
    return OllamaClient(settings, api_key)