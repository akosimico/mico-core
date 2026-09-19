from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select

from app.database.database import Database
from app.database.models import MonitoredServiceRecord, ReminderRecord, ScheduledTaskRecord, TaskRecord
from app.tools.github import GitHubClient

if TYPE_CHECKING:
    from discord.ext import commands

logger = logging.getLogger("mico.automation.workers")

DAILY_SUMMARY = "daily_summary"
WEEKLY_DEVELOPMENT_REPORT = "weekly_development_report"
VALID_AUTOMATION_TASKS = {DAILY_SUMMARY, WEEKLY_DEVELOPMENT_REPORT}


def next_cron_run(schedule: str, after: datetime, timezone_name: str) -> datetime:
    """Return the next UTC occurrence for MICO's small cron subset.

    Automations only create ``M H * * *`` and ``M H * * D`` schedules. Keeping
    this parser local avoids another dependency while preserving portable cron.
    """
    fields = schedule.split()
    if len(fields) != 5:
        raise ValueError("Schedule must use five cron fields.")
    minute_text, hour_text, day_month, month, weekday = fields
    if day_month != "*" or month != "*":
        raise ValueError("Only daily and weekly schedules are supported.")
    try:
        minute, hour = int(minute_text), int(hour_text)
    except ValueError as exc:
        raise ValueError("Schedule hour and minute must be numeric.") from exc
    if not 0 <= minute <= 59 or not 0 <= hour <= 23:
        raise ValueError("Schedule hour or minute is out of range.")
    if weekday != "*" and (not weekday.isdigit() or not 0 <= int(weekday) <= 6):
        raise ValueError("Schedule weekday must be 0 (Monday) through 6 (Sunday).")
    try:
        local_tz = ZoneInfo(timezone_name)
    except Exception:
        local_tz = timezone.utc
    current = after.astimezone(local_tz).replace(second=0, microsecond=0)
    for offset in range(0, 8):
        candidate_date = (current + timedelta(days=offset)).date()
        candidate = datetime(candidate_date.year, candidate_date.month, candidate_date.day, hour, minute, tzinfo=local_tz)
        if weekday != "*" and candidate.weekday() != int(weekday):
            continue
        if candidate > after.astimezone(local_tz):
            return candidate.astimezone(timezone.utc)
    raise ValueError("Could not calculate the next schedule occurrence.")


class AutomationService:
    """Persistence and validation for user-configured recurring automations."""

    def __init__(self, db: Database, default_timezone: str = "Asia/Manila"):
        self.db = db
        self.default_timezone = default_timezone

    async def enable(self, user_id: str, task: str, schedule: str, channel_id: str | None) -> ScheduledTaskRecord:
        if task not in VALID_AUTOMATION_TASKS:
            raise ValueError(f"Unsupported automation task: {task}")
        now = datetime.now(timezone.utc)
        next_run = next_cron_run(schedule, now, self.default_timezone)
        async with self.db.session() as session:
            record = (await session.execute(select(ScheduledTaskRecord).where(
                ScheduledTaskRecord.user_id == str(user_id), ScheduledTaskRecord.task == task
            ))).scalar_one_or_none()
            if record is None:
                record = ScheduledTaskRecord(user_id=str(user_id), task=task, schedule=schedule, next_run=next_run, enabled=True, channel_id=channel_id)
                session.add(record)
            else:
                record.schedule, record.next_run, record.enabled, record.channel_id = schedule, next_run, True, channel_id
            await session.flush()
            await session.refresh(record)
            return record

    async def disable(self, user_id: str, task: str) -> bool:
        async with self.db.session() as session:
            record = (await session.execute(select(ScheduledTaskRecord).where(
                ScheduledTaskRecord.user_id == str(user_id), ScheduledTaskRecord.task == task
            ))).scalar_one_or_none()
            if record is None:
                return False
            record.enabled = False
            return True

    async def list_for_user(self, user_id: str) -> list[ScheduledTaskRecord]:
        async with self.db.session() as session:
            return list((await session.execute(select(ScheduledTaskRecord).where(
                ScheduledTaskRecord.user_id == str(user_id)
            ).order_by(ScheduledTaskRecord.task))).scalars().all())


