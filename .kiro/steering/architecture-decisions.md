---
inclusion: auto
name: architecture-decisions
description: Condensed architecture decision records for Mokinjay (ADR-000 to ADR-028) covering LLM profiles, encryption, structured outputs, sandbox, connectors, skills, sessions, data sources, and API keys. Use before changing any of those designs.
---

# Architecture decisions (condensed)

The full records live in the local-only `docs/reference/decisions.md`. Each decision lists what would change it; consult it before reversing one.

| ADR | Decision |
|---|---|
| 000 | The product is hosted AI agents exposed as API endpoints. |
| 001 | LLM context window is looked up at save and stored; runtime reads the row only. |
| 002 | Test connection is the save gate (`verified` / `failed`). |
| 003 | LLM/MCP keys use Fernet from `LLM_ENCRYPTION_KEY`; never returned in responses. |
| 004 | Context-window lookup calls `init_chat_model` with a dummy key and reads static profile data (no network). |
| 005 | Superuser queries use `scalars().first()`. |
| 006 | Superseded by 022 (SQLite dev is gone). |
| 007 | Three phases: library, runtime, agent creation. |
| 008 | Structured outputs compose by `@Reference`, not inline nesting. |
| 009 | References resolve when an agent is built or run, not at definition edit. Editing warns about dependents. |
| 010 | Sandbox is a per-agent, lazy, per-run Docker capability (also a subprocess fallback). |
| 011 | Object storage if configured, else filesystem; same API. |
| 012 | External DBs are URI connection records. |
| 013 | Connectors (predefined MCP) and Tools are separate sections. |
| 014 | Number intentionally skipped. |
| 015 | Tools are built-in or user-defined. |
| 016 | An agent sees only tools assigned to it. |
| 017 | No code deletions during simplification; mark instead. |
| 018 | Structured-output fields are canonical; paste mode converts. |
| 019 | References keyed by name; renames cascade. |
| 020 | Connector auth Model A now, path to per-user Model B via `auth_scope`. |
| 021 | Skills use progressive disclosure with `@` and `/` references. |
| 022 | PostgreSQL is the only database. |
| 023 | Development runs against a hosted PostgreSQL; `.env` is the single source; accounts reproducible via seed. |
| 024 | Server-side sessions, revoking logout, background pruning. |
| 025 | Backend port 8001 plus a silent `/v1/models` stub. |
| 026 | CodeMirror 6 for the Python tool editor. |
| 027 | Data sources execute server-side, read-only, with a per-agent table allowlist. |
| 028 | Public API keys are workspace-scoped; the agent is named per request. Spend is tracked via `executions.api_key_id`. A browser-embeddable publishable key would be a distinct credential, never the agent key. |

## Notes worth remembering

- Sandbox interface: `execute_python(code, timeout)` and `execute_tool(name, args)`, returning stdout/stderr/error and generated files. Container sizes scale by largest attached file, with swap pinned to memory and a per-workspace in-flight budget.
- The sandbox host moved remote without changing the protocol: the daemon reuses the Docker backend and kernel over the existing socket; the app talks HTTP.
- Public routes differ by auth: internal `/api` uses session JWTs, `/v1` uses API keys.
- Rate limiter fails open on Redis outage by design.
