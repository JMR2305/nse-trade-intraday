# APEXQUANT PHASE 1 — REVISED CAPITAL / UNIVERSE EXECUTION PLAN

**Date:** 2026-08-21  
**Status:** PLAN ONLY — no execution performed  
**Supersedes:** APEXQUANT_PHASE1_CAPITAL_UNIVERSE_LTIM_BRANCH_PLAN.md  

---

## SAFETY CONSTRAINTS — Held Throughout Phase 1

| Setting | Status | Verification |
|---|---|---|
| `auto_paper_entries` | `false` | Confirmed via `GET /api/phase20/settings` |
| `bootstrap_paper_enabled` | `false` | Confirmed via `GET /api/phase20/settings` |
| `auto_paper_exits` | `true` | Confirmed |
| Phase 20 executor / scheduler / exits / EOD | Untouched | No file edits in this plan |
| Phase 0C/0D safety code | Untouched | No file edits in this plan |
| Broker order APIs | Not called | Paper only |
| Production changes | Require operator approval | Execution is Phase 1C–1E only |

**Confirmation: no execution was performed during the production of this document.**

---

## 1. EXECUTIVE SUMMARY

The original Phase 1 plan is revised on three dimensions:

1. **Universe:** The proposed symbol list included high-price names (LTIM ₹4,000–₹6,000, PERSISTENT ₹5,000+, COFORGE ₹6,000+) that conflict with the low-price target. All prices are now verified live (2026-08-21) and candidates are separated by price band. A critical structural finding: **genuine liquid IT stocks on NSE are expensive** — at the strict ₹20–₹200 band, only WIPRO (₹180.8) qualifies. The operator must choose a price band before universe population.

2. **Execution separation:** Capital migration and universe switch are now fully separated into discrete phases (1C / 1D / 1E), each requiring its own operator approval. The branch produces only documentation and dev-environment work (1A / 1B).

3. **UI proof:** All five pages have been audited with file:line evidence. No UI file changes are required for Phase 1. The existing pages will reflect all changes automatically through canonical data sources.

---

## 2. CORRECTED LOW-PRICE UNIVERSE OPTIONS

### Price band options

| Band | Range | IT coverage | Infra coverage | Bank coverage | Total candidates |
|---|---|---|---|---|---|
| **Option A — Strict low-price** | ₹20–₹200 | Thin (WIPRO only) | Strong (9 names) | Strong (8 names) | ~18 |
| **Option B — Moderate** ✅ | ₹20–₹500 | Thin (WIPRO only + TANLA at ₹570 just outside) | Very strong (13 names) | Very strong (11 names) | ~25 |
| **Option C — Broad liquid** | ₹20–₹1,500 | Adequate (WIPRO + TANLA + RATEGAIN + HCLTECH) | Maximal | Maximal | ~30 |

### Analysis by option at ₹1,00,000 capital / ₹25,000 per-stock cap

**Option A (₹20–₹200)**  
- Pros: Purest low-price mandate. Maximum lot-size per trade (e.g. UCOBANK ₹25.7 → 972 shares at cap). High sensitivity to price moves in percentage terms.  
- Cons: IT sector is limited to WIPRO alone. Very low absolute-price stocks (UCOBANK ₹25, IOB ₹33) have wide bid-ask spreads and higher brokerage-per-rupee ratios. Universe is PSU-bank and infra-heavy, reducing diversity.

**Option B (₹20–₹500)** ✅ RECOMMENDED  
- Pros: 25 candidates across IT/Infra/Bank. Minimum 50 shares per trade at ₹500 average. Includes higher-quality private banks (FEDERALBNK ₹361, KTKBANK ₹328). Still excludes genuinely expensive IT stocks. Manageable scan universe.  
- Cons: IT coverage remains thin — WIPRO is the sole IT name unless band is extended. TANLA (₹570) is just outside the boundary.

**Option C (₹20–₹1,500)**  
- Pros: Adds TANLA (₹570 IT), RATEGAIN (₹990 IT), HCLTECH (₹1,302 IT). Genuine IT diversity.  
- Cons: At the top of the range (₹1,500), ₹25,000 cap allows only 16 shares — tight for intraday. HCLTECH and RATEGAIN are not "low price" by any normal definition.

### Structural finding: IT on NSE is expensive

