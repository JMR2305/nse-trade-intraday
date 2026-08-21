# APEXQUANT PHASE 2A — ADVISORY MULTI-BOT BRANCH PLAN

**Branch:** `phase2a-advisory-multi-bot-logic`  
**Branch state:** Created from the current `main` workspace state. Not merged.  
**Deployment state:** No production deployment was triggered or requested.  
**Plan state:** Proposal only. No migration, bot implementation, endpoint, scheduler hook, or trade-state change is included in this phase.

---

## 1. Safety Contract

Phase 2A is a **paper-only, advisory-only** analysis layer. It may read canonical custom-universe metadata, canonical completed scan snapshots, and the current paper settings to confirm safety state. It must not write to trade, portfolio, position, scheduler, execution, broker, or settings paths.

The following production state is explicitly out of scope and remains untouched:

| Setting / state | Required value |
|---|---|
| `initial_capital` | `100000` |
| `active_intraday_universe` | `CUSTOM_LOW_PRICE_SECTOR` |
| `auto_paper_entries` | `false` |
| `bootstrap_paper_enabled` | `false` |
| `auto_paper_exits` | `true` |
| Positions | `[]` |

**No Phase 20 executor, scheduler, exits, EOD, position, or broker-order file will be modified.**

---

## 2. Proposed Bot Responsibilities

All outputs use explicit advisory vocabulary:

- `WATCH`
- `CANDIDATE`
- `REJECTED`
- `BLOCKED_DATA_QUALITY`
- `INSUFFICIENT_CONTEXT`
- `SUPERVISOR_BLOCKED`

They must never emit an executable order, order quantity, broker instruction, `BUY`, `SELL`, `EXECUTE`, or an auto-enable command.

### 2.1 Market Data / Universe Bot

**Input:** `custom_universe_store` active master rows and the latest canonical scan snapshot.  
**Rules:**

- Require `allowed_universe=CUSTOM_LOW_PRICE_SECTOR`.
- Require exactly 23 active rows.
- Require IOB and UCOBANK to remain inactive/excluded.
- Reject any symbol not present in the active custom-universe master.
- Reject a missing/empty custom universe rather than falling back to `NIFTY_50`, `DEFAULT_WATCHLIST`, or a legacy scanner list.

**Output:** A universe-health record containing count, active symbols, excluded symbols, non-custom candidates rejected, scan coverage, and `no_nifty_fallback=true`.

### 2.2 Data Quality Bot

**Input:** The 23 validated active master rows plus matching rows from the canonical scan snapshot.  
**Checks:**

- master `ohlcv_available=true`;
- snapshot/candle availability;
- scan freshness and explicit stale/unavailable quality states;
- non-null current price;
- non-null positive volume or a clearly reported lack of intraday volume;
- all 23 active symbols have a matching canonical-scan item.

**Fail-closed rule:** Any symbol with missing required data, stale/unavailable quality, or incomplete scan coverage gets `BLOCKED_DATA_QUALITY` and is not passed to strategy scoring. No daily-data substitute may be used to pretend intraday VWAP or opening-range evidence exists.

### 2.3 Market Regime Bot

**Input:** Existing index, sector, VIX, breadth, and regime context when present in the canonical market-intelligence snapshot.  
**Output classes:** `TRENDING`, `RANGE_BOUND`, `WEAK`, `VOLATILE`, or `INSUFFICIENT_CONTEXT`.

**Fail-closed rule:** Missing index/sector context produces `INSUFFICIENT_CONTEXT`, not a fabricated bullish or bearish classification. The result may reduce or block a strategy score, but cannot change a strategy, threshold, portfolio, or trade decision.

### 2.4 Strategy Bots

Each strategy returns a 0–100 **advisory score**, evidence list, data-quality state, risk flags, and a non-executable decision. Strategy data requirements are strict:

| Bot | Required evidence | Advisory-only result |
|---|---|---|
| VWAP Pullback | Intraday VWAP, pullback/reclaim relationship, volume confirmation, non-stale source | score + reason |
| Opening Range Breakout | First 15- or 30-minute session high/low, breakout relationship, volume confirmation | score + reason |
| EMA Pullback | Declared EMA trend, pullback/reclaim evidence, sufficient candle history | score + reason |

If the required candle shape is unavailable, the strategy returns `INSUFFICIENT_CONTEXT` or `BLOCKED_DATA_QUALITY` with score `0`; it must not infer a setup from a different timeframe.

### 2.5 Risk Gate Bot

**Fixed Phase 2A advisory configuration:**

| Limit | Value |
|---|---:|
| Capital basis | ₹100,000 |
| Per-stock notional cap | ₹25,000 |
| Risk per idea | ₹1,000 |
| Daily loss limit | ₹3,000 |

