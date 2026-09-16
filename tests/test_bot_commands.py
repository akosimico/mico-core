from unittest.mock import AsyncMock, MagicMock

import pytest
from discord.ext import commands

from app.ai.agent import Agent
from app.ai.provider import AIProvider, Message
from app.bot.client import build_bot
from app.config import Settings


class DummyProvider(AIProvider):
    async def generate(self, messages: list[Message], system_prompt: str) -> str:
        return "ok"


@pytest.fixture
def bot():
    settings = Settings(discord_token="fake-token", command_prefix="!")
    agent = Agent(provider=DummyProvider())
    return build_bot(settings, agent)


@pytest.mark.asyncio
async def test_help_command(bot):
    cmd = bot.get_command("help")
    assert cmd is not None

    ctx = MagicMock(spec=commands.Context)
    ctx.prefix = "!"
    ctx.reply = AsyncMock()

    await cmd.callback(ctx)
    ctx.reply.assert_called_once()
    help_text = ctx.reply.call_args[0][0]
    assert "!remember" in help_text
    assert "!memories" in help_text
    assert "!forget" in help_text
    assert "!reset" in help_text
    assert "!time" in help_text
    assert "!calc" in help_text
    assert "!remind" in help_text
    assert "!task" in help_text
    assert "!repos" in help_text


@pytest.mark.asyncio
async def test_on_command_error_missing_remember_argument(bot):
    ctx = MagicMock(spec=commands.Context)
    ctx.prefix = "!"
    ctx.command = bot.get_command("remember")
    ctx.invoked_with = "remember"
    ctx.reply = AsyncMock()

    param = MagicMock()
    param.name = "fact"
    err = commands.MissingRequiredArgument(param)

    await bot.on_command_error(ctx, err)

    ctx.reply.assert_called_once()
    reply_msg = ctx.reply.call_args[0][0]
    assert "Missing fact" in reply_msg
    assert "!remember <fact>" in reply_msg


@pytest.mark.asyncio
async def test_on_command_error_missing_forget_argument(bot):
    ctx = MagicMock(spec=commands.Context)
    ctx.prefix = "!"
    ctx.command = bot.get_command("forget")
    ctx.invoked_with = "forget"
    ctx.reply = AsyncMock()

    param = MagicMock()
    param.name = "memory_id"
    err = commands.MissingRequiredArgument(param)

    await bot.on_command_error(ctx, err)

    ctx.reply.assert_called_once()
    reply_msg = ctx.reply.call_args[0][0]
    assert "Missing memory ID" in reply_msg
    assert "!forget <id>" in reply_msg


@pytest.mark.asyncio
async def test_on_command_error_bad_forget_argument(bot):
    ctx = MagicMock(spec=commands.Context)
    ctx.prefix = "!"
    ctx.command = bot.get_command("forget")
    ctx.invoked_with = "forget"
    ctx.reply = AsyncMock()

    err = commands.BadArgument("Converting to int failed")

    await bot.on_command_error(ctx, err)

    ctx.reply.assert_called_once()
    reply_msg = ctx.reply.call_args[0][0]
    assert "Invalid numeric ID" in reply_msg
    assert "The ID must be a number" in reply_msg


@pytest.mark.asyncio
async def test_on_command_error_command_not_found(bot):
    ctx = MagicMock(spec=commands.Context)
    ctx.prefix = "!"
    ctx.command = None
    ctx.invoked_with = "buratatata"
    ctx.reply = AsyncMock()

    err = commands.CommandNotFound("Command buratatata is not found")

    await bot.on_command_error(ctx, err)

    ctx.reply.assert_called_once()
    reply_msg = ctx.reply.call_args[0][0]
    assert "Unknown command `!buratatata`" in reply_msg
    assert "!help" in reply_msg


@pytest.mark.asyncio
async def test_on_command_error_missing_calc_argument(bot):
    ctx = MagicMock(spec=commands.Context)
    ctx.prefix = "!"
    ctx.command = bot.get_command("calc")
    ctx.invoked_with = "calc"
    ctx.reply = AsyncMock()

    param = MagicMock()
    param.name = "expression"
    err = commands.MissingRequiredArgument(param)

    await bot.on_command_error(ctx, err)

    ctx.reply.assert_called_once()
    reply_msg = ctx.reply.call_args[0][0]
    assert "Missing math expression" in reply_msg
    assert "!calc <expression>" in reply_msg


@pytest.mark.asyncio
async def test_on_command_error_missing_task_argument(bot):
    ctx = MagicMock(spec=commands.Context)
    ctx.prefix = "!"
    ctx.command = bot.get_command("task")
    ctx.invoked_with = "task"
    ctx.reply = AsyncMock()

    param = MagicMock()
    param.name = "title"
    err = commands.MissingRequiredArgument(param)

    await bot.on_command_error(ctx, err)

    ctx.reply.assert_called_once()
    reply_msg = ctx.reply.call_args[0][0]
    assert "Missing task title" in reply_msg
    assert "!task <title>" in reply_msg

