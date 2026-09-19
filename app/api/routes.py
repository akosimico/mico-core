from __future__ import annotations

import logging
import hashlib
import hmac
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from app.ai.agent import Agent
from app.config import get_settings
from app.database.database import get_database
from app.database.models import AuditLog, Memory, MonitoredServiceRecord, ReminderRecord, ScheduledTaskRecord, TaskRecord
from sqlalchemy import func, select

logger = logging.getLogger("mico.api")
router = APIRouter()

# Global reference to Agent (set during application startup)
_agent: Agent | None = None
_discord_bot: Any | None = None
_voice_service: Any | None = None


def set_agent(agent: Agent | None) -> None:
    global _agent
    _agent = agent


def set_discord_bot(bot: Any | None) -> None:
    """Expose the running bot to the webhook route without coupling API startup to Discord."""
    global _discord_bot
    _discord_bot = bot


def set_voice_service(service: Any | None) -> None:
    global _voice_service
    _voice_service = service


def get_voice_service() -> Any:
    if _voice_service is None or not _voice_service.enabled:
        raise HTTPException(status_code=503, detail="Voice is not configured. Set OPENAI_API_KEY to enable it.")
    return _voice_service


def get_agent() -> Agent:
    if _agent is None:
        raise HTTPException(status_code=503, detail="Agent is not initialized yet.")
    return _agent


# --- Schemas ---


class HealthResponse(BaseModel):
    status: str
    app: str = "MICO"
    version: str = "0.3.0"
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


class ToolInfo(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]


class ToolExecuteRequest(BaseModel):
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    user_id: str | None = None


class ToolExecuteResponse(BaseModel):
    tool_name: str
    output: str


class TaskCreateRequest(BaseModel):
    user_id: str
    title: str
    description: str | None = None
    due_date: str | None = None


class ReminderCreateRequest(BaseModel):
    user_id: str
    content: str
    remind_at: str
    channel_id: str | None = None


class VoiceTranscriptResponse(BaseModel):
    transcript: str


class VoiceReplyResponse(BaseModel):
    transcript: str
    reply: str


class DashboardResponse(BaseModel):
    task_counts: dict[str, int]
    reminders_due: int
    automations_enabled: int
    memory_count: int
    monitors: list[dict[str, Any]]
    recent_activity: list[dict[str, Any]]


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


