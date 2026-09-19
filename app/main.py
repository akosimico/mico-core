from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI

from app.ai.agent import Agent
from app.ai.memory import MemoryService
from app.ai.provider import get_provider
from app.api.routes import router as api_router, set_agent
from app.bot.client import build_bot
from app.config import get_settings
from app.database.database import get_database
from app.tools import build_default_registry

logger = logging.getLogger("mico.main")


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifecycle manager: initializes database, AI agent, memory service, and Discord bot."""
    settings = get_settings()
    setup_logging(settings.log_level)
    logger.info("Initializing MICO backend (provider=%s)", settings.ai_provider)

    # 1. Initialize Database
    db = get_database(settings)
    await db.init_models()

    # 2. Build Memory Service, Tool Registry & AI Agent
    memory_service = MemoryService(db)
    tool_registry = build_default_registry(db=db, settings=settings)
    provider = get_provider(settings)
    agent = Agent(
        provider=provider,
        max_history_messages=settings.max_history_messages,
        memory_service=memory_service,
        tool_registry=tool_registry,
    )
    set_agent(agent)

    # 3. Start Discord Bot (if enabled and token provided)
    bot_task: asyncio.Task | None = None
    bot = None
    if settings.enable_bot and settings.discord_token:
        logger.info("Starting Discord bot in background task...")
        bot = build_bot(settings, agent, db=db)
        bot_task = asyncio.create_task(bot.start(settings.discord_token))
    else:
        logger.info("Discord bot is disabled or DISCORD_TOKEN is empty; running API only")

    try:
        yield
    finally:
        logger.info("Shutting down MICO...")
        if bot is not None:
            if hasattr(bot, "automation_worker") and bot.automation_worker:
                await bot.automation_worker.stop()
            logger.info("Closing Discord bot connection...")
            await bot.close()
        if bot_task is not None:
            bot_task.cancel()
            try:
                await bot_task
            except (asyncio.CancelledError, Exception):
                pass
        await db.close()
        logger.info("MICO shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title="MICO — Personal AI Automation Assistant",
        description="FastAPI backend + Discord Bot with AI provider abstraction, persistent memory, and tool calling",
        version="0.3.0",
        lifespan=lifespan,
    )

    @app.get("/")
    async def root():
        return {
            "app": "MICO",
            "version": "0.3.0",
            "status": "online",
            "docs": "/docs",
        }

    app.include_router(api_router, prefix="/api")
    return app


app = create_app()


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    if settings.enable_api:
        logger.info(
            "Launching FastAPI server on http://%s:%s",
            settings.api_host,
            settings.api_port,
        )
        uvicorn.run(
            "app.main:app",
            host=settings.api_host,
            port=settings.api_port,
            reload=False,
            log_level=settings.log_level.lower(),
        )
    else:
        # Standalone bot mode if API is disabled
        logger.info("API disabled; running Discord bot standalone")
        db = get_database(settings)
        asyncio.run(db.init_models())
        memory_service = MemoryService(db)
        tool_registry = build_default_registry(db=db, settings=settings)
        provider = get_provider(settings)
        agent = Agent(
            provider=provider,
            max_history_messages=settings.max_history_messages,
            memory_service=memory_service,
            tool_registry=tool_registry,
        )
        bot = build_bot(settings, agent, db=db)
        bot.run(settings.discord_token)


if __name__ == "__main__":
    main()
