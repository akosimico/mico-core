from unittest.mock import MagicMock

import pytest
from google.genai import errors

from app.ai.provider import GeminiProvider, Message


def make_server_error() -> errors.ServerError:
    return errors.ServerError(code=503, response_json={"error": {"message": "overloaded"}})


def make_client_error() -> errors.ClientError:
    return errors.ClientError(code=400, response_json={"error": {"message": "bad request"}})


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
