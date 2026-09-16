from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from openai import BadRequestError, InternalServerError, RateLimitError

from app.ai.provider import Message, OpenAICompatibleProvider

_FAKE_REQUEST = httpx.Request("POST", "https://example.invalid/chat/completions")


def make_server_error() -> InternalServerError:
    resp = httpx.Response(503, request=_FAKE_REQUEST, json={"error": {"message": "overloaded"}})
    return InternalServerError("overloaded", response=resp, body=None)


def make_rate_limit_error() -> RateLimitError:
    resp = httpx.Response(429, request=_FAKE_REQUEST, json={"error": {"message": "rate limited"}})
    return RateLimitError("rate limited", response=resp, body=None)


def make_bad_request_error() -> BadRequestError:
    resp = httpx.Response(400, request=_FAKE_REQUEST, json={"error": {"message": "bad request"}})
    return BadRequestError("bad request", response=resp, body=None)


def make_completion_response(text: str) -> MagicMock:
    response = MagicMock()
    response.choices = [MagicMock(message=MagicMock(content=text))]
    return response


def build_provider_with_fake_client(create_side_effects):
    provider = OpenAICompatibleProvider(
        api_key="fake-key",
        model_chain=["model-a", "model-b", "model-c"],
        provider_label="test-provider",
    )

    fake_client = MagicMock()
    fake_client.chat.completions.create = AsyncMock(side_effect=create_side_effects)
    provider._client = fake_client  # noqa: SLF001 - intentional test seam
    return provider, fake_client


@pytest.mark.asyncio
async def test_uses_primary_model_when_it_succeeds():
    provider, fake_client = build_provider_with_fake_client([make_completion_response("hi from model-a")])

    reply = await provider.generate([Message(role="user", content="hello")], "system prompt")

    assert reply == "hi from model-a"
    assert fake_client.chat.completions.create.call_args.kwargs["model"] == "model-a"


@pytest.mark.asyncio
async def test_falls_back_on_server_error():
    provider, fake_client = build_provider_with_fake_client(
        [make_server_error(), make_completion_response("hi from model-b")]
    )

    reply = await provider.generate([Message(role="user", content="hello")], "system prompt")

    assert reply == "hi from model-b"
    assert fake_client.chat.completions.create.call_count == 2


@pytest.mark.asyncio
async def test_falls_back_on_rate_limit():
    provider, fake_client = build_provider_with_fake_client(
        [make_rate_limit_error(), make_completion_response("hi from model-b")]
    )

    reply = await provider.generate([Message(role="user", content="hello")], "system prompt")

    assert reply == "hi from model-b"
    assert fake_client.chat.completions.create.call_count == 2


@pytest.mark.asyncio
async def test_bad_request_does_not_fall_back():
    provider, fake_client = build_provider_with_fake_client([make_bad_request_error()])

    with pytest.raises(BadRequestError):
        await provider.generate([Message(role="user", content="hello")], "system prompt")

    assert fake_client.chat.completions.create.call_count == 1


@pytest.mark.asyncio
async def test_raises_after_exhausting_chain():
    provider, _ = build_provider_with_fake_client(
        [make_server_error(), make_server_error(), make_server_error()]
    )

    with pytest.raises(InternalServerError):
        await provider.generate([Message(role="user", content="hello")], "system prompt")


def test_missing_api_key_raises_immediately():
    with pytest.raises(ValueError, match="No API key"):
        OpenAICompatibleProvider(api_key=None, model_chain=["model-a"], provider_label="groq")
