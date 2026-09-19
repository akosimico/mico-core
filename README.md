# MICO — Milestone 7 (PC Agent)

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
- **Automation Engine**: A lifecycle-managed background worker delivers reminders, daily task summaries, and weekly GitHub development reports to Discord, with DM fallback.
- **Developer Assistant**: Project-aware task management, GitHub queries for today's commits and stale repositories, and signed GitHub webhook notifications relayed to Discord.
- **Service Monitoring**: Configurable HTTP health checks with Discord alerts on failures and recovery notifications that include downtime.
- **PC Agent**: Workspace-confined file, search, project, and Git-status actions, plus explicit Discord confirmation for commands, deletion, Git writes, and deployment.
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
  - `!automation daily on [HH:MM]` — Enable a daily task summary (default: 08:00).
  - `!automation weekly on [DAY] [HH:MM]` — Enable a weekly development report (default: Monday 09:00).
  - `!automation <daily|weekly> off` — Disable a recurring automation.
  - `!automations` — List configured automation schedules.
  - `!monitor add <name> <https://url> [seconds]` — Monitor a service endpoint.
  - `!monitor remove <id>` — Stop monitoring a service.
  - `!monitors` — Show monitored services and their latest health state.
  - `!confirm <code>` — Execute a pending modifying PC action.
  - `!cancel <code>` — Cancel a pending PC action.
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

Configure GitHub webhooks with `GITHUB_WEBHOOK_SECRET` and `GITHUB_WEBHOOK_CHANNEL_ID`, then point GitHub at `POST /api/webhooks/github`. MICO validates `X-Hub-Signature-256` before posting push, issue, and pull-request events to Discord.

Set `PC_WORKSPACE_ROOT` to the only directory MICO may access. Optionally allow safe app launches with `PC_ALLOWED_APPLICATIONS=code,notepad`. Modifying actions always require a user-specific `!confirm` code and are written to the audit log.

See [plan.md](plan.md) for completed milestones and upcoming work.
