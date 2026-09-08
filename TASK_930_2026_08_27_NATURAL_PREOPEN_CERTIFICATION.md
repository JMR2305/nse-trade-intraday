# Task #930 — Natural Pre-Open Certification

## Final verdict

**B. PHASE 5A COVERAGE FAILURE**

The natural 2026-08-27 pre-open lifecycle was observed read-only. It produced
an exact 23-symbol scheduled collection earlier in the window, but the final
natural collection before the 09:15 IST freeze boundary failed closed:

- observed at **09:14:49 IST**;
- session status: `PARTIAL_COVERAGE`;
- persisted rows: `23`, but valid rows: `0` and stale rows: `23`;
- persistence status: `COVERAGE_INCOMPLETE`;
- retry state: `RETRY_REQUIRED`;
- live snapshot count: `0`;
- freeze batch: `null`; and
- collection error: `Provider response did not cover the active pre-open universe`.

The procedure therefore stopped. No retry, replay, backfill, manual
collection, manual freeze, scan, provider refresh, settings update, portfolio
change, order, or deployment was performed.

## Observation identity

| Field | Observed value |
| --- | --- |
| Environment | `production` |
| Git commit | `06ff8327ed35b4ab298f15e7b8f7cdef8ad02191` |
| Build ID | `apexquant-06ff8327ed35` |
| Deployment ID | `0d018179-abe0-42c2-a554-dbb19d11341f` |
| Production URL | `https://nse-trade-intraday.replit.app` |
| Deployment status | Public Autoscale deployment; successful build |
| Initial scheduler session | `preopen-2026-08-27-2396e6` |

The health endpoint confirmed a production runtime. It did not expose a
separate UI build identifier, so a UI/API build-identity `MATCH` claim is not
made in this certification record.

## Natural lifecycle timeline

| IST time | Read-only observation |
| --- | --- |
| 08:44 | Scheduler active in `init`; provider health was `LIVE`, scope `ALL`; no collection rows yet. |
| 08:53 | Scheduler naturally advanced to `readiness`. |
| 09:00:24 | Natural scheduled collection observed with 23 expected, returned, normalized, persisted, and live snapshots; all coverage counters were zero for missing/duplicate/malformed/unexpected/failed. |
| 09:05 | Repeated natural collection remained exact and live; verified but not frozen. |
| 09:09 | Repeated natural collection remained exact and live; freeze still scheduled for 09:15. |
| 09:14:49 | Final observed natural collection failed closed: all 23 rows were stale, `COVERAGE_INCOMPLETE`, no valid live snapshots, and no freeze. |

## Why this is not certifiable

Certification requires the exact verified collection batch to remain fresh and
live through the freeze proof. The final observed batch did not satisfy that
requirement. A previous verified batch cannot be substituted for the failed
natural collection, and the procedure explicitly prohibits manual intervention
to convert this outcome into a pass.

## Scope and safety

All production requests made during this observation were HTTP `GET` requests
to health, pre-open, and portfolio observation endpoints. No credentials,
admin token, settings change, lifecycle trigger, broker login, broker order,
or production write was used.

See the accompanying batch/freeze, symbol-outcome, safety/portfolio, and data
authority records for the captured evidence.