# APEXQUANT PHASE 1 — CAPITAL / UNIVERSE / LTIM BRANCH PLAN

**Date:** 2026-08-21  
**Controlling context:** Phase 0D production safety build accepted  
**Branch:** Separate branch from main — no production deployment until operator approval  
**Status:** Plan only — no code or DB mutations in this document

---

## SAFETY CONSTRAINTS — Held Throughout Phase 1

| Constraint | Enforcement |
|---|---|
| auto_paper_entries=false | Phase 0C guard — unchanged |
| bootstrap_paper_enabled=false | Settings DB — unchanged |
| Phase 0C/0D safety code untouched | Capital/universe/LTIM changes touch zero Phase 20 executor/scheduler/exits files |
| No broker order APIs | Paper only — confirmed |
| No production deployment without operator approval | This plan produces branch work only |

---

## 1. CURRENT PRODUCTION BASELINE

All values confirmed via live production API at 2026-08-21T09:10Z.

| Parameter | Production Value | Dev Value |
|---|---|---|
| `initial_capital` | ₹5,00,000 | ₹1,00,000 |
| `active_intraday_universe` | `NIFTY_50` (50 symbols) | `NIFTY_50` |
| `config_hash` | `81df262bfdbdaaf5` | `cced4e9be73e79cd` |
| `auto_paper_entries` | `false` | `false` |
| `bootstrap_paper_enabled` | `false` | `false` |
| `auto_paper_exits` | `true` | `true` |
| Capital migration status | `CONFIRMATION_REQUIRED` | `ALREADY_APPLIED` |
| Open positions | 0 | 0 |
| Closed trades | 6 (realized P&L: −₹278.74) | 4 (realized P&L: ₹0) |
| LTIM in active universe | No (removed from config.NIFTY_50) | No |
| Custom universe table populated | Unknown (endpoint returned empty) | Empty |

**Derived limits at current production capital (₹5,00,000):**

| Limit | At ₹5,00,000 | At ₹1,00,000 |
|---|---|---|
| Per-stock exposure cap (25%) | ₹1,25,000 | ₹25,000 |
| Sector exposure cap (40%) | ₹2,00,000 | ₹40,000 |
| Portfolio deployed cap (80%) | ₹4,00,000 | ₹80,000 |
| Risk per trade (1%) | ₹5,000 | ₹1,000 |
| Daily loss limit (3%) | ₹15,000 | ₹3,000 |
| Circuit breaker loss limit (3%) | ₹15,000 | ₹3,000 |
| Bootstrap max order value | ₹15,000 | ₹15,000 (fixed, not %-based) |

---

## 2. CAPITAL OPTIONS AND RECOMMENDATION

### Background

The migration endpoint already exists (`POST /api/phase20/capital-migration`), is tested, and is armed on production with status `CONFIRMATION_REQUIRED`. Dev has already applied it (`ALREADY_APPLIED`). The machinery is built — this is a single operator-confirmed DB write, not a code change.

### Option A — Keep ₹5,00,000

**What changes:** Nothing.  
**Pros:** No action required; no risk during Phase 1 branch work.  
**Cons:**  
- Production capital is 5× the intended value, making per-trade risk and exposure caps larger than designed  
- Per-stock cap of ₹1,25,000 allows outsized concentration in a low-liquidity custom universe stock  
- Risk per trade of ₹5,000 vs the designed ₹1,000 makes paper P&L numbers unrepresentative of the target operating mode  
- Dev and production operate at different capital scales, making direct comparison of any analytics misleading  

### Option B — Migrate to ₹1,00,000 ✅ RECOMMENDED

**What changes:** One DB row update (`phase20_settings.initial_capital` 500000 → 100000) and associated KV sync.  
**Mechanism:** Existing `POST /api/phase20/capital-migration` with operator confirmation text:  
```
I confirm there are no open or exit-pending paper positions and approve rebasing paper capital to ₹100,000.
```
**Prerequisites already met on production:**
- `open_count = 0` ✅
- `exit_pending_count = 0` ✅
- `auto_paper_entries = false` ✅
- Migration key `paper_capital_migration:target:100000:v1` dedupes the operation (idempotent)

