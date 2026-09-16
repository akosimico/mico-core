from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from dateutil import parser
from sqlalchemy import select, update

from app.database.database import Database, get_database
from app.database.models import ReminderRecord, TaskRecord
from app.tools.base import Tool

logger = logging.getLogger("mico.tools.tasks")


def parse_datetime_flexible(text: str) -> datetime:
    """Parse relative expressions like 'in 10 minutes', 'tomorrow at 3pm', or standard datetime strings."""
    cleaned = text.strip().lower()
    now = datetime.now(timezone.utc)

    # Relative time pattern: "in 15 minutes", "in 2 hours", "in 3 days"
    rel_match = re.match(
        r"^in\s+(\d+)\s*(m|min|minute|minutes|h|hr|hour|hours|d|day|days)$", cleaned
    )
    if rel_match:
        val = int(rel_match.group(1))
        unit = rel_match.group(2)
        if unit.startswith("m"):
            return now + timedelta(minutes=val)
        if unit.startswith("h"):
            return now + timedelta(hours=val)
        if unit.startswith("d"):
            return now + timedelta(days=val)

    # Tomorrow pattern
    if "tomorrow" in cleaned:
        time_part = re.sub(r"^.*?tomorrow(?:\s+at)?\s*", "", cleaned).strip()
        target_date = (now + timedelta(days=1)).date()
        if time_part:
            try:
                parsed_time = parser.parse(time_part).time()
                return datetime.combine(target_date, parsed_time, tzinfo=timezone.utc)
            except Exception:
                pass
        return datetime.combine(target_date, datetime(2000, 1, 1, 9, 0).time(), tzinfo=timezone.utc)

    # Standard / fuzzy date parsing
    try:
        parsed = parser.parse(text, fuzzy=True)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except Exception as exc:
        raise ValueError(f"Could not parse date/time from '{text}': {exc}") from exc


class TaskService:
    def __init__(self, db: Database | None = None):
        self._db = db

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
            target_time = parse_datetime_flexible(remind_at)
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

            time_str = target_time.strftime("%Y-%m-%d %I:%M %p UTC")
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
                time_str = r.remind_at.strftime("%Y-%m-%d %I:%M %p UTC")
                lines.append(f"• `#{r.id}` [{status}] {r.content} (At: {time_str})")

            return "\n".join(lines)

    # --- Tasks ---

    async def create_task(
        self,
        user_id: str,
        title: str,
        description: str | None = None,
        due_date: str | None = None,
    ) -> str:
        """Create a new task."""
        parsed_due = None
        if due_date:
            try:
                parsed_due = parse_datetime_flexible(due_date)
            except Exception:
                logger.warning("Could not parse due date '%s' for task", due_date)

        async with self.db.session() as session:
            task = TaskRecord(
                user_id=str(user_id),
                title=title.strip(),
                description=description.strip() if description else None,
                status="pending",
                due_date=parsed_due,
            )
            session.add(task)
            await session.commit()
            await session.refresh(task)

            due_msg = f" (due {parsed_due.strftime('%Y-%m-%d')})" if parsed_due else ""
            return f"✅ Task #{task.id} created: \"{task.title}\"{due_msg}"

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
        async with self.db.session() as session:
            stmt = (
                update(TaskRecord)
                .where(TaskRecord.id == int(task_id), TaskRecord.user_id == str(user_id))
                .values(status="completed", updated_at=datetime.now(timezone.utc))
            )
            result = await session.execute(stmt)
            await session.commit()

            if result.rowcount > 0:
                return f"✅ Task #{task_id} has been marked as completed!"
            return f"❌ Could not find active task #{task_id} belonging to you."


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
                },
                "required": ["user_id", "title"],
            },
            func=service.create_task,
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
