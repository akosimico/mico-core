from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from app.ai.prompts import SYSTEM_PROMPT, build_system_prompt
from app.ai.provider import AIProvider, Message
from app.tools.base import Tool, ToolRegistry

if TYPE_CHECKING:
    from app.ai.memory import MemoryService
    from app.database.models import Memory

logger = logging.getLogger("mico.ai.agent")


class ContextualToolRegistry(ToolRegistry):
    """Wraps a ToolRegistry to automatically supply user context (like user_id and channel_id) if omitted by the LLM."""

    def __init__(
        self,
        base_registry: ToolRegistry,
        default_user_id: str | None = None,
        default_channel_id: str | None = None,
    ):
        super().__init__(tools=dict(base_registry.tools))
        self.default_user_id = default_user_id
        self.default_channel_id = default_channel_id

    async def execute(self, name: str, **kwargs) -> str:
        tool = self.get(name)
        if tool:
            props = tool.parameters.get("properties", {})
            if "user_id" in props and not kwargs.get("user_id") and self.default_user_id:
                kwargs["user_id"] = self.default_user_id
            if "channel_id" in props and not kwargs.get("channel_id") and self.default_channel_id:
                kwargs["channel_id"] = self.default_channel_id
        return await super().execute(name, **kwargs)


class Agent:
    """
    Owns conversation orchestration, memory integration, tool execution,
    and talks to whatever AIProvider is configured.

    Milestone 1: in-memory conversation history.
    Milestone 2: persistent database-backed memory via MemoryService.
    Milestone 3: tool calling registry & multi-turn execution.
    """

    def __init__(
        self,
        provider: AIProvider,
        max_history_messages: int = 20,
        memory_service: MemoryService | None = None,
        tool_registry: ToolRegistry | None = None,
    ):
        self._provider = provider
        self._max_history = max_history_messages
        self._memory_service = memory_service
        self._tool_registry = tool_registry
        self._history: dict[str, list[Message]] = {}

    @property
    def memory_service(self) -> MemoryService | None:
        return self._memory_service

    @property
    def tool_registry(self) -> ToolRegistry | None:
        return self._tool_registry

    def reset(self, conversation_id: str) -> None:
        """Clear conversation history synchronously (and schedules DB clear if active)."""
        self._history.pop(conversation_id, None)
        if self._memory_service is not None:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self._memory_service.clear_history(conversation_id))
            except RuntimeError:
                pass

    async def areset(self, conversation_id: str) -> None:
        """Clear conversation history asynchronously, ensuring DB records are deleted."""
        self._history.pop(conversation_id, None)
        if self._memory_service is not None:
            await self._memory_service.clear_history(conversation_id)

    async def remember(
        self,
        user_id: str,
        content: str,
        category: str = "general",
        project_name: str | None = None,
        importance: int = 1,
    ) -> Memory | None:
        """Explicitly save a long-term memory fact for a user."""
        if self._memory_service is None:
            return None
        return await self._memory_service.add_memory(
            user_id=user_id,
            content=content,
            category=category,
            project_name=project_name,
            importance=importance,
        )

    async def get_user_memories(
        self,
        user_id: str,
        category: str | None = None,
        project_name: str | None = None,
    ) -> list[Memory]:
        """Fetch remembered facts for a user."""
        if self._memory_service is None:
            return []
        return await self._memory_service.get_memories(
            user_id=user_id,
            category=category,
            project_name=project_name,
        )

    async def forget(self, memory_id: int, user_id: str | None = None) -> bool:
        """Delete a remembered fact."""
        if self._memory_service is None:
            return False
        return await self._memory_service.delete_memory(memory_id=memory_id, user_id=user_id)

    async def handle_message(
        self,
        conversation_id: str,
        user_message: str,
        user_id: str | None = None,
        server_id: str | None = None,
        project_name: str | None = None,
    ) -> str:
        """
        Process a user turn:
        1. Checks for explicit "remember that..." intent and stores the fact if present.
        2. Injects relevant user and project memories into the system prompt.
        3. Loads conversation history (from DB or in-memory cache).
        4. Calls provider with tools if tool_registry is available.
        5. Persists the conversation turn to the database.
        """
        memory_context = ""

        # Auto-detect explicit memory facts like "remember that I prefer TypeScript"
        if self._memory_service is not None and user_id is not None:
            fact_data = self._memory_service.extract_memory_fact(user_message)
            if fact_data is not None:
                fact, category, extracted_project = fact_data
                await self._memory_service.add_memory(
                    user_id=user_id,
                    content=fact,
                    category=category,
                    project_name=extracted_project or project_name,
                )

            # Retrieve remembered context for prompt injection
            memory_context = await self._memory_service.format_memories_for_prompt(
                user_id=user_id,
                project_name=project_name,
            )

        # Build prompt with memories and user context included
        system_prompt = build_system_prompt(memory_context=memory_context, user_id=user_id)

        # Load short-term history
        if self._memory_service is not None:
            history = await self._memory_service.get_history(
                conversation_id, limit=self._max_history
            )
            history.append(Message(role="user", content=user_message))
        else:
            in_mem = self._history.setdefault(conversation_id, [])
            in_mem.append(Message(role="user", content=user_message))
            history = in_mem

        try:
            if self._tool_registry is not None:
                active_registry = ContextualToolRegistry(
                    self._tool_registry,
                    default_user_id=user_id,
                    default_channel_id=conversation_id,
                )
                reply = await self._provider.generate_with_tools(
                    messages=history,
                    system_prompt=system_prompt,
                    tool_registry=active_registry,
                )
            else:
                reply = await self._provider.generate(history, system_prompt)
        except Exception:
            logger.exception("AI provider failed for conversation %s", conversation_id)
            if self._memory_service is None:
                in_mem_hist = self._history.get(conversation_id)
                if in_mem_hist:
                    in_mem_hist.pop()
            raise

        # Save turns to database or in-memory cache
        if self._memory_service is not None:
            await self._memory_service.save_message(
                conversation_id=conversation_id,
                role="user",
                content=user_message,
                user_id=user_id,
                server_id=server_id,
            )
            await self._memory_service.save_message(
                conversation_id=conversation_id,
                role="assistant",
                content=reply,
                user_id=user_id,
                server_id=server_id,
            )
        else:
            in_mem.append(Message(role="assistant", content=reply))
            overflow = len(in_mem) - self._max_history
            if overflow > 0:
                del in_mem[:overflow]

        return reply
