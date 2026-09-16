from __future__ import annotations

from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from app.ai.agent import Agent
from app.automation.workers import ReminderWorker
from app.bot.events import register_events
from app.config import Settings

if TYPE_CHECKING:
    from app.database.database import Database


def build_bot(settings: Settings, agent: Agent, db: Database | None = None) -> commands.Bot:
    intents = discord.Intents.default()
    intents.message_content = True  # required to read message text, not just mentions

    bot = commands.Bot(
        command_prefix=settings.command_prefix,
        intents=intents,
        help_command=None,
    )

    # Stashing these on the bot instance keeps events.py simple —
    # no globals, no re-reading config/agent from disk on every message.
    bot.mico_agent = agent  # type: ignore[attr-defined]
    bot.mico_settings = settings  # type: ignore[attr-defined]
    bot.reminder_worker = ReminderWorker(bot=bot, db=db) if db is not None else None  # type: ignore[attr-defined]

    register_events(bot)
    return bot