The bot checks feasibility only and returns `ALLOWED_ADVISORY` or `REJECTED_ADVISORY`, with the exact blocking reason. It does not calculate an order payload, reserve capital, update a daily counter, create a position, or call any Phase 20 gate/executor method.

If the read-only Phase 20 settings disagree with the fixed Phase 2A capital/safety basis, the result is `REJECTED_ADVISORY` with `CONFIG_MISMATCH`; there is no fallback to a different capital value.

### 2.6 AI Decision / Scoring Bot

**Input:** Eligible strategy scores, data-quality verdict, regime classification, and advisory risk verdict.  
**Output:** One ranked, explainable advisory idea per eligible custom-universe symbol:

- final score and rank;
- strongest supporting strategy;
- evidence and conflicts;
- data-quality state;
- risk flags;
- expiry/context timestamp; and
- an advisory decision only.

The decision bot has no dependency on `execution_agent`, `paper_trader`, broker clients, entry routes, or Phase 20 write methods.

### 2.7 Supervisor Bot

The supervisor acts as the final safety assertion before audit persistence:

1. confirms all input/output objects carry `advisory_only=true` and `paper_only=true`;
2. confirms the universe is exactly the validated 23-symbol custom universe;
3. confirms `auto_paper_entries=false` and `bootstrap_paper_enabled=false` via a read-only settings snapshot;
4. rejects any output with an executable action, order field, broker reference, or prohibited import/call;
5. emits `SUPERVISOR_BLOCKED` if any upstream bot fails, data quality is poor, settings are unsafe, or universe health is not exact.

It can only approve an output for **advisory recording**, never for trade execution.

### 2.8 Audit / Learning Bot

The audit bot persists immutable advisory artifacts for later operator review. It does not read or write the Phase 20 trade ledger, positions, paper-entry APIs, or settings mutation APIs.

Records are append-only and keyed by scan/run identity. A repeated invocation for the same scan, build, config, bot, symbol, and strategy is idempotent (`ON CONFLICT DO NOTHING`), never an update of prior evidence.

---

## 3. Proposed Data Flow

```text
custom_universe_master (read-only)
        + canonical completed scan snapshot (read-only)
        + market-intelligence context (read-only, optional)
        + Phase 20 settings snapshot (read-only supervisor check)
                              |
                              v
                 Universe Bot (exact 23 / no fallback)
                              |
                              v
                    Data Quality Bot (fail closed)
                              |
                    +---------+----------+
                    |                    |
                    v                    v
           Market Regime Bot      VWAP / ORB / EMA Bots
                    |                    |
                    +---------+----------+
                              v
                   Advisory Risk Gate Bot
                              |
                              v
                 AI Decision / Ranking Bot
                              |
                              v
                 Supervisor Bot (safety assertion)
                              |
                              v
           Append-only advisory audit tables only
```

**Explicitly absent from the flow:** `phase20_executor`, `phase20_scheduler`, `phase20_exits`, EOD routines, trade ledger writes, position writes, paper-entry routes, broker clients, and live-order APIs.

---

## 4. Data Model Proposal — Review Before Any Migration

No migration is created in this branch. The following is the proposed additive-only schema for Phase 2B review.

### Common immutable fields

Every stored advisory record will include:

```text
id, observed_at, scan_id, symbol, bot_name, strategy_name,
score, decision, reason, data_quality, risk_flags,
build_id, config_hash, paper_only=true
```

For run-level or universe-level records, `symbol` is the explicit sentinel `__RUN__` or `__UNIVERSE__`; it is never omitted. `strategy_name` is similarly explicit (`SUPERVISOR`, `UNIVERSE_HEALTH`, or `NONE`) so the audit shape remains uniform.

All four tables must enforce:

- `paper_only BOOLEAN NOT NULL DEFAULT TRUE CHECK (paper_only IS TRUE)`;
- append-only inserts only (`ON CONFLICT DO NOTHING`); no update/delete API;
- `decision` constrained to advisory vocabulary;
- no foreign key to, trigger on, or write path into `phase20_paper_trades`, positions, portfolio state, or settings;
- an allow-listed SQL writer that can target only the four advisory tables.

### 4.1 `advisory_bot_outputs`

One normalized raw output per bot, symbol/run, and scan.

| Column | Purpose |
|---|---|
| `id` | Immutable output identifier |
| Common fields | Mandatory immutable audit fields above |
| `payload` JSONB | Complete sanitized bot payload/evidence |
| `source_snapshot_ts` | Timestamp of the canonical scan evidence |
| `created_at` | Persistence timestamp |

