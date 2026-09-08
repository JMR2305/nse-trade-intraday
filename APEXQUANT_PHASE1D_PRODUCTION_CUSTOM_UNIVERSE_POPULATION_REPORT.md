# APEXQUANT PHASE 1D — PRODUCTION CUSTOM UNIVERSE POPULATION REPORT

**Date:** 2026-08-21  
**Environment:** Production (`https://nse-trade-intraday.replit.app`)  
**Controlling report:** APEXQUANT_PHASE1B_DEV_CUSTOM_UNIVERSE_VALIDATION_REPORT.md  
**Universe option:** Option B — ₹20–₹500 moderate low-price band  
**Outcome:** ✅ Complete — 25 rows in production, all checks pass  

---

## SAFETY CONSTRAINTS — Confirmed Throughout

| Setting | Value | Changed? |
|---|---|---|
| `initial_capital` | 100000 | No |
| `active_intraday_universe` | NIFTY_50 | No |
| `auto_paper_entries` | false | No |
| `bootstrap_paper_enabled` | false | No |
| `auto_paper_exits` | true | No |
| `positions` | [] | No |
| Broker order APIs called | None | No |
| Trades created | 0 | No |
| Positions closed | 0 | No |

---

## TASK 1 — PRE-POPULATION PRODUCTION SNAPSHOT

Captured at 2026-08-21 (before calling the upsert endpoint):

```
GET /api/phase20/settings
  initial_capital         = 100000          ✅
  active_intraday_universe= NIFTY_50        ✅
  auto_paper_entries      = False           ✅
  bootstrap_paper_enabled = False           ✅
  auto_paper_exits        = True            ✅

GET /api/phase20/positions
  positions: []                             ✅

GET /api/universe/custom/status (before)
  active_count    = 0
  excluded_count  = 0
  total_candidates= 0
  last_refresh    = None

GET /api/universe/custom/symbols (before)
  total rows: 0
```

Production was clean — no prior custom universe rows existed.

---

## TASK 2 — PRODUCTION POPULATION

**Execution path:** `POST /api/universe/custom/upsert` (new permanent admin endpoint)  
**Method:** Idempotent `ON CONFLICT DO UPDATE` via `custom_universe_store.upsert_symbols()`  
**Called at:** 2026-08-21 (after publish)  

**Result:**
```json
{"success": true, "upserted": 25}
```

25 rows inserted in one atomic call: 23 active + 2 inactive audit rows.

**Code changes deployed with this publish:**
1. `POST /universe/custom/upsert` route added to `artifacts/api-server/src/routes/universe-custom.ts`
2. `universe_custom_upsert` command added to `artifacts/api-server/src/python/main.py`
3. `get_status()` price_filter display fixed in `artifacts/api-server/src/python/custom_universe_store.py` — now reads actual `min(price_min)` / `max(price_max)` from stored rows instead of hardcoded `{min:20, max:200}`

---

## TASK 3 — POST-POPULATION VERIFICATION

### 3.1 Symbol rows

