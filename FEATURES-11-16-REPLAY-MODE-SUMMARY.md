# Features 11–16: Operations Centre Replay Mode
**ApexQuant AI — NSE Trading Platform**
*Completed: 6 August 2026*

---

## Overview

Replay Mode lets operators watch the AI agent pipeline make decisions in real-time, debug any stock's journey through all 9 pipeline stages, compare AI decisions against market outcomes, and generate executive summaries — all from real scan snapshots stored in the database.

**Page route:** `/replay`
**Sidebar location:** Operations → Replay Mode

---

## Architecture

### Data Sources
| Source | Used For |
|---|---|
| `scan_state.snapshot` (Postgres JSONB) | Latest scan — richest data (50 symbols, 9 reconstructed stages, confidence, gate results, strategy scores) |
| `signal_snapshots.signals` (Postgres) | Historical scans — fallback for sessions not in `scan_state` |
| `paper_trades` table | Outcome tracking for Decision Comparison |

### New Files
| File | Purpose |
|---|---|
| `artifacts/api-server/src/python/replay_engine.py` | Python engine — 5 functions reconstructing the 9-stage pipeline from scan snapshots |
| `artifacts/api-server/src/routes/replay.ts` | 5 Express GET routes |
| `artifacts/trading-dashboard/src/pages/ReplayModePage.tsx` | Full React page (1 081 lines) implementing all 6 features |

### Modified Files
| File | Change |
|---|---|
| `artifacts/api-server/src/python/main.py` | +5 dispatch branches: `replay_sessions`, `replay_build`, `replay_symbol`, `replay_comparison`, `replay_summary` |
| `artifacts/api-server/src/routes/index.ts` | Imported and wired `replayRouter` |
| `artifacts/trading-dashboard/src/App.tsx` | Added `<Route path="/replay" component={ReplayModePage} />` |
| `artifacts/trading-dashboard/src/components/layout/AgentConfig.ts` | Added nav entry under Operations group |

---

## API Endpoints

```
GET /api/replay/sessions
GET /api/replay/sessions/:scanId
GET /api/replay/sessions/:scanId/symbol/:symbol
GET /api/replay/sessions/:scanId/comparison
GET /api/replay/sessions/:scanId/summary
```

Use `scanId = "latest"` to always fetch the most recent scan.

---

## Feature Breakdown

### Feature 11 — Animated Pipeline Replay
**Tab:** Pipeline Replay

- Session picker (dropdown) pre-populated with real scans from the database
- **Play / Pause / Reset** controls + **Fast / Normal / Slow** speed selector
- 9 animated stage cards flow left-to-right: Supervisor → Market Data → Research → Market Intelligence → Monitoring → Strategy → Risk → AI Decision → Execution
- Each card activates sequentially with a pulsing teal beacon; shows IN count, OUT count, rejected count, and processing time when done
- Live "stocks moving" ticker shows which symbols are active in the current stage
- Click any stage card to jump straight to the Time Travel tab paused at that stage

**9 Reconstructed Stages from latest scan (50-stock universe):**
| Stage | IN | OUT | Rejected |
|---|---|---|---|
| Supervisor | 50 | 50 | 0 |
| Market Data | 50 | 50 | 0 |
| Research | 50 | 50 | 0 |
| Market Intelligence | 50 | 48 | 2 |
| Monitoring | 48 | 48 | 0 |
| Strategy | 48 | 48 | 0 |
| Risk | 48 | 48 | 0 |
| AI Decision | 48 | 4 | 0 |
| Execution | 4 | 5 | — |

---

### Feature 12 — Click Any Stock Journey
**Tab:** Stock Journey

- Full paginated grid of all stocks evaluated in the session
- Filter by action: ALL / BUY / WATCH / HOLD / AVOID
- Search by symbol or sector name
- Each card shows: symbol, sector, final action badge, confidence %, strategy, paper-eligible flag
- Click any symbol → full **Stock Journey modal** (Features 12 + 13 combined)
- Modal shows the symbol's complete 9-step agent timeline with pass/fail/warn badges, scores, reasons, and key detail fields per stage

---

### Feature 13 — Agent Thinking Panel
**Tab:** Agent Thinking (standalone) / integrated into Stock Journey modal

