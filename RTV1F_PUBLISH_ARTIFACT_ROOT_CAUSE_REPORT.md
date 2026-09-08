# RTV-1F Publish Artifact / Commit Mismatch Diagnosis

## Scope and safety boundary

This report covers only source identity, the publish-build chain, and the
non-destructive schema plan. It does **not** authorize a production publish,
token hydration, scans, portfolio writes, universe changes, safety-flag
changes, or broker activity.

## Identity evidence

| Item | Value |
|---|---|
| Original RTV-1E reference commit | `3ca36c4847c6309149aaf78a94da87b529034881` |
| Production runtime commit observed | `a75c9d6d144e8aa20ee0fcdf757f0ef53914f36e` |
| Production build ID observed | `apexquant-phase0c-20260821` |
| Production deployment ID observed | `0d018179-abe0-42c2-a554-dbb19d11341f` |
| Final approved deploy candidate | `1142f07e5a616747bbfa60722b6d681f0b03c3c0` |
| Required candidate build ID | `apexquant-1142f07e5a61` |

At the time of diagnosis, the production identity endpoint returned HTTP 200
and reported `environment=production`, but it did not meet the RTV-1E identity
gate: the commit was not the recorded reference and the build ID was retired.

## Source and commit relationship

- Current workspace branch: `rtv1-market-data-portfolio-truth`.
- The original RTV-1E reference commit is present and is an ancestor of the
  candidate branch.
- The runtime SHA `a75c9d6…` is a normal source commit on the same branch,
  created at `2026-08-23T21:27:30Z` with subject
  `Update deployment scripts and build tests for api-server`.
- It is **eight commits ahead** of `3ca36c…`, not behind it and not from a
  different branch.
- The former workspace HEAD `f3731690…` is a generated deployment checkpoint:
  it has parent `a75c9d6…`, no source-tree delta, and records deployment build
  `b727ef75-78fd-4ff2-9e87-440c070e491e`.

Classification of the production SHA: **A — later ancestor of the candidate**.
Classification of the publish checkpoint: **D — generated checkpoint commit**.
There is no evidence that Replit reused an old API artifact or selected a wrong
source branch.

## Exact source-to-runtime chain

| Stage | Identity / location | Finding |
|---|---|---|
| Workspace at successful publish start | `a75c9d6…` on `rtv1-market-data-portfolio-truth` | Correct source selected |
| Root publish hook | `scripts/deploy-build.sh` | Logged `Source commit: a75c9d6d144e` |
| Root API bundle | `artifacts/api-server/dist/index.mjs` | Built successfully |
| Image cleanup | root publish hook | Removed `.git` for image-size safety |
| Artifact API build | `artifacts/api-server/build.mjs` | Rebuilt successfully using the persisted source-commit handoff |
| Publish checkpoint | `f3731690…` | Created after the successful build; not the build input |
| Production runtime | `/api/health/details` | Correctly reported `a75c9d6…`, the build input |

The identity did **not** change from `a75c9d6…` to another commit inside the
publish pipeline. The original comparison target (`3ca36c…`) was not advanced
after the safe RTV-1D/RTV-1E follow-up fixes.

## Root cause

The hard stop had two independent causes:

1. **Approved-reference drift:** production was built from `a75c9d6…`, an
   existing same-branch commit containing the safe follow-up work, while the
   gate still compared it with the earlier `3ca36c…` reference.
2. **Build identity injection defect:** `.replit` supplied the retired shared
   value `apexquant-phase0c-20260821`. `build.mjs` accepted it and embedded it
   into the new API bundle, even though the source SHA was current.

This is **not** a stale build cache, stale `dist` directory, wrong artifact
root, or Replit checkpoint source-selection failure. The production commit
proved the source handoff worked; the stale label was injected by configuration.

## Corrected candidate

`1142f07e5a616747bbfa60722b6d681f0b03c3c0` is the
**APPROVED_DEPLOY_COMMIT** for the next controlled publish attempt.

It contains:

- removal of the stale shared build-ID setting;
- source-commit handoff across `.git` cleanup;
- commit-derived API build IDs (`apexquant-<12-hex-sha>`);
- fail-closed runtime rejection of any non-derived production build ID;
- regression tests for the legacy labels and handoff behavior; and
- the durable operator rule for verifying compiled artifact identity.

The diff from `3ca36c…` to the approved candidate contains ten commits. Every
changed file is scoped to RTV-1D/RTV-1E evidence, identity/readiness fixes,
schema safety, or the final identity correction:

