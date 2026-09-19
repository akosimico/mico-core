from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from discord.ext import commands
from sqlalchemy import select

from app.automation.workers import (
    DAILY_SUMMARY,
    AutomationService,
    AutomationWorker,
    next_cron_run,
)
from app.database.database import Database
from app.database.models import ScheduledTaskRecord, TaskRecord


@pytest_asyncio.fixture
async def test_db(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'automation.db'}")
    await db.init_models()
    try:
        yield db
    finally:
        await db.close()


def test_next_cron_run_supports_daily_and_weekly_schedules():
    after = datetime(2026, 9, 20, 23, 0, tzinfo=timezone.utc)  # Monday 07:00 PHT
    daily = next_cron_run("0 8 * * *", after, "Asia/Manila")
    weekly = next_cron_run("0 9 * * 0", after, "Asia/Manila")
    assert daily > after
    assert daily.astimezone(timezone(timedelta(hours=8))).hour == 8
    assert weekly.weekday() == 0
    with pytest.raises(ValueError):
        next_cron_run("invalid", after, "Asia/Manila")


@pytest.mark.asyncio
async def test_automation_service_enables_updates_disables_and_lists(test_db):
    service = AutomationService(test_db)
    created = await service.enable("user1", DAILY_SUMMARY, "0 8 * * *", "42")
    assert created.enabled and created.channel_id == "42"
    updated = await service.enable("user1", DAILY_SUMMARY, "30 8 * * *", "99")
    assert updated.id == created.id and updated.schedule == "30 8 * * *"
    assert len(await service.list_for_user("user1")) == 1
    assert await service.disable("user1", DAILY_SUMMARY) is True
    assert (await service.list_for_user("user1"))[0].enabled is False


@pytest.mark.asyncio
async def test_worker_dispatches_daily_summary_and_advances_next_run(test_db):
    bot = MagicMock(spec=commands.Bot)
    channel = MagicMock()
    channel.send = AsyncMock()
    bot.get_channel.return_value = channel
    now = datetime.now(timezone.utc)
    async with test_db.session() as session:
        session.add_all([
            ScheduledTaskRecord(user_id="100", task=DAILY_SUMMARY, schedule="0 8 * * *", next_run=now - timedelta(minutes=1), enabled=True, channel_id="200"),
            TaskRecord(user_id="100", title="Late task", status="pending", due_date=now - timedelta(days=1)),
            TaskRecord(user_id="100", title="Upcoming task", status="pending", due_date=now + timedelta(days=1)),
        ])
    worker = AutomationWorker(bot, test_db)
    assert await worker.check_and_dispatch_due_scheduled_tasks() == 1
    message = channel.send.call_args[0][0]
    assert "Daily MICO Summary" in message
    assert "Overdue" in message and "Late task" in message
    async with test_db.session() as session:
        record = (await session.execute(select(ScheduledTaskRecord))).scalar_one()
        persisted_next_run = record.next_run.replace(tzinfo=timezone.utc) if record.next_run.tzinfo is None else record.next_run
        assert persisted_next_run > now
