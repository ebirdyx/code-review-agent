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

    source: Literal["code", "ticket", "pr_description"]
    quote: str = Field(min_length=1, description="Verbatim text from the source")


class Finding(StrictModel):
    category: Category
    severity: Severity
    file: str = Field(min_length=1)
    line: int | None = Field(default=None, ge=1, description="Line in the new file version")
    title: str = Field(min_length=1, max_length=120)
    explanation: str = Field(min_length=1, description="What behaves wrongly, and why")
    evidence: list[Evidence] = Field(min_length=1)


class ModelReview(StrictModel):
    """What we ask the *model* to produce. Deliberately small.

    An empty `findings` list is valid: "I looked and found nothing".
    `limitations` is where the model says what it could not judge
    (for example, a requirement that is not specified).
    """

    findings: list[Finding] = Field(default_factory=list)
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


class ValidationProblem(StrictModel):
    """Something our checks could not confirm. The finding is kept, but flagged.

    `finding_index` is the position in the final `findings` list (None = whole output).
    """

    finding_index: int | None = None
    kind: ProblemKind
    message: str = Field(min_length=1)


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
