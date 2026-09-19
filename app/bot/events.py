from __future__ import annotations

import logging
import re
from io import BytesIO

import discord
from discord.ext import commands

from app.automation.workers import DAILY_SUMMARY, WEEKLY_DEVELOPMENT_REPORT

logger = logging.getLogger("mico.bot.events")

DISCORD_MESSAGE_LIMIT = 2000
WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6}


def _parse_time(value: str) -> tuple[int, int]:
    parts = value.split(":")
    if len(parts) != 2 or not all(part.isdigit() for part in parts):
        raise ValueError("Time must use 24-hour HH:MM format.")
    hour, minute = int(parts[0]), int(parts[1])
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("Time must be between 00:00 and 23:59.")
    return hour, minute


def register_events(bot: commands.Bot) -> None:
    @bot.event
    async def on_ready():
        db = getattr(bot, "mico_database", None)
        if db is not None and not await db.acquire_bot_lease():
            logger.error("Another MICO Discord worker already owns the database lease; closing this duplicate worker.")
            bot.mico_is_active = False  # type: ignore[attr-defined]
            await bot.close()
            return
        user = bot.user
        logger.info("MICO is online as %s (id: %s)", user, user.id if user else "?")
        worker = getattr(bot, "automation_worker", None)
        if worker is not None:
            await worker.start()

    @bot.event
    async def on_message(message: discord.Message):
        if not getattr(bot, "mico_is_active", True):
            return
        # Process bot prefix commands first
        await bot.process_commands(message)

        if message.author.bot:
            return
        if message.content.startswith(bot.command_prefix):
            return

        is_dm = isinstance(message.channel, discord.DMChannel)
        is_mentioned = bot.user in message.mentions if bot.user else False

        # Respond in DMs always, and in servers only when @mentioned.
        if not is_dm and not is_mentioned:
            return

        content = message.content
        if bot.user:
            content = content.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip()

        voice_attachment = next(
            (attachment for attachment in message.attachments if (attachment.content_type or "").startswith("audio/")),
            None,
        )
        is_voice_turn = voice_attachment is not None
        if is_voice_turn:
            voice_service = getattr(bot, "voice_service", None)
            if voice_service is None or not voice_service.enabled:
                await message.reply("Voice input is not configured. Set `OPENAI_API_KEY` to enable it.")
                return
            try:
                content = await voice_service.transcribe(
                    await voice_attachment.read(), voice_attachment.filename, voice_attachment.content_type or "audio/ogg"
                )
            except Exception:
                logger.exception("Could not transcribe Discord voice attachment")
                await message.reply("I couldn't transcribe that audio message. Please try a shorter recording.")
                return

        if not content:
            return

        agent = bot.mico_agent  # type: ignore[attr-defined]
        conversation_id = str(message.channel.id)
        user_id = str(message.author.id)
        server_id = str(message.guild.id) if message.guild else None

        async with message.channel.typing():
            try:
                reply = await agent.handle_message(
                    conversation_id=conversation_id,
                    user_message=content,
                    user_id=user_id,
                    server_id=server_id,
                )
            except Exception:
                logger.exception("Failed to handle message in channel %s", conversation_id)
                await message.reply(
                    "Something went wrong talking to the model — check the bot's logs. Try again in a moment."
                )
                return

        await _send_long_message(message.channel, reply)
        if is_voice_turn:
            try:
                audio = await bot.voice_service.synthesize(reply)  # type: ignore[attr-defined]
                await message.channel.send(file=discord.File(BytesIO(audio), filename="mico-response.mp3"))
            except Exception:
                logger.exception("Could not synthesize voice response")

    # -------------------------------------------------------------------------
    # Help & Core Commands
    # -------------------------------------------------------------------------

    @bot.command(name="help")
    async def help_command(ctx: commands.Context):
        """Show available commands and usage guide."""
        p = ctx.prefix
        help_text = (
            "🤖 **MICO Commands & Usage Guide**\n\n"
            "**Chatting with MICO (AI with Tool Calling):**\n"
            "• In DMs: send any message directly.\n"
            "• In server channels: `@MICO <your message>`\n"
            "• Natural tool calling: MICO automatically executes tools when you ask questions like:\n"
            "  - *\"What time is it in Tokyo?\"*\n"
            "  - *\"Calculate 12 * 45 + sqrt(144)\"*\n"
            "  - *\"Remind me tomorrow at 10am to update portfolio\"*\n"
            "  - *\"Add write unit tests to my tasks\"* or *\"What are my tasks?\"*\n"
            "  - *\"Show the latest commits on akosimico/mico-jarvis\"*\n\n"
            "**Memory Commands:**\n"
            f"• `{p}remember <fact>` — Store a fact in long-term memory.\n"
            f"• `{p}memories` — List all your saved memories.\n"
            f"• `{p}forget <id>` — Delete a saved memory by ID.\n"
            f"• `{p}reset` — Clear conversation history for this channel.\n\n"
            "**Tool Quick Commands:**\n"
            f"• `{p}time [timezone]` — Check current time (e.g. `{p}time Asia/Tokyo`).\n"
            f"• `{p}calc <expression>` — Evaluate math (e.g. `{p}calc 25 * 4 + 10`).\n"
            f"• `{p}remind <time> to <content>` — Set a reminder (e.g. `{p}remind in 15m to deploy`).\n"
            f"• `{p}reminders` — List active reminders.\n"
            f"• `{p}task <title>` — Add a new to-do task.\n"
            f"• `{p}tasks [status]` — List tasks (optional: pending/completed).\n"
            f"• `{p}taskdone <id>` — Mark a task completed.\n"
            f"• `{p}repos [user]` — List GitHub repositories.\n"
            f"• `{p}commits <owner/repo>` — View latest repository commits.\n"
            f"• `{p}issues <owner/repo>` — View open issues in a repository.\n"
        )
        help_text += (
            "\n**Automations:**\n"
            f"• `{p}automation daily on [HH:MM]` — Enable daily task summaries (default: 08:00).\n"
            f"• `{p}automation weekly on [DAY] [HH:MM]` — Enable weekly development reports (default: Monday 09:00).\n"
            f"• `{p}automation <daily|weekly> off` — Disable an automation.\n"
            f"• `{p}automations` — Show your automation schedules.\n"
            "\n**Monitoring:**\n"
            f"• `{p}monitor add <name> <https://url> [seconds]` — Monitor a service (minimum interval: 15 seconds).\n"
            f"• `{p}monitor remove <id>` — Stop monitoring a service.\n"
            f"• `{p}monitors` — Show service health and last check results.\n"
            "\n**PC Agent:**\n"
            f"• `{p}confirm <code>` — Execute a queued modifying PC action.\n"
            f"• `{p}cancel <code>` — Cancel a queued PC action.\n"
        )
        await ctx.reply(help_text)

    @bot.command(name="reset")
    async def reset_command(ctx: commands.Context):
        """Clear conversation history for the current channel."""
        agent = bot.mico_agent  # type: ignore[attr-defined]
        await agent.areset(str(ctx.channel.id))
        await ctx.reply("Conversation history cleared for this channel.")

    # -------------------------------------------------------------------------
    # Memory Commands
    # -------------------------------------------------------------------------

    @bot.command(name="remember")
    async def remember_command(ctx: commands.Context, *, fact: str):
        """Explicitly store a fact in MICO's long-term memory."""
        agent = bot.mico_agent  # type: ignore[attr-defined]
        mem = await agent.remember(user_id=str(ctx.author.id), content=fact)
        if mem:
            await ctx.reply(f'Remembered: "{mem.content}" (ID: `{mem.id}`)')
        else:
            await ctx.reply("Memory persistence is not enabled.")

    @bot.command(name="memories")
    async def memories_command(ctx: commands.Context):
        """List all remembered facts for the current user."""
        agent = bot.mico_agent  # type: ignore[attr-defined]
        mems = await agent.get_user_memories(user_id=str(ctx.author.id))
        if not mems:
            await ctx.reply(
                "I don't have any saved memories for you yet. Use `!remember <fact>` or say 'remember that...'"
            )
            return
        lines = [f"`#{m.id}` [{m.category}] {m.content}" for m in mems]
        await ctx.reply("**Your saved memories:**\n" + "\n".join(lines))

    @bot.command(name="forget")
    async def forget_command(ctx: commands.Context, memory_id: int):
        """Delete a saved memory by ID."""
        agent = bot.mico_agent  # type: ignore[attr-defined]
        success = await agent.forget(memory_id=memory_id, user_id=str(ctx.author.id))
        if success:
            await ctx.reply(f"Memory `#{memory_id}` has been forgotten.")
        else:
            await ctx.reply(f"Could not find memory `#{memory_id}` belonging to you.")

    # -------------------------------------------------------------------------
    # Tool Commands (Direct Manual Invocation)
    # -------------------------------------------------------------------------

    @bot.command(name="time")
    async def time_command(ctx: commands.Context, *, timezone_name: str = "UTC"):
        """Check current time in a specified timezone."""
        agent = bot.mico_agent  # type: ignore[attr-defined]
        registry = agent.tool_registry
        if registry:
            result = await registry.execute("get_time", timezone_name=timezone_name)
            await ctx.reply(result)
        else:
            await ctx.reply("Tool execution is not enabled.")

    @bot.command(name="calc")
    async def calc_command(ctx: commands.Context, *, expression: str):
        """Calculate mathematical expression."""
        agent = bot.mico_agent  # type: ignore[attr-defined]
        registry = agent.tool_registry
        if registry:
            result = await registry.execute("calculator", expression=expression)
            await ctx.reply(result)
        else:
            await ctx.reply("Tool execution is not enabled.")

    @bot.command(name="remind")
    async def remind_command(ctx: commands.Context, *, args: str):
        """Set a reminder. Format: !remind <time> to <content> (e.g. !remind in 15m to deploy)"""
        # Split on " to " or " | "
        parts = re.split(r"\s+(?:to|\|\s*)\s*", args, maxsplit=1)
        if len(parts) < 2:
            await ctx.reply("⚠️ Format: `!remind <time> to <what>`\n*Example:* `!remind in 20 minutes to check email`")
            return
        remind_at, content = parts[0].strip(), parts[1].strip()

        agent = bot.mico_agent  # type: ignore[attr-defined]
        registry = agent.tool_registry
        if registry:
            res = await registry.execute(
                "create_reminder",
                user_id=str(ctx.author.id),
                content=content,
                remind_at=remind_at,
                channel_id=str(ctx.channel.id),
            )
            await ctx.reply(res)
        else:
            await ctx.reply("Tool execution is not enabled.")

    @bot.command(name="reminders")
    async def reminders_command(ctx: commands.Context):
        """List active reminders."""
        agent = bot.mico_agent  # type: ignore[attr-defined]
        registry = agent.tool_registry
        if registry:
            res = await registry.execute("list_reminders", user_id=str(ctx.author.id))
            await ctx.reply(res)
        else:
            await ctx.reply("Tool execution is not enabled.")

    @bot.command(name="task")
    async def task_command(ctx: commands.Context, *, title: str):
        """Add a to-do task."""
        agent = bot.mico_agent  # type: ignore[attr-defined]
        registry = agent.tool_registry
        if registry:
            res = await registry.execute("create_task", user_id=str(ctx.author.id), title=title)
            await ctx.reply(res)
        else:
            await ctx.reply("Tool execution is not enabled.")

    @bot.command(name="tasks")
    async def tasks_command(ctx: commands.Context, status: str | None = None):
        """List tasks (optional status: pending/completed)."""
        agent = bot.mico_agent  # type: ignore[attr-defined]
        registry = agent.tool_registry
        if registry:
            res = await registry.execute("list_tasks", user_id=str(ctx.author.id), status=status)
            await ctx.reply(res)
        else:
            await ctx.reply("Tool execution is not enabled.")

    @bot.command(name="taskdone")
    async def taskdone_command(ctx: commands.Context, task_id: int):
        """Mark a task completed by ID."""
        agent = bot.mico_agent  # type: ignore[attr-defined]
        registry = agent.tool_registry
        if registry:
            res = await registry.execute("complete_task", user_id=str(ctx.author.id), task_id=task_id)
            await ctx.reply(res)
        else:
            await ctx.reply("Tool execution is not enabled.")

    @bot.command(name="automation")
    async def automation_command(ctx: commands.Context, kind: str, action: str, *options: str):
        """Configure daily summaries or weekly development reports."""
        service = getattr(bot, "automation_service", None)
        if service is None:
            await ctx.reply("Automation persistence is not enabled.")
            return
        kind, action = kind.lower(), action.lower()
        task = DAILY_SUMMARY if kind == "daily" else WEEKLY_DEVELOPMENT_REPORT if kind == "weekly" else None
        if task is None or action not in {"on", "off"}:
            await ctx.reply("Usage: `!automation daily on [HH:MM]`, `!automation weekly on [DAY] [HH:MM]`, or `!automation <daily|weekly> off`")
            return
        if action == "off":
            await ctx.reply(f"{'✅ ' + kind.title() + ' automation disabled.' if await service.disable(str(ctx.author.id), task) else 'No ' + kind + ' automation is configured yet.'}")
            return
        try:
            if kind == "daily":
                hour, minute = _parse_time(options[0] if options else "08:00")
                schedule = f"{minute} {hour} * * *"
            else:
                day = options[0].lower() if options else "monday"
                if day not in WEEKDAYS:
                    raise ValueError("Day must be Monday through Sunday.")
                hour, minute = _parse_time(options[1] if len(options) > 1 else "09:00")
                schedule = f"{minute} {hour} * * {WEEKDAYS[day]}"
            record = await service.enable(str(ctx.author.id), task, schedule, str(ctx.channel.id))
            await ctx.reply(f"✅ {kind.title()} automation enabled for `{schedule}` ({bot.mico_settings.default_timezone}). Next run: <t:{int(record.next_run.timestamp())}:R>.")  # type: ignore[attr-defined]
        except ValueError as exc:
            await ctx.reply(f"⚠️ {exc}")

    @bot.command(name="automations")
    async def automations_command(ctx: commands.Context):
        """List recurring automations configured for the current user."""
        service = getattr(bot, "automation_service", None)
        if service is None:
            await ctx.reply("Automation persistence is not enabled.")
            return
        records = await service.list_for_user(str(ctx.author.id))
        if not records:
            await ctx.reply("You have no configured automations. Use `!automation daily on` to get started.")
            return
        lines = ["⚙️ **Your Automations:**"]
        for record in records:
            label = "Daily summary" if record.task == DAILY_SUMMARY else "Weekly development report"
            lines.append(f"• **{label}** — {'enabled' if record.enabled else 'disabled'}; `{record.schedule}`; next: <t:{int(record.next_run.timestamp())}:R>")
        await ctx.reply("\n".join(lines))

    @bot.command(name="monitor")
    async def monitor_command(ctx: commands.Context, action: str, *args: str):
        """Add or remove an HTTP service monitor."""
        service = getattr(bot, "monitoring_service", None)
        if service is None:
            await ctx.reply("Monitoring persistence is not enabled.")
            return
        action = action.lower()
        if action == "add":
            if len(args) < 2:
                await ctx.reply("⚠️ Usage: `!monitor add <name> <https://url> [seconds]`")
                return
            try:
                interval = int(args[2]) if len(args) > 2 else 60
                record = await service.add(str(ctx.author.id), str(ctx.channel.id), args[0], args[1], interval)
                await ctx.reply(f"✅ Monitoring `{record.name}` every {record.interval_seconds}s: {record.url} (ID: `{record.id}`)")
            except (ValueError, TypeError) as exc:
                await ctx.reply(f"⚠️ {exc}")
            return
        if action == "remove":
            if not args or not args[0].isdigit():
                await ctx.reply("⚠️ Usage: `!monitor remove <id>`")
                return
            await ctx.reply("✅ Monitor removed." if await service.remove(str(ctx.author.id), int(args[0])) else "Could not find that monitor.")
            return
        await ctx.reply("⚠️ Usage: `!monitor add <name> <https://url> [seconds]` or `!monitor remove <id>`")

    @bot.command(name="monitors")
    async def monitors_command(ctx: commands.Context):
        """List monitored services for the current user."""
        service = getattr(bot, "monitoring_service", None)
        if service is None:
            await ctx.reply("Monitoring persistence is not enabled.")
            return
        records = await service.list_for_user(str(ctx.author.id))
        if not records:
            await ctx.reply("You are not monitoring any services. Use `!monitor add` to get started.")
            return
        lines = ["🩺 **Monitored Services:**"]
        for record in records:
            state = record.last_status or "pending first check"
            detail = f" — {record.last_error}" if record.last_error else ""
            lines.append(f"• `#{record.id}` **{record.name}**: {state}{detail} ({record.url}; every {record.interval_seconds}s)")
        await ctx.reply("\n".join(lines))

    @bot.command(name="confirm")
    async def confirm_command(ctx: commands.Context, token: str):
        """Confirm a queued PC action owned by the invoking user."""
        service = getattr(bot, "pc_service", None)
        if service is None:
            await ctx.reply("PC action service is not enabled.")
            return
        await ctx.reply(await service.confirm(str(ctx.author.id), token))

    @bot.command(name="cancel")
    async def cancel_command(ctx: commands.Context, token: str):
        """Cancel a queued PC action owned by the invoking user."""
        service = getattr(bot, "pc_service", None)
        if service is None:
            await ctx.reply("PC action service is not enabled.")
            return
        await ctx.reply("✅ Pending action cancelled." if await service.cancel(str(ctx.author.id), token) else "No pending action found for that confirmation code.")

    @bot.command(name="repos")
    async def repos_command(ctx: commands.Context, username: str | None = None):
        """List GitHub repositories."""
        agent = bot.mico_agent  # type: ignore[attr-defined]
        registry = agent.tool_registry
        if registry:
            res = await registry.execute("github_get_repositories", username=username)
            await ctx.reply(res)
        else:
            await ctx.reply("Tool execution is not enabled.")

    @bot.command(name="commits")
    async def commits_command(ctx: commands.Context, repo: str, limit: int = 5):
        """List latest commits on a GitHub repository."""
        agent = bot.mico_agent  # type: ignore[attr-defined]
        registry = agent.tool_registry
        if registry:
            res = await registry.execute("github_get_commits", repo=repo, limit=limit)
            await ctx.reply(res)
        else:
            await ctx.reply("Tool execution is not enabled.")

    @bot.command(name="issues")
    async def issues_command(ctx: commands.Context, repo: str, state: str = "open"):
        """List issues on a GitHub repository."""
        agent = bot.mico_agent  # type: ignore[attr-defined]
        registry = agent.tool_registry
        if registry:
            res = await registry.execute("github_get_issues", repo=repo, state=state)
            await ctx.reply(res)
        else:
            await ctx.reply("Tool execution is not enabled.")

    # -------------------------------------------------------------------------
    # Command Error Handler
    # -------------------------------------------------------------------------

    @bot.event
    async def on_command_error(ctx: commands.Context, error: Exception):
        """Deliver friendly error & usage messages in Discord instead of failing silently to terminal."""
        if isinstance(error, commands.CommandInvokeError):
            error = error.original

        prefix = ctx.prefix or "!"
        cmd_name = ctx.command.name if ctx.command else (ctx.invoked_with or "command")

        if isinstance(error, commands.MissingRequiredArgument):
            if cmd_name == "remember":
                await ctx.reply(
                    f"⚠️ **Missing fact to remember.**\n"
                    f"**Usage:** `{prefix}remember <fact>`\n"
                    f"**Example:** `{prefix}remember I prefer Python over JavaScript`"
                )
            elif cmd_name == "forget":
                await ctx.reply(
                    f"⚠️ **Missing memory ID.**\n"
                    f"**Usage:** `{prefix}forget <id>`\n"
                    f"**Example:** `{prefix}forget 1` (use `{prefix}memories` to see all IDs)"
                )
            elif cmd_name == "calc":
                await ctx.reply(
                    f"⚠️ **Missing math expression.**\n"
                    f"**Usage:** `{prefix}calc <expression>`\n"
                    f"**Example:** `{prefix}calc 12 * 45 + sqrt(144)`"
                )
            elif cmd_name == "remind":
                await ctx.reply(
                    f"⚠️ **Missing reminder details.**\n"
                    f"**Usage:** `{prefix}remind <time> to <what>`\n"
                    f"**Example:** `{prefix}remind in 15 minutes to take a break`"
                )
            elif cmd_name == "task":
                await ctx.reply(
                    f"⚠️ **Missing task title.**\n"
                    f"**Usage:** `{prefix}task <title>`\n"
                    f"**Example:** `{prefix}task Update portfolio README`"
                )
            elif cmd_name == "taskdone":
                await ctx.reply(
                    f"⚠️ **Missing task ID.**\n"
                    f"**Usage:** `{prefix}taskdone <task_id>`\n"
                    f"**Example:** `{prefix}taskdone 1` (use `{prefix}tasks` to see IDs)"
                )
            elif cmd_name == "automation":
                await ctx.reply(
                    f"⚠️ **Missing automation details.**\n"
                    f"**Usage:** `{prefix}automation daily on [HH:MM]` or `{prefix}automation weekly on [DAY] [HH:MM]`\n"
                    f"**Example:** `{prefix}automation daily on 08:30`"
                )
            elif cmd_name == "monitor":
                await ctx.reply(
                    f"⚠️ **Missing monitor details.**\n"
                    f"**Usage:** `{prefix}monitor add <name> <https://url> [seconds]`\n"
                    f"**Example:** `{prefix}monitor add portfolio https://example.com 60`"
                )
            elif cmd_name in ("confirm", "cancel"):
                await ctx.reply(
                    f"⚠️ **Missing confirmation code.**\n"
                    f"**Usage:** `{prefix}{cmd_name} <code>`\n"
                    f"**Example:** `{prefix}{cmd_name} ABCD1234`"
                )
            elif cmd_name in ("commits", "issues"):
                await ctx.reply(
                    f"⚠️ **Missing repository name.**\n"
                    f"**Usage:** `{prefix}{cmd_name} <owner/repo>`\n"
                    f"**Example:** `{prefix}{cmd_name} akosimico/mico-jarvis`"
                )
            else:
                await ctx.reply(
                    f"⚠️ **Missing argument:** `{error.param.name}`\n"
                    f"Type `{prefix}help` for usage details."
                )
            return

        if isinstance(error, commands.BadArgument):
            if cmd_name in ("forget", "taskdone"):
                await ctx.reply(
                    f"⚠️ **Invalid numeric ID.** The ID must be a number.\n"
                    f"**Example:** `{prefix}{cmd_name} 1`"
                )
            elif cmd_name in ("commits", "issues"):
                await ctx.reply(
                    f"⚠️ **Invalid limit argument.** The limit must be a number.\n"
                    f"**Example:** `{prefix}{cmd_name} akosimico/mico-jarvis 5`"
                )
            else:
                await ctx.reply(
                    f"⚠️ **Invalid argument** provided for `{prefix}{cmd_name}`.\n"
                    f"Type `{prefix}help` for usage details."
                )
            return

        if isinstance(error, commands.CommandNotFound):
            await ctx.reply(
                f"⚠️ Unknown command `{prefix}{ctx.invoked_with}`. Type `{prefix}help` to view all available commands."
            )
            return

        logger.exception("Error executing command %s: %s", cmd_name, error)
        await ctx.reply(
            f"⚠️ An unexpected error occurred while running `{prefix}{cmd_name}`. Please try again."
        )


async def _send_long_message(channel: discord.abc.Messageable, text: str) -> None:
    """Discord caps messages at 2000 characters — split cleanly if the reply is longer."""
    if len(text) <= DISCORD_MESSAGE_LIMIT:
        await channel.send(text)
        return

    for i in range(0, len(text), DISCORD_MESSAGE_LIMIT):
        await channel.send(text[i : i + DISCORD_MESSAGE_LIMIT])
