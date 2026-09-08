# RTV-2A — Scheduler scan authority

## Origin model

Every newly persisted canonical scan now carries one of:

- `SCHEDULED` — emitted by the market-hours scheduler.
- `MANUAL` — locally/manual command initiated.
- `API_TRIGGERED` — requested through the explicit scan API action.
- `RECOVERY` — recovery workflow.
- `BACKFILL` — historical/backfill workflow.
- `UNKNOWN` — legacy/unclassified data; fail-safe, non-certifying.

The origin is persisted with canonical scan metadata and returned with the
snapshot. Cached snapshots retain their original origin rather than acquiring
the origin of a later reader.

## Authority rules

1. The scheduler calls the canonical scan engine with `SCHEDULED`.
2. `POST /api/live-data/scan/run` is explicitly stamped `API_TRIGGERED`.
3. Observation GET routes load the latest persisted snapshot only; they do not
   use the canonical scan engine.
4. `trading_data_ready` requires a fresh, complete, authenticated data set
   **and** `trigger_origin == SCHEDULED`.
5. Manual/API/recovery/backfill/unknown scans remain visible for diagnosis and
   research but cannot certify live-session readiness.

## Why this is fail-safe

A user refresh, dashboard cold start, or API consumer must never transform an
observation into a certifying market action. The origin rule ensures that the
readiness state can be traced to the natural scheduler, not inferred from a
fresh-looking scan.