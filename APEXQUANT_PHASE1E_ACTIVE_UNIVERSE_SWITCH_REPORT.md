# APEXQUANT PHASE 1E — ACTIVE UNIVERSE SWITCH REPORT

**Date:** 2026-08-21  
**Environment:** Production (`https://nse-trade-intraday.replit.app`)  
**Controlling report:** APEXQUANT_PHASE1D_PRODUCTION_CUSTOM_UNIVERSE_POPULATION_REPORT.md  
**Action:** Switch `active_intraday_universe` from `NIFTY_50` → `CUSTOM_LOW_PRICE_SECTOR`  
**Outcome:** ✅ Complete — universe switched, all safety flags unchanged  

---

## SAFETY CONSTRAINTS — Confirmed Throughout

| Setting | Before switch | After switch | Changed? |
|---|---|---|---|
| `initial_capital` | 100000 | 100000 | No |
| `active_intraday_universe` | NIFTY_50 | CUSTOM_LOW_PRICE_SECTOR | **Yes — intended** |
| `auto_paper_entries` | false | false | No |
| `bootstrap_paper_enabled` | false | false | No |
| `auto_paper_exits` | true | true | No |
| `positions` | [] | [] | No |
| Broker order APIs called | — | 0 | No |
| Trades created | — | 0 | No |
| Positions closed | — | 0 | No |

---

## TASK 1 — PRE-SWITCH SNAPSHOT

Captured immediately before calling `POST /universe/active`:

```
GET /api/phase20/settings
  initial_capital         = 100000          ✅
  active_intraday_universe= NIFTY_50        ✅
  auto_paper_entries      = False           ✅
  bootstrap_paper_enabled = False           ✅
  auto_paper_exits        = True            ✅

GET /api/phase20/positions
  positions: []    count: 0                 ✅

GET /api/universe/custom/status
  active_universe   = NIFTY_50
  active_count      = 23                   ✅
  excluded_count    = 2                    ✅
  total_candidates  = 25                   ✅
  sector_counts     = {BANK:9, INFRA:13, IT:1} ✅
  price_filter      = {min:20, max:500}    ✅
  ohlcv_cache_hit_pct = 100.0              ✅
  paper_trading_only = True                ✅
  no_live_broker_orders = True             ✅

GET /api/universe/custom/symbols
  total rows: 25
  active    : 23 symbols                   ✅
  inactive  : 2 (IOB, UCOBANK)             ✅
```

**Halt-condition check:**
| Condition | Value | Halt? |
|---|---|---|
| positions == [] | ✅ [] | No |
| auto_paper_entries == false | ✅ False | No |
| bootstrap_paper_enabled == false | ✅ False | No |
| custom active_count == 23 | ✅ 23 | No |
| price_filter == 20–500 | ✅ {min:20,max:500} | No |

**No halt conditions triggered — proceeded with switch.**

---

## TASK 2 — SWITCH ACTIVE UNIVERSE

**Endpoint called:**
```
POST https://nse-trade-intraday.replit.app/api/universe/active
Content-Type: application/json

{"active_intraday_universe": "CUSTOM_LOW_PRICE_SECTOR"}
```

**Response:**
```json
{
  "success": true,
  "settings": {
    "active_intraday_universe": "CUSTOM_LOW_PRICE_SECTOR",
    "initial_capital": 100000,
    "auto_paper_entries": false,
    "bootstrap_paper_enabled": false,
    "auto_paper_exits": true,
    ...
  }
}
```

The response body included the full updated settings object — `active_intraday_universe` confirmed as `CUSTOM_LOW_PRICE_SECTOR` in the same call.

---

## TASK 3 — POST-SWITCH VERIFICATION

### 3.1 Settings (confirmed unchanged except universe)

```
GET /api/phase20/settings (after switch)

active_intraday_universe= CUSTOM_LOW_PRICE_SECTOR  ✅ (switched)
initial_capital         = 100000                   ✅ (unchanged)
auto_paper_entries      = False                    ✅ (unchanged)
bootstrap_paper_enabled = False                    ✅ (unchanged)
auto_paper_exits        = True                     ✅ (unchanged)
```

### 3.2 Custom universe status (after switch)

