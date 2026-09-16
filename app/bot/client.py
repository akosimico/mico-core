from __future__ import annotations

import discord
from discord.ext import commands

from app.ai.agent import Agent
from app.bot.events import register_events
from app.config import Settings


def build_bot(settings: Settings, agent: Agent) -> commands.Bot:
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

    register_events(bot)
    return bot
