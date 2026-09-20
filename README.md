# Mico Core

Mico Core is a self-hosted personal AI automation assistant for Discord. It combines natural conversation, tool calling, memory, reminders, GitHub workflows, voice, and a lightweight dashboard in one project you can run with your own credentials.

Built for developers who want a capable assistant without handing control of their workflows, data, or provider accounts to a hosted bot.

## What it does

- Chat naturally in Discord DMs or by mentioning the bot in a server.
- Use Gemini, Groq, OpenAI, or OpenRouter through one provider abstraction.
- Create tasks and reminders, remember useful facts, and schedule daily or weekly summaries.
- Query GitHub repositories, commits, and issues; optionally receive signed webhook notifications.
- Monitor HTTP services and receive outage and recovery alerts.
- Transcribe Discord audio and return text-to-speech responses with OpenAI Audio.
- Work with a confirmation-gated local PC agent for workspace files, Git status, commands, and deployments.
- View tasks, reminders, automations, service health, and activity in the React dashboard.

## Architecture

Mico Core runs a FastAPI API and Discord bot on the same async foundation. SQLAlchemy supports SQLite for local development and PostgreSQL for Docker or production. The React/Tailwind dashboard consumes the API, while a background worker handles reminders, summaries, monitoring, and GitHub notifications.

## Quick start

### Prerequisites

- Python 3.11 or newer
- A Discord application and bot token
- An API key for one supported AI provider (Gemini is the default)
- Node.js 20+ only if you want to run or build the dashboard

### 1. Clone and install

```bash
git clone https://github.com/akosimico/mico-core.git
cd mico-core

python -m venv venv
# macOS/Linux
source venv/bin/activate
# Windows PowerShell
# .\\venv\\Scripts\\Activate.ps1

pip install -r requirements.txt
```

### 2. Create your local configuration

```bash
# macOS/Linux
cp .env.example .env
# Windows PowerShell
# Copy-Item .env.example .env
```

Open `.env` and set your Discord bot token and one provider key. For the default Gemini setup, the minimum is:

```dotenv
DISCORD_TOKEN=your-discord-bot-token
AI_PROVIDER=gemini
GEMINI_API_KEY=your-gemini-api-key
```

The included configuration uses SQLite (`mico.db`) locally, so no database service is needed for this path.

### 3. Create and invite a Discord bot

1. In the [Discord Developer Portal](https://discord.com/developers/applications), create an application and add a bot.
2. Under **Bot**, enable **Message Content Intent** in Privileged Gateway Intents.
3. Copy the bot token into `DISCORD_TOKEN` in your `.env` file.
4. Under **OAuth2 → URL Generator**, select the `bot` scope and grant at least **Send Messages** and **Read Message History**. Open the generated URL to invite the bot to your server.

### 4. Run Mico Core

```bash
python -m app.main
```

The API is available at [http://127.0.0.1:8000](http://127.0.0.1:8000), with interactive API documentation at [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs). Send the bot a DM, or mention it in a server with `@MICO <message>`.

## Configuration

Copy `.env.example` to `.env`; it documents every supported setting. Do not commit `.env`—it is already ignored by Git.

| Goal | Required settings |
| --- | --- |
| Default Gemini bot | `DISCORD_TOKEN`, `GEMINI_API_KEY` |
| Groq bot | `DISCORD_TOKEN`, `AI_PROVIDER=groq`, `GROQ_API_KEY` |
| OpenAI bot | `DISCORD_TOKEN`, `AI_PROVIDER=openai`, `OPENAI_API_KEY` |
| OpenRouter bot | `DISCORD_TOKEN`, `AI_PROVIDER=openrouter`, `OPENAI_API_KEY`, `OPENAI_BASE_URL` |
| API-only mode | `ENABLE_BOT=false` plus an AI provider key |
| Voice replies | `VOICE_ENABLED=true`, `OPENAI_API_KEY` |
| Docker/PostgreSQL | `POSTGRES_PASSWORD` and `docker compose up --build` |

`GITHUB_TOKEN`, webhook settings, monitoring, automation schedules, and PC-agent settings are optional. See the comments in `.env.example` before enabling them.

## Using the bot

Mico Core chooses tools from natural language. For example:

- “What time is it in Manila?”
- “Remind me tomorrow at 9 AM to review the pull request.”
- “Add write integration tests to my tasks.”
- “Show the latest commits on akosimico/mico-core.”

You can also use fast command shortcuts:

| Command | Description |
| --- | --- |
| `!time [timezone]` | Show the current time in a timezone. |
| `!calc <expression>` | Calculate a safe arithmetic expression. |
| `!remind <time> to <what>` | Create a reminder. |
| `!reminders` | List reminders. |
| `!task <title>` / `!tasks [status]` / `!taskdone <id>` | Manage tasks. |
| `!remember <fact>` / `!memories` / `!forget <id>` | Manage long-term memory. |
| `!repos [user]` / `!commits <owner/repo>` / `!issues <owner/repo>` | Query GitHub. |
| `!automation ...` / `!automations` | Manage daily and weekly summaries. |
| `!monitor add|remove|list` | Manage HTTP service monitoring. |
| `!confirm <code>` / `!cancel <code>` | Approve or cancel a queued PC-agent action. |
| `!help` | Show the complete Discord command guide. |

## API and dashboard

The REST API supports chat, tool inspection/execution, tasks, reminders, memories, voice, GitHub webhooks, and dashboard data. Explore the complete schema at `/docs` after starting the API.

To run the dashboard locally:

```bash
cd frontend
npm ci
npm run dev
```

For the full stack with PostgreSQL, separate API/worker containers, and the dashboard:

```bash
# Set POSTGRES_PASSWORD in .env first
docker compose up --build
```

The dashboard will be available at [http://localhost:3000](http://localhost:3000).

## Security notes

- Keep API keys and Discord tokens only in `.env`; never commit or share that file.
- The local PC agent is restricted to `PC_WORKSPACE_ROOT`. Writing files, deleting files, commands, Git writes, and deployments require an explicit Discord confirmation code.
- Use a dedicated Discord server and least-privilege provider and GitHub tokens when testing integrations.
- Validate and configure `GITHUB_WEBHOOK_SECRET` before exposing the webhook endpoint publicly.

## Development

Run the test suite:

```bash
pytest -q
```

Build the dashboard:

```bash
cd frontend
npm ci
npm run build
```

Additional operational details and a demo flow are available in [docs/operations.md](docs/operations.md) and [docs/demo-script.md](docs/demo-script.md).

## Contributing

Fork the repository, create a focused branch, add or update tests for behavioral changes, and open a pull request with a concise description of the problem and solution. Please keep secrets, local databases, and generated build output out of commits.

## License

Mico Core is available under the [MIT License](LICENSE). Created by Mico Helis.
