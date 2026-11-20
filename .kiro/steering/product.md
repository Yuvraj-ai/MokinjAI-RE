---
inclusion: always
---

# Product: Mokinjay

Mokinjay is an **AI agent platform as a service**. Users build customized AI agents from a per-workspace resource library, then expose each agent as an API endpoint. External apps (chatbots, CRMs, dashboards) call that endpoint with an API key and get AI features without building an AI stack.

**The agent is the product.** The resource library feeds agent construction. API exposure is the delivery mechanism. The Playground chat exists to test agents. The visual workflow canvas is **legacy**, kept working but not the product.

Flow: build agent -> expose endpoint -> external app calls it with an API key.

## Resource library (per workspace)

| Resource | Notes |
|---|---|
| System prompts | CRUD; token count computed on read with tiktoken `o200k_base`. |
| LLM profiles | OpenAI, Anthropic, Gemini, Custom (base URL + model). Test-as-save; Fernet-encrypted keys. |
| Structured outputs | Field lists, `@Ref` composition, JSON Schema compiled on read. |
| Tools | Built-in (`@tool`, no sandbox) and user-defined Python (sandboxed). |
| Skills | Markdown packs, `@Skill` and `/Tool` references, progressive disclosure. |
| Connectors | Predefined MCP catalog (Slack, GitHub, Notion, PostgreSQL...). Users enable, never author. |
| Files | Workspace file library (folders + loose files, 95 MiB uploads). Read by sandboxed Python. |
| Data sources | External DB connections. Postgres, MySQL and MongoDB are queryable (read-only). ChromaDB is creatable but not queryable. |

## Agents

An agent composes: LLM profile (+ params: temperature, max tokens, reasoning, stream, top_p, seed, stop), optional structured output, optional web search (Exa, Tavily, or provider-native), a source prompt (provenance only), tools, skills, connectors, files, data sources, and subagents (cycles rejected). Composition is validated at run start. Nothing is frozen into a compiled column.

## Public API

Workspace-scoped keys (`mk_...`, SHA-256 hashed, shown once). Endpoints: `POST /v1/chat`, `GET /v1/agent`, `GET /v1/health`. The agent is named per request; the key's workspace is the boundary. Server-side chat sessions are stamped by key. Per-key rate limit (default 60/min, fails open if Redis is down) and credit limits (daily/weekly/monthly reset) are enforced before any model call.

## Workspaces and roles

Multi-user workspaces with owner/admin/editor/viewer roles. Admin login also supports Telegram OTP.

## Deferred (do not build unprompted)

Per-end-user identity (connector "Model B"), publishable/browser keys, webhooks/SDKs, per-agent public docs pages, workspace analytics, a dedicated structured-output invoke endpoint, vector retrieval for files.
