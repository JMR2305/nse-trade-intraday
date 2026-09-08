2# APEXQUANT PHASE 1F — POST-PUBLISH SECURITY GATE VERIFICATION REPORT

**Verification timestamp:** 2026-08-21T18:43:38Z (UTC) / 2026-08-22 00:13 IST  
**Environment:** Production — https://nse-trade-intraday.replit.app  
**Publish triggered by:** Operator (2026-08-21, after market close)  
**Verdict:** ✅ ALL CHECKS PASSED — Phase 1F security blocker RESOLVED

---

## SAFETY INVARIANT — Confirmed Unchanged Throughout

| Setting | Expected | Production value | Changed? |
|---|---|---|---|
| `auto_paper_entries` | false | **False** | No |
| `bootstrap_paper_enabled` | false | **False** | No |
| `initial_capital` | 100000 | **100000** | No |
| `active_intraday_universe` | CUSTOM_LOW_PRICE_SECTOR | **CUSTOM_LOW_PRICE_SECTOR** | No |
| `auto_paper_exits` | true | **True** | No |
| `positions` | [] | **[]** | No |
| Trades created | 0 | **0** | No |
| Positions closed | 0 | **0** | No |
| Broker order API calls | 0 | **0** | No |
| Live orders placed | 0 | **0** | No |

---

## CHECK 1 — POST upsert with no x-admin-token

**Request:**
```
POST https://nse-trade-intraday.replit.app/api/universe/custom/upsert
Content-Type: application/json
Body: {"rows":[]}
(no x-admin-token header)
```

**Response:**
```
HTTP 403
{"success":false,"error":"Forbidden: valid x-admin-token header required"}
```

**Verdict:** ✅ PASS  
- HTTP 403 returned  
- Error message matches expected: `valid x-admin-token header required`  
- `universe_custom_upsert` Python command not dispatched (gate fires before body validation or Python call)

---

## CHECK 2 — POST upsert with wrong x-admin-token

**Request:**
```
POST https://nse-trade-intraday.replit.app/api/universe/custom/upsert
Content-Type: application/json
x-admin-token: definitely-not-the-right-token-xyz123
Body: {"rows":[]}
```

**Response:**
```
HTTP 403
{"success":false,"error":"Forbidden: valid x-admin-token header required"}
```

**Verdict:** ✅ PASS  
- HTTP 403 returned for wrong token  
- Same error body as no-token case — no information leakage about expected token  
- `universe_custom_upsert` Python command not dispatched

---

## CHECK 3 — GET /api/universe/custom/status (public, no token)

**Request:**
```
GET https://nse-trade-intraday.replit.app/api/universe/custom/status
(no x-admin-token header)
```

**Response:**
```
HTTP 200
{
  "success": true,
  "active_universe": "CUSTOM_LOW_PRICE_SECTOR",
  "custom_universe_name": "CUSTOM_LOW_PRICE_SECTOR",
  "price_filter": {"min": 20, "max": 500},
  "sectors": ["IT", "INFRA", "BANK"],
  "active_count": 23,
  "excluded_count": 2,
  "total_candidates": 25,
  "sector_counts": {"BANK": 9, "INFRA": 13, "OTHER": 1},
  "last_refresh": null,
  "ohlcv_cache_hit_rate_pct": 95.7,
  "kite_ltp": {"available_symbols": 0, "status": "FALLBACK_OR_UNAVAILABLE"},
  "asm_gsm": "unavailable_skip",
  "paper_trading_only": true,
  "no_live_broker_orders": true
}
```

**Field checks:**

| Field | Expected | Actual | Pass? |
|---|---|---|---|
| HTTP status | 200 | 200 | ✅ |
| `active_universe` | CUSTOM_LOW_PRICE_SECTOR | CUSTOM_LOW_PRICE_SECTOR | ✅ |
| `active_count` | 23 | 23 | ✅ |
| `price_filter.min` | 20 | 20 | ✅ |
| `price_filter.max` | 500 | 500 | ✅ |
| `paper_trading_only` | true | true | ✅ |
| `no_live_broker_orders` | true | true | ✅ |
| GET accessible without token | Yes | Yes | ✅ |

