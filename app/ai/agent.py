from __future__ import annotations

import logging

from app.ai.prompts import SYSTEM_PROMPT
from app.ai.provider import AIProvider, Message

logger = logging.getLogger("mico.ai.agent")


class Agent:
    """
    Owns conversation history and talks to whatever AIProvider is configured.
    Callers (Discord today, maybe a REST API or CLI later) just call
    `handle_message` — they don't need to know about providers, prompts,
    or history management.

    History is in-memory and per-conversation (Milestone 1). Milestone 2
    moves this to Postgres and adds long-term/project memory on top.
    """

    def __init__(self, provider: AIProvider, max_history_messages: int = 20):
        self._provider = provider
        self._max_history = max_history_messages
        self._history: dict[str, list[Message]] = {}

    def reset(self, conversation_id: str) -> None:
        self._history.pop(conversation_id, None)

    async def handle_message(self, conversation_id: str, user_message: str) -> str:
        history = self._history.setdefault(conversation_id, [])
        history.append(Message(role="user", content=user_message))

        try:
            reply = await self._provider.generate(history, SYSTEM_PROMPT)
        except Exception:
            logger.exception("AI provider failed for conversation %s", conversation_id)
            history.pop()  # don't keep a failed turn in history
            raise

        history.append(Message(role="assistant", content=reply))

        overflow = len(history) - self._max_history
        if overflow > 0:
            del history[:overflow]

        return reply
