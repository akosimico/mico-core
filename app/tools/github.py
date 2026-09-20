from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
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

    async def get_activity_summary(self) -> str:
        """Summarize the configured account's recent repository activity."""
        if not self.default_user and not self.token:
            return "**GitHub activity:** unavailable — configure `GITHUB_DEFAULT_USER` or `GITHUB_TOKEN`."
        user = self.default_user
        headers = self._get_headers()
        try:
            async with httpx.AsyncClient(headers=headers, timeout=15.0) as client:
                url = (f"{GITHUB_API_BASE}/users/{user}/repos?sort=updated&per_page=10" if user
                       else f"{GITHUB_API_BASE}/user/repos?sort=updated&per_page=10")
                repos_response = await client.get(url)
                repos_response.raise_for_status()
                repos = repos_response.json()
                since = datetime.now(timezone.utc) - timedelta(days=7)
                commits: list[str] = []
                issue_count = 0
                for repo in repos:
                    name = repo.get("full_name")
                    if not name:
                        continue
                    commits_response = await client.get(f"{GITHUB_API_BASE}/repos/{name}/commits?per_page=5")
                    if commits_response.status_code == 200:
                        for commit in commits_response.json():
                            author_date = commit.get("commit", {}).get("author", {}).get("date", "")
                            try:
                                committed_at = datetime.fromisoformat(author_date.replace("Z", "+00:00"))
                            except ValueError:
                                continue
                            if committed_at >= since:
                                message = commit.get("commit", {}).get("message", "").split("\n")[0]
                                commits.append(f"• {name}: {message}")
                    issues_response = await client.get(f"{GITHUB_API_BASE}/repos/{name}/issues?state=open&per_page=100")
                    if issues_response.status_code == 200:
                        issue_count += sum(1 for item in issues_response.json() if "pull_request" not in item)
                lines = ["🐙 **GitHub activity (last 7 days)**"]
                lines.append(f"Open issues across recent repositories: **{issue_count}**")
                lines.extend(commits[:10] or ["No commits found in the last 7 days."])
                return "\n".join(lines)
        except Exception as exc:
            logger.exception("GitHub activity summary failed: %s", exc)
            return f"**GitHub activity:** unavailable ({exc})"

    async def get_commits_today(self, repo: str | None = None) -> str:
        """Report commits authored today in a repository or recent account repos."""
        since = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
        if repo:
            repositories = [{"full_name": repo.strip().strip("/")}]
        elif self.default_user:
            repositories = await self._recent_repositories()
        else:
            return "Error: Specify a repository or configure GITHUB_DEFAULT_USER."
        lines: list[str] = ["🔨 **Today's GitHub Commits:**"]
        try:
            async with httpx.AsyncClient(headers=self._get_headers(), timeout=15.0) as client:
                for item in repositories:
                    name = item.get("full_name")
                    response = await client.get(f"{GITHUB_API_BASE}/repos/{name}/commits?per_page=30")
                    if response.status_code != 200:
                        continue
                    for commit in response.json():
                        date_text = commit.get("commit", {}).get("author", {}).get("date", "")
                        try:
                            committed_at = datetime.fromisoformat(date_text.replace("Z", "+00:00"))
                        except ValueError:
                            continue
                        if committed_at >= since:
                            lines.append(f"• {name}: {commit.get('commit', {}).get('message', '').split(chr(10))[0]}")
            return "\n".join(lines) if len(lines) > 1 else "No commits found today."
        except Exception as exc:
            logger.exception("GitHub today commits failed: %s", exc)
            return f"GitHub API error: {exc}"

    async def _recent_repositories(self) -> list[dict[str, Any]]:
        user = self.default_user
        async with httpx.AsyncClient(headers=self._get_headers(), timeout=15.0) as client:
            url = f"{GITHUB_API_BASE}/users/{user}/repos?sort=updated&per_page=30" if user else f"{GITHUB_API_BASE}/user/repos?sort=updated&per_page=30"
            response = await client.get(url)
            response.raise_for_status()
            return response.json()

    async def get_stale_repositories(self, days: int = 30) -> str:
        """List configured-account repositories with no updates within a threshold."""
        if not self.default_user and not self.token:
            return "Error: Configure GITHUB_DEFAULT_USER or GITHUB_TOKEN."
        days = max(1, min(int(days), 3650))
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        try:
            repos = await self._recent_repositories()
            stale = []
            for repo in repos:
                updated_text = repo.get("updated_at", "")
                try:
                    updated_at = datetime.fromisoformat(updated_text.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if updated_at < cutoff:
                    stale.append(f"• {repo.get('full_name')} — last updated {updated_at.date()}")
            return "🧊 **Stale Repositories:**\n" + "\n".join(stale) if stale else f"No repositories are stale after {days} days."
        except Exception as exc:
            logger.exception("GitHub stale repositories failed: %s", exc)
            return f"GitHub API error: {exc}"

    async def summarize_commits(self, repo: str, limit: int = 10) -> str:
        """Return a concise deterministic digest of recent commit messages."""
        commits = await self.get_commits(repo, limit=max(1, min(limit, 20)))
        if commits.startswith("Error:") or commits.startswith("GitHub API error:"):
            return commits
        return commits.replace("🔨 **Recent Commits", "🧾 **Commit Summary")


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
                        "description": "Repository in 'owner/repo' format (e.g. 'akosimico/mico-core').",
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
                        "description": "Repository in 'owner/repo' format (e.g. 'akosimico/mico-core').",
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
        Tool(
            name="github_get_commits_today",
            description="Show commits made today for a repository or across the configured account's recent repositories.",
            parameters={
                "type": "object",
                "properties": {"repo": {"type": "string", "description": "Optional owner/repo. Omitting it uses the configured account."}},
                "required": [],
            },
            func=client.get_commits_today,
        ),
        Tool(
            name="github_get_stale_repositories",
            description="List configured-account repositories not updated within a number of days.",
            parameters={
                "type": "object",
                "properties": {"days": {"type": "integer", "description": "Staleness threshold in days; defaults to 30."}},
                "required": [],
            },
            func=client.get_stale_repositories,
        ),
        Tool(
            name="github_summarize_commits",
            description="Summarize the latest commits in a repository.",
            parameters={
                "type": "object",
                "properties": {
                    "repo": {"type": "string", "description": "Repository in owner/repo format."},
                    "limit": {"type": "integer", "description": "Number of commits to summarize; defaults to 10."},
                },
                "required": ["repo"],
            },
            func=client.summarize_commits,
        ),
    ]