**What the migration does (code-proven):**
1. Acquires entry admission lock (blocks concurrent entry checks)
2. Verifies 0 open/exit-pending positions in DB
3. Updates `phase20_settings.initial_capital` to 100000
4. Syncs legacy portfolio cash via `_sync_legacy_portfolio_locked()`
5. Syncs Phase 11 KV keys (`phase11_starting_capital`, `phase11_topup_target`) to 100000
6. Records migration status in `paper_capital_migration_status` table
7. Emits `CAPITAL_REBASE` pipeline event
8. Releases admission lock

**What the migration does NOT do:**
- Does not touch any Phase 0C/0D safety code
- Does not enable entries or bootstrap
- Does not call broker APIs
- Does not modify closed trade history (6 trades, −₹278.74 P&L — preserved)

**Pros:**
- Dev/prod parity — both operate at ₹1,00,000
- Risk limits sized correctly for the custom universe target
- All analytics, bootstrap sizing, and circuit breakers calibrated for the designed scale  

**Recommendation:** Execute Option B on the branch, deploy, then run with operator confirmation. This is a single API call with no code changes required.

---

## 3. UNIVERSE OPTIONS AND RECOMMENDATION

### Background

The custom universe infrastructure already exists:
- Table `custom_universe_master` (schema: `symbol TEXT PRIMARY KEY`, `yahoo_symbol`, `kite_symbol`, `instrument_token`, `sector`, `sub_sector`, `price_band`, `is_active`, `added_at`, `notes`)
- Table `custom_universe_membership_history` (append-only snapshots for no-look-ahead backtests)
- Route `POST /api/universe/custom/refresh` — triggers scan with custom universe symbols
- Route `GET /api/universe/custom/status` — Mission Control custom universe status card
- Route `GET /api/universe/custom/symbols` — returns active symbols list
- UI: `MissionControl.tsx` has `UniverseModeControl` component with `CUSTOM_LOW_PRICE_SECTOR` option and a Refresh button
- `InvestigationCenter.tsx:445` maps `universe === "custom_low_price_sector"` → `universe_mode: "CUSTOM_LOW_PRICE_SECTOR"`

The infrastructure is built. **The `custom_universe_master` table is currently empty on production.**

### Option A — Stay on NIFTY_50

**What changes:** Nothing.  
**Pros:** No risk; no DB population required.  
**Cons:**  
- NIFTY_50 includes many high-price blue-chips (RELIANCE >₹1,200, TCS >₹3,500) where ₹1,00,000 capital allows very few shares per trade  
- The stated target for this research platform is low-price IT/Infra/Bank names — NIFTY_50 is not that universe  
- At ₹1,00,000, a 25% per-stock cap (₹25,000) cannot meaningfully buy a round lot of high-price NIFTY_50 names  

### Option B — Switch to Custom Low-Price IT/Infra/Bank Universe ✅ RECOMMENDED

**Two sub-steps:**

#### Sub-step B1 — Populate `custom_universe_master` (DB write, no code change)

Proposed initial universe (low-price IT/Infra/Bank names, typically <₹1,500 per share at time of writing, allowing ≥16 shares at ₹25,000 per-stock cap):

**IT:**

| Symbol | Company | Sector |
|---|---|---|
| WIPRO | Wipro Ltd | IT |
| TECHM | Tech Mahindra | IT |
| MPHASIS | Mphasis | IT |
| LTIM | LTIMindtree | IT |
| PERSISTENT | Persistent Systems | IT |
| COFORGE | Coforge | IT |
| KPITTECH | KPIT Technologies | IT |

**Infra/Capital Goods:**

| Symbol | Company | Sector |
|---|---|---|
| LT | Larsen & Toubro | INFRA |
| ABFRL | Aditya Birla Fashion | INFRA |
| BHEL | BHEL | INFRA |
| IRFC | IRFC | INFRA |
| RVNL | Rail Vikas Nigam | INFRA |

**Bank/Finance:**

| Symbol | Company | Sector |
|---|---|---|
| SBIN | State Bank of India | BANK |
| BANKBARODA | Bank of Baroda | BANK |
| CANBK | Canara Bank | BANK |
| FEDERALBNK | Federal Bank | BANK |
| IDFCFIRSTB | IDFC First Bank | BANK |
| PNB | Punjab National Bank | BANK |

