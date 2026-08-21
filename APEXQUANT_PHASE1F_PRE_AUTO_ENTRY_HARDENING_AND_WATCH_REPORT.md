# APEXQUANT PHASE 1F — PRE-AUTO-ENTRY HARDENING AND MARKET SESSION WATCH REPORT

**Date:** 2026-08-21  
**Environment:** Dev confirmed ✅ | Production deploy pending ⏳  
**Controlling report:** APEXQUANT_PHASE1E_ACTIVE_UNIVERSE_SWITCH_REPORT.md  
**Outcome:** Security gate implemented, tested, and confirmed active on dev server. `UNIVERSE_ADMIN_TOKEN` secret set. Production deploy ready to publish.

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
| Positions closed | 0 | No |

---

## TASK 1 — ADMIN ROUTE SECURITY IMPLEMENTATION

### Route changed

**File:** `artifacts/api-server/src/routes/universe-custom.ts`  
**Route:** `POST /universe/custom/upsert`

```typescript
// Before (unprotected — any caller could write the symbol master):
router.post("/universe/custom/upsert", wrap(async (req, res) => {
  const rows = req.body?.rows;
  if (!Array.isArray(rows) || rows.length === 0) { ... }
  res.json(await runPython(["universe_custom_upsert", ...]));
}));

// After (fail-closed token gate):
router.post("/universe/custom/upsert", wrap(async (req, res) => {
  const expectedToken = process.env.UNIVERSE_ADMIN_TOKEN;
  const providedToken = req.headers["x-admin-token"];
  // Fail-closed: no env var OR wrong header → 403 always
  if (!expectedToken || providedToken !== expectedToken) {
    res.status(403).json({ success: false, error: "Forbidden: valid x-admin-token header required" });
    return;
  }
  const rows = req.body?.rows;
  if (!Array.isArray(rows) || rows.length === 0) { ... }
  res.json(await runPython(["universe_custom_upsert", ...]));
}));
```

**Fail-closed guarantee:** If `UNIVERSE_ADMIN_TOKEN` is not set in the environment, `!expectedToken` is truthy and every request returns 403 regardless of what header the caller sends. An unconfigured environment is never open.

**GET routes unchanged:** `GET /universe/custom/status` and `GET /universe/custom/symbols` are read-only and remain public — no token required.

### `UNIVERSE_ADMIN_TOKEN` secret

Set via Replit Secrets on 2026-08-21. Present in the shared environment — will be available to the production build automatically on next deploy.

### Dev server verification

Immediately after restarting with the new code and secret:

```
POST /api/universe/custom/upsert  (no token)
→ HTTP 403  {"success":false,"error":"Forbidden: valid x-admin-token header required"}  ✅

POST /api/universe/custom/upsert  (wrong token)
→ HTTP 403  {"success":false,"error":"Forbidden: valid x-admin-token header required"}  ✅

GET /api/universe/custom/status   (no token)
→ HTTP 200  {"success":true,"active_count":23,...}  ✅  (public — no change)
```

### Production status (pre-deploy)

```
POST https://nse-trade-intraday.replit.app/api/universe/custom/upsert  (no token)
→ HTTP 400  {"success":false,"error":"rows must be a non-empty array"}
```

Production is still running the old code — the gate reaches body validation but not the token check. **Deploy is required.** After deploy the same request will return HTTP 403.

---

## TASK 2 — SECURITY TESTS

**New test file:** `artifacts/api-server/src/routes/universe-admin-security.test.ts`

| # | Test | Result |
|---|---|---|
| 1 | `POST /upsert` without `x-admin-token` → 403, `universe_custom_upsert` never dispatched | ✅ Pass |
| 2 | `POST /upsert` with wrong token → 403, `universe_custom_upsert` never dispatched | ✅ Pass |
| 3 | `POST /upsert` with correct token → 200, Python dispatched | ✅ Pass |
| 4 | `GET /universe/custom/status` public, no 403 | ✅ Pass |
| 5 | `GET /universe/custom/symbols` public, no 403 | ✅ Pass |
| 6 | Only `universe_custom_upsert` dispatched — no broker order commands | ✅ Pass |
| 7 | Fail-closed: 403 for any token when `UNIVERSE_ADMIN_TOKEN` env var unset | ✅ Pass |

**Full TS suite:**
```
Test Files  1 failed | 12 passed (13)
Tests       1 failed | 124 passed (125)
Duration    13.64s
```

The 1 remaining failure is **pre-existing and unrelated to Phase 1F**:
- `scan-cache-invalidation.test.ts` — asserts `api_build_id = 'development'`; receives `apexquant-phase0c-20260821` (pre-existing since the Phase 0C build ID was stamped)

