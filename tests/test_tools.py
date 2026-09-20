from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio

from app.database.database import Database
from app.tools import build_default_registry
from app.tools.base import Tool, ToolRegistry
from app.tools.github import GitHubClient
from app.tools.system import calculator, get_time
from app.tools.tasks import TaskService


@pytest_asyncio.fixture
async def test_db(tmp_path):
    db_file = tmp_path / "test_tools.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"
    db = Database(db_url)
    await db.init_models()
    try:
        yield db
    finally:
        await db.close()


# --- System Tools (Tools 1 & 2) ---


def test_get_time():
    res_utc = get_time("UTC")
    assert "UTC" in res_utc

    res_tokyo = get_time("Asia/Tokyo")
    assert "Asia/Tokyo" in res_tokyo

    res_alias = get_time("pst")
    assert "America/Los_Angeles" in res_alias

    res_local = get_time("local")
    assert "current local time" in res_local


def test_calculator_valid():
    assert "25" in calculator("5 * 5")
    assert "14" in calculator("sqrt(144) + 2")
    assert "3.14" in calculator("round(pi, 2)")
    assert "8" in calculator("2 ** 3")
    assert "10" in calculator("(50 - 20) / 3")


def test_calculator_errors():
    assert "Division by zero" in calculator("10 / 0")
    assert "Calculation error" in calculator("__import__('os').system('ls')")
    assert "cannot be empty" in calculator("   ")


# --- Task and Reminder Tools (Tools 3 to 7) ---


@pytest.mark.asyncio
async def test_tasks_and_reminders(test_db):
    service = TaskService(db=test_db)
    user_id = "user_test_tools"

    project = await service.create_project(user_id=user_id, name="MICO")
    assert "Project #" in project

    # Tool 3: create_reminder
    res_remind = await service.create_reminder(
        user_id=user_id,
        content="Deploy portfolio",
        remind_at="in 30 minutes",
    )
    assert "Reminder #" in res_remind
    assert "Deploy portfolio" in res_remind

    # Tool 4: list_reminders
    res_list_remind = await service.list_reminders(user_id=user_id)
    assert "Deploy portfolio" in res_list_remind

    # Tool 5: create_task
    res_task = await service.create_task(
        user_id=user_id,
        title="Write integration tests",
        description="Cover all 10 tools",
        due_date="tomorrow",
        project_name="MICO",
    )
    assert "Task #" in res_task
    assert "Write integration tests" in res_task

    # Tool 6: list_tasks
    res_tasks = await service.list_tasks(user_id=user_id)
    assert "Write integration tests" in res_tasks
    assert "pending" in res_tasks
    assert "MICO" in await service.list_projects(user_id=user_id)

    # Tool 7: complete_task
    res_done = await service.complete_task(user_id=user_id, task_id=1)
    assert "marked as completed" in res_done

    res_tasks_after = await service.list_tasks(user_id=user_id, status="completed")
    assert "Write integration tests" in res_tasks_after


# --- GitHub Tools (Tools 8 to 10) ---


@pytest.mark.asyncio
async def test_github_tools_mocked():
    client = GitHubClient(token="mock-token", default_user="testuser")

    # Mock get_repositories
    mock_repos = [
        {
            "full_name": "testuser/repo1",
            "html_url": "https://github.com/testuser/repo1",
            "stargazers_count": 10,
            "language": "Python",
            "description": "A great repo",
        }
    ]
    req = httpx.Request("GET", "https://api.github.com")
    with patch("httpx.AsyncClient.get", return_value=httpx.Response(200, json=mock_repos, request=req)):
        res_repos = await client.get_repositories("testuser")
        assert "testuser/repo1" in res_repos
        assert "Python" in res_repos

    # Mock get_commits
    mock_commits = [
        {
            "sha": "abcdef123456",
            "commit": {
                "author": {"name": "Test Author", "date": "2026-09-16T12:00:00Z"},
                "message": "Initial commit\n\nMore details",
            },
        }
    ]
    with patch("httpx.AsyncClient.get", return_value=httpx.Response(200, json=mock_commits, request=req)):
        res_commits = await client.get_commits("testuser/repo1")
        assert "abcdef1" in res_commits
        assert "Initial commit" in res_commits
        assert "Test Author" in res_commits

    # Mock get_issues
    mock_issues = [
        {
            "number": 1,
            "title": "Bug in main loop",
            "user": {"login": "issue_author"},
        },
        {
            "number": 2,
            "title": "Pull Request title",
            "user": {"login": "pr_author"},
            "pull_request": {},  # Should be filtered out
        },
    ]
    with patch("httpx.AsyncClient.get", return_value=httpx.Response(200, json=mock_issues, request=req)):
        res_issues = await client.get_issues("testuser/repo1")
        assert "#1" in res_issues
        assert "Bug in main loop" in res_issues
        assert "Pull Request title" not in res_issues  # excluded PR


