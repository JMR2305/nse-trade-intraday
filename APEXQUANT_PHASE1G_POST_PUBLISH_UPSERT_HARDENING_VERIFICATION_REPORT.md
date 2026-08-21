# APEXQUANT PHASE 1G — POST-PUBLISH UPSERT HARDENING VERIFICATION REPORT

**Environment:** Production only — `https://nse-trade-intraday.replit.app`  
**Published build status:** Healthy public Autoscale deployment  
**Publish timestamp:** Production deployment started `2026-08-21T20:16:13.513Z` / `2026-08-22 01:46:13 IST`; API artifact process started at `2026-08-21T20:16:13.565Z`.  
**Verification timestamp:** `2026-08-21T20:45:33Z` / `2026-08-22 02:15:33 IST`  
**Verdict:** **PASS — partial active-row upsert hardening is live in production.**

---

## Safety Invariant — No Trading or Configuration Mutation

This verification used only production read-only `GET` requests plus two intentionally rejected `POST /api/universe/custom/upsert` requests:

1. an authenticated but incomplete WIPRO payload, expected to fail validation; and
2. an unauthenticated empty-body request, expected to fail authorization.

It did **not** call settings, scan, trade-entry, position-exit, square-off, broker, or live-order endpoints.

| Invariant | Before verification | After verification | Result |
|---|---|---|---|
| `initial_capital` | 100000 | 100000 | ✅ unchanged |
| `active_intraday_universe` | `CUSTOM_LOW_PRICE_SECTOR` | `CUSTOM_LOW_PRICE_SECTOR` | ✅ unchanged |
| `auto_paper_entries` | false | false | ✅ remains disabled |
| `bootstrap_paper_enabled` | false | false | ✅ remains disabled |
| `auto_paper_exits` | true | true | ✅ unchanged |
| Open positions | `[]` | `[]` | ✅ none |
| Ledger records | 6 historic closed records | Same 6 records | ✅ no trade/close mutation |
| Broker order APIs / live orders | Not called | Not called | ✅ paper-only verification |

---

## 1. Partial WIPRO Overwrite Rejection Proof

**Request**

```http
POST /api/universe/custom/upsert
Content-Type: application/json
x-admin-token: [valid production secret; not displayed]

{
  "rows": [
    {
      "symbol": "WIPRO",
      "is_active": true,
      "sector": null,
      "price_max": 200,
      "ohlcv_available": false
    }
  ]
}
```

**Production response**

```text
HTTP 400
{"success":false,"error":"active row 0 for WIPRO must include non-null: sector, company_name, yahoo_symbol, kite_symbol, price_min"}
```

**Result: ✅ PASS**

- The response is the active-row validation failure, before a successful upsert response can be produced.
- `universe_custom_upsert` was **not dispatched**: the request was rejected at the HTTP validation gate with HTTP 400.
- The intentionally supplied unsafe values did not alter production data.

---

## 2. WIPRO Preservation Proof

`GET /api/universe/custom/symbols` was captured immediately before and after the rejected POST.

| Field | Before | After | Result |
|---|---|---|---|
| `symbol` | `WIPRO` | `WIPRO` | ✅ |
| `sector` | `IT` | `IT` | ✅ |
| `company_name` | `Wipro Ltd` | `Wipro Ltd` | ✅ |
| `yahoo_symbol` | `WIPRO.NS` | `WIPRO.NS` | ✅ |
| `kite_symbol` | `WIPRO` | `WIPRO` | ✅ |
| `price_min` | 20 | 20 | ✅ |
| `price_max` | 500 | 500 | ✅ |
| `ohlcv_available` | true | true | ✅ |
| `is_active` | true | true | ✅ |
| Full WIPRO response object | identical | identical | ✅ |
| Full 25-row symbols response | identical | identical | ✅ |

**Result: ✅ PASS — the rejected partial payload did not overwrite WIPRO metadata.**

---

## 3. Custom-Universe Status Proof

**Request:** `GET /api/universe/custom/status` without an admin token  
**HTTP status:** `200` before and after the rejected POST

| Field | Expected | Production result | Result |
|---|---|---|---|
| `active_universe` | `CUSTOM_LOW_PRICE_SECTOR` | `CUSTOM_LOW_PRICE_SECTOR` | ✅ |
| `active_count` | 23 | 23 | ✅ |
| `sector_counts.BANK` | 9 | 9 | ✅ |
| `sector_counts.INFRA` | 13 | 13 | ✅ |
| `sector_counts.IT` | 1 | 1 | ✅ |
| `price_filter.min` | 20 | 20 | ✅ |
| `price_filter.max` | 500 | 500 | ✅ |
| `ohlcv_cache_hit_rate_pct` | 100 or explained | 100 | ✅ no miss |
| `paper_trading_only` | true | true | ✅ |
| `no_live_broker_orders` | true | true | ✅ |

