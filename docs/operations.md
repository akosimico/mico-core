# Operations

## Local development

- Backend: `venv\Scripts\python.exe -m app.main`
- Dashboard: `cd frontend; npm install; npm run dev`
- Tests: `venv\Scripts\python.exe -m pytest -q`

## Docker

Set real secrets in `.env`, add `POSTGRES_PASSWORD`, then run `docker compose up --build`. The dashboard is at `http://localhost:3000`; the backend is private to Compose and served through `/api`.

The backend serves FastAPI only. The worker service runs Discord plus the automation scheduler, preventing duplicate bot connections.

The containerized PC agent is intentionally confined to the repository bind-mounted at `/workspace`; it cannot operate on arbitrary Windows Desktop files. To test deletion, create a disposable file inside this repository.

## Verification checklist

1. `venv\Scripts\python.exe -m pytest -q`
2. `cd frontend; npm ci; npm run build`
3. `docker compose up --build`, then open `http://localhost:3000`.
4. In Discord, test a reminder, a monitor, a confirmation-required PC action, and an audio attachment.
