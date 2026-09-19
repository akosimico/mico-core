from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import pytest_asyncio
from discord.ext import commands
from sqlalchemy import select

from app.automation.workers import AutomationWorker, MonitoringService
from app.database.database import Database
from app.database.models import MonitoredServiceRecord


@pytest_asyncio.fixture
async def test_db(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'monitoring.db'}")
    await db.init_models()
    try:
        yield db
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_monitoring_service_validates_and_lists_records(test_db):
    service = MonitoringService(test_db)
    with pytest.raises(ValueError, match="http"):
        await service.add("user", "channel", "bad", "ftp://example.com")
    monitor = await service.add("user", "channel", "portfolio", "https://portfolio.example", 1)
    assert monitor.interval_seconds == 15
    assert (await service.list_for_user("user"))[0].name == "portfolio"
    assert await service.remove("user", monitor.id) is True


@pytest.mark.asyncio
async def test_monitor_failure_and_recovery_alerts_include_downtime(test_db):
    bot = MagicMock(spec=commands.Bot)
    channel = MagicMock()
    channel.send = AsyncMock()
    bot.get_channel.return_value = channel
    service = MonitoringService(test_db)
    monitor = await service.add("100", "200", "API", "https://api.example", 15)
    worker = AutomationWorker(bot, test_db)
    request = httpx.Request("GET", "https://api.example")

    with patch("httpx.AsyncClient.get", return_value=httpx.Response(503, request=request)):
        assert await worker.check_monitored_services() == 1
    assert "Service down" in channel.send.call_args[0][0]

    async with test_db.session() as session:
        stored = await session.get(MonitoredServiceRecord, monitor.id)
        assert stored is not None
        stored.last_checked_at = None
        stored.failure_started_at = datetime.now(timezone.utc)

    channel.send.reset_mock()
    with patch("httpx.AsyncClient.get", return_value=httpx.Response(200, request=request)):
        assert await worker.check_monitored_services() == 1
    assert "Service recovered" in channel.send.call_args[0][0]
    async with test_db.session() as session:
        stored = (await session.execute(select(MonitoredServiceRecord))).scalar_one()
        assert stored.last_status == "healthy"
        assert stored.failure_started_at is None

