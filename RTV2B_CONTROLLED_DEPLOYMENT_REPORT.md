# RTV-2B — Controlled Production Deployment Report

**Date:** 2026-08-24  
**Verdict:** **SAFETY REGRESSION — deployment stopped**

## Goal

RTV-2B was intended to publish only the verified RTV-2A persistence and
observation-safety fixes, then prove the exact deployed identity before the
next natural NSE session.

## Task 1 — Source candidate

- Branch: `rtv1-market-data-portfolio-truth`
- Candidate HEAD:
  `253c687bb76d29bb09638bb0bddf00ff5e84fee7`
- Candidate build ID:
  `apexquant-253c687bb76d2`
- Working tree: clean
- Current production commit before this attempt:
  `393747a8102ee3fc8adaa36d60b6ed8db18bc4b8`

The candidate contains the RTV-2A runtime changes for durable Phase 5A state,
immutable collection batches, lifecycle ordering, session scoping, read-only
GET behavior, scan origin metadata, and readiness certification. The related
tests and evidence documents are also present.

## Blocking source-scope finding

The tracked runtime settings file contains this unrelated and prohibited
change:

```diff
- "auto_paper_entries": false,
- "auto_paper_entries_confirmed_at": null,
+ "auto_paper_entries": true,
+ "auto_paper_entries_confirmed_at": "2026-08-24T03:33:38Z",
```

This violates the RTV-2B rules:

- automatic entries must remain disabled;
- no trading configuration changes are allowed during this deployment.

The `active_intraday_universe` value in that file is unchanged by this
candidate. The production health response currently reports
`CUSTOM_LOW_PRICE_SECTOR` with 23 symbols, but that does not override the
source-scope failure.

## Decision

**STOP.** No `APPROVED_DEPLOY_COMMIT` was authorized and no publish action was
initiated. The candidate must not be promoted until the settings regression is
resolved and the pre-deploy gate is rerun.

## Safety actions taken

- No deployment publish was triggered.
- No pre-open job was triggered.
- No scan was triggered.
- No universe membership was changed.
- No strategy or threshold was changed.
- No portfolio was reset.
- No historical ledger was modified.
- No automatic-entry or bootstrap activation was performed.
- No broker order was placed.

## Validation available before the stop

The verified RTV-2A source checks passed before this deployment attempt:

- Phase 5A/scan/readiness Python suite: 156 passed
- Scan route regression suite: 10 passed
- Push notification regression suite: 25 passed
- API build: passed
- API TypeScript check: passed
- Workspace typecheck: passed
- Python syntax compilation: passed
- Diff whitespace check: passed

These results do not override the source-scope safety failure.

## Production status observed

Before the stop, the production identity endpoint returned HTTP 200 and
reported:

- environment: `production`
- git commit: `393747a8102ee3fc8adaa36d60b6ed8db18bc4b8`
- build ID: `apexquant-393747a8102e`
- deployment ID: present
- deployment URL: `https://nse-trade-intraday.replit.app`

The current production identity does not match the blocked candidate, as
expected because no publish was performed.

## Required resolution

Resolve the `auto_paper_entries` source regression without changing the
approved universe, thresholds, capital, ledger, or broker settings. Then rerun
Tasks 1–5 of the attached RTV-2B procedure before requesting publication.