At ₹20–₹200 and even ₹20–₹500, only one liquid IT name (WIPRO) qualifies. This is a characteristic of the NSE IT sector, not a data gap. Options:
- **Accept** Bank+Infra-heavy universe with WIPRO as sole IT; drop "IT" from the universe label.
- **Mixed band**: ₹20–₹200 for Bank/Infra, ₹20–₹1,500 for IT specifically. This can be encoded via the `price_min`/`price_max` fields in `custom_universe_master`.
- **Extend to ₹1,500**: Accept TANLA + RATEGAIN + HCLTECH as IT representatives.

**Operator decision required before Phase 1B:** Choose the price band (or mixed-band) approach.

---

## 3. RECOMMENDED PRICE BAND

**Recommendation: Option B (₹20–₹500)** with an explicit call-out that IT coverage is structurally thin.

If the operator wants at least 3 IT names, extend to Option C (₹20–₹1,500) or use the mixed-band approach. Either way, do not include LTIM (current price ₹4,000–₹6,000 range) in any version of a low-price universe.

---

## 4. CANDIDATE SYMBOL TABLE BY PRICE BAND

All prices verified via yfinance on 2026-08-21. Symbols with `NaN` had unavailable data — marked for manual verification before inclusion.

### Key for table columns
- **In NIFTY_50 master**: Symbol is in `config.SECTOR_MAP` → has verified Yahoo `.NS` and Kite symbol mappings in production data.
- **Needs verify**: Symbol not in current NIFTY_50 config. Yahoo symbol and Kite `instrument_token` must be verified before insertion into `custom_universe_master`.
- **LTP source**: yfinance (auto-available) or Kite LTP overlay (requires `instrument_token`).

---

### OPTION A — Strict Low-Price (₹20–₹200)

**IT Sector**

| Symbol | Company | Sector | LTP (2026-08-21) | Shares @ ₹25K cap | Intraday suitability | In NIFTY_50 master | Yahoo mapping | Kite mapping |
|---|---|---|---|---|---|---|---|---|
| WIPRO | Wipro Ltd | IT | ₹180.8 | 138 | ✅ Very high volume, F&O stock, tight spread | ✅ Yes | `WIPRO.NS` ✅ | ✅ Yes |

> **IT note:** WIPRO is the only qualifying IT name in the strict band. At ₹180.8, 138 shares per trade is adequate. This is a quality, liquid IT stock with F&O availability.

**Infra / PSU Sector**

| Symbol | Company | Sector | LTP (2026-08-21) | Shares @ ₹25K cap | Intraday suitability | In NIFTY_50 master | Yahoo mapping | Kite mapping |
|---|---|---|---|---|---|---|---|---|
| IRFC | Indian Railway Finance Corp | Infra Finance | ₹86.4 | 289 | ✅ High retail participation, large volumes post-listing | ❌ Needs verify | `IRFC.NS` ✅ | Needs verify |
| NBCC | NBCC India Ltd | Infra / Construction | ₹88.9 | 281 | ✅ PSU infra, good volumes, budget-cycle sensitivity | ❌ Needs verify | `NBCC.NS` ✅ | Needs verify |
| NMDC | NMDC Ltd | Mining / Infra | ₹84.6 | 295 | ✅ High volume, commodity-sensitive, F&O-eligible | ❌ Needs verify | `NMDC.NS` ✅ | Needs verify |
| IRCON | IRCON International | Infra / Construction | ₹124.7 | 200 | ✅ PSU infra, decent volumes | ❌ Needs verify | `IRCON.NS` ✅ | Needs verify |
| HUDCO | Housing & Urban Dev Corp | Infra Finance | ₹186.1 | 134 | ✅ Good retail participation since listing | ❌ Needs verify | `HUDCO.NS` ✅ | Needs verify |
| GAIL | GAIL India | Gas / Infra | ₹172.0 | 145 | ✅ F&O stock, high volume, gas-price sensitive | ❌ Needs verify | `GAIL.NS` ✅ | Needs verify |
| SAIL | Steel Authority of India | Steel / Infra | ₹173.5 | 144 | ✅ F&O stock, high volume, commodity-driven | ❌ Needs verify | `SAIL.NS` ✅ | Needs verify |
| MRPL | Mangalore Refinery (MRPL) | Refinery / Infra | ₹176.8 | 141 | ✅ HPCL subsidiary, decent volumes | ❌ Needs verify | `MRPL.NS` ✅ | Needs verify |