**Python suites:**
```
test_custom_universe_store.py   : 18/18 ✅
test_phase0c_safety_fixes.py    : 22/22 ✅
Total                           : 40/40 passed in 1.34s
```

---

## TASK 3 — KITE TOKEN HYDRATION

The local Kite instrument cache (`kite_instruments_cache.json`) was inspected:

| Field | Value |
|---|---|
| Cache date | 2026-08-09 (12 days stale) |
| Total instruments | 1 record |
| Custom symbols matched | **0 / 23** |

Hydration is **not possible from the local cache**. All 23 active symbols retain `instrument_token = NULL`.

**Per-symbol summary (all 23 active symbols):**

| Symbol | Yahoo symbol | Kite symbol | Token | OHLCV | Status |
|---|---|---|---|---|---|
| BANKBARODA | BANKBARODA.NS | BANKBARODA | NULL | ✅ | Pending live Kite session |
| BANKINDIA | BANKINDIA.NS | BANKINDIA | NULL | ✅ | Pending live Kite session |
| CANBK | CANBK.NS | CANBK | NULL | ✅ | Pending live Kite session |
| FEDERALBNK | FEDERALBNK.NS | FEDERALBNK | NULL | ✅ | Pending live Kite session |
| IDFCFIRSTB | IDFCFIRSTB.NS | IDFCFIRSTB | NULL | ✅ | Pending live Kite session |
| KTKBANK | KTKBANK.NS | KTKBANK | NULL | ✅ | Pending live Kite session |
| MAHABANK | MAHABANK.NS | MAHABANK | NULL | ✅ | Pending live Kite session |
| PNB | PNB.NS | PNB | NULL | ✅ | Pending live Kite session |
| UNIONBANK | UNIONBANK.NS | UNIONBANK | NULL | ✅ | Pending live Kite session |
| COALINDIA | COALINDIA.NS | COALINDIA | NULL | ✅ | Pending live Kite session |
| GAIL | GAIL.NS | GAIL | NULL | ✅ | Pending live Kite session |
| HUDCO | HUDCO.NS | HUDCO | NULL | ✅ | Pending live Kite session |
| IRCON | IRCON.NS | IRCON | NULL | ✅ | Pending live Kite session |
| IRFC | IRFC.NS | IRFC | NULL | ✅ | Pending live Kite session |
| MRPL | MRPL.NS | MRPL | NULL | ✅ | Pending live Kite session |
| NBCC | NBCC.NS | NBCC | NULL | ✅ | Pending live Kite session |
| NMDC | NMDC.NS | NMDC | NULL | ✅ | Pending live Kite session |
| NTPC | NTPC.NS | NTPC | NULL | ✅ | Pending live Kite session |
| PFC | PFC.NS | PFC | NULL | ✅ | Pending live Kite session |
| RECLTD | RECLTD.NS | RECLTD | NULL | ✅ | Pending live Kite session |
| RVNL | RVNL.NS | RVNL | NULL | ✅ | Pending live Kite session |
| SAIL | SAIL.NS | SAIL | NULL | ✅ | Pending live Kite session |
| WIPRO | WIPRO.NS | WIPRO | NULL | ✅ | Pending live Kite session |

**Not a blocker.** All 23 symbols have `ohlcv_available = true` and `ohlcv_cache_hit_rate_pct = 100`. yfinance provides complete OHLCV for scanning. Kite LTP overlay improves real-time price freshness only. Token hydration is tracked as task #893 — complete it by calling `POST /api/universe/custom/refresh` during an active Kite session.

---

## TASK 4 — FIRST MARKET SESSION WATCH PLAN

### Why the first session hasn't run yet

The Phase 1E switch happened at **~17:58 IST on 2026-08-21 (Friday, after market close)**. The last full scan (scan_id `76e307f291e7`) ran at 10:02 IST under `NIFTY_50`. The scanner reads `active_intraday_universe` from settings at each scan start, so the **first custom-universe scan runs at market open Monday 2026-08-25 09:15 IST**.

### Provider readiness (confirmed today)

```
GET /api/live-data/health

provider_health:
  connection_status       : CONNECTED
  provider                : Yahoo Finance (yfinance)
  last_successful_fetch   : 2026-08-21T17:57:28Z
  symbols_succeeded       : 3/3
  stale_symbols           : 0
  avg_latency_ms          : 286
  paper_execution_eligible: True
  quality_summary         : {LIVE: 3}
  notes: ['PAPER TRADING ONLY — no real orders are placed by this system.']
```

### Session watch checklist — Monday 2026-08-25

