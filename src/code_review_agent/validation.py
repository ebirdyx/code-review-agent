"""Turn the model's raw text into a ReviewResult, checking what can be checked.

Three layers, from cheap to meaningful:
  1. Syntax:   is it JSON?
  2. Schema:   does it have the right fields and allowed values?
  3. Grounding: do the cited file, line and quotes exist in the input we sent?

None of these decides whether a finding is TRUE. A finding can pass every check
and still be wrong (a real line, a real quote, a wrong conclusion). The human
reviewer keeps that judgement.

Locations that cannot be confirmed are reported as problems. They are never
"fixed" by guessing a replacement.
"""

from __future__ import annotations

import json
import re
from typing import get_args, get_origin

from pydantic import BaseModel, ValidationError

from .context import HUNK_HEADER, render_ticket, split_diff
from .evidence import compute_profile
from .review import RunRecord
from .schemas import (
    WHOLE_CHANGE,
    Coverage,
    FailureKind,
    Finding,
    ModelReview,
    ProblemKind,
    ReviewFailure,
    ReviewInput,
    ReviewResult,
    RunSummary,
    Ticket,
    ValidationProblem,
)


class InvalidOutput(Exception):
    """The raw text is not a usable review (bad JSON or schema)."""


# ------------------------------------------------------------------ 1 + 2: parsing

_FENCE = re.compile(r"^```[a-zA-Z]*\s*\n(.*?)\n?```\s*$", re.DOTALL)
_BARE_KEY = re.compile(r"(?m)^(\s*)([A-Za-z_][A-Za-z0-9_]*)(\s*:)")


def parse_model_output(raw: str, done_reason: str | None = None) -> tuple[ModelReview, list[ValidationProblem]]:
    """Single-pass review output: parse and schema-validate (see `parse_json_output`)."""
    return parse_json_output(raw, ModelReview, done_reason)


def parse_json_output(raw: str, model: type[BaseModel], done_reason: str | None = None):
    """Parse and schema-validate against `model`. Returns (object, format warnings).

    Raises InvalidOutput with a human-readable reason otherwise.
    """
    warnings: list[ValidationProblem] = []
    text = raw.strip()
    if not text:
        raise InvalidOutput("The model returned an empty response." + _length_hint(done_reason))

    fenced = _FENCE.match(text)
    if fenced:  # tolerated, but visible: we asked for bare JSON
        text = fenced.group(1).strip()
        warnings.append(
            ValidationProblem(
                kind=ProblemKind.FORMAT_WARNING,
                message="The model wrapped its JSON in a Markdown code fence; it was unwrapped.",
            )
        )

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        # Some models write `verdict: "x"` instead of `"verdict": "x"`. Quoting a key that starts a line is
        # safe (a JSON string cannot contain a raw newline) and changes no value; anything else stays invalid.
        repaired = _BARE_KEY.sub(r'\1"\2"\3', text)
        try:
            data = json.loads(repaired)
        except json.JSONDecodeError:
            raise InvalidOutput(
                f"The response is not valid JSON ({exc.msg} at line {exc.lineno}, column {exc.colno})."
                + _length_hint(done_reason)
            ) from exc
        warnings.append(
            ValidationProblem(
                kind=ProblemKind.FORMAT_WARNING,
                message="The model wrote some field names without quotes; they were quoted.",
            )
        )

    try:
        return model.model_validate(data), warnings
    except ValidationError as exc:
        original = exc
        details = "; ".join(
            f"{'.'.join(str(p) for p in err['loc']) or '(root)'}: {err['msg']}"
            for err in exc.errors()[:5]
        )
        more = f" (+{exc.error_count() - 5} more)" if exc.error_count() > 5 else ""
        failure = InvalidOutput(f"The JSON does not match the review schema: {details}{more}")

    # One malformed finding should not cost the valid ones. Keep what validates, drop the rest VISIBLY.
    salvaged = _salvage(data, model)
    if salvaged is None:
        raise failure from original
    cleaned, dropped = salvaged
    try:
        obj = model.model_validate(cleaned)
    except ValidationError as exc:
        raise failure from exc
    warnings += [ValidationProblem(kind=ProblemKind.FORMAT_WARNING, message=f"{DROPPED} {note}") for note in dropped]
    return obj, warnings


DROPPED = "Dropped"  # messages that start with this describe model output we discarded (it counts as lost coverage)


def _item_model(field) -> type[BaseModel] | None:
    """For a field typed list[SomeModel], SomeModel; otherwise None."""
    args = get_args(field.annotation)
    if get_origin(field.annotation) is list and len(args) == 1 and isinstance(args[0], type) and issubclass(args[0], BaseModel):
        return args[0]
    return None


