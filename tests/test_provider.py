from unittest.mock import AsyncMock, MagicMock

import pytest
from google.genai import errors

from app.ai.provider import AIProvider, GeminiProvider, Message, QuotaFailoverProvider
from app.tools.base import ToolRegistry
from app.tools.system import get_time_tool


def make_server_error() -> errors.ServerError:
    return errors.ServerError(code=503, response_json={"error": {"message": "overloaded"}})


def make_client_error() -> errors.ClientError:
    return errors.ClientError(code=400, response_json={"error": {"message": "bad request"}})


def make_model_not_found_error() -> errors.ClientError:
    return errors.ClientError(code=404, response_json={"error": {"message": "model not found", "status": "NOT_FOUND"}})


def make_quota_error() -> errors.ClientError:
    return errors.ClientError(code=429, response_json={"error": {"message": "quota exhausted", "status": "RESOURCE_EXHAUSTED"}})


class StubProvider(AIProvider):
    def __init__(self, response: str | Exception):
        self.response = response
        self.calls = 0

    async def generate(self, messages: list[Message], system_prompt: str) -> str:
        self.calls += 1
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def build_provider_with_fake_client(chat_create_side_effects):
    """
    Builds a GeminiProvider without hitting the real API: constructs it
    normally (cheap, no network call), then swaps in a fake `_client` whose
    `.chats.create(...)` returns pre-scripted results/errors in order.
    """
    provider = GeminiProvider(api_key="fake-key", model_chain=["model-a", "model-b", "model-c"])

    fake_client = MagicMock()
    fake_client.chats.create.side_effect = chat_create_side_effects
    provider._client = fake_client  # noqa: SLF001 - intentional test seam
    return provider, fake_client


def make_chat_returning(text: str) -> MagicMock:
    chat = MagicMock()
    chat.send_message.return_value = MagicMock(text=text)
    return chat


@pytest.mark.asyncio
async def test_uses_primary_model_when_it_succeeds():
    provider, fake_client = build_provider_with_fake_client([make_chat_returning("hi from model-a")])

    reply = await provider.generate([Message(role="user", content="hello")], "system prompt")

    assert reply == "hi from model-a"
    assert fake_client.chats.create.call_args.kwargs["model"] == "model-a"


@pytest.mark.asyncio
async def test_falls_back_to_next_model_on_server_error():
    provider, fake_client = build_provider_with_fake_client(
        [make_server_error(), make_chat_returning("hi from model-b")]
    )

    reply = await provider.generate([Message(role="user", content="hello")], "system prompt")

    assert reply == "hi from model-b"
    assert fake_client.chats.create.call_count == 2
    assert fake_client.chats.create.call_args.kwargs["model"] == "model-b"


@pytest.mark.asyncio
async def test_falls_back_through_multiple_models():
    provider, fake_client = build_provider_with_fake_client(
        [make_server_error(), make_server_error(), make_chat_returning("hi from model-c")]
    )

    reply = await provider.generate([Message(role="user", content="hello")], "system prompt")

    assert reply == "hi from model-c"
    assert fake_client.chats.create.call_count == 3


@pytest.mark.asyncio
async def test_raises_last_error_if_every_model_fails():
    provider, _ = build_provider_with_fake_client(
        [make_server_error(), make_server_error(), make_server_error()]
    )

    with pytest.raises(errors.ServerError):
        await provider.generate([Message(role="user", content="hello")], "system prompt")


@pytest.mark.asyncio
async def test_client_error_does_not_fall_back():
    """A 4xx (bad key, bad request, quota) shouldn't burn through the whole
    chain — another model won't fix a bad API key."""
    provider, fake_client = build_provider_with_fake_client([make_client_error()])

    with pytest.raises(errors.ClientError):
        await provider.generate([Message(role="user", content="hello")], "system prompt")

    assert fake_client.chats.create.call_count == 1


@pytest.mark.asyncio
async def test_falls_back_when_primary_model_is_not_found():
    provider, fake_client = build_provider_with_fake_client(
        [make_model_not_found_error(), make_chat_returning("hi from model-b")]
    )

    reply = await provider.generate([Message(role="user", content="hello")], "system prompt")

    assert reply == "hi from model-b"
    assert fake_client.chats.create.call_count == 2


@pytest.mark.asyncio
async def test_uses_groq_when_gemini_quota_is_exhausted():
    primary = StubProvider(make_quota_error())
    fallback = StubProvider("reply from groq")
    provider = QuotaFailoverProvider(primary, fallback, "Gemini", "Groq")

    reply = await provider.generate([Message(role="user", content="hello")], "system prompt")

    assert reply == "reply from groq"
    assert primary.calls == 1
    assert fallback.calls == 1


@pytest.mark.asyncio
async def test_does_not_fail_over_for_non_quota_gemini_errors():
    primary = StubProvider(make_client_error())
    fallback = StubProvider("reply from groq")
    provider = QuotaFailoverProvider(primary, fallback, "Gemini", "Groq")

    with pytest.raises(errors.ClientError):
        await provider.generate([Message(role="user", content="hello")], "system prompt")
    assert fallback.calls == 0


@pytest.mark.asyncio
async def test_gemini_generate_with_tools():
    provider, fake_client = build_provider_with_fake_client([])

    fake_aio = MagicMock()
    fake_chat = MagicMock()

    call_mock = MagicMock()
    call_mock.name = "get_time"
    call_mock.args = {"timezone_name": "UTC"}

    resp1 = MagicMock()
    resp1.function_calls = [call_mock]
    resp1.text = None

    resp2 = MagicMock()
    resp2.function_calls = None
    resp2.text = "The time in UTC is 12:00 PM."

    fake_chat.send_message = AsyncMock(side_effect=[resp1, resp2])
    fake_aio.chats.create = MagicMock(return_value=fake_chat)
    fake_client.aio = fake_aio

    registry = ToolRegistry()
    registry.register(get_time_tool)

    reply = await provider.generate_with_tools(
        messages=[Message(role="user", content="What time is it?")],
        system_prompt="sys prompt",
        tool_registry=registry,
    )

    assert "The time in UTC is 12:00 PM." in reply
    assert fake_chat.send_message.call_count == 2
