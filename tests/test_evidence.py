"""Static-analysis evidence and the change profile.

These tests run the REAL Ruff and Bandit (deterministic, offline, no model) on small inputs, so
they check our integration with the actual tools, not a stand-in. Only the timeout and crash
paths patch the subprocess call, because they cannot be provoked on demand.
"""

import subprocess
from pathlib import Path

import pytest

from code_review_agent.connectors.snapshot import load_example, save_snapshot
from code_review_agent.context import evidence
from code_review_agent.context.evidence import (
    _clean_env,
    _ruff_category,
    _ruff_severity,
    added_lines,
    compute_profile,
    render_leads,
    run_static_analysis,
    tool_findings_to_findings,
)
from code_review_agent.schemas import (
    Category,
    PullRequestMetadata,
    ReviewInput,
    Severity,
    SupportingFile,
)

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT / "evaluation" / "cases"
EXAMPLES = ROOT / "examples"


def case_dir(case_id: str) -> Path:
    return CASES / case_id if (CASES / case_id).is_dir() else EXAMPLES / case_id


def make_input(diff: str, files: dict[str, str] | None = None, supporting: dict[str, str] | None = None, **kw) -> ReviewInput:
    return ReviewInput(
        pr=PullRequestMetadata(title="t"), diff=diff,
        analysis_files=[SupportingFile(path=p, content=c) for p, c in (files or {}).items()],
        supporting_files=[SupportingFile(path=p, content=c) for p, c in (supporting or {}).items()], **kw)


def add_diff(path: str, start: int, lines: list[str], context_before: int = 0) -> str:
    body = "\n".join("+" + line for line in lines)
    return (f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n"
            f"@@ -{start},0 +{start},{len(lines)} @@\n{body}\n")


# ============================================================ real tools on benchmark cases


def test_tools_flag_exactly_the_known_pattern_defects_on_the_changed_line():
    flagged = {}
    for folder in sorted(p for root in (CASES, EXAMPLES) for p in root.iterdir() if p.is_dir()):
        _, review_input = load_example(folder)
        findings, runs = run_static_analysis(review_input)
        assert all(r.status == "ok" for r in runs), (folder.name, runs)
        on_line = [f"{f.tool}:{f.rule}" for f in findings if f.on_changed_line]
        if on_line:
            flagged[folder.name] = on_line
    # Four of the sixteen planted defects are known patterns; the other twelve need understanding.
    assert flagged == {
        "user-search-sql": ["bandit:B608"],  # SQL built with an f-string
        "password-md5": ["bandit:B324"],  # MD5 for a password
        "parse-quantity": ["ruff:BLE001"],  # blind `except Exception`
        "fetch-profile": ["bandit:B310"],  # urlopen with an unchecked URL scheme
    }


def test_tools_stay_quiet_on_the_correct_changes():
    for case_id in ("slugify-title", "safe-divide", "invoice-vat", "free-shipping-fixed"):
        _, review_input = load_example(case_dir(case_id))
        findings, _ = run_static_analysis(review_input)
        assert findings == []


def test_tool_input_files_match_the_diffs_they_accompany():
    # The analysis files are NOT shown to the model, so they must agree with the diff that IS:
    # every line the diff adds must be that very line of the analysis file.
    checked = 0
    for folder in sorted(p for root in (CASES, EXAMPLES) for p in root.iterdir() if p.is_dir()):
        _, review_input = load_example(folder)
        files = {f.path: f.content.splitlines() for f in review_input.analysis_files}
        for path, numbers in added_lines(review_input.diff).items():
            if not path.endswith(".py"):
                continue
            assert path in files, f"{folder.name}: no analysis file for {path}"
            from code_review_agent.pipeline.validation import _index_diff

            shown, _ = _index_diff(review_input.diff)
            for n in numbers:
                assert files[path][n - 1] == shown[path][n], f"{folder.name}:{path}:{n}"
                checked += 1
    assert checked > 50


# ================================================================= changed lines only


