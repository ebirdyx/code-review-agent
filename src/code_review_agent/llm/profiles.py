"""Model profiles: named, documented model setups you can switch with one flag.

A profile is a recipe (provider, address, model id, which environment variable holds the key).
It never contains a secret. `resolve_settings` turns a profile plus command-line overrides into
the `ModelSettings` that are saved with every review.
"""

from __future__ import annotations

import os
import tomllib
from importlib import resources
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, ValidationError

from ..schemas import StrictModel
from .client import DEFAULT_HOST, ModelSettings

PROFILE_ENV = "REVIEW_AGENT_PROFILE"
PROFILES_FILE_ENV = "REVIEW_AGENT_PROFILES"


class ProfileError(Exception):
    """A profile is missing or malformed. The message says what to fix."""


class Profile(StrictModel):
    provider: Literal["ollama", "openai-compatible"] = "ollama"
    host: str = DEFAULT_HOST
    model: str
    key_env: str | None = None
    timeout_s: float = Field(default=180.0, gt=0)
    temperature: float = Field(default=0.0, ge=0)
    seed: int | None = 42
    num_ctx: int | None = None
    num_predict: int | None = None
    structured_output: bool = True
    json_mode: bool = True
    max_concurrency: int = Field(default=1, ge=1, le=8)
    licence: str = ""  # licence of the model weights, for the report
    notes: str = ""


class ProfileFile(StrictModel):
    default: str
    profiles: dict[str, Profile]


def _read(path: Path | None, text: str | None = None) -> dict[str, Any]:
    try:
        return tomllib.loads(text if text is not None else path.read_text(encoding="utf-8"))  # type: ignore[union-attr]
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ProfileError(f"Cannot read profiles from {path or 'the built-in file'}: {exc}") from exc


def load_profiles(extra: Path | None = None) -> ProfileFile:
    """Built-in profiles, overlaid with a user file (explicit path, $REVIEW_AGENT_PROFILES or ./models.toml)."""
    builtin = _read(None, resources.files("code_review_agent.llm").joinpath("models.toml").read_text(encoding="utf-8"))
    merged: dict[str, Any] = {"default": builtin["default"], "profiles": dict(builtin.get("profiles", {}))}
    user_path = extra or (Path(os.environ[PROFILES_FILE_ENV]) if os.environ.get(PROFILES_FILE_ENV) else Path("models.toml"))
    if user_path.exists():
        user = _read(user_path)
        merged["profiles"].update(user.get("profiles", {}))
        merged["default"] = user.get("default", merged["default"])
    try:
        parsed = ProfileFile.model_validate(merged)
    except ValidationError as exc:
        raise ProfileError(f"Invalid profile definition: {exc.errors()[0]['loc']} {exc.errors()[0]['msg']}") from exc
    if parsed.default not in parsed.profiles:
        raise ProfileError(f"The default profile '{parsed.default}' is not defined.")
    return parsed


def resolve_settings(
    profile: str | None = None,
    overrides: dict[str, Any] | None = None,
    profiles_file: Path | None = None,
) -> ModelSettings:
    """Profile (explicit > $REVIEW_AGENT_PROFILE > default) + overrides (command-line flags).

    When no profile is chosen, the legacy OLLAMA_HOST / OLLAMA_MODEL / OLLAMA_TIMEOUT variables
    still apply on top of the default profile, as before profiles existed.
    """
    available = load_profiles(profiles_file)
    explicit = profile or os.environ.get(PROFILE_ENV)
    name = explicit or available.default
    if name not in available.profiles:
        raise ProfileError(f"Unknown profile '{name}'. Available: {', '.join(sorted(available.profiles))}.")
    values = available.profiles[name].model_dump(exclude={"licence", "notes"})
    if explicit is None:
        for env, field in (("OLLAMA_HOST", "host"), ("OLLAMA_MODEL", "model")):
            if os.environ.get(env):
                values[field] = os.environ[env]
        if os.environ.get("OLLAMA_TIMEOUT"):
            values["timeout_s"] = float(os.environ["OLLAMA_TIMEOUT"])
    values.update({k: v for k, v in (overrides or {}).items() if v is not None})
    return ModelSettings(profile=name, **values)
