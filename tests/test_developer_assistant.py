import hashlib
import hmac
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from discord.ext import commands
from httpx import ASGITransport, AsyncClient

from app.api.routes import set_discord_bot
from app.config import Settings
from app.main import app
from app.tools.github import GitHubClient


@pytest.mark.asyncio
async def test_github_developer_queries():
    client = GitHubClient(default_user="mico")
    request = httpx.Request("GET", "https://api.github.com")
    now = datetime.now(timezone.utc)
    repos = [{"full_name": "mico/repo", "updated_at": (now - timedelta(days=60)).isoformat()}]
    commits = [{"commit": {"author": {"date": now.isoformat()}, "message": "Ship developer tools"}}]

    async def fake_get(url, *args, **kwargs):
        if "/repos?" in url:
            return httpx.Response(200, json=repos, request=request)
        if "/commits?" in url:
            return httpx.Response(200, json=commits, request=request)
        return httpx.Response(200, json=[], request=request)

    with patch("httpx.AsyncClient.get", side_effect=fake_get):
        assert "Ship developer tools" in await client.get_commits_today()
        assert "mico/repo" in await client.get_stale_repositories(days=30)
        assert "Commit Summary" in await client.summarize_commits("mico/repo")


@pytest.mark.asyncio
async def test_github_webhook_validates_and_relays():
    bot = MagicMock(spec=commands.Bot)
    channel = MagicMock()
    channel.send = AsyncMock()
    bot.get_channel.return_value = channel
    set_discord_bot(bot)
    settings = Settings(github_webhook_secret="secret", github_webhook_channel_id="123")
    payload = {"repository": {"full_name": "mico/repo"}, "sender": {"login": "mico"}, "ref": "refs/heads/main", "commits": [{"message": "Fix webhook"}]}
    import json
    body = json.dumps(payload).encode()
    signature = "sha256=" + hmac.new(b"secret", body, hashlib.sha256).hexdigest()
    with patch("app.api.routes.get_settings", return_value=settings):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as http_client:
            response = await http_client.post("/api/webhooks/github", content=body, headers={"X-GitHub-Event": "push", "X-Hub-Signature-256": signature, "Content-Type": "application/json"})
            assert response.status_code == 202
            assert response.json()["status"] == "delivered"
            bad = await http_client.post("/api/webhooks/github", content=body, headers={"X-GitHub-Event": "push", "X-Hub-Signature-256": "sha256=bad"})
            assert bad.status_code == 401
    set_discord_bot(None)
    assert "GitHub push" in channel.send.call_args[0][0]