OLD_AND_NEW = '''def old():
    try:
        return 1
    except Exception:
        return 0


def new():
    try:
        return 2
    except Exception:
        return 0
'''


def test_only_warnings_on_lines_the_pr_changed_become_findings():
    diff = add_diff("m.py", 8, OLD_AND_NEW.splitlines()[7:])  # the PR adds only new() (lines 8-12)
    review_input = make_input(diff, {"m.py": OLD_AND_NEW})
    findings, runs = run_static_analysis(review_input)
    ruff = next(r for r in runs if r.name == "ruff")
    assert ruff.total_findings == 2 and ruff.findings_on_changed_lines == 1  # one was already there
    changed = [f for f in findings if f.on_changed_line]
    assert [(f.rule, f.line) for f in changed] == [("BLE001", 11)]
    assert [f.title for f in tool_findings_to_findings(findings)] == [
        "ruff BLE001: Do not catch blind exception: `Exception`"]
    assert "1 further warning(s) on lines this pull request did not touch were ignored" in render_leads(findings, runs)


def test_a_tool_finding_becomes_a_complete_finding_with_the_code_line_as_evidence():
    diff = add_diff("m.py", 8, OLD_AND_NEW.splitlines()[7:])
    findings, _ = run_static_analysis(make_input(diff, {"m.py": OLD_AND_NEW}))
    f = tool_findings_to_findings(findings)[0]
    assert (f.category, f.severity, f.file, f.line) == (Category.ERROR_HANDLING, Severity.MEDIUM, "m.py", 11)
    assert f.source == "tool" and f.found_by == ["ruff"]
    assert f.evidence[0].source == "code" and f.evidence[0].quote == "except Exception:"
    assert "deterministic check" in f.explanation


def test_supporting_files_are_analysed_too_without_duplicates():
    diff = add_diff("m.py", 1, ["import os"])
    review_input = make_input(diff, {"m.py": "import os\n"}, supporting={"m.py": "import os\n"})
    _, runs = run_static_analysis(review_input)
    assert runs[0].files_checked == 1


# ==================================================================== noise control


def test_bandit_warnings_in_test_files_are_ignored_but_counted():
    # Found on a real PR: 270 of Bandit's 276 warnings were `assert` in pytest files.
    source = "def test_x():\n    assert 1 == 1\n"
    findings, runs = run_static_analysis(make_input(add_diff("tests/test_x.py", 1, source.splitlines()), {"tests/test_x.py": source}))
    bandit = next(r for r in runs if r.name == "bandit")
    assert bandit.total_findings == 0 and "1 warning(s) in test files were ignored" in bandit.message
    assert not [f for f in findings if f.tool == "bandit"]


def test_the_same_assert_in_production_code_is_still_reported():
    source = "def check(x):\n    assert x > 0\n"
    findings, _ = run_static_analysis(make_input(add_diff("src/app.py", 1, source.splitlines()), {"src/app.py": source}))
    assert [(f.tool, f.rule, f.line, f.on_changed_line) for f in findings if f.tool == "bandit"] == [("bandit", "B101", 2, True)]


def test_ruff_still_checks_test_files():
    source = "def test_x():\n    try:\n        pass\n    except Exception:\n        pass\n"
    findings, _ = run_static_analysis(make_input(add_diff("tests/test_x.py", 1, source.splitlines()), {"tests/test_x.py": source}))
    assert any(f.tool == "ruff" and f.rule == "BLE001" and f.on_changed_line for f in findings)


def test_reportable_findings_are_capped_most_serious_first():
    from code_review_agent.context.evidence import (
        MAX_REPORTED_FINDINGS,
        select_reportable,
    )
    from code_review_agent.schemas import ToolFinding

    def tf(i, severity):
        return ToolFinding(tool="ruff", rule=f"R{i}", file="a.py", line=i + 1, message="m", severity=severity,
                           category=Category.LOGIC_DEFECT, on_changed_line=True)

    items = [tf(i, Severity.LOW) for i in range(25)] + [tf(100 + i, Severity.HIGH) for i in range(10)]
    selected, left_out = select_reportable(items)
    assert len(selected) == MAX_REPORTED_FINDINGS and left_out == 5
    assert all(t.severity == Severity.HIGH for t in selected[:10])  # the serious ones are never the ones dropped
    off_line = [tf(1, Severity.HIGH).model_copy(update={"on_changed_line": False})]
    assert select_reportable(off_line) == ([], 0)


