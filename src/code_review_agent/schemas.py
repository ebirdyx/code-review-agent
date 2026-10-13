"""Data contracts: what the reviewer receives and what it produces.

Everything is a Pydantic model. Pydantic gives us two things from one definition:
validation of JSON data, and a JSON Schema that we can later show to the model.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    """Base class: unknown fields are errors, so typos in JSON files are caught."""

    model_config = ConfigDict(extra="forbid")


# --------------------------------------------------------------------------- inputs


class Ticket(StrictModel):
    """The requirement: a Jira ticket (read from a local file for now)."""

    key: str = Field(pattern=r"^[A-Z][A-Z0-9]+-\d+$", examples=["SHOP-42"])
    title: str = Field(min_length=1)
    description: str = ""
    # May legitimately be empty: some tickets have no acceptance criteria.
    # A missing criterion must be visible to the reviewer, never invented.
    acceptance_criteria: list[str] = Field(default_factory=list)


class PullRequestMetadata(StrictModel):
    title: str = Field(min_length=1)
    description: str = ""
    # Filled by the GitHub connector; absent for local examples.
    base_sha: str | None = None
    head_sha: str | None = None
    repository: str | None = None  # "owner/name"
    number: int | None = None
    url: str | None = None


class SupportingFile(StrictModel):
    """Extra source code (not part of the diff) that helps understand the change."""

    path: str = Field(min_length=1)
    content: str


class ReviewInput(StrictModel):
    """Everything about the code change itself. The ticket is kept separate."""

    pr: PullRequestMetadata
    diff: str = Field(min_length=1, description="Unified diff of the change")
    supporting_files: list[SupportingFile] = Field(default_factory=list)
    # Things a connector could NOT retrieve (unavailable patches, files not fetched...).
    # They are shown to the model and reported as partial coverage, never dropped silently.
    input_notes: list[str] = Field(default_factory=list)
    # Full source of changed files, for the static-analysis tools only (NOT shown to the model).
    analysis_files: list[SupportingFile] = Field(default_factory=list)
    # Team coding rules (from the BASE branch, so a PR cannot rewrite its own rules).
    rules: str | None = None
    rules_source: str | None = None  # where the rules came from, for the report


# -------------------------------------------------------------------------- findings


class Category(StrEnum):
    LOGIC_DEFECT = "logic_defect"
    REQUIREMENT_MISMATCH = "requirement_mismatch"
    BOUNDARY_CONDITION = "boundary_condition"
    ERROR_HANDLING = "error_handling"
    SECURITY = "security"
    MAINTAINABILITY = "maintainability"


class Severity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class Evidence(StrictModel):
    """One piece of support for a finding: a quote and where it came from."""

    source: Literal["code", "ticket", "pr_description", "rules"]
    quote: str = Field(min_length=1, description="Verbatim text from the source")


class Finding(StrictModel):
    category: Category
    severity: Severity
    file: str = Field(min_length=1)
    line: int | None = Field(default=None, ge=1, description="Line in the new file version")
    title: str = Field(min_length=1, max_length=120)
    explanation: str = Field(min_length=1, description="What behaves wrongly, and why")
    evidence: list[Evidence] = Field(min_length=1)
    # Filled in by our pipeline, never by the model (hidden from the schema the model sees).
    found_by: list[str] = Field(default_factory=list)  # which passes or tools reported it
    verification: Literal["supported", "uncertain"] | None = None  # verifier's opinion, if it ran
    verification_note: str = ""
    source: Literal["llm", "tool"] = "llm"  # "tool": backed by a static-analysis finding (not dismissable)


INTERNAL_FINDING_FIELDS = ("found_by", "verification", "verification_note", "source")
WHOLE_CHANGE = "(whole change)"  # `file` value for a finding about the change as a whole


def public_schema(model: type[BaseModel], allow_rules: bool = False) -> dict:
    """JSON Schema shown to the model.

    Our internal bookkeeping fields are removed from Finding, and the evidence source "rules" is
    only offered to the pass that checks the team rules (so other prompts stay exactly as before).
    """
    schema = model.model_json_schema()
    defs = schema.get("$defs", {})
    finding = defs.get("Finding")
    if finding:
        for name in INTERNAL_FINDING_FIELDS:
            finding.get("properties", {}).pop(name, None)
    source = defs.get("Evidence", {}).get("properties", {}).get("source")
    if source and not allow_rules and "rules" in source.get("enum", []):
        source["enum"] = [v for v in source["enum"] if v != "rules"]
    return schema


class ModelReview(StrictModel):
    """What we ask the *model* to produce. Deliberately small.

    An empty `findings` list is valid: "I looked and found nothing".
    `limitations` is where the model says what it could not judge
    (for example, a requirement that is not specified).
    """

    findings: list[Finding] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


# ------------------------------------------------- what the other specialist passes produce

Verdict = Literal["met", "not_met", "cannot_determine"]


class CriterionVerdict(StrictModel):
    """The compliance pass's verdict on ONE numbered acceptance criterion."""

    number: int = Field(ge=1, description="The criterion's number in the ticket's list")
    verdict: Verdict
    explanation: str = Field(min_length=1)
    evidence: list[Evidence] = Field(default_factory=list)
    file: str | None = Field(default=None, description="File where the code concerned is, if any")
    line: int | None = Field(default=None, ge=1)
    severity: Severity = Severity.MEDIUM  # how serious it is if the criterion is NOT met


