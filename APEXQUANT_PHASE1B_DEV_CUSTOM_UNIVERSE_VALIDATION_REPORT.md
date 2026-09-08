# APEXQUANT PHASE 1B — DEV CUSTOM UNIVERSE VALIDATION REPORT

**Date:** 2026-08-21  
**Environment:** Dev only (localhost:8080 / dev PostgreSQL)  
**Universe option:** Option B — ₹20–₹500 moderate low-price band  
**Outcome:** ✅ All tasks complete — ready for Phase 1D operator approval  
**Controlling plan:** APEXQUANT_PHASE1_REVISED_CAPITAL_UNIVERSE_EXECUTION_PLAN.md  

---

## SAFETY CONSTRAINTS — Confirmed Throughout

| Setting | Dev value | Production value |
|---|---|---|
| `auto_paper_entries` | false | false |
| `bootstrap_paper_enabled` | false | false |
| `auto_paper_exits` | true | true |
| `active_intraday_universe` | NIFTY_50 | NIFTY_50 |
| `initial_capital` | 100000 | 100000 |
| Production `custom_universe_master` | **NOT TOUCHED** | Empty (unchanged) |
| Broker order APIs called | No | No |

---

## 1. FINAL APPROVED DEV-ONLY SYMBOL LIST

**Price band:** ₹20–₹500 (Option B moderate)  
**Total active symbols:** 23 (1 IT + 13 Infra + 9 Bank)  
**Total rows in store:** 25 (23 active + 2 excluded with documented reasons)

| # | Symbol | Company | Sector | LTP (2026-08-21) | Price band | Shares @ ₹25K |
|---|---|---|---|---|---|---|
| 1 | WIPRO | Wipro Ltd | IT | ₹180.79 | ✅ In band | 138 |
| 2 | IRFC | Indian Railway Finance Corp | INFRA | ₹86.40 | ✅ In band | 289 |
| 3 | NBCC | NBCC India Ltd | INFRA | ₹88.88 | ✅ In band | 281 |
| 4 | NMDC | NMDC Ltd | INFRA | ₹84.61 | ✅ In band | 295 |
| 5 | IRCON | IRCON International Ltd | INFRA | ₹124.72 | ✅ In band | 200 |
| 6 | HUDCO | HUDCO | INFRA | ₹186.09 | ✅ In band | 134 |
| 7 | GAIL | GAIL India Ltd | INFRA | ₹172.00 | ✅ In band | 145 |
| 8 | SAIL | Steel Authority of India | INFRA | ₹173.46 | ✅ In band | 144 |
| 9 | MRPL | Mangalore Refinery (MRPL) | INFRA | ₹176.81 | ✅ In band | 141 |
| 10 | RVNL | Rail Vikas Nigam Ltd | INFRA | ₹225.30 | ✅ In band | 110 |
| 11 | RECLTD | REC Ltd | INFRA | ₹326.65 | ✅ In band | 76 |
| 12 | NTPC | NTPC Ltd | INFRA | ₹340.00 | ✅ In band | 73 |
| 13 | PFC | Power Finance Corporation | INFRA | ₹363.00 | ✅ In band | 68 |
| 14 | COALINDIA | Coal India Ltd | INFRA | ₹405.20 | ✅ In band | 61 |
| 15 | IDFCFIRSTB | IDFC First Bank | BANK | ₹86.75 | ✅ In band | 288 |
| 16 | PNB | Punjab National Bank | BANK | ₹116.55 | ✅ In band | 214 |
| 17 | CANBK | Canara Bank | BANK | ₹129.96 | ✅ In band | 192 |
| 18 | BANKINDIA | Bank of India | BANK | ₹142.79 | ✅ In band | 175 |
| 19 | MAHABANK | Bank of Maharashtra | BANK | ₹80.26 | ✅ In band | 311 |
| 20 | UNIONBANK | Union Bank of India | BANK | ₹183.45 | ✅ In band | 136 |
| 21 | BANKBARODA | Bank of Baroda | BANK | ₹247.00 | ✅ In band | 101 |
| 22 | KTKBANK | Karnataka Bank | BANK | ₹328.30 | ✅ In band | 76 |
| 23 | FEDERALBNK | Federal Bank | BANK | ₹361.00 | ✅ In band | 69 |

---

## 2. MAPPING VERIFICATION TABLE

All 23 symbols verified via yfinance on 2026-08-21.

