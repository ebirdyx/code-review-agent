"""Compare several evaluation runs (configurations) side by side, reproducibly.

`eval-run` writes `eval-config.json` next to its run folders: the exact configuration (pipeline, prompt set, tools,
context, verifier, model) and an index of every run. `eval-compare` reads one or more such folders, scores every run
with the same code as `eval-score`, and prints one table per question: which configuration found more, missed more,
raised more false alarms, cost more, and how much the result moves between repeats.

Where labels come from is stated for every configuration. If no label file exists, labels are SUGGESTED from the
location alone (the same rule as `eval-template`) and the table says so: that matches a finding to a defect by file and
nearby line, not by meaning, so it can under- or over-count. Only labels confirmed by a named person are final.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from ..schemas import StrictModel
from .scoring import (
    NEAR_LINES,
    EvaluationError,
    LabelFile,
    LoadedRun,
    RunScore,
    Totals,
    discover_runs,
    score_run,
    suggest_labels,
    totals,
)

CONFIG_NAME = "eval-config.json"


class EvalRunEntry(StrictModel):
    case_id: str
    rep: int
    folder: str  # run folder name inside the evaluation folder
    status: Literal["completed", "failed", "not_run"]


class EvalConfig(StrictModel):
    """Everything that defines one evaluation configuration. Written by `eval-run`."""

    label: str
    created_at: str
    split: str  # "dev", "heldout", "all", or "custom" (cases taken from --cases-dir)
    cases: list[str]
    repeat: int
    pipeline: str
    prompt_version: str
    passes: list[str] | None = None
    verify: bool
    tools: list[str]
    context: bool
    ruff_select: str | None = None
    model: str
    host: str
    profile: str | None = None
    temperature: float | None = None
    seed: int | None = None
    agent_commit: str | None = None
    notes: list[str] = []  # how this configuration was produced, when that matters for reading the numbers
    runs: list[EvalRunEntry] = []


def auto_label(pipeline: str, verify: bool, tools: list[str], context: bool) -> str:
    """A short name made from what differs from the full default pipeline."""
    if pipeline == "single":
        return "single-pass"
    parts = ["multi"]
    if not tools:
        parts.append("no-tools")
    if not context:
        parts.append("no-context")
    if not verify:
        parts.append("no-verify")
    return "-".join(parts)


def current_commit() -> str | None:
    """Short git hash of the agent's own code, or None (installed package, no git).

    "+uncommitted" is appended when tracked files differ from that commit: the hash alone would not reproduce the run.
    """
    here = Path(__file__).parent
    try:
        done = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=here, capture_output=True, text=True, timeout=5)
        out = done.stdout.strip()
        if done.returncode != 0 or not out:
            return None
        status = subprocess.run(["git", "status", "--porcelain", "--untracked-files=no"], cwd=here,
                                capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    return out + "+uncommitted" if status.returncode == 0 and status.stdout.strip() else out


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def save_config(runs_dir: Path, config: EvalConfig) -> None:
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / CONFIG_NAME).write_text(config.model_dump_json(indent=2), encoding="utf-8")


def load_config(runs_dir: Path) -> EvalConfig | None:
    path = runs_dir / CONFIG_NAME
    if not path.exists():
        return None
    return EvalConfig.model_validate_json(path.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------- scoring one configuration


@dataclass
class ConfigResult:
    label: str
    config: EvalConfig | None
    runs: list[LoadedRun]
    scores: list[RunScore]
    label_basis: str
    skipped: list[str] = field(default_factory=list)  # runs that could not be loaded, with the reason
    rep_of: dict[str, int] = field(default_factory=dict)  # run folder name -> repetition number


def _labels_for(runs_dir: Path, labels_path: Path | None) -> tuple[LabelFile | None, str]:
    """Labels to use for a folder: an explicit file, else `<folder>/labels.json`, else none (suggest from location)."""
    path = labels_path if labels_path else runs_dir / "labels.json"
    if path.exists():
        return LabelFile.model_validate_json(path.read_text(encoding="utf-8")), str(path)
    return None, ""


def load_configuration(runs_dir: Path, expected_dir: Path, labels_path: Path | None = None) -> ConfigResult:
    config = load_config(runs_dir)
    label = config.label if config else runs_dir.name
    runs, skipped = discover_runs(runs_dir, expected_dir)
    label_file, label_source = _labels_for(runs_dir, labels_path)
    scores: list[RunScore] = []
    suggested = confirmed = 0
    for run in runs:
        known = label_file.labels.get(run.name) if label_file else None
        if known is not None:
            labels = known
            confirmed += 1
        else:
            labels = suggest_labels(run) if run.result.status == "completed" else None
            suggested += 1
        scores.append(score_run(run, labels))
    if label_file and confirmed and not suggested and label_file.reviewed_by.strip():
        basis = f"labels confirmed by {label_file.reviewed_by.strip()} ({label_source})"
    elif label_file and confirmed:
        basis = f"{confirmed} run(s) from a PROVISIONAL label file ({label_source})" + (
            f", {suggested} suggested from location" if suggested else "")
    else:
        basis = "suggested from location only (PROVISIONAL: a finding counts as a defect when it is in the same file near the expected line)"
    rep_of = {e.folder: e.rep for e in config.runs} if config else {}
    return ConfigResult(label, config, runs, scores, basis, skipped, rep_of)


# --------------------------------------------------------------------------- statistics


def per_repeat_totals(result: ConfigResult) -> list[Totals]:
    """Totals of each repetition separately, to show how much the result moves between repeats."""
    groups: dict[int, list[RunScore]] = {}
    for s in result.scores:
        groups.setdefault(result.rep_of.get(s.name, 1), []).append(s)
    return [totals(groups[k]) for k in sorted(groups)]


def _num(x: float | None) -> str:
    return "n/a" if x is None else f"{x:.2f}"


def _range(values: list[float | None]) -> str:
    present = [v for v in values if v is not None]
    if len(present) < 2:
        return ""
    return f"{min(present):.2f}-{max(present):.2f}"


def _loc(score_list: list[RunScore], attr: str, tp: int) -> str:
    return "n/a" if tp == 0 else f"{sum(getattr(s, attr) for s in score_list)}/{tp}"


def render_comparison(results: list[ConfigResult], expected_dir: Path) -> str:
    out = ["# Comparison of evaluation configurations", ""]
    provisional = [r for r in results if "confirmed by" not in r.label_basis]
    if provisional:
        out += ["> **PROVISIONAL.** Labels of: " + ", ".join(r.label for r in provisional)
                + " are not confirmed by a named human reviewer. Do not report these numbers as final.", ""]

    # --- configurations
    out += ["## Configurations", "",
            "| Label | Pipeline | Prompt | Passes | Tools | Context | Verifier | Model | Repeats | Runs | Agent commit |",
            "|---|---|---|---|---|---|---|---|--:|--:|---|"]
    for r in results:
        c = r.config
        if c is None:
            out.append(f"| {r.label} | (no {CONFIG_NAME}) | | | | | | | | {len(r.runs)} | |")
            continue
        passes = ",".join(c.passes) if c.passes else ("default" if c.pipeline == "multi" else "-")
        tools = ",".join(c.tools) if c.tools else "off"
        out.append(f"| {r.label} | {c.pipeline} | {c.prompt_version} | {passes} | {tools} | {'on' if c.context else 'off'} | "
                   f"{'on' if c.verify else 'off'} | {c.model} | {c.repeat} | {len(r.runs)} | {c.agent_commit or 'n/a'} |")
    notes = [(r.label, n) for r in results if r.config for n in r.config.notes]
    if notes:
        out += ["", "Notes on how these configurations were produced:", ""] + [f"- **{label}**: {note}" for label, note in notes]
    differing = _differences([r.config for r in results if r.config])
    out += ["", ("Configurations differ in: " + ", ".join(differing) + ".") if differing
            else "The configurations are identical in every recorded setting (only the runs differ).", ""]

    # --- results
    out += ["## Results", "",
            "| Label | Runs (failed) | TP | FP | FN | Precision | Recall | F1 | Recall over repeats | Extra | Dup | Exact line | Mean model s | Tokens in |",
            "|---|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|--:|"]
    for r in results:
        t = totals(r.scores)
        reps = per_repeat_totals(r)
        done = [s for s in r.scores if not s.failed and s.model_s is not None]
        mean_s = f"{sum(s.model_s for s in done) / len(done):.1f}" if done else "n/a"
        out.append(f"| {r.label} | {t.runs} ({t.failed}) | {t.tp} | {t.fp} | {t.fn} | {_num(t.precision)} | {_num(t.recall)} | "
                   f"{_num(t.f1)} | {_range([x.recall for x in reps]) or '-'} | {t.extra} | {t.duplicate} | "
                   f"{_loc(r.scores, 'loc_exact', t.tp)} | {mean_s} | {sum(s.tokens_in for s in r.scores)} |")
    out += [""]

    # --- per case
    case_ids = sorted({s.case_id for r in results for s in r.scores})
    expected_count = {run.record.case_id: len(run.expected.expected_findings) for r in results for run in r.runs}
    out += ["## Per case", "",
            "Defects found out of those possible (summed over repeats), and false positives. `-` = case not run in that configuration.", "",
            "| Case | Expected | " + " | ".join(r.label for r in results) + " |",
            "|---|--:|" + "---|" * len(results)]
    for case_id in case_ids:
        cells = []
        for r in results:
            rows = [s for s in r.scores if s.case_id == case_id]
            if not rows:
                cells.append("-")
                continue
            exp = expected_count.get(case_id, 0)
            tp, fp = sum(s.tp for s in rows), sum(s.fp for s in rows)
            found = f"{tp}/{exp * len(rows)} found, " if exp else ""
            failed = f", {sum(s.failed for s in rows)} failed" if any(s.failed for s in rows) else ""
            cells.append(f"{found}{fp} FP{failed}")
        out.append(f"| {case_id} | {expected_count.get(case_id, 0)} | " + " | ".join(cells) + " |")

    # --- provenance and honesty
    out += ["", "## Where the labels come from", ""]
    out += [f"- **{r.label}**: {r.label_basis}" for r in results]
    skipped = [(r.label, note) for r in results for note in r.skipped]
    if skipped:
        out += ["", "## Runs not scored", ""] + [f"- {label}: {note}" for label, note in skipped]
    total_cases = len(case_ids)
    out += ["", f"_Sample: {total_cases} case(s). The model is not deterministic: compare the spread between repeats "
                f"(\"Recall over repeats\") with the differences between configurations before drawing a conclusion. "
                f"\"Within {NEAR_LINES} lines\" is how location is matched when labels are suggested._", ""]
    return "\n".join(out)


def _differences(configs: list[EvalConfig]) -> list[str]:
    if len(configs) < 2:
        return []
    names = ["pipeline", "prompt_version", "passes", "verify", "tools", "context", "model", "profile", "temperature", "seed"]
    return [n for n in names if len({str(getattr(c, n)) for c in configs}) > 1]


def compare(runs_dirs: list[Path], expected_dir: Path, labels_path: Path | None = None) -> tuple[str, list[ConfigResult]]:
    if not runs_dirs:
        raise EvaluationError("Give at least one evaluation folder.")
    results = []
    for d in runs_dirs:
        if not d.is_dir():
            raise EvaluationError(f"{d} is not a folder.")
        try:
            result = load_configuration(d, expected_dir, labels_path)
        except ValidationError as exc:
            raise EvaluationError(f"{d}: unreadable configuration or labels ({exc.error_count()} problem(s)).") from exc
        if not result.scores:
            raise EvaluationError(f"{d}: no scorable runs found (needs run folders with an expected answer in {expected_dir}).")
        results.append(result)
    labels = [r.label for r in results]
    if len(set(labels)) != len(labels):  # two folders with the same label would be indistinguishable in the tables
        for position, r in enumerate(results):
            if labels.count(r.label) > 1:
                r.label = f"{r.label} ({runs_dirs[position].name})"
    return render_comparison(results, expected_dir), results
