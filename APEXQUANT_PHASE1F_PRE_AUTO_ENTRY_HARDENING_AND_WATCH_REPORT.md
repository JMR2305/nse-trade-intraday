# APEXQUANT PHASE 1F — PRE-AUTO-ENTRY HARDENING AND MARKET SESSION WATCH REPORT

**Date:** 2026-08-21  
**Environment:** Production (`https://nse-trade-intraday.replit.app`) + Dev  
**Controlling report:** APEXQUANT_PHASE1E_ACTIVE_UNIVERSE_SWITCH_REPORT.md  
**Goal:** Complete all remaining prerequisites before auto entries can be re-enabled  
**Outcome:** ✅ Route security implemented and tested | ⚠️ Kite tokens pending live session | ⏳ First session watch Monday 2026-08-25  

---

## SAFETY CONSTRAINTS — Confirmed Throughout

| Setting | Value | Changed? |
|---|---|---|
| `initial_capital` | 100000 | No |
| `active_intraday_universe` | CUSTOM_LOW_PRICE_SECTOR | No |
| `auto_paper_entries` | false | No |
| `bootstrap_paper_enabled` | false | No |
| `auto_paper_exits` | true | No |
| `positions` | [] | No |
| Broker order APIs called | 0 | No |
| Trades created | 0 | No |

---

## TASK 1 — ADMIN ROUTE SECURITY IMPLEMENTATION

### What changed

`artifacts/api-server/src/routes/universe-custom.ts` — `POST /universe/custom/upsert` now requires a valid `x-admin-token` header matching the `UNIVERSE_ADMIN_TOKEN` environment secret.

**Before (unprotected):**
```typescript
router.post("/universe/custom/upsert", wrap(async (req, res) => {
  const rows = req.body?.rows;
  if (!Array.isArray(rows) || rows.length === 0) { ... }
  res.json(await runPython(["universe_custom_upsert", ...]));
}));
```

**After (fail-closed token gate):**
```typescript
router.post("/universe/custom/upsert", wrap(async (req, res) => {
  const expectedToken = process.env.UNIVERSE_ADMIN_TOKEN;
  const providedToken = req.headers["x-admin-token"];
  if (!expectedToken || providedToken !== expectedToken) {
    res.status(403).json({ success: false, error: "Forbidden: valid x-admin-token header required" });
    return;
  }
  const rows = req.body?.rows;
  if (!Array.isArray(rows) || rows.length === 0) { ... }
  res.json(await runPython(["universe_custom_upsert", ...]));
}));
```

**Fail-closed guarantee:** If `UNIVERSE_ADMIN_TOKEN` is not set in the environment, `!expectedToken` is truthy and the route returns 403 for ALL requests — including ones that provide a header. An unconfigured environment is never open.

### Dev server verification

Immediately after restarting the dev server with the new code:

```bash
curl -X POST http://localhost:PORT/api/universe/custom/upsert \
  -H "Content-Type: application/json" \
  -d '{"rows":[{"symbol":"TEST","is_active":true}]}'

→ {"success":false,"error":"Forbidden: valid x-admin-token header required"}   ✅
```

### Production status

**Action required:** The security gate code must be deployed to production. Until then, the production server still runs the old unprotected route. The `UNIVERSE_ADMIN_TOKEN` secret must be set in production secrets **before** deploying so the gate is active from the moment the new build starts.

**Deployment is safe:** All other APIs continue to work. Only `POST /universe/custom/upsert` behaviour changes — it goes from open to token-gated. All other `GET` routes are unaffected.

---

## TASK 2 — ADMIN TOKEN TEST RESULTS

**Test file:** `artifacts/api-server/src/routes/universe-admin-security.test.ts` (7 tests)

| # | Test | Result |
|---|---|---|
| 1 | `POST /upsert` without `x-admin-token` → 403 | ✅ Pass |
| 2 | `POST /upsert` with wrong token → 403 | ✅ Pass |
| 3 | `POST /upsert` with correct token → 200, Python dispatched | ✅ Pass |
| 4 | `GET /universe/custom/status` remains public, no 403 | ✅ Pass |
| 5 | `GET /universe/custom/symbols` remains public, no 403 | ✅ Pass |
| 6 | Only `universe_custom_upsert` command dispatched — no broker commands | ✅ Pass |
| 7 | Fail-closed: 403 for any header value when `UNIVERSE_ADMIN_TOKEN` env var unset | ✅ Pass |

