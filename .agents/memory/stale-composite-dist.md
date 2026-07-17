---
name: Stale composite dist declarations
description: Why trading-dashboard typecheck can show phantom missing-export / implicit-any errors from @workspace/api-client-react
---
Rule: when `tsc --noEmit` in an artifact reports a missing export from `@workspace/api-client-react` (plus cascading implicit-any errors), do NOT edit the consuming page — rebuild the referenced project first: `pnpm exec tsc -b lib/api-client-react`.

**Why:** artifact tsconfigs use TypeScript project references, so types resolve from `lib/*/dist/*.d.ts` (gitignored, per-environment), not from `src`. After the OpenAPI client is regenerated, a stale dist silently drops new hooks like `useGetSymbols`, and the `any`-typed data cascades into implicit-any errors in the page.

**How to apply:** any time the api-spec/openapi client is regenerated, also run `tsc -b` on the affected lib package (or run typechecks via `tsc -b`) before trusting red typecheck output.