> **Note on LTIM:** LTIM was removed from the NIFTY_50 config but it is appropriate for the custom IT universe (LTIMindtree is mid-cap IT, typically ₹4,000–₹6,000 range). Operator should verify price is within target band before including. See Section 4.

> **Operator decision required:** Confirm exact symbol list and price-band cutoff before populating. The plan proposes the above as a starting candidate list.

#### Sub-step B2 — Change active universe setting (DB write, no code change)

After custom universe is populated and verified:
```
PUT /api/phase20/settings
{ "patch": { "active_intraday_universe": "CUSTOM_LOW_PRICE_SECTOR" } }
```

**What this does:** All subsequent scan cycles use `get_active_symbols()` from `custom_universe_master` instead of `config.NIFTY_50`.

**What this does NOT do:**
- Does not enable entries or bootstrap
- Does not touch Phase 0C/0D safety code
- Does not modify existing closed trade history (trades already recorded against NIFTY_50 symbols are unaffected)

**Custom universe population method:** `POST /api/universe/custom/upsert` or direct DB insert via `custom_universe_store.upsert_symbols()`. The `upsert_symbols` function is idempotent (ON CONFLICT DO UPDATE).

---

## 4. LTIM HANDLING RECOMMENDATION

### Current status

| Check | Result |
|---|---|
| `LTIM` in `config.NIFTY_50` | **No** — confirmed `LTIM in NIFTY_50: False` |
| `config.SECTOR_MAP["IT"]` | `['TCS', 'INFY', 'WIPRO', 'HCLTECH', 'TECHM']` — LTIM absent |
| `nifty50_company_master_store.bootstrap_from_config()` | Documents: "rows no longer in the configured universe (e.g. LTIM after it left the index) are retained for history but marked `is_active = FALSE`" |
| Any route or scan that would pick LTIM from NIFTY_50 | No — LTIM is not in `config.NIFTY_50` |

### What happened historically

LTIM left the NIFTY_50 index at some point before the current config. The `nifty50_company_master_store` was designed to handle exactly this: `bootstrap_from_config()` deactivates (`is_active = FALSE`) any DB row for a symbol no longer in `config.SECTOR_MAP`, preserving historical records.

### Recommended action: None required for NIFTY_50 mode

LTIM is already not in the active NIFTY_50 scan universe. No scan, no entry, no signal will be generated for LTIM while `active_intraday_universe = NIFTY_50`. Historical company master rows for LTIM (if any) are already marked `is_active = FALSE`.

### If switching to custom universe (Option B above)

LTIM *can* be added to `custom_universe_master` explicitly, since:
- The custom universe is operator-curated — it is not bound to NIFTY_50 membership
- LTIMindtree is a valid IT name for research purposes
- The `custom_universe_master` table is independent of `nifty50_company_master`

**Recommendation:** Include LTIM in the custom universe candidate list if its current price falls within the operator-approved price band. Verify price before committing. This is a DB-only operation; no code changes.

---

## 5. UI IMPACT

### Capital display

| Page | Field | Source | Impact of ₹1L migration |
|---|---|---|---|
| `AIPaperTraderPage.tsx` S12 | "Starting Capital" | `phase11/capital/config` → `starting_capital` | Updates to ₹1,00,000 after migration |
| `AIPaperTraderPage.tsx` header | `p20Settings?.initial_capital` | `phase20/settings` | Updates automatically |
| `Phase11PortfolioPage.tsx` | `capital_mode_label`, `starting_capital` | `phase11/capital/config` | Updates automatically |
| `AIInvestigationCentre.tsx` | `starting_capital` | replay endpoint | Updates on next replay |
| `CommandCenter.tsx` | Phase 11 snapshot | `phase11/snapshot` | Updates automatically |

All capital displays read from the canonical source (`phase20/settings.initial_capital` or `phase11/capital/config` which reads the same KV). No UI file changes required.

### Universe display

| Page | Field | Impact of custom universe switch |
|---|---|---|
| `MissionControl.tsx` `UniverseModeControl` | Active universe selector | Reflects new `active_intraday_universe` value immediately |
| `MissionControl.tsx` scan grid | Symbol chips | Shows custom universe symbols on next scan |
| `InvestigationCenter.tsx` | `universe_mode` flag | Routes to `CUSTOM_LOW_PRICE_SECTOR` path when switched |
| `ResearchReport.tsx` | `equal_weight_universe_pct` benchmark | Computes against active universe symbols |

