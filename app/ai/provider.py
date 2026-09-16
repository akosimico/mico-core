from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.config import Settings

logger = logging.getLogger("mico.ai.provider")


@dataclass
class Message:
    role: str  # "user" or "assistant"
    content: str


class AIProvider(ABC):
    """
    Common interface every AI backend implements.

    To add a new backend (OpenAI, OpenRouter, a local model, ...):
      1. Subclass AIProvider and implement `generate`.
      2. Add one branch to `get_provider()` below.
    Nothing in app/ai/agent.py or app/bot/ needs to change.
    """

    @abstractmethod
    async def generate(self, messages: list[Message], system_prompt: str) -> str:
        """Given the conversation so far and a system prompt, return the reply text."""
        raise NotImplementedError


class GeminiProvider(AIProvider):
    def __init__(self, api_key: str | None, model_chain: list[str]):
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY is not set. Add it to your .env (see .env.example)."
            )
        if not model_chain:
            raise ValueError("GeminiProvider needs at least one model name.")

        # Uses the current `google-genai` SDK. The older `google-generativeai`
        # package is deprecated as of 2025 — don't reintroduce it.
        from google import genai

        self._client = genai.Client(api_key=api_key)
        self._model_chain = model_chain  # primary first, then fallbacks in order

    async def generate(self, messages: list[Message], system_prompt: str) -> str:
        # The SDK's sync client is used here; run it off the event loop so
        # the bot stays responsive to other Discord events while waiting.
        return await asyncio.to_thread(self._generate_sync, messages, system_prompt)

    def _generate_sync(self, messages: list[Message], system_prompt: str) -> str:
        from google.genai import errors, types

        # Everything except the final message becomes chat history;
        # the final message is sent as the new turn.
        history = [
            types.Content(
                role="user" if m.role == "user" else "model",
                parts=[types.Part(text=m.content)],
            )
            for m in messages[:-1]
        ]

        last_error: Exception | None = None

        for model_name in self._model_chain:
            try:
                chat = self._client.chats.create(
                    model=model_name,
                    config=types.GenerateContentConfig(system_instruction=system_prompt),
                    history=history,
                )
                response = chat.send_message(messages[-1].content)
                if model_name != self._model_chain[0]:
                    logger.warning("Served by fallback model %r after primary failed", model_name)
                return response.text

            except errors.ServerError as exc:
                # 5xx: overloaded / transient — worth trying the next model.
                logger.warning("Gemini model %r unavailable (%s) — trying next in chain", model_name, exc)
                last_error = exc
                continue

            except errors.ClientError:
                # 4xx: bad key, bad request, quota, etc — another model won't
                # help, so fail fast instead of burning the whole chain.
                raise

        assert last_error is not None
        raise last_error


class OpenAICompatibleProvider(AIProvider):
    """
    Works for Groq, OpenAI, OpenRouter, or any other API that speaks the
    OpenAI chat-completions protocol — they differ only in base_url,
    api_key, and model names. Same fallback-chain behavior as GeminiProvider.
    """

    def __init__(
        self,
        api_key: str | None,
        model_chain: list[str],
        base_url: str | None = None,
        provider_label: str = "openai-compatible",
    ):
        if not api_key:
            raise ValueError(
                f"No API key set for provider {provider_label!r}. Check your .env."
            )
        if not model_chain:
            raise ValueError("OpenAICompatibleProvider needs at least one model name.")

        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model_chain = model_chain  # primary first, then fallbacks in order
        self._provider_label = provider_label

    async def generate(self, messages: list[Message], system_prompt: str) -> str:
        from openai import APIStatusError

        api_messages = [{"role": "system", "content": system_prompt}]
        api_messages += [
            {"role": "user" if m.role == "user" else "assistant", "content": m.content}
            for m in messages
        ]

        last_error: Exception | None = None

        for model_name in self._model_chain:
            try:
                response = await self._client.chat.completions.create(
                    model=model_name,
                    messages=api_messages,
                )
                if model_name != self._model_chain[0]:
                    logger.warning(
                        "%s: served by fallback model %r after primary failed",
                        self._provider_label,
                        model_name,
                    )
                return response.choices[0].message.content

            except APIStatusError as exc:
                # 5xx (server-side) or 429 (rate limit / overloaded) — worth
                # trying the next model. Anything else (401 bad key, 400 bad
                # request, etc) won't be fixed by switching models.
                if exc.status_code >= 500 or exc.status_code == 429:
                    logger.warning(
                        "%s model %r unavailable (%s) — trying next in chain",
                        self._provider_label,
                        model_name,
                        exc,
                    )
                    last_error = exc
                    continue
                raise

        assert last_error is not None
        raise last_error


def get_provider(settings: Settings) -> AIProvider:
    """
    Factory: returns whichever provider is configured via AI_PROVIDER.
    This is the ONLY place in the app that should branch on provider name.
    """
    provider_name = settings.ai_provider.lower()

    if provider_name == "gemini":
        model_chain = settings.gemini_model_chain
        logger.info("Using Gemini provider (model chain: %s)", " -> ".join(model_chain))
        return GeminiProvider(api_key=settings.gemini_api_key, model_chain=model_chain)

    if provider_name == "groq":
        model_chain = settings.groq_model_chain
        logger.info("Using Groq provider (model chain: %s)", " -> ".join(model_chain))
        return OpenAICompatibleProvider(
            api_key=settings.groq_api_key,
            model_chain=model_chain,
            base_url=settings.groq_base_url,
            provider_label="groq",
        )

    if provider_name in ("openai", "openrouter"):
        model_chain = settings.openai_model_chain
        logger.info("Using %s provider (model chain: %s)", provider_name, " -> ".join(model_chain))
        return OpenAICompatibleProvider(
            api_key=settings.openai_api_key,
            model_chain=model_chain,
            base_url=settings.openai_base_url,
            provider_label=provider_name,
        )

    raise ValueError(
        f"Unknown AI_PROVIDER: {settings.ai_provider!r}. Expected one of: gemini, groq, openai, openrouter."
    )
