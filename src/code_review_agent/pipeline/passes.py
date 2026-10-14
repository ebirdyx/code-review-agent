"""The specialist passes: which exist, the JSON Schema each must answer with, and the prompts they are given.

Prompt sets are folders under `prompts/` (`multi_v1` ... `multi_v4`); an old set stays loadable so an old run can be
reproduced. `render_candidates` is the numbered list the verifier is shown.
"""

from __future__ import annotations

import json
from importlib import resources

from pydantic import BaseModel

from ..schemas import (
    ComplianceReview,
    Finding,
    ModelReview,
    VerifyReview,
    public_schema,
)

# The prompt set used by default. Older sets stay loadable so an old run can be reproduced:
#   v1 had no static-analysis or team-rules blocks; v3 added a stricter rules pass, guidance for vague criteria and a
#   verifier that judges rule findings; v4 describes the RELATED CODE block (repository context).
MULTI_PROMPT_VERSION = "multi_v4"
DEFAULT_PASSES = ("compliance", "defects", "security", "standards")
PASS_MODELS: dict[str, type[BaseModel]] = {
    "compliance": ComplianceReview,
    "defects": ModelReview,
    "security": ModelReview,
    "standards": ModelReview,
    "verify": VerifyReview,
}


def schema_for(name: str) -> dict:
    """The JSON Schema one pass must follow (only the standards pass may cite the team rules)."""
    return public_schema(PASS_MODELS[name], allow_rules=(name == "standards"))


def available_multi_versions() -> list[str]:
    root = resources.files("code_review_agent").joinpath("prompts")
    return sorted(p.name for p in root.iterdir() if p.is_dir() and p.joinpath("common.md").is_file())


def load_pass_system(version: str, name: str) -> str:
    """System prompt of one pass: shared rules + the pass's focus + the JSON Schema of its output."""
    if version not in available_multi_versions():
        raise ValueError(f"Unknown multi-pass prompt version '{version}'. Available: {', '.join(available_multi_versions())}")
    if name not in PASS_MODELS:
        raise ValueError(f"Unknown pass '{name}'. Available: {', '.join(PASS_MODELS)}")
    base = resources.files("code_review_agent").joinpath("prompts", version)
    common = base.joinpath("common.md").read_text(encoding="utf-8").rstrip()
    focus = base.joinpath(f"{name}.md").read_text(encoding="utf-8").rstrip()
    schema = json.dumps(schema_for(name), indent=1)
    return (
        f"{common}\n\n{focus}\n\n## Output format\n\n"
        "Reply with a single JSON object and nothing else (no Markdown fences, no commentary). "
        f"It must follow this JSON Schema:\n```json\n{schema}\n```\n"
    )


def render_candidates(findings: list[Finding]) -> str:
    """The numbered candidate list shown to the verifier (one compact entry per finding)."""
    entries = []
    for i, f in enumerate(findings, 1):
        where = f"{f.file}:{f.line}" if f.line else f.file
        claim = " ".join(f.explanation.split())
        quotes = "; ".join(f'{e.source}: "{" ".join(e.quote.split())}"' for e in f.evidence)
        entries.append(f"{i}. [{f.severity}] {f.category} at {where}: {' '.join(f.title.split())}\n"
                       f"   Claim: {claim}\n   Evidence: {quotes}")
    return "\n".join(entries)
