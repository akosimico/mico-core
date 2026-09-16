from __future__ import annotations

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from app.config import Settings

if TYPE_CHECKING:
    from app.tools.base import ToolRegistry

logger = logging.getLogger("mico.ai.provider")


@dataclass
class Message:
    role: str  # "user", "assistant", or "system"
    content: str


class AIProvider(ABC):
    """
    Common interface every AI backend implements.
    Exposes `generate` for plain text completions and `generate_with_tools`
    for function calling.
    """

    @abstractmethod
    async def generate(self, messages: list[Message], system_prompt: str) -> str:
        """Given the conversation so far and a system prompt, return the reply text."""
        raise NotImplementedError

    async def generate_with_tools(
        self,
        messages: list[Message],
        system_prompt: str,
        tool_registry: ToolRegistry,
        max_tool_iterations: int = 5,
    ) -> str:
        """Generate a response with access to external tools."""
        return await self.generate(messages, system_prompt)


class GeminiProvider(AIProvider):
    def __init__(self, api_key: str | None, model_chain: list[str]):
        if not api_key:
            raise ValueError(
                "GEMINI_API_KEY is not set. Add it to your .env (see .env.example)."
            )
        if not model_chain:
            raise ValueError("GeminiProvider needs at least one model name.")

        from google import genai

        self._client = genai.Client(api_key=api_key)
        self._model_chain = model_chain  # primary first, then fallbacks in order

    async def generate(self, messages: list[Message], system_prompt: str) -> str:
        return await asyncio.to_thread(self._generate_sync, messages, system_prompt)

    def _generate_sync(self, messages: list[Message], system_prompt: str) -> str:
        from google.genai import errors, types

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
                return response.text or ""

            except errors.ServerError as exc:
                logger.warning("Gemini model %r unavailable (%s) — trying next in chain", model_name, exc)
                last_error = exc
                continue

            except errors.ClientError:
                raise

        assert last_error is not None
        raise last_error

    async def generate_with_tools(
        self,
        messages: list[Message],
        system_prompt: str,
        tool_registry: ToolRegistry,
        max_tool_iterations: int = 5,
    ) -> str:
        """Asynchronous generation with Gemini tool calling."""
        from google.genai import errors, types

        declarations = [
            types.FunctionDeclaration(
                name=t["name"],
                description=t["description"],
                parameters=t["parameters"],
            )
            for t in tool_registry.to_gemini_declarations()
        ]
        gemini_tools = [types.Tool(function_declarations=declarations)] if declarations else None

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
                chat = self._client.aio.chats.create(
                    model=model_name,
                    config=types.GenerateContentConfig(
                        system_instruction=system_prompt,
                        tools=gemini_tools,
                    ),
                    history=history,
                )
                response = await chat.send_message(messages[-1].content)

                iterations = 0
                while response.function_calls and iterations < max_tool_iterations:
                    iterations += 1
                    tool_parts = []
                    for call in response.function_calls:
                        fn_name = call.name
                        fn_args = dict(call.args) if call.args else {}
                        logger.info("Gemini calling tool: %s(%s)", fn_name, fn_args)
                        output = await tool_registry.execute(fn_name, **fn_args)
                        tool_parts.append(
                            types.Part.from_function_response(
                                name=fn_name,
                                response={"result": str(output)},
                            )
                        )
                    response = await chat.send_message(tool_parts)

                if model_name != self._model_chain[0]:
                    logger.warning("Served by fallback model %r after primary failed", model_name)
                return response.text or ""

            except errors.ServerError as exc:
                logger.warning("Gemini model %r unavailable (%s) — trying next in chain", model_name, exc)
                last_error = exc
                continue
            except errors.ClientError:
                raise

        assert last_error is not None
        raise last_error


class OpenAICompatibleProvider(AIProvider):
    """
    Works for Groq, OpenAI, OpenRouter, or any other API that speaks the
    OpenAI chat-completions protocol. Includes full tool-calling support.
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
        self._model_chain = model_chain
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
                return response.choices[0].message.content or ""

            except APIStatusError as exc:
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

    async def generate_with_tools(
        self,
        messages: list[Message],
        system_prompt: str,
        tool_registry: ToolRegistry,
        max_tool_iterations: int = 5,
    ) -> str:
        from openai import APIStatusError

        api_messages: list[dict[str, Any]] = [{"role": "system", "content": system_prompt}]
        api_messages += [
            {"role": "user" if m.role == "user" else "assistant", "content": m.content}
            for m in messages
        ]

        tools_schema = tool_registry.to_openai_tools()
        last_error: Exception | None = None

        for model_name in self._model_chain:
            try:
                curr_messages = list(api_messages)
                iterations = 0

                while iterations < max_tool_iterations:
                    iterations += 1
                    response = await self._client.chat.completions.create(
                        model=model_name,
                        messages=curr_messages,
                        tools=tools_schema if tools_schema else None,
                    )
                    choice = response.choices[0]
                    msg = choice.message

                    if not msg.tool_calls:
                        return msg.content or ""

                    # Add model's tool calls to conversational messages
                    curr_messages.append(msg.model_dump(exclude_none=True))

                    for tool_call in msg.tool_calls:
                        fn_name = tool_call.function.name
                        try:
                            fn_args = json.loads(tool_call.function.arguments or "{}")
                        except Exception:
                            fn_args = {}

                        logger.info("%s calling tool: %s(%s)", self._provider_label, fn_name, fn_args)
                        output = await tool_registry.execute(fn_name, **fn_args)

                        curr_messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": str(output),
                        })

                # If reached max iterations, make final plain completion
                final_res = await self._client.chat.completions.create(
                    model=model_name,
                    messages=curr_messages,
                )
                return final_res.choices[0].message.content or ""

            except APIStatusError as exc:
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
