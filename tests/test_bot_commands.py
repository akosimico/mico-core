from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from discord.ext import commands

from app.ai.agent import Agent
from app.ai.provider import AIProvider, Message
from app.bot.client import build_bot
from app.config import Settings
from app.database.database import Database
from app.tools import build_default_registry


class DummyProvider(AIProvider):
    async def generate(self, messages: list[Message], system_prompt: str) -> str:
        return "ok"


@pytest.fixture
def bot():
    settings = Settings(discord_token="fake-token", command_prefix="!")
    agent = Agent(provider=DummyProvider())
    return build_bot(settings, agent)


@pytest_asyncio.fixture
async def bot_with_tools(tmp_path):
    db_file = tmp_path / "test_bot_tools.db"
    db = Database(f"sqlite+aiosqlite:///{db_file}")
    await db.init_models()
    registry = build_default_registry(db=db)
    agent = Agent(provider=DummyProvider(), tool_registry=registry)
    settings = Settings(discord_token="fake-token", command_prefix="!")
    b = build_bot(settings, agent)
    try:
        yield b
    finally:
        await db.close()


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


@pytest.mark.asyncio
async def test_on_command_error_missing_remind_argument(bot):
    ctx = MagicMock(spec=commands.Context)
    ctx.prefix = "!"
    ctx.command = bot.get_command("remind")
    ctx.invoked_with = "remind"
    ctx.reply = AsyncMock()

    param = MagicMock()
    param.name = "args"
    err = commands.MissingRequiredArgument(param)

    await bot.on_command_error(ctx, err)

    ctx.reply.assert_called_once()
    reply_msg = ctx.reply.call_args[0][0]
    assert "Missing reminder details" in reply_msg
    assert "!remind <time> to <what>" in reply_msg


@pytest.mark.asyncio
async def test_on_command_error_missing_taskdone_argument(bot):
    ctx = MagicMock(spec=commands.Context)
    ctx.prefix = "!"
    ctx.command = bot.get_command("taskdone")
    ctx.invoked_with = "taskdone"
    ctx.reply = AsyncMock()

    param = MagicMock()
    param.name = "task_id"
    err = commands.MissingRequiredArgument(param)

    await bot.on_command_error(ctx, err)

    ctx.reply.assert_called_once()
    reply_msg = ctx.reply.call_args[0][0]
    assert "Missing task ID" in reply_msg
    assert "!taskdone <task_id>" in reply_msg


@pytest.mark.asyncio
async def test_on_command_error_missing_and_bad_commits_argument(bot):
    ctx = MagicMock(spec=commands.Context)
    ctx.prefix = "!"
    ctx.command = bot.get_command("commits")
    ctx.invoked_with = "commits"
    ctx.reply = AsyncMock()

    param = MagicMock()
    param.name = "repo"
    err = commands.MissingRequiredArgument(param)

    await bot.on_command_error(ctx, err)
    reply_msg = ctx.reply.call_args[0][0]
    assert "Missing repository name" in reply_msg

    # Bad argument test
    ctx.reply.reset_mock()
    bad_err = commands.BadArgument("Converting limit failed")
    await bot.on_command_error(ctx, bad_err)
    bad_reply = ctx.reply.call_args[0][0]
    assert "Invalid limit argument" in bad_reply


@pytest.mark.asyncio
async def test_bot_tool_commands_execution(bot_with_tools):
    bot = bot_with_tools

    ctx = MagicMock(spec=commands.Context)
    ctx.prefix = "!"
    ctx.author.id = "test_user_discord"
    ctx.channel.id = "test_chan_123"
    ctx.reply = AsyncMock()

    # !time
    cmd_time = bot.get_command("time")
    await cmd_time.callback(ctx, timezone_name="UTC")
    assert "UTC" in ctx.reply.call_args[0][0]

    # !calc
    ctx.reply.reset_mock()
    cmd_calc = bot.get_command("calc")
    await cmd_calc.callback(ctx, expression="15 * 3")
    assert "45" in ctx.reply.call_args[0][0]

    # !task
    ctx.reply.reset_mock()
    cmd_task = bot.get_command("task")
    await cmd_task.callback(ctx, title="Buy milk")
    assert "Task #" in ctx.reply.call_args[0][0]
    assert "Buy milk" in ctx.reply.call_args[0][0]

    # !tasks
    ctx.reply.reset_mock()
    cmd_tasks = bot.get_command("tasks")
    await cmd_tasks.callback(ctx)
    assert "Buy milk" in ctx.reply.call_args[0][0]

    # !taskdone
    ctx.reply.reset_mock()
    cmd_taskdone = bot.get_command("taskdone")
    await cmd_taskdone.callback(ctx, task_id=1)
    assert "marked as completed" in ctx.reply.call_args[0][0]

    # !remind
    ctx.reply.reset_mock()
    cmd_remind = bot.get_command("remind")
    await cmd_remind.callback(ctx, args="in 10 minutes to take a break")
    assert "Reminder #" in ctx.reply.call_args[0][0]
    assert "take a break" in ctx.reply.call_args[0][0]

    # !reminders
    ctx.reply.reset_mock()
    cmd_reminders = bot.get_command("reminders")
    await cmd_reminders.callback(ctx)
    assert "take a break" in ctx.reply.call_args[0][0]

