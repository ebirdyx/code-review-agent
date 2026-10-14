"""The ways the program is started must point at code that exists (a module move silently breaks them)."""

import importlib
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_the_review_agent_command_points_at_a_real_callable():
    scripts = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["scripts"]
    module, _, function = scripts["review-agent"].partition(":")
    assert callable(getattr(importlib.import_module(module), function))


def test_python_dash_m_runs_the_command_line():
    done = subprocess.run([sys.executable, "-m", "code_review_agent", "--help"], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0 and "review-agent" in done.stdout and "eval-compare" in done.stdout


def test_the_data_files_live_next_to_the_modules_that_read_them():
    from importlib import resources

    assert resources.files("code_review_agent.llm").joinpath("models.toml").is_file()
    assert resources.files("code_review_agent.app").joinpath("web", "index.html").is_file()
    assert resources.files("code_review_agent").joinpath("prompts", "multi_v4", "common.md").is_file()


def test_every_module_of_the_package_imports():
    import pkgutil

    import code_review_agent

    for module in pkgutil.walk_packages(code_review_agent.__path__, "code_review_agent."):
        if module.name.endswith(".__main__"):  # running it is its job: it would start the command line
            continue
        importlib.import_module(module.name)