**Bank Sector**

| Symbol | Company | Sector | LTP (2026-08-21) | Shares @ ₹25K cap | Intraday suitability | In NIFTY_50 master | Yahoo mapping | Kite mapping |
|---|---|---|---|---|---|---|---|---|
| IDFCFIRSTB | IDFC First Bank | Private Bank | ₹86.8 | 288 | ✅ Very high volume, retail favourite, F&O stock | ❌ Needs verify | `IDFCFIRSTB.NS` ✅ | Needs verify |
| PNB | Punjab National Bank | PSU Bank | ₹116.6 | 214 | ✅ F&O stock, very high volume, widely tracked | ❌ Needs verify | `PNB.NS` ✅ | Needs verify |
| CANBK | Canara Bank | PSU Bank | ₹130.0 | 192 | ✅ F&O stock, high volume | ❌ Needs verify | `CANBK.NS` ✅ | Needs verify |
| BANKINDIA | Bank of India | PSU Bank | ₹142.8 | 175 | ✅ F&O stock, good volumes | ❌ Needs verify | `BANKINDIA.NS` ✅ | Needs verify |
| MAHABANK | Bank of Maharashtra | PSU Bank | ₹80.3 | 311 | ✅ Good retail volumes, government-banking sensitive | ❌ Needs verify | `MAHABANK.NS` ✅ | Needs verify |
| IOB | Indian Overseas Bank | PSU Bank | ₹33.0 | 757 | ⚠️ High share count but thin absolute spread; caution | ❌ Needs verify | `IOB.NS` ✅ | Needs verify |
| UCOBANK | UCO Bank | PSU Bank | ₹25.7 | 972 | ⚠️ Very high share count; wide effective spread; assess carefully | ❌ Needs verify | `UCOBANK.NS` ✅ | Needs verify |
| UNIONBANK | Union Bank of India | PSU Bank | ₹183.4 | 136 | ✅ F&O stock, solid volumes | ❌ Needs verify | `UNIONBANK.NS` ✅ | Needs verify |

> **Bank note on IOB and UCOBANK:** Both are within the strict price band but at very low absolute prices (₹25–₹33). A single paisa movement represents a 0.04%–0.12% move. While the share count per trade is high (700–970), the bid-ask spread in absolute terms can be meaningful for intraday exits. Recommend the operator assess intraday spread data before including.

**Option A total: ~17 symbols (1 IT, 8 Infra, 8 Bank)**

---

### OPTION B — Moderate (₹20–₹500) — All Option A symbols plus:

| Symbol | Company | Sector | LTP (2026-08-21) | Shares @ ₹25K cap | Intraday suitability | In NIFTY_50 master | Yahoo mapping | Kite mapping |
|---|---|---|---|---|---|---|---|---|
| RVNL | Rail Vikas Nigam | Infra | ₹225.3 | 110 | ✅ High retail participation, infrastructure-budget driven | ❌ Needs verify | `RVNL.NS` ✅ | Needs verify |
| BANKBARODA | Bank of Baroda | PSU Bank | ₹247.0 | 101 | ✅ F&O stock, high volume, well-covered | ❌ Needs verify | `BANKBARODA.NS` ✅ | Needs verify |
| RECLTD | REC Ltd | Infra Finance | ₹326.6 | 76 | ✅ F&O stock, infrastructure lending, high volume | ❌ Needs verify | `RECLTD.NS` ✅ | Needs verify |
| NTPC | NTPC Ltd | Power / Infra | ₹340.0 | 73 | ✅ F&O stock, very high volume, power-sector proxy | ❌ Needs verify | `NTPC.NS` ✅ | Needs verify |
| KTKBANK | Karnataka Bank | Private Bank | ₹328.3 | 76 | ✅ Decent volumes, South India private bank | ❌ Needs verify | `KTKBANK.NS` ✅ | Needs verify |
| FEDERALBNK | Federal Bank | Private Bank | ₹361.0 | 69 | ✅ F&O stock, high quality private bank, solid volumes | ❌ Needs verify | `FEDERALBNK.NS` ✅ | Needs verify |
| PFC | Power Finance Corp | Infra Finance | ₹363.0 | 68 | ✅ F&O stock, power sector lending, high volume | ❌ Needs verify | `PFC.NS` ✅ | Needs verify |
| COALINDIA | Coal India | Mining / Infra | ₹405.2 | 61 | ✅ NIFTY_50-adjacent, very high volume, dividend play | ❌ Needs verify | `COALINDIA.NS` ✅ | Needs verify |