**Idempotency key:** `(scan_id, bot_name, symbol, strategy_name, build_id, config_hash)`.

### 4.2 `advisory_strategy_scores`

One independent strategy score per eligible symbol, strategy, and scan.

| Column | Purpose |
|---|---|
| Common fields | Mandatory immutable audit fields above |
| `rank_within_strategy` | Advisory-only relative rank |
| `supporting_factors` JSONB | Deterministic strategy evidence |
| `input_summary` JSONB | Price/volume/indicator values used |
| `created_at` | Persistence timestamp |

**Idempotency key:** `(scan_id, symbol, strategy_name, build_id, config_hash)`.

### 4.3 `advisory_decision_audit`

One final supervisor-reviewed AI decision per symbol and scan.

| Column | Purpose |
|---|---|
| Common fields | Mandatory immutable audit fields above |
| `final_rank` | Advisory rank only |
| `strategy_scores` JSONB | Referenced strategy-score summary |
| `regime_context` JSONB | Regime evidence or insufficiency reason |
| `supervisor_verdict` | `APPROVED_FOR_ADVISORY_RECORD` or `SUPERVISOR_BLOCKED` |
| `created_at` | Persistence timestamp |

**Idempotency key:** `(scan_id, symbol, build_id, config_hash)`.

### 4.4 `advisory_universe_health`

One universe-level health assertion per scan.

| Column | Purpose |
|---|---|
| Common fields | `symbol=__UNIVERSE__`, `bot_name=universe-bot`, `strategy_name=UNIVERSE_HEALTH` |
| `active_count` | Must equal 23 for `HEALTHY` |
| `inactive_symbols` JSONB | Expected `[IOB, UCOBANK]` |
| `unexpected_symbols` JSONB | Must be empty |
| `missing_symbols` JSONB | Must be empty |
| `nifty_fallback_detected` | Must be false |
| `coverage_summary` JSONB | Canonical scan match/freshness details |
| `created_at` | Persistence timestamp |

**Idempotency key:** `(scan_id, build_id, config_hash)`.

### Storage recommendation

Use the existing Phase 24 append-only storage conventions as the implementation reference, extending its safety-test approach rather than introducing any Phase 20 persistence dependency. The advisory schema must remain a separate, additive store with no shared tables or mutation functions with Phase 20.

---

## 5. Proposed Files for Phase 2B Implementation

No files below are created or modified in this Phase 2A plan.

| Proposed file | Purpose |
|---|---|
| `artifacts/api-server/src/python/advisory_bots/__init__.py` | Advisory package boundary and shared safety constants |
| `artifacts/api-server/src/python/advisory_bots/contracts.py` | Typed immutable input/output contracts and advisory vocabulary |
| `artifacts/api-server/src/python/advisory_bots/universe_bot.py` | Exact custom-universe health and exclusion checks |
| `artifacts/api-server/src/python/advisory_bots/data_quality_bot.py` | OHLCV/freshness/price/volume fail-closed checks |
| `artifacts/api-server/src/python/advisory_bots/regime_bot.py` | Read-only regime classification |
| `artifacts/api-server/src/python/advisory_bots/strategies.py` | VWAP Pullback, ORB, and EMA Pullback scoring only |
| `artifacts/api-server/src/python/advisory_bots/risk_gate_bot.py` | Fixed ₹1L advisory feasibility limits |
| `artifacts/api-server/src/python/advisory_bots/decision_bot.py` | Explainable final advisory rank |
| `artifacts/api-server/src/python/advisory_bots/supervisor_bot.py` | Mandatory safety assertions and final advisory block |
| `artifacts/api-server/src/python/advisory_bots/audit_bot.py` | Append-only advisory record adapter |
| `artifacts/api-server/src/python/advisory_bots/orchestrator.py` | Pure read → analyze → audit orchestration; no scheduler integration |
| `artifacts/api-server/src/python/phase24_store.py` | Additive advisory-table DDL and append-only repository methods, subject to review |
| `artifacts/api-server/src/python/tests/unit/test_advisory_bots.py` | Isolation, safety, universe, data-quality, risk, and score tests |
| `artifacts/api-server/src/python/test_phase24.py` | Extend advisory AST/import/write allow-list coverage if the storage implementation uses Phase 24 conventions |
| `APEXQUANT_PHASE2B_ADVISORY_MULTI_BOT_IMPLEMENTATION_REPORT.md` | Implementation evidence, test output, schema decision, and explicit no-execution proof |

**Deliberately excluded files:** `phase20_executor.py`, `phase20_scheduler.py`, `phase20_exits.py`, EOD files, paper-entry code, broker clients, paper-trade stores, position stores, and production deployment configuration.

