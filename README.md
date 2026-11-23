# Project Mokinjay — AI Agent Platform as a Service

Mokinjay is an **AI agent platform as a service**. Users build customized AI agents from a per-workspace resource library (system prompts, LLM profiles, structured outputs, tools, skills, connectors, files and data sources), then expose each agent as an API endpoint. External applications such as chatbots, CRMs and dashboards call that endpoint with an API key and get AI features without building an AI stack.

**The agent is the product.** The resource library feeds agent construction, and API exposure is the delivery mechanism. The Playground exists to test agents. The visual workflow canvas is a legacy feature, kept working but no longer developed.

**Flow: build an agent → expose it with an API key → an external app calls it.**

## What It Does

- **Resource library** (per workspace)
  - **System prompts** with exact token counts (tiktoken `o200k_base`).
  - **LLM profiles** for OpenAI, Anthropic, Gemini or any OpenAI-compatible endpoint. Testing the connection is the save, and keys are Fernet-encrypted at rest.
  - **Structured outputs**: field lists with `@Reference` composition, compiled to JSON Schema on read.
  - **Tools**: built-in tools run in the backend. User-defined Python tools run in an isolated sandbox.
  - **Skills**: Markdown packs with progressive disclosure. `@Skill` composes skills and `/Tool` attaches tools.
  - **Connectors**: a predefined MCP catalog (Slack, GitHub, Notion, PostgreSQL, …). Users enable connectors; they do not write them.
  - **Files**: a workspace file library (folders and loose files, 95 MiB uploads, OneDrive and Google Drive import). Sandboxed Python reads the files.
  - **Data sources**: read-only external databases. PostgreSQL, MySQL and MongoDB are queryable. ChromaDB connections can be created but not queried yet.
- **Agents** combine an LLM profile and its parameters, an optional structured output, optional web search (Exa, Tavily or provider-native), tools, skills, connectors, files, data sources and subagents.
- **Fail-safe runs**
  - Transient tool errors are retried.
  - Other tool errors go back to the model.
  - A component that fails to load is skipped and named to the model.
  - When sandboxes are busy, runs wait in a short per-workspace queue instead of failing.
- **Playground**: a chat for testing agents. It streams tool activity, and replies render as Markdown or OpenUI.
- **Public API**: workspace-scoped `mk_...` keys with per-key agent access, rate limits and credit limits.
- **Activity dashboard and logs**: requests, tokens, spend, latency, cache hits and every run, filterable by key, agent, source and model.
- **Workspaces and RBAC**: owner, admin, editor and viewer roles. Admin login also works with a Telegram OTP.
- **Workflow canvas (legacy)**: the original drag-and-drop pipeline editor.

## Tech Stack

| Layer | Technology |
|-------|------------|
| **Frontend** | React 19, TypeScript, Vite, Zustand, TanStack Query, React Router 7, Tailwind CSS 3, CodeMirror 6, React Flow (legacy canvas), Vitest |
| **Backend** | Python 3.12+, FastAPI, SQLAlchemy 2 (async, asyncpg), Pydantic v2, Alembic |
| **LLM layer** | LangChain 1.x and LangGraph, `langchain-openai/anthropic/google-genai`, `langchain-mcp-adapters`, `langchain-exa`, `langchain-tavily` |
| **Database** | PostgreSQL only (local, Neon or Supabase) |
| **Sandbox** | Docker container per run (no network, read-only root, non-root), subprocess fallback, or a remote sandbox daemon |
| **Storage** | Local filesystem or any S3-compatible bucket (Backblaze B2, Neon Object Storage) |
| **Queue / cache** | Redis (public API rate limiter); Celery only for the legacy canvas path |
| **Auth** | JWT access and refresh tokens backed by a server-side `sessions` table |

## Project Structure