**Option B total: ~25 symbols (1 IT, 13 Infra, 11 Bank)**

---

### OPTION C — Broad Liquid (₹20–₹1,500) — All Option B symbols plus:

| Symbol | Company | Sector | LTP (2026-08-21) | Shares @ ₹25K cap | Intraday suitability | In NIFTY_50 master | Yahoo mapping | Kite mapping |
|---|---|---|---|---|---|---|---|---|
| TANLA | Tanla Platforms | IT (Cloud Comms) | ₹570.5 | 43 | ✅ Mid-cap IT, good liquidity, cloud messaging | ❌ Needs verify | `TANLA.NS` ✅ | Needs verify |
| RATEGAIN | RateGain Travel Tech | IT (Travel Tech) | ₹990.0 | 25 | ⚠️ Adequate volume; smaller-cap; spread caution at 25 shares | ❌ Needs verify | `RATEGAIN.NS` ✅ | Needs verify |
| HCLTECH | HCL Technologies | IT | ₹1,302.5 | 19 | ⚠️ Very high quality but 19 shares per trade is very thin for intraday | ✅ Yes | `HCLTECH.NS` ✅ | ✅ Yes |

> **Broad IT note:** HCLTECH at 19 shares per ₹25,000 cap is borderline workable for intraday. A ₹10 move (0.77%) yields ₹190 gross on 19 shares, which after charges is marginal. RATEGAIN at 25 shares is only slightly better. TANLA at 43 shares is the strongest IT candidate in this range.

> **LTIM:** Current price ₹4,000–₹6,000. **Not included in any band.** Even at the ₹25,000 per-stock cap, LTIM allows only 4–6 shares per trade — unsuitable for intraday execution at ₹1,00,000 capital.

**Option C total: ~28 symbols (4 IT, 13 Infra, 11 Bank)**

---

## 5. CAPITAL MIGRATION STANDALONE CHECKLIST

This checklist is for Phase 1C (production-only, operator-approved). Each step must be completed and logged before the next.

**Pre-migration verification (run first — halt if any check fails):**

```
Step 1. GET /api/phase20/settings
        → Confirm auto_paper_entries = false
        → HALT if true

Step 2. GET /api/phase20/settings
        → Confirm bootstrap_paper_enabled = false
        → HALT if true

Step 3. GET /api/phase20/positions
        → Confirm positions = []
        → HALT if any position exists

Step 4. GET /api/phase20/capital-migration/status
        → Confirm exit_pending_count = 0
        → HALT if exit_pending_count > 0

Step 5. Capture pre-migration baseline (log all fields):
        GET /api/phase20/settings
        Record: initial_capital, per_stock_exposure_cap, risk_per_trade,
                daily_loss_limit, circuit_breaker_daily_loss_limit,
                config_hash, updated_at
```

**Migration execution:**

```
Step 6. POST /api/phase20/capital-migration
        Body: {
          "confirmation": "I confirm there are no open or exit-pending paper positions and approve rebasing paper capital to ₹100,000."
        }
        → Confirm response: { "status": "APPLIED", "success": true }
        → HALT on any error
```

**Post-migration verification:**

```
Step 7. Capture post-migration state:
        GET /api/phase20/settings
        Record: initial_capital, per_stock_exposure_cap, risk_per_trade,
                daily_loss_limit, circuit_breaker_daily_loss_limit,
                config_hash, updated_at

Step 8. Verify initial_capital = 100000
        → HALT if still 500000

Step 9. Verify derived risk limits at ₹1,00,000:
        - per_stock_exposure_cap = 25000   (25% of 100000)
        - risk_per_trade         = 1000    (1% of 100000)
        - daily_loss_limit       = 3000    (3% of 100000)
        - circuit_breaker_daily_loss_limit = 3000
        → HALT on any mismatch

Step 10. GET /api/phase20/capital-migration/status
         → Confirm status = "ALREADY_APPLIED"
         → Confirm current_capital = 100000
         → Confirm closed_history.preserved = true
         → Confirm closed trade count unchanged from pre-migration count (was 6)
         → HALT if closed_trade_count differs

Step 11. Confirm no live orders:
         GET /api/phase20/positions
         → Confirm positions = [] (paper only — no broker API called)
         GET /api/phase20/settings
         → Confirm auto_paper_entries still = false
         → Confirm bootstrap_paper_enabled still = false
```

