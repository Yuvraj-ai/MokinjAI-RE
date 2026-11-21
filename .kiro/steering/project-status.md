---
inclusion: auto
name: project-status
description: Current feature status, known gaps, and what is shipped vs deferred in Mokinjay. Use when planning work, judging whether something already exists, or checking known issues.
---

# Project status

## Phases

1. **Resource library** — complete.
2. **Agent runtime and sandbox** — complete.
3. **Agent creation, Playground, public API exposure** — complete.

The earlier Phase 3 design specs were voided by the owner. They are research records only, never to be built from. The shipped design came from the later agent-creation plan, Playground spec, and API-keys spec.

## Shipped

Sessions, PostgreSQL-only, structured outputs, LLM profiles, prompt token counts, repo hygiene guards, workspaces, legacy workflows and engine, executions, auth/RBAC, tools, skills, seed script, connectors, file library (replaced the original Knowledge Base), data sources (Postgres, MySQL, MongoDB find-only), Docker sandbox, agents, Playground, API keys with public `/v1`, remote sandbox host, Render deployment with object storage, and cloud file import (OneDrive OAuth per user, Google Picker) through one `import_document()` path.

## Activity dashboard, Activity Logs, key agent access

Built and verified in a browser against a scratch database: dashboard as home, empty and populated states, logs with detail drawer and sessions, shared filters held in the URL, key Activity and Logs buttons, per-key agent access (create, edit after use, enforcement on `/v1`). The schema change for this work is a migration that adds execution telemetry columns, `api_keys.all_agents`, and `api_key_agents`. It has NOT been applied to the hosted database; the deploy will apply it at boot.

Not built: Trends and Explore tabs, Guardrails, live mode, export, reasoning tokens shown unless a model reports them.

## Known gaps (open)

- Test suite is not fully green: a small number of `@tool` decorator tests in `test_builtin_tools.py` fail (reproduce when the file runs alone).
- Legacy canvas: `knowledge` node exists in UI only (not in backend `ModuleRegistry`); canvas offers Gemini but the engine Agent node supports only OpenAI and Anthropic (returns an explicit unsupported-provider error).
- Execution WebSocket manager has no publishers; `useWebSocket` is defined but never mounted. Runs are synchronous; the Celery path is unused.
- `frontend/src/types/nodes.ts` is dead code (marked, not deleted).
- Agent duplication does not copy data-source attachments.
- ChromaDB connections are creatable but not queryable.
- Vector retrieval for files is undesigned and deferred.

## Nothing is waiting on the user

No pending decisions. Do not re-propose the voided specs. Do not invent API-exposure directions; ask.

## Deployment summary

Frontend: Render static site. API: Render free web service (sleeps when idle, kept warm by a health ping). Database: Supabase Postgres via session pooler (asyncpg; the transaction pooler breaks prepared statements). Uploads: Backblaze B2 via S3 settings. Sandbox: a daemon on an InstaBox VM reusing `DockerBackend` and `kernel.py`, reached by `InstaboxBackend` over HTTP with HMAC signing. Render's start command runs migrations on boot with `ALLOW_REMOTE_MIGRATIONS=1`. No secrets belong in the repo; they live in Render, local `.env`, and the VM env file. See `deployment.md` at the repo root and `backend/deploy/`.
