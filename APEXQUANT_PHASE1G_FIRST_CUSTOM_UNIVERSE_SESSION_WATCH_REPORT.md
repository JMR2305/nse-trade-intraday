# APEXQUANT PHASE 1G — FIRST CUSTOM-UNIVERSE SESSION WATCH REPORT

**Report state:** Pre-session preparation and data-integrity correction complete; market-session and EOD observations pending.  
**Controlling report:** `APEXQUANT_PHASE1F_POST_PUBLISH_SECURITY_GATE_VERIFICATION_REPORT.md`  
**Production target:** `https://nse-trade-intraday.replit.app`  
**Prepared:** 2026-08-22 00:49 IST / 2026-08-21T19:19:15Z  
**Current decision:** **NO-GO** for auto-paper-entry re-enable until the Monday 2026-08-24 scan and EOD watch complete.

---

## 1. Correct Exchange Session Date

The previous reports incorrectly called **2026-08-25** a Monday. It is a Tuesday.

| Item | Confirmed value |
|---|---|
| Phase 1E switch | Friday, 2026-08-21, after NSE close |
| Next calendar weekday | Monday, **2026-08-24** |
| NSE trading-holiday check | The official NSE 2026 equity trading-holiday list has no holiday on 2026-08-24 |
| Next actual NSE regular trading session | **Monday, 2026-08-24**, regular market opens 09:15 IST |
| First custom-universe watch window | Check first completed scan after 09:30 IST on Monday, 2026-08-24 |

The Phase 1F pre-publish and post-publish reports were corrected to use Monday, 2026-08-24.

---

## 2. Sector-Count Investigation and Fix

### Production issue observed before repair

`GET /api/universe/custom/status` correctly reported:

```json
"sector_counts": {"BANK": 9, "INFRA": 13, "OTHER": 1}
```

`GET /api/universe/custom/symbols` identified the source row:

```json
{
  "symbol": "WIPRO",
  "sector": null,
  "industry": null,
  "company_name": null,
  "price_min": 20,
  "price_max": 200,
  "ohlcv_available": false
}
```

### Root cause

This was **not** a faulty status aggregation:

- `custom_universe_store.get_status()` counts the persisted `sector` value and intentionally uses `OTHER` only when that field is empty.
- WIPRO’s authoritative `custom_universe_master` row had been overwritten by a later **partial** upsert. The upsert implementation applies defaults to omitted values, including `price_max=200` and `ohlcv_available=false`; omitted descriptive fields become `null`.
- The approved Phase 1D source payload already contained the correct WIPRO record: `sector=IT`, `price_max=500`, and `ohlcv_available=true`.

### Risk / diversification impact assessment

For WIPRO specifically, the live scan and Phase 20 risk gate fall back to the legacy NIFTY sector map when custom metadata is missing. That fallback maps WIPRO to `IT`, so the immediate WIPRO sector-cap calculation was not incorrectly treated as `OTHER`.

Nevertheless, the persisted custom-universe metadata is the authoritative source for the custom scan and status views. Missing metadata could produce an incorrect sector bucket for a future custom symbol that has no legacy-map fallback. The record was therefore corrected before the first session watch.

### Safe production repair performed

One authenticated call to the already-verified, token-protected admin route restored **only** WIPRO’s approved master record:

```text
POST /api/universe/custom/upsert
Response: {"success":true,"upserted":1}
```

Restored fields include:

| Field | Corrected value |
|---|---|
| `company_name` | Wipro Ltd |
| `sector` | IT |
| `industry` | IT Services |
| `price_min` / `price_max` | 20 / 500 |
| `ohlcv_available` | true |
| `last_ltp_source` | yfinance_close |
| `is_active` | true |

This call only updated `custom_universe_master` plus its append-only membership observation. It did **not** change trading settings, capital, the active universe, thresholds, scans, positions, trades, or broker order activity.

### Post-repair production proof

```text
GET /api/universe/custom/status

active_universe              = CUSTOM_LOW_PRICE_SECTOR
active_count                 = 23
price_filter                 = {min: 20, max: 500}
sector_counts                = {BANK: 9, INFRA: 13, IT: 1}
ohlcv_cache_hit_rate_pct     = 100
paper_trading_only           = true
no_live_broker_orders        = true
```

```text
GET /api/universe/custom/symbols

total_rows                   = 25
active_count                 = 23
inactive_symbols             = [IOB, UCOBANK]
forbidden_active             = []
WIPRO                        = {sector: IT, industry: IT Services,
                                price_min: 20, price_max: 500,
                                ohlcv_available: true}
```

**Sector-count outcome: RESOLVED.** The master-data correction fixes both the status display and the authoritative custom-universe metadata before the session watch.

---

## 3. Production Safety Baseline After Repair