**Verdict:** ✅ PASS — Read-only routes remain public; token gate does not affect GET endpoints.

---

## CHECK 4 — GET /api/universe/custom/symbols (public, no token)

**Request:**
```
GET https://nse-trade-intraday.replit.app/api/universe/custom/symbols
(no x-admin-token header)
```

**Response analysis:**

| Field | Expected | Actual | Pass? |
|---|---|---|---|
| HTTP status | 200 | 200 | ✅ |
| `active_count` | 23 | 23 | ✅ |
| `inactive_count` | 2 | 2 | ✅ |
| IOB inactive | true | true | ✅ |
| UCOBANK inactive | true | true | ✅ |
| Forbidden symbols in active list | 0 | 0 | ✅ |
| GET accessible without token | Yes | Yes | ✅ |

**23 active symbols confirmed:**
```
BANKBARODA, BANKINDIA, CANBK, FEDERALBNK, IDFCFIRSTB, KTKBANK, MAHABANK, PNB, UNIONBANK
COALINDIA, GAIL, HUDCO, IRCON, IRFC, MRPL, NBCC, NMDC, NTPC, PFC, RECLTD, RVNL, SAIL
WIPRO
```

**2 inactive symbols confirmed:**
```
IOB, UCOBANK
```

**Forbidden NIFTY_50 symbols confirmed absent from active list:**  
LTIM, HCLTECH, RATEGAIN, KFINTECH, TCS, INFY — none present.

**Verdict:** ✅ PASS

---

## CHECK 5 — GET /api/phase20/settings

**Request:**
```
GET https://nse-trade-intraday.replit.app/api/phase20/settings
```

**Response:**

| Field | Expected | Actual | Pass? |
|---|---|---|---|
| HTTP status | 200 | 200 | ✅ |
| `initial_capital` | 100000 | 100000 | ✅ |
| `active_intraday_universe` | CUSTOM_LOW_PRICE_SECTOR | CUSTOM_LOW_PRICE_SECTOR | ✅ |
| `auto_paper_entries` | false | False | ✅ |
| `bootstrap_paper_enabled` | false | False | ✅ |
| `auto_paper_exits` | true | True | ✅ |

**Verdict:** ✅ PASS — All production settings unchanged after publish.

---

## CHECK 6 — GET /api/phase20/positions

**Request:**
```
GET https://nse-trade-intraday.replit.app/api/phase20/positions
```

**Response:**

| Field | Expected | Actual | Pass? |
|---|---|---|---|
| HTTP status | 200 | 200 | ✅ |
| `positions` | [] | [] | ✅ |
| `positions_count` | 0 | 0 | ✅ |

**Verdict:** ✅ PASS — No open positions, no carry-overs, no unexpected state.

---

## CHECK 7 — No Trades, No Positions, No Live Orders

| Invariant | Evidence | Pass? |
|---|---|---|
| No trades created | `positions=[]`, no ledger rows observed | ✅ |
| No positions closed | Pre-publish positions=[]; post-publish positions=[] | ✅ |
| No broker order API calls | `paper_trading_only=true`, `no_live_broker_orders=true` on status; `auto_paper_entries=false` | ✅ |
| No live orders | Entries disabled; paper-only confirmed | ✅ |
| Publish action = code deploy only | Static route code change; zero data mutation required | ✅ |

---

## CHECK 8 — Phase 0C Safety Tests (Post-Publish)

Run against local dev (same codebase as published):

```
tests/unit/test_phase0c_safety_fixes.py  — 22/22 ✅
tests/unit/test_custom_universe_store.py — 18/18 ✅
Total: 40 passed, 1 warning in 1.29s
```

All 40 pass. The `DeprecationWarning` on `datetime.utcnow()` is pre-existing and does not affect test outcomes.

---

## SUMMARY TABLE