**All 11 steps must pass before migration is considered complete.**

---

## 6. PRODUCTION VS DEV ACTION SEPARATION

### Phase 1A — Research and validation (this document)
**Environment:** None — documentation only  
**Changes:** None — no DB, no files, no settings  
**Operator approval:** Required to proceed to 1B  

| Deliverable | Status |
|---|---|
| Revised universe candidate list with live prices | ✅ Section 4 |
| Price band options with pros/cons | ✅ Section 3 |
| Capital migration standalone checklist | ✅ Section 5 |
| UI proof with file:line evidence | ✅ Section 7 |
| Test plan | ✅ Section 8 |

---

### Phase 1B — Dev-only universe population
**Environment:** Dev database only (localhost:8080)  
**Changes:** DB writes to dev `custom_universe_master` and `custom_universe_membership_history`  
**Code changes:** None  
**Operator approval required before starting:** Yes (price band choice)

| Step | Action | Type |
|---|---|---|
| 1B-1 | Choose price band (A / B / C / mixed) | Operator decision |
| 1B-2 | Verify Kite `instrument_token` for all "Needs verify" symbols | Dev verification |
| 1B-3 | Call `POST /api/universe/custom/upsert` or `upsert_symbols()` on dev DB | Dev DB write |
| 1B-4 | `GET /api/universe/custom/symbols` — confirm count and all `is_active=true` | Dev verification |
| 1B-5 | `GET /api/universe/custom/status` — confirm sector counts | Dev verification |
| 1B-6 | Run test suite (Section 8) on dev | Dev test |
| 1B-7 | Do NOT switch dev `active_intraday_universe` until tests pass | Guard |

---

### Phase 1C — Production capital migration
**Environment:** Production only (`nse-trade-intraday.replit.app`)  
**Changes:** `phase20_settings.initial_capital` 500000 → 100000; KV sync; event emit  
**Code changes:** None  
**Operator approval required before starting:** Yes — explicit operator sign-off

Execute the 11-step checklist in Section 5. No other Phase 1 action may proceed concurrently.

---

### Phase 1D — Production universe population
**Environment:** Production DB only  
**Changes:** `custom_universe_master` table populated (currently empty); `custom_universe_membership_history` snapshot  
**Code changes:** None  
**Operator approval required before starting:** Yes — requires Phase 1C complete, plus operator symbol approval  
**Prerequisite:** 1B completed and verified on dev; exact symbol list operator-approved

| Step | Action | Type |
|---|---|---|
| 1D-1 | Confirm Phase 1C ALREADY_APPLIED | Prerequisite check |
| 1D-2 | Call `POST /api/universe/custom/upsert` on prod with approved symbol list | Production DB write |
| 1D-3 | `GET /api/universe/custom/symbols` on prod — confirm count | Production verification |
| 1D-4 | Do NOT change `active_intraday_universe` yet | Guard |

---

### Phase 1E — Production universe switch
**Environment:** Production settings only  
**Changes:** `phase20_settings.active_intraday_universe`: NIFTY_50 → CUSTOM_LOW_PRICE_SECTOR  
**Code changes:** None  
**Operator approval required before starting:** Yes — requires Phase 1D verified  

| Step | Action | Type |
|---|---|---|
| 1E-1 | Confirm 1D symbols queryable and count matches expectation | Prerequisite check |
| 1E-2 | `PUT /api/phase20/settings` `{ "active_intraday_universe": "CUSTOM_LOW_PRICE_SECTOR" }` | Production setting change |
| 1E-3 | `GET /api/phase20/settings` — confirm `active_intraday_universe = CUSTOM_LOW_PRICE_SECTOR` | Verification |
| 1E-4 | Mission Control: confirm Universe selector reflects new value | UI verification |
| 1E-5 | Wait for next scheduled scan — confirm scan uses custom symbols | Operational verification |
| 1E-6 | Confirm `auto_paper_entries` still `false` after setting change | Safety check |