| Check | Required value | Production value | Result |
|---|---|---|---|
| Initial capital | 100000 | 100000 | ✅ |
| Active universe | CUSTOM_LOW_PRICE_SECTOR | CUSTOM_LOW_PRICE_SECTOR | ✅ |
| Auto paper entries | false | false | ✅ |
| Bootstrap paper | false | false | ✅ |
| Auto paper exits | true | true | ✅ |
| Open positions | [] | [] | ✅ |
| Paper-only mode | true | true | ✅ |
| Live broker orders | disabled | `no_live_broker_orders=true` | ✅ |

No capital, universe, threshold, entry, bootstrap, or exit setting was changed during Phase 1G preparation.

---

## 4. Provider Health Before Session

`GET /api/live-data/health` returned:

```text
connection_status       = CONNECTED
provider                = Yahoo Finance (yfinance)
symbols_succeeded       = 3
stale_symbols           = []
avg_latency_ms          = 269.7
quality_summary         = {LIVE: 3, NEAR_LIVE: 0, STALE: 0, UNAVAILABLE: 0}
paper_execution_eligible= true
last_successful_fetch   = 2026-08-21T19:18:36Z
```

**Pre-session provider verdict: READY FOR OBSERVATION.** This is a three-symbol health probe only; it is not proof that the full 23-symbol custom scan has completed.

---

## 5. Trading-Activity Check

### Actions performed in this Phase 1G preparation

| Operation | Count | Trading effect |
|---|---:|---|
| Read-only production GET requests | Multiple | None |
| Authenticated WIPRO master-data upsert | 1 | None — metadata only |
| Scans triggered manually | 0 | None |
| Trade-entry routes called | 0 | None |
| Position-exit routes called | 0 | None |
| Broker order APIs called | 0 | None |
| Live orders placed | 0 | None |

### Ledger context

The durable ledger contains six **historic, closed** paper records dated 2026-08-18 through 2026-08-20, with exits completed no later than 2026-08-21 05:36 IST—before the 2026-08-21 ~17:58 IST Phase 1E universe switch.

There are no ledger records created after the Phase 1E switch, and `positions=[]` remains true. Therefore:

- No CUSTOM-universe AUTO trades were created during this preparation.
- No BOOTSTRAP_AUTO trades were created during this preparation.
- No positions were opened or closed during this preparation.
- No live orders or broker order APIs were used.

---

## 6. First-Scan Proof — Pending Monday Session

**Not yet observable.** The current time is Saturday, 2026-08-22 IST; no first post-switch regular NSE session has occurred.

After the first scan completes on Monday 2026-08-24 (check after 09:30 IST), record:

| Endpoint / field | Required outcome |
|---|---|
| `GET /api/live-data/summary` → `universe_mode` | CUSTOM_LOW_PRICE_SECTOR |
| `symbols_analysed` | 23 |
| `symbols_with_errors` | 0 |
| NIFTY_50 fallback | Absent |
| `GET /api/universe/custom/symbols` | 23 active; IOB/UCOBANK inactive; forbidden symbols absent |
| `GET /api/universe/custom/status` | BANK=9, INFRA=13, IT=1; price band 20–500 |
| `GET /api/phase20/settings` | capital=100000; entries=false; bootstrap=false |
| `GET /api/phase20/positions` | [] |
| `GET /api/live-data/health` | CONNECTED; no material stale-symbol issue |

---

## 7. EOD Proof — Pending Monday Session

At or after 15:20 IST on Monday 2026-08-24, verify:

| Endpoint | Required outcome |
|---|---|
| `GET /api/phase20/eod-status` | Route succeeds; no open positions; no false healthy result if EOD fails |
| `GET /api/phase20/eod-outcomes` | Route succeeds; no ERROR rows |
| `GET /api/phase20/positions` | [] |
| `GET /api/phase20/ledger` | No new AUTO or BOOTSTRAP_AUTO record for the custom-universe watch |

---

## 8. GO / NO-GO Recommendation

| Requirement | Status |
|---|---|
| Admin upsert route secured in production | ✅ Phase 1F verified |
| Correct custom-universe master metadata | ✅ WIPRO repaired; sector counts now 9/13/1 |
| Capital and active universe unchanged | ✅ |
| Auto entries and bootstrap disabled | ✅ |
| No open positions / no Phase 1G trading activity | ✅ |
| Provider health pre-session | ✅ CONNECTED |
| First custom-universe regular-session scan observed | ⏳ Monday 2026-08-24 |
| 23 symbols analysed with zero errors | ⏳ Monday 2026-08-24 |
| EOD route and outcomes verified | ⏳ Monday 2026-08-24 |

**Current recommendation: NO-GO.**  
Do **not** enable `auto_paper_entries` or bootstrap. The security and master-data prerequisites are now satisfied, but the required first-session scan and EOD evidence do not exist yet.

**Earliest possible future decision:** after the complete Monday 2026-08-24 watch, including EOD verification, and only with explicit operator approval.