class ComplianceReview(StrictModel):
    """Output of the ticket-compliance pass."""

    criteria: list[CriterionVerdict] = Field(default_factory=list)
    scope_findings: list[Finding] = Field(default_factory=list)  # changes nobody asked for
    limitations: list[str] = Field(default_factory=list)


class FindingVerdict(StrictModel):
    index: int = Field(ge=1, description="The candidate finding's number")
    verdict: Literal["supported", "unsupported", "uncertain"]
    reason: str = Field(min_length=1)


class VerifyReview(StrictModel):
    """Output of the verification pass: a second look at every candidate finding."""

    verdicts: list[FindingVerdict] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- result


class FailureKind(StrEnum):
    INPUT_ERROR = "input_error"
    MODEL_UNAVAILABLE = "model_unavailable"
    CONNECTION_ERROR = "connection_error"
    AUTH_ERROR = "auth_error"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    INVALID_OUTPUT = "invalid_output"


class ReviewFailure(StrictModel):
    kind: FailureKind
    message: str = Field(min_length=1)


class Coverage(StrictModel):
    """How much of the input the model actually saw."""

    complete: bool
    omitted: list[str] = Field(default_factory=list)


class ProblemKind(StrEnum):
    UNKNOWN_FILE = "unknown_file"  # file is neither in the diff nor in supporting code
    LINE_NOT_IN_DIFF = "line_not_in_diff"  # line number is not a line the diff shows
    LINE_OUT_OF_RANGE = "line_out_of_range"  # line beyond the end of a supporting file
    QUOTE_NOT_FOUND = "quote_not_found"  # evidence quote is not in its claimed source
    FORMAT_WARNING = "format_warning"  # output was usable but not exactly as requested
    UNSUPPORTED_VERDICT = "unsupported_verdict"  # a met / not_met verdict without evidence
    MISSING_VERDICT = "missing_verdict"  # the model skipped a criterion; we marked it cannot_determine
    UNKNOWN_CRITERION = "unknown_criterion"  # a verdict for a criterion number that does not exist
    INCONSISTENT_VERDICT = "inconsistent_verdict"  # a criterion marked met, yet a finding reports a problem in the code it cites


class ValidationProblem(StrictModel):
    """Something our checks could not confirm. The finding is kept, but flagged.

    `finding_index` is the position in the final `findings` list (None = whole output);
    `criterion_index` (0-based) is set instead when the problem concerns a checklist row.
    """

    finding_index: int | None = None
    criterion_index: int | None = None
    kind: ProblemKind
    message: str = Field(min_length=1)


class CriterionCheck(StrictModel):
    """One row of the requirements checklist: an acceptance criterion and what was found."""

    number: int = Field(ge=1)
    text: str  # taken from the ticket, never from the model
    verdict: Verdict
    explanation: str
    evidence: list[Evidence] = Field(default_factory=list)
    file: str | None = None
    line: int | None = None
    severity: Severity = Severity.MEDIUM


class DismissedFinding(StrictModel):
    """A candidate finding the verifier judged unsupported. Kept visible, never silently dropped."""

    finding: Finding
    reason: str


class PassSummary(StrictModel):
    """What one specialist pass did (shown in the report and the UI)."""

    name: str
    status: Literal["ok", "failed", "skipped"]
    model: str = ""
    duration_s: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    findings: int = 0  # candidates this pass contributed
    message: str = ""  # why it failed or was skipped


class ToolFinding(StrictModel):
    """One warning from a static-analysis tool (Ruff, Bandit...). Deterministic, not from the model."""

    tool: str
    rule: str  # e.g. "S608", "B006"
    file: str
    line: int = Field(ge=1)
    message: str
    severity: Severity
    category: Category
    code_line: str = ""  # the text of that line, used as evidence
    on_changed_line: bool = False  # True when the PR added or changed this very line