---

## 7. UI PROOF — PAGE BY PAGE

All findings are code-verified with file and line references.

### 7.1 AI Paper Trader (`AIPaperTraderPage.tsx`)

| What operator sees | Source endpoint | Field | Updates automatically? | Notes |
|---|---|---|---|---|
| "Starting Capital" KPI (S12 section) | `/phase11/portfolio` | `data.starting_capital` | ✅ Yes | Reflects ₹1,00,000 after 1C |
| "Starting Capital" in capital config panel | `/phase11/capital/config` | `cfg.starting_capital` | ✅ Yes | L3758-3782 |
| "Daily Capital" chip in Session header | `/phase20/settings` (fallback: `/phase20/capital-migration/status`) | `settings.initial_capital` or `current_capital` | ✅ Yes | L866-868 |
| Capital migration button shows "→ ₹100K" | Local constant | `configuredCapital !== 100_000` check | — | L969-971: comparison constant, not a setting |
| "Auto Entries" ON/OFF card | `/phase11/session/status` | `session.auto_paper_entries` | ✅ Yes | L803-817 — shows current false state |
| Bootstrap badge "DISABLED" | `/phase20/bootstrap-status` | `bootstrap_paper_enabled` | ✅ Yes | L1512-1524 — already shows DISABLED |
| Active universe name | **NOT SHOWN** | — | — | Only WATCH symbol count visible (L1745-1752). No universe label gap identified as safety risk. |

**Verdict: Capital, auto-entries, and bootstrap all show correctly from canonical sources. No UI changes required for Phase 1.**

---

### 7.2 Mission Control (`MissionControl.tsx`)

| What operator sees | Source endpoint | Field | Updates automatically? | Notes |
|---|---|---|---|---|
| Portfolio Value / Cash / Invested | `/portfolio/snapshot` | `equity`, `cash`, `invested_value` | ✅ Yes | L2043-2125; no hardcoded capital |
| "Universe: N symbols" chip | Scan status | `latest_scan.universe_size` / `progress.symbols_total` | ✅ Yes | L666-713 — shows 50 on NIFTY_50, custom count after 1E |
| Universe mode selector | `/phase20/settings` | `active_intraday_universe` | ✅ Yes | L2403-2447; shows current NIFTY_50 |
| Low-price universe card (custom symbols, sector counts, active/excluded counts) | `/universe/custom/status` + `/universe/custom/symbols` | `active_count`, `sector_counts`, per-symbol list | ✅ Yes (auto-mounts on CUSTOM_LOW_PRICE_SECTOR) | L2326-2393; only visible after 1E |
| BootstrapStatusBanner (entries status) | `/phase20/bootstrap-status` | `bootstrap_paper_enabled`, `auto_paper_entries` | ✅ Yes | L1783-1792; **renders blank when both are false** — correct, not a bug |

**Verdict: Capital, universe, and status all update from canonical sources. The BootstrapStatusBanner being invisible when both disabled is intentional — the page shows the universe selector and symbol count without it. No UI changes required.**

---

### 7.3 Mobile Dashboard (`artifacts/trading-mobile/app/(tabs)/index.tsx`)

| What operator sees | Source endpoint | Field | Updates automatically? | Notes |
|---|---|---|---|---|
| Portfolio value / Cash / Invested | `/portfolio` (OpenAPI generated) | `total_value`, `cash`, `invested_value` | ✅ Yes | L207-255; dynamic, no hardcoded amounts |
| "Auto Entries" status tile | `/phase20/settings` | `auto_paper_entries` | ✅ Yes | L286-292; shows ON/OFF |
| Active universe | **NOT SHOWN** | — | — | Not surfaced on mobile dashboard |
| Bootstrap status | **NOT SHOWN** | — | — | Not surfaced on mobile dashboard |
| Starting capital | **NOT SHOWN** | — | — | Portfolio value shown, not starting capital |

**Verdict: Capital reflected as portfolio value. Auto-entries shown as status tile. Universe and bootstrap not displayed on mobile — acceptable for Phase 1. Operators verifying universe/bootstrap must use web dashboard. No UI changes required.**

---

### 7.4 Live Data Health (`LiveDataHealth.tsx`)