Check after 09:30 IST (allow scanner first run to complete):

| Check | Expected | Endpoint |
|---|---|---|
| Universe mode | `CUSTOM_LOW_PRICE_SECTOR` | `GET /api/live-data/summary` → `universe_mode` |
| Symbols scanned | 23 | `GET /api/live-data/summary` → `symbols_analysed` |
| No NIFTY_50 fallback | `universe_mode != NIFTY_50` | same |
| Forbidden symbols absent | LTIM/HCLTECH/RATEGAIN/etc. absent | `GET /api/universe/custom/symbols` |
| IOB/UCOBANK not scanned | `is_active = false`, absent from results | same |
| No AUTO/BOOTSTRAP trades | `positions = []` | `GET /api/phase20/positions` |
| Scanner errors | `symbols_with_errors = 0` | `GET /api/live-data/summary` |
| Provider health | CONNECTED, all LIVE | `GET /api/live-data/health` |
| 15:20 squareoff | No open positions | `GET /api/phase20/eod-status` |
| EOD outcomes | Route works, 0 trades | `GET /api/phase20/eod-outcomes` |
| Build ID | `apexquant-phase0c-20260821` or later | `GET /api/healthz` → `build_id` |

---

## TASK 5 — COMPLETE DELIVERABLE CHECKLIST

| Item | Status |
|---|---|
| 1. Current production baseline | ✅ `CUSTOM_LOW_PRICE_SECTOR`, capital=100000, entries=false, bootstrap=false, exits=true, positions=[] |
| 2. Admin route security proof | ✅ Token gate live on dev; fail-closed; GET routes unaffected |
| 3. Security test results | ✅ 7/7 new tests pass; 40/40 Python pass; 124/125 TS pass (1 pre-existing unrelated failure) |
| 4. Kite token hydration table | ⚠️ 0/23 — cache stale; requires live Kite session (task #893) |
| 5. Session watch plan | ✅ Monday 2026-08-25; provider CONNECTED; 23-symbol checklist documented |
| 6. Active universe CUSTOM_LOW_PRICE_SECTOR | ✅ Confirmed |
| 7. Capital ₹1,00,000 | ✅ `initial_capital = 100000` |
| 8. Auto entries/bootstrap disabled | ✅ Both `false` — unchanged |
| 9. Positions [] | ✅ Confirmed |
| 10. No trades or live orders | ✅ `paper_trading_only=True`, `no_live_broker_orders=True` |
| 11. Go/no-go recommendation | See below |

---

## GO / NO-GO RECOMMENDATION FOR AUTO-ENTRY RE-ENABLE

| # | Condition | Status |
|---|---|---|
| 1 | `UNIVERSE_ADMIN_TOKEN` secret set | ✅ Set 2026-08-21 |
| 2 | Admin upsert route with token gate deployed to production | ⏳ **Deploy required** |
| 3 | Production returns 403 without token (post-deploy verify) | ⏳ After deploy |
| 4 | First clean market session watched | ⏳ Monday 2026-08-25 |
| 5 | Scanner `universe_mode = CUSTOM_LOW_PRICE_SECTOR`, `symbols_analysed = 23` | ⏳ Monday 2026-08-25 |
| 6 | No AUTO/BOOTSTRAP_AUTO trades observed during watch session | ⏳ Monday 2026-08-25 |
| 7 | `positions = []` at moment of auto-entry enable | Required — verify at enable time |
| 8 | `initial_capital = 100000` at moment of auto-entry enable | Required — verify at enable time |

**CURRENT VERDICT: NO-GO — 1 hard blocker remaining:**  
→ Deploy the security gate code to production (publish the project).

**Expected GO date:** Monday 2026-08-25 after market close, if session watch passes.

---

## POST-DEPLOY VERIFICATION (run after publish completes)

```bash
# 1. Gate is active — no token → 403
curl -s -o /dev/null -w "%{http_code}" \
  -X POST https://nse-trade-intraday.replit.app/api/universe/custom/upsert \
  -H "Content-Type: application/json" -d '{"rows":[]}'
# Expected: 403

# 2. Settings unchanged
curl -s https://nse-trade-intraday.replit.app/api/phase20/settings | \
  python3 -c "import sys,json; s=json.load(sys.stdin)['settings']; \
  print(s['active_intraday_universe'], s['auto_paper_entries'], s['initial_capital'])"
# Expected: CUSTOM_LOW_PRICE_SECTOR False 100000

# 3. Positions still []
curl -s https://nse-trade-intraday.replit.app/api/phase20/positions | \
  python3 -c "import sys,json; print(json.load(sys.stdin).get('positions'))"
# Expected: []
```