# ============================================================ what cannot be analysed


def test_no_python_means_skipped_with_a_reason_not_silence():
    review_input = make_input(add_diff("README.md", 1, ["hello"]))
    findings, runs = run_static_analysis(review_input)
    assert findings == [] and [(r.name, r.status) for r in runs] == [("ruff", "skipped"), ("bandit", "skipped")]
    assert "no Python file" in runs[0].message


def test_a_changed_python_file_that_is_not_available_in_full_is_named():
    diff = add_diff("a.py", 1, ["x = 1"]) + add_diff("b.py", 1, ["y = 2"])
    _, runs = run_static_analysis(make_input(diff, {"a.py": "x = 1\n"}))
    assert all("b.py" in r.message and "not available in full" in r.message for r in runs)


def test_python_file_present_in_the_diff_but_missing_everywhere_is_skipped_with_the_reason():
    _, runs = run_static_analysis(make_input(add_diff("a.py", 1, ["x = 1"])))
    assert runs[0].status == "skipped" and "no Python file was available in full" in runs[0].message


def test_unknown_tools_are_rejected_and_no_tools_is_allowed():
    with pytest.raises(ValueError, match="Unknown tool"):
        run_static_analysis(make_input(add_diff("a.py", 1, ["x = 1"]), {"a.py": "x = 1\n"}), tools=("pylint",))
    assert run_static_analysis(make_input(add_diff("a.py", 1, ["x = 1"])), tools=()) == ([], [])


def test_a_file_with_a_syntax_error_does_not_crash_the_review():
    source = "def broken(:\n    pass\n"
    findings, runs = run_static_analysis(make_input(add_diff("bad.py", 1, source.splitlines()), {"bad.py": source}))
    assert all(r.status == "ok" for r in runs)
    syntax = [f for f in findings if f.rule == "invalid-syntax"]
    assert syntax and syntax[0].severity == Severity.HIGH and syntax[0].on_changed_line


# ===================================================================== safety


@pytest.mark.parametrize("path", ["../evil.py", "/etc/evil.py", "C:/evil.py", "a\\..\\evil.py", "x/../../evil.py", ""])
def test_unsafe_paths_are_never_written_or_analysed(path):
    review_input = make_input(add_diff("ok.py", 1, ["x = 1"]), {path: "import os\n"} if path else {})
    _, runs = run_static_analysis(review_input)
    assert runs[0].status == "skipped"  # the unsafe file was dropped, so nothing was left to analyse


def test_a_malicious_config_in_the_pr_cannot_switch_the_tools_off():
    source = "def f():\n    try:\n        return 1\n    except Exception:\n        return 0\n"
    review_input = make_input(
        add_diff("m.py", 1, source.splitlines()),
        {"m.py": source, "ruff.toml": "[lint]\nselect = []\n", "pyproject.toml": "[tool.ruff]\nexclude = ['*']\n"},
    )
    findings, _ = run_static_analysis(review_input)
    assert any(f.rule == "BLE001" for f in findings)  # config files are not even copied, and Ruff runs --isolated


def test_secret_looking_environment_variables_never_reach_the_tools(monkeypatch):
    for name in ("OLLAMA_API_KEY", "JIRA_API_TOKEN", "GITHUB_TOKEN", "MY_SECRET", "DB_PASSWORD", "AWS_CREDENTIALS"):
        monkeypatch.setenv(name, "hunter2")
    monkeypatch.setenv("HARMLESS_SETTING", "ok")
    env = _clean_env()
    assert "hunter2" not in env.values() and "HARMLESS_SETTING" in env and "PATH" in env or "Path" in env