def _salvage(data, model: type[BaseModel]) -> tuple[dict, list[str]] | None:
    """Validate list items one by one. Returns (data with only the valid items, notes on dropped ones),
    or None when nothing can be saved (not an object, nothing was wrong with the items, or no item is valid)."""
    if not isinstance(data, dict):
        return None
    cleaned = dict(data)
    dropped: list[str] = []
    kept_any = False
    for name, field in model.model_fields.items():
        item_model = _item_model(field)
        items = data.get(name)
        if item_model is None or not isinstance(items, list):
            continue
        valid = []
        for i, item in enumerate(items):
            try:
                item_model.model_validate(item)
            except ValidationError as exc:
                err = exc.errors()[0]
                label = (item.get("title") or item.get("number") or "") if isinstance(item, dict) else ""
                where = ".".join(str(p) for p in err["loc"])
                dropped.append(f"{name}[{i}]{' (' + str(label)[:60] + ')' if label else ''}: {where}: {err['msg']}")
            else:
                valid.append(item)
        cleaned[name] = valid
        kept_any = kept_any or bool(valid)
    if not dropped or not kept_any:
        return None  # either the problem is not in the items, or every item was malformed: that is a failure
    return cleaned, dropped


def _length_hint(done_reason: str | None) -> str:
    if done_reason == "length":
        return " The model stopped because it reached its token limit, so the output was cut off."
    return ""


# ------------------------------------------------------------------ duplicates


def _norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def deduplicate(findings: list[Finding]) -> tuple[list[Finding], int]:
    """Drop repeated reports of one problem (same place+category, or same title).

    This is a cheap syntactic check. Duplicates that are worded differently are
    handled by the semantic matching used in the evaluation (Stage 5).
    """
    seen_place: set[tuple] = set()
    seen_title: set[tuple] = set()
    kept: list[Finding] = []
    for f in findings:
        place = (f.file, f.line, f.category)
        title = (f.file, f.category, _norm_title(f.title))
        if place in seen_place or title in seen_title:
            continue
        seen_place.add(place)
        seen_title.add(title)
        kept.append(f)
    return kept, len(findings) - len(kept)


# ------------------------------------------------------------------ 3: grounding


def _squash(text: str) -> str:
    """Collapse whitespace so indentation differences do not hide a real quote."""
    return " ".join(text.split())


def _index_diff(diff: str) -> tuple[dict[str, dict[int, str]], list[str]]:
    """Map file -> {new line number: text} for lines the diff shows (added + context).

    Also returns every diff line's text (removed lines too) for quote searching.
    """
    lines_by_file: dict[str, dict[int, str]] = {}
    all_text: list[str] = []
    for file_diff in split_diff(diff):
        shown: dict[int, str] = lines_by_file.setdefault(file_diff.path, {})
        new_no: int | None = None
        for line in file_diff.text.splitlines():
            match = HUNK_HEADER.match(line)
            if match:
                new_no = int(match.group(1))
            elif new_no is None or line.startswith("\\"):
                continue  # file header, or "\ No newline at end of file"
            elif line.startswith("-"):
                all_text.append(line[1:])
            else:
                content = line[1:] if line[:1] in "+ " else line
                shown[new_no] = content
                all_text.append(content)
                new_no += 1
    return lines_by_file, all_text


class Grounder:
    """Checks cited files, lines and quotes against the input a model was given."""

    def __init__(self, ticket: Ticket | None, review_input: ReviewInput):
        self.diff_lines, diff_text = _index_diff(review_input.diff)
        self.supporting = {s.path: s.content for s in review_input.supporting_files}
        self.related: dict[str, list[tuple[int, int]]] = {}  # file -> line ranges of the related snippets shown
        for s in review_input.related_code:
            self.related.setdefault(s.path, []).append((s.start_line, s.end_line))
        code = _squash("\n".join(diff_text + list(self.supporting.values()) + [s.text for s in review_input.related_code]))
        # Quotes may come from the raw ticket fields or from the rendered text the model was
        # shown (which numbers the criteria: "1. ..."), so accept both.
        ticket_text = (
            _squash("\n".join([ticket.key, ticket.title, ticket.description, *ticket.acceptance_criteria,
                               render_ticket(ticket, [])]))
            if ticket else None
        )
        pr_text = _squash(f"{review_input.pr.title}\n{review_input.pr.description}")
        rules_text = _squash(review_input.rules) if review_input.rules else None
        self._haystacks = {"code": code, "ticket": ticket_text, "pr_description": pr_text, "rules": rules_text}

    def location(self, file: str | None, line: int | None) -> tuple[ProblemKind, str] | None:
        if file is None or file == WHOLE_CHANGE:
            return None  # a statement about the change as a whole has no file to check
        if file in self.supporting:
            total = len(self.supporting[file].splitlines())
            if line is not None and line > total:
                return ProblemKind.LINE_OUT_OF_RANGE, f"{file} has {total} lines, but line {line} is cited."
        elif file in self.diff_lines:
            if line is not None and line not in self.diff_lines[file] and not self._in_related(file, line):
                return ProblemKind.LINE_NOT_IN_DIFF, f"Line {line} of {file} is not a line shown in the diff."
        elif file in self.related:
            if line is not None and not self._in_related(file, line):
                return ProblemKind.LINE_OUT_OF_RANGE, f"Line {line} of {file} is outside the related code that was shown."
        else:
            known = sorted(set(self.diff_lines) | set(self.supporting) | set(self.related))
            return ProblemKind.UNKNOWN_FILE, f"{file} is not in the provided input (known files: {', '.join(known) or 'none'})."
        return None

    def _in_related(self, file: str, line: int) -> bool:
        return any(a <= line <= b for a, b in self.related.get(file, []))

    def quote(self, ev) -> tuple[ProblemKind, str] | None:
        haystack = self._haystacks[ev.source]
        if haystack is None:
            if ev.source == "rules":
                return ProblemKind.QUOTE_NOT_FOUND, f"Evidence cites the team rules, but no team rules were provided: \"{ev.quote}\""
            return ProblemKind.QUOTE_NOT_FOUND, f"Evidence cites the ticket, but no ticket was provided: \"{ev.quote}\""
        if _squash(ev.quote) not in haystack:
            where = "the team rules" if ev.source == "rules" else "the input"
            return ProblemKind.QUOTE_NOT_FOUND, f"Quoted {ev.source} text was not found in {where}: \"{ev.quote}\""
        return None