**Full test run (all suites):**
```
Test Files  2 failed | 11 passed (13)
Tests       2 failed | 123 passed (125)
```

The 2 failing tests are **pre-existing** and unrelated to Phase 1F:
- `scan-cache-invalidation.test.ts` — asserts `api_build_id = 'development'`, receives `apexquant-phase0c-20260821` (pre-existing since Phase 0C build ID was set)
- `pushNotifier.test.ts` — pre-existing mock timing issue (unrelated)

All 7 new security tests pass. All 40 Python unit tests (custom universe + Phase 0C safety) pass.

---

## TASK 3 — KITE TOKEN HYDRATION

### Hydration status

Kite token hydration was attempted against the local `kite_instruments_cache.json`. Result:

| Field | Value |
|---|---|
| Cache date | 2026-08-09 |
| Total instruments in cache | 1 |
| Custom universe symbols found | 0 / 23 |

The local Kite instrument cache is stale (2026-08-09, 12 days old) and contains only 1 record — this is not a valid instrument list. Kite token hydration for the 23 custom symbols is **not possible from the local cache**.

### Per-symbol hydration table

| Symbol | Yahoo symbol | Kite symbol | Token before | Token after | Hydration status | Failure reason |
|---|---|---|---|---|---|---|
| WIPRO | WIPRO.NS | WIPRO | NULL | NULL | ⏳ Pending | Stale cache — no NSE instrument data |
| IRFC | IRFC.NS | IRFC | NULL | NULL | ⏳ Pending | Stale cache — no NSE instrument data |
| NBCC | NBCC.NS | NBCC | NULL | NULL | ⏳ Pending | Stale cache — no NSE instrument data |
| NMDC | NMDC.NS | NMDC | NULL | NULL | ⏳ Pending | Stale cache — no NSE instrument data |
| IRCON | IRCON.NS | IRCON | NULL | NULL | ⏳ Pending | Stale cache — no NSE instrument data |
| HUDCO | HUDCO.NS | HUDCO | NULL | NULL | ⏳ Pending | Stale cache — no NSE instrument data |
| GAIL | GAIL.NS | GAIL | NULL | NULL | ⏳ Pending | Stale cache — no NSE instrument data |
| SAIL | SAIL.NS | SAIL | NULL | NULL | ⏳ Pending | Stale cache — no NSE instrument data |
| MRPL | MRPL.NS | MRPL | NULL | NULL | ⏳ Pending | Stale cache — no NSE instrument data |
| RVNL | RVNL.NS | RVNL | NULL | NULL | ⏳ Pending | Stale cache — no NSE instrument data |
| RECLTD | RECLTD.NS | RECLTD | NULL | NULL | ⏳ Pending | Stale cache — no NSE instrument data |
| NTPC | NTPC.NS | NTPC | NULL | NULL | ⏳ Pending | Stale cache — no NSE instrument data |
| PFC | PFC.NS | PFC | NULL | NULL | ⏳ Pending | Stale cache — no NSE instrument data |
| COALINDIA | COALINDIA.NS | COALINDIA | NULL | NULL | ⏳ Pending | Stale cache — no NSE instrument data |
| IDFCFIRSTB | IDFCFIRSTB.NS | IDFCFIRSTB | NULL | NULL | ⏳ Pending | Stale cache — no NSE instrument data |
| PNB | PNB.NS | PNB | NULL | NULL | ⏳ Pending | Stale cache — no NSE instrument data |
| CANBK | CANBK.NS | CANBK | NULL | NULL | ⏳ Pending | Stale cache — no NSE instrument data |
| BANKINDIA | BANKINDIA.NS | BANKINDIA | NULL | NULL | ⏳ Pending | Stale cache — no NSE instrument data |
| MAHABANK | MAHABANK.NS | MAHABANK | NULL | NULL | ⏳ Pending | Stale cache — no NSE instrument data |
| UNIONBANK | UNIONBANK.NS | UNIONBANK | NULL | NULL | ⏳ Pending | Stale cache — no NSE instrument data |
| BANKBARODA | BANKBARODA.NS | BANKBARODA | NULL | NULL | ⏳ Pending | Stale cache — no NSE instrument data |
| KTKBANK | KTKBANK.NS | KTKBANK | NULL | NULL | ⏳ Pending | Stale cache — no NSE instrument data |
| FEDERALBNK | FEDERALBNK.NS | FEDERALBNK | NULL | NULL | ⏳ Pending | Stale cache — no NSE instrument data |

