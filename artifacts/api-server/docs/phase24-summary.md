# Phase 24 — AI Learning & Continuous Improvement Engine — Summary

> **Status:** COMPLETE
> **Scope:** Advisory-only, append-only learning layer over the canonical Phase 20 paper trade ledger
> **Gate:** None — routes are always mounted; every payload is labelled `advisory_only: true`
> **UI:** AI Learning Center page (`artifacts/trading-dashboard/src/pages/AILearningCenter.tsx`)

---

## Objective

Give the platform a permanent institutional memory: capture every CLOSED paper
trade into an immutable Trade Intelligence record, analyse what went right or
wrong (entry/exit timing, stop/target quality, missed profit), learn from
rejected candidates (were the risk gates correct?), rank strategies/sectors/
time buckets, grade each AI subsystem daily, and turn all of that into
manually-approved advisory recommendations and periodic reports.

**Hard boundaries:**
- READ-ONLY over trading state. Phase 24 has **no write path** into trading
  rules, thresholds, strategy enablement, or risk gates — proven by an AST
  safety test, not just convention.
- Records derive from the **exact trade-time payload** the executor stored
  (ledger columns + evidence JSONB) — never a re-evaluation.
- Approving a recommendation records **intent only**; nothing is auto-applied.
- Excursions (MFE/MAE) are never computed from mock candles — if real intraday
  candles are unavailable, the fields are explicitly `null`
  (`excursion_source: "unavailable"`).

---

## Architecture

| Module | Responsibility |
|--------|----------------|
| `phase24_store.py` | Durable storage: 4 Postgres tables (`phase24_trade_intelligence`, `phase24_missed_opps`, `phase24_recommendations`, `phase24_reports`) with a JSON file fallback when `DATABASE_URL` is absent (local dev / tests). Append-only enforced at the storage layer: trade + missed-opp inserts use `ON CONFLICT DO NOTHING`; recommendations may transition `PROPOSED → APPROVED | DISMISSED` exactly once; reports are idempotent per `(period, period_key)`. |
| `phase24_engine.py` | Trade capture (`capture_closed_trades`, idempotent per `trade_id`), record building from the ledger row (`build_trade_record`), excursion computation (MFE/MAE from intraday candles over the holding window), post-trade analysis (`analyze_trade`), missed-opportunity analysis over the latest canonical scan's gate rejections (`run_missed_opportunity_analysis`, one permanent record per `(scan_id, symbol)`), and risk-rule learning (`risk_rule_learning` — per-gate `SAVES_MONEY` / `BLOCKS_PROFITS` / `MIXED` / `INSUFFICIENT_EVIDENCE` verdicts, requiring ≥5 evaluated rejections). |
| `phase24_analytics.py` | Aggregate analytics over the permanent records only (no duplicate ledger math): strategy ranking, sector ranking, time/weekday/regime/volatility analysis, confidence calibration (delegates to the Phase 21 calibration engine — one source of truth), daily AI scorecard (grades 8 subsystems 0–10: scanner, research, market intelligence, monitoring, strategy, risk, execution, portfolio; insufficient data → `null`, never fabricated), period lessons (mistakes + improvements), best/worst trades, and the single `overview()` payload consumed by the dashboard. |
| `phase24_recommendations.py` | Recommendation generation (once per IST day unless forced) from analytics signals — strategy underperformance, gate effectiveness, calibration error, sector losses — all stored as `PROPOSED` with `requires_manual_approval: true`. Periodic reports (daily/weekly/monthly/quarterly), idempotent per period key. `maybe_run_daily_learning()` is a KV-guarded scheduler tick (same pattern as the daily session report) that runs capture → missed-opportunity analysis → recommendations → due reports once per IST day after market close, and never raises. |

### Post-trade analysis verdicts (per trade, advisory)

Computed only from the captured record + holding-window excursions:

- **Entry timing:** `EARLY` (large adverse move before working), `LATE` (entry near window high), `OK`, `UNKNOWN`.
- **Stop quality:** `TOO_TIGHT` (stopped out, then the move turned favourable), `TOO_LOOSE` (loss taken while price never approached the stop), `OK`, `UNKNOWN`.
- **Target quality:** `TOO_CONSERVATIVE` (price exceeded target by >3%), `TOO_AGGRESSIVE` (never reached half the target distance), `OK`, `UNKNOWN`.
- **Exit timing / missed P&L:** `max_potential_pnl`, `missed_pnl`, `could_have_earned_more`, `EARLY` / `LATE` / `OK`.
- **Trailing-stop counterfactual:** would a 1%-from-peak trail have beaten the actual exit (advisory P&L delta).
- **Better-strategy advisory:** compares the trade's strategy against the regime matrix's highest-expectancy strategy for the trade's regime.

---

## API Surface (`src/routes/phase24.ts`)

All routes are advisory-only; nothing mutates trading configuration.

