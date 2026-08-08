# Data Architecture Consolidation — Verification Report

Generated: 2026-08-08 · Canonical scan: `2bf7afb3d547` · Portfolio version: `4:2026-08-07T04:17:06Z`

## What was found

The pipeline itself was already consolidated (canonical scan bundle, unified replay snapshot,
ops-centre reading `counts_source: replay_snapshot`, `INITIAL_CAPITAL` from `portfolio_store`,
broker STATE_FILE import fixed). The remaining divergence was in the **portfolio family of
endpoints**, which read three different stores:

| Endpoint (before) | Store used | Positions | Cash | Equity |
|---|---|---|---|---|
| `/api/phase4a/dashboard` | phase20 ledger ✅ | 4 | 13,911.41 | 49,713.51 |
| `/api/portfolio` | legacy paper_trader state ❌ | 1 | 41,199.60 | 49,823.60 |
| `/api/phase11/snapshot` | legacy portfolio_store state ❌ | 1 | 41,199.60 | 50,000.00 |
| `/api/portfolio/snapshot` | **mixed** ledger positions + legacy cash ❌ | 4 | 41,199.60 | **77,288.19** |
| `/api/trades?scope=all` | legacy paper_trader mirror ❌ | 12 rows incl. archived TCS demo trades | — | — |

Root cause: the legacy paper_trader daily reset archives positions that remain OPEN in the
phase20 ledger, and `/portfolio/snapshot` summed ledger positions on top of legacy cash
(double counting → equity ₹77,288 from ₹50,000 capital).

A second bug: ops-centre `avg_strategy_confidence` double-scaled already-percent confidences
(showed 5304.5 instead of 53).

## What was changed

New module: `artifacts/api-server/src/python/canonical_portfolio.py` — the ONLY portfolio math:

- positions = phase20 ledger rows with status OPEN/EXIT_PENDING
- realized P&L = ledger CLOSED rows
- `cash = INITIAL_CAPITAL − Σ(open cost) + Σ(realized)`
- `equity = INITIAL_CAPITAL + realized + unrealized MTM` (marks: live Kite quotes when a
  verified session exists, else last canonical scan; per-position `mark_source` flags)
- emits `scan_id`, `portfolio_version` (row count + latest update ts), `source: phase20_ledger`

Repointed consumers (no shape changes for the frontend):

- `/api/portfolio` (`cmd_portfolio`) → canonical, legacy response shape preserved
- `/api/trades` + `/api/trades?scope=all` (`cmd_trades*`) → fills emitted from the ledger
  (BUY per entry, SELL per CLOSED exit) — archived demo TCS rows no longer surface
- `/api/phase11/snapshot` (`get_phase11_portfolio`) → canonical cash/invested/equity/counts
- `/api/portfolio/snapshot` (`portfolio_snapshot.py`) → canonical cash/invested/unrealized;
  equity now includes unrealized MTM; per-position rows overlaid with canonical marks
- `ops_centre._pipeline_summary` → confidence normalisation without double scaling

## Verification (live values, after)

All portfolio-facing endpoints now return identical figures:

| Endpoint | Positions | Cash | Equity | Unrealized | Scan ID |
|---|---|---|---|---|---|
| `/api/phase4a/dashboard` | 4 | 13,911.41 | 49,713.51 | −286.49 | 2bf7afb3d547 |
| `/api/portfolio` | 4 | 13,911.41 | 49,713.51 | −286.49 | 2bf7afb3d547 |
| `/api/phase11/snapshot` | 4 | 13,911.41 | 49,713.51 | −286.49 | (canonical) |
| `/api/portfolio/snapshot` | 4 | 13,911.41 | 49,713.51 | −286.49 | (canonical) |
| `/api/trades?scope=all` | 4 BUY fills (BAJFINANCE, GRASIM, DIVISLAB, TRENT) | — | — | — | per-trade |

## Page-by-page data sources (after consolidation)

| Page | Endpoint(s) | Store | Scan ID |
|---|---|---|---|
| Replay | `/replay/sessions*` | Replay snapshot (scan_state_store) | 2bf7afb3d547 |
| AI Operations Centre | `/ops-centre/snapshot` | Operations snapshot (counts_source=replay_snapshot, consistency_ok=true) | 2bf7afb3d547 |
| Portfolio | `/phase11/snapshot`, `/portfolio/snapshot` | **canonical_portfolio → phase20 ledger** | 2bf7afb3d547 |
| Trade History | `/trades`, `/trades?scope=all` | **canonical_portfolio → phase20 ledger** | per-trade |
| Portfolio Performance | `/portfolio-performance/*` | Performance engine over portfolio store (`INITIAL_CAPITAL` from portfolio_store) | — |
| Validation | `/validation/dashboard` | Validation aggregator over ledger + scan + replay | 2bf7afb3d547 |
| Phase 4A | `/phase4a/dashboard` | Phase 4A aggregator over ledger + scan + replay | 2bf7afb3d547 |
| Broker | `/broker/status`, `/broker/paper-summary` | Broker client + ledger reconciliation (loads; no STATE_FILE import error) | — |
| Execution Quality | `/execution-quality/*` | FIFO matcher over ledger trades | — |
| EOD Reconciliation | `/broker/reconciliation` | phase20 ledger | — |

Frontend audit (all 10 pages above): **no client-side aggregation** — pages render backend
values only; no hardcoded capital, demo, or synthetic data found.

## Post-review hardening

An architect review flagged residual inconsistencies; all were fixed and re-verified:

- `/api/phase11/portfolio/open-positions` (Phase 11 Portfolio / AI Paper Trader rows) now
  reads canonical positions — previously legacy state (would have shown 1 row vs 4).
- `/api/portfolio/snapshot` position rows are now built from canonical positions
  (includes EXIT_PENDING, canonical marks + `mark_source` per row).
- Missing-mark semantics made explicit: canonical snapshot carries `equity_complete: false`
  and `unrealized_note` when any mark is unavailable (equity uses known MTM only).
- `canonical_trades` is fault-tolerant (ledger failure → empty list, not a 500).
- Phase 11 unit tests updated to canonical-ledger fixtures — 68/68 pass
  (`test_phase11.py` 60, `test_phase4a_dashboard.py` 8).

Final parity check after hardening (all four endpoints): equity 49,713.51 · 4 positions ·
cash 13,911.41 · unrealized −286.49.

## Notes

- Marks are currently `scan`-sourced (no live broker session on the weekend); position rows
  carry `mark_source` badges so live vs scan is always explicit.
- The legacy paper_trader/portfolio_store state remains for pnl_history charting only; it no
  longer drives any position, cash, or equity figure.
