---
inclusion: always
---

# Working conventions

## Process rules

- **TDD for backend changes.** Write the failing test first, see it fail, write minimal code, see it pass, then refactor. Tests live in `backend/unit_tests/`. Never claim completion without running the suite.
- **Always use `backend/venv`.** Pin exact versions in `backend/requirements.txt` when adding or upgrading libraries.
- **No deletions during simplification.** Mark unused code for later removal instead of deleting it.
- **Use LangChain/LangGraph** where an official implementation exists. Do not hand-roll.
- **Do not invent product direction.** If a decision is unclear (especially public API exposure), ask the user.
- **Backend validation is authoritative**; frontend validation is a convenience.

## Git and docs hygiene

- **Commit as you go, one logical change per commit** (a feature, a bug fix, a docs update), each with a clear message. Do not batch unrelated work. Do not push without being asked.
- **Never run migrations against the hosted Neon database (the repo-root `.env`) without explicit approval.** Verify schema changes on a scratch local database; migrate Neon only when told. The earlier repository's Supabase database is read-only reference: never write to it.
- This repository has no deployment; a push deploys nothing. Still do not push without being asked.
- Reverting a hosted migration is also a hosted change: ask first.

- `docs/` is gitignored and local-only by the owner's request. Never force-add it.
- `.kiro/` IS tracked. Keep it free of secrets, commit hashes, and calendar dates. Describe state, not history.
- Never copy `.env` values into committed files. `.env`, `*.bak`, `keys.txt`, `.claude/`, `.superpowers/`, `.playwright-mcp/`, `.design-port/` are ignored.
- Do not revert user changes in the working tree unless asked.

## Security patterns in force

- Model output is untrusted. Markdown renders without raw HTML, with unsafe link schemes blanked and remote images replaced by a label. OpenUI renders only the trimmed component library, gets no `toolProvider`, and forwards only follow-up messages and user-confirmed http(s) links. A CSP meta tag limits `img-src` to self, data: and blob:. Every renderer sits behind an error boundary and keeps the raw reply.
- OpenUI eligibility (context window >= 200,000) is enforced in the chat router and again in the runtime. The frontend only reads `capabilities.output_formats`.
- Secrets (LLM keys, connector auth, external DB URIs) are Fernet-encrypted at rest via `app/crypto.py`. API responses expose only `has_api_key`-style booleans. A blank key on retest keeps the existing ciphertext.
- Public API keys are SHA-256 hashed; plaintext is shown once.
- Sessions are server-side; logout revokes immediately over HTTP and WebSocket. The execution WebSocket checks workspace membership.
- Migrations are never automatic. Remote DBs need `ALLOW_REMOTE_MIGRATIONS=1`.
- Sandbox runs `--network none`, read-only root, tmpfs work/output, non-root, memory/CPU capped, hard timeout. The in-sandbox `ctx` is offline only. DB and HTTP access come from host-side tools and connectors.
- Data-source queries are read-only in five layers: recommended DB role, read-only transaction, sqlglot SELECT-only guard with per-agent table allowlist, row/byte/time limits, audit log. Cloud metadata hosts are blocked before dialing.
- Runs are fail-safe. Every agent graph (main and subagents) gets the tool middleware from `services/agent_resilience.py`: `ToolRetryMiddleware` retries transient errors only (timeouts, connection errors, HTTP 429/5xx) up to 2 times with 1 s then 2 s backoff; `ToolErrorMiddleware` returns any other tool exception to the model as an error message; `ToolFailureLimitMiddleware` stops calling a tool after 3 failures in one run (successes are never limited). A component that fails while the run is built (MCP connector unreachable or over the 15 s load timeout, missing web-search key, tool code that no longer parses, attached file missing from storage) is skipped, logged as one WARNING line, listed to the model in the system prompt and streamed as an `unavailable` activity card. A retried call shows as one card ("after N attempts").
- Licensing: do not copy GPL code into this project. The logging module is an independent implementation.

## Design conventions

- **LLM profiles:** test connection is the save. Pass -> `verified`; fail -> row persisted as `failed` with the error. Agent creation reads `?usable=true`. Context window is looked up from LangChain profile data on save; if missing, user supplies it. Compaction threshold defaults to 80% of the window and is editable.
- **Structured outputs:** fields are canonical (paste mode is just a converter). References are by name and renames cascade in one transaction. Names are unique per workspace, case-insensitive. Compiled schema is generated on read. Cycles are rejected at save naming the path. Delete is blocked (409) while referenced. Duplicate name -> 409. `any` omits `type`. A list cannot nest a list.
- **Tools:** built-in tools run without sandbox; custom tools need a docstring with `Args:`, type hints on all params, and a return annotation. `ctx` is a name in the execution namespace, never a parameter. Deleting a tool referenced by a skill is blocked.
- **Skills:** `@SkillName` composes skills, `/ToolName` auto-attaches tools. LLM sees a menu and loads full content via `read_skill`. Reject cycles, self-reference, and missing targets.
- **Connectors:** predefined catalog only. Model A auth (builder-owned credentials); `auth_scope` is the future path to per-user auth.
- **Files:** attached files cannot be deleted. Agent folder attachments are snapshotted into `agent_documents` with per-file exclusions. `documents.vector_ids` stays a Text placeholder until retrieval is designed (a test pins it).
- **Agents:** composition validated at run start, nothing frozen. Deleting a referenced LLM profile or connection returns 409. Agent duplication does not copy data-source attachments (known gap).
- **Conflicts** return 409, not 400.
- **Token counts:** server exact (`o200k_base`); the frontend live editor uses a word-based estimate labelled `~N tokens`.

## Telemetry and activity

- LangChain standardises `usage_metadata`: `input_token_details` (`cache_read`, `cache_creation`) and `output_token_details` (`reasoning`). It does not report time to first token, so the runtime measures it.
- A run stores its provider/model snapshot and `ttft_ms` on the execution. `token_usage` carries `cache_reported` and `reasoning_reported` so a reported 0 is distinguishable from "provider reports nothing". Never present unreported detail as zero.
- The Activity dashboard ranks and charts from `executions`; the previous period is `None` (shown as "No prior data") when it holds no runs.
- API key agent access: `all_agents` plus an `api_key_agents` join. Check access before looking the agent up, so unknown and forbidden ids answer identically. A key created through the service defaults to all agents; the API requires an explicit choice.

## Repository guard tests

`test_repo_hygiene.py` fails if a git submodule gitlink appears. `test_schema_parity.py` builds a DB from migrations and compares it column by column to the models. Keep migrations linear and in parity with models.