| What operator sees | Source endpoint | Field | Updates automatically? | Notes |
|---|---|---|---|---|
| Universe size | `/live-data/scan` | `summary.universe_size` | ✅ Yes | L483-485; shows "N symbols"; reflects custom count after 1E |
| Universe mode name | **NOT SHOWN** | — | — | Size shown but not mode name (NIFTY_50 vs CUSTOM) |
| Capital | **NOT SHOWN** | — | — | Not on this page (health metrics only) |
| Auto entries / bootstrap | **NOT SHOWN** | — | — | `paper_execution_eligible` flag shown (different from auto_entries status) |

**Verdict: Universe size updates automatically post-1E. Mode name not displayed — not a safety concern for this page. No UI changes required.**

---

### 7.5 Portfolio / Risk Pages

| Page | Capital display | Source | Universe shown | Auto entries shown | Notes |
|---|---|---|---|---|---|
| `PortfolioPerformance.tsx` | Portfolio value, `total_portfolio_value`, `initial_capital` | `/portfolio-performance/summary` | ❌ No | ❌ No | `initial_capital` field from performance API — updates after 1C |
| `RiskValidation.tsx` | `total_value`, `cash_available`, `invested_capital` | `/risk-validation/portfolio` | ❌ No | ❌ No | Dynamic from API |
| `RiskOptimisation.tsx` | Derived values only (allocation ratios, position sizes) | `/risk-optimisation/capital` | ❌ No | ❌ No | No absolute capital; no universe |

**Verdict: All capital values are dynamic from canonical API endpoints. No hardcoded capital constants found on any of these pages. Universe and auto-entries are not surfaced — no safety gap for Phase 1. No UI changes required.**

---

### UI Proof Summary

**All five pages source capital, universe, and entries-status from canonical API endpoints. No hardcoded ₹5,00,000 or ₹1,00,000 values exist (the ₹1,00,000 on AIPaperTraderPage L969 is a comparison literal for the migration button, not a setting). Zero UI file changes are required for Phase 1.**

---

## 8. TESTS AND VERIFICATION

### 8.1 Tests to create on branch (Phase 1B)

File: `artifacts/api-server/src/python/tests/unit/test_custom_universe_store.py`

No test file currently exists. The following tests must be written before any dev population:

**Test 1 — Upsert idempotency**
```python
# Insert same symbol twice; verify row count = 1 and latest values applied.
# Uses isolated test DB.
```

**Test 2 — Active-only filtering**
```python
# Insert 3 symbols: 2 is_active=True, 1 is_active=False.
# get_active_symbols() must return exactly the 2 active symbols.
# get_all_symbols() must return all 3.
```

**Test 3 — Membership history append-only snapshot**
```python
# Insert symbol set at time T1. Insert updated set at T2.
# get_historical_universe_resolution(T1.date) must return T1 set.
# get_historical_universe_resolution(T2.date) must return T2 set.
# Neither write may delete any historical row.
```

**Test 4 — CUSTOM_LOW_PRICE_SECTOR scan uses only custom symbols**
```python
# Set active_intraday_universe = CUSTOM_LOW_PRICE_SECTOR.
# Call scan universe-resolution function.
# Assert returned symbols == get_active_symbols() (not config.NIFTY_50).
```

**Test 5 — Empty custom universe blocks scan safely**
```python
# Truncate custom_universe_master.
# Attempt to start scan under CUSTOM_LOW_PRICE_SECTOR.
# Assert scan returns an error / empty-universe guard, does not scan NIFTY_50 silently.
```

**Test 6 — Invalid Kite/yfinance mapping is reported**
```python
# Insert symbol with kite_symbol=None and ohlcv_available=False.
# Call get_active_symbol_metadata().
# Assert the row is returned with ohlcv_available=False and the scan skips it with a logged warning (not silent use).
```

**Test 7 — Phase 0C safety suite passes after Phase 1 changes**
```bash
# Run before and after any Phase 1 code changes (expected: no changes, still passes).
python3 -m pytest tests/unit/test_phase0c_safety_fixes.py -v
# Expected: 22 passed, 0 failed
```

### 8.2 Existing tests to re-run (no changes expected)

```bash
python3 -m pytest tests/unit/test_phase0c_safety_fixes.py -v        # 22 tests
python3 -m pytest tests/unit/test_paper_capital_migration.py -v     # existing migration tests
python3 -m pytest tests/ -q --ignore=tests/integration -x           # full unit suite
```