Three collapsible panels per symbol:

**Strategy Agent**
- Strategy name, technical score, confidence %, decision badge
- Per-indicator breakdown (name, value, status badge)
- Win rate, profit factor, historical trade count

**Risk Agent**
- Position size %, risk %, R:R ratio, portfolio heat
- Entry / stop loss / target price grid
- Gate results grid (green ✓ / red ✗ per gate)
- Rejection reason if risk-blocked

**AI Decision Agent**
- Final decision badge, confidence %, opportunity score, holding days estimate
- Full reasoning list (each BUY/AVOID reason)

---

### Feature 14 — Decision Comparison
**Tab:** Decision Comparison

- Summary cards: Correct Calls · Losses · Missed Opportunities · Pending
- Full table: symbol, AI action, confidence, entry price, outcome %, verdict (CORRECT / LOSS / MISSED_OPPORTUNITY / CORRECT_AVOID / PENDING)
- Outcome % shown in green (positive) / red (negative)
- "Pending" used for trades with no closed outcome yet — no fabricated data

---

### Feature 15 — Time Travel Debugger
**Tab:** Time Travel

- Stage scrubber: click any of the 9 stage buttons to "pause" the pipeline at that moment
- Left panel: stage snapshot (IN/OUT/rejected/duration/description + rejected symbol chips)
- Right panel: cohort of stocks active at that stage in a filterable grid
- Each stock card shows symbol, sector, technical score, final action
- Stage is highlighted amber when selected

---

### Feature 16 — Replay Executive Summary
**Tab:** Summary

- **Verdict banner** (colour-coded: emerald = "Ready for Production", amber = caution)
- **Pipeline funnel chart**: 8-step horizontal bar chart from Scanned → Paper Trades with % drop-off at each stage
- **Performance panel**: win rate, profitable trades, total trades
- **Agent stats**: most rejections agent, slowest agent (+ ms), fastest agent (+ ms), overall AI score

**Latest scan summary:**
```
Verdict:   Ready for Production
AI Score:  78 / 100
Regime:    (from scan snapshot)
Duration:  23.9 s
Funnel:    50 → 50 → 50 → 48 → 48 → 4 (BUY) → 48 (risk) → 5 (paper trades)
```

---

## Design Decisions

| Decision | Rationale |
|---|---|
| Dedicated `/replay` page, not embedded in AI Ops Centre | AI Ops Centre is already 1 245 lines; Replay needs full-width animated layout |
| Reconstruct stages from `snapshot.recommendations` | Per-symbol data (gates, scores, confidence, strategy, paper_eligible) is already there — no re-evaluation needed |
| Historical v1 is deterministic | Reads immutable snapshots; never re-runs the pipeline |
| `signal_snapshots` fallback | Older sessions not in `scan_state` can still be replayed via `signals[]` array |
| Extensible architecture | `_build_stages_from_snapshot()` is the only function that needs updating for v2 (Market Replay / backtesting) |
| No fake fills / fabricated outcomes | Comparison uses `paper_trades.exit_price`; pending = no closed trade, shown as "Pending" |

---

## Known Limitations (v1 scope)

- Stage durations are reconstructed approximations (scan total ÷ weights), not per-agent wall-clock times — the pipeline doesn't currently emit per-stage timing
- Historical sessions from `signal_snapshots` lack gate-level detail (strategy scores and gate results) — they reconstruct a simplified 3-stage view
- Outcome `%` in Decision Comparison is null for open positions (paper trades not yet closed)

---

## Testing

```bash
# Session list
curl http://localhost:8080/api/replay/sessions

# Latest scan pipeline (9 stages, 50 symbols)
curl http://localhost:8080/api/replay/sessions/latest

# Single symbol journey (9 steps, agent thinking)
curl http://localhost:8080/api/replay/sessions/latest/symbol/RELIANCE

# Decision comparison (50 comparisons)
curl http://localhost:8080/api/replay/sessions/latest/comparison

# Executive summary (verdict + funnel + performance)
curl http://localhost:8080/api/replay/sessions/latest/summary
```

All endpoints return HTTP 200 with real database data. TypeScript compiles clean (`tsc --noEmit` passes).
