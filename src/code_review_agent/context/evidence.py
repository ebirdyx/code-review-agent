"""Evidence gathered WITHOUT any model: static analysis (Ruff, Bandit) and the change profile.

Why: a language model reads code and reasons about intent, but it can miss well-known
patterns and it can invent problems. Static analysers are the opposite: precise on known
patterns, blind to meaning. We run both and let them check each other:
  * a tool warning on a line the PR changed becomes a finding straight away (source "tool");
  * every tool warning is also handed to the model passes as a concrete LEAD to investigate;
  * warnings on lines the PR did not touch are counted but never reported as the PR's fault.

Safety: the tools only PARSE the code, they never run it. Files are copied into a fresh
temporary directory (paths validated against `..` tricks), the tools run without a shell, with
a timeout, with the project's configuration ignored, and with every secret-looking environment
variable removed.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path, PurePosixPath

from ..schemas import (
    Category,
    ChangeProfile,
    Evidence,
    Finding,
    ReviewInput,
    Severity,
    ToolFinding,
    ToolRun,
)
from .builder import HUNK_HEADER, split_diff

DEFAULT_TOOLS = ("ruff", "bandit")
# Bug-oriented Ruff rule families: pyflakes (F), syntax (E9), bugbear (B), blind except (BLE),
# pylint errors and warnings (PLE, PLW). Style families are left out on purpose: noise.
RUFF_SELECT = "F,E9,B,BLE,PLE,PLW"
MAX_FILES = 40
MAX_FILE_CHARS = 500_000
TOOL_TIMEOUT_S = 60
MAX_OUTPUT_CHARS = 5_000_000
MAX_LEADS_IN_PROMPT = 40
MAX_REPORTED_FINDINGS = 30  # tool warnings turned into findings per review


# ------------------------------------------------------------------------ the diff


def added_lines(diff: str) -> dict[str, set[int]]:
    """For each file, the line numbers (in the new file) that the diff ADDS."""
    result: dict[str, set[int]] = {}
    for file_diff in split_diff(diff):
        added = result.setdefault(file_diff.path, set())
        new_no: int | None = None
        for line in file_diff.text.splitlines():
            match = HUNK_HEADER.match(line)
            if match:
                new_no = int(match.group(1))
            elif new_no is None or line.startswith(("\\", "-")):
                continue
            else:
                if line.startswith("+"):
                    added.add(new_no)
                new_no += 1
    return result


def _safe_relative(path: str) -> str | None:
    """A relative POSIX path with no `..`, drive letters or backslashes, or None."""
    p = PurePosixPath(path)
    if not path or p.is_absolute() or ".." in p.parts or "\\" in path or ":" in path:
        return None
    return p.as_posix()


# ----------------------------------------------------------------------- the tools


def _clean_env() -> dict[str, str]:
    """The environment for a tool: everything except variables that look like secrets."""
    secret = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL", re.IGNORECASE)
    return {k: v for k, v in os.environ.items() if not secret.search(k)}


def _version(package: str) -> str | None:
    try:
        return version(package)
    except PackageNotFoundError:
        return None


def _ruff_severity(code: str) -> Severity:
    # "invalid-syntax": the file cannot even be parsed, the most serious thing a tool can say.
    if code in ("invalid-syntax", "syntax-error") or code.startswith(("F821", "F822", "F823", "PLE", "E9")):
        return Severity.HIGH
    if code.startswith(("B", "BLE", "F6", "F5", "F7")):
        return Severity.MEDIUM
    return Severity.LOW


def _ruff_category(code: str) -> Category:
    if code.startswith("BLE"):
        return Category.ERROR_HANDLING
    if code.startswith(("F4", "F8", "PLW")) and not code.startswith(("F821", "F822", "F823")):
        return Category.MAINTAINABILITY  # unused imports and variables, redefinitions
    return Category.LOGIC_DEFECT


def _run(cmd: list[str], cwd: Path, timeout: float) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 - fixed argv, no shell, no user-controlled arguments
        cmd, cwd=cwd, env=_clean_env(), capture_output=True, text=True, timeout=timeout,
        stdin=subprocess.DEVNULL, check=False,
    )


def _run_ruff(workdir: Path, select: str, timeout: float) -> list[dict]:
    done = _run([sys.executable, "-m", "ruff", "check", "--isolated", "--no-cache", "--exit-zero",
                 "--select", select, "--output-format", "json", "."], workdir, timeout)
    if done.returncode != 0 or len(done.stdout) > MAX_OUTPUT_CHARS:
        raise RuntimeError(f"ruff exited with code {done.returncode}: {done.stderr.strip()[:200] or 'no message'}")
    return json.loads(done.stdout or "[]")


def _run_bandit(workdir: Path, timeout: float) -> list[dict]:
    done = _run([sys.executable, "-m", "bandit", "-q", "-r", ".", "-f", "json", "--exit-zero"], workdir, timeout)
    if done.returncode != 0 or len(done.stdout) > MAX_OUTPUT_CHARS:
        raise RuntimeError(f"bandit exited with code {done.returncode}: {done.stderr.strip()[:200] or 'no message'}")
    return json.loads(done.stdout or "{}").get("results", [])


def _relative(workdir: Path, filename: str) -> str:
    path = Path(filename)
    try:
        path = path.resolve().relative_to(workdir.resolve()) if path.is_absolute() else path
    except ValueError:
        pass
    return path.as_posix().removeprefix("./")


def run_static_analysis(
    review_input: ReviewInput,
    tools: tuple[str, ...] | list[str] = DEFAULT_TOOLS,
    ruff_select: str = RUFF_SELECT,
    timeout: float = TOOL_TIMEOUT_S,
) -> tuple[list[ToolFinding], list[ToolRun]]:
    """Run the chosen tools on the Python files available in full. Never raises for a tool problem:
    a tool that cannot run is reported in its ToolRun, not hidden."""
    unknown = [t for t in tools if t not in DEFAULT_TOOLS]
    if unknown:
        raise ValueError(f"Unknown tool(s) {unknown}. Available: {', '.join(DEFAULT_TOOLS)}")
    if not tools:
        return [], []

    files: dict[str, str] = {}
    for sf in [*review_input.analysis_files, *review_input.supporting_files]:
        rel = _safe_relative(sf.path)
        if rel and rel.endswith(".py") and len(sf.content) <= MAX_FILE_CHARS and len(files) < MAX_FILES:
            files.setdefault(rel, sf.content)
    changed_py = [fd.path for fd in split_diff(review_input.diff) if fd.path.endswith(".py")]
    missing = [p for p in changed_py if p not in files]

    if not files:
        reason = ("no Python file was available in full" if changed_py else "the change contains no Python file")
        return [], [ToolRun(name=t, version=_version(t), status="skipped", message=reason) for t in tools]

    added = added_lines(review_input.diff)
    findings: list[ToolFinding] = []
    runs: list[ToolRun] = []

    with tempfile.TemporaryDirectory(prefix="review-agent-") as tmp:
        workdir = Path(tmp)
        for rel, content in files.items():
            target = workdir / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")

        for tool in tools:
            started = time.monotonic()
            run = ToolRun(name=tool, version=_version(tool), status="ok", files_checked=len(files))
            try:
                raw = _run_ruff(workdir, ruff_select, timeout) if tool == "ruff" else _run_bandit(workdir, timeout)
            except subprocess.TimeoutExpired:
                run.status, run.message = "failed", f"timed out after {timeout:g} s"
            except (OSError, RuntimeError, ValueError) as exc:
                run.status, run.message = "failed", f"{type(exc).__name__}: {exc}"[:300]
            else:
                found = _convert(tool, raw, workdir, files, added)
                notes: list[str] = []
                if tool == "bandit":
                    # Bandit's assert (B101) and hard-coded-password rules fire constantly in test code:
                    # classic false positives. Test files are not security-reviewed by this tool.
                    kept = [f for f in found if not _is_test(f.file)]
                    if len(kept) != len(found):
                        notes.append(f"{len(found) - len(kept)} warning(s) in test files were ignored (noise in tests)")
                    found = kept
                findings += found
                run.total_findings = len(found)
                run.findings_on_changed_lines = sum(f.on_changed_line for f in found)
                if notes:
                    run.message = "; ".join(notes)
            run.duration_s = round(time.monotonic() - started, 2)
            if missing and run.status == "ok":
                gap = f"{len(missing)} changed Python file(s) were not available in full and were not checked: {', '.join(missing[:5])}"
                run.message = f"{run.message}; {gap}" if run.message else gap
            runs.append(run)
    return findings, runs


def _convert(tool: str, raw, workdir: Path, files: dict[str, str], added: dict[str, set[int]]) -> list[ToolFinding]:
    out: list[ToolFinding] = []
    for item in raw:
        if tool == "ruff":
            code = item.get("code") or "syntax-error"
            rel, line = _relative(workdir, item["filename"]), item["location"]["row"]
            severity, category = _ruff_severity(code), _ruff_category(code)
            message = item["message"]
        else:
            code = item["test_id"]
            rel, line = _relative(workdir, item["filename"]), item["line_number"]
            severity = {"HIGH": Severity.HIGH, "MEDIUM": Severity.MEDIUM}.get(item["issue_severity"], Severity.LOW)
            category, message = Category.SECURITY, item["issue_text"]
        lines = files.get(rel, "").splitlines()
        text = lines[line - 1].strip() if 1 <= line <= len(lines) else ""
        out.append(ToolFinding(
            tool=tool, rule=code, file=rel, line=max(line, 1), message=message, severity=severity,
            category=category, code_line=text, on_changed_line=line in added.get(rel, set()),
        ))
    return out


# -------------------------------------------------- from tool findings to our findings


_SEVERITY_ORDER = {Severity.CRITICAL: 0, Severity.HIGH: 1, Severity.MEDIUM: 2, Severity.LOW: 3}


def select_reportable(tool_findings: list[ToolFinding]) -> tuple[list[ToolFinding], int]:
    """The warnings that become findings: those on changed lines, the most serious first, capped.

    Returns (selected, number left out by the cap). A flood of tool warnings would bury the real review.
    """
    on_lines = sorted((t for t in tool_findings if t.on_changed_line), key=lambda t: (_SEVERITY_ORDER[t.severity], t.file, t.line))
    return on_lines[:MAX_REPORTED_FINDINGS], max(0, len(on_lines) - MAX_REPORTED_FINDINGS)


def tool_findings_to_findings(tool_findings: list[ToolFinding]) -> list[Finding]:
    """Warnings on lines the PR changed become findings. The line itself is the evidence."""
    out = []
    for t in select_reportable(tool_findings)[0]:
        out.append(Finding(
            category=t.category, severity=t.severity, file=t.file, line=t.line,
            title=_short(f"{t.tool} {t.rule}: {t.message}", 120),
            explanation=f"{t.message} (reported by the static-analysis tool {t.tool}, rule {t.rule}; "
                        "a deterministic check, not a model's opinion).",
            evidence=[Evidence(source="code", quote=t.code_line or "(empty line)")],
            found_by=[t.tool], source="tool",
        ))
    return out


def _short(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render_leads(tool_findings: list[ToolFinding], runs: list[ToolRun]) -> str:
    """The block shown to the model passes: concrete leads from the tools."""
    if not runs:
        return "(static analysis was not run)"
    header = "Tools: " + ", ".join(f"{r.name} {r.version or ''} ({r.status}{': ' + r.message if r.message else ''})".replace("  ", " ")
                                    for r in runs)
    on_lines = [f for f in tool_findings if f.on_changed_line]
    lines = [header]
    if not on_lines:
        lines.append("No warnings on lines changed by this pull request.")
    else:
        lines.append("Warnings on lines changed by this pull request:")
        for f in on_lines[:MAX_LEADS_IN_PROMPT]:
            lines.append(f"- {f.tool} {f.rule} at {f.file}:{f.line} [{f.severity}]: {' '.join(f.message.split())}"
                         + (f" | code: {f.code_line}" if f.code_line else ""))
        if len(on_lines) > MAX_LEADS_IN_PROMPT:
            lines.append(f"- ({len(on_lines) - MAX_LEADS_IN_PROMPT} more not shown)")
    ignored = len(tool_findings) - len(on_lines)
    if ignored:
        lines.append(f"({ignored} further warning(s) on lines this pull request did not touch were ignored.)")
    return "\n".join(lines)


# ---------------------------------------------------------------------- change profile

_SOURCE_SUFFIXES = {".py", ".js", ".jsx", ".ts", ".tsx", ".java", ".go", ".rs", ".rb", ".php", ".cs", ".c", ".cc",
                    ".cpp", ".h", ".hpp", ".kt", ".swift", ".scala", ".sh", ".sql"}
_DEPENDENCY_FILES = {"requirements.txt", "pyproject.toml", "package.json", "package-lock.json", "poetry.lock", "uv.lock",
                     "pom.xml", "build.gradle", "go.mod", "go.sum", "gemfile", "cargo.toml", "cargo.lock", "yarn.lock"}
_SENSITIVE = re.compile(r"auth|login|logout|password|passwd|secret|token|crypto|payment|billing|checkout|permission|"
                        r"acl|admin|session|security|oauth|jwt|migration", re.IGNORECASE)


def _is_test(path: str) -> bool:
    p = PurePosixPath(path)
    name = p.name.lower()
    parts = {part.lower() for part in p.parts[:-1]}
    return bool(parts & {"test", "tests", "__tests__", "spec", "specs"}) or name.startswith("test_") or any(
        marker in name for marker in ("_test.", ".test.", ".spec.", "_spec."))


def compute_profile(review_input: ReviewInput) -> ChangeProfile:
    """Size and nature of the change, from the diff alone."""
    files = split_diff(review_input.diff)
    profile = ChangeProfile(files_changed=len(files))
    sensitive: list[str] = []
    deps: list[str] = []
    ci: list[str] = []
    for fd in files:
        in_hunk = False
        for line in fd.text.splitlines():
            if HUNK_HEADER.match(line):
                in_hunk = True
            elif in_hunk and line.startswith("+"):
                profile.lines_added += 1
            elif in_hunk and line.startswith("-"):
                profile.lines_removed += 1
        suffix = PurePosixPath(fd.path).suffix.lower() or "(none)"
        profile.languages[suffix] = profile.languages.get(suffix, 0) + 1
        if _is_test(fd.path):
            profile.test_files += 1
        elif suffix in _SOURCE_SUFFIXES:
            profile.source_files += 1
            if _SENSITIVE.search(fd.path):
                sensitive.append(fd.path)
        if PurePosixPath(fd.path).name.lower() in _DEPENDENCY_FILES:
            deps.append(fd.path)
        if ".github/workflows" in fd.path or PurePosixPath(fd.path).name.lower() in {"dockerfile", ".gitlab-ci.yml"} \
                or fd.path.endswith((".tf", "docker-compose.yml", "compose.yaml")):
            ci.append(fd.path)

    if profile.source_files and not profile.test_files:
        profile.hints.append(f"{profile.source_files} source file(s) changed but no test file changed.")
    if sensitive:
        profile.hints.append("Touches security-sensitive area(s): " + ", ".join(sensitive[:5]) + ".")
    if deps:
        profile.hints.append("Dependency or build file(s) changed: " + ", ".join(deps[:5]) + ".")
    if ci:
        profile.hints.append("CI or infrastructure file(s) changed: " + ", ".join(ci[:5]) + ".")
    size = profile.lines_added + profile.lines_removed
    if size > 500 or profile.files_changed > 20:
        profile.hints.append(f"Large change ({profile.files_changed} files, {size} lines): large diffs are reviewed less reliably.")
    return profile