| Method | Route | Purpose |
|--------|-------|---------|
| GET | `/api/phase24/overview` | Full AI Learning Center payload (30 s route-side cache + single-flight; 120 s Python timeout) |
| GET | `/api/phase24/trades` | Permanent Trade Intelligence records (`?limit=`) |
| POST | `/api/phase24/capture` | Capture closed ledger trades (idempotent) |
| GET | `/api/phase24/missed` | Stored missed-opportunity records |
| POST | `/api/phase24/missed/run` | Analyse latest canonical scan rejections |
| GET | `/api/phase24/risk-learning` | Per-gate rejection effectiveness |
| GET | `/api/phase24/strategy-ranking` | Ranked strategy stats |
| GET | `/api/phase24/sector-ranking` | Ranked sector stats + best/worst summary |
| GET | `/api/phase24/time-analysis` | Hour / weekday / regime / volatility buckets |
| GET | `/api/phase24/calibration` | Confidence calibration (Phase 21 engine + phase24 counts) |
| GET | `/api/phase24/scorecard` | Daily AI scorecard |
| GET | `/api/phase24/recommendations` | `?status=PROPOSED\|APPROVED\|DISMISSED` |
| POST | `/api/phase24/recommendations/generate` | Generate today's recommendations |
| POST | `/api/phase24/recommendations/:id/decide` | `{ decision: "approve" \| "dismiss", note? }` — intent only, final |
| GET | `/api/phase24/reports` | `?period=daily\|weekly\|monthly\|quarterly` |
| POST | `/api/phase24/reports/generate` | `{ period, force? }` — idempotent per period key |

Python is invoked via `main.py` CLI commands (`p24_overview`, `p24_trades`,
`p24_capture`, `p24_missed`, `p24_missed_run`, `p24_risk_learning`,
`p24_strategy_ranking`, `p24_sector_ranking`, `p24_time_analysis`,
`p24_calibration`, `p24_scorecard`, `p24_recommendations`,
`p24_recommendations_generate`, `p24_rec_decide`, `p24_reports`,
`p24_report_generate`).

---

## Dashboard — AI Learning Center

Single page driven primarily by the one `overview` call (plus recommendations
and reports queries):

- **Daily AI Scorecard** — 8 subsystem scores (0–10), overall, strengths/weaknesses.
- **Lessons** — daily / weekly / monthly cards: period stats, mistakes (early exits, profit-turned-loss, tight stops), improvements.
- **Best / worst trades** — top-5 lists from the permanent records.
- **Confidence calibration** — per-bucket predicted vs observed win rate and calibration error.
- **Risk-rule learning** — per-gate verdicts with effectiveness percentages.
- **Strategy & sector rankings** — full stats tables (win rate, P&L, profit factor, expectancy, Sharpe, confidence accuracy).
- **Time / weekday / regime / volatility analysis** — best/worst per dimension.
- **Recommendations panel** — Approve / Dismiss with optional note; decided items show final status. The panel states explicitly that approval records intent only.
- **Automated reports** — expandable per-period reports with performance stats, mistakes, expected improvements, and a JSON download.
- Manual triggers: **Capture closed trades** and **Generate recommendations** buttons.

The page header and empty states carry the advisory-only labelling throughout.

---

## Safety & Design Principles

1. **No auto-execution / no config mutation** — enforced structurally by an AST test that forbids mutating calls (`update_settings`, `execute_buy`, `create_paper_entry`, `apply_adjustment`, …) and forbidden imports (`paper_trader`, `phase20_exits`) across all four Phase 24 modules.
2. **Append-only records** — trade intelligence and missed-opp records can never be overwritten or re-evaluated; recommendation decisions are final; the first report per period is permanent.
3. **Trade-time truth** — records are built from the ledger row the executor wrote, including its evidence JSONB (indicators, gates, scores); analysis never re-evaluates market conditions.
4. **No fabricated excursions** — mock-source candles are rejected; missing data yields explicit `null` fields.
5. **INSUFFICIENT_EVIDENCE over extrapolation** — rule verdicts need ≥5 evaluated rejections; scorecard components with no data are `null`.
6. **Scheduler safety** — the daily learning tick is KV-guarded (idempotent per IST day), only runs when the market is CLOSED, restores the guard key on failure so the next tick can retry, and never raises into the scheduler.
7. **Scoped KV writes** — the only `phase20_store` mutation is Phase 24's own `phase24_*` guard key (AST-verified).

---

## Test Coverage (`test_phase24.py`)

All tests run against the JSON file fallback in a tmpdir — the dev database is
never touched.

| Area | What is proven |
|------|----------------|
| Store append-only | Duplicate trade/missed-opp inserts rejected; report idempotent per period |
| Recommendation lifecycle | PROPOSED → APPROVED/DISMISSED once; invalid decisions rejected; "intent only" in the response |
| Excursions | MFE/MAE math from candles; explicit `null` when no candles |
| Post-trade analysis | EARLY/LATE exits, TOO_TIGHT stops, TOO_CONSERVATIVE/TOO_AGGRESSIVE targets, UNKNOWN on missing data, always advisory |
| Capture | Idempotent per trade_id; OPEN trades skipped; record fields come from the exact ledger row (`source: "phase20_ledger"`) |
| Missed opps & risk learning | BLOCKS_PROFITS / SAVES_MONEY / INSUFFICIENT_EVIDENCE verdicts; permanent storage idempotent per `(scan_id, symbol)` |
| Analytics | Ranking math (win rate, profit factor, expectancy, rank), sector summary, IST time buckets, scorecard shape, lesson detection |
| Generation | Recommendations from underperforming strategies (stored PROPOSED, manual approval required); once-per-day dedup; report idempotency; period-key formats |
| **AST safety** | No forbidden mutating calls or imports in any Phase 24 module; `kv_set` limited to `phase24_*` keys; `decide_recommendation` imports nothing |

---

## Related

- Phase 20 executor/ledger — the single source of truth Phase 24 reads.
- Phase 21 regime matrix & calibration — reused (not duplicated) for the better-strategy advisory and confidence calibration.
