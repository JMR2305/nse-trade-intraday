# Task #944 — Runtime Identity and Safety

## Published production identity

Read-only `GET /api/health/details` verification returned:

| Field | Value |
|---|---|
| Environment | `production` |
| Git commit | `06ff8327ed35b4ab298f15e7b8f7cdef8ad02191` |
| Build ID | `apexquant-06ff8327ed35` |
| Deployment ID | `0d018179-abe0-42c2-a554-dbb19d11341f` |
| Runtime timestamp | `2026-08-26T09:58:02.346Z` |
| Instance | `nse-trade-intraday.replit.app` |

The corresponding source identities are:

```text
CURRENT_WORKSPACE_HEAD = 74b55d239efc21e697f49ca9fc7fe86b3dc4dc93
TASK_941_MERGE_COMMIT   = c38c2b3091f63c0862e07908a5a995df56d253c0
TASK_942_MERGE_COMMIT   = ba3727403d45c8bdec6a25eebaf3236da859727c
CURRENT_VISIBLE_GIT_COMMIT = 74b55d239efc21e697f49ca9fc7fe86b3dc4dc93
DEPLOYED_SOURCE_COMMIT = 06ff8327ed35b4ab298f15e7b8f7cdef8ad02191
DEPLOYED_BUILD_ID      = apexquant-06ff8327ed35
```

`git merge-base --is-ancestor` proves both Task #941 and Task #942 merge
commits are ancestors of the deployed source commit. The deployed commit is a
documentation-only descendant of the runtime merge; it includes the required
runtime files.

## Production schema

Read-only production SQL confirms:

- `preopen_collection_outcomes` exists;
- all required columns exist, including the non-null
  `session_id`, `collection_batch_id`, `symbol`, `outcome_status`, and
  `reason_code` fields;
- the nullable provider/normalization/evidence columns exist;
- `preopen_collection_outcomes_pkey` uniquely indexes
  `(session_id, collection_batch_id, symbol)`; and
- `idx_preopen_outcomes_session_batch` indexes
  `(session_id, collection_batch_id)`.

The table currently contains zero rows. No historical outcome backfill was
performed or required.

## Read-only production safety baseline

| Safety/control | Result |
|---|---|
| Active universe | `CUSTOM_LOW_PRICE_SECTOR` |
| Active universe count | 23 |
| Mapping/token coverage | 23/23 |
| Automatic paper entries | `false` |
| Entry confirmation | `null` |
| Bootstrap | `false` |
| Automatic paper exits | `true` |
| Effective mode | `PAPER_TRADING_RESEARCH_ONLY` |
| Portfolio source | `phase20_ledger` |
| Portfolio status | `DISABLED` |
| Controlled execution | disabled |
| Effective `execution_allowed` | `false` |
| Live broker orders | disabled (`live_order_placement_enabled=false`) |
| Open positions | 0 |
| `EXIT_PENDING` | 0 |
| Portfolio health | `HEALTHY` |
| Unresolved portfolio discrepancies | 0 |

The effective execution gate is closed by the combination of automatic entries
disabled, portfolio status `DISABLED`, paper-only mode, and live order
placement disabled. No setting was changed during verification.

The canonical portfolio snapshot reports:

```text
position_source      = phase20_ledger
open_position_count  = 0
equity_complete      = true
paper_mode           = true
status               = DISABLED
```

The production paper ledger contains six `BUY` rows and six matching `SELL`
rows: six historical closed paper trades are preserved.

## Kite and market-data baseline

Dedicated read-only live Kite checks returned:

```text
connected       = true
token_status    = VALID
token_expired   = false
is_mock         = false
provider        = Zerodha Kite Connect
live_order_placement_enabled = false
```

The direct read-only LTP request returned all 23 configured symbols from
Zerodha Kite. At the verification timestamp the market was open and the
health payload reported:

```text
current_quote_freshness = LIVE
current_quote_provider  = ZERODHA_KITE
trading_data_ready      = true
symbols_on_kite         = 23
symbols_fallback       = 0
symbols_stale           = 0
symbols_synthetic       = 0
symbols_unavailable     = 0
missing_symbols         = []
token_coverage_pct      = 100
```

## Historical safety baseline

The August 26 session remains:

```text
session_id                = preopen-2026-08-26-ccb21a
status                    = PARTIAL_COVERAGE
expected_count            = 23
persisted_count           = 3
verified_collection_batch = null
frozen_collection_batch   = null
```

It remains incomplete, uncertified historical evidence.

## Verdict

**PASS — published runtime identity, schema support, safety controls, Kite
connectivity, and portfolio/ledger baseline verified read-only.**