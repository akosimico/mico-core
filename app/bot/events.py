from __future__ import annotations

import logging

import discord
from discord.ext import commands

logger = logging.getLogger("mico.bot.events")

DISCORD_MESSAGE_LIMIT = 2000


def register_events(bot: commands.Bot) -> None:
    @bot.event
    async def on_ready():
        user = bot.user
        logger.info("MICO is online as %s (id: %s)", user, user.id if user else "?")

    @bot.event
    async def on_message(message: discord.Message):
        # Let commands (like !reset) run too.
        await bot.process_commands(message)

        if message.author.bot:
            return
        if message.content.startswith(bot.command_prefix):
            return

        is_dm = isinstance(message.channel, discord.DMChannel)
        is_mentioned = bot.user in message.mentions if bot.user else False

        # Milestone 1: respond in DMs always, and in servers only when @mentioned.
        # (No "wake word" parsing yet — that's a cheap addition later if you want it.)
        if not is_dm and not is_mentioned:
            return

        content = message.content
        if bot.user:
            content = content.replace(f"<@{bot.user.id}>", "").replace(f"<@!{bot.user.id}>", "").strip()

        if not content:
            return

        agent = bot.mico_agent  # type: ignore[attr-defined]
        conversation_id = str(message.channel.id)

        async with message.channel.typing():
            try:
                reply = await agent.handle_message(conversation_id, content)
            except Exception:
                logger.exception("Failed to handle message in channel %s", conversation_id)
                await message.reply(
                    "Something went wrong talking to the model — check the bot's logs. Try again in a moment."
                )
                return

        await _send_long_message(message.channel, reply)

    @bot.command(name="reset")
    async def reset_command(ctx: commands.Context):
        agent = bot.mico_agent  # type: ignore[attr-defined]
        agent.reset(str(ctx.channel.id))
        await ctx.reply("Conversation history cleared for this channel.")


async def _send_long_message(channel: discord.abc.Messageable, text: str) -> None:
    """Discord caps messages at 2000 characters — split cleanly if the reply is longer."""
    if len(text) <= DISCORD_MESSAGE_LIMIT:
        await channel.send(text)
        return

    for i in range(0, len(text), DISCORD_MESSAGE_LIMIT):
        await channel.send(text[i : i + DISCORD_MESSAGE_LIMIT])
