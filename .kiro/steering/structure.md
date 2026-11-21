---
inclusion: always
---

# Repository structure

```
backend/
  app/
    main.py            FastAPI app, router registration, /health, /health/db, /v1/models stub, public sub-app, WS
    config.py          Pydantic Settings (repo-root .env)
    crypto.py          Fernet helpers (LLM keys, connector secrets, DB URIs)
    database.py        async engine/session
    models/            agent, api_key, chat, cloud_connection, connector, execution, external_database,
                       knowledge (file folders + documents), llm_profile, prompt, resource_usage,
                       search_credential, session, skill, structured_output, tool, user, workflow, workspace
    schemas/           Pydantic request/response models
    routers/           agents, api_keys, auth, cloud_connections, connectors, executions, external_databases,
                       files, imports, llm_profiles, playground, prompts, public, search_credentials,
                       skills, structured_outputs, tools, users, workflows, workspaces, activity
    services/          domain logic (see below)
    tools/             built-in @tool registry (builtin.py, registry.py)
    middleware/        auth + RBAC dependencies
    engine/            LEGACY workflow DAG executor + modules (agent, prompt, transform, conditional, http_request, output)
    workers/           Celery app/tasks (legacy path)
    websocket/         execution WS manager (no publishers wired)
    utils/             security helpers, errors, tokens (tiktoken)
  services (selected):
    agent_runtime / agent_composition / agent_capabilities / agent_tools / agent_validation / agent_dependencies
    structured_output (pure compiler, no DB)   skill (compiler)   tool_schema (AST extraction)
    connector_catalog / connector_runtime      web_search         model_profiles / llm_probe
    api_keys (incl. agent access) / public_limits   sessions / otp_store / telegram / seed
    activity (dashboard + logs aggregations over executions)
    sandbox/       kernel.py (stdlib-only), protocol, backends (Docker, Subprocess, Instabox), session, budget, daemon/
    data_sources/  guard (sqlglot), mongo_guard, postgres, mysql, mongo, ssrf, schema_cache
    storage/       base, filesystem, s3
    document_import / google_drive / onedrive / cloud_connections / uploads
  alembic/versions/  linear migration chain
  unit_tests/        ~90 test files (pytest)
  deploy/            sandbox daemon systemd unit and env examples, Render env example
  seed.py, create_user.py, run_mokinjay.py

frontend/src/
  App.tsx            route tree
  api/               Axios wrappers per resource (activity.ts for the dashboard and logs)
  pages/             Activity (dashboard), ActivityLogs, Agents, Playground, ApiKeys(+Detail), Dashboard(workflows), WorkflowEditor,
                     ExecutionHistory (retired, replaced by ActivityLogs, kept unrouted),
                     Prompts, StructuredOutputs, Files, DataSources, Skills, LlmProfiles, Tools, Connectors, Login
  components/        agents/ (config dialog, pickers), flow/ (legacy canvas), execution/, auth/, layout/, dashboard/
  store/             Zustand (auth, workflow, execution, theme)
  lib/               activityFilters (URL-held filter state), chartColors, format, agentAccess
  hooks/ types/

docker/              Dockerfile.backend, Dockerfile.frontend, Dockerfile.sandbox
scripts/             generate_fernet_key.py, generate_jwt_secret.py
render.yaml          Render blueprint (API web service + static frontend)
deployment.md        deployment record (committed)
docs/                LOCAL-ONLY, gitignored (plans, specs, ADRs, manuals). Never push.
memory.md            local-only agent memory file (gitignored)
```

## Frontend routes

`/login`, `/dashboard`, `/logs`, `/agents`, `/playground`, `/keys`, `/keys/:keyId`, `/workflows`, `/workflows/:id/edit`, `/prompts`, `/structured-outputs`, `/files`, `/data-sources`, `/skills`, `/llms`, `/tools`, `/connectors`. Root and a successful login go to `/dashboard`. `/executions` redirects to `/logs`.

## API shape

- Internal REST under `/api/...`, workspace-scoped: `/api/workspaces/{workspace_id}/<resource>`.
- Activity: `/activity/summary`, `/activity/logs`, `/activity/logs/{id}`, `/activity/sessions`, all taking the same filters (`from`, `to`, `tz`, `api_key_id`, `agent_id`, `source`, `model`).
- Public API served under `/v1` (separate sub-app; Bearer `mk_...` key).
- Backend port is **8001**. A silent `/v1/models` stub on the main app exists to stop local AI tools probing it.

## Overloaded term

`"agent"` also names a legacy canvas node type in `engine/modules/agent.py`. It is unrelated to a workspace `Agent`. It is marked, not renamed.