@router.get("/dashboard/{user_id}", response_model=DashboardResponse)
async def dashboard(user_id: str) -> DashboardResponse:
    """Structured dashboard data for a user; no LLM/tool text parsing required."""
    db = get_database()
    async with db.session() as session:
        task_rows = (await session.execute(select(TaskRecord.status, func.count(TaskRecord.id)).where(
            TaskRecord.user_id == user_id
        ).group_by(TaskRecord.status))).all()
        reminders_due = (await session.execute(select(func.count(ReminderRecord.id)).where(
            ReminderRecord.user_id == user_id, ReminderRecord.is_completed == False  # noqa: E712
        ))).scalar_one()
        enabled = (await session.execute(select(func.count(ScheduledTaskRecord.id)).where(
            ScheduledTaskRecord.user_id == user_id, ScheduledTaskRecord.enabled == True  # noqa: E712
        ))).scalar_one()
        memory_count = (await session.execute(select(func.count(Memory.id)).where(Memory.user_id == user_id))).scalar_one()
        monitors = list((await session.execute(select(MonitoredServiceRecord).where(
            MonitoredServiceRecord.user_id == user_id
        ).order_by(MonitoredServiceRecord.id.desc()))).scalars().all())
        activity = list((await session.execute(select(AuditLog).where(
            AuditLog.user_id == user_id
        ).order_by(AuditLog.created_at.desc()).limit(10))).scalars().all())
    return DashboardResponse(
        task_counts={status: count for status, count in task_rows},
        reminders_due=reminders_due,
        automations_enabled=enabled,
        memory_count=memory_count,
        monitors=[{"id": item.id, "name": item.name, "url": item.url, "status": item.last_status or "pending", "error": item.last_error} for item in monitors],
        recent_activity=[{"action": item.action, "status": item.status, "created_at": item.created_at.isoformat(), "details": item.details} for item in activity],
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


@router.post("/voice/transcribe", response_model=VoiceTranscriptResponse)
async def transcribe_voice(request: Request, filename: str = Query(default="voice-message.ogg")) -> VoiceTranscriptResponse:
    service = get_voice_service()
    try:
        return VoiceTranscriptResponse(transcript=await service.transcribe(await request.body(), filename, request.headers.get("content-type", "audio/ogg")))
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/voice/reply", response_model=VoiceReplyResponse)
async def voice_reply(
    request: Request,
    conversation_id: str = Query(...),
    user_id: str | None = Query(default=None),
    server_id: str | None = Query(default=None),
    filename: str = Query(default="voice-message.ogg"),
) -> VoiceReplyResponse:
    service = get_voice_service()
    agent = get_agent()
    try:
        transcript = await service.transcribe(await request.body(), filename, request.headers.get("content-type", "audio/ogg"))
        reply = await agent.handle_message(conversation_id=conversation_id, user_message=transcript, user_id=user_id, server_id=server_id)
        return VoiceReplyResponse(transcript=transcript, reply=reply)
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/voice/synthesize")
async def synthesize_voice(request: Request) -> Response:
    service = get_voice_service()
    try:
        text = (await request.body()).decode("utf-8").strip()
        return Response(content=await service.synthesize(text), media_type="audio/mpeg")
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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


# --- Tool & Task Endpoints ---


@router.get("/tools", response_model=list[ToolInfo])
async def list_available_tools() -> list[ToolInfo]:
    """List all tools currently registered on the MICO agent."""
    agent = get_agent()
    if agent.tool_registry is None:
        return []
    return [
        ToolInfo(
            name=t.name,
            description=t.description,
            parameters=t.parameters,
        )
        for t in agent.tool_registry.list_tools()
    ]


@router.post("/tools/execute", response_model=ToolExecuteResponse)
async def execute_tool_endpoint(req: ToolExecuteRequest) -> ToolExecuteResponse:
    """Execute a registered tool directly by name."""
    agent = get_agent()
    if agent.tool_registry is None:
        raise HTTPException(status_code=501, detail="Tool registry is not enabled on this agent.")

    tool = agent.tool_registry.get(req.tool_name)
    if not tool:
        raise HTTPException(status_code=404, detail=f"Tool '{req.tool_name}' not found.")

    args = dict(req.arguments)
    if req.user_id and "user_id" in tool.parameters.get("properties", {}) and "user_id" not in args:
        args["user_id"] = req.user_id

    output = await tool.execute(**args)
    return ToolExecuteResponse(tool_name=req.tool_name, output=str(output))


@router.get("/tasks/{user_id}")
async def get_user_tasks(user_id: str, status: str | None = Query(default=None)) -> dict[str, Any]:
    """Fetch tasks for a user."""
    agent = get_agent()
    if agent.tool_registry is None:
        raise HTTPException(status_code=501, detail="Tool registry is not enabled.")
    output = await agent.tool_registry.execute("list_tasks", user_id=user_id, status=status)
    return {"user_id": user_id, "tasks": output}


@router.post("/tasks")
async def create_user_task(req: TaskCreateRequest) -> dict[str, Any]:
    """Create a task for a user."""
    agent = get_agent()
    if agent.tool_registry is None:
        raise HTTPException(status_code=501, detail="Tool registry is not enabled.")
    output = await agent.tool_registry.execute(
        "create_task",
        user_id=req.user_id,
        title=req.title,
        description=req.description,
        due_date=req.due_date,
    )
    return {"user_id": req.user_id, "result": output}


@router.patch("/tasks/{task_id}/complete")
async def complete_user_task(task_id: int, user_id: str = Query(...)) -> dict[str, Any]:
    """Mark a task as completed."""
    agent = get_agent()
    if agent.tool_registry is None:
        raise HTTPException(status_code=501, detail="Tool registry is not enabled.")
    output = await agent.tool_registry.execute("complete_task", user_id=user_id, task_id=task_id)
    return {"user_id": user_id, "task_id": task_id, "result": output}


@router.get("/reminders/{user_id}")
async def get_user_reminders(user_id: str, include_completed: bool = Query(default=False)) -> dict[str, Any]:
    """Fetch reminders for a user."""
    agent = get_agent()
    if agent.tool_registry is None:
        raise HTTPException(status_code=501, detail="Tool registry is not enabled.")
    output = await agent.tool_registry.execute(
        "list_reminders", user_id=user_id, include_completed=include_completed
    )
    return {"user_id": user_id, "reminders": output}


@router.post("/reminders")
async def create_user_reminder(req: ReminderCreateRequest) -> dict[str, Any]:
    """Create a scheduled reminder for a user."""
    agent = get_agent()
    if agent.tool_registry is None:
        raise HTTPException(status_code=501, detail="Tool registry is not enabled.")
    output = await agent.tool_registry.execute(
        "create_reminder",
        user_id=req.user_id,
        content=req.content,
        remind_at=req.remind_at,
        channel_id=req.channel_id,
    )
    return {"user_id": req.user_id, "result": output}


def _format_github_webhook(event: str, payload: dict[str, Any]) -> str | None:
    repository = payload.get("repository", {}).get("full_name", "repository")
    sender = payload.get("sender", {}).get("login", "someone")
    if event == "push":
        commits = payload.get("commits", [])
        messages = [commit.get("message", "commit").split("\n")[0] for commit in commits[:5]]
        branch = payload.get("ref", "").removeprefix("refs/heads/")
        detail = "\n".join(f"• {message}" for message in messages) or "• No commit details supplied"
        return f"🔨 **GitHub push** to `{repository}` ({branch}) by @{sender}\n{detail}"
    if event == "issues":
        issue = payload.get("issue", {})
        return f"🐛 **Issue {payload.get('action', 'updated')}** in `{repository}`: #{issue.get('number')} {issue.get('title', '')}"
    if event == "pull_request":
        pull = payload.get("pull_request", {})
        return f"🔀 **Pull request {payload.get('action', 'updated')}** in `{repository}`: #{pull.get('number')} {pull.get('title', '')}"
    return None


@router.post("/webhooks/github", status_code=202)
async def github_webhook(
    request: Request,
    x_github_event: str = Header(default=""),
    x_hub_signature_256: str = Header(default=""),
) -> dict[str, Any]:
    """Validate GitHub's HMAC signature and relay supported events to Discord."""
    settings = get_settings()
    if not settings.github_webhook_secret or not settings.github_webhook_channel_id:
        raise HTTPException(status_code=503, detail="GitHub webhook delivery is not configured.")
    body = await request.body()
    expected = "sha256=" + hmac.new(settings.github_webhook_secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid GitHub webhook signature.")
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid GitHub webhook payload.") from exc
    message = _format_github_webhook(x_github_event, payload)
    if message is None:
        return {"status": "ignored", "event": x_github_event}
    if _discord_bot is None:
        raise HTTPException(status_code=503, detail="Discord bot is not connected.")
    try:
        channel_id: int | str = int(settings.github_webhook_channel_id) if settings.github_webhook_channel_id.isdigit() else settings.github_webhook_channel_id
        channel = _discord_bot.get_channel(channel_id)
        if channel is None and hasattr(_discord_bot, "fetch_channel"):
            channel = await _discord_bot.fetch_channel(channel_id)
        if channel is None or not hasattr(channel, "send"):
            raise RuntimeError("Configured Discord webhook channel is unavailable.")
        await channel.send(message)
    except Exception as exc:
        logger.exception("Failed to relay GitHub webhook to Discord: %s", exc)
        raise HTTPException(status_code=502, detail="GitHub webhook could not be delivered to Discord.") from exc
    return {"status": "delivered", "event": x_github_event}
