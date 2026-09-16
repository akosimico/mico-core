# MICO — Milestone 3 (Core + Memory + Tool Calling)

Personal AI agent accessible through Discord and REST API, featuring multi-turn conversation memory, swappable AI providers, and function/tool calling (system utilities, task & reminder tracking, and GitHub integration).

## Features

- **FastAPI Backend + Discord Bot**: Runs both concurrently in the same async event loop.
- **Provider Abstraction with Tool Calling**: Seamless tool execution across Gemini, Groq, OpenAI, and OpenRouter without modifying agent or bot logic.
- **10 Core Tools Built-in**:
  1. `get_time(timezone_name)` — Timezone and local time lookup.
  2. `calculator(expression)` — AST-safe arithmetic and math expressions.
  3. `create_reminder(user_id, content, remind_at, channel_id)` — Relative and absolute reminder scheduler.
  4. `list_reminders(user_id, include_completed)` — Query active or completed reminders.
  5. `create_task(user_id, title, description, due_date)` — Add tasks to persistent to-do list.
  6. `list_tasks(user_id, status)` — Filter and display tasks.
  7. `complete_task(user_id, task_id)` — Mark tasks as completed.
  8. `github_get_repositories(username)` — List recent GitHub repositories.
  9. `github_get_commits(repo, limit)` — View latest git commits on a repository.
  10. `github_get_issues(repo, state, limit)` — View issues on a repository.
- **Natural AI Tool Calling**: Ask natural questions like *"What time is it in Tokyo?"*, *"Calculate 25 * 4 + 10"*, or *"Add update README to my tasks"*, and MICO automatically invokes the right tools and incorporates results into its response.
- **Persistent Memory**: Short-term conversation history and long-term user facts and project preferences (`!remember`, `!memories`, `!forget`).
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
   # Edit .env: DISCORD_TOKEN, GEMINI_API_KEY / GROQ_API_KEY, DATABASE_URL, etc.
   ```

5. **Run:**
   ```bash
   python -m app.main
   ```
   FastAPI server will be available at `http://127.0.0.1:8000` (interactive Swagger UI docs at `http://127.0.0.1:8000/docs`), and the Discord bot will connect in the background.

## Using it

- **DM the bot** — replies to every message.
- **In a server channel** — `@MICO <your message>` to interact.
- **Natural Tool Invocations** — e.g. *"What are my tasks?"*, *"What time is it in Manila?"*, *"Show recent commits on akosimico/mico-jarvis"*.
- **Quick Commands**:
  - `!time [timezone]` — Check current time.
  - `!calc <expression>` — Quick calculator.
  - `!remind <time> to <what>` — Schedule a reminder.
  - `!reminders` — List active reminders.
  - `!task <title>` — Add a task.
  - `!tasks [status]` — List tasks.
  - `!taskdone <id>` — Mark a task completed.
  - `!repos [user]` — List GitHub repositories.
  - `!commits <owner/repo>` — View recent commits.
  - `!issues <owner/repo>` — View open issues.
  - `!remember <fact>` — Store long-term memory.
  - `!memories` — List saved memories.
  - `!forget <id>` — Delete memory.
  - `!reset` — Clear conversation history for channel.
  - `!help` — Display comprehensive command guide.
- **REST API**:
  - `POST /api/chat` — Chat with MICO (natural tool calling enabled).
  - `GET /api/tools` & `POST /api/tools/execute` — Introspect and execute tools.
  - `GET/POST /api/tasks`, `PATCH /api/tasks/{id}/complete` — Manage tasks.
  - `GET/POST /api/reminders` — Manage reminders.
  - `GET/POST/DELETE /api/memories` — Memory CRUD endpoints.

## Running tests

```bash
pytest
```

## What's next

See [plan.md](plan.md) — Milestone 4 adds the Automation Engine (background worker loop, automated reminders, daily summaries, and health checks).
