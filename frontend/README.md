# Mokinjay frontend

React 19 + TypeScript + Vite single-page app for Mokinjay. See the repo-root `README.md` for the product and backend.

## Commands

```bash
npm install            # set OPENUI_TELEMETRY_DISABLED=1 to skip OpenUI install telemetry
npm run dev            # http://localhost:5173
npm run build          # tsc -b && vite build
npm run lint
npm test               # Vitest + Testing Library (jsdom)
npm run openui:prompt  # regenerate backend/app/services/openui_prompt.txt after changing the OpenUI library
```

## Backend connection

The dev server proxies `/api` and `/ws` to `BACKEND_URL` (default `http://localhost:8001`). To point at another backend, for example a scratch one on 8011:

```bash
BACKEND_URL=http://localhost:8011 npm run dev -- --port 5175
```

A production build reads `VITE_API_URL`. Google Drive import needs `VITE_GOOGLE_CLIENT_ID`, `VITE_GOOGLE_PICKER_API_KEY` and `VITE_GOOGLE_PROJECT_NUMBER`.

## Layout

| Path | Contents |
|---|---|
| `src/App.tsx` | Route tree. `/` and a successful login go to `/dashboard`. |
| `src/pages/` | One page per route: Activity dashboard, Activity Logs, Agents, Playground, API Keys, the resource pages, legacy Workflows. |
| `src/components/playground/` | Chat thread, activity cards (tool calls, retry attempts, unavailable components), queued-run line, Markdown and OpenUI renderers. |
| `src/components/ui/` | Shared primitives (Spinner, Badge, ...). |
| `src/api/` | Axios wrappers per resource. |
| `src/store/` | Zustand stores (auth, theme, legacy workflow and execution). |
| `src/lib/` | Filter state held in the URL, formatting, output-format rules, Google Picker. |
| `src/components/flow/` | Legacy workflow canvas (React Flow). |