```
GET /api/universe/custom/status (after switch)

active_universe       = CUSTOM_LOW_PRICE_SECTOR   ✅ (updated)
active_count          = 23                         ✅
excluded_count        = 2                          ✅
sector_counts         = {BANK:9, INFRA:13, IT:1}  ✅
price_filter          = {min:20, max:500}          ✅
ohlcv_cache_hit_pct   = 100.0                      ✅
paper_trading_only    = True                       ✅
no_live_broker_orders = True                       ✅
```

### 3.3 Positions (after switch)

```
GET /api/phase20/positions (after switch)

positions: []    count: 0   ✅
```

### 3.4 No trade rows created, updated, or deleted

Verified via `GET /api/phase20/positions` — zero positions before and after switch. The universe switch is a pure settings write — it calls `phase20_settings_update` which patches only the `phase20_settings` store. No trade ledger table is touched.

### 3.5 No broker order APIs called

The `POST /universe/active` route calls `runPython(["phase20_settings_update", ...])` only. The `phase20_settings_update` command performs a settings patch exclusively. No `kite_connect`, `place_order`, `modify_order`, or `cancel_order` calls exist in this code path.

---

## TASK 4 — SCAN RESOLUTION PROOF

```
GET /api/universe/custom/symbols (after switch)

active_count    : 23
inactive_count  : 2

Active symbols (23 — the complete scan universe):
  BANKBARODA  BANKINDIA   CANBK       FEDERALBNK  IDFCFIRSTB
  KTKBANK     MAHABANK    PNB         UNIONBANK
  COALINDIA   GAIL        HUDCO       IRCON       IRFC
  MRPL        NBCC        NMDC        NTPC        PFC
  RECLTD      RVNL        SAIL        WIPRO

Inactive symbols (excluded from scanning):
  IOB       — low price audit row, not scanned ✅
  UCOBANK   — low price audit row, not scanned ✅

NIFTY_50 symbol leak     : NONE ✅
Forbidden symbols present: NONE ✅
  (LTIM, HCLTECH, RATEGAIN, TANLA, PERSISTENT, COFORGE, MPHASIS, LT — all absent)
```

