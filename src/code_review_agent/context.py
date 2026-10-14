"""Context builder: turns ticket + PR + diff + code into the text sent to the model.

No model is involved here. The output is deterministic: same inputs, same text.

Two principles:
  1. Trusted instructions (written by us) and untrusted content (written by
     ticket authors and PR authors) are kept in separate places and the
     untrusted content is fenced with explicit markers.
  2. Nothing is dropped silently. If something is missing or does not fit in the
     size budget, it is listed in `missing_inputs` / `coverage.omitted` and
     also announced to the model in an INPUT STATUS section.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from importlib import resources

from pydantic import Field

from .schemas import Coverage, ModelReview, ReviewInput, StrictModel, Ticket, public_schema

DEFAULT_PROMPT_VERSION = "review_v1"  # change only after a dev comparison (see docs)
DEFAULT_MAX_CHARS = 30_000  # budget for untrusted content (roughly 8k tokens)
FIELD_CAP = 4_000  # max chars for ticket / PR description text before it is cut

HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")
NUM_WIDTH = 5


class ReviewContext(StrictModel):
    prompt_version: str
    system: str  # trusted instructions + output schema
    user: str  # input status + fenced untrusted content
    missing_inputs: list[str] = Field(default_factory=list)
    coverage: Coverage


# ------------------------------------------------------------------ diff handling


@dataclass
class FileDiff:
    path: str
    text: str  # raw diff text of this file


def split_diff(diff: str) -> list[FileDiff]:
    """Split a unified diff into one chunk per file (on `diff --git` lines)."""
    lines = diff.splitlines()
    starts = [i for i, line in enumerate(lines) if line.startswith("diff --git ")]
    if not starts:  # plain `---`/`+++` diff without git headers: treat as one file
        return [FileDiff(_path_of(lines), "\n".join(lines))]
    chunks = []
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        chunk = lines[start:end]
        chunks.append(FileDiff(_path_of(chunk), "\n".join(chunk)))
    return chunks


def _path_of(chunk: list[str]) -> str:
    """File path in the new version (or the old one for deleted files)."""
    old = new = None
    for line in chunk:
        if line.startswith("+++ "):
            new = line[4:].strip()
        elif line.startswith("--- "):
            old = line[4:].strip()
        elif line.startswith("@@"):
            break
    for candidate in (new, old):
        if candidate and candidate != "/dev/null":
            return re.sub(r"^[ab]/", "", candidate)
    if chunk and chunk[0].startswith("diff --git "):  # binary / rename-only
        return chunk[0].split(" b/", 1)[-1].strip()
    return "<unknown>"


def annotate_diff(text: str) -> str:
    """Prefix each diff line with its line number in the NEW file.

    Models are poor at counting lines. We count for them, so a finding can cite a
    number that we can later verify against the same diff.
        '    6 | +    if total > 100:'   added line, new line 6
        '    5 |      def f():'          context line, new line 5
        '      | -    old code'          removed line: no new line number
    """
    out = []
    new_no: int | None = None  # None until the first hunk header
    for line in text.splitlines():
        match = HUNK_HEADER.match(line)
        if match:
            new_no = int(match.group(1))
            out.append(f"{'':>{NUM_WIDTH}} | {line}")
        elif new_no is None or line.startswith(("-", "\\")):
            out.append(f"{'':>{NUM_WIDTH}} | {line}")  # header or removed line
        else:  # '+' line, ' ' context line, or a context line whose space was stripped
            out.append(f"{new_no:>{NUM_WIDTH}} | {line}")
            new_no += 1
    return "\n".join(out)


# ---------------------------------------------------------------- text rendering


def _fit(text: str, cap: int, label: str, omitted: list[str]) -> str:
    """Cut `text` to `cap` chars with a visible marker, and record the cut."""
    if len(text) <= cap:
        return text
    omitted.append(f"{label}: truncated, {len(text) - cap} of {len(text)} characters omitted")
    return text[:cap] + f"\n[TRUNCATED: {len(text) - cap} characters omitted]"


def render_ticket(ticket: Ticket, omitted: list[str]) -> str:
    """The ticket exactly as the model sees it (numbered criteria, labelled fields)."""
    criteria = (
        "\n".join(f"{i}. {c}" for i, c in enumerate(ticket.acceptance_criteria, 1))
        if ticket.acceptance_criteria
        else "(none provided)"
    )
    description = _fit(ticket.description, FIELD_CAP, "ticket description", omitted)
    return (
        f"Key: {ticket.key}\nTitle: {ticket.title}\n"
        f"Description:\n{description or '(none provided)'}\n"
        f"Acceptance criteria:\n{criteria}"
    )


def available_prompt_versions() -> list[str]:
    folder = resources.files("code_review_agent.prompts")
    return sorted(p.name.removesuffix(".md") for p in folder.iterdir() if p.name.endswith(".md"))


def load_system_prompt(prompt_version: str = DEFAULT_PROMPT_VERSION) -> str:
    """Trusted instructions (versioned file) followed by the output JSON Schema."""
    if prompt_version not in available_prompt_versions():
        raise ValueError(
            f"Unknown prompt version '{prompt_version}'. Available: {', '.join(available_prompt_versions())}"
        )
    instructions = (
        resources.files("code_review_agent.prompts")
        .joinpath(f"{prompt_version}.md")
        .read_text(encoding="utf-8")
    )
    schema = json.dumps(public_schema(ModelReview), indent=1)
    return f"{instructions}\n```json\n{schema}\n```\n"


def build_context(
    ticket: Ticket | None,
    review_input: ReviewInput,
    max_chars: int = DEFAULT_MAX_CHARS,
    prompt_version: str = DEFAULT_PROMPT_VERSION,
) -> ReviewContext:
    """Assemble the system and user messages (single-pass pipeline)."""
    user, missing, coverage = build_user_message(ticket, review_input, max_chars)
    return ReviewContext(
        prompt_version=prompt_version,
        system=load_system_prompt(prompt_version),
        user=user,
        missing_inputs=missing,
        coverage=coverage,
    )


def build_user_message(
    ticket: Ticket | None,
    review_input: ReviewInput,
    max_chars: int = DEFAULT_MAX_CHARS,
    extra_blocks: dict[str, str] | None = None,
) -> tuple[str, list[str], Coverage]:
    """The user message: input status plus the fenced untrusted content.

    `max_chars` limits the untrusted content (ticket, PR text, diff, supporting
    code). Whole files are omitted when they do not fit; they are never cut in
    half, except long ticket / PR text which is cut with a visible marker.
    `extra_blocks` adds more fenced blocks (the verifier uses it for candidate findings).
    Returns (message, missing_inputs, coverage).
    """
    missing: list[str] = []
    omitted: list[str] = list(review_input.input_notes)  # what a connector could not retrieve

    # --- ticket and PR text (always included first: they are the requirements)
    if ticket is None:
        missing.append("No Jira ticket was provided. Requirements are unknown.")
        ticket_text = "(no ticket provided)"
    else:
        if not ticket.acceptance_criteria:
            missing.append(f"Ticket {ticket.key} has no acceptance criteria.")
        if not ticket.description.strip():
            missing.append(f"Ticket {ticket.key} has no description.")
        ticket_text = render_ticket(ticket, omitted)

    pr_description = _fit(review_input.pr.description, FIELD_CAP, "PR description", omitted)
    pr_text = f"Title: {review_input.pr.title}\nDescription:\n{pr_description or '(none provided)'}"
    if not review_input.pr.description.strip():
        missing.append("The pull request has no description.")

    remaining = max_chars - len(ticket_text) - len(pr_text)

    # --- diff: whole files, in order, while they fit
    diff_parts: list[str] = []
    for file_diff in split_diff(review_input.diff):
        annotated = annotate_diff(file_diff.text)
        if len(annotated) <= remaining:
            diff_parts.append(annotated)
            remaining -= len(annotated)
        else:
            omitted.append(
                f"diff of {file_diff.path}: omitted, {len(annotated)} characters "
                f"exceeds the remaining budget ({max(remaining, 0)})"
            )
    if not diff_parts:
        diff_parts.append("(no diff content fitted in the budget)")

    # --- supporting code: whole files while they fit
    support_parts: list[str] = []
    for sf in review_input.supporting_files:
        block = f"--- file: {sf.path}\n{sf.content}"
        if len(block) <= remaining:
            support_parts.append(block)
            remaining -= len(block)
        else:
            omitted.append(f"supporting file {sf.path}: omitted, {len(block)} characters too large")
    if not review_input.supporting_files:
        missing.append("No supporting code was provided; only the diff is visible.")

    blocks = {
        "TICKET": ticket_text,
        "PULL REQUEST": pr_text,
        "DIFF": "\n".join(diff_parts),
        "SUPPORTING CODE": "\n\n".join(support_parts) or "(none provided)",
        **(extra_blocks or {}),
    }
    # Marker id derived from the content itself, so the content cannot contain it.
    fence_id = hashlib.sha256("\x00".join(blocks.values()).encode()).hexdigest()[:8]

    status_lines = [f"- MISSING: {m}" for m in missing] + [f"- OMITTED: {o}" for o in omitted]
    status = "\n".join(status_lines) if status_lines else "- All inputs were provided in full."

    sections = [f"## INPUT STATUS\n{status}"]
    for name, content in blocks.items():
        sections.append(
            f"<<<BEGIN UNTRUSTED {name} id={fence_id}>>>\n{content}\n"
            f"<<<END UNTRUSTED {name} id={fence_id}>>>"
        )

    return "\n\n".join(sections), missing, Coverage(complete=not omitted, omitted=omitted)