| # | Check | Expected | Result |
|---|---|---|---|
| 1 | POST no token | HTTP 403 | ✅ HTTP 403 |
| 2 | POST wrong token | HTTP 403 | ✅ HTTP 403 |
| 3 | GET status (public) | HTTP 200, active_count=23, price_filter={20,500} | ✅ |
| 4 | GET symbols (public) | HTTP 200, 23 active, IOB+UCOBANK inactive, no forbidden | ✅ |
| 5 | Settings | capital=100000, universe=CUSTOM, entries=false, bootstrap=false | ✅ |
| 6 | Positions | [] | ✅ |
| 7 | No trades/orders | 0 | ✅ |
| 8 | Phase 0C safety tests | 40/40 pass | ✅ 40/40 |

---

## PHASE 1F SECURITY BLOCKER STATUS

| Blocker | Status before publish | Status after publish |
|---|---|---|
| `POST /upsert` returns 403 without token (production) | ❌ Was returning 400 (body validation reached) | ✅ Returns 403 (token gate fires first) |
| `UNIVERSE_ADMIN_TOKEN` secret present in production env | ✅ Set 2026-08-21 | ✅ Confirmed active |
| GET routes unaffected | ✅ | ✅ |
| Settings/positions unchanged | ✅ | ✅ |

**Phase 1F security blocker: RESOLVED ✅**

---

## GO / NO-GO FOR AUTO-ENTRY RE-ENABLE (Updated)

| # | Condition | Status |
|---|---|---|
| 1 | `UNIVERSE_ADMIN_TOKEN` secret set | ✅ 2026-08-21 |
| 2 | Admin upsert route token gate deployed to production | ✅ **Verified 2026-08-21T18:43Z** |
| 3 | Production returns 403 without token | ✅ **Confirmed** |
| 4 | First market session watched (custom universe scan confirmed) | ⏳ Monday 2026-08-24 09:15 IST |
| 5 | Scanner `universe_mode=CUSTOM_LOW_PRICE_SECTOR`, `symbols_analysed=23` | ⏳ Monday 2026-08-24 |
| 6 | No AUTO/BOOTSTRAP_AUTO trades during watch session | ⏳ Monday 2026-08-24 |
| 7 | `positions=[]` at the moment of auto-entry enable | Required — verify at enable time |
| 8 | `initial_capital=100000` at the moment of auto-entry enable | Required — verify at enable time |

**Current verdict: NO-GO — 1 remaining condition**  
The only remaining blocker before auto entries can be considered is **the Monday 2026-08-24 market session watch** (task #892).

---

## MONDAY 2026-08-24 SESSION WATCH CHECKLIST

Check after 09:30 IST (allow the 09:15 scan to complete):

```bash
# Universe mode and symbols analysed
curl -s https://nse-trade-intraday.replit.app/api/live-data/summary | \
  python3 -c "import sys,json; d=json.load(sys.stdin); \
  print('universe_mode:', d.get('universe_mode')); \
  print('symbols_analysed:', d.get('symbols_analysed')); \
  print('symbols_with_errors:', d.get('symbols_with_errors'))"
# Expected: universe_mode=CUSTOM_LOW_PRICE_SECTOR, symbols_analysed=23, symbols_with_errors=0

# Positions still []
curl -s https://nse-trade-intraday.replit.app/api/phase20/positions | \
  python3 -c "import sys,json; print(json.load(sys.stdin).get('positions'))"
# Expected: []

# Provider health
curl -s https://nse-trade-intraday.replit.app/api/live-data/health | \
  python3 -c "import sys,json; d=json.load(sys.stdin); \
  print('status:', d.get('provider_health',{}).get('connection_status'))"
# Expected: CONNECTED

# EOD squareoff status (check at 15:25 IST)
curl -s https://nse-trade-intraday.replit.app/api/phase20/eod-status
# Expected: no open positions, 0 trades
```

**If all checks pass Monday:** Conditions for enabling `auto_paper_entries=true` are met. Operator approves. Enable via `POST /api/phase20/settings` with `{"auto_paper_entries": true}`.