```
GET /api/universe/custom/symbols (production, after population)

total_rows   : 25   ✅
active_rows  : 23   ✅
inactive_rows:  2   ✅

ACTIVE symbols (23):
  BANKBARODA   sector=BANK  ltp=247.00   ohlcv=True  ✅
  BANKINDIA    sector=BANK  ltp=142.79   ohlcv=True  ✅
  CANBK        sector=BANK  ltp=129.96   ohlcv=True  ✅
  FEDERALBNK   sector=BANK  ltp=361.00   ohlcv=True  ✅
  IDFCFIRSTB   sector=BANK  ltp=86.75    ohlcv=True  ✅
  KTKBANK      sector=BANK  ltp=328.30   ohlcv=True  ✅
  MAHABANK     sector=BANK  ltp=80.26    ohlcv=True  ✅
  PNB          sector=BANK  ltp=116.55   ohlcv=True  ✅
  UNIONBANK    sector=BANK  ltp=183.45   ohlcv=True  ✅
  COALINDIA    sector=INFRA ltp=405.20   ohlcv=True  ✅
  GAIL         sector=INFRA ltp=172.00   ohlcv=True  ✅
  HUDCO        sector=INFRA ltp=186.09   ohlcv=True  ✅
  IRCON        sector=INFRA ltp=124.72   ohlcv=True  ✅
  IRFC         sector=INFRA ltp=86.40    ohlcv=True  ✅
  MRPL         sector=INFRA ltp=176.81   ohlcv=True  ✅
  NBCC         sector=INFRA ltp=88.88    ohlcv=True  ✅
  NMDC         sector=INFRA ltp=84.61    ohlcv=True  ✅
  NTPC         sector=INFRA ltp=340.00   ohlcv=True  ✅
  PFC          sector=INFRA ltp=363.00   ohlcv=True  ✅
  RECLTD       sector=INFRA ltp=326.65   ohlcv=True  ✅
  RVNL         sector=INFRA ltp=225.30   ohlcv=True  ✅
  SAIL         sector=INFRA ltp=173.46   ohlcv=True  ✅
  WIPRO        sector=IT    ltp=180.79   ohlcv=True  ✅

INACTIVE symbols (2):
  IOB      — Excluded Phase 1B: very low absolute price (₹33); spread/slippage risk  ✅
  UCOBANK  — Excluded Phase 1B: very low absolute price (₹25.7); spread/slippage risk ✅

Forbidden symbols absent: LTIM HCLTECH RATEGAIN TANLA PERSISTENT COFORGE MPHASIS LT ✅
```

### 3.2 Status endpoint

```
GET /api/universe/custom/status (production, after population)

success               : True             ✅
active_universe       : NIFTY_50         ✅ (not switched — Phase 1E pending)
active_count          : 23               ✅
excluded_count        : 2                ✅
total_candidates      : 25               ✅
sector_counts         : {BANK:9, INFRA:13, IT:1}  ✅
price_filter          : {min:20, max:500}          ✅ (fixed — was 200 before this publish)
ohlcv_cache_hit_pct   : 100.0            ✅
last_refresh          : None             (expected — no Kite refresh run yet)
kite_ltp              : {available_symbols:0, status:FALLBACK_OR_UNAVAILABLE}
paper_trading_only    : True             ✅
no_live_broker_orders : True             ✅
```

### 3.3 Active universe unchanged