class ToolRun(StrictModel):
    """What one tool did on this review (shown in the report)."""

    name: str
    version: str | None = None
    status: Literal["ok", "failed", "skipped"]
    message: str = ""  # why it failed or was skipped
    files_checked: int = 0
    total_findings: int = 0
    findings_on_changed_lines: int = 0
    duration_s: float | None = None


class ChangeProfile(StrictModel):
    """Facts about the size and nature of the change, computed without any model."""

    files_changed: int = 0
    lines_added: int = 0
    lines_removed: int = 0
    languages: dict[str, int] = Field(default_factory=dict)  # file extension -> number of files
    source_files: int = 0
    test_files: int = 0
    hints: list[str] = Field(default_factory=list)  # things a reviewer should know first


class ReviewedRevision(StrictModel):
    """The exact code revision a review looked at (pull requests only)."""

    repository: str | None = None
    pr_number: int | None = None
    url: str | None = None
    base_sha: str | None = None
    head_sha: str


class RunSummary(StrictModel):
    """Who produced this result, and how (the full details are in run.json)."""

    revision: ReviewedRevision | None = None
    case_id: str
    created_at: str
    prompt_version: str
    model: str
    host: str
    duration_s: float | None = None
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    ticket: str | None = None  # "KEY: title" of the ticket whose requirements were used, or None


class ReviewResult(StrictModel):
    """What our *program* saves for every review attempt.

    `status` separates two situations that must never be confused:
      - "completed": the review ran. `findings` may be empty (nothing found).
      - "failed":    the review did not run properly. `error` explains why,
                     and `findings` is empty because nothing can be concluded.

    `problems` are checks we could not confirm (locations, quotes). They say
    nothing about whether a finding is TRUE: only a human can judge that.
    """

    status: Literal["completed", "failed"]
    findings: list[Finding] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)  # stated by the model
    error: ReviewFailure | None = None
    run: RunSummary | None = None
    coverage: Coverage | None = None
    missing_inputs: list[str] = Field(default_factory=list)  # noted by the context builder
    problems: list[ValidationProblem] = Field(default_factory=list)
    duplicates_removed: int = 0
    # Multi-pass pipeline only (empty for the single-pass pipeline):
    pipeline: str = "single"
    passes: list[PassSummary] = Field(default_factory=list)
    criteria: list[CriterionCheck] = Field(default_factory=list)  # requirements checklist
    dismissed: list[DismissedFinding] = Field(default_factory=list)  # judged unsupported by the verifier
    tools: list[ToolRun] = Field(default_factory=list)  # static-analysis tools that ran (or why not)
    change_profile: ChangeProfile | None = None

    @model_validator(mode="after")
    def _status_matches_content(self) -> Self:
        if self.status == "failed":
            if self.error is None:
                raise ValueError("a failed review must carry an error")
            if self.findings:
                raise ValueError("a failed review cannot carry findings")
        elif self.error is not None:
            raise ValueError("a completed review cannot carry an error")
        return self


# ------------------------------------------------------------------------- triage
# The human reviewer's decision on each finding. Saved next to the run as triage.json.


class TriageDecision(StrictModel):
    finding_index: int = Field(ge=0)
    decision: Literal["accepted", "dismissed"]
    note: str = Field(default="", max_length=1000)


class TriageFile(StrictModel):
    reviewer: str = Field(default="", max_length=100)
    updated_at: str = ""
    decisions: list[TriageDecision] = Field(default_factory=list)

    @model_validator(mode="after")
    def _one_decision_per_finding(self) -> Self:
        indices = [d.finding_index for d in self.decisions]
        if len(indices) != len(set(indices)):
            raise ValueError("two decisions for the same finding")
        return self


# ---------------------------------------------------------------- expected answers
# Written by humans, stored OUTSIDE the examples folder, never shown to the model.


class ExpectedFinding(StrictModel):
    category: Category
    file: str
    line: int | None = None
    # Text that must appear on `line` of the new file. A test checks it, so the
    # ground-truth line number cannot silently drift away from the intended code.
    code_anchor: str | None = None
    description: str = Field(min_length=1, description="The defect, in plain words")


class ExpectedReview(StrictModel):
    case_id: str
    group: str = ""  # benchmark group: boundary, logic, requirement, error_handling, ...
    expected_findings: list[ExpectedFinding] = Field(default_factory=list)
    # Claims a good review must NOT make (guards against hallucinated defects).
    must_not_report: list[str] = Field(default_factory=list)
    # Things a good review should say it could not judge.
    expected_limitations: list[str] = Field(default_factory=list)
    notes: str = ""