**Result: ✅ PASS**

---

## 4. Symbol-List Proof

**Request:** `GET /api/universe/custom/symbols` without an admin token  
**HTTP status:** `200` before and after the rejected POST

| Check | Production result | Result |
|---|---|---|
| Total stored rows | 25 | ✅ |
| Active symbols | 23 | ✅ |
| WIPRO sector | `IT` | ✅ |
| WIPRO price band | 20–500 | ✅ |
| WIPRO OHLCV availability | true | ✅ |
| IOB | inactive | ✅ |
| UCOBANK | inactive | ✅ |
| Forbidden symbols in active list | none | ✅ |

**Result: ✅ PASS**

---

## 5. Settings Proof

**Request:** `GET /api/phase20/settings`  
**HTTP status:** `200` before and after the rejected POST

| Field | Expected | Production result | Result |
|---|---|---|---|
| `initial_capital` | 100000 | 100000 | ✅ |
| `active_intraday_universe` | `CUSTOM_LOW_PRICE_SECTOR` | `CUSTOM_LOW_PRICE_SECTOR` | ✅ |
| `auto_paper_entries` | false | false | ✅ |
| `bootstrap_paper_enabled` | false | false | ✅ |
| `auto_paper_exits` | true | true | ✅ |

**Result: ✅ PASS — no configuration was changed.**

---

## 6. Positions and Ledger Proof

### Positions

**Request:** `GET /api/phase20/positions`  
**HTTP status:** `200` before and after the rejected POST

```json
{"positions":[]}
```

**Result: ✅ PASS — no open positions existed or were changed.**

### Ledger

**Request:** `GET /api/phase20/ledger`  
**HTTP status:** `200` before and after the rejected POST

| Check | Before | After | Result |
|---|---:|---:|---|
| Ledger record count | 6 | 6 | ✅ |
| Trade IDs | identical | identical | ✅ |
| Trade statuses | all `CLOSED` | all `CLOSED` | ✅ |

The six records are pre-existing historic closed paper records; their count, IDs, and statuses were identical before and after this verification.

**Result: ✅ PASS — no trades were created and no positions were closed by this verification.**

---

## 7. Public-Route and Authorization Proof

| Request | Token | Expected | Production result | Result |
|---|---|---|---|---|
| `GET /api/universe/custom/status` | none | HTTP 200 | HTTP 200 | ✅ |
| `GET /api/universe/custom/symbols` | none | HTTP 200 | HTTP 200 | ✅ |
| `GET /api/phase20/settings` | none | HTTP 200 | HTTP 200 | ✅ |
| `GET /api/phase20/positions` | none | HTTP 200 | HTTP 200 | ✅ |
| `POST /api/universe/custom/upsert` with `{"rows":[]}` | none | HTTP 403 | HTTP 403 | ✅ |

Unauthenticated POST response:

```json
{"success":false,"error":"Forbidden: valid x-admin-token header required"}
```

**Result: ✅ PASS — public read-only routes remain available, while the write route remains token-protected.**

---

## 8. Hardening-Blocker Resolution

| Blocker | Status |
|---|---|
| A partial active-symbol upsert can null required metadata | ✅ resolved |
| Omitted active-row fields can silently default WIPRO `price_max` to 200 | ✅ resolved |
| An incomplete WIPRO payload can set `ohlcv_available=false` and persist | ✅ resolved |
| Valid token bypasses active-row completeness validation | ✅ resolved |
| Public GET routes regress because of write-route hardening | ✅ resolved |

**Phase 1G partial-upsert hardening blocker: RESOLVED ✅**

---

## 9. Remaining Auto-Entry Blocker

**Current decision: NO-GO.**

Do **not** enable `auto_paper_entries`.  
Do **not** enable `bootstrap_paper_enabled`.

The remaining prerequisite is the first Monday regular-market custom-universe watch:

1. observe a completed scan with `universe_mode=CUSTOM_LOW_PRICE_SECTOR`;
2. confirm `symbols_analysed=23` and `symbols_with_errors=0`;
3. confirm no NIFTY_50 fallback;
4. recheck the custom-universe status, symbol list, settings, positions, and provider health; and
5. complete the after-15:20 IST EOD checks with no open positions and no `ERROR` outcome rows.

Only after that watch passes and an operator explicitly approves it may auto-paper-entry re-enable be considered.