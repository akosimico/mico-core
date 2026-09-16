from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.ai.agent import Agent
from app.config import get_settings
from app.database.database import get_database

logger = logging.getLogger("mico.api")
router = APIRouter()

# Global reference to Agent (set during application startup)
_agent: Agent | None = None


def set_agent(agent: Agent | None) -> None:
    global _agent
    _agent = agent


def get_agent() -> Agent:
    if _agent is None:
        raise HTTPException(status_code=503, detail="Agent is not initialized yet.")
    return _agent


# --- Schemas ---


class HealthResponse(BaseModel):
    status: str
    app: str = "MICO"
    version: str = "0.2.0"
    ai_provider: str
    database: str
    bot_enabled: bool


class ChatRequest(BaseModel):
    conversation_id: str = Field(..., description="Unique conversation/channel ID")
    message: str = Field(..., description="User message text")
    user_id: str | None = Field(default=None, description="Optional user ID for memory recall")
    server_id: str | None = Field(default=None, description="Optional server/guild ID")
    project_name: str | None = Field(default=None, description="Optional project context")


class ChatResponse(BaseModel):
    reply: str
    conversation_id: str


class MemoryCreateRequest(BaseModel):
    user_id: str
    content: str
    category: str = "general"
    project_name: str | None = None
    importance: int = Field(default=1, ge=1, le=5)


class MemoryResponse(BaseModel):
    id: int
    user_id: str
    content: str
    category: str
    project_name: str | None
    importance: int


# --- Endpoints ---


@router.get("/health", response_model=HealthResponse)
async def health_check() -> HealthResponse:
    settings = get_settings()
    db = get_database()
    db_status = "connected"
    try:
        async with db.session():
            pass
    except Exception as exc:
        db_status = f"unhealthy: {exc}"

    return HealthResponse(
        status="ok",
        ai_provider=settings.ai_provider,
        database=db_status,
        bot_enabled=settings.enable_bot and bool(settings.discord_token),
    )


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest) -> ChatResponse:
    agent = get_agent()
    try:
        reply = await agent.handle_message(
            conversation_id=request.conversation_id,
            user_message=request.message,
            user_id=request.user_id,
            server_id=request.server_id,
            project_name=request.project_name,
        )
        return ChatResponse(reply=reply, conversation_id=request.conversation_id)
    except Exception as exc:
        logger.exception("Error processing chat message: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/memories/{user_id}", response_model=list[MemoryResponse])
async def list_memories(
    user_id: str,
    category: str | None = Query(default=None),
    project: str | None = Query(default=None),
) -> list[MemoryResponse]:
    agent = get_agent()
    if agent.memory_service is None:
        raise HTTPException(status_code=501, detail="Memory service is not active.")

    records = await agent.get_user_memories(
        user_id=user_id,
        category=category,
        project_name=project,
    )
    return [
        MemoryResponse(
            id=m.id,
            user_id=m.user_id,
            content=m.content,
            category=m.category,
            project_name=m.project_name,
            importance=m.importance,
        )
        for m in records
    ]


@router.post("/memories", response_model=MemoryResponse)
async def create_memory(req: MemoryCreateRequest) -> MemoryResponse:
    agent = get_agent()
    if agent.memory_service is None:
        raise HTTPException(status_code=501, detail="Memory service is not active.")

    mem = await agent.remember(
        user_id=req.user_id,
        content=req.content,
        category=req.category,
        project_name=req.project_name,
        importance=req.importance,
    )
    if mem is None:
        raise HTTPException(status_code=500, detail="Failed to persist memory.")

    return MemoryResponse(
        id=mem.id,
        user_id=mem.user_id,
        content=mem.content,
        category=mem.category,
        project_name=mem.project_name,
        importance=mem.importance,
    )


@router.delete("/memories/{memory_id}")
async def delete_memory(memory_id: int, user_id: str | None = Query(default=None)) -> dict[str, Any]:
    agent = get_agent()
    if agent.memory_service is None:
        raise HTTPException(status_code=501, detail="Memory service is not active.")

    deleted = await agent.forget(memory_id=memory_id, user_id=user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Memory not found.")
    return {"deleted": True, "memory_id": memory_id}
