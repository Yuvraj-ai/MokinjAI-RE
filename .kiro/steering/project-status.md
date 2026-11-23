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

## Playground output formats (Markdown and OpenUI)

Built and verified in a browser against a scratch database with a stub OpenAI-compatible model. Replies render as GitHub-flavoured Markdown for every model. OpenUI (thesysdev OpenUI Lang, React renderer) is offered when the agent's LLM profile has a stored context window of at least 200,000 tokens (model-card value for known models, user-typed for custom ones). The choice is per turn, held in page state; the reply's format is stored on `chat_messages.output_format` (NULL reads as Markdown). That column comes from a migration NOT applied to the hosted database. The public `/v1` API is unchanged and always Markdown.

Not verified against real providers yet: how reliably each model writes valid OpenUI.

## Fail-safe runs

A failing tool or component does not end a run: transient tool errors are retried, other tool errors go back to the model, and components that cannot load are skipped and reported to the model and the activity stream. Sandbox contention queues per workspace (2 minutes, 20 waiting) and then fails with `sandbox_busy` (429 on buffered `/v1/chat`). A connector tool call that exceeds the 60 s ceiling is reported to the model and is not retried. Details are in conventions and product.

## Known gaps (open)

- A busy 429 leaves the user message in the conversation, so a client retry repeats the user turn.
- The Playground's waiting line can linger briefly after Stop or an early error until the session refetches.
- The sandbox queue is in-process; with several API workers each has its own queue.
- The public `/v1` buffered response concatenates text from every model step, including narration before a tool call; the persisted message keeps only the final step.
- The OpenUI packages declare `zustand@^4` as a peer; a package.json override runs them on the app's zustand 5. Re-check after upgrading them.
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

Neon: a Neon project (`mokinjay-sg`, region AWS Singapore `aws-ap-southeast-1`, branch `main`; `neon.ts`: Postgres, an `assets` Object Storage bucket, a starter `hello` function) is wired for local use, in the same region as the Render backend. The Render deployment is unchanged and still uses Supabase.
