from __future__ import annotations

import logging

from app.ai.agent import Agent
from app.ai.provider import get_provider
from app.bot.client import build_bot
from app.config import get_settings


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    )


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level)

    logger = logging.getLogger("mico.main")
    logger.info("Starting MICO (provider=%s)", settings.ai_provider)

    provider = get_provider(settings)
    agent = Agent(provider=provider, max_history_messages=settings.max_history_messages)
    bot = build_bot(settings, agent)

    bot.run(settings.discord_token)


if __name__ == "__main__":
    main()