### 8.3 Manual verification sequence (post 1C/1D/1E)

```bash
# After 1C:
curl https://nse-trade-intraday.replit.app/api/phase20/capital-migration/status | python3 -m json.tool
# Expect: status=ALREADY_APPLIED, current_capital=100000

# After 1D:
curl https://nse-trade-intraday.replit.app/api/universe/custom/symbols | python3 -m json.tool
# Expect: N symbols, all is_active=true

# After 1E:
curl https://nse-trade-intraday.replit.app/api/phase20/settings | python3 -m json.tool
# Expect: active_intraday_universe=CUSTOM_LOW_PRICE_SECTOR
```

---

## 9. ROLLBACK PLAN

### Capital rollback (1C undo)

The capital migration is designed to be idempotent but not auto-reversible. If rollback to ₹5,00,000 is required after 1C:

```bash
# No open positions needed (verify first):
GET /api/phase20/positions → positions must be []

# Direct settings patch:
PUT /api/phase20/settings
{ "patch": { "initial_capital": 500000 } }

# Verify:
GET /api/phase20/settings → initial_capital = 500000
```

Closed trade history is not affected in either direction. The migration dedup key (`paper_capital_migration:target:100000:v1`) will still show `ALREADY_APPLIED` but the settings row overrides it.

### Universe rollback (1E undo)

```bash
PUT /api/phase20/settings
{ "patch": { "active_intraday_universe": "NIFTY_50" } }
```

`custom_universe_master` rows are preserved — the table is never deleted on revert. Re-enabling the custom universe later requires only repeating 1E.

### Universe population rollback (1D undo)

```sql
-- Mark all custom universe symbols inactive (soft delete — preserves history)
UPDATE custom_universe_master SET is_active = FALSE;
-- Or hard delete (loses history):
TRUNCATE custom_universe_master;
```

### Replit checkpoint rollback

Phase 1 involves no code changes — checkpoint rollback would not undo DB writes. Use the API-level rollback steps above for all Phase 1 DB actions.

---

## 10. OPERATOR DECISIONS REQUIRED

The following decisions must be made before any Phase 1 execution begins.

| # | Decision | Options | Phase blocked on this |
|---|---|---|---|
| D1 | Price band for custom universe | A (₹20–₹200) / B (₹20–₹500 recommended) / C (₹20–₹1,500) / Mixed (wider band for IT) | Phase 1B, 1D, 1E |
| D2 | IT coverage approach | Accept WIPRO-only / extend band for IT only / include TANLA+HCLTECH via broad band | Phase 1B, 1D, 1E |
| D3 | Include IOB (₹33) and UCOBANK (₹25.7)? | Include (high share count, thin spread risk) / Exclude (conservative) | Phase 1B, 1D |
| D4 | Approve capital migration ₹5L → ₹1L | Approve / Defer | Phase 1C |
| D5 | Confirm approved symbol list (operator signs off specific symbols) | Review candidate table in Section 4 | Phase 1B, 1D |

---

## 11. CONFIRMATION: NO EXECUTION PERFORMED

> This document is a plan only.  
> No capital migration has been performed.  
> No custom universe table has been populated.  
> No active universe setting has been changed.  
> No Phase 20 safety file has been modified.  
> No file in the codebase has been changed.

---

## 12. CONFIRMATION: AUTO ENTRIES AND BOOTSTRAP REMAIN DISABLED

| Setting | Value (confirmed live 2026-08-21) |
|---|---|
| `auto_paper_entries` | `false` |
| `bootstrap_paper_enabled` | `false` |
| `auto_paper_entries_confirmed_at` | `null` |
| `auto_paper_exits` | `true` (exits-only continues) |

These settings are unchanged by any action described in this plan. Capital migration explicitly checks and pauses entries during execution. Universe changes do not touch entry logic.

---

## 13. CONFIRMATION: NO LIVE ORDERS

No step in this plan calls a broker order API. All operations are:
- DB row reads/writes (settings, universe master)
- KV key updates (Phase 11 capital keys)
- Pipeline event emits (CAPITAL_REBASE — internal only)
- `GET` / `PUT` calls to the paper-trading management API

Paper only. Zero broker API calls.
