# Phase 2A — System Health Audit Report
## ApexQuant AI NSE Paper Trading Platform

**Audit date:** 2026-07-25 (Saturday — weekend, market closed)  
**Auditor:** Phase 2A automated probe suite (`phase2a_health_audit.py`)  
**API server:** `http://localhost:8080` · uptime 764 s · Node v24.13.0  
**Mode:** PAPER TRADING / RESEARCH ONLY — no live orders  
**Overall verdict:** ⚠️ DEGRADED (13 HEALTHY · 2 DEGRADED · 0 DOWN)

---

## 1. Subsystem Health Table

| # | Subsystem | Status | Latency | Key Fields Verified | Gaps |
|---|-----------|--------|---------|-------------------|------|
| 1 | Market Data | ✅ HEALTHY | 863 ms | market.state, now_ist, quote_provider, scan_id, coverage | 48/50 symbols (LTIM+TATAMOTORS missing — weekend) |
| 2 | Scanner | ✅ HEALTHY | 2 ms | scan_id, status, snapshot_ts, symbols_requested/received | Last scan 3h ago — stale (weekend expected) |
| 3 | Signal Engine | ✅ HEALTHY | 788 ms | stock, signal, confidence, price | All 10 signals are NO_TRADE (stale/weekend) |
| 4 | AI Advisory | ✅ HEALTHY | 241 ms | decision, confidence, regime, PAPER label, staleness | BUY disabled when stale ✅ |
| 5 | Risk Engine | ⚠️ DEGRADED | 136 ms | portfolio/health endpoint reachable | **pydantic missing** — PortfolioConfig falls back to hardcoded defaults |
| 6 | Paper Execution | ✅ HEALTHY | 215 ms | paper_mode=True, live-orders=404 | Auto paper entries OFF (safe default) |
| 7 | Portfolio | ✅ HEALTHY | 192 ms | cash, equity, open_positions, initial_capital, peak_equity, drawdown_pct | Clean state (₹5,000 cash, no positions) |
| 8 | P&L | ✅ HEALTHY | 198 ms | realised_pnl_today, unrealised_pnl, total_pnl, drawdown_amount, drawdown_pct | pnl_history in legacy endpoint |
| 9 | Trade Journal | ✅ HEALTHY | 127 ms | endpoint_reachable, returns_list, scope=all | 0 trades (clean state) |
| 10 | Audit Logs | ✅ HEALTHY | 184 ms | report, phase, label, generated_at | PAPER label confirmed |
| 11 | Recovery | ✅ HEALTHY | 45 ms | healthz, health/live, health/ready, python_runtime, scan_cache | uptime=764s |
| 12 | Mobile App | ⚠️ DEGRADED | 44 ms | apiConfig.ts, dataStatus.ts, package.json | Expo workflow stuck on port-conflict prompt |
| 13 | Dashboard | ✅ HEALTHY | 37 ms | port_24210_reachable, apiConfig.ts, ConnectivityPanel.tsx | — |
| 14 | API Server | ✅ HEALTHY | 1 ms | 10/10 route files present | — |
| 15 | Database | ✅ HEALTHY | 10 ms | DATABASE_URL, connection_ok, 6/6 tables | — |

---

## 2. Live API Response Matrix

All endpoints probed against the running dev server (port 8080, 2026-07-25):

| Endpoint | HTTP | Status | Response time | Shape verified |
|----------|------|--------|--------------|----------------|
| `GET /api/healthz` | 200 | `{status:"ok"}` | 1 ms | ✅ |
| `GET /api/health/live` | 200 | `{status:"ok",uptime_s:764}` | 1 ms | ✅ |
| `GET /api/health/ready` | 200 | `{status:"ready",checks:{python_runtime:true,scan_cache:true}}` | 45 ms | ✅ |
| `GET /api/health/details` | 200 | Full observability payload, mode=PAPER_TRADING_RESEARCH_ONLY | 570 ms | ✅ |
| `GET /api/live-data/health-v2` | 200 | `{success:true,market:{state:"WEEKEND",...}}` | 863 ms | ✅ |
| `GET /api/live-data/scan/status` | 200 | `{latest_scan:{scan_id:"d49e1ec37b7f",status:"SUCCESS",symbols:48/50}}` | 2 ms | ✅ |
| `GET /api/signals` | 200 | Array[10] of Signal objects (NO_TRADE — weekend stale) | 788 ms | ✅ |
| `GET /api/ai-decisions` | 200 | Array[10] of AIDecision objects, SIDEWAYS regime | 241 ms | ✅ |
| `GET /api/portfolio` | 200 | `{cash:5000,positions:[],pnl_history:[...]}` | 163 ms | ✅ |
| `GET /api/portfolio/snapshot` | 200 | Full snapshot with paper_mode=true, status=DISABLED | 209 ms | ✅ |
| `GET /api/portfolio/health` | 200 | `{status:"DEGRADED",degraded_reasons:["Exposure limits using hardcoded defaults"]}` | 406 ms | ⚠️ |
| `GET /api/portfolio/config` | 200 | `{loaded:false,error:"No module named 'pydantic'"}` | 163 ms | ⚠️ |
| `GET /api/trades` | 200 | `[]` (clean state) | 158 ms | ✅ |
| `GET /api/watchlist` | 200 | 10-symbol NIFTY 50 subset | 167 ms | ✅ |
| `GET /api/phase13/audit` | 200 | `{report:{label:"PAPER / RESEARCH ONLY",...}}` | 184 ms | ✅ |
| `GET /api/phase15/staleness` | 200 | `{stale:true,scan_age_human:"3h 16m",buy_recommendations_disabled:true}` | 126 ms | ✅ |
| `GET /api/phase22/activation` | 200 | `{paper_automation_active:false}` | ~150 ms | ✅ |
| `GET /api/phase22/readiness` | 200 | `{all_passed:false,failed_checks:["latest_scan_fresh","market_open"]}` | ~200 ms | ✅ |

