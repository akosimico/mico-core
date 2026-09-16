# MICO — Milestone 2 (Core + Memory + FastAPI)

Personal AI agent accessible through Discord and REST API, with swappable AI providers and persistent memory (conversations, user preferences, and project-specific knowledge).

## Features

- **FastAPI Backend + Discord Bot**: Runs both concurrently in the same async event loop.
- **Provider Abstraction**: Easily switch between Gemini, Groq, OpenAI, and OpenRouter without modifying agent or bot code.
- **Persistent Short-Term Memory**: Conversation history tracked and stored in database per channel/session.
- **Long-Term & Project Memory**: Store and retrieve user preferences, facts, and project contexts (`!remember <fact>`, natural language "remember that...", `!memories`, `!forget <id>`).
- **Database Engine**: SQLAlchemy 2.0 async engine supporting PostgreSQL (`asyncpg`) in production and SQLite (`aiosqlite`) fallback for local development and testing.

## Setup

1. **Create a Discord bot:**
   - Go to the [Discord Developer Portal](https://discord.com/developers/applications) → New Application → Bot.
   - Under "Privileged Gateway Intents", enable **Message Content Intent**.
   - Copy the bot token.
   - Under OAuth2 → URL Generator, check `bot`, and permissions `Send Messages` + `Read Message History`. Use the generated URL to invite the bot to your server.

2. **Get an AI API key:**
   - Gemini: [Google AI Studio](https://aistudio.google.com/)
   - Or Groq / OpenAI / OpenRouter.

3. **Install dependencies:**
   ```bash
   python -m venv venv
   source venv/bin/activate   # Windows: venv\Scripts\activate
   pip install -r requirements.txt
   ```

4. **Configure:**
   ```bash
   cp .env.example .env
   # Edit .env: DISCORD_TOKEN, GEMINI_API_KEY / GROQ_API_KEY, DATABASE_URL
   ```

5. **Run:**
   ```bash
   python -m app.main
   ```
   FastAPI server will be available at `http://127.0.0.1:8000` (docs at `http://127.0.0.1:8000/docs`), and the Discord bot will connect in the background.

## Using it

- **DM the bot** — replies to every message.
- **In a server channel** — @mention the bot to talk to it.
- **`!remember <fact>`** — stores a long-term fact.
- **`!memories`** — lists your saved memories.
- **`!forget <id>`** — removes a saved memory by ID.
- **`!reset`** — clears conversation history for the current channel.
- **REST API** — use `POST /api/chat`, `GET /api/health`, and `/api/memories` endpoints.

## Running tests

```bash
pytest
```

## What's next

See [plan.md](plan.md) — Milestone 3 adds tool calling (time, calculator, tasks, reminders, and GitHub integration).
