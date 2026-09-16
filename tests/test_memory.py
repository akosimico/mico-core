import pytest
import pytest_asyncio
from app.ai.agent import Agent
from app.ai.memory import MemoryService
from app.ai.provider import AIProvider, Message
from app.database.database import Database
from app.database.models import Base


class EchoProvider(AIProvider):
    def __init__(self):
        self.last_system_prompt: str = ""
        self.call_history: list[list[Message]] = []

    async def generate(self, messages: list[Message], system_prompt: str) -> str:
        self.last_system_prompt = system_prompt
        self.call_history.append(list(messages))
        return f"Echo: {messages[-1].content}"


@pytest_asyncio.fixture
async def test_db(tmp_path):
    db_file = tmp_path / "test_mico.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"
    db = Database(db_url)
    await db.init_models()
    try:
        yield db
    finally:
        await db.close()


@pytest_asyncio.fixture
def memory_service(test_db):
    return MemoryService(test_db)


@pytest.mark.asyncio
async def test_short_term_history(memory_service):
    conv_id = "test-chan-1"

    # Save turns
    await memory_service.save_message(conv_id, "user", "Hello MICO")
    await memory_service.save_message(conv_id, "assistant", "Hello! How can I help?")

    history = await memory_service.get_history(conv_id)
    assert len(history) == 2
    assert history[0].role == "user"
    assert history[0].content == "Hello MICO"
    assert history[1].role == "assistant"
    assert history[1].content == "Hello! How can I help?"

    # Clear history
    await memory_service.clear_history(conv_id)
    cleared = await memory_service.get_history(conv_id)
    assert len(cleared) == 0


@pytest.mark.asyncio
async def test_long_term_and_project_memories(memory_service):
    user_id = "user_42"

    # Add general memory
    mem1 = await memory_service.add_memory(
        user_id=user_id,
        content="I prefer Python over JavaScript",
        category="preference",
        importance=4,
    )
    assert mem1.id is not None
    assert mem1.category == "preference"

    # Add project memory
    mem2 = await memory_service.add_memory(
        user_id=user_id,
        content="Portfolio frontend is built with Tailwind CSS",
        category="project",
        project_name="portfolio",
        importance=3,
    )
    assert mem2.project_name == "portfolio"

    # Query memories
    all_mems = await memory_service.get_memories(user_id)
    assert len(all_mems) == 2

    # Query by project
    project_mems = await memory_service.get_memories(user_id, project_name="portfolio")
    assert len(project_mems) == 1
    assert project_mems[0].content == "Portfolio frontend is built with Tailwind CSS"

    # Search memories
    search_res = await memory_service.search_memories(user_id, "Python")
    assert len(search_res) == 1
    assert "Python" in search_res[0].content

    # Delete memory
    deleted = await memory_service.delete_memory(mem1.id, user_id=user_id)
    assert deleted is True

    remaining = await memory_service.get_memories(user_id)
    assert len(remaining) == 1
    assert remaining[0].id == mem2.id


@pytest.mark.asyncio
async def test_prompt_formatting(memory_service):
    user_id = "user_99"
    await memory_service.add_memory(
        user_id=user_id,
        content="Prefers concise code without excess comments",
        category="preference",
    )
    await memory_service.add_memory(
        user_id=user_id,
        content="Stack: FastAPI and PostgreSQL",
        category="project",
        project_name="mico-jarvis",
    )

    formatted = await memory_service.format_memories_for_prompt(user_id=user_id)
    assert "Prefers concise code" in formatted
    assert "[mico-jarvis] Stack: FastAPI and PostgreSQL" in formatted


@pytest.mark.asyncio
async def test_agent_with_memory_integration(memory_service):
    provider = EchoProvider()
    agent = Agent(provider=provider, memory_service=memory_service)

    # First turn
    reply1 = await agent.handle_message(
        conversation_id="chan-xyz",
        user_message="My name is Alex",
        user_id="user_alex",
    )
    assert reply1 == "Echo: My name is Alex"

    # Auto-remember intent check
    reply2 = await agent.handle_message(
        conversation_id="chan-xyz",
        user_message="remember that I am working on the MICO project",
        user_id="user_alex",
    )
    assert "Echo:" in reply2

    # Verify memory was stored
    memories = await agent.get_user_memories(user_id="user_alex")
    assert any("working on the MICO project" in m.content for m in memories)

    # Next turn should include memory in prompt
    await agent.handle_message(
        conversation_id="chan-xyz",
        user_message="What was my project?",
        user_id="user_alex",
    )
    assert "working on the MICO project" in provider.last_system_prompt
