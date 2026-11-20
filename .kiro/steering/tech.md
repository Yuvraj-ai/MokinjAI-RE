---
inclusion: always
---

# Tech stack and commands

## Stack

| Layer | Technology |
|---|---|
| Frontend | React 19, TypeScript, Vite, Zustand, TanStack Query, React Router 7, Tailwind CSS 3, React Flow (`@xyflow/react`, legacy canvas), CodeMirror 6 (tool editor), Axios |
| Backend | Python 3.12+, FastAPI, SQLAlchemy 2 (async, asyncpg), Pydantic v2, Alembic |
| Database | PostgreSQL only (JSONB, tz-aware timestamps). SQLite is retired. |
| LLM layer | LangChain 1.x, LangGraph, `langchain-openai/anthropic/google-genai`, `langchain-mcp-adapters`, `langchain-exa`, `langchain-tavily` |
| Data-source guard | `sqlglot` (SELECT-only SQL guard) |
| Storage | `FilesystemStorage` (default) or `S3Storage` (S3-compatible, e.g. Backblaze B2) |
| Queue / cache | Celery + Redis. Only the `/v1` rate limiter really needs Redis; the Celery path is effectively dead (nothing sets `async_execution`). |
| Auth | JWT access/refresh tokens backed by a server-side `sessions` table |

Pinned versions live in `backend/requirements.txt`. Pin exact versions when adding libraries.

## Commands

All Python runs through `backend/venv/bin/python`. Never use system Python.

```bash
# Backend tests (needs local Postgres DB whose name ends in _test)
cd backend && ./venv/bin/python -m pytest unit_tests/ -q -m "not docker"

# Run API (port 8001, not 8000)
cd backend && ./venv/bin/uvicorn app.main:app --reload --port 8001

# Migrations (remote DBs need ALLOW_REMOTE_MIGRATIONS=1)
cd backend && ./venv/bin/alembic upgrade head

# Seed admin user + Default workspace (idempotent; run after migrations)
backend/venv/bin/python backend/seed.py --generate-password

# Frontend
cd frontend && npm run dev      # dev server on 5173
cd frontend && npm run build    # tsc -b && vite build
cd frontend && npm run lint

# Everything at once
./run_mokinjay.sh
```

Generate secrets with `scripts/generate_jwt_secret.py` and `scripts/generate_fernet_key.py`.

## Configuration

Settings load from the **repo-root `.env`** by absolute path (both the app and Alembic), so the working directory never changes which DB is used. `.env.example` is the template. Key variables: `DATABASE_URL`, `TEST_DATABASE_URL`, `REDIS_URL`, `JWT_SECRET_KEY`, `LLM_ENCRYPTION_KEY`, `FRONTEND_URL`, `SANDBOX_*`, `STORAGE_S3_*`, `STORAGE_MAX_UPLOAD_BYTES`, `MS_CLIENT_*` (OneDrive), `TELEGRAM_*`, `PUBLIC_API_RATE_LIMIT_PER_MINUTE`.

`LLM_ENCRYPTION_KEY` must be a valid Fernet key. Rotating it makes every stored key undecryptable.

## Test environment

- Suite runs against local Postgres `mokinjay_test` and refuses any database name not ending in `_test` (it truncates tables).
- Docker-dependent tests are marked `docker` and are opt-in.
- `pytest.ini` sets `asyncio_mode = auto` and `testpaths = unit_tests`.
- Known standing failures: a few built-in `@tool` decorator tests in `test_builtin_tools.py`. Do not treat them as regressions you caused, but report them.
