# ApexQuant AI — Production Readiness Report
**Date:** 08 Aug 2026 (market weekend) · **Scope:** Continuous paper trading · **Mode:** PAPER / ADVISORY ONLY

---

## 1. Verdict

**GO for continuous paper trading**, with the environmental caveats in §6. No silent failures, placeholders, or data-source mismatches were found across the audited pages. Every metric on every core page now derives from a single canonical architecture: the phase20 ledger via `canonical_portfolio.py` and the durable scan snapshot (scan `2bf7afb3d547`).

---

## 2. Canonical data architecture (Phase 12 source mapping)

| Surface | Metric(s) | Source |
|---|---|---|
| Portfolio (`/portfolio-live`), `/api/portfolio/snapshot` | positions, cash ₹13,911.41, equity ₹49,713.51, unrealized −₹286.49 | `canonical_portfolio.build_canonical_portfolio()` (phase20 ledger; marks live-Kite-else-scan with `mark_source`) |
| Trade History (`/trades`) | all trade rows + metadata | `canonical_trades(scope)` (ledger; legacy-compat aliases) |
| Portfolio Performance (`/portfolio-performance`) | KPIs, equity curve, sector allocation, summary | `performance_engine.load_all()` → canonical trades + portfolio (legacy state only for pnl_history sparkline) |
| Execution Quality (`/execution-quality`) | 4 trade records, slippage, fill delay, scores | `execution_quality.metrics.build_execution_records()` → `canonical_portfolio._ledger_rows()` (legacy FIFO only as exception fallback) |
| Trade Replay (`/trade-replay`), Replay Mode | round trips, evidence dataset | phase20 ledger + append-only Phase 22 evidence store |
| Ops Centre (`/ai-operations-centre`) | pipeline counts, confidences | `build_replay()` unified replay snapshot (counts_source=replay_snapshot) |
| Validation (`/validation`) | trading stats, data quality, pipeline | same ledger + scan snapshot; cash identity shown: 50,000 − 36,088.59 + 0 = 13,911.41 ✓ |
| Phase 4A (`/phase4a-session`) | readiness checks, session monitor, open positions | same scan (`2bf7afb3`) + ledger; positions marked SCAN source |
| Broker (`/broker-execution`) | EOD reconciliation, modes | phase20 ledger reconciliation; Zerodha mock, PAPER mode |

**Consistency check:** one scan_id (`2bf7afb3d547`), one ledger, identical cash/equity/position counts across all endpoints and pages. Verified live via endpoint sweep (12 endpoints, all 200) and UI screenshots.

## 3. Pipeline verification (Phases 1–2)

Full trace for scan `2bf7afb3d547`: 50 universe → 48 processed (2 missing candles: LTIM, TATAMOTORS) → 43 AI decisions → 2 BUY signals → **0 paper orders** → portfolio unchanged.

**Why BUYs stop before Portfolio — explained, not silent:** both BUYs were rejected by the Risk Agent with logged reasons ("Market Open; No Open Duplicate; Per Stock Cap"); validation shows rejected 2 / risk_blocks 2, and the UI banner states "BUY recommendations are disabled until a fresh scan runs" (scan ~32h stale on a weekend). This is the designed fail-safe: stale data + market closed ⇒ entry gate blocks. Ops Centre pipeline trace matches the replay snapshot exactly (consistency_ok = true).

## 4. Fixes made during this sprint

1. **Portfolio Performance engine repointed to canonical data** — previously read legacy portfolio_store state; now equity/cash/trades match the rest of the platform.
2. **Execution Quality repointed to canonical ledger** — previously FIFO-matched legacy fills (showed 12 trades incl. archived demos); now shows the true 4 trades.
3. **Canonical trades gained legacy-compat aliases** so all consumers keep their field contracts.
4. **Operator Status scanner check fixed** — was polling a non-existent `/scan/status` (permanent 404 / "checking…"); now uses `/live-data/scan/status`.
5. **Execution Quality fallback hardened (post-review)** — legacy fallback now permitted only when the canonical ledger is unavailable; once ledger rows are obtained, malformed rows are logged and skipped rather than silently swapping the whole dataset to legacy data. New canonical-ledger tests prove the primary path (open/closed row mapping, sorting, malformed-row skip with fallback assertion).
6. Legacy `pnl_history` read in Portfolio Performance documented as a temporary compatibility source (charting only — never feeds cash/equity/positions).
7. Tests updated; **96/96 pass** across the touched modules (48 EQ + 48 PP). Dashboard typecheck clean.

## 5. UI audit (Phase 10)

Screenshotted at 1440px: Portfolio Performance, Execution Quality, Broker & Execution, Validation, Trade Replay, AI Operations Centre, Phase 4A (Portfolio and Trades pages verified earlier). Findings:
- No undefined values, broken cards, or overflow.
- Two intentional 404s remain in logs: `/api/live-orders` (safety proof that no live-order endpoint exists — expected by the Operator Status safety card) and GET `/api/phase4a/final-report` before a report is generated (returns a helpful message; UI handles it with `retry: false`).
- Ops Centre agent snapshot takes ~25s by design; the page communicates this while platform status stays live.

## 6. Remaining issues by severity

**Critical:** none.

**High:** none.

**Medium (environmental, weekend-related):**
- Market Data validation WARNING — yfinance DEGRADED, 96% coverage; 2 missing candles (LTIM, TATAMOTORS). Genuine data-provider condition, not a false warning. Expect it to clear on a fresh weekday scan with an active Zerodha session.
- Scan staleness banner (32h old) — correct behavior on a weekend; confirms BUY-gating works.

**Low:**
- Equity curve has only 1 data point ("Collecting equity history") — pnl_history is sparse on a young portfolio; fills in as sessions accumulate.
- Execution Quality exit slippage shows "—" — all 4 trades still open; populates on exits.
- trading-document-hub / project-video workflows have pre-existing port noise; out of scope for the trading platform.

## 7. Go/no-go recommendation

**GO.** The platform is safe for continuous paper trading:
- Single source of truth for all portfolio math; cross-page parity verified.
- Fail-safe gates proven live (stale scan + market closed ⇒ 0 orders, fully logged).
- No live-order path exists (verified 404); PAPER mode enforced end-to-end.
- Kill switch, circuit breaker, and EOD reconciliation all healthy (reconciliation CLEAN, 0 discrepancies).

Recheck on the next trading day: fresh scan clears the staleness banner, coverage returns to 100% with a Zerodha session, and auto paper entries flow through the full pipeline.
