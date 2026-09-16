import pytest

from app.ai.agent import Agent
from app.ai.provider import AIProvider, Message


class FakeProvider(AIProvider):
    """Echoes the last user message, prefixed - lets us test Agent logic
    (history tracking, trimming, reset) without hitting a real API."""

    def __init__(self):
        self.calls: list[list[Message]] = []

    async def generate(self, messages: list[Message], system_prompt: str) -> str:
        self.calls.append(list(messages))
        return f"echo: {messages[-1].content}"


@pytest.mark.asyncio
async def test_handle_message_returns_reply():
    agent = Agent(provider=FakeProvider())
    reply = await agent.handle_message("chan-1", "hello")
    assert reply == "echo: hello"


@pytest.mark.asyncio
async def test_history_persists_within_conversation():
    provider = FakeProvider()
    agent = Agent(provider=provider)

    await agent.handle_message("chan-1", "first")
    await agent.handle_message("chan-1", "second")

    # Second call should have seen the first exchange in its history.
    second_call_messages = provider.calls[1]
    assert len(second_call_messages) == 3  # user, assistant, user
    assert second_call_messages[0].content == "first"


@pytest.mark.asyncio
async def test_history_is_isolated_per_conversation():
    provider = FakeProvider()
    agent = Agent(provider=provider)

    await agent.handle_message("chan-1", "hello from chan 1")
    await agent.handle_message("chan-2", "hello from chan 2")

    chan_2_messages = provider.calls[1]
    assert len(chan_2_messages) == 1
    assert chan_2_messages[0].content == "hello from chan 2"


@pytest.mark.asyncio
async def test_history_trims_to_max_length():
    agent = Agent(provider=FakeProvider(), max_history_messages=4)

    for i in range(5):
        await agent.handle_message("chan-1", f"message {i}")

    history = agent._history["chan-1"]  # noqa: SLF001 - fine in a test
    assert len(history) == 4


@pytest.mark.asyncio
async def test_reset_clears_history():
    provider = FakeProvider()
    agent = Agent(provider=provider)

    await agent.handle_message("chan-1", "hello")
    agent.reset("chan-1")
    await agent.handle_message("chan-1", "hello again")

    second_call_messages = provider.calls[1]
    assert len(second_call_messages) == 1


@pytest.mark.asyncio
async def test_failed_generation_does_not_poison_history():
    class FailingProvider(AIProvider):
        async def generate(self, messages, system_prompt):
            raise RuntimeError("boom")

    agent = Agent(provider=FailingProvider())

    with pytest.raises(RuntimeError):
        await agent.handle_message("chan-1", "hello")

    assert agent._history.get("chan-1", []) == []  # noqa: SLF001
