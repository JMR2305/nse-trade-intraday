# Task #944 — Post-Publish Production Runtime Verification

## Verification boundary

This was a read-only verification of the already-published deployment. No
republish or second deployment was performed. No Phase 5A/5B/5C trigger,
manual scan, retry, replay, backfill, universe refresh, setting change,
portfolio mutation, ledger mutation, or broker order was invoked.

## 1. Current production identity

Read-only `GET /api/health/details` returned:

| Field | Value |
|---|---|
| `environment` | `production` |
| `git_commit` | `06ff8327ed35b4ab298f15e7b8f7cdef8ad02191` |
| `build_id` | `apexquant-06ff8327ed35` |
| `deployment_id` | `0d018179-abe0-42c2-a554-dbb19d11341f` |
| `runtime_timestamp` | `2026-08-26T09:58:02.346Z` |

The workspace and merge identities are:

| Identity | SHA |
|---|---|
| `CURRENT_WORKSPACE_HEAD` | `74b55d239efc21e697f49ca9fc7fe86b3dc4dc93` |
| `TASK_941_MERGE_COMMIT` | `c38c2b3091f63c0862e07908a5a995df56d253c0` |
| `TASK_942_MERGE_COMMIT` | `ba3727403d45c8bdec6a25eebaf3236da859727c` |
| `CURRENT_VISIBLE_GIT_COMMIT` | `74b55d239efc21e697f49ca9fc7fe86b3dc4dc93` |
| `DEPLOYED_SOURCE_COMMIT` | `06ff8327ed35b4ab298f15e7b8f7cdef8ad02191` |
| `DEPLOYED_BUILD_ID` | `apexquant-06ff8327ed35` |

**Result: PASS.** Both Task #941 and Task #942 merge commits are ancestors of
the deployed source commit. The deployed commit is a documentation-only
descendant of the runtime merge; the required runtime files are present.

## 2. Task #941 production runtime/source verification

| Required invariant | Result and evidence |
|---|---|
| Custom-universe NSE provider scope is `ALL` | **PASS** — `nse_preopen_provider.py::_preopen_key()` forces `ALL`; `fetch_collection_evidence()` and `_fetch_raw()` use that scope. |
| Hard-coded `NIFTY` cannot override custom-universe scope | **PASS** — the custom-universe scope is selected internally by `_preopen_key()` rather than accepting a restricted external key. |
| Provider cache is isolated by query scope | **PASS** — `nse_preopen_provider.py::_fetch_raw()` includes the requested scope in its cache identity and validates it before reuse. |
| `preopen_collection_outcomes` support exists | **PASS** — `preopen_db.py::_ensure_schema()`, `_insert_collection_outcome()`, `persist_collection()`, and `get_collection_outcomes()` provide durable support; production schema presence is confirmed below. |
| Every expected symbol receives one immutable outcome | **PASS** — `preopen_engine.py::_resolve_collection_symbols()`, `_finalise_collection_outcomes()`, `_coverage_with_outcomes()`, and `preopen_db.py::_canonical_outcomes()` operate on the exact expected set and primary key `(session_id, collection_batch_id, symbol)`. |
| Missing provider rows do not create fabricated snapshots | **PASS** — `preopen_engine.py::_failure_outcomes()` and `_fetch_provider_collection()` record outcomes for missing/failed symbols; only normalized provider rows enter snapshot persistence. |
| NSE timestamps use Asia/Kolkata | **PASS** — `nse_preopen_provider.py::_nse_last_update_age_seconds()` parses the NSE wall-clock timestamp in the Asia/Kolkata timezone. |
| Missing/malformed/future/`>=300s` timestamps fail stale | **PASS** — `_nse_last_update_age_seconds()` and `NSEOfficialProvider._normalize()` fail closed for each of those cases; boundary tests cover the behavior. |
| `MATCH` requires exact expected/live/persisted parity | **PASS** — `preopen_engine.py::_collection_batch_status()` and the persistence coverage contract require exact set and batch agreement before certification. |
| Freeze independently validates exact batch/outcomes/liveness | **PASS** — `preopen_scheduler.py::_phase_09_15_freeze()` re-reads the exact verified batch and validates complete outcomes, liveness, and explicit live evidence before freezing. |

The deployed API also returns the new certification shape: the August 26
session is `PARTIAL_COVERAGE`, while `collection_batch.certified=false`,
`certification_status=NOT_VERIFIED`, and both verified/frozen batch IDs are
null.

## 3. Task #942 production UI verification

**Result: PASS.**

A read-only browser load of:

```text
/trading-dashboard/preopen-intelligence
```

showed:

