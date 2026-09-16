import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.ai.agent import Agent
from app.ai.memory import MemoryService
from app.ai.provider import AIProvider, Message
from app.api.routes import set_agent
from app.database.database import Database, set_database
from app.main import app


class MockProvider(AIProvider):
    async def generate(self, messages: list[Message], system_prompt: str) -> str:
        return f"Model reply to: {messages[-1].content}"


@pytest_asyncio.fixture
async def client_and_agent(tmp_path):
    db_file = tmp_path / "test_api_mico.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"
    db = Database(db_url)
    await db.init_models()
    set_database(db)

    mem_service = MemoryService(db)
    provider = MockProvider()
    agent = Agent(provider=provider, memory_service=mem_service)
    set_agent(agent)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac, agent

    await db.close()
    set_database(None)
    set_agent(None)


@pytest.mark.asyncio
async def test_root_endpoint(client_and_agent):
    client, _ = client_and_agent
    res = await client.get("/")
    assert res.status_code == 200
    data = res.json()
    assert data["app"] == "MICO"
    assert data["status"] == "online"


@pytest.mark.asyncio
async def test_health_endpoint(client_and_agent):
    client, _ = client_and_agent
    res = await client.get("/api/health")
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "ok"
    assert data["database"] == "connected"


@pytest.mark.asyncio
async def test_chat_endpoint(client_and_agent):
    client, _ = client_and_agent
    payload = {
        "conversation_id": "api-conv-1",
        "message": "Hello from API!",
        "user_id": "user_api_1",
    }
    res = await client.post("/api/chat", json=payload)
    assert res.status_code == 200
    data = res.json()
    assert "Model reply to: Hello from API!" in data["reply"]
    assert data["conversation_id"] == "api-conv-1"


@pytest.mark.asyncio
async def test_memories_crud_endpoints(client_and_agent):
    client, agent = client_and_agent

    # 1. Create memory
    create_payload = {
        "user_id": "u100",
        "content": "Uses PostgreSQL on Windows",
        "category": "environment",
        "importance": 3,
    }
    create_res = await client.post("/api/memories", json=create_payload)
    assert create_res.status_code == 200
    created_data = create_res.json()
    mem_id = created_data["id"]
    assert created_data["user_id"] == "u100"
    assert created_data["content"] == "Uses PostgreSQL on Windows"

    # 2. List memories
    list_res = await client.get("/api/memories/u100")
    assert list_res.status_code == 200
    list_data = list_res.json()
    assert len(list_data) == 1
    assert list_data[0]["id"] == mem_id

    # 3. Delete memory
    delete_res = await client.delete(f"/api/memories/{mem_id}?user_id=u100")
    assert delete_res.status_code == 200
    assert delete_res.json()["deleted"] is True

    # 4. Verify empty list
    list_after = await client.get("/api/memories/u100")
    assert len(list_after.json()) == 0
