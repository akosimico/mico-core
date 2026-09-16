from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from discord.ext import commands

from app.automation.workers import ReminderWorker
from app.database.database import Database
from app.database.models import ReminderRecord


@pytest_asyncio.fixture
async def test_db(tmp_path):
    db_file = tmp_path / "test_reminder_worker.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"
    db = Database(db_url)
    await db.init_models()
    try:
        yield db
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_reminder_worker_dispatches_due_reminders(test_db):
    # Mock Discord bot and channel
    mock_bot = MagicMock(spec=commands.Bot)
    mock_channel = MagicMock()
    mock_channel.send = AsyncMock()
    mock_bot.get_channel.return_value = mock_channel

    worker = ReminderWorker(bot=mock_bot, db=test_db, check_interval_seconds=0.1)

    # 1. Create a reminder due in the past (due 10 seconds ago)
    now = datetime.now(timezone.utc)
    async with test_db.session() as session:
        due_reminder = ReminderRecord(
            user_id="user_remind_1",
            channel_id="channel_999",
            content="deploy to production",
            remind_at=now - timedelta(seconds=10),
            is_completed=False,
        )
        # Create another reminder in the future (not due yet)
        future_reminder = ReminderRecord(
            user_id="user_remind_1",
            channel_id="channel_999",
            content="future task",
            remind_at=now + timedelta(hours=2),
            is_completed=False,
        )
        session.add_all([due_reminder, future_reminder])
        await session.commit()

    # 2. Run check and dispatch
    dispatched = await worker.check_and_dispatch_due_reminders()
    assert dispatched == 1

    # 3. Verify channel received message with user mention and content
    mock_channel.send.assert_called_once()
    msg = mock_channel.send.call_args[0][0]
    assert "<@user_remind_1>" in msg
    assert "deploy to production" in msg

    # 4. Verify database state: due reminder is now completed, future is not
    async with test_db.session() as session:
        from sqlalchemy import select

        records = (await session.execute(select(ReminderRecord).order_by(ReminderRecord.id))).scalars().all()
        assert records[0].is_completed is True
        assert records[1].is_completed is False

    # 5. Subsequent run should not dispatch anything
    mock_channel.send.reset_mock()
    dispatched_again = await worker.check_and_dispatch_due_reminders()
    assert dispatched_again == 0
    mock_channel.send.assert_not_called()


@pytest.mark.asyncio
async def test_reminder_worker_fallback_to_user_dm(test_db):
    mock_bot = MagicMock(spec=commands.Bot)
    # Channel lookup returns None (channel deleted or not found)
    mock_bot.get_channel.return_value = None
    mock_bot.fetch_channel = AsyncMock(side_effect=Exception("Channel not found"))

    # User DM mock
    mock_user = MagicMock()
    mock_user.send = AsyncMock()
    mock_bot.get_user.return_value = mock_user

    worker = ReminderWorker(bot=mock_bot, db=test_db, check_interval_seconds=0.1)

    now = datetime.now(timezone.utc)
    async with test_db.session() as session:
        record = ReminderRecord(
            user_id="user_dm_target",
            channel_id="deleted_chan",
            content="Drink water",
            remind_at=now - timedelta(seconds=5),
            is_completed=False,
        )
        session.add(record)
        await session.commit()

    dispatched = await worker.check_and_dispatch_due_reminders()
    assert dispatched == 1
    mock_user.send.assert_called_once()
    assert "Drink water" in mock_user.send.call_args[0][0]


@pytest.mark.asyncio
async def test_reminder_worker_lifecycle(test_db):
    mock_bot = MagicMock(spec=commands.Bot)
    mock_bot.wait_until_ready = AsyncMock()

    worker = ReminderWorker(bot=mock_bot, db=test_db, check_interval_seconds=0.05)
    await worker.start()
    assert worker._running is True
    assert worker._task is not None

    # Idempotent start
    await worker.start()

    await worker.stop()
    assert worker._running is False
