import pytest
import pytest_asyncio

from app.ai.agent import Agent
from app.ai.provider import AIProvider, Message
from app.database.database import Database
from app.tools import build_default_registry
from app.tools.base import ToolRegistry


class MockToolCallingProvider(AIProvider):
    """Simulates an LLM calling a tool on the first iteration and returning a text answer on the second."""

    def __init__(self, tool_to_call: str, tool_args: dict):
        self.tool_to_call = tool_to_call
        self.tool_args = tool_args
        self.calls: list[str] = []

    async def generate(self, messages: list[Message], system_prompt: str) -> str:
        return "Plain completion without tools"

    async def generate_with_tools(
        self,
        messages: list[Message],
        system_prompt: str,
        tool_registry: ToolRegistry,
        max_tool_iterations: int = 5,
    ) -> str:
        # Simulate model inspecting messages and calling the requested tool
        output = await tool_registry.execute(self.tool_to_call, **self.tool_args)
        self.calls.append(output)
        return f"Tool result was: {output}"


@pytest_asyncio.fixture
async def test_db(tmp_path):
    db_file = tmp_path / "test_agent_tools.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"
    db = Database(db_url)
    await db.init_models()
    try:
        yield db
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_agent_tool_calling_flow(test_db):
    registry = build_default_registry(db=test_db)
    provider = MockToolCallingProvider(
        tool_to_call="calculator",
        tool_args={"expression": "100 * 2 + 5"},
    )
    agent = Agent(provider=provider, tool_registry=registry)

    reply = await agent.handle_message(
        conversation_id="conv-tool-1",
        user_message="What is 100 * 2 + 5?",
    )

    assert "Tool result was: 100 * 2 + 5 = 205" in reply
    assert len(provider.calls) == 1
    assert "205" in provider.calls[0]


@pytest.mark.asyncio
async def test_agent_contextual_user_id_injection(test_db):
    registry = build_default_registry(db=test_db)
    # The provider does not supply user_id in tool_args; Agent should inject it
    provider = MockToolCallingProvider(
        tool_to_call="create_task",
        tool_args={"title": "Test contextual user_id"},
    )
    agent = Agent(provider=provider, tool_registry=registry)

    reply = await agent.handle_message(
        conversation_id="conv-tool-2",
        user_message="Add task Test contextual user_id",
        user_id="user_injected_123",
    )

    assert "Task #" in reply
    assert "Test contextual user_id" in reply