def test_the_tools_are_given_a_timeout_and_no_shell(monkeypatch):
    seen = {}

    def spy(cmd, **kwargs):
        seen.update(kwargs, cmd=cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")

    monkeypatch.setattr(evidence.subprocess, "run", spy)
    run_static_analysis(make_input(add_diff("a.py", 1, ["x = 1"]), {"a.py": "x = 1\n"}), tools=("ruff",), timeout=7)
    assert seen["timeout"] == 7 and not seen.get("shell") and isinstance(seen["cmd"], list)
    assert "--isolated" in seen["cmd"] and seen["stdin"] == subprocess.DEVNULL


# ================================================================= tool failures


def test_a_tool_that_times_out_is_reported_as_failed(monkeypatch):
    def slow(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, 1)

    monkeypatch.setattr(evidence.subprocess, "run", slow)
    _, runs = run_static_analysis(make_input(add_diff("a.py", 1, ["x = 1"]), {"a.py": "x = 1\n"}), timeout=1)
    assert all(r.status == "failed" and "timed out" in r.message for r in runs)


def test_a_tool_that_crashes_or_prints_garbage_is_reported_as_failed(monkeypatch):
    def broken(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 2, stdout="", stderr="boom: internal error")

    monkeypatch.setattr(evidence.subprocess, "run", broken)
    _, runs = run_static_analysis(make_input(add_diff("a.py", 1, ["x = 1"]), {"a.py": "x = 1\n"}))
    assert all(r.status == "failed" and "boom" in r.message for r in runs)

    def garbage(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="not json", stderr="")

    monkeypatch.setattr(evidence.subprocess, "run", garbage)
    _, runs = run_static_analysis(make_input(add_diff("a.py", 1, ["x = 1"]), {"a.py": "x = 1\n"}))
    assert all(r.status == "failed" for r in runs)


def test_one_failing_tool_does_not_stop_the_other(monkeypatch):
    real = evidence._run_bandit

    def ruff_dies(workdir, select, timeout):
        raise RuntimeError("ruff exploded")

    monkeypatch.setattr(evidence, "_run_ruff", ruff_dies)
    source = 'import hashlib\n\n\ndef h(p):\n    return hashlib.md5(p).hexdigest()\n'
    findings, runs = run_static_analysis(make_input(add_diff("m.py", 1, source.splitlines()), {"m.py": source}))
    assert {r.name: r.status for r in runs} == {"ruff": "failed", "bandit": "ok"}
    assert any(f.tool == "bandit" and f.on_changed_line for f in findings)
    assert real  # kept to show the real bandit ran


# ============================================================ mapping and rendering


@pytest.mark.parametrize(
    ("code", "severity", "category"),
    [("F821", Severity.HIGH, Category.LOGIC_DEFECT), ("PLE0101", Severity.HIGH, Category.LOGIC_DEFECT),
     ("B006", Severity.MEDIUM, Category.LOGIC_DEFECT), ("BLE001", Severity.MEDIUM, Category.ERROR_HANDLING),
     ("F401", Severity.LOW, Category.MAINTAINABILITY), ("F841", Severity.LOW, Category.MAINTAINABILITY),
     ("PLW0603", Severity.LOW, Category.MAINTAINABILITY), ("invalid-syntax", Severity.HIGH, Category.LOGIC_DEFECT)],
)
def test_rule_to_severity_and_category_mapping(code, severity, category):
    assert _ruff_severity(code) == severity and _ruff_category(code) == category


def test_leads_block_when_nothing_was_found_or_nothing_ran():
    assert render_leads([], []) == "(static analysis was not run)"
    _, runs = run_static_analysis(make_input(add_diff("a.py", 1, ["x = 1"]), {"a.py": "x = 1\n"}))
    text = render_leads([], runs)
    assert "No warnings on lines changed by this pull request." in text and "ruff" in text and "bandit" in text


def test_leads_block_is_capped():
    source = "\n".join(f"def f{i}():\n    try:\n        pass\n    except Exception:\n        pass\n" for i in range(50))
    findings, runs = run_static_analysis(make_input(add_diff("m.py", 1, source.splitlines()), {"m.py": source}))
    text = render_leads(findings, runs)
    assert text.count("- ruff BLE001") == evidence.MAX_LEADS_IN_PROMPT and "more not shown" in text


# ========================================================================== changes


def diff_for(*paths: str, lines: int = 3) -> str:
    return "".join(add_diff(p, 1, [f"line {i}" for i in range(lines)]) for p in paths)


def profile(*paths: str, lines: int = 3):
    return compute_profile(ReviewInput(pr=PullRequestMetadata(title="t"), diff=diff_for(*paths, lines=lines)))


def test_profile_counts_files_lines_types_and_tests():
    p = profile("src/app.py", "tests/test_app.py", "README.md")
    assert (p.files_changed, p.lines_added, p.lines_removed) == (3, 9, 0)
    assert p.languages == {".py": 2, ".md": 1} and (p.source_files, p.test_files) == (1, 1)
    assert p.hints == []


def test_profile_warns_when_source_changes_without_tests():
    assert any("no test file changed" in h for h in profile("src/app.py").hints)
    assert not any("no test file" in h for h in profile("src/app.py", "src/app.test.js").hints)
    assert not any("no test file" in h for h in profile("README.md").hints)  # docs only: nothing to test


@pytest.mark.parametrize("path", ["src/auth/login.py", "payments/charge.py", "db/migrations/001.py", "api/session.ts"])
def test_profile_flags_sensitive_areas(path):
    assert any("security-sensitive" in h and path in h for h in profile(path, "tests/test_x.py").hints)


def test_profile_flags_dependencies_ci_and_size():
    hints = " ".join(profile("pyproject.toml", ".github/workflows/ci.yml", "Dockerfile", "package.json").hints)
    assert "Dependency or build file(s) changed: pyproject.toml, package.json" in hints
    assert "CI or infrastructure file(s) changed: .github/workflows/ci.yml, Dockerfile" in hints
    big = " ".join(profile("a.py", lines=600).hints)
    assert "Large change" in big
    assert not any("Large change" in h for h in profile("a.py").hints)


def test_profile_of_a_removal_only_change():
    diff = "diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1,3 +0,0 @@\n-x\n-y\n-z\n"
    p = compute_profile(ReviewInput(pr=PullRequestMetadata(title="t"), diff=diff))
    assert (p.lines_added, p.lines_removed) == (0, 3)


# ===================================================================== loading


def test_analysis_files_and_rules_round_trip_through_a_snapshot(tmp_path):
    from code_review_agent.connectors.github import PullRequestSnapshot

    snap = PullRequestSnapshot(
        metadata=PullRequestMetadata(title="t", head_sha="a" * 40), diff=add_diff("a.py", 1, ["x = 1"]),
        analysis_files=[SupportingFile(path="pkg/a.py", content="x = 1\n")], rules="- No prints.\n",
        rules_source=".review-agent/rules.md at base commit bbbbbbb")
    save_snapshot(snap, tmp_path / "snap")
    _, loaded = load_example(tmp_path / "snap")
    assert [(f.path, f.content) for f in loaded.analysis_files] == [("pkg/a.py", "x = 1\n")]
    assert loaded.rules == "- No prints.\n" and loaded.rules_source == ".review-agent/rules.md at base commit bbbbbbb"
    assert loaded.supporting_files == []  # analysis files are never mixed into what the model sees


def test_snapshot_refuses_analysis_paths_outside_its_folder(tmp_path):
    from code_review_agent.connectors.github import PullRequestSnapshot

    snap = PullRequestSnapshot(metadata=PullRequestMetadata(title="t"), diff="d",
                               analysis_files=[SupportingFile(path="../../evil.py", content="x")])
    with pytest.raises(ValueError, match="outside the snapshot folder"):
        save_snapshot(snap, tmp_path / "snap")
    assert not (tmp_path / "evil.py").exists()
