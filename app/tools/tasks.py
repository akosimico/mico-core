from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from zoneinfo import ZoneInfo

from dateutil import parser
from sqlalchemy import select, update

from app.database.database import Database, get_database
from app.database.models import ProjectRecord, ReminderRecord, TaskRecord
from app.tools.base import Tool

logger = logging.getLogger("mico.tools.tasks")


def format_relative_delta(diff_seconds: float) -> str:
    """Format seconds into a clean humanized relative string (e.g. '10 seconds', '5 minutes', '2 hours')."""
    abs_diff = abs(diff_seconds)
    if abs_diff < 1:
        return "a moment"
    if abs_diff < 60:
        s = int(round(abs_diff))
        return f"{s} second{'s' if s != 1 else ''}"
    if abs_diff < 3600:
        m = int(abs_diff // 60)
        s = int(abs_diff % 60)
        if s > 0 and abs_diff < 300:
            return f"{m}m {s}s"
        return f"{m} minute{'s' if m != 1 else ''}"
    if abs_diff < 86400:
        h = int(abs_diff // 3600)
        m = int((abs_diff % 3600) // 60)
        if m > 0:
            return f"{h}h {m}m"
        return f"{h} hour{'s' if h != 1 else ''}"
    d = int(abs_diff // 86400)
    return f"{d} day{'s' if d != 1 else ''}"


def format_datetime_human(
    dt: datetime,
    tz_name: str = "Asia/Manila",
    is_completed: bool = False,
) -> str:
    """
    Format a datetime into a human-friendly string with localized time and relative duration.
    Examples:
    - Pending: "in 10 seconds (today at 09:57:10 PM PHT)"
    - Pending tomorrow: "in 14 hours (tomorrow at 10:00 AM PHT)"
    - Completed: "completed 15 seconds ago (today at 09:57:10 PM PHT)"
    - Overdue: "overdue by 2 minutes (today at 09:55 PM PHT)"
    """
    now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)

    try:
        target_tz: ZoneInfo | timezone = ZoneInfo(tz_name)
    except Exception:
        target_tz = timezone.utc

    local_dt = dt.astimezone(target_tz)
    now_local = now.astimezone(target_tz)
    if tz_name.lower() in ("asia/manila", "manila", "pht"):
        tz_abbr = "PHT"
    else:
        tz_abbr = local_dt.tzname() or tz_name

    diff_seconds = (dt - now).total_seconds()
    rel_time = format_relative_delta(diff_seconds)

    # Show seconds for short durations (< 2 minutes)
    if abs(diff_seconds) < 120:
        clock_str = local_dt.strftime("%I:%M:%S %p")
    else:
        clock_str = local_dt.strftime("%I:%M %p")

    # Date descriptor
    if local_dt.date() == now_local.date():
        day_str = "today"
    elif local_dt.date() == (now_local + timedelta(days=1)).date():
        day_str = "tomorrow"
    elif local_dt.date() == (now_local - timedelta(days=1)).date():
        day_str = "yesterday"
    else:
        day_str = local_dt.strftime("%b %d, %Y")

    if is_completed:
        return f"completed {rel_time} ago ({day_str} at {clock_str} {tz_abbr})"

    if diff_seconds >= 0:
        return f"in {rel_time} ({day_str} at {clock_str} {tz_abbr})"
    return f"overdue by {rel_time} ({day_str} at {clock_str} {tz_abbr})"


def parse_datetime_flexible(text: str, default_tz: str = "Asia/Manila") -> datetime:
    """Parse relative expressions like 'in 10 seconds', 'in 15 minutes', 'tomorrow at 10am', or standard datetime strings."""
    cleaned = text.strip().lower()
    now = datetime.now(timezone.utc)

    try:
        target_tz: ZoneInfo | timezone = ZoneInfo(default_tz)
    except Exception:
        target_tz = timezone.utc

    # Relative time pattern: "in 10s", "in 15 minutes", "in 1 hour 30 mins", "in 3 days"
    if cleaned.startswith("in "):
        matches = re.findall(
            r"(\d+)\s*(s(?:ec(?:ond)?s?)?|m(?:in(?:ute)?s?)?|h(?:(?:ou)?rs?)?|d(?:ays?)?|w(?:(?:ee)?ks?)?)\b",
            cleaned,
        )
        if matches:
            delta = timedelta()
            for val_str, unit in matches:
                val = int(val_str)
                if unit.startswith("s"):
                    delta += timedelta(seconds=val)
                elif unit.startswith("m"):
                    delta += timedelta(minutes=val)
                elif unit.startswith("h"):
                    delta += timedelta(hours=val)
                elif unit.startswith("d"):
                    delta += timedelta(days=val)
                elif unit.startswith("w"):
                    delta += timedelta(weeks=val)
            if delta.total_seconds() > 0:
                return now + delta

    # Tomorrow pattern
    if "tomorrow" in cleaned:
        time_part = re.sub(r"^.*?tomorrow(?:\s+at)?\s*", "", cleaned).strip()
        now_local = now.astimezone(target_tz)
        target_date = (now_local + timedelta(days=1)).date()
        if time_part:
            try:
                parsed_time = parser.parse(time_part).time()
                local_dt = datetime.combine(target_date, parsed_time, tzinfo=target_tz)
                return local_dt.astimezone(timezone.utc)
            except Exception:
                pass
        local_dt = datetime.combine(target_date, datetime(2000, 1, 1, 9, 0).time(), tzinfo=target_tz)
        return local_dt.astimezone(timezone.utc)

    # Standard / fuzzy date parsing
    try:
        parsed = parser.parse(text, fuzzy=True)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=target_tz).astimezone(timezone.utc)
        else:
            parsed = parsed.astimezone(timezone.utc)
        return parsed
    except Exception as exc:
        raise ValueError(f"Could not parse date/time from '{text}': {exc}") from exc


class TaskService:
    def __init__(self, db: Database | None = None, default_timezone: str = "Asia/Manila"):
        self._db = db
        self.default_timezone = default_timezone

    @property
    def db(self) -> Database:
        return self._db or get_database()

    # --- Reminders ---

    async def create_reminder(
        self,
        user_id: str,
        content: str,
        remind_at: str,
        channel_id: str | None = None,
    ) -> str:
        """Create a scheduled reminder."""
        try:
            target_time = parse_datetime_flexible(remind_at, default_tz=self.default_timezone)
        except Exception as exc:
            return f"Error: Invalid reminder time: {exc}"

        async with self.db.session() as session:
            record = ReminderRecord(
                user_id=str(user_id),
                channel_id=channel_id,
                content=content.strip(),
                remind_at=target_time,
                is_completed=False,
            )
            session.add(record)
            await session.commit()
            await session.refresh(record)

            time_str = format_datetime_human(target_time, tz_name=self.default_timezone)
            return f"✅ Reminder #{record.id} set for {time_str}: \"{record.content}\""

    async def list_reminders(
        self,
        user_id: str,
        include_completed: bool = False,
    ) -> str:
        """List active or all reminders for a user."""
        async with self.db.session() as session:
            stmt = select(ReminderRecord).where(ReminderRecord.user_id == str(user_id))
            if not include_completed:
                stmt = stmt.where(ReminderRecord.is_completed == False)
            stmt = stmt.order_by(ReminderRecord.remind_at.asc())

            result = await session.execute(stmt)
            records = list(result.scalars().all())

            if not records:
                return "You have no active reminders."

            lines = ["📋 **Your Reminders:**"]
            for r in records:
                status = "✅ Completed" if r.is_completed else "⏰ Pending"
                time_str = format_datetime_human(
                    r.remind_at,
                    tz_name=self.default_timezone,
                    is_completed=r.is_completed,
                )
                lines.append(f"• `#{r.id}` [{status}] {r.content} ({time_str})")

            return "\n".join(lines)

    # --- Tasks ---

    async def create_task(
        self,
        user_id: str,
        title: str,
        description: str | None = None,
        due_date: str | None = None,
        project_name: str | None = None,
    ) -> str:
        """Create a new task."""
        parsed_due = None
        if due_date:
            try:
                parsed_due = parse_datetime_flexible(due_date)
            except Exception:
                logger.warning("Could not parse due date '%s' for task", due_date)

        async with self.db.session() as session:
            project = None
            if project_name:
                project = (await session.execute(select(ProjectRecord).where(
                    ProjectRecord.user_id == str(user_id), ProjectRecord.name.ilike(project_name.strip())
                ))).scalar_one_or_none()
                if project is None:
                    project = ProjectRecord(user_id=str(user_id), name=project_name.strip())
                    session.add(project)
                    await session.flush()
            task = TaskRecord(
                user_id=str(user_id),
                title=title.strip(),
                description=description.strip() if description else None,
                status="pending",
                due_date=parsed_due,
                project_id=project.id if project else None,
            )
            session.add(task)
            await session.commit()
            await session.refresh(task)

            due_msg = f" (due {parsed_due.strftime('%Y-%m-%d')})" if parsed_due else ""
            return f"✅ Task #{task.id} created: \"{task.title}\"{due_msg}"

    async def create_project(self, user_id: str, name: str, description: str | None = None) -> str:
        """Create a named project for grouping tasks."""
        clean_name = name.strip()
        if not clean_name:
            return "Error: Project name cannot be empty."
        async with self.db.session() as session:
            existing = (await session.execute(select(ProjectRecord).where(
                ProjectRecord.user_id == str(user_id), ProjectRecord.name.ilike(clean_name)
            ))).scalar_one_or_none()
            if existing:
                return f"Project \"{existing.name}\" already exists (#{existing.id})."
            project = ProjectRecord(user_id=str(user_id), name=clean_name, description=description.strip() if description else None)
            session.add(project)
            await session.flush()
            return f"✅ Project #{project.id} created: \"{project.name}\""

    async def list_projects(self, user_id: str) -> str:
        """List projects and their active task counts."""
        async with self.db.session() as session:
            projects = list((await session.execute(select(ProjectRecord).where(
                ProjectRecord.user_id == str(user_id)
            ).order_by(ProjectRecord.created_at.desc()))).scalars().all())
            if not projects:
                return "You have no projects yet."
            lines = ["📁 **Your Projects:**"]
            for project in projects:
                active_count = len(list((await session.execute(select(TaskRecord).where(
                    TaskRecord.project_id == project.id, TaskRecord.status.in_(("pending", "in_progress"))
                ))).scalars().all()))
                lines.append(f"• `#{project.id}` **{project.name}** — {active_count} active task(s)")
            return "\n".join(lines)

    async def list_tasks(
        self,
        user_id: str,
        status: str | None = None,
    ) -> str:
        """List tasks for a user, optionally filtered by status ('pending', 'completed', etc.)."""
        async with self.db.session() as session:
            stmt = select(TaskRecord).where(TaskRecord.user_id == str(user_id))
            if status:
                stmt = stmt.where(TaskRecord.status == status.lower().strip())
            stmt = stmt.order_by(TaskRecord.created_at.desc())

            result = await session.execute(stmt)
            records = list(result.scalars().all())

            if not records:
                status_note = f" with status '{status}'" if status else ""
                return f"You have no tasks{status_note}."

            lines = [f"📋 **Your Tasks ({len(records)}):**"]
            for t in records:
                badge = "✅" if t.status == "completed" else "⏳"
                due_info = f" [Due: {t.due_date.strftime('%b %d')}]" if t.due_date else ""
                lines.append(f"• `#{t.id}` {badge} **{t.title}** ({t.status}){due_info}")
                if t.description:
                    lines.append(f"   _{t.description}_")

            return "\n".join(lines)

    async def complete_task(
        self,
        user_id: str,
        task_id: int,
    ) -> str:
        """Mark a task as completed."""
        try:
            numeric_id = int(task_id)
        except (ValueError, TypeError):
            return f"Error: Invalid task ID '{task_id}'. The task ID must be a number."

        async with self.db.session() as session:
            stmt = (
                update(TaskRecord)
                .where(TaskRecord.id == numeric_id, TaskRecord.user_id == str(user_id))
                .values(status="completed", updated_at=datetime.now(timezone.utc))
            )
            result = await session.execute(stmt)
            await session.commit()

            if result.rowcount > 0:
                return f"✅ Task #{numeric_id} has been marked as completed!"
            return f"❌ Could not find active task #{numeric_id} belonging to you."


def build_task_tools(service: TaskService) -> list[Tool]:
    return [
        Tool(
            name="create_reminder",
            description="Set a reminder for the user at a specified time or relative duration.",
            parameters={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "The user ID for whom the reminder is created.",
                    },
                    "content": {
                        "type": "string",
                        "description": "What to remind the user about.",
                    },
                    "remind_at": {
                        "type": "string",
                        "description": "When to remind (e.g. 'in 30 minutes', 'tomorrow at 10am', '2026-09-17 14:00').",
                    },
                    "channel_id": {
                        "type": "string",
                        "description": "Optional Discord channel ID to deliver the reminder in.",
                    },
                },
                "required": ["user_id", "content", "remind_at"],
            },
            func=service.create_reminder,
        ),
        Tool(
            name="list_reminders",
            description="List scheduled reminders for the user.",
            parameters={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "The user ID whose reminders to list.",
                    },
                    "include_completed": {
                        "type": "boolean",
                        "description": "Whether to include already completed reminders. Defaults to false.",
                    },
                },
                "required": ["user_id"],
            },
            func=service.list_reminders,
        ),
        Tool(
            name="create_task",
            description="Create a new to-do task for the user.",
            parameters={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "The user ID who owns the task.",
                    },
                    "title": {
                        "type": "string",
                        "description": "Title or short description of the task.",
                    },
                    "description": {
                        "type": "string",
                        "description": "Optional extended details or notes for the task.",
                    },
                    "due_date": {
                        "type": "string",
                        "description": "Optional due date (e.g. 'tomorrow', 'next Monday', '2026-09-20').",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "Optional project name. A missing project is created automatically.",
                    },
                },
                "required": ["user_id", "title"],
            },
            func=service.create_task,
        ),
        Tool(
            name="create_project",
            description="Create a project for grouping the user's development tasks.",
            parameters={
                "type": "object",
                "properties": {
                    "user_id": {"type": "string", "description": "The project owner."},
                    "name": {"type": "string", "description": "Project name."},
                    "description": {"type": "string", "description": "Optional project description."},
                },
                "required": ["user_id", "name"],
            },
            func=service.create_project,
        ),
        Tool(
            name="list_projects",
            description="List the user's projects and their active task counts.",
            parameters={
                "type": "object",
                "properties": {"user_id": {"type": "string", "description": "The project owner."}},
                "required": ["user_id"],
            },
            func=service.list_projects,
        ),
        Tool(
            name="list_tasks",
            description="List to-do tasks for the user, with optional filter by status.",
            parameters={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "The user ID whose tasks to fetch.",
                    },
                    "status": {
                        "type": "string",
                        "description": "Optional status filter ('pending', 'completed', or omit for all).",
                    },
                },
                "required": ["user_id"],
            },
            func=service.list_tasks,
        ),
        Tool(
            name="complete_task",
            description="Mark a specific task as completed using its task ID.",
            parameters={
                "type": "object",
                "properties": {
                    "user_id": {
                        "type": "string",
                        "description": "The user ID who owns the task.",
                    },
                    "task_id": {
                        "type": "integer",
                        "description": "The numeric ID of the task to mark completed.",
                    },
                },
                "required": ["user_id", "task_id"],
            },
            func=service.complete_task,
        ),
    ]
