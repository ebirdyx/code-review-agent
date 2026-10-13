"""Guard rails on the GitHub Actions template: the safety properties must not be edited away by accident."""

from pathlib import Path

TEMPLATE = (Path(__file__).parent.parent / "integration" / "code-review.yml").read_text(encoding="utf-8")


def test_only_the_needed_permissions_are_granted():
    assert "contents: read" in TEMPLATE and "pull-requests: write" in TEMPLATE
    assert "contents: write" not in TEMPLATE


def test_fork_pull_requests_and_drafts_are_skipped():
    assert "head.repo.full_name == github.repository" in TEMPLATE and "!github.event.pull_request.draft" in TEMPLATE


def test_the_dangerous_trigger_is_not_used():
    # pull_request_target runs with secrets on code from forks.
    assert "pull_request_target" not in TEMPLATE.replace("# ", "").split("on:")[1].split("permissions:")[0]


def test_untrusted_values_reach_the_shell_through_env_not_inline():
    run_block = TEMPLATE.split("run: |")[1].split("- name:")[0]
    assert "${{" not in run_block


def test_secrets_are_read_from_repository_secrets_and_a_newer_push_cancels_the_old_review():
    assert "secrets.OLLAMA_API_KEY" in TEMPLATE and "cancel-in-progress: true" in TEMPLATE
    assert "--post-comment" in TEMPLATE
