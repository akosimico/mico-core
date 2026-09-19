from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.database.database import Database
from app.database.models import AuditLog
from app.tools.pc import AUTO_EXECUTE, CONFIRM_REQUIRED, PCActionService, permission_level


@pytest_asyncio.fixture
async def test_db(tmp_path):
    db = Database(f"sqlite+aiosqlite:///{tmp_path / 'pc_agent.db'}")
    await db.init_models()
    try:
        yield db
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_pc_agent_confines_safe_actions_and_audits(test_db, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "notes.txt").write_text("MICO local agent", encoding="utf-8")
    service = PCActionService(test_db, workspace_root=str(workspace))
    assert permission_level("read_file") == AUTO_EXECUTE
    assert permission_level("delete_file") == CONFIRM_REQUIRED

    assert "MICO local agent" in await service.read_file("user1", "notes.txt")
    assert "notes.txt" in await service.search_files("user1", "notes")
    with pytest.raises(ValueError, match="workspace"):
        service._path("../outside.txt")

    async with test_db.session() as session:
        audits = list((await session.execute(select(AuditLog).where(AuditLog.user_id == "user1"))).scalars().all())
        assert {audit.action for audit in audits} == {"read_file", "search_files"}
        assert all(audit.status == "SUCCESS" for audit in audits)


@pytest.mark.asyncio
async def test_destructive_pc_action_requires_confirmation_then_logs_result(test_db, tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    target = workspace / "remove-me.txt"
    target.write_text("temporary", encoding="utf-8")
    service = PCActionService(test_db, workspace_root=str(workspace))

    queued = await service.request_confirmation("user1", "delete_file", {"path": "remove-me.txt"})
    token = queued.split("!confirm ")[1].split()[0]
    assert target.exists()
    result = await service.confirm("user1", token)
    assert "Deleted" in result
    assert not target.exists()

    async with test_db.session() as session:
        statuses = [audit.status for audit in (await session.execute(select(AuditLog).where(AuditLog.action == "delete_file"))).scalars().all()]
        assert statuses == ["PENDING", "SUCCESS"]