No UI file changes required. The Mission Control universe selector already has the `CUSTOM_LOW_PRICE_SECTOR` option wired. The universe change is a settings + DB write only.

---

## 6. DB / TABLE IMPACT

| Table | Change | Risk |
|---|---|---|
| `phase20_settings` | `initial_capital`: 500000 → 100000 (capital migration only) | Low — single row update, migration is guarded and idempotent |
| `paper_capital_migration_status` | New row recording the migration event | Low — append-only |
| `phase20_kv_store` | `phase11_starting_capital`, `phase11_topup_target` updated to 100000 | Low — KV update only |
| `custom_universe_master` | Populated with ~20 symbols (currently empty) | Low — upsert, idempotent |
| `custom_universe_membership_history` | One snapshot row per symbol inserted | Low — append-only |
| `nifty50_company_master` | No change (LTIM already `is_active=FALSE`) | None |
| Phase 20 trade tables | No change | None |
| Phase 0C/0D tables (`phase20_eod_outcomes`) | No change | None |

No schema DDL changes required. All tables already exist.

---

## 7. FILE-BY-FILE PLAN

### Files that change: NONE for capital migration or universe switch

Both operations are pure DB/KV writes triggered via existing API endpoints. No Python or TypeScript files need to be modified.

### Files to verify on branch (read-only confirmation)

| File | What to verify |
|---|---|
| `artifacts/api-server/src/python/paper_capital_migration.py` | Confirm `TARGET_CAPITAL = 100_000.0` and `_sync_legacy_portfolio_locked()` do not touch Phase 0C code |
| `artifacts/api-server/src/python/custom_universe_store.py` | Confirm `upsert_symbols()` is idempotent and does not touch phase20 executor |
| `artifacts/api-server/src/python/config.py` | Confirm `NIFTY_50` still excludes LTIM and no import change is needed |
| `artifacts/api-server/src/routes/trading.ts` | Confirm `POST /api/phase20/capital-migration` route is present and requires confirmation text |
| `artifacts/api-server/src/routes/trading.ts` | Confirm `PUT /api/phase20/settings` route validates `active_intraday_universe` enum |

### If operator decides to add new symbols that require yfinance/Kite mapping changes

| File | Change |
|---|---|
| `artifacts/api-server/src/python/config.py` | Potentially add new sector mappings if any symbol is not in `SECTOR_MAP` (for correlation/risk computation) |
| `artifacts/api-server/src/python/symbol_validation.py` | Add company name entries for new symbols |

These are optional and only needed if adding symbols outside the existing master lists.

---

## 8. TESTS

### Capital migration

The migration module already has a full test suite (`test_paper_capital_migration.py`). No new tests are required for the branch unless code changes are made.

Post-migration verification (manual, not automated):
```bash
GET /api/phase20/capital-migration/status
# Expected: { "status": "ALREADY_APPLIED", "current_capital": 100000 }

GET /api/phase20/settings
# Expected: initial_capital=100000, config_hash changed

GET /api/phase20/positions
# Expected: positions=[]

# Derived limits at ₹1,00,000
# per_stock_exposure_cap = 25000
# risk_per_trade = 1000
# daily_loss_limit = 3000
```

### Custom universe population

After `upsert_symbols()`:
```bash
GET /api/universe/custom/symbols
# Expected: list of populated symbols, all is_active=true

GET /api/universe/custom/status
# Expected: symbol count matches population

# Spot-check one symbol
GET /api/live-data/scan/status  # after a scan under custom universe
```

Automated test to add on branch (if any custom universe logic is modified):
- `test_custom_universe_store.py` — upsert idempotency, active/inactive filtering, history snapshot isolation

---

## 9. ROLLBACK PLAN

### Capital rollback

The migration is designed to be reversible. If operator wishes to revert to ₹5,00,000:

```bash
# No dedicated rollback endpoint exists — would require a direct settings update
PUT /api/phase20/settings
{ "patch": { "initial_capital": 500000 } }
```

The migration dedup key (`paper_capital_migration:target:100000:v1`) would still show `ALREADY_APPLIED` but a manual settings patch overrides it. The closed trade history is not affected by either direction.