def check_grounding(
    findings: list[Finding], ticket: Ticket | None, review_input: ReviewInput
) -> list[ValidationProblem]:
    grounder = Grounder(ticket, review_input)
    problems: list[ValidationProblem] = []
    for i, f in enumerate(findings):
        issues = [grounder.location(f.file, f.line), *[grounder.quote(ev) for ev in f.evidence]]
        problems += [ValidationProblem(finding_index=i, kind=k, message=m) for k, m in filter(None, issues)]
    return problems


def check_criteria(checks, ticket: Ticket | None, review_input: ReviewInput) -> list[ValidationProblem]:
    """Same checks for the rows of the requirements checklist, plus: met / not_met need evidence."""
    grounder = Grounder(ticket, review_input)
    problems: list[ValidationProblem] = []
    for i, c in enumerate(checks):
        issues = [grounder.location(c.file, c.line), *[grounder.quote(ev) for ev in c.evidence]]
        if c.verdict in ("met", "not_met") and not any(ev.source == "code" for ev in c.evidence):
            issues.append((ProblemKind.UNSUPPORTED_VERDICT,
                           f"Criterion {c.number} is marked {c.verdict} without any quote from the code."))
        problems += [ValidationProblem(criterion_index=i, kind=k, message=m) for k, m in filter(None, issues)]
    return problems


# ------------------------------------------------------------------ putting it together


def finalize_review(
    record: RunRecord, ticket: Ticket | None, review_input: ReviewInput
) -> ReviewResult:
    """Build the final ReviewResult from one run record."""
    if record.pipeline == "multi":
        from .pipeline import assemble_multi  # imported here: pipeline builds on this module

        return assemble_multi(record, ticket, review_input)
    run = RunSummary(
        revision=record.revision,
        case_id=record.case_id,
        created_at=record.created_at,
        prompt_version=record.prompt_version,
        model=record.settings.model,
        host=record.settings.host,
        duration_s=record.duration_s,
        prompt_tokens=record.prompt_tokens,
        completion_tokens=record.completion_tokens,
        ticket=f"{ticket.key}: {ticket.title}" if ticket else None,
    )
    common = {"run": run, "coverage": record.coverage, "missing_inputs": record.missing_inputs,
              "change_profile": compute_profile(review_input)}

    if record.error is not None:  # the model call itself failed (Stage 3)
        return ReviewResult(status="failed", error=record.error, **common)

    try:
        review, problems = parse_model_output(record.raw_response or "", record.done_reason)
    except InvalidOutput as exc:
        return ReviewResult(
            status="failed",
            error=ReviewFailure(kind=FailureKind.INVALID_OUTPUT, message=str(exc)),
            **common,
        )

    findings, removed = deduplicate(review.findings)
    # Output the parser had to discard is lost coverage: say so, instead of letting it look like "nothing found".
    lost = [p.message for p in problems if p.message.startswith(DROPPED)]
    if lost:
        common["coverage"] = Coverage(
            complete=False, omitted=[*record.coverage.omitted, *[f"model output: {m}" for m in lost]])
        problems = [p for p in problems if not p.message.startswith(DROPPED)]
    problems = problems + check_grounding(findings, ticket, review_input)
    return ReviewResult(
        status="completed",
        findings=findings,
        limitations=review.limitations,
        problems=problems,
        duplicates_removed=removed,
        **common,
    )
