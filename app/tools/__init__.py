from __future__ import annotations

from typing import TYPE_CHECKING

from app.config import Settings, get_settings
from app.database.database import Database, get_database
from app.tools.base import Tool, ToolRegistry
from app.tools.github import GitHubClient, build_github_tools
from app.tools.system import calculator_tool, get_time_tool
from app.tools.tasks import TaskService, build_task_tools


def build_default_registry(
    db: Database | None = None,
    settings: Settings | None = None,
) -> ToolRegistry:
    """Instantiate and register all 10 standard MICO tools."""
    cfg = settings or get_settings()
    registry = ToolRegistry()

    # System tools (Tool 1 & 2)
    registry.register(get_time_tool)
    registry.register(calculator_tool)

    # Task & Reminder tools (Tools 3 to 7)
    task_service = TaskService(db=db, default_timezone=cfg.default_timezone)
    for tool in build_task_tools(task_service):
        registry.register(tool)

    # GitHub tools (Tools 8 to 10)
    gh_client = GitHubClient(
        token=cfg.github_token,
        default_user=cfg.github_default_user,
    )
    for tool in build_github_tools(gh_client):
        registry.register(tool)

    return registry


__all__ = ["Tool", "ToolRegistry", "build_default_registry"]