**To complete hydration:** Call `POST /api/universe/custom/refresh` during an authenticated Kite session. This downloads the current NSE instrument list from the Zerodha API, matches symbols, and writes `instrument_token` values to `custom_universe_master`. Scanner will then use Kite LTP overlay for these symbols.

**This is NOT a blocker** for the first session watch or auto entries — yfinance provides complete OHLCV for all 23 symbols (`ohlcv_available = true`, `ohlcv_cache_hit_rate_pct = 100`). Kite token hydration improves real-time LTP freshness only.

---

## TASK 4 — FIRST MARKET SESSION WATCH PLAN

### Context

The Phase 1E switch happened at **~17:58 IST on 2026-08-21 (Friday, after market close)**. The last full scanner run used `universe_mode: NIFTY_50` (scan_id `76e307f291e7`, snapshot_ts `2026-08-21T10:02:20Z`). The scanner reads `active_intraday_universe` from settings at scan time, so the **first scan using `CUSTOM_LOW_PRICE_SECTOR` will be the next market session: Monday 2026-08-25 at 09:15 IST**.

### Provider readiness (confirmed today)

```
GET /api/live-data/health

provider_health:
  provider      : Yahoo Finance (yfinance)
  connection_status: CONNECTED
  last_successful_fetch: 2026-08-21T17:57:28Z
  symbols_succeeded: 3/3
  stale_symbols: 0
  unavailable_symbols: 0
  avg_latency_ms: 286
  paper_execution_eligible: True
  quality_summary: {LIVE: 3}
  notes: ['PAPER TRADING ONLY — no real orders are placed by this system.']
```

### Watch checklist — Monday 2026-08-25

Verify each of the following during the first session after 09:15 IST:

| Check | Expected | How to verify |
|---|---|---|
| Scanner universe | CUSTOM_LOW_PRICE_SECTOR | `GET /api/live-data/summary` → `universe_mode` |
| Symbols scanned | 23 | `GET /api/live-data/summary` → `symbols_analysed` |
| No NIFTY_50 fallback | absent | `universe_mode != 'NIFTY_50'` and `universe_size != 50` |
| Forbidden symbols absent | absent | `GET /api/universe/custom/symbols` — active list |
| IOB/UCOBANK not scanned | absent | Not in scan results, `is_active = false` |
| No AUTO/BOOTSTRAP_AUTO trades | 0 | `GET /api/phase20/positions` → `positions = []` |
| Positions remain [] | [] | `GET /api/phase20/positions` |
| Scanner health | CONNECTED / LIVE data | `GET /api/live-data/health` → `connection_status` |
| 15:20 squareoff | no positions to square | `GET /api/phase20/eod-status` |
| EOD outcomes route | works, 0 trades | `GET /api/phase20/eod-outcomes` |
| No ERROR rows | 0 | `GET /api/live-data/summary` → `symbols_with_errors = 0` |
| Build ID | `apexquant-phase0c-20260821` or later | `GET /api/healthz` → `build_id` |

### Scan signal observation (advisory only)

With entries disabled, scanner signals are advisory only. On the first session watch:
- Record what `buy_count`, `strong_buy_count`, `watch_count` are for the 23 custom symbols
- Verify `paper_eligible_count` scores are reasonable (not all 0 or all 23)
- Verify sector-level signal distribution (expect BANK/INFRA/IT signals, not NIFTY sectors)
- No action needed — just observation

---

## TASK 4 — TEST RESULTS (ALL SUITES)