---

## 6. Required Tests for Phase 2B

`tests/unit/test_advisory_bots.py` does not exist yet because this branch contains only the plan. It must be created before any bot implementation is considered complete.

| Requirement | Test proof |
|---|---|
| 1. Bots cannot create trades | Patch all trade/ledger entry functions to fail; run orchestration and prove no call and no ledger mutation |
| 2. Bots cannot call broker APIs | AST/import deny-list plus mocked broker methods that fail if touched |
| 3. Bots cannot enable `auto_paper_entries` | Patch settings write API to fail; supervisor reads false and only reports state |
| 4. Bots read only custom-universe symbols | Fixture includes non-custom scan rows; prove they are rejected |
| 5. IOB/UCOBANK excluded | Fixture contains both inactive rows; prove neither reaches data quality or strategy scoring |
| 6. No NIFTY_50 fallback | Empty/mismatched custom-universe fixture must block with `SUPERVISOR_BLOCKED`, not use a default watchlist |
| 7. Bad data blocks scoring | Missing OHLCV, stale timestamp, null price, and missing volume fixtures each prevent strategy evaluation |
| 8. Risk limits use ₹1L basis | Boundary tests verify ₹25k per-stock, ₹1k per-idea, and ₹3k daily-loss blocks |
| 9. Strategy bots produce scores only | Verify score/reason/evidence output and absence of executable action/order fields |
| 10. Phase 0C safety remains intact | Existing Phase 0C suite passes unchanged |
| 11. Audit writes are isolated | Fake DB captures writes and proves only the four advisory tables are targeted |
| 12. Append-only behavior | Same idempotency key is ignored; prior advisory evidence is never overwritten |

### Required commands after Phase 2B implementation

```bash
cd artifacts/api-server/src/python
python3 -m pytest tests/unit/test_phase0c_safety_fixes.py -v
python3 -m pytest tests/unit/test_custom_universe_store.py -v
python3 -m pytest tests/unit/test_advisory_bots.py -v
```

### Baseline run on this planning branch

```text
tests/unit/test_phase0c_safety_fixes.py  — 22 passed, 1 existing datetime deprecation warning
tests/unit/test_custom_universe_store.py — 20 passed
```

The advisory suite is intentionally pending because no advisory implementation was created in Phase 2A.

---

## 7. Merge Conditions

Do not merge this branch until all conditions below are met:

1. The proposed schema has explicit operator approval and remains additive-only.
2. The implementation diff contains no Phase 20 executor, scheduler, exits, EOD, position, portfolio, paper-entry, broker, or settings-write changes.
3. The AST/import deny-list and runtime mocks prove no path can create trades, close positions, call brokers, or enable settings.
4. The exact 23-symbol custom-universe and no-fallback tests pass.
5. Data-quality, risk-limit, strategy-score, append-only, and audit-table allow-list tests pass.
6. The three required test commands pass.
7. The supervisor blocks reporting if `auto_paper_entries` or `bootstrap_paper_enabled` is not false.
8. A code review confirms that all persistent writes target only the four approved advisory tables.
9. The user explicitly approves the table migration and Phase 2B implementation scope.
10. No production deployment occurs as part of merge approval; deployment remains a separate operator decision.

---

## 8. Phase 2B Recommendation

Proceed with Phase 2B only after explicit approval of this table design.

Recommended implementation order:

1. Build pure contracts and the Universe/Data Quality bots with fixture-only tests.
2. Add the three strategy scorers and regime classifier, preserving zero-score fail-closed behavior.
3. Add the fixed-limit advisory Risk Gate and AI Decision/Supervisor flow.
4. Add the four append-only advisory tables and storage allow-list only after the safety tests pass in file/fake-DB mode.
5. Add the audit bot and full orchestration.
6. Run the required test suite and a source-diff guard proving Phase 20 safety code was not touched.
7. Produce a Phase 2B implementation report for review before any merge or deployment.

**Recommendation:** Phase 2B is safe to implement only as a manually invoked, read-only advisory pipeline. Do not attach it to the Phase 20 scheduler, executor, broker layer, paper-entry flow, exits, or EOD workflow.

---

## 9. Explicit Confirmations

- **No production deployment:** confirmed.
- **No merge to main:** confirmed.
- **No auto-paper-entry enablement:** confirmed.
- **No bootstrap enablement:** confirmed.
- **No capital or active-universe change:** confirmed.
- **No trades created:** confirmed.
- **No positions closed:** confirmed.
- **No broker order API calls:** confirmed.
- **No Phase 20 executor/scheduler/exits/EOD safety code touched:** confirmed.