---
name: API base path routing
description: Frontend API URLs must target root /api, not the SPA's BASE_URL prefix
---

The api-server artifact is mounted at root paths=["/api"], while the trading-dashboard SPA is proxied at /trading-dashboard/. Building API URLs from `import.meta.env.BASE_URL` (e.g. `${BASE_URL}api`) produces /trading-dashboard/api, which the proxy routes to the Vite SPA fallback and returns HTML — causing "Unexpected end of JSON input" and HTML downloads instead of CSV/JSON.

**Why:** The pnpm-workspace proxy routes by path prefix; the API is a separate artifact at /api, not nested under the SPA base path.

**How to apply:** All dashboard API calls must use the shared helper in `src/lib/api.ts` (API_BASE="/api", apiJson()). apiJson reads text first and detects empty/HTML/invalid-JSON responses — never call `res.json()` blindly. Regression tests live in `src/lib/api.test.ts` (run vitest with PORT and BASE_PATH env vars set, since vite.config.ts requires them).
