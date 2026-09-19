# MICO — Personal AI Automation Assistant

**Status:** In Progress
**Started:** September 2026
**Current milestone:** Milestone 7 (Milestones 1, 2, 3, 4, 5 & 6 completed)

## What this is

MICO is a JARVIS-inspired personal AI agent, accessible through Discord, that can
understand natural language, remember context, call tools, automate tasks,
monitor services, and (eventually) act on your PC and respond to voice.

Core principle: **LLM ≠ MICO.** The LLM is just the reasoning component. MICO is
the whole agent system wrapped around it — router, memory, tools, scheduler,
database, Discord client.

```
                     ┌──────────────────────┐
                     │       MICO AI         │
                     │   Agent / Brain       │
                     └──────────┬────────────┘
                                │
                     ┌──────────▼────────────┐
                     │     Agent Router       │
                     │  Intent + Tool Select  │
                     └──────────┬────────────┘
                                │
         ┌──────────────────────┼──────────────────────┐
         ▼                      ▼                      ▼
   ┌───────────┐         ┌────────────┐         ┌───────────┐
   │  Memory   │         │   Tools    │         │ Scheduler │
   └───────────┘         └─────┬──────┘         └───────────┘
                                │
          ┌─────────────────────┼─────────────────────┐
          ▼                     ▼                     ▼
       GitHub                System                Web/API
          │                     │                     │
          ▼                     ▼                     ▼
    Repositories           PC actions            External data

                     ┌─────────────────────┐
                     │      PostgreSQL      │
                     └─────────────────────┘
                                ▲
                                │
                        ┌───────┴───────┐
                        │    Discord    │
                        │    Client     │
                        └───────────────┘
```

## Golden rule

**Don't start with the JARVIS UI. Start with the agent architecture.**

First real milestone target:

```
You:  Mico, what time is it?
Mico: It's 12:17 AM.

You:  Mico, remind me tomorrow at 10 AM to work on my portfolio.
Mico: Done. I'll remind you tomorrow at 10 AM.

You:  Mico, what are my tasks?
Mico: You have 3 active tasks...
```

Once that's reliable, everything else builds on top of it.

---

## Tech stack

| Layer | Choice | Notes |
|---|---|---|
| Backend | Python + FastAPI | async, great AI ecosystem, easy Discord + REST integration |
| Discord | discord.py | |
| Database | PostgreSQL | users, servers, conversations, messages, memories, projects, tasks, reminders, tool_executions, audit_logs |
| Cache / queue | none at first → Redis + Celery/ARQ later | don't add until scheduler/workers need it |
| AI provider | **Gemini by default**, but provider must be swappable | see below |
| Frontend | React + Tailwind (later) | MICO dashboard, Milestone 8+ |
| Deployment | local first → Docker Compose (Postgres, Redis, FastAPI, bot, worker, React) later | |

### Provider abstraction (important — build this from day one)

Never hardcode Gemini calls directly into agent logic. Put a thin provider
interface in front of it so swapping later is a config change, not a rewrite:

```
MICO
 │
 ├── OpenAI-compatible API
 ├── OpenRouter
 ├── Gemini   ← default
 └── Local model
```

`app/ai/providers.py` should expose one common interface (e.g. `generate()`,
`generate_with_tools()`), with a `GeminiProvider` implementation first and a
`.env` var (`AI_PROVIDER=gemini`) selecting it. Adding OpenAI/OpenRouter/local
later should mean writing one new class, not touching the agent or router.

---

## Suggested repo structure (target end-state)

```
MICO/
├── backend/
│   ├── app/
│   │   ├── ai/
│   │   │   ├── agent.py
│   │   │   ├── memory.py
│   │   │   ├── prompts.py
│   │   │   └── providers.py
│   │   ├── bot/
│   │   │   ├── discord.py
│   │   │   └── commands.py
│   │   ├── tools/
│   │   │   ├── github.py
│   │   │   ├── system.py
│   │   │   ├── tasks.py
│   │   │   ├── web.py
│   │   │   └── monitoring.py
│   │   ├── automation/
│   │   │   ├── scheduler.py
│   │   │   └── workers.py
│   │   ├── database/
│   │   │   ├── models.py
│   │   │   └── migrations/
│   │   └── main.py
│   └── tests/
├── frontend/
│   └── React dashboard
├── docker/
├── docs/
├── .env.example
├── docker-compose.yml
└── README.md
```

(Milestone 1 starts with a much smaller version of this — see below.)

---

## Milestone checklist

### 🟢 Milestone 1 — MICO Core (Completed)
Goal: `Discord → MICO → Gemini → Discord`, reliably.

- [x] FastAPI project scaffold (`app/main.py`, `config.py`)
- [x] discord.py bot boots and responds to a message
- [x] `app/ai/providers.py` with `GeminiProvider` behind a common interface
- [x] Basic system prompt for MICO's persona
- [x] In-memory conversation history (per channel/user)
- [x] Error handling (API failures, rate limits, bad input)
- [x] Basic logging
- [x] `.env.example` with `AI_PROVIDER`, `GEMINI_API_KEY`, `DISCORD_TOKEN`

Minimal structure for this milestone only:
```
mico/
├── app/
│   ├── main.py
│   ├── bot/{client.py, events.py}
│   ├── ai/{provider.py, prompts.py, agent.py}
│   ├── database/{models.py, database.py}
│   └── config.py
├── tests/
├── .env
├── requirements.txt
└── README.md
```

