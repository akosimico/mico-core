from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import Settings, get_settings
from app.tools.base import Tool

logger = logging.getLogger("mico.tools.github")

GITHUB_API_BASE = "https://api.github.com"


class GitHubClient:
    def __init__(self, token: str | None = None, default_user: str | None = None):
        self.token = token
        self.default_user = default_user

    def _get_headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": "MICO-Assistant/0.3.0",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def get_repositories(self, username: str | None = None) -> str:
        """Fetch public or user repositories."""
        user = username or self.default_user
        headers = self._get_headers()

        async with httpx.AsyncClient(headers=headers, timeout=15.0) as client:
            if user:
                url = f"{GITHUB_API_BASE}/users/{user}/repos?sort=updated&per_page=10"
            elif self.token:
                url = f"{GITHUB_API_BASE}/user/repos?sort=updated&per_page=10"
            else:
                return "Error: No GitHub username provided and no default user or GITHUB_TOKEN configured."

            try:
                resp = await client.get(url)
                if resp.status_code == 404:
                    return f"Error: GitHub user '{user}' was not found."
                if resp.status_code == 403:
                    return "Error: GitHub API rate limit reached or token lacks permissions."
                resp.raise_for_status()
                repos = resp.json()

                if not repos:
                    return f"No repositories found for {user or 'authenticated user'}."

                lines = [f"📂 **GitHub Repositories ({len(repos)}):**"]
                for r in repos:
                    stars = r.get("stargazers_count", 0)
                    lang = r.get("language") or "N/A"
                    desc = f" — _{r.get('description')}_" if r.get("description") else ""
                    lines.append(f"• **[{r.get('full_name')}]({r.get('html_url')})** (⭐ {stars} | {lang}){desc}")

                return "\n".join(lines)
            except Exception as exc:
                logger.exception("GitHub get_repositories failed: %s", exc)
                return f"GitHub API error: {exc}"

    async def get_commits(self, repo: str, limit: int = 5) -> str:
        """Fetch recent commits from a repository (repo in format 'owner/name')."""
        repo_clean = repo.strip().strip("/")
        if "/" not in repo_clean:
            if self.default_user:
                repo_clean = f"{self.default_user}/{repo_clean}"
            else:
                return "Error: Please specify the repository in 'owner/repo' format (e.g. 'octocat/Hello-World')."

        url = f"{GITHUB_API_BASE}/repos/{repo_clean}/commits?per_page={max(1, min(limit, 20))}"
        headers = self._get_headers()

        async with httpx.AsyncClient(headers=headers, timeout=15.0) as client:
            try:
                resp = await client.get(url)
                if resp.status_code == 404:
                    return f"Error: Repository '{repo_clean}' was not found on GitHub."
                if resp.status_code == 403:
                    return "Error: GitHub rate limit exceeded or access forbidden."
                resp.raise_for_status()
                commits = resp.json()

                if not commits:
                    return f"No commits found for repository '{repo_clean}'."

                lines = [f"🔨 **Recent Commits for {repo_clean}:**"]
                for c in commits:
                    sha = c.get("sha", "")[:7]
                    commit_obj = c.get("commit", {})
                    author = commit_obj.get("author", {}).get("name") or "Unknown"
                    message = commit_obj.get("message", "").split("\n")[0]
                    date_str = commit_obj.get("author", {}).get("date", "")[:10]
                    lines.append(f"• [`{sha}`] {message} — _{author}_ ({date_str})")

                return "\n".join(lines)
            except Exception as exc:
                logger.exception("GitHub get_commits failed: %s", exc)
                return f"GitHub API error: {exc}"

    async def get_issues(self, repo: str, state: str = "open", limit: int = 5) -> str:
        """Fetch issues for a repository (excluding pull requests)."""
        repo_clean = repo.strip().strip("/")
        if "/" not in repo_clean:
            if self.default_user:
                repo_clean = f"{self.default_user}/{repo_clean}"
            else:
                return "Error: Please specify the repository in 'owner/repo' format."

        url = f"{GITHUB_API_BASE}/repos/{repo_clean}/issues?state={state}&per_page={max(1, min(limit, 20))}"
        headers = self._get_headers()

        async with httpx.AsyncClient(headers=headers, timeout=15.0) as client:
            try:
                resp = await client.get(url)
                if resp.status_code == 404:
                    return f"Error: Repository '{repo_clean}' was not found on GitHub."
                resp.raise_for_status()
                items = resp.json()

                # Filter out Pull Requests (GitHub issues endpoint includes PRs)
                issues = [item for item in items if "pull_request" not in item]

                if not issues:
                    return f"No {state} issues found in '{repo_clean}'."

                lines = [f"🐛 **Issues in {repo_clean} ({state}):**"]
                for iss in issues[:limit]:
                    num = iss.get("number")
                    title = iss.get("title")
                    user = iss.get("user", {}).get("login") or "user"
                    lines.append(f"• `#{num}` **{title}** (by @{user})")

                return "\n".join(lines)
            except Exception as exc:
                logger.exception("GitHub get_issues failed: %s", exc)
                return f"GitHub API error: {exc}"


def build_github_tools(client: GitHubClient) -> list[Tool]:
    return [
        Tool(
            name="github_get_repositories",
            description="List recent repositories for a GitHub user or the configured account.",
            parameters={
                "type": "object",
                "properties": {
                    "username": {
                        "type": "string",
                        "description": "GitHub username. If omitted, uses default/authenticated user.",
                    }
                },
                "required": [],
            },
            func=client.get_repositories,
        ),
        Tool(
            name="github_get_commits",
            description="Get the recent commits for a GitHub repository in 'owner/repo' format.",
            parameters={
                "type": "object",
                "properties": {
                    "repo": {
                        "type": "string",
                        "description": "Repository in 'owner/repo' format (e.g. 'akosimico/mico-jarvis').",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of commits to return (default: 5).",
                    },
                },
                "required": ["repo"],
            },
            func=client.get_commits,
        ),
        Tool(
            name="github_get_issues",
            description="List issues for a GitHub repository in 'owner/repo' format.",
            parameters={
                "type": "object",
                "properties": {
                    "repo": {
                        "type": "string",
                        "description": "Repository in 'owner/repo' format (e.g. 'akosimico/mico-jarvis').",
                    },
                    "state": {
                        "type": "string",
                        "description": "Issue state to filter ('open', 'closed', 'all'). Defaults to 'open'.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Number of issues to return (default: 5).",
                    },
                },
                "required": ["repo"],
            },
            func=client.get_issues,
        ),
    ]