```
Python:
  test_custom_universe_store.py   : 18/18 ✅
  test_phase0c_safety_fixes.py    : 22/22 ✅
  Total                           : 40/40

TypeScript (new):
  universe-admin-security.test.ts : 7/7 ✅

TypeScript (full suite):
  Test Files : 11 passed | 2 failed (13 total)
  Tests      : 123 passed | 2 failed (125 total)
  Pre-existing failures (not Phase 1F related):
    scan-cache-invalidation.test.ts : api_build_id mismatch (expects 'development')
    pushNotifier.test.ts            : mock timing issue
```

---

## TASK 5 — COMPLETE DELIVERABLE CHECKLIST

| Item | Status |
|---|---|
| 1. Current production baseline | ✅ `CUSTOM_LOW_PRICE_SECTOR`, capital=100000, entries=false, positions=[] |
| 2. Admin route security implementation proof | ✅ Token gate in `universe-custom.ts`; dev server returns 403 without token |
| 3. Admin token test results | ✅ 7/7 new security tests pass |
| 4. Kite token hydration table | ⚠️ 0/23 hydrated — local cache stale (2026-08-09, 1 instrument only); requires live Kite session via `POST /universe/custom/refresh` |
| 5. Market-session watch plan/result | ✅ Plan documented; first session Monday 2026-08-25 09:15 IST; provider CONNECTED |
| 6. Active universe remains CUSTOM_LOW_PRICE_SECTOR | ✅ Confirmed |
| 7. Capital remains ₹1,00,000 | ✅ `initial_capital = 100000` |
| 8. Auto entries/bootstrap remain disabled | ✅ Both `false` |
| 9. Positions remain [] | ✅ Confirmed |
| 10. No trades or live orders | ✅ No trades created; `paper_trading_only=True`; `no_live_broker_orders=True` |
| 11. Go/no-go recommendation | See below |

---

## GO / NO-GO RECOMMENDATION FOR AUTO-ENTRY RE-ENABLE

| # | Condition | Status |
|---|---|---|
| 1 | `UNIVERSE_ADMIN_TOKEN` secret set in production | ⚠️ **Required** — secret not yet configured |
| 2 | Admin upsert route deployed with token gate | ⚠️ **Required** — new code not yet deployed to production |
| 3 | First clean market session watched (2026-08-25) | ⏳ Pending — market closed (Friday evening) |
| 4 | Scanner runs on `CUSTOM_LOW_PRICE_SECTOR`, 23 symbols, no NIFTY leak | ⏳ Pending — next market open |
| 5 | No AUTO/BOOTSTRAP_AUTO trades observed during watch session | ⏳ Pending |
| 6 | `positions = []` at moment of auto-entry enable | Required — verify at enable time |
| 7 | `initial_capital = 100000` confirmed at enable time | Required — verify at enable time |
| 8 | Kite token hydration (23 symbols) | ⏳ Optional — improves LTP quality but not a hard blocker |

**CURRENT VERDICT: NO-GO** — 2 hard blockers remain:
1. `UNIVERSE_ADMIN_TOKEN` secret must be set in production before deploying
2. The new security gate code must be deployed to production
3. First clean market session watch must complete (earliest: Monday 2026-08-25)

**Expected GO date: Monday 2026-08-25 after market close**, assuming the session watch passes all checks above.

---

## ACTIONS REQUIRED FROM OPERATOR

### Step 1 — Set UNIVERSE_ADMIN_TOKEN secret (do this now)

The secret has been requested via the Replit Secrets form in the next message. Choose a strong random value (e.g. 32+ character hex string). Store it securely — you will need it to call `POST /universe/custom/upsert` in future.

### Step 2 — Deploy (after setting the secret)

Publish the project from the deployment pane. The token gate will be active from the moment the new build starts. Verify:
```bash
curl -X POST https://nse-trade-intraday.replit.app/api/universe/custom/upsert \
  -H "Content-Type: application/json" \
  -d '{"rows":[]}' \
  → {"success":false,"error":"Forbidden: valid x-admin-token header required"}
```

### Step 3 — Watch Monday session (2026-08-25)

After market open (09:15 IST), poll `GET /api/live-data/summary` and confirm:
- `universe_mode = CUSTOM_LOW_PRICE_SECTOR`
- `symbols_analysed = 23`
- `symbols_with_errors = 0`
- `positions = []`

If all checks pass, Phase 1F is fully complete and auto entries can be enabled.