### 🟢 Milestone 2 — Memory (Completed)
- [x] PostgreSQL set up, `database.py` connection layer
- [x] `memories` table: `id, user_id, content, category, importance, created_at, updated_at`
- [x] Short-term memory: current conversation context
- [x] Long-term memory: explicit "remember that..." facts
- [x] Project memory: grouped facts (e.g. portfolio stack)
- [x] User/server config table
- [x] In-chat command error handling (`on_command_error` with argument hints instead of silent terminal errors)
- [x] Custom `!help` command with command reference and examples
- [ ] (Later, not this milestone) embeddings/vector search for recall

---

### 📋 Command & `!help` Maintenance Rule (Mandatory across all milestones)

Whenever new Discord commands or user-facing tools are introduced:
1. **Always update `!help`**: Every new command must be documented in `!help` with its description, syntax, and an example.
2. **Always update `on_command_error`**: Handle missing arguments (`MissingRequiredArgument`) and bad input (`BadArgument`) with friendly in-chat error messages and usage syntax instead of failing silently to the terminal.

---

### 🟢 Milestone 3 — Tool Calling (Completed)
The biggest milestone — MICO stops being "just a chatbot."

- [x] Tool registry pattern (`tools/`)
- [x] Gemini function-calling wired through `agent.py`
- [x] Tool 1: `get_time()`
- [x] Tool 2: `calculator()`
- [x] Tool 3: `create_reminder()`
- [x] Tool 4: `list_reminders()`
- [x] Tool 5: `create_task()`
- [x] Tool 6: `list_tasks()`
- [x] Tool 7: `complete_task()`
- [x] Tool 8: `github_get_repositories()`
- [x] Tool 9: `github_get_commits()`
- [x] Tool 10: `github_get_issues()`
- [x] Update `!help` and `on_command_error` with any new prefix commands for tools

### 🟢 Milestone 4 — Automation Engine (Completed)
- [x] `scheduled_tasks` table: `id, user_id, task, schedule, next_run, enabled`
- [x] Background worker/scheduler loop
- [x] Reminder automation
- [x] Daily summary automation
- [x] Weekly development report
- [x] Overdue task detection
- [x] GitHub activity summary automation
- [x] Website/service monitoring scheduling foundation (feeds Milestone 6)

### 🟢 Milestone 5 — Developer Assistant (Completed)
- [x] GitHub integration: "what did I commit today", "show open issues", "stale repos", "summarize commits"
- [x] Project/task management via chat ("add X to my tasks")
- [x] GitHub webhook → Discord push notifications

### 🟢 Milestone 6 — Monitoring (Completed)
- [x] Periodic health-check job (portfolio, API, DB, deployments)
- [x] Failure detection → Discord alert
- [x] Recovery detection → Discord recovery message + downtime duration

### 🔴 Milestone 7 — PC Agent
- [ ] `open_application()`, `open_project()`, `read_file()`, `search_files()`, `check_git_status()` — safe, auto-execute
- [ ] `run_command()`, `delete_file()`, `git_push()`, `git_reset()`, `deploy()` — require confirmation
- [ ] Permission system (tool → permission level)
- [ ] Confirmation flow in Discord ("This will modify your repo. Proceed?")
- [ ] Audit log table + entries for every tool execution

### 🔴 Milestone 8 — Voice
- [ ] Speech-to-text input
- [ ] Route transcribed text through existing MICO pipeline
- [ ] Text-to-speech output

### 📊 Dashboard (after Discord version is solid)
- [ ] React + Tailwind dashboard: tasks, automations, services, memory counts, recent activity feed

### 🐳 Productionize
- [ ] Dockerfiles for backend, worker, frontend
- [ ] `docker-compose.yml` (Postgres, Redis, FastAPI, bot, worker, React)
- [ ] CI/CD basics
- [ ] Documentation + demo video

---

## Permissions & safety (applies from Milestone 7 onward, design it early)

```
run_command
   ↓
Is command allowed?
   ↓ yes
Does it require confirmation?
   ↓ yes
Ask user → Execute → Log action
```

Every tool execution should be logged:

```
TOOL EXECUTION
User: Mico
Tool: run_command
Command: npm run build
Status: SUCCESS
Time: 01:43:21
```

This is worth calling out explicitly in interviews as a security-conscious design decision.

---

## Suggested build order

| Week | Focus |
|---|---|
| 1 | Discord bot, FastAPI backend, Gemini connection, basic conversations |
| 2 | PostgreSQL, conversation history, memory, user/server config |
| 3 | Tool system, registry, function calling, first 5 tools |
| 4 | Tasks, reminders, scheduler, background jobs |
| 5 | GitHub integration, webhooks, GitHub summaries, dev commands |
| 6 | Monitoring, alerts, health checks, daily/weekly reports |
| 7+ | PC automation, permissions, confirmations, audit logs, voice |
| Final | React dashboard, Docker, documentation, demo video, resume writeup |

Timeline is a guide, not a deadline — milestones matter more than the calendar.

---

## Resume/portfolio angle

This project should read as more than "an AI chatbot." By the end it touches:

- **Backend:** Python, FastAPI, PostgreSQL, REST APIs, async programming
- **AI:** LLM APIs, function/tool calling, agent architecture, RAG, memory, prompt engineering
- **Automation:** schedulers, background workers, webhooks, monitoring, event-driven systems
- **DevOps:** Docker, CI/CD, health checks, logging
- **Integrations:** Discord API, GitHub API, external APIs
- **Frontend:** React, Tailwind, dashboards
- **Security:** permissions, confirmations, audit logging, secrets management

---

## Open questions / decisions to revisit

- [ ] Vector DB choice for long-term memory recall (pgvector vs. standalone)
- [ ] Which additional providers to support after Gemini (OpenAI first, or OpenRouter for flexibility?)
- [ ] Hosting target for "always-on" bot once past local dev (VPS? Docker on a home server?)
- [ ] Scope of PC agent — single machine only, or something remotely triggerable?