```
mokinjay project/
├── backend/
│   ├── app/
│   │   ├── main.py          # FastAPI app, routers, /health, public /v1 sub-app, WebSocket
│   │   ├── config.py        # Settings, loaded from the repo-root .env
│   │   ├── db_url.py        # Normalises libpq/Neon URLs for asyncpg
│   │   ├── models/          # SQLAlchemy models
│   │   ├── schemas/         # Pydantic request/response models
│   │   ├── routers/         # Internal /api routes and the public /v1 routes
│   │   ├── services/        # Agent runtime and resilience, composition, sandbox, data sources,
│   │   │                    # storage, connectors, skills, structured outputs, API keys, activity
│   │   ├── tools/           # Built-in @tool registry
│   │   ├── middleware/      # Auth and RBAC dependencies
│   │   ├── engine/          # Legacy workflow DAG executor
│   │   └── workers/         # Celery tasks (legacy path)
│   ├── alembic/versions/    # Linear migration chain
│   ├── unit_tests/          # pytest suite
│   ├── deploy/              # Sandbox daemon and Render env examples
│   └── seed.py              # Admin user + Default workspace (idempotent)
├── frontend/src/
│   ├── pages/               # Dashboard (activity), Logs, Agents, Playground, API Keys, resource pages, Workflows
│   ├── components/          # playground/, agents/, activity/, files/, tools/, ui/, flow/ (legacy), ...
│   ├── api/                 # Axios wrappers per resource
│   ├── store/  lib/  hooks/  types/
├── docker/                  # Dockerfile.backend, Dockerfile.frontend, Dockerfile.sandbox
├── neon.ts, hello.ts        # Neon config (Postgres, object storage bucket, starter function)
├── render.yaml              # Render blueprint (API + static frontend)
├── deployment.md            # Record of the live deployment
├── run_mokinjay.sh          # One-command local start
└── .env.example             # Environment template
```

## Prerequisites

| Software | Version | Required For |
|----------|---------|-------------|
| Python | 3.12+ | Backend |
| Node.js | 20+ | Frontend |
| PostgreSQL | 14+ | Database (local, or a hosted URL) |
| Redis | 7+ | Public API rate limiter (fails open without it) |
| Docker | 20+ | Sandbox containers (optional; a subprocess fallback exists) |

## Setup & Run

### Quick Start

```bash
cp .env.example .env
# Set at least:
#   DATABASE_URL=<PostgreSQL URL>
#   JWT_SECRET_KEY=<python scripts/generate_jwt_secret.py>
#   LLM_ENCRYPTION_KEY=<python scripts/generate_fernet_key.py>

./run_mokinjay.sh
```

The script starts Redis, the backend on port 8001, a Celery worker and the frontend on port 5173. It does not run migrations. Run them yourself first (see below). Then open **http://localhost:5173**.

### Manual Setup

```bash
# Backend
cd backend
python3 -m venv venv
./venv/bin/pip install -r requirements.txt

# Migrations. Alembic reads DATABASE_URL from the repo-root .env and refuses a
# remote host unless ALLOW_REMOTE_MIGRATIONS=1 is set.
./venv/bin/alembic upgrade head

# Admin user and Default workspace (idempotent)
./venv/bin/python seed.py --generate-password

# API server (port 8001, not 8000)
./venv/bin/uvicorn app.main:app --reload --port 8001
```

```bash
# Frontend
cd frontend
npm install          # set OPENUI_TELEMETRY_DISABLED=1 to skip OpenUI install telemetry
npm run dev          # http://localhost:5173, proxies /api to 8001
```

### Tests

```bash
# Backend: needs a local PostgreSQL database whose name ends in _test (it truncates tables)
cd backend && ./venv/bin/python -m pytest unit_tests/ -q -m "not docker"

# Frontend
cd frontend && npm test
```

### Docker (Full Stack)

```bash
cp .env.example .env
docker-compose up --build
```

## Environment Variables

All settings load from the **repo-root `.env`** by absolute path, so the working directory never changes which database is used. `.env.example` is the template.

