---
name: API server route restart
description: New Express routes added to artifacts/api-server require a workflow restart before they're servable
---

Adding a new route (e.g. `router.get("/learning-summary", ...)`) to `artifacts/api-server/src/routes/*.ts`
does not take effect live even though the dev workflow is "running" — the route returns
`Cannot GET /...` until the `artifacts/api-server: API Server` workflow is restarted.

**Why:** The api-server's dev process doesn't appear to hot-reload new route registrations the way
Vite hot-reloads frontend pages/components.

**How to apply:** After adding or changing Express route registrations in api-server, restart the
`artifacts/api-server: API Server` workflow before curling/testing the new endpoint, or the test will
falsely appear to fail.
