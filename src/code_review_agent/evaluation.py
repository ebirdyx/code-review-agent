"""Evaluation: label model findings by hand, then compute honest metrics.

Why labels instead of automatic matching: whether a finding describes "the same
defect" is a judgement about meaning. We do not ask another model to make it. The
tool only SUGGESTS labels from location; a person confirms them, and the
scoreboard says PROVISIONAL until a reviewer's name is recorded.

Labelling rubric (written before any result was seen):
  tp         The finding describes an expected defect (by meaning). A different
             category than expected is still a tp; category accuracy is reported
             separately. Each expected defect can be matched by ONE tp.
  duplicate  Another report of an already-matched defect. Counted once: it is
             neither a tp nor a fp.
  fp         A defect claim that is false, unsupported, or hedged about a rule the
             requirements do not specify ("if the business wants X, this is a bug").
             Any defect finding on a correct change is a fp.
  extra      A plausible, true observation that is not in the expected answers
             (e.g. a magic number). Reported, but NOT counted in precision.
  usefulness (optional) 0 = useless or misleading, 1 = true but marginal,
             2 = a reviewer would act on it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Self

from pydantic import Field, ValidationError, model_validator

from .loading import load_expected
from .review import RunRecord
from .schemas import ExpectedReview, ReviewResult, StrictModel

NEAR_LINES = 2  # "near" location tolerance for the location-accuracy metric


class EvaluationError(Exception):
    """Labels or run data are inconsistent. The message says what to fix."""


# ------------------------------------------------------------------------- split


class Split(StrictModel):
    note: str = ""
    dev: list[str]
    heldout: list[str]

    @model_validator(mode="after")
    def _disjoint(self) -> Self:
        overlap = set(self.dev) & set(self.heldout)
        if overlap:
            raise ValueError(f"cases in both dev and held-out: {sorted(overlap)}")
        return self

    def cases(self, name: str) -> list[str]:
        if name == "dev":
            return self.dev
        if name == "heldout":
            return self.heldout
        return self.dev + self.heldout  # "all"

    def split_of(self, case_id: str) -> str | None:
        return "dev" if case_id in self.dev else "heldout" if case_id in self.heldout else None


def load_split(path: Path) -> Split:
    return Split.model_validate_json(path.read_text(encoding="utf-8"))


def find_case_dir(case_id: str, roots: list[Path]) -> Path:
    for root in roots:
        if (root / case_id).is_dir():
            return root / case_id
    raise EvaluationError(f"case '{case_id}' not found in: {', '.join(str(r) for r in roots)}")


# ------------------------------------------------------------------------ labels


class Verdict(StrEnum):
    TP = "tp"
    FP = "fp"
    DUPLICATE = "duplicate"
    EXTRA = "extra"


class FindingLabel(StrictModel):
    finding_index: int = Field(ge=0)
    verdict: Verdict
    matches: int | None = Field(default=None, ge=0, description="index into expected_findings")
    usefulness: int | None = Field(default=None, ge=0, le=2)
    note: str = ""

    @model_validator(mode="after")
    def _matches_rules(self) -> Self:
        needs = self.verdict in (Verdict.TP, Verdict.DUPLICATE)
        if needs and self.matches is None:
            raise ValueError(f"a '{self.verdict}' label must say which expected defect it matches")
        if not needs and self.matches is not None:
            raise ValueError(f"a '{self.verdict}' label cannot have `matches`")
        return self


class LabelFile(StrictModel):
    reviewed_by: str = ""  # a HUMAN's name. Empty = provisional.
    draft_by: str = ""  # who produced the first draft of the labels, if not the reviewer
    labels: dict[str, list[FindingLabel]] = Field(default_factory=dict)  # key = run folder name


# -------------------------------------------------------------------- loading runs


@dataclass
class LoadedRun:
    name: str  # run folder name
    record: RunRecord
    result: ReviewResult
    expected: ExpectedReview


def discover_runs(runs_dir: Path, expected_dir: Path) -> tuple[list[LoadedRun], list[str]]:
    """Find run folders under runs_dir. Returns the runs and human-readable skip notes."""
    runs: list[LoadedRun] = []
    notes: list[str] = []
    for run_json in sorted(runs_dir.rglob("run.json")):
        folder = run_json.parent
        try:
            record = RunRecord.model_validate_json(run_json.read_text(encoding="utf-8"))
            result_path = folder / "result.json"
            if not result_path.exists():
                notes.append(f"{folder.name}: skipped (no result.json)")
                continue
            result = ReviewResult.model_validate_json(result_path.read_text(encoding="utf-8"))
            if record.settings.model.startswith("(none"):
                notes.append(f"{folder.name}: skipped (text validated from a file, no model ran)")
                continue
            expected_path = expected_dir / f"{record.case_id}.json"
            if not expected_path.exists():
                notes.append(f"{folder.name}: skipped (no expected answer for '{record.case_id}')")
                continue
            runs.append(LoadedRun(folder.name, record, result, load_expected(expected_path)))
        except (OSError, ValidationError) as exc:
            notes.append(f"{folder.name}: skipped ({exc.__class__.__name__}: {exc})")
    return runs, notes


# ----------------------------------------------------------------- suggest labels


def suggest_labels(run: LoadedRun) -> list[FindingLabel]:
    """Propose labels from location only. A human must confirm or correct them."""
    claimed: set[int] = set()
    labels: list[FindingLabel] = []
    for i, f in enumerate(run.result.findings):
        match = None
        for j, exp in enumerate(run.expected.expected_findings):
            same_file = f.file == exp.file
            near = f.line is None or exp.line is None or abs(f.line - exp.line) <= NEAR_LINES
            if same_file and near:
                match = j
                break
        if match is None:
            labels.append(FindingLabel(finding_index=i, verdict=Verdict.FP, note="auto-suggested: no expected defect nearby"))
        elif match in claimed:
            labels.append(FindingLabel(finding_index=i, verdict=Verdict.DUPLICATE, matches=match, note="auto-suggested"))
        else:
            claimed.add(match)
            labels.append(FindingLabel(finding_index=i, verdict=Verdict.TP, matches=match, note="auto-suggested: same file, nearby line"))
    return labels


def build_label_template(runs: list[LoadedRun], existing: LabelFile | None = None) -> LabelFile:
    """Keep existing labels; add suggestions for completed runs that have none yet."""
    out = existing.model_copy(deep=True) if existing else LabelFile()
    for run in runs:
        if run.name in out.labels or run.result.status != "completed":
            continue
        out.labels[run.name] = suggest_labels(run)
    return out


# ----------------------------------------------------------------------- scoring


@dataclass
class RunScore:
    name: str
    case_id: str
    group: str
    failed: bool
    tp: int = 0
    fp: int = 0
    fn: int = 0
    extra: int = 0
    duplicate: int = 0
    loc_exact: int = 0
    loc_near: int = 0
    cat_ok: int = 0
    usefulness: list[int] = field(default_factory=list)
    model_s: float | None = None
    wall_s: float | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    problems: int = 0  # validation problems (unconfirmed locations / quotes)


def score_run(run: LoadedRun, labels: list[FindingLabel] | None) -> RunScore:
    expected = run.expected.expected_findings
    score = RunScore(
        name=run.name, case_id=run.record.case_id, group=run.expected.group or "?",
        failed=run.result.status == "failed",
        model_s=run.record.duration_s, wall_s=run.record.wall_clock_s,
        tokens_in=run.record.prompt_tokens or 0, tokens_out=run.record.completion_tokens or 0,
        problems=len(run.result.problems),
    )
    if score.failed:  # a review that did not complete detected nothing
        score.fn = len(expected)
        return score

    findings = run.result.findings
    by_index = {lab.finding_index: lab for lab in (labels or [])}
    if len(by_index) != len(labels or []):
        raise EvaluationError(f"{run.name}: two labels for the same finding_index")
    missing = [i for i in range(len(findings)) if i not in by_index]
    if missing:
        raise EvaluationError(f"{run.name}: no label for finding(s) {missing}")
    extra_idx = [i for i in by_index if i >= len(findings)]
    if extra_idx:
        raise EvaluationError(f"{run.name}: labels for non-existent finding(s) {extra_idx}")

    matched: set[int] = set()
    for i, f in enumerate(findings):
        lab = by_index[i]
        if lab.matches is not None and lab.matches >= len(expected):
            raise EvaluationError(f"{run.name}: finding {i} matches expected #{lab.matches}, which does not exist")
        if lab.usefulness is not None:
            score.usefulness.append(lab.usefulness)
        if lab.verdict == Verdict.TP:
            if lab.matches in matched:
                raise EvaluationError(f"{run.name}: expected defect #{lab.matches} matched by two 'tp' labels; mark one 'duplicate'")
            matched.add(lab.matches)
            exp = expected[lab.matches]
            score.tp += 1
            score.cat_ok += f.category == exp.category
            if f.line is not None and exp.line is not None:
                score.loc_exact += f.line == exp.line
                score.loc_near += abs(f.line - exp.line) <= NEAR_LINES
        elif lab.verdict == Verdict.FP:
            score.fp += 1
        elif lab.verdict == Verdict.EXTRA:
            score.extra += 1
    for i, f in enumerate(findings):  # duplicates must point at a defect that has a tp
        lab = by_index[i]
        if lab.verdict == Verdict.DUPLICATE:
            if lab.matches not in matched:
                raise EvaluationError(f"{run.name}: finding {i} is a duplicate of expected #{lab.matches}, which has no 'tp' label")
            score.duplicate += 1
    score.fn = len(expected) - len(matched)
    return score


@dataclass
class Totals:
    runs: int
    failed: int
    tp: int
    fp: int
    fn: int
    extra: int
    duplicate: int
    precision: float | None
    recall: float | None
    f1: float | None


def totals(scores: list[RunScore]) -> Totals:
    tp, fp, fn = (sum(getattr(s, k) for s in scores) for k in ("tp", "fp", "fn"))
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    if precision is None or recall is None:
        f1 = None
    else:
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return Totals(
        runs=len(scores), failed=sum(s.failed for s in scores), tp=tp, fp=fp, fn=fn,
        extra=sum(s.extra for s in scores), duplicate=sum(s.duplicate for s in scores),
        precision=precision, recall=recall, f1=f1,
    )


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.2f}"


def _ratio(n: int, d: int) -> str:
    return "n/a" if d == 0 else f"{n}/{d} ({n / d:.0%})"


def render_scoreboard(scores: list[RunScore], labels: LabelFile, split_name: str, runs: list[LoadedRun]) -> str:
    t = totals(scores)
    provisional = not labels.reviewed_by.strip()
    out = [f"# Evaluation results: {split_name}", ""]
    if provisional:
        out += [
            "> **PROVISIONAL.** The labels have not been confirmed by a named human reviewer"
            + (f" (draft by: {labels.draft_by})" if labels.draft_by else "")
            + ". Do not report these numbers as final.",
            "",
        ]
    else:
        out += [f"Labels confirmed by: {labels.reviewed_by}", ""]

    models = sorted({f"{r.record.settings.model} @ {r.record.settings.host}" for r in runs})
    prompts = sorted({r.record.prompt_version for r in runs})
    out += [f"- Model(s): {', '.join(models)}", f"- Prompt version(s): {', '.join(prompts)}",
            f"- Runs scored: {t.runs} ({t.failed} failed)", ""]
    if len(models) > 1 or len(prompts) > 1:
        out += ["> Warning: results mix several models or prompt versions.", ""]

    out += ["## Per run", "", "| Run | Group | TP | FP | FN | Extra | Dup | Unconfirmed | Model time |",
            "|---|---|--:|--:|--:|--:|--:|--:|--:|"]
    for s in scores:
        mt = "n/a" if s.model_s is None else f"{s.model_s:.1f} s"
        flag = " (FAILED)" if s.failed else ""
        out.append(f"| {s.case_id}{flag} | {s.group} | {s.tp} | {s.fp} | {s.fn} | {s.extra} | {s.duplicate} | {s.problems} | {mt} |")

    out += ["", "## Overall", "",
            f"- True positives: {t.tp}, false positives: {t.fp}, false negatives: {t.fn}",
            f"- Precision: {_pct(t.precision)}   Recall: {_pct(t.recall)}   F1: {_pct(t.f1)}",
            f"- Plausible extras (not in precision): {t.extra}; duplicate reports merged: {t.duplicate}",
            f"- Location accuracy on true positives: exact {_ratio(sum(s.loc_exact for s in scores), t.tp)}, "
            f"within {NEAR_LINES} lines {_ratio(sum(s.loc_near for s in scores), t.tp)}",
            f"- Category matches expected on true positives: {_ratio(sum(s.cat_ok for s in scores), t.tp)}"]
    use = [u for s in scores for u in s.usefulness]
    out.append(f"- Usefulness (0-2), mean over {len(use)} rated finding(s): " + (f"{sum(use) / len(use):.2f}" if use else "not rated"))

    done = [s for s in scores if not s.failed and s.model_s is not None]
    if done:
        out.append(f"- Mean model time: {sum(s.model_s for s in done) / len(done):.1f} s; "
                   f"mean wall-clock: {sum((s.wall_s or 0) for s in done) / len(done):.1f} s")
    out.append(f"- Tokens: {sum(s.tokens_in for s in scores)} in / {sum(s.tokens_out for s in scores)} out")
    out.append("- Inference cost: not measured (Ollama Cloud returns no per-request cost).")

    groups = sorted({s.group for s in scores})
    out += ["", "## By group", "", "| Group | Runs | TP | FP | FN | Recall |", "|---|--:|--:|--:|--:|--:|"]
    for g in groups:
        gt = totals([s for s in scores if s.group == g])
        out.append(f"| {g} | {gt.runs} | {gt.tp} | {gt.fp} | {gt.fn} | {_pct(gt.recall)} |")

    out += ["", f"_Sample size: {len({s.case_id for s in scores})} cases, {t.runs} runs. "
            "With so few cases, a difference of one finding moves these numbers a lot: "
            "treat them as indicative, not statistically established._"]
    return "\n".join(out) + "\n"