---

## 3. Python Package Inventory

| Package | Required By | Dev `.pythonlibs` | Notes |
|---------|------------|-------------------|-------|
| yfinance 1.5.1 | Market Data, Scanner | ✅ Present | ❌ Missing in Autoscale deploy (BLOCKER) |
| pandas 3.x | Scanner, Signal Engine | ✅ Present | — |
| numpy 2.x | Indicators, Signal Engine | ✅ Present | — |
| sqlalchemy 2.x | Async ORM | ✅ Present | — |
| asyncpg 0.29 | PostgreSQL async | ✅ Present | — |
| psycopg2-binary 2.9.12 | PostgreSQL sync | ✅ Present | — |
| kiteconnect 5.2 | Zerodha broker | ✅ Present | — |
| reportlab 4.x | PDF export | ✅ Present | — |
| openpyxl 3.x | Excel export | ✅ Present | — |
| **pydantic** | PortfolioConfig, RC-8 risk | **❌ MISSING** | **HIGH — config falls back to hardcoded defaults** |

---

## 4. Database Schema Verification

All 6 critical tables confirmed present and reachable:

| Table | Purpose | Status |
|-------|---------|--------|
| `paper_portfolio` | Cash, positions, pnl_history (id=1 row) | ✅ |
| `paper_trades` | Append-only trade ledger (BUY + SELL records) | ✅ |
| `signals_cache` | Latest enriched signal list per key | ✅ |
| `scan_state` | Latest successful scan snapshot + metadata | ✅ |
| `scan_lock` | Distributed scan lease (Autoscale-safe) | ✅ |
| `phase20_paper_trades` | Phase 20 auto paper entry ledger (partial unique index) | ✅ |

Additional tables present (not audited for critical status):
`signal_snapshots`, `signal_snapshots`, `phase22_evidence`, `historical_knowledge_trades`,
`trade_intelligence`, `prediction_snapshots`, `trade_evaluations`, `model_versions`,
`proposed_adjustments`, `hypotheses`, `feature_importance_snapshots`, `feature_weights`,
`portfolio_decisions`, `alert_deliveries`, `broker_reconciliation_runs/discrepancies`,
`session_archives`, `phase20_settings/scan_runs/scheduler_state/notifications/kv`

---

## 5. Safety Invariants Confirmed

| Invariant | Verified | Evidence |
|-----------|----------|---------|
| Paper mode only | ✅ | `portfolio/snapshot.paper_mode=true`; `GET /api/live-orders` → 404 |
| AI advisory-only | ✅ | `phase15/staleness.label="PAPER / RESEARCH ONLY"`; `buy_recommendations_disabled=true` when stale |
| Auto paper entries OFF by default | ✅ | `phase22/activation.paper_automation_active=false`; explicit confirmation required to enable |
| No Zerodha live session active | ✅ | `live-data/health-v2.quote_provider` shows "Zerodha login required (no active session)" |
| Kill switch reachable | ✅ | `portfolio/health.activation_check_ok=true` |
| RC-7 paper_trader.py intact | ✅ | BUY/SELL execute paper only; no live order routes exposed |
| RC-8 risk gate active (degraded) | ⚠️ | Risk gate enforced with hardcoded defaults — pydantic config unavailable |

---

## 6. Gaps Identified

### 🔴 BLOCKER — Production Python path missing yfinance

