---
inclusion: auto
name: docs-map
description: Map of the local-only docs/ tree (plans, specs, ADRs, manuals, runbooks) and how to use it. Use when you need deeper design detail than the steering files hold.
---

# Docs map

`docs/` is gitignored and local-only. It may be absent on a fresh clone. Treat it as read-only reference, and never quote commit identifiers or dates from it into tracked files.

| Path | Contents |
|---|---|
| `docs/reference/decisions.md` | Full ADRs with context and "what would change it". |
| `docs/reference/project-status.md` | Feature table, completed work, known gaps. |
| `docs/reference/backend-issues.md` | Resolved backend defects (OTP bugs, token expiry) and open-issue pointer. |
| `docs/superpowers/ROADMAP.md` | Build tracker: built / tested / verified per feature, cross-document issues. |
| `docs/superpowers/specs/` | Design specs per feature. Phase 3 early specs are VOID. |
| `docs/superpowers/plans/` | Implementation plans per feature. |
| `docs/directives/agent-creation.md` | Owner's original agent-creation directions and detailed spec (two-pane config window: parameters left, configuration right). |
| `docs/guides/backend-manual/` | 18-chapter backend manual (stack, config, models, auth, routers, sandbox, engine, migrations, recipes, verification, watch-outs). |
| `docs/guides/frontend-manual/` | Frontend manual (stack, Vite proxy, styling, API layer, stores, hooks, pages, canvas, UI flows). |
| `docs/guides/agent-workflow-manual.md` | Safe operating procedure for agents in this repo. |
| `docs/guides/deployment-architecture.md`, `deploy-render.md`, `admin-otp-setup.md` | Hosting decisions, Render runbook, OTP setup. |
| `docs/plans/agent-builder-plan/` | Historical preliminary design. Not current architecture. |

## Tracked deployment files

`deployment.md`, `render.yaml`, `backend/deploy/`, and `docker/` are tracked. `deployment.md`, `render.yaml` and `backend/deploy/` describe the earlier repository's deployment; this repository is not deployed.

## Guidance

- Prefer the code when it disagrees with a doc, then flag the drift.
- The ROADMAP header reports the latest suite state; rerun the suite rather than trusting it.
