---
name: Trading Dashboard BASE_PATH fix
description: artifact.toml previewPath and BASE_PATH must match the proxy-served URL prefix or Wouter routing silently fails for every route.
---

## Rule
`artifacts/trading-dashboard/.replit-artifact/artifact.toml` must set:
```toml
previewPath = "/trading-dashboard/"
[[services]]
paths = [ "/trading-dashboard/" ]
[services.env]
BASE_PATH = "/trading-dashboard/"
```

**Why:** The Replit dev proxy serves this artifact at `/trading-dashboard/` (derived from the directory name `artifacts/trading-dashboard`). Vite injects `import.meta.env.BASE_URL` from `BASE_PATH`. The app uses `WouterRouter base={import.meta.env.BASE_URL.replace(/\/$/, "")}`. If `BASE_PATH="/"`, Wouter base is `""` and it tries to match the full pathname `/trading-dashboard/experiments` against routes like `/experiments` — none match and every page shows NotFound. The symptom is: sidebar renders, content area shows 404 page, no JS console errors.

**How to apply:** Any time the trading-dashboard workflow is recreated or the artifact is re-registered, verify these three fields are set to `/trading-dashboard/`. Use `verifyAndReplaceArtifactToml` to edit — never edit artifact.toml directly. After changing, restart the workflow and confirm `BASE_PATH=/trading-dashboard/` appears in the running Vite process env (`/proc/<pid>/environ`).