```text
Session Phase       = PARTIAL_COVERAGE
Collection Batch    = Not certified
Certified           = false
```

The page displayed the certification warning and stated that no durable
verified collection batch was recorded. The browser check observed no page
errors or console errors. No action control was clicked.

The page therefore distinguishes session state from certified collection state;
the incomplete August 26 session does not appear certified.

## 4. Historical August 26 session

Read-only production SQL and API verification confirm:

```text
SESSION_ID                 = preopen-2026-08-26-ccb21a
STATUS                     = PARTIAL_COVERAGE
EXPECTED_COUNT             = 23
PERSISTED_COUNT            = 3
VERIFIED_COLLECTION_BATCH = null
FROZEN_COLLECTION_BATCH    = null
AUTHORITATIVE_COLLECTED_3  = [COALINDIA, NTPC, WIPRO]
```

The persisted collection batch is:

```text
collection-3a70e162d5f146a3b8514974ee6a780e
```

The outcome table currently has zero rows because it was introduced after this
failed collection. The immutable session coverage and persisted snapshot rows
remain authoritative. `GAIL` is in the missing-symbol set, not the collected
three-symbol set. No historical data was changed.

**Result: PASS — historical evidence preserved and discrepancy reconciled.**

## 5. Schema presence

**Result: PASS.**

Production contains `preopen_collection_outcomes` with the required columns:

```text
session_id
collection_batch_id
symbol
outcome_status
reason_code
provider_symbol
provider_response_present
normalization_result
eligibility_status
snapshot_id
provider_scope
provider_raw_count
created_at
```

Required indexes confirmed:

```text
preopen_collection_outcomes_pkey
  UNIQUE (session_id, collection_batch_id, symbol)

idx_preopen_outcomes_session_batch
  (session_id, collection_batch_id)
```

No migration or direct DDL was run during this verification.

## 6. Safety baseline

| Control | Production result |
|---|---|
| Active universe | `CUSTOM_LOW_PRICE_SECTOR` |
| Active count | 23 |
| Mapping/token coverage | 23/23 |
| Automatic paper entries | `false` |
| Entry confirmation | `null` |
| Bootstrap | `false` |
| Automatic exits | `true` |
| Controlled execution | disabled |
| Effective `execution_allowed` | `false` |
| Live broker orders | disabled |
| Mode | `PAPER_TRADING_RESEARCH_ONLY` |
| Portfolio source | `phase20_ledger` |
| Open positions | 0 |
| `EXIT_PENDING` | 0 |
| Historical closed trades | 6 preserved |
| Portfolio health | `HEALTHY` |
| Unresolved discrepancies | 0 |

The portfolio snapshot reports `position_source=phase20_ledger`,
`open_position_count=0`, `paper_mode=true`, and `status=DISABLED`. The paper
trade table contains six `BUY` and six matching `SELL` rows.

**Result: PASS.**

## 7. Kite and market-data verification

Dedicated read-only Kite status/diagnostics returned:

```text
connected                    = true
token_status                 = VALID
token_expired                = false
is_mock                      = false
provider                     = Zerodha Kite Connect
live_order_placement_enabled = false
```

The market was open during the verification. A direct read-only
`GET /api/kite/ltp` request returned all 23 configured symbols from live Kite.
The health payload reported:

```text
current_quote_freshness = LIVE
current_quote_provider  = ZERODHA_KITE
trading_data_ready      = true
symbols_on_kite         = 23
symbols_fallback        = 0
symbols_stale           = 0
symbols_synthetic       = 0
symbols_unavailable     = 0
missing_symbols         = []
token_coverage_pct      = 100
```

**Result: PASS.**

## 8. No-mutation proof

The verification actions issued only:

- GET requests to health, pre-open status, portfolio, Phase 20, Kite, and
  coverage endpoints;
- read-only SQL `SELECT` queries against production; and
- a browser navigation with no action-control clicks.

No POST, PUT, PATCH, or DELETE request was issued. Therefore, the verification
itself caused:

```text
manual scans       = 0
Phase 5A triggers   = 0
retries             = 0
replays             = 0
broker orders       = 0
settings mutations  = 0
portfolio mutations = 0
ledger mutations    = 0
```

Scheduled background scans visible in service logs are independent scheduler
activity and were not invoked by this verification.

## 9. Final decision

**TASK #944 PASS — CURRENT PRODUCTION READY FOR NEXT NATURAL PRE-OPEN**

Task #941 and Task #942 are definitely present in the currently deployed
production runtime. Do not republish. The next new Phase 5A evidence must come
from the naturally scheduled NSE pre-open session, and the August 26 historical
session must remain untouched.