| Symbol | Sector | Yahoo symbol | Kite symbol | Instrument token | LTP | Volume (daily) | yfinance | OHLCV | Kite LTP | Include/Exclude | Notes |
|---|---|---|---|---|---|---|---|---|---|---|---|
| WIPRO | IT | WIPRO.NS | WIPRO | NULL | ₹180.79 | 4,635,652 | ✅ OK | ✅ | Pending | Include | NIFTY_50 symbol — mapping pre-verified |
| IRFC | INFRA | IRFC.NS | IRFC | NULL | ₹86.40 | 4,765,907 | ✅ OK | ✅ | Pending | Include | yfinance verified |
| NBCC | INFRA | NBCC.NS | NBCC | NULL | ₹88.88 | 5,369,124 | ✅ OK | ✅ | Pending | Include | yfinance verified |
| NMDC | INFRA | NMDC.NS | NMDC | NULL | ₹84.61 | 18,865,805 | ✅ OK | ✅ | Pending | Include | Very high volume |
| IRCON | INFRA | IRCON.NS | IRCON | NULL | ₹124.72 | 909,714 | ✅ OK | ✅ | Pending | Include | Lower volume — acceptable for intraday |
| HUDCO | INFRA | HUDCO.NS | HUDCO | NULL | ₹186.09 | 875,044 | ✅ OK | ✅ | Pending | Include | Lower volume — acceptable |
| GAIL | INFRA | GAIL.NS | GAIL | NULL | ₹172.00 | 6,509,016 | ✅ OK | ✅ | Pending | Include | yfinance verified |
| SAIL | INFRA | SAIL.NS | SAIL | NULL | ₹173.46 | 14,683,544 | ✅ OK | ✅ | Pending | Include | Very high volume |
| MRPL | INFRA | MRPL.NS | MRPL | NULL | ₹176.81 | 6,535,381 | ✅ OK | ✅ | Pending | Include | yfinance verified |
| RVNL | INFRA | RVNL.NS | RVNL | NULL | ₹225.30 | 2,616,366 | ✅ OK | ✅ | Pending | Include | Option B band |
| RECLTD | INFRA | RECLTD.NS | RECLTD | NULL | ₹326.65 | 4,327,156 | ✅ OK | ✅ | Pending | Include | Option B band |
| NTPC | INFRA | NTPC.NS | NTPC | NULL | ₹340.00 | 6,532,622 | ✅ OK | ✅ | Pending | Include | Option B band |
| PFC | INFRA | PFC.NS | PFC | NULL | ₹363.00 | 9,592,260 | ✅ OK | ✅ | Pending | Include | Option B band |
| COALINDIA | INFRA | COALINDIA.NS | COALINDIA | NULL | ₹405.20 | 10,327,223 | ✅ OK | ✅ | Pending | Include | Option B band |
| IDFCFIRSTB | BANK | IDFCFIRSTB.NS | IDFCFIRSTB | NULL | ₹86.75 | 12,588,998 | ✅ OK | ✅ | Pending | Include | Very high volume |
| PNB | BANK | PNB.NS | PNB | NULL | ₹116.55 | 14,047,780 | ✅ OK | ✅ | Pending | Include | Very high volume |
| CANBK | BANK | CANBK.NS | CANBK | NULL | ₹129.96 | 8,124,111 | ✅ OK | ✅ | Pending | Include | yfinance verified |
| BANKINDIA | BANK | BANKINDIA.NS | BANKINDIA | NULL | ₹142.79 | 5,333,928 | ✅ OK | ✅ | Pending | Include | yfinance verified |
| MAHABANK | BANK | MAHABANK.NS | MAHABANK | NULL | ₹80.26 | 7,790,968 | ✅ OK | ✅ | Pending | Include | yfinance verified |
| UNIONBANK | BANK | UNIONBANK.NS | UNIONBANK | NULL | ₹183.45 | 6,916,849 | ✅ OK | ✅ | Pending | Include | yfinance verified |
| BANKBARODA | BANK | BANKBARODA.NS | BANKBARODA | NULL | ₹247.00 | 7,914,129 | ✅ OK | ✅ | Pending | Include | Option B band |
| KTKBANK | BANK | KTKBANK.NS | KTKBANK | NULL | ₹328.30 | 3,431,080 | ✅ OK | ✅ | Pending | Include | Option B band |
| FEDERALBNK | BANK | FEDERALBNK.NS | FEDERALBNK | NULL | ₹361.00 | 4,397,811 | ✅ OK | ✅ | Pending | Include | Option B band |

**Instrument token status:** NULL for all non-NIFTY_50 symbols — `instrument_token` is not required for yfinance-based scanning. It becomes available when a Kite session is active and `POST /universe/custom/refresh` is called (which hydrates tokens from the Kite instrument cache). The `ohlcv_available = true` flag on all symbols confirms yfinance data is available for scanning now.

---

## 3. INCLUDED / EXCLUDED SYMBOLS AND REASONS

### Included (23 symbols)
All 23 are `is_active = true`, all have `ohlcv_available = true`, all verified via yfinance 2026-08-21. Reasons stored in `reason_included` column.

### Excluded (2 symbols — stored as inactive rows for audit)

| Symbol | LTP | Reason | Shares @ ₹25K cap |
|---|---|---|---|
| IOB | ₹33.0 | Very low absolute price; spread/slippage risk at 757 shares per ₹25K cap | 757 |
| UCOBANK | ₹25.7 | Very low absolute price; spread/slippage risk at 972 shares per ₹25K cap | 972 |

Excluded symbols are stored as `is_active = false` rows with documented `reason_excluded`. They do not appear in `get_active_symbols()` and would not enter any scan. They are retained for audit purposes.

### Not included (per operator instruction)
LTIM, HCLTECH, RATEGAIN, TANLA, PERSISTENT, COFORGE, MPHASIS, LT — outside ₹20–₹500 band or explicitly excluded by operator.

---

## 4. TEST FILE CREATED

**File:** `artifacts/api-server/src/python/tests/unit/test_custom_universe_store.py`  
**Tests written:** 18 unit tests across 7 test classes  
**DB layer:** Fully mocked — no writes to the real database during test runs  

| Class | Tests | Coverage |
|---|---|---|
| `TestUpsertIdempotency` | 3 | Second upsert succeeds; empty list; blank symbol skipped |
| `TestActiveOnlyFiltering` | 4 | Active-only return; empty result; all-symbols includes inactive; SQL has is_active filter |
| `TestMembershipHistoryAppendOnly` | 2 | History table is written; ON CONFLICT DO NOTHING present |
| `TestCustomModeUsesOnlyCustomSymbols` | 2 | Custom mode → custom symbols; metadata keys match active list |
| `TestEmptyUniverseBlocksScanSafely` | 3 | Empty → no NIFTY_50 fallback; DB unavailable → empty not exception; get_status returns zero counts |
| `TestInvalidMappingReported` | 3 | ohlcv_available=False row returned not dropped; hit rate reflects unavailable; NULL instrument_token accepted |
| `TestPhase0CSafetySuiteUnaffected` | 1 | Phase 0C 22-test suite gate |

---

## 5. TEST RESULTS

```
============================= test session starts ==============================
platform linux -- Python 3.12.12, pytest-9.1.1
collected 18 items

tests/unit/test_custom_universe_store.py::TestUpsertIdempotency::test_empty_row_list_returns_success_zero PASSED
tests/unit/test_custom_universe_store.py::TestUpsertIdempotency::test_second_upsert_succeeds_and_returns_upserted_count PASSED
tests/unit/test_custom_universe_store.py::TestUpsertIdempotency::test_upsert_with_missing_symbol_key_skips_silently PASSED
tests/unit/test_custom_universe_store.py::TestActiveOnlyFiltering::test_get_active_symbols_empty_when_all_inactive PASSED
tests/unit/test_custom_universe_store.py::TestActiveOnlyFiltering::test_get_active_symbols_returns_only_active_rows PASSED
tests/unit/test_custom_universe_store.py::TestActiveOnlyFiltering::test_get_all_symbols_returns_all_including_inactive PASSED
tests/unit/test_custom_universe_store.py::TestActiveOnlyFiltering::test_sql_execute_includes_is_active_filter PASSED
tests/unit/test_custom_universe_store.py::TestMembershipHistoryAppendOnly::test_history_insert_uses_on_conflict_do_nothing PASSED
tests/unit/test_custom_universe_store.py::TestMembershipHistoryAppendOnly::test_upsert_writes_to_history_table PASSED
tests/unit/test_custom_universe_store.py::TestCustomModeUsesOnlyCustomSymbols::test_get_active_symbol_metadata_keys_match_get_active_symbols PASSED
tests/unit/test_custom_universe_store.py::TestCustomModeUsesOnlyCustomSymbols::test_scan_universe_resolution_uses_custom_symbols_not_nifty50 PASSED
tests/unit/test_custom_universe_store.py::TestEmptyUniverseBlocksScanSafely::test_db_unavailable_returns_empty_not_exception PASSED
tests/unit/test_custom_universe_store.py::TestEmptyUniverseBlocksScanSafely::test_empty_custom_universe_gives_empty_scan_universe_not_nifty50 PASSED
tests/unit/test_custom_universe_store.py::TestEmptyUniverseBlocksScanSafely::test_get_status_returns_zero_counts_when_table_empty PASSED
tests/unit/test_custom_universe_store.py::TestInvalidMappingReported::test_get_status_ohlcv_hit_rate_reflects_unavailable PASSED
tests/unit/test_custom_universe_store.py::TestInvalidMappingReported::test_symbol_with_ohlcv_unavailable_is_returned_not_dropped PASSED
tests/unit/test_custom_universe_store.py::TestInvalidMappingReported::test_upsert_accepts_row_with_null_instrument_token PASSED
tests/unit/test_custom_universe_store.py::TestPhase0CSafetySuiteUnaffected::test_phase0c_safety_suite_passes PASSED

============================== 18 passed in 2.47s ==============================
```