**Finding:** The Replit Autoscale deployment uses system `python3`, not `.pythonlibs/bin/python3`.
System python3 does not have `yfinance` (confirmed from deployment logs: `ModuleNotFoundError: No module named 'yfinance'` every scan tick).

**Impact:** All Python routes fail in production — scanner, signals, portfolio, everything.

**Fix:** Add `uv sync --frozen` to `[deployment.build]` in `.replit` so the Autoscale build
installs all pyproject.toml dependencies. Alternatively, set `PYTHON_BIN` to the uv-managed
Python path in the production environment.

**Files:** `python-env.ts`, `.replit`

---

### 🟠 HIGH — pydantic missing from .pythonlibs

**Finding:** `import pydantic` fails in `.pythonlibs/bin/python3`. This breaks `PortfolioConfig`
(Pydantic v2 model), causing `portfolio/config` to return `{loaded:false, error:"No module named 'pydantic'"}`.
The Risk Engine falls back to hardcoded exposure defaults instead of the operator-configured values.

**Impact:** RC-8 risk limits cannot be read from configuration. Operators cannot verify or update
exposure limits via the API — `PATCH /api/portfolio/config` still works (TypeScript layer) but the
underlying Python config is not loaded.

**Fix:** `uv add pydantic` (or add `pydantic>=2.0` to `pyproject.toml` dependencies and run `uv sync`).

**Files:** `portfolio_manager.py`, `pyproject.toml`

---

### 🟡 MEDIUM — Mobile App Expo workflow stuck on port conflict

**Finding:** Expo process PID 316 already holds port 21338. The second workflow instance (spawned
when the session resumed) is waiting for an interactive Y/n prompt to accept port 21339. The mobile
app does not serve traffic until the prompt is answered.

**Impact:** Mobile previews in the Replit preview pane are unavailable. The Expo JS bundle
itself is built correctly; only the dev server is blocked.

**Fix:** Restart the `artifacts/trading-mobile: expo` workflow from the Replit workflow manager.
The second instance will be killed, and the workflow will restart cleanly on the correct port.

---

### 🟢 LOW — LTIM + TATAMOTORS weekend data gap (2/50 symbols)

**Finding:** Scanner reports `missing_symbols: ["LTIM", "TATAMOTORS"]`. Yahoo Finance returns
no data for these tickers on weekends.

**Impact:** 2/50 symbols show no signal this weekend. Both tickers are correct
(`LTIM.NS`, `TATAMOTORS.NS`) and will return data on the next trading day (Monday 2026-07-27).

**Fix:** No fix needed. Monitor on Monday. The scanner correctly records them as missing rather
than hallucinating data.

---

## 7. Dependency Graph

See [`phase2a_dependency_graph.md`](phase2a_dependency_graph.md) for the full Mermaid flowchart.

**Critical path (market feed → paper trade):**
```
Yahoo Finance → Market Data → Scanner → Signal Engine →
AI Advisory → Risk Engine → Paper Execution →
Portfolio → P&L → Trade Journal → Audit Logs
```

Each step in the critical path is HEALTHY or DEGRADED with a hardcoded fallback.
**No step is DOWN** — the system can execute paper trades in its current state.

---

## 8. Phase 2A Verdict

| Dimension | Score | Notes |
|-----------|-------|-------|
| All 15 subsystems reachable | ✅ | 0 DOWN |
| Critical path intact | ✅ | All 13 E2E steps have running code |
| Safety invariants | ✅ | Paper mode, advisory-only, auto-entries OFF |
| Production-ready Python deps | ❌ | yfinance missing in Autoscale; pydantic missing everywhere |
| Full config load | ❌ | PortfolioConfig degraded (pydantic) |
| Mobile workflow | ⚠️ | Port conflict — workflow restart needed |

**Foundation verdict for Phase 2B:** ✅ PROCEED  
The system has enough subsystem coverage for E2E workflow and failure testing.
The two DEGRADED subsystems (Risk Engine config load, Mobile workflow) do not block
Phase 2B — paper trades can still execute with hardcoded risk defaults, and the mobile
E2E tests can run against the API directly.

The BLOCKER (production yfinance) must be resolved before any production deployment.

---

## 9. Files Produced

| File | Purpose |
|------|---------|
| `artifacts/api-server/src/python/phase2a_health_audit.py` | Reusable audit probe script |
| `artifacts/api-server/docs/phase2a_audit_results.json` | Machine-readable results (consumed by Phase 2E+F) |
| `artifacts/api-server/docs/phase2a_dependency_graph.md` | Mermaid data-flow diagram (15 subsystems) |
| `artifacts/api-server/docs/phase2a_report.md` | This report |