`active_intraday_universe = NIFTY_50` — confirmed in both settings and status endpoints. Universe switch to `CUSTOM_LOW_PRICE_SECTOR` is a separate Phase 1E step (task #888), not part of this phase.

### 3.4 Production settings unchanged (post-population)

```
initial_capital         = 100000   ✅
active_intraday_universe= NIFTY_50 ✅
auto_paper_entries      = False    ✅
bootstrap_paper_enabled = False    ✅
auto_paper_exits        = True     ✅
```

### 3.5 No trades or positions changed

```
positions = []   ✅
trades_created   = 0  ✅
positions_closed = 0  ✅
broker_apis_called = 0 ✅
```

---

## TASK 4 — KITE/YFINANCE MAPPING STATUS

All 25 rows have `yahoo_symbol` and `kite_symbol` set. `instrument_token = NULL` for all 23 active symbols — expected at this stage; Kite token hydration is task #889.

| Symbol | Yahoo symbol | Kite symbol | Instrument token | OHLCV | Kite LTP now | Token hydration |
|---|---|---|---|---|---|---|
| WIPRO | WIPRO.NS | WIPRO | NULL | ✅ | Pending | Required (#889) |
| IRFC | IRFC.NS | IRFC | NULL | ✅ | Pending | Required (#889) |
| NBCC | NBCC.NS | NBCC | NULL | ✅ | Pending | Required (#889) |
| NMDC | NMDC.NS | NMDC | NULL | ✅ | Pending | Required (#889) |
| IRCON | IRCON.NS | IRCON | NULL | ✅ | Pending | Required (#889) |
| HUDCO | HUDCO.NS | HUDCO | NULL | ✅ | Pending | Required (#889) |
| GAIL | GAIL.NS | GAIL | NULL | ✅ | Pending | Required (#889) |
| SAIL | SAIL.NS | SAIL | NULL | ✅ | Pending | Required (#889) |
| MRPL | MRPL.NS | MRPL | NULL | ✅ | Pending | Required (#889) |
| RVNL | RVNL.NS | RVNL | NULL | ✅ | Pending | Required (#889) |
| RECLTD | RECLTD.NS | RECLTD | NULL | ✅ | Pending | Required (#889) |
| NTPC | NTPC.NS | NTPC | NULL | ✅ | Pending | Required (#889) |
| PFC | PFC.NS | PFC | NULL | ✅ | Pending | Required (#889) |
| COALINDIA | COALINDIA.NS | COALINDIA | NULL | ✅ | Pending | Required (#889) |
| IDFCFIRSTB | IDFCFIRSTB.NS | IDFCFIRSTB | NULL | ✅ | Pending | Required (#889) |
| PNB | PNB.NS | PNB | NULL | ✅ | Pending | Required (#889) |
| CANBK | CANBK.NS | CANBK | NULL | ✅ | Pending | Required (#889) |
| BANKINDIA | BANKINDIA.NS | BANKINDIA | NULL | ✅ | Pending | Required (#889) |
| MAHABANK | MAHABANK.NS | MAHABANK | NULL | ✅ | Pending | Required (#889) |
| UNIONBANK | UNIONBANK.NS | UNIONBANK | NULL | ✅ | Pending | Required (#889) |
| BANKBARODA | BANKBARODA.NS | BANKBARODA | NULL | ✅ | Pending | Required (#889) |
| KTKBANK | KTKBANK.NS | KTKBANK | NULL | ✅ | Pending | Required (#889) |
| FEDERALBNK | FEDERALBNK.NS | FEDERALBNK | NULL | ✅ | Pending | Required (#889) |
| IOB (inactive) | IOB.NS | IOB | NULL | ✅ | — | — |
| UCOBANK (inactive) | UCOBANK.NS | UCOBANK | NULL | ✅ | — | — |

**Scanning behaviour without Kite tokens:** All 23 active symbols have `ohlcv_available = true`. Production scanning will use **yfinance as the LTP/OHLCV source** for all custom symbols until Kite token hydration is completed (task #889). This is safe and expected — the scan engine's Kite LTP overlay is additive and optional; yfinance provides full scanning capability.

---

## TASK 5 — PRICE_FILTER DISPLAY STATUS

**Status: FIXED ✅ — no longer a Phase 1E blocker.**

The `get_status()` function previously returned a hardcoded `price_filter: {min: 20.0, max: 200.0}` regardless of the actual data stored. This was corrected in the code deployed with this publish:

```python
# Before (hardcoded — wrong):
"price_filter": {"min": 20.0, "max": 200.0}

# After (derived from stored rows — correct):
price_mins = [row["price_min"] for row in rows if row.get("price_min") is not None]
price_maxs = [row["price_max"] for row in rows if row.get("price_max") is not None]
price_filter = {
    "min": min(price_mins) if price_mins else 20.0,
    "max": max(price_maxs) if price_maxs else 500.0,
}
```

Production now returns `price_filter: {min: 20, max: 500}` ✅ — matching the approved Option B band.

---

## TASK 6 — TEST RESULTS

Both suites run against the post-publish codebase:

```
$ python3 -m pytest tests/unit/test_custom_universe_store.py tests/unit/test_phase0c_safety_fixes.py -q

........................................                [100%]
40 passed, 1 warning in 1.53s
```

| Suite | Tests | Result |
|---|---|---|
| `test_custom_universe_store.py` | 18 | ✅ All pass |
| `test_phase0c_safety_fixes.py` | 22 | ✅ All pass |
| **Total** | **40** | **✅ All pass** |

Phase 0C safety suite passes unchanged after all Phase 1D code changes.

---

## TASK 7 — COMPLETE DELIVERABLE CHECKLIST

| Item | Status |
|---|---|
| 1. Pre-population production snapshot | ✅ Captured (all settings confirmed clean, 0 custom rows before) |
| 2. Exact production symbol rows inserted | ✅ 25 rows (23 active + 2 inactive), upserted=25 |
| 3. Active/inactive symbol counts | ✅ active=23, inactive=2 |
| 4. Sector counts | ✅ IT=1, INFRA=13, BANK=9 |
| 5. Membership history snapshot proof | ✅ History rows inserted with snapshot_date=2026-08-21 (append-only ON CONFLICT DO NOTHING) |
| 6. Mapping verification table | ✅ See Task 4 — all 25 symbols have yahoo_symbol + kite_symbol; token hydration pending |
| 7. Active universe still NIFTY_50 | ✅ Confirmed in both settings and status |
| 8. Capital still ₹1,00,000 | ✅ initial_capital=100000 unchanged |
| 9. Auto entries / bootstrap disabled | ✅ auto_paper_entries=False, bootstrap_paper_enabled=False |
| 10. No trades or positions changed | ✅ positions=[], no trades created, no positions closed |
| 11. No live orders | ✅ paper_trading_only=True, no_live_broker_orders=True |
| 12. Price-filter display | ✅ FIXED — production now shows {min:20, max:500} |
| 13. Phase 1E safety recommendation | See below |

---

## PHASE 1E SAFETY RECOMMENDATION

**Recommendation: SAFE to proceed to Phase 1E (universe switch) subject to the conditions below.**

| Condition | Status |
|---|---|
| Production `custom_universe_master` has exactly 23 active symbols | ✅ |
| All 23 symbols have `ohlcv_available = true` | ✅ |
| All 23 symbols within ₹20–₹500 Option B band | ✅ Verified 2026-08-21 |
| IOB and UCOBANK present as inactive audit rows | ✅ |
| Forbidden symbols absent (LTIM etc.) | ✅ |
| Production settings unchanged | ✅ |
| `active_intraday_universe` still NIFTY_50 | ✅ |
| `auto_paper_entries` still false | ✅ |
| `positions = []` before switch | ✅ |
| 40/40 tests pass | ✅ |
| `price_filter` display correct (20–500) | ✅ Fixed |
| Kite token hydration complete | ⏳ Pending (#889) — **not required for Phase 1E** |

**Kite token hydration (task #889) is NOT a blocker for Phase 1E.** The scan engine uses yfinance for all custom symbols until Kite tokens are available — this is fully functional for paper scanning. Token hydration improves LTP freshness but does not prevent scanning.

**Phase 1E action when approved:** `POST /api/universe/active` with body `{"active_intraday_universe": "CUSTOM_LOW_PRICE_SECTOR"}`. This is a settings-only write — no code deployment required. The active universe switch is instantaneous and reversible.

**HALT condition before Phase 1E:** `positions` must still be `[]` at the moment of the switch. Verify with `GET /api/phase20/positions` immediately before calling the switch endpoint.

---

## FILES CREATED OR MODIFIED IN PHASE 1D

| File | Change |
|---|---|
| `artifacts/api-server/src/routes/universe-custom.ts` | Added `POST /universe/custom/upsert` route |
| `artifacts/api-server/src/python/main.py` | Added `universe_custom_upsert` command dispatcher |
| `artifacts/api-server/src/python/custom_universe_store.py` | Fixed hardcoded `price_filter` in `get_status()` |
| `scripts/phase1d_production_upsert.sh` | One-time production curl payload (retained for audit) |
| `APEXQUANT_PHASE1D_PRODUCTION_CUSTOM_UNIVERSE_POPULATION_REPORT.md` | This report |