| Variable | Description |
|----------|-------------|
| `DATABASE_URL` | PostgreSQL URL used by the app and Alembic. Both `postgresql+asyncpg://` and libpq-style URLs (as `neon env pull` writes them) work. The built-in default is a local fallback. |
| `DATABASE_URL_UNPOOLED` | Optional direct URL that Alembic uses when `DATABASE_URL` is a pooled host (Neon). |
| `TEST_DATABASE_URL` | Database for the test suite. Its name must end in `_test`. |
| `JWT_SECRET_KEY` | JWT signing secret. Mint one with `scripts/generate_jwt_secret.py`. |
| `LLM_ENCRYPTION_KEY` | Fernet key for stored LLM keys, connector secrets and database URIs. Required to save an LLM profile. Rotating it makes every stored secret undecryptable. |
| `REDIS_URL` | Redis for the `/v1` rate limiter (default `redis://localhost:6379`). |
| `PUBLIC_API_RATE_LIMIT_PER_MINUTE` | Per-key limit on `/v1` (default 60). |
| `FRONTEND_URL` | Allowed CORS origin (default `http://localhost:5173`). |
| `SANDBOX_*` | Sandbox backend (`auto`, `docker`, `subprocess`, or the remote daemon URL and secrets), image, memory, CPU and timeouts. |
| `STORAGE_S3_*` | S3-compatible storage. When empty, files go to the local filesystem. Empty values fall back to Neon's `AWS_*` variables. |
| `STORAGE_MAX_UPLOAD_BYTES` | Upload ceiling (default 95 MiB). |
| `MS_CLIENT_*`, `VITE_GOOGLE_*` | OneDrive and Google Drive import. |
| `TELEGRAM_*` | Admin OTP login. |

## Usage

1. **Log in** at http://localhost:5173/login. You land on the Activity dashboard.
2. **Fill the resource library** with an LLM profile, then any prompts, tools, skills, connectors, files and data sources.
3. **Build an agent** under **Agents**.
4. **Test it** in **Playground**. Tool calls, retries, skipped components and a queued run all show in the chat.
5. **Expose it**: create a key under **API Keys**, choose which agents it may call, then call the agent:

```bash
curl -X POST http://localhost:8001/v1/chat \
  -H "Authorization: Bearer mk_..." -H "Content-Type: application/json" \
  -d '{"agent_id": "<agent id>", "message": "Hello"}'
```

When every sandbox in the workspace is busy, a `/v1/chat` request waits for up to 2 minutes with its connection open, so set the client read timeout above that. After that, a buffered request returns 429 `sandbox_busy` with a `Retry-After` header, and a streamed request gets a `sandbox_busy` error event. Nothing from the refused turn is stored.

6. **Watch usage** on the dashboard and in **Activity Logs**.

## API Endpoints

Internal routes are workspace-scoped and use session JWTs. `W` below stands for `/api/workspaces/{workspace_id}`.

### Auth, workspaces, users
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/auth/login`, `/api/auth/refresh` | Log in, refresh tokens |
| `POST` | `/api/auth/logout`, `/api/auth/logout-all` | Revoke this session or all sessions (HTTP and WebSocket) |
| `GET` | `/api/auth/me` | Current user |
| `POST` | `/api/auth/admin/otp/send`, `/validate` | Telegram admin OTP |
| `GET/POST` | `/api/workspaces` | List/create workspaces |
| `GET/PUT/DELETE` | `W` | Get/update/delete a workspace |
| `GET/POST`, `DELETE` | `W/members`, `W/members/{user_id}` | Workspace members |

### Resource library
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET/POST`, `GET/PUT/DELETE` | `W/prompts`, `W/prompts/{id}` | System prompts |
| `GET`, `POST` | `W/llm-profiles` (`?usable=true`), `W/llm-profiles/test` | List profiles; test-and-save |
| `POST`, `DELETE` | `W/llm-profiles/{id}/test`, `W/llm-profiles/{id}` | Retest; delete (409 while referenced) |
| `GET` | `W/llm-profiles/context-window` | Look up a model's context window |
| `GET/POST`, `GET/PUT/DELETE` | `W/structured-outputs`, `W/structured-outputs/{id}` | Structured outputs (renames cascade) |
| `POST` | `W/structured-outputs/parse-schema` | Convert pasted JSON Schema to fields |
| `GET/POST`, `GET/PUT/DELETE` | `W/tools`, `W/tools/{id}` | User-defined tools |
| `GET`, `POST` | `W/tools/builtin`, `W/tools/validate` | Built-in tools; validate tool code |
| `GET/POST`, `GET/PUT/DELETE` | `W/skills`, `W/skills/{id}` | Skills |
| `GET` | `W/skills/reference-menu` | `@`/`/` reference menu |
| `GET`, `GET/POST`, `GET/PUT/DELETE` | `W/connectors/catalog`, `W/connectors`, `W/connectors/{id}` | Connector catalog and instances |
| `POST` | `W/connectors/{id}/test` | Probe an MCP connector |
| `GET/POST`, `PATCH/DELETE` | `W/files/folders`, `W/files/folders/{id}` | Folders |
| `GET/POST/PATCH` | `W/files/documents` | List, upload (multipart), move files |
| `DELETE`, `GET` | `W/files/documents/{id}`, `.../download` | Delete (refused while attached); download |
| `POST` | `W/imports/onedrive`, `W/imports/google` | Import from cloud drives |
| `GET`, `GET`, `DELETE` | `/api/cloud-connections`, `/onedrive/authorize`, `/onedrive/callback`, `/onedrive/items`, `/{provider}` | Per-user cloud connections |
| `GET/POST`, `GET/PATCH/DELETE` | `W/external-databases`, `W/external-databases/{id}` | Data sources |
| `GET` | `W/external-databases/{id}/schema` | Data source tables and columns |
| `GET`, `PUT/DELETE` | `W/search-credentials`, `W/search-credentials/{provider}` | Exa/Tavily web search keys |

