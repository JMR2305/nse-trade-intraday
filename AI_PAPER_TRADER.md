# 🤖 AI Paper Trader — Page Summary

> **Route:** `/ai-paper-trader` · **Phase 11** · Paper trading only — no live broker orders, no real money.

---

## Overview

The AI Paper Trader is the primary operational screen for NSE paper trading during market hours. It consolidates all 12 key views into a single page so operators never need to navigate away while the market is open.

All data is fetched from existing Phase 11 backend endpoints using TanStack Query. The page is **read-only** and **advisory-only** — it displays AI recommendations and portfolio state but does not place any real orders.

---

## Page Structure

### Always-Visible Sections (top to bottom)

| # | Section | Purpose | Data Source |
|---|---------|---------|-------------|
| 1 | **Market Status** | Live market state, IST clock, session, regime, NIFTY 50, BANK NIFTY, India VIX, market health score | `/live-data/health-v2` + `/market-intelligence/overview` |
| 2 | **Portfolio Summary** | Starting capital, portfolio value, cash, buying power, invested, unrealised P/L, today P/L, overall return, drawdown, open positions | `/phase11/portfolio` |
| 3 | **Live AI Status** | Stocks monitored, recommendation count, open positions, current AI activity, best opportunity | `/phase11/recommendations` + `/phase11/timeline` |
| 4 | **Current Holdings** | Full open-position table with **P/L sparklines**, buy/current price, target, stop-loss, confidence bar, strategy, risk, duration | `/phase11/portfolio/open-positions` + `/phase11/timeline` |
| 5 | **Live Activity Feed** | Filterable event stream (ALL / TRADE / MARKET / SCAN / LEARNING) with colour-coded event types | `/phase11/timeline` |
| 6 | **Recommendation Queue** | Ranked AI recommendations with confidence bars, entry/target/stop-loss, expected return, reasoning | `/phase11/recommendations` |
| 7 | **Today's Closed Trades** | All trades closed today — entry, exit, P/L, return %, exit reason, strategy, lesson learned | `/phase11/portfolio/closed-positions` |
| 8 | **AI Performance** | Win rate, profit factor, avg gain/loss, avg hold time, recommendation accuracy, best/worst strategy | `/phase11/ai-performance` |

### Bottom Tabbed Panel

| Tab | Content |
|-----|---------|
| 📊 **Charts** | Cumulative P/L area chart · Trade distribution bar chart · Capital allocation pie · Portfolio drawdown chart |
| 📅 **Date History** | Monthly calendar heatmap (green = winning day, red = losing day) + drill-down daily summary with trade list and mini timeline |
| ⏯ **Replay** | Step-by-step session replay with play/pause/skip controls, portfolio value line chart, and AI decision log |
| 💰 **Capital** | Capital configuration (mode, starting amount, last reset) + full reset/top-up history log |

---

## P/L Sparklines (Section 4)

Each open position row includes a **96 × 36 px inline SVG sparkline** showing price momentum since entry:

- 🟢 **Green line** — current price ≥ buy price (trending toward target)
- 🔴 **Red line** — current price < buy price (trending toward stop-loss)
- Dashed reference lines mark the **entry price** (slate), **target** (green), and **stop-loss** (red)
- Price points are built from: `buy_price` → up to 18 intraday timeline price events → `current_price`
- Reuses the existing `apt/timeline` TanStack Query cache — **no extra network request**

---

## Safety Guarantees

| Guarantee | Implementation |
|-----------|---------------|
| Paper-only banner | Sticky indigo header visible at all times |
| No live execution | All writes disabled; all endpoints advisory-only |
| No real money | Starting capital is virtual (₹50,000 default) |
| Advisory label | "READ-ONLY · ADVISORY ONLY · No live broker orders · No real money" shown in banner |

---

## API Endpoints Used

```
GET /live-data/health-v2                          — market state (nested market object)
GET /market-intelligence/overview                 — NIFTY, BANKNIFTY, VIX, regime (nested objects)
GET /phase11/portfolio                            — portfolio summary
GET /phase11/portfolio/open-positions             — current holdings
GET /phase11/portfolio/closed-positions?limit=20  — today's closed trades
GET /phase11/recommendations                      — recommendation queue
GET /phase11/timeline?limit=200                   — activity feed + sparkline prices
GET /phase11/ai-performance                       — AI performance metrics
GET /phase11/calendar?year=&month=               — monthly calendar heatmap
GET /phase11/daily-summary?date=                 — drill-down daily view
GET /phase11/replay?date=                        — session replay snapshots
GET /phase11/capital/config                       — capital configuration
GET /phase11/capital/topups                       — reset/top-up history
```

---

## Navigation

- **Route:** `/ai-paper-trader`
- **Breadcrumb:** AI Decision → AI Paper Trader
- **Sidebar:** Listed under **Agent 7 — AI Decision Agent** and **Agent 8 — Execution Agent**
- **Command Centre shortcut:** ⭐ "AI Paper Trader" card above the Phase 11 Paper Trading Centre card

---

## Key Design Decisions

| Decision | Reason |
|----------|--------|
| Single unified page | Eliminates context-switching during live market hours |
| All data from existing Phase 11 endpoints | Zero new backend logic; no regression risk |
| Pure SVG sparklines (no Recharts per row) | Lightweight — up to 20 rows rendered without performance penalty |
| Shared TanStack Query cache keys | Sections sharing the same endpoint (e.g. `apt/timeline`) make only one network request |
| Ascending timeline → last event for "current activity" | Phase 11 timeline is sorted chronologically ascending; `events[events.length - 1]` is the most recent |
| `health-v2` nested contract | `market.state` / `market.is_open` — not top-level fields |
| `market-intelligence/overview` nested contract | `regime.nifty_price`, `regime.banknifty_price`, `volatility.vix_value` — not top-level |
| `avg_holding_label` (not `avg_holding_time`) | Actual server key from `phase11_autonomous.py` line 940 |

---

*Last updated: August 2026 · Phase 11 · ApexQuant AI*
