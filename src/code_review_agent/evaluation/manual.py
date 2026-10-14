"""Evaluating answers produced OUTSIDE the tool, for example in a chat with Claude or ChatGPT.

The comparison with a more advanced agent must use the same input and the same scoring as the open models:

  * `export_prompt` writes exactly the text the single-pass pipeline sends to a model (same instructions, same ticket,
    same diff, same supporting code), ready to paste into a chat;
  * `manual_record` turns the pasted answer back into a `RunRecord`, which is then validated and saved like any other run
    (JSON, schema, files, lines, quotes), so `eval-compare` can put it next to the open-model configurations.

What is NOT the same, and must be stated in a report: a chat interface may add hidden instructions or tools, and it does
not enforce the JSON Schema the way our API calls do. `extract_json_object` lets an answer with prose around the JSON be
scored on its content; every such repair is counted so the report can say how often it was needed.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from ..context.builder import DEFAULT_PROMPT_VERSION, build_context
from ..llm.client import ModelSettings
from ..pipeline.records import RunRecord, sent_text
from ..schemas import ReviewInput, Ticket

MANUAL_HOST = "manual (chat interface)"


def export_prompt(ticket: Ticket | None, review_input: ReviewInput, max_chars: int, prompt_version: str = DEFAULT_PROMPT_VERSION) -> str:
    """The exact text the single-pass pipeline sends, as one message: instructions, then the fenced content."""
    context = build_context(ticket, review_input, max_chars=max_chars, prompt_version=prompt_version)
    return f"{context.system}\n\n----------------------------------------\n\n{context.user}\n"


def extract_json_object(text: str) -> tuple[str, bool]:
    """The first complete top-level JSON object in `text`, and whether anything had to be cut away.

    Returns the text unchanged (False) when it already is one JSON document or when no object can be found, so a
    genuinely broken answer is still reported as broken. A Markdown fence around the JSON counts as "unchanged": the
    validator already tolerates (and reports) fences.
    """
    stripped = text.strip()
    try:
        json.loads(stripped)
        return text, False
    except ValueError:
        pass
    if stripped.startswith("```") and stripped.endswith("```"):
        return text, False
    start = stripped.find("{")
    while start != -1:
        depth, in_string, escaped = 0, False, False
        for i in range(start, len(stripped)):
            ch = stripped[i]
            if in_string:
                if escaped:
                    escaped = False
                elif ch == "\\":
                    escaped = True
                elif ch == '"':
                    in_string = False
            elif ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = stripped[start:i + 1]
                    try:
                        json.loads(candidate)
                    except ValueError:
                        break  # this brace was not the start of the answer: look for the next one
                    return candidate, True
        start = stripped.find("{", start + 1)
    return text, False


def manual_record(
    case_id: str,
    answer: str,
    ticket: Ticket | None,
    review_input: ReviewInput,
    model_name: str,
    max_chars: int,
    prompt_version: str = DEFAULT_PROMPT_VERSION,
) -> tuple[RunRecord, str]:
    """A run record for an answer given outside the tool, and the text that was (to be) sent. No model is called."""
    context = build_context(ticket, review_input, max_chars=max_chars, prompt_version=prompt_version)
    record = RunRecord(
        case_id=case_id,
        created_at=datetime.now(UTC).isoformat(timespec="seconds"),
        prompt_version=context.prompt_version,
        settings=ModelSettings(model=model_name, host=MANUAL_HOST),
        max_chars=max_chars,
        coverage=context.coverage,
        missing_inputs=context.missing_inputs,
        raw_response=answer,
    )
    return record, sent_text(context.system, context.user)