# --- Tool Registry ---


@pytest.mark.asyncio
async def test_tool_registry(test_db):
    registry = build_default_registry(db=test_db)
    tool_names = [t.name for t in registry.list_tools()]

    expected_tools = [
        "get_time",
        "calculator",
        "create_reminder",
        "list_reminders",
        "create_task",
        "list_tasks",
        "complete_task",
        "github_get_repositories",
        "github_get_commits",
        "github_get_issues",
    ]

    for t in expected_tools:
        assert t in tool_names

    # Test schema exports
    openai_tools = registry.to_openai_tools()
    assert len(openai_tools) == 28
    assert openai_tools[0]["type"] == "function"

    gemini_decls = registry.to_gemini_declarations()
    assert len(gemini_decls) == 28
    assert "name" in gemini_decls[0]

    # Test direct execution
    calc_res = await registry.execute("calculator", expression="10 + 20")
    assert "30" in calc_res

    # Test non-existent tool
    err_res = await registry.execute("non_existent_tool")
    assert "is not registered" in err_res


def test_flexible_datetime_parsing():
    from zoneinfo import ZoneInfo
    from app.tools.tasks import format_datetime_human, format_relative_delta, parse_datetime_flexible

    now = datetime.now(timezone.utc)

    # 10 seconds parsing
    dt_10s = parse_datetime_flexible("in 10s")
    assert dt_10s > now
    assert 8 <= (dt_10s - now).total_seconds() <= 12

    dt_15m = parse_datetime_flexible("in 15 mins")
    assert dt_15m > now
    assert (dt_15m - now).total_seconds() >= 800

    dt_compound = parse_datetime_flexible("in 1 hour 30 mins")
    assert (dt_compound - now).total_seconds() >= 5300

    dt_2d = parse_datetime_flexible("in 2 days")
    assert (dt_2d - now).total_seconds() >= 170000

    # Tomorrow in Asia/Manila (UTC+8) -> local hour is 10
    dt_tomorrow = parse_datetime_flexible("tomorrow at 10am", default_tz="Asia/Manila")
    assert dt_tomorrow > now
    assert dt_tomorrow.astimezone(ZoneInfo("Asia/Manila")).hour == 10

    # Humanized relative delta tests
    assert format_relative_delta(10) == "10 seconds"
    assert format_relative_delta(1) == "1 second"
    assert format_relative_delta(60) == "1 minute"
    assert format_relative_delta(7200) == "2 hours"

    # Humanized formatting in Asia/Manila timezone
    human_str = format_datetime_human(dt_10s, tz_name="Asia/Manila")
    assert "PHT" in human_str
    assert "in 10 seconds" in human_str or "in 9 seconds" in human_str or "in 11 seconds" in human_str

    with pytest.raises(ValueError, match="Could not parse date/time"):
        parse_datetime_flexible("not a real date at all xyz")


@pytest.mark.asyncio
async def test_complete_task_invalid_id(test_db):
    service = TaskService(db=test_db)
    res = await service.complete_task(user_id="user1", task_id="not-a-number")  # type: ignore[arg-type]
    assert "Invalid task ID" in res