**Scan resolution behaviour:** The scan engine reads `active_intraday_universe` from settings at runtime. Now that this is `CUSTOM_LOW_PRICE_SECTOR`, the engine will call `custom_universe_store.get_active_symbols()` which returns only the 23 active rows. There is no code path that falls back to NIFTY_50 while the setting is `CUSTOM_LOW_PRICE_SECTOR`. OHLCV source for all 23 symbols is yfinance (Kite token hydration pending, task #889).

---

## TASK 5 — ADMIN ROUTE SECURITY CHECK

**Route:** `POST /universe/custom/upsert`

### Current protection level

| Property | Status |
|---|---|
| Authentication middleware | ❌ None — any caller can POST |
| API key / token header check | ❌ None |
| IP allowlist / network restriction | ❌ None |
| Input validation | ✅ Partial — `rows` must be non-empty array; Python layer validates schema |
| Idempotency | ✅ `ON CONFLICT DO UPDATE` — repeated calls don't corrupt data |
| Broker API reachability | ✅ This route can never call a broker order API |
| Trade creation reachability | ✅ This route cannot create or modify trades |
| Request logging | ⚠️ Express access log only — no structured audit trail of who called it |

### Risk assessment

**Current risk: LOW** — The route modifies only `custom_universe_master` (symbol metadata). It cannot create trades, move capital, or call broker APIs regardless of payload. The only abuse vector is overwriting the production symbol list, which would take effect on the next scanner run. Since `auto_paper_entries = false`, a corrupted symbol list would produce scanner results but no paper trades.

**Future risk: MEDIUM-HIGH** — Once auto entries are re-enabled, a malicious or accidental upsert could inject low-quality or adversarial symbols into the scan universe, which could then generate paper buy signals and automatic entries.

### Recommendation: Lock before auto entries are re-enabled

Before setting `auto_paper_entries = true`, restrict this route with an admin token:

```typescript
// In universe-custom.ts, before the upsert handler:
const ADMIN_TOKEN = process.env.UNIVERSE_ADMIN_TOKEN;

router.post("/universe/custom/upsert", wrap(async (req, res) => {
  if (ADMIN_TOKEN && req.headers["x-admin-token"] !== ADMIN_TOKEN) {
    res.status(403).json({ success: false, error: "Forbidden" });
    return;
  }
  // ... existing body
}));
```

Set `UNIVERSE_ADMIN_TOKEN` as a Replit secret. This is **not required now** — auto entries remain disabled and the risk is low. It is a **hard prerequisite** before auto entries are ever switched on.

**Current verdict: SAFE to leave deployed in its current form while auto_paper_entries=false.**

---

## TASK 6 — TEST RESULTS

```
$ python3 -m pytest tests/unit/test_custom_universe_store.py tests/unit/test_phase0c_safety_fixes.py -q

........................................                [100%]
40 passed, 1 warning in 1.55s
```

| Suite | Tests | Result |
|---|---|---|
| `test_custom_universe_store.py` | 18 | ✅ All pass |
| `test_phase0c_safety_fixes.py` | 22 | ✅ All pass |
| **Total** | **40** | **✅ No regressions** |

---

## TASK 7 — COMPLETE DELIVERABLE CHECKLIST

| Item | Status |
|---|---|
| 1. Pre-switch snapshot | ✅ All halt conditions clear (positions=[], entries=false, bootstrap=false, active_count=23, price_filter=20–500) |
| 2. Switch response | ✅ `{"success":true, "active_intraday_universe":"CUSTOM_LOW_PRICE_SECTOR"}` |
| 3. Post-switch settings proof | ✅ All settings verified — only `active_intraday_universe` changed |
| 4. Custom universe status proof | ✅ `active_universe=CUSTOM_LOW_PRICE_SECTOR`, active_count=23, sector_counts correct, price_filter correct |
| 5. Scan-resolution proof | ✅ 23 active custom symbols only; IOB/UCOBANK inactive; no forbidden symbols; no NIFTY_50 leakage |
| 6. Active universe now CUSTOM_LOW_PRICE_SECTOR | ✅ Confirmed in settings, status, and switch response |
| 7. Capital remains ₹1,00,000 | ✅ `initial_capital = 100000` unchanged |
| 8. Auto entries / bootstrap remain disabled | ✅ `auto_paper_entries=False`, `bootstrap_paper_enabled=False` |
| 9. Positions remain [] | ✅ `positions=[]`, count=0 after switch |
| 10. No trades / positions changed | ✅ Pure settings write — no ledger tables touched |
| 11. No live orders | ✅ `paper_trading_only=True`, `no_live_broker_orders=True`, no broker API calls in switch path |
| 12. Admin upsert route security status | ⚠️ Unprotected — LOW risk while entries disabled; must add token gate before enabling entries |
| 13. Phase 1E acceptance | ✅ **ACCEPTED** — see below |
| 14. Remaining conditions before re-enabling auto entries | See below |

---

## PHASE 1E ACCEPTED ✅

The active universe is now `CUSTOM_LOW_PRICE_SECTOR`. The 23 approved Option B symbols (IT=1, Infra=13, Bank=9, ₹20–₹500) form the production scan universe. NIFTY_50 is no longer the active universe. All safety flags are intact.

---

## REMAINING CONDITIONS BEFORE RE-ENABLING AUTO ENTRIES

The following must all be satisfied before setting `auto_paper_entries = true`:

| Condition | Status |
|---|---|
| 1. **First clean market-session watch** — observe at least one full intraday session (09:15–15:30 IST) scanning the 23 custom symbols without errors, no spurious signals, scanner health = HEALTHY | ⏳ Pending |
| 2. **Kite token hydration** (task #889) — populate `instrument_token` for all 23 symbols to enable real-time LTP overlay | ⏳ Pending (not a hard blocker, but improves signal quality) |
| 3. **Admin upsert route locked** — add `UNIVERSE_ADMIN_TOKEN` secret and `x-admin-token` header gate to `POST /universe/custom/upsert` before auto entries go live | ⏳ Required before entries |
| 4. **`positions = []` at moment of enable** — verify immediately before calling the enable endpoint | Required (verify at enable time) |
| 5. **Capital confirmed ₹1,00,000** — verify `initial_capital = 100000` immediately before enabling | Required (verify at enable time) |

**Auto entries remain disabled. No further action is needed from this phase.**
