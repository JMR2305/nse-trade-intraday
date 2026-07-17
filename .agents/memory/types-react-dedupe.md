---
name: Unified @types/react across workspace
description: pnpm overrides force one @types/react copy; Expo warning is accepted risk
---

Rule: keep exactly one `@types/react` / `@types/react-dom` version workspace-wide,
enforced via `overrides` in `pnpm-workspace.yaml` (^19.2.0) plus `catalog:` entries
in every package.json (including trading-mobile).

**Why:** duplicate copies (Expo pinned ~19.1.x vs catalog ^19.2.0) produced nominal
"two different types with this name exist" tsc errors in shadcn components
(button-group, calendar) that could only be silenced with local casts.

**How to apply:**
- Never pin `@types/react`/`@types/react-dom` in an individual package — use `catalog:`.
- Expo start prints "expected ~19.1.10" for these types — advisory only; runtime React
  is unchanged. Do not "fix" it by re-pinning; that reintroduces the duplication.
- Orphaned old `.pnpm` dirs may linger after install; verify via lockfile grep and
  symlink resolution, not `ls node_modules/.pnpm`.
- Metro can crash watching stale `*_tmp_*` dirs left by pnpm churn — delete them and
  restart the expo workflow.
- Dashboard prod build needs `PORT` and `BASE_PATH` env vars (vite.config.ts throws).