### Agents, Playground, keys, activity
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET/POST`, `GET/PUT/DELETE` | `W/agents`, `W/agents/{id}` | Agents |
| `GET` | `W/agents/options` | Pickable resources for the agent editor |
| `GET/POST`, `GET/PATCH/DELETE` | `W/playground/sessions`, `W/playground/sessions/{id}` | Playground sessions |
| `POST` | `W/playground/sessions/{id}/chat` | Send a message (SSE stream of text and activity) |
| `GET/POST`, `GET/PATCH/DELETE` | `W/api-keys`, `W/api-keys/{id}` | API keys and their agent access |
| `POST`, `GET` | `W/api-keys/{id}/rotate`, `/disable`, `/enable`, `/usage` | Key lifecycle and usage |
| `GET` | `W/activity/summary`, `W/activity/logs`, `W/activity/logs/{id}`, `W/activity/sessions` | Dashboard and logs (filters: `from`, `to`, `tz`, `api_key_id`, `agent_id`, `source`, `model`) |

### Public API (Bearer `mk_...`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/v1/chat` | Run an agent (buffered or streamed; optional `conversation_id`) |
| `GET` | `/v1/agent` | Describe an agent the key may call |
| `GET` | `/v1/health` | Health check |

### Legacy canvas and other
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET/POST`, `GET/PUT/DELETE` | `W/workflows`, `W/workflows/{id}` | Workflows |
| `POST` | `W/workflows/{id}/execute`, `/publish` | Run or publish a workflow |
| `GET`, `POST` | `W/executions`, `W/executions/{id}`, `/cancel` | Workflow executions |
| `GET` | `/health`, `/health/db` | Health checks |
| `GET` | `/v1/models` (main app) | Silent stub that stops local AI tools from probing the port |
| `WS` | `/ws/executions/{id}` | Execution updates (no publishers wired) |

## Architecture

```
Browser (React 19)                     External app
    │  /api (session JWT)                  │  /v1 (mk_... key, rate + credit limits)
    ▼                                      ▼
FastAPI (uvicorn, port 8001) ──────────────┘
    │
    ├── agent runtime (LangChain create_agent + LangGraph)
    │     ├── tool middleware: retry transient errors → errors to the model → per-run failure limit
    │     ├── built-in tools, data-source queries (read-only), MCP connectors, web search, subagents
    │     └── sandbox (per-workspace FIFO queue) ── Docker / subprocess / remote daemon
    │                                              (user tools, attached files)
    ├── SQLAlchemy (asyncpg) ── PostgreSQL
    ├── storage ── filesystem or S3-compatible bucket
    └── Redis ── /v1 rate limiter
```

## License

This project is for personal/educational use.

---

Based on Project TKAE (To Kill An Eagle).