**Phase 0C gate result:** PASSED — all 22 Phase 0C safety tests pass unchanged.

---

## 6. DEV DB POPULATION EVIDENCE

**Script:** `artifacts/api-server/src/python/scripts/populate_dev_custom_universe.py`  
**Executed at:** 2026-08-21T13:50:21Z  
**Target:** Dev PostgreSQL only (localhost)  
**Method:** `custom_universe_store.upsert_symbols()` — idempotent ON CONFLICT DO UPDATE  

**Population result:**
```json
{
  "success": true,
  "upserted": 25,
  "active_symbols": 23,
  "excluded_symbols": 2,
  "total_rows": 25,
  "error": null
}
```

**History table:** `custom_universe_membership_history` received one snapshot row per symbol at `snapshot_at = 2026-08-21T13:50:21Z`, `snapshot_date = 2026-08-21`. Confirmed via `get_historical_universe_resolution()` → `status = HISTORICAL_SNAPSHOT`, 23 active symbols.

---

## 7. CUSTOM UNIVERSE SYMBOLS / STATUS RESPONSES

### `GET /api/universe/custom/status` (dev)

```json
{
  "success": true,
  "active_universe": "NIFTY_50",
  "custom_universe_name": "CUSTOM_LOW_PRICE_SECTOR",
  "active_count": 23,
  "excluded_count": 2,
  "total_candidates": 25,
  "sector_counts": {
    "BANK": 9,
    "INFRA": 13,
    "IT": 1
  },
  "last_refresh": "2026-08-21T13:50:21.653856+00:00",
  "ohlcv_cache_hit_rate_pct": 100.0,
  "kite_ltp": {
    "available_symbols": 0,
    "status": "FALLBACK_OR_UNAVAILABLE"
  },
  "paper_trading_only": true,
  "no_live_broker_orders": true
}
```

> `active_universe = NIFTY_50` is correct — the active universe has NOT been switched (Phase 1E not yet approved). `custom_universe_name = CUSTOM_LOW_PRICE_SECTOR` shows the prepared custom universe is registered and ready.

> `kite_ltp.status = FALLBACK_OR_UNAVAILABLE` is expected — Kite sessions are not active in dev. All 23 symbols will use yfinance as LTP source, which is confirmed available (`ohlcv_available = true` on all rows).

> `price_filter: {min:20, max:200}` in the status endpoint is a display label from `get_status()` hardcoded to the original narrow-band description. The actual `price_min/price_max` stored per-symbol in the DB is `20/500` (Option B band) as populated.

### `GET /api/universe/custom/symbols` (dev)

Returns 25 rows: 23 with `is_active: true`, 2 (IOB, UCOBANK) with `is_active: false`. All rows include `reason_included`/`reason_excluded`, `last_ltp`, `avg_volume_20d`, `ohlcv_available`, and timestamps. Full response confirmed via API.

---

## 8. SCAN RESOLUTION PROOF

Tested by calling the universe resolution logic directly in the dev Python environment:

