---
name: API codegen lockstep
description: Generated zod/client defaults must be regenerated whenever openapi.yaml changes.
---
The rule: any change to defaults or schemas in `lib/api-spec/openapi.yaml` must be followed by `pnpm --filter @workspace/api-spec run codegen`, then verify the generated constants in `lib/api-zod/src/generated/api.ts` match.

**Why:** A recalibration changed spec defaults but the generated zod defaults stayed stale, so clients relying on generated defaults would send the old values. Caught only in review.

**How to apply:** Treat spec edit + codegen + grep of the generated default constants as one atomic step.