If the migration itself fails mid-way (DB connection lost, etc.), the `_acquire_entry_admission_lock` / `_release_entry_admission_lock` mechanism ensures no half-applied state: a subsequent call to `GET /api/phase20/capital-migration/status` will report the last completed state.

### Universe rollback

Reverting from CUSTOM_LOW_PRICE_SECTOR to NIFTY_50:
```bash
PUT /api/phase20/settings
{ "patch": { "active_intraday_universe": "NIFTY_50" } }
```

The `custom_universe_master` table is not cleared on revert — symbols remain in the DB for future use. No data loss.

### Branch rollback (Replit checkpoint)

Since both operations are DB writes rather than code changes, a Replit checkpoint rollback would not undo DB changes. Rollback is via the API endpoints above, not via checkpoint.

---

## 10. CONFIRMATION: PHASE 20 SAFETY CODE UNTOUCHED

The following files are **not touched** by any Phase 1 action:

| File | Role | Touched? |
|---|---|---|
| `phase20_executor.py` | Entry window guard, stale signal guard, fail-closed timestamp guard | ❌ No |
| `phase20_scheduler.py` | 15:20 squareoff trigger, entry cutoff guard | ❌ No |
| `phase20_exits.py` | `close_all_for_intraday_squareoff()`, force-close survivor path | ❌ No |
| `phase20_eod_outcomes.py` | Durable outcome table | ❌ No |
| `phase20_eod_status.py` | `exit_price_source` propagation | ❌ No |
| `phase20_store.py` | Settings DB, KV store | ❌ No (capital migration reads it via existing API) |
| `tests/unit/test_phase0c_safety_fixes.py` | 22-test Phase 0C safety suite | ❌ No |

The capital migration route (`POST /api/phase20/capital-migration`) calls `_update_settings()` through the same guarded path as `PUT /api/phase20/settings` — it does not bypass any Phase 0C guard.

---

## 11. CONFIRMATION: AUTO ENTRIES AND BOOTSTRAP REMAIN DISABLED

| Setting | Current (prod) | After all Phase 1 actions | Change? |
|---|---|---|---|
| `auto_paper_entries` | `false` | `false` | No |
| `auto_paper_entries_confirmed_at` | `null` | `null` | No |
| `bootstrap_paper_enabled` | `false` | `false` | No |
| `auto_paper_exits` | `true` | `true` | No |

Neither capital migration nor universe switch touches the `auto_paper_entries` or `bootstrap_paper_enabled` fields. The migration module explicitly pauses entries (`_pause_entries_best_effort()`) but does not re-enable them. Entries remain paused until operator explicitly re-enables with confirmation text after the first clean Phase 0C production session (see Phase 0D Task 7 watch plan).

---

## 12. CONFIRMATION: NO LIVE ORDERS

No Phase 1 action calls any broker order API. All changes are:
- Settings DB row updates (capital, universe)
- KV store key updates (Phase 11 capital keys)
- `custom_universe_master` table inserts
- Pipeline event emit (`CAPITAL_REBASE`)

All paper-only. Zero broker API calls.

---

## EXECUTION ORDER (recommended)

| Step | Action | Mechanism | Requires deploy? |
|---|---|---|---|
| 1 | Operator confirms symbol list for custom universe | Review candidate list in Section 3 | No |
| 2 | Populate `custom_universe_master` via `upsert_symbols()` or UI | DB write | No (can do on dev or prod directly) |
| 3 | Verify symbols are queryable (`GET /api/universe/custom/symbols`) | API call | No |
| 4 | Execute capital migration with confirmation | `POST /api/phase20/capital-migration` with confirmation text | No (endpoint already live on prod) |
| 5 | Verify capital migrated (`GET /api/phase20/capital-migration/status` → `ALREADY_APPLIED`) | API call | No |
| 6 | Switch active universe to `CUSTOM_LOW_PRICE_SECTOR` | `PUT /api/phase20/settings` | No |
| 7 | Verify next scan uses custom universe symbols | `GET /api/universe/custom/status` | No |
| 8 | Run Phase 0C test suite to confirm safety code untouched | `python3 -m pytest tests/unit/test_phase0c_safety_fixes.py -v` | No |
| 9 | First clean market session observation (2026-08-24) | Phase 0D watch plan | No |
| 10 | Operator review → auto entries re-enable decision | Operator confirmation | After Step 9 |