```
active_count : 23
symbols      : ['BANKBARODA', 'BANKINDIA', 'CANBK', 'COALINDIA', 'FEDERALBNK',
                'GAIL', 'HUDCO', 'IDFCFIRSTB', 'IRCON', 'IRFC', 'KTKBANK',
                'MAHABANK', 'MRPL', 'NBCC', 'NMDC', 'NTPC', 'PFC', 'PNB',
                'RECLTD', 'RVNL', 'SAIL', 'UNIONBANK', 'WIPRO']
sector_counts: {"BANK": 9, "INFRA": 13, "IT": 1}

scan resolution proof
resolved universe size : 23
mode                   : CUSTOM_LOW_PRICE_SECTOR (simulated)
NIFTY_50 leak          : none

empty universe safety
empty custom → scan universe: [] (safe — no NIFTY_50 fallback)
```

**Key proofs:**
1. With CUSTOM_LOW_PRICE_SECTOR active, `get_active_symbols()` returns exactly 23 symbols — none from NIFTY_50 that aren't in the custom list
2. Empty custom universe (`get_active_symbols()` returns `[]`) → scan universe = `[]`. The `live_scan_engine.py` and `market_scanner.py` code does NOT fall back to NIFTY_50 when the custom store is empty (confirmed by code review at `live_scan_engine.py:737-743`)
3. Historical snapshot recorded for today (2026-08-21) — backtests after this date can resolve the custom universe accurately

---

## 9. CONFIRMATION: PRODUCTION WAS NOT CHANGED

| Production resource | Status |
|---|---|
| `custom_universe_master` on production | **NOT TOUCHED — still empty** |
| `custom_universe_membership_history` on production | **NOT TOUCHED** |
| `phase20_settings.active_intraday_universe` on production | NIFTY_50 (unchanged) |
| `phase20_settings.initial_capital` on production | 100000 (Phase 1C value, unchanged) |
| `auto_paper_entries` on production | false (unchanged) |
| `bootstrap_paper_enabled` on production | false (unchanged) |

The population script contains an explicit production-URL guard that would exit with an error if run against the production `DATABASE_URL`.

---

## 10. CONFIRMATION: AUTO ENTRIES AND BOOTSTRAP REMAIN DISABLED

| Setting | Dev | Production |
|---|---|---|
| `auto_paper_entries` | false ✅ | false ✅ |
| `bootstrap_paper_enabled` | false ✅ | false ✅ |
| `auto_paper_exits` | true ✅ | true ✅ |
| Dev positions created | 0 ✅ | — |

---

## 11. CONFIRMATION: NO LIVE ORDERS

- The population script only calls `upsert_symbols()` — a DB write, not a broker API
- `paper_trading_only: true` and `no_live_broker_orders: true` confirmed in both status and population output
- Dev `positions = []` confirmed after population
- No broker APIs were called at any point during Phase 1B

---

## 12. RECOMMENDATION: SAFE FOR PHASE 1D PRODUCTION POPULATION

**Recommendation: SAFE to proceed to Phase 1D** with the following conditions met:

| Condition | Status |
|---|---|
| All 23 symbols have verified yfinance data | ✅ `ohlcv_available = true` on all |
| All 23 symbols within ₹20–₹500 Option B band | ✅ Confirmed with live prices |
| IOB and UCOBANK excluded per operator instruction | ✅ Stored as inactive rows |
| LTIM, HCLTECH, RATEGAIN, TANLA excluded per operator instruction | ✅ Not present |
| Upsert is idempotent (safe to re-run) | ✅ ON CONFLICT DO UPDATE |
| History snapshot recorded | ✅ 2026-08-21 snapshot exists |
| Empty universe safety confirmed (no NIFTY_50 fallback) | ✅ Proven |
| 18/18 unit tests pass | ✅ |
| Phase 0C 22-test safety gate passes | ✅ |
| No production changes made in Phase 1B | ✅ |

**Phase 1D action when approved:** Run `populate_dev_custom_universe.py` against the production `DATABASE_URL` (after removing the production-URL guard), or call `upsert_symbols()` directly via the production Python environment. This is a DB write only — no code deployment required.

**Phase 1E (universe switch) remains a separate operator-approved step** (`PUT /api/phase20/settings` with `active_intraday_universe = CUSTOM_LOW_PRICE_SECTOR`). This is not part of Phase 1D.

---

## FILES CREATED IN PHASE 1B

| File | Purpose |
|---|---|
| `artifacts/api-server/src/python/tests/unit/test_custom_universe_store.py` | 18-test unit suite for custom universe store |
| `artifacts/api-server/src/python/scripts/populate_dev_custom_universe.py` | Idempotent population script for the 23-symbol approved list |
| `APEXQUANT_PHASE1B_DEV_CUSTOM_UNIVERSE_VALIDATION_REPORT.md` | This report |

No Python modules, routes, or configuration files were modified.
