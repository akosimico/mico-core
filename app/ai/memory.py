from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from sqlalchemy import delete, select

from app.ai.provider import Message
from app.database.database import Database
from app.database.models import Conversation, Memory, MessageRecord

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("mico.ai.memory")


class MemoryService:
    """
    Manages both short-term conversational context and long-term memory
    (facts, user preferences, and project-specific knowledge).
    """

    def __init__(self, db: Database):
        self.db = db

    # -------------------------------------------------------------------------
    # Short-Term Memory (Conversation History)
    # -------------------------------------------------------------------------

    async def get_history(self, conversation_id: str, limit: int = 20) -> list[Message]:
        """Fetch the most recent messages for a conversation, ordered chronologically."""
        async with self.db.session() as session:
            stmt = (
                select(MessageRecord)
                .where(MessageRecord.conversation_id == conversation_id)
                .order_by(MessageRecord.created_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            records = list(result.scalars().all())
            records.reverse()  # oldest to newest

            return [Message(role=r.role, content=r.content) for r in records]

    async def save_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        user_id: str | None = None,
        server_id: str | None = None,
    ) -> MessageRecord:
        """Persist a single user or assistant message to the database."""
        async with self.db.session() as session:
            # Ensure conversation record exists
            conv_stmt = select(Conversation).where(Conversation.id == conversation_id)
            conv_res = await session.execute(conv_stmt)
            conv = conv_res.scalar_one_or_none()

            if conv is None:
                conv = Conversation(
                    id=conversation_id,
                    user_id=user_id,
                    server_id=server_id,
                )
                session.add(conv)
                await session.flush()

            msg = MessageRecord(
                conversation_id=conversation_id,
                role=role,
                content=content,
            )
            session.add(msg)
            await session.commit()
            return msg

    async def clear_history(self, conversation_id: str) -> None:
        """Clear all messages associated with a conversation."""
        async with self.db.session() as session:
            stmt = delete(MessageRecord).where(MessageRecord.conversation_id == conversation_id)
            await session.execute(stmt)
            await session.commit()
            logger.info("Cleared history for conversation %s", conversation_id)

    # -------------------------------------------------------------------------
    # Long-Term & Project Memory
    # -------------------------------------------------------------------------

    async def add_memory(
        self,
        user_id: str,
        content: str,
        category: str = "general",
        project_name: str | None = None,
        importance: int = 1,
    ) -> Memory:
        """Store a long-term memory or project fact."""
        async with self.db.session() as session:
            memory = Memory(
                user_id=user_id,
                content=content.strip(),
                category=category,
                project_name=project_name.lower().strip() if project_name else None,
                importance=importance,
            )
            session.add(memory)
            await session.commit()
            await session.refresh(memory)
            logger.info("Saved memory id=%s for user=%s [category=%s]", memory.id, user_id, category)
            return memory

    async def get_memories(
        self,
        user_id: str,
        category: str | None = None,
        project_name: str | None = None,
        limit: int = 20,
    ) -> list[Memory]:
        """Retrieve memories for a user, optionally filtered by category or project."""
        async with self.db.session() as session:
            stmt = select(Memory).where(Memory.user_id == user_id)
            if category:
                stmt = stmt.where(Memory.category == category)
            if project_name:
                stmt = stmt.where(Memory.project_name == project_name.lower().strip())

            stmt = stmt.order_by(Memory.importance.desc(), Memory.created_at.desc()).limit(limit)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def search_memories(self, user_id: str, query: str, limit: int = 10) -> list[Memory]:
        """Search memories containing query keywords."""
        async with self.db.session() as session:
            pattern = f"%{query.strip()}%"
            stmt = (
                select(Memory)
                .where(Memory.user_id == user_id, Memory.content.ilike(pattern))
                .order_by(Memory.importance.desc(), Memory.created_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def delete_memory(self, memory_id: int, user_id: str | None = None) -> bool:
        """Delete a memory by ID. If user_id is provided, checks ownership."""
        async with self.db.session() as session:
            stmt = delete(Memory).where(Memory.id == memory_id)
            if user_id is not None:
                stmt = stmt.where(Memory.user_id == user_id)
            result = await session.execute(stmt)
            await session.commit()
            return result.rowcount > 0

    # -------------------------------------------------------------------------
    # Context Formatting for Agent Prompt
    # -------------------------------------------------------------------------

    async def format_memories_for_prompt(
        self,
        user_id: str | None = None,
        project_name: str | None = None,
        max_items: int = 10,
    ) -> str:
        """
        Assemble long-term and project memories into a Markdown context section
        to be appended to the AI system prompt.
        """
        if not user_id:
            return ""

        async with self.db.session() as session:
            stmt = (
                select(Memory)
                .where(Memory.user_id == user_id)
                .order_by(Memory.importance.desc(), Memory.created_at.desc())
                .limit(max_items)
            )
            result = await session.execute(stmt)
            all_memories = list(result.scalars().all())

        if not all_memories:
            return ""

        general_memories = [m for m in all_memories if m.category != "project"]
        project_memories = [m for m in all_memories if m.category == "project"]

        sections: list[str] = []

        if general_memories:
            items = "\n".join(f"- {m.content}" for m in general_memories)
            sections.append(f"Remembered facts about the user:\n{items}")

        if project_memories:
            items = "\n".join(
                f"- [{m.project_name or 'project'}] {m.content}" for m in project_memories
            )
            sections.append(f"Remembered project details:\n{items}")

        return "\n\n".join(sections)

    # -------------------------------------------------------------------------
    # Memory Intent Extraction Helper
    # -------------------------------------------------------------------------

    @staticmethod
    def extract_memory_fact(text: str) -> tuple[str, str, str | None] | None:
        """
        Check if user input matches a "remember that..." pattern.
        Returns (content, category, project_name) if matched, or None.

        Examples:
        - "remember that I prefer Python" -> ("I prefer Python", "user_fact", None)
        - "remember project portfolio: uses Next.js and Tailwind" -> ("uses Next.js and Tailwind", "project", "portfolio")
        """
        stripped = text.strip()

        # Project fact pattern: "remember project <name>: <fact>" or "project <name>: remember <fact>"
        proj_match = re.match(
            r"^(?:please\s+)?remember\s+project\s+([a-zA-Z0-9_\-]+)\s*[:\-]\s*(.+)$",
            stripped,
            re.IGNORECASE,
        )
        if proj_match:
            project_name = proj_match.group(1).strip()
            fact = proj_match.group(2).strip()
            return fact, "project", project_name

        # General fact pattern: "remember that ...", "remember: ...", "remember this: ..."
        gen_match = re.match(
            r"^(?:please\s+)?remember(?:\s+that|\s*:\s*|\s+this\s*:\s*|\s+)\s*(.+)$",
            stripped,
            re.IGNORECASE,
        )
        if gen_match:
            fact = gen_match.group(1).strip()
            # Ignore trivial requests like "remember?" or "remember what I said"
            if len(fact) > 3 and not fact.endswith("?"):
                return fact, "general", None

        return None
