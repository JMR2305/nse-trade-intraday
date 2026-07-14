---
name: API route dev reload
description: New Express routes require an API workflow restart before testing
---
Rule: after adding routes to the API server (trading.ts), restart the `artifacts/api-server: API Server` workflow before curl-testing.

**Why:** The dev process does not reliably hot-reload route registrations; curl tests returned "Cannot GET" 404s and stale route behavior until restart, which looked like broken code.

**How to apply:** Edit routes → restart workflow → sleep ~4s → curl. If EADDRINUSE, pkill orphan tsx/vite processes first.