class MonitoringService:
    """User-facing persistence for HTTP service health checks."""

    def __init__(self, db: Database):
        self.db = db

    async def add(self, user_id: str, channel_id: str | None, name: str, url: str, interval_seconds: int = 60) -> MonitoredServiceRecord:
        from urllib.parse import urlparse

        parsed = urlparse(url.strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Monitor URL must be a valid http:// or https:// address.")
        interval = max(15, min(int(interval_seconds), 86400))
        async with self.db.session() as session:
            record = MonitoredServiceRecord(user_id=str(user_id), channel_id=channel_id, name=name.strip(), url=url.strip(), interval_seconds=interval)
            session.add(record)
            await session.flush()
            await session.refresh(record)
            return record

    async def remove(self, user_id: str, monitor_id: int) -> bool:
        async with self.db.session() as session:
            record = (await session.execute(select(MonitoredServiceRecord).where(
                MonitoredServiceRecord.id == int(monitor_id), MonitoredServiceRecord.user_id == str(user_id)
            ))).scalar_one_or_none()
            if record is None:
                return False
            await session.delete(record)
            return True

    async def list_for_user(self, user_id: str) -> list[MonitoredServiceRecord]:
        async with self.db.session() as session:
            return list((await session.execute(select(MonitoredServiceRecord).where(
                MonitoredServiceRecord.user_id == str(user_id)
            ).order_by(MonitoredServiceRecord.id))).scalars().all())


class AutomationWorker:
    """One lifecycle-managed worker for one-time reminders and recurring jobs."""

    def __init__(self, bot: commands.Bot, db: Database, check_interval_seconds: float = 3.0,
                 default_timezone: str = "Asia/Manila", github_token: str | None = None,
                 github_default_user: str | None = None, monitor_timeout_seconds: float = 10.0):
        self.bot, self.db = bot, db
        self.check_interval, self.default_timezone = check_interval_seconds, default_timezone
        self.github = GitHubClient(token=github_token, default_user=github_default_user)
        self.monitor_timeout_seconds = monitor_timeout_seconds
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info("AutomationWorker started (polling every %ss)", self.check_interval)

    async def stop(self) -> None:
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        logger.info("AutomationWorker stopped")

    async def _run_loop(self) -> None:
        try:
            await self.bot.wait_until_ready()
            while self._running:
                for check in (self.check_and_dispatch_due_reminders, self.check_and_dispatch_due_scheduled_tasks, self.check_monitored_services):
                    try:
                        await check()
                    except Exception:
                        logger.exception("Automation polling operation failed")
                await asyncio.sleep(self.check_interval)
        except asyncio.CancelledError:
            pass

    async def _send_to_channel_or_dm(self, user_id: str, channel_id: str | None, text: str) -> bool:
        if channel_id:
            try:
                channel_key: int | str = int(channel_id) if channel_id.isdigit() else channel_id
                channel = self.bot.get_channel(channel_key)
                if channel is None and hasattr(self.bot, "fetch_channel"):
                    channel = await self.bot.fetch_channel(channel_key)
                if channel and hasattr(channel, "send"):
                    await channel.send(text)
                    return True
            except Exception as exc:
                logger.warning("Channel delivery failed for user %s: %s", user_id, exc)
        try:
            user_key: int | str = int(user_id) if user_id.isdigit() else user_id
            user = self.bot.get_user(user_key)
            if user is None and hasattr(self.bot, "fetch_user"):
                user = await self.bot.fetch_user(user_key)
            if user and hasattr(user, "send"):
                await user.send(text)
                return True
        except Exception as exc:
            logger.error("DM delivery failed for user %s: %s", user_id, exc)
        return False

    async def _dispatch_reminder(self, reminder: ReminderRecord) -> bool:
        return await self._send_to_channel_or_dm(reminder.user_id, reminder.channel_id, f"⏰ **Reminder:** <@{reminder.user_id}>, you asked to be reminded: **{reminder.content}**")

    async def check_and_dispatch_due_reminders(self) -> int:
        now = datetime.now(timezone.utc)
        async with self.db.session() as session:
            due = list((await session.execute(select(ReminderRecord).where(
                ReminderRecord.is_completed == False, ReminderRecord.remind_at <= now  # noqa: E712
            ).order_by(ReminderRecord.remind_at.asc()))).scalars().all())
            count = 0
            for reminder in due:
                if await self._dispatch_reminder(reminder):
                    reminder.is_completed = True
                    count += 1
            return count

    async def check_and_dispatch_due_scheduled_tasks(self) -> int:
        now = datetime.now(timezone.utc)
        async with self.db.session() as session:
            due = list((await session.execute(select(ScheduledTaskRecord).where(
                ScheduledTaskRecord.enabled == True, ScheduledTaskRecord.next_run <= now  # noqa: E712
            ).order_by(ScheduledTaskRecord.next_run.asc()))).scalars().all())
            for record in due:
                record.next_run = next_cron_run(record.schedule, now, self.default_timezone)
            await session.flush()
            payloads = [(record.user_id, record.channel_id, record.task) for record in due]
        sent = 0
        for user_id, channel_id, task in payloads:
            try:
                if await self._send_to_channel_or_dm(user_id, channel_id, await self._build_scheduled_message(user_id, task)):
                    sent += 1
            except Exception:
                logger.exception("Scheduled task %s failed for user %s", task, user_id)
        return sent

    @staticmethod
    def _as_utc(value: datetime) -> datetime:
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

    async def check_monitored_services(self) -> int:
        """Run due HTTP health checks and alert only on state transitions."""
        now = datetime.now(timezone.utc)
        async with self.db.session() as session:
            services = list((await session.execute(select(MonitoredServiceRecord).where(
                MonitoredServiceRecord.enabled == True  # noqa: E712
            ))).scalars().all())
            due = [service for service in services if service.last_checked_at is None or now - self._as_utc(service.last_checked_at) >= timedelta(seconds=service.interval_seconds)]
            for service in due:
                service.last_checked_at = now
            await session.flush()
            payloads = [(service.id, service.user_id, service.channel_id, service.name, service.url) for service in due]

        outcomes: list[tuple[int, str, str | None]] = []
        async with httpx.AsyncClient(timeout=self.monitor_timeout_seconds, follow_redirects=True) as client:
            for service_id, _, _, _, url in payloads:
                try:
                    response = await client.get(url)
                    outcomes.append((service_id, "healthy" if 200 <= response.status_code < 400 else "unhealthy", None if 200 <= response.status_code < 400 else f"HTTP {response.status_code}"))
                except httpx.HTTPError as exc:
                    outcomes.append((service_id, "unhealthy", str(exc) or exc.__class__.__name__))

        alerts: list[tuple[str, str | None, str]] = []
        async with self.db.session() as session:
            for service_id, status, error in outcomes:
                service = await session.get(MonitoredServiceRecord, service_id)
                if service is None:
                    continue
                previous, service.last_status, service.last_error = service.last_status, status, error
                if status == "unhealthy" and previous != "unhealthy":
                    service.failure_started_at = now
                    alerts.append((service.user_id, service.channel_id, f"🚨 **Service down:** `{service.name}` ({service.url}) — {error}"))
                elif status == "healthy" and previous == "unhealthy":
                    started = self._as_utc(service.failure_started_at) if service.failure_started_at else now
                    downtime = now - started
                    seconds = int(downtime.total_seconds())
                    service.failure_started_at = None
                    service.last_error = None
                    alerts.append((service.user_id, service.channel_id, f"✅ **Service recovered:** `{service.name}` is healthy again after {seconds // 60}m {seconds % 60}s of downtime."))
        sent = 0
        for user_id, channel_id, message in alerts:
            if await self._send_to_channel_or_dm(user_id, channel_id, message):
                sent += 1
        return sent

    async def _build_scheduled_message(self, user_id: str, task: str) -> str:
        if task == DAILY_SUMMARY:
            return await self._daily_summary(user_id)
        if task == WEEKLY_DEVELOPMENT_REPORT:
            return await self._weekly_report(user_id)
        raise ValueError(f"Unknown scheduled task {task}")

    async def _daily_summary(self, user_id: str) -> str:
        now = datetime.now(timezone.utc)
        async with self.db.session() as session:
            tasks = list((await session.execute(select(TaskRecord).where(
                TaskRecord.user_id == str(user_id), TaskRecord.status.in_(("pending", "in_progress"))
            ).order_by(TaskRecord.due_date.asc()))).scalars().all())
        def as_utc(value: datetime) -> datetime:
            return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)

        overdue = [t for t in tasks if t.due_date and as_utc(t.due_date) < now]
        upcoming = [t for t in tasks if t.due_date and as_utc(t.due_date) >= now]
        unscheduled = [t for t in tasks if not t.due_date]
        lines = ["📋 **Your Daily MICO Summary**"]
        if not tasks:
            return "\n".join(lines + ["You have no active tasks. Enjoy the clear slate!"])
        for heading, records in (("Overdue", overdue), ("Upcoming", upcoming), ("No due date", unscheduled)):
            if records:
                lines += [f"\n**{heading}**", *[f"• #{item.id} {item.title}" for item in records]]
        return "\n".join(lines)

    async def _weekly_report(self, user_id: str) -> str:
        return f"📈 **Weekly Development Report**\n\n{await self._daily_summary(user_id)}\n\n{await self.github.get_activity_summary()}"


class ReminderWorker(AutomationWorker):
    """Backward-compatible name retained for existing integrations and tests."""