| Group | Files | Why required |
|---|---|---|
| Runtime identity and readiness | `artifacts/api-server/src/lib/runtimeIdentity.ts`, `runtimeIdentity.test.ts`, `build.mjs`, `build.identity.test.ts`, `src/python/main.py`, `src/python/market_data_health.py`, `src/python/test_paper_capital_migration.py`, `src/python/tests/unit/test_market_data_health.py`, `artifacts/api-server/.replit-artifact/artifact.toml`, `.replit`, `scripts/deploy-build.sh` | Identifies the deployed source, preserves the commit through cleanup, derives a non-stale build ID, and reports current-universe readiness safely. |
| Custom-universe schema safety | `artifacts/api-server/src/python/custom_universe_store.py`, `src/python/tests/unit/test_custom_universe_store.py`, `lib/db/protected-tables.json` | Canonically declares and protects the nullable metadata fields without production mutation. |
| RTV verification evidence | `RTV1D_CONTROLLED_DEPLOYMENT_REPORT.md`, `RTV1D_NEXT_SESSION_GATE.md`, `RTV1D_PRODUCTION_MARKET_DATA_VERIFICATION.csv`, `RTV1D_PRODUCTION_POST_DEPLOY_RECONCILIATION.csv`, `RTV1D_RUNTIME_IDENTITY_AND_SAFETY.md`, `RTV1E_NONDESTRUCTIVE_SCHEMA_SAFETY_REPORT.md` | Records the read-only findings, hard stops, and zero-statement schema plan. |
| Durable engineering rules | `.agents/memory/MEMORY.md`, `.agents/memory/public-build-id-labels.md`, `.agents/memory/python-env-deploy.md`, `.agents/memory/python-managed-schema-parity.md` | Preserves the identity and Python-managed-schema safety constraints. |
| Controlled input records | `attached_assets/Pasted-RTV-1D-CONTROLLED-PRODUCTION-DEPLOYMENT-RECONCILIATION-_1787511300491.txt`, `attached_assets/Pasted-RTV-1E-PRODUCTION-IDENTITY-23-SYMBOL-READINESS-COMPLETI_1787518642653.txt`, `attached_assets/Pasted-RTV-1E-STOP-DESTRUCTIVE-PRODUCTION-MIGRATION-DO-NOT-APP_1787519431688.txt` | User-provided control records; no runtime behavior. |

The candidate contains no strategy, threshold, universe-activation, broker,
portfolio, or destructive-database change.

## Candidate build proof

An isolated production-style build was created from a Git archive of the exact
approved candidate, not from the working directory. It ran the root publish
hook, removed `.git`, then ran the artifact API build again.

| Check | Result |
|---|---|
| Source-commit handoff | `1142f07e5a616747bbfa60722b6d681f0b03c3c0` |
| Embedded API commit | exact match |
| Embedded API build ID | `apexquant-1142f07e5a61` |
| Old runtime SHA `a75c9d6…` in bundle | absent |
| Retired build ID `apexquant-phase0c-20260821` in bundle | absent |
| Runtime identity module | present |
| Canonical portfolio source | present |
| Custom-universe hydration source | present |
| Current-universe readiness source | present |
| Candidate API bundle SHA-256 | `560759b47d3187dbdd6d542da4dbae4bd8fd50a46c5af4d3a6f175cd91650e9c` |

## Test and schema results

| Check | Result |
|---|---|
| API identity tests | 8 passed |
| Portfolio parity / historical ledger / universe / Kite-session / safety tests | 109 passed |
| Python warning | 1 existing `datetime.utcnow()` deprecation warning |
| Full TypeScript check | passed |
| Isolated root production build + second artifact API build | passed |
| Development API restart and `/api/healthz` | passed |
| Regenerated publish schema diff | no diff |
| `statementsToExecute` | `[]` |
| `columnsToRemove`, `tablesToRemove`, `tablesToTruncate` | all `[]` |
| `hasStructuralDataLoss` | `false` |

The schema result preserves `instrument_token`, `instrument_exchange`,
`instrument_tradingsymbol`, `instrument_cache_date`, and
`instrument_mapping_at`.

## Production state after this diagnosis

No new production publish was performed. Consequently, production still has
the prior identity (`a75c9d6…` / `apexquant-phase0c-20260821`) and has **not**
passed the new candidate identity gate.

The next permitted action is a **user-controlled publish** of
`1142f07e5a616747bbfa60722b6d681f0b03c3c0`. Immediately afterward, and before
any hydration or other RTV-1E verification, query `/api/health/details` and
require:

- `environment = production`
- `git_commit = 1142f07e5a616747bbfa60722b6d681f0b03c3c0`
- `build_id = apexquant-1142f07e5a61`
- deployment ID present
- current runtime timestamp

Any mismatch remains a hard stop.

## Final verdict

**E. BUILD IDENTITY INJECTION DEFECT — fixed locally and proven in an isolated
production build; not yet published.**

RTV-1E token hydration, scans, portfolio checks, and all further production
verification remain blocked until the exact approved candidate is published
and passes the production identity gate.