from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.database.database import Database
from app.database.models import ReminderRecord

if TYPE_CHECKING:
    from discord.ext import commands

logger = logging.getLogger("mico.automation.workers")


class ReminderWorker:
    """
    Background worker that continuously polls the database for due reminders
    and dispatches reminder notifications to Discord channels or DMs.
    """

    def __init__(
        self,
        bot: commands.Bot,
        db: Database,
        check_interval_seconds: float = 3.0,
    ):
        self.bot = bot
        self.db = db
        self.check_interval = check_interval_seconds
        self._task: asyncio.Task | None = None
        self._running = False

    async def start(self) -> None:
        """Start the reminder background worker task."""
        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "ReminderWorker started (polling due reminders every %ss)",
            self.check_interval,
        )

    async def stop(self) -> None:
        """Stop the background worker."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):
                pass
        logger.info("ReminderWorker stopped")

    async def _run_loop(self) -> None:
        """Wait for Discord bot gateway connection, then start polling."""
        try:
            await self.bot.wait_until_ready()
            logger.info("Discord bot is ready — ReminderWorker beginning polling loop.")
            while self._running:
                try:
                    await self.check_and_dispatch_due_reminders()
                except Exception as exc:
                    logger.exception("Error during reminder check: %s", exc)
                await asyncio.sleep(self.check_interval)
        except asyncio.CancelledError:
            pass

    async def check_and_dispatch_due_reminders(self) -> int:
        """Query and send all due pending reminders."""
        now = datetime.now(timezone.utc)
        async with self.db.session() as session:
            stmt = (
                select(ReminderRecord)
                .where(ReminderRecord.is_completed == False)  # noqa: E712
                .where(ReminderRecord.remind_at <= now)
                .order_by(ReminderRecord.remind_at.asc())
            )
            result = await session.execute(stmt)
            due_records = list(result.scalars().all())

            if not due_records:
                return 0

            dispatched_count = 0
            for reminder in due_records:
                try:
                    sent = await self._dispatch_reminder(reminder)
                    if sent:
                        dispatched_count += 1
                except Exception as exc:
                    logger.exception("Failed to dispatch reminder #%s: %s", reminder.id, exc)
                finally:
                    # Always mark completed to prevent infinite notification loops
                    reminder.is_completed = True

            await session.commit()
            return dispatched_count

    async def _dispatch_reminder(self, reminder: ReminderRecord) -> bool:
        """Send the reminder notification to Discord."""
        message_text = (
            f"⏰ **Reminder:** <@{reminder.user_id}>, you asked to be reminded: **{reminder.content}**"
        )

        # 1. Try sending to the channel where the reminder was created
        if reminder.channel_id:
            try:
                chan_id: int | str = (
                    int(reminder.channel_id)
                    if reminder.channel_id.isdigit()
                    else reminder.channel_id
                )
                channel = self.bot.get_channel(chan_id)
                if channel is None and hasattr(self.bot, "fetch_channel"):
                    channel = await self.bot.fetch_channel(chan_id)
                if channel and hasattr(channel, "send"):
                    await channel.send(message_text)
                    logger.info("Dispatched reminder #%s to channel %s", reminder.id, reminder.channel_id)
                    return True
            except Exception as exc:
                logger.warning(
                    "Failed to deliver reminder #%s to channel %s: %s. Falling back to DM.",
                    reminder.id,
                    reminder.channel_id,
                    exc,
                )

        # 2. Fallback to direct message (DM)
        try:
            u_id: int | str = (
                int(reminder.user_id)
                if reminder.user_id.isdigit()
                else reminder.user_id
            )
            user = self.bot.get_user(u_id)
            if user is None and hasattr(self.bot, "fetch_user"):
                user = await self.bot.fetch_user(u_id)
            if user and hasattr(user, "send"):
                await user.send(message_text)
                logger.info("Dispatched reminder #%s to user DM %s", reminder.id, reminder.user_id)
                return True
        except Exception as exc:
            logger.error("Failed to deliver reminder #%s to user DM %s: %s", reminder.id, reminder.user_id, exc)

        return False
