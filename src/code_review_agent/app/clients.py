"""Where the network clients are created.

Commands call these factories (never the classes directly), so there is ONE place to substitute them: tests replace
`clients.github_client` and `clients.jira_client`. Both read their credentials from the environment (GITHUB_TOKEN,
JIRA_BASE_URL / JIRA_EMAIL / JIRA_API_TOKEN) and never print them.
"""

from __future__ import annotations

from ..connectors.github import GitHubClient
from ..connectors.jira import JiraClient


def github_client() -> GitHubClient:
    return GitHubClient()


def jira_client() -> JiraClient:
    return JiraClient()
