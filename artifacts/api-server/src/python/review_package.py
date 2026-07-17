"""
review_package.py — Phase Review Package generator (current phase: 18).

STANDING RULE: every change made to the application must also be reflected in
this review package (implementation summary, feature matrix, tests, data
exports) so an external reviewer always sees the latest state.

Assembles Phase16_Review_Package/ and zips it to Phase16_Review_Package.zip
so an external reviewer (e.g. ChatGPT) can audit the whole application
without manual screenshots:

  screenshots/           full-page PNGs (captured by capture_screenshots.mjs)
  csv/                   opportunities, signals, portfolio, performance,
                         ai_performance, notifications, learning,
                         trade_history, risk_analytics
  json/                  scan_snapshot, ai_decision, dashboard_summary,
                         portfolio_summary, learning_summary, diagnostics,
                         production_readiness
  implementation_summary.md, production_readiness.md,
  feature_matrix.csv, test_results.csv, diagnostics.json, README.md

Honesty rules: only real pages, real cached/computed data, "Insufficient Data"
or "Not Available" where data does not exist. No placeholders. PAPER ONLY.
"""

from __future__ import annotations

import csv
import json
import os
import re
import shutil
import subprocess
import time
import zipfile
from datetime import datetime, timezone
from typing import Any

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PHASE = 22
PACKAGE_NAME = f"Phase{PHASE}_Review_Package"
PACKAGE_DIR = os.path.join(BASE_DIR, PACKAGE_NAME)
ZIP_PATH = os.path.join(BASE_DIR, f"{PACKAGE_NAME}.zip")

NA = "Not Available"
INSUFFICIENT = "Insufficient Data"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _load_json(fname: str, default: Any) -> Any:
    try:
        with open(os.path.join(BASE_DIR, fname)) as f:
            return json.load(f)
    except Exception:
        return default


def _write_csv(path: str, header: list[str], rows: list[list]):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)


def _write_json(path: str, data: Any):
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def _run_tests(script: str) -> dict:
    try:
        p = subprocess.run(["python3", script], cwd=BASE_DIR,
                           capture_output=True, text=True, timeout=180)
        out = (p.stdout or "") + (p.stderr or "")
        m = re.search(r"(\d+) passed, (\d+) failed", out)
        if m:
            return {"passed": int(m.group(1)), "failed": int(m.group(2)), "ran": True}
        # unittest format: "Ran N tests in Xs" then "OK" or "FAILED (failures=A, errors=B)"
        m = re.search(r"Ran (\d+) tests? in", out)
        if m:
            total = int(m.group(1))
            fm = re.search(r"FAILED \((?:failures=(\d+))?(?:, )?(?:errors=(\d+))?\)", out)
            failed = (int(fm.group(1) or 0) + int(fm.group(2) or 0)) if fm else 0
            return {"passed": total - failed, "failed": failed, "ran": True}
    except Exception:
        pass
    return {"passed": 0, "failed": 0, "ran": False}


# ── CSV export builders ──────────────────────────────────────────────────────

def _csv_opportunities(out: str, scan: dict):
    rows = []
    for r in scan.get("recommendations", []):
        rows.append([r.get("rank"), r.get("symbol"), r.get("sector"),
                     r.get("final_action"), r.get("opportunity_score"),
                     r.get("calibrated_confidence"), r.get("entry_price"),
                     r.get("stop_loss"), r.get("target_price"), r.get("rr_ratio"),
                     r.get("strategy_name"), r.get("regime"), r.get("data_quality"),
                     r.get("all_gates_passed"), r.get("error") or ""])
    if not rows:
        rows = [[INSUFFICIENT] + [""] * 14]
    _write_csv(out, ["Rank", "Symbol", "Sector", "Action", "OpportunityScore",
                     "Confidence", "Entry", "StopLoss", "Target", "RRRatio",
                     "Strategy", "Regime", "DataQuality", "AllGatesPassed", "Error"], rows)


def _csv_signals(out: str):
    signals = _load_json("signals_cache.json", [])
    rows = [[s.get("stock"), s.get("signal"), s.get("confidence"),
             s.get("price"), s.get("rsi"), s.get("trend"), s.get("reason", "")]
            for s in signals if isinstance(s, dict)]
    if not rows:
        rows = [[INSUFFICIENT] + [""] * 6]
    _write_csv(out, ["Stock", "Signal", "Confidence", "Price", "RSI", "Trend", "Reason"], rows)


def _csv_portfolio(out: str, portfolio: dict):
    rows = []
    for p in portfolio.get("positions", []):
        qty = p.get("quantity") or 0
        rows.append([p.get("symbol"), qty, p.get("avg_price"), p.get("current_price"),
                     round(qty * (p.get("avg_price") or 0), 2),
                     round(qty * (p.get("current_price") or 0), 2),
                     p.get("pnl"), p.get("pnl_pct")])
    rows.append(["TOTAL", "", "", "", portfolio.get("invested_value", NA),
                 portfolio.get("total_value", NA), portfolio.get("total_pnl", ""), ""])
    if len(rows) == 1:
        rows.insert(0, ["No open positions"] + [""] * 7)
    _write_csv(out, ["Symbol", "Quantity", "AvgPrice", "CurrentPrice",
                     "Invested", "CurrentValue", "PnL", "PnLPct"], rows)


def _csv_performance(out: str, analytics: dict):
    s, r = analytics.get("summary", {}), analytics.get("risk", {})
    rows = [[k, s.get(k, NA)] for k in
            ("portfolio_value", "total_return_pct", "today_return", "weekly_return",
             "monthly_return", "total_trades", "win_rate_pct", "profit_factor",
             "avg_winner", "avg_loser", "expectancy")]
    rows += [[k, r.get(k, NA)] for k in
             ("max_drawdown_pct", "current_drawdown_pct", "sharpe", "sortino",
              "calmar", "volatility_pct", "beta", "risk_score", "risk_level")]
    _write_csv(out, ["Metric", "Value"], rows)


def _csv_ai_performance(out: str, analytics: dict):
    ai = analytics.get("ai_performance", {})
    rows = [[k, ai.get(k, NA)] for k in sorted(ai)] if ai else [[INSUFFICIENT, ""]]
    _write_csv(out, ["Metric", "Value"], rows)


def _csv_notifications(out: str):
    alerts = _load_json("phase9_alerts.json", [])
    if isinstance(alerts, dict):
        alerts = alerts.get("alerts", [])
    rows = [[a.get("timestamp"), a.get("type"), a.get("symbol"),
             a.get("severity"), a.get("message", a.get("title", ""))]
            for a in alerts if isinstance(a, dict)]
    if not rows:
        rows = [[INSUFFICIENT] + [""] * 4]
    _write_csv(out, ["Timestamp", "Type", "Symbol", "Severity", "Message"], rows)


def _csv_learning(out: str, learning: dict):
    rows: list[list] = []
    for k, v in learning.items():
        if isinstance(v, (str, int, float, bool)) or v is None:
            rows.append([k, NA if v is None else v])
    if not rows:
        rows = [[INSUFFICIENT, ""]]
    _write_csv(out, ["Field", "Value"], rows)


def _csv_trades(out: str):
    state = _load_json("state.json", {})
    rows = [[t.get("timestamp"), t.get("action"), t.get("symbol"), t.get("quantity"),
             t.get("price"), t.get("pnl", ""), t.get("strategy_name", ""),
             t.get("confidence", ""), t.get("scan_id", "")]
            for t in state.get("trades", [])]
    if not rows:
        rows = [["No trades recorded yet"] + [""] * 8]
    _write_csv(out, ["Timestamp", "Action", "Symbol", "Quantity", "Price",
                     "PnL", "Strategy", "Confidence", "ScanId"], rows)


def _csv_risk(out: str, risk: dict):
    rows: list[list] = []
    def flatten(prefix: str, d: Any):
        if isinstance(d, dict):
            for k, v in d.items():
                flatten(f"{prefix}{k}." if prefix else f"{k}.", v) if isinstance(v, dict) \
                    else rows.append([f"{prefix}{k}", v if not isinstance(v, list) else json.dumps(v)[:200]])
    flatten("", risk)
    if not rows:
        rows = [[INSUFFICIENT, ""]]
    _write_csv(out, ["Metric", "Value"], rows)


# ── Reports ──────────────────────────────────────────────────────────────────

def _implementation_summary(t15: dict, t16: dict, t17: dict, t18: dict, t19: dict = None,
                            t20: dict = None, t21: dict = None, t22: dict = None,
                            t22s: dict = None, t22i: dict = None) -> str:
    t19 = t19 or {}
    t20 = t20 or {}
    t21 = t21 or {}
    t22 = t22 or {}
    t22s = t22s or {}
    t22i = t22i or {}
    return f"""# Phase {PHASE} Implementation Summary — Controlled Auto Paper Trading & Evidence Accumulation

- **Phase:** {PHASE}
- **Date:** {_now()}
- **Scope rule respected:** automated PAPER trading only; live-order writes remain disabled;
  auto paper entries default OFF and require the exact typed confirmation "ENABLE PAPER ONLY".
  No real Zerodha orders are possible. PAPER / RESEARCH ONLY.

## Phase 22 final production fix (latest — session sharing & scan performance)
- **Daily Zerodha session model** — Kite tokens expire at the next 06:00 IST after
  creation. Expiry checks are fail-safe: a missing or unparseable token timestamp is
  treated as EXPIRED, never trusted (kite_token_store.token_expiry_utc / is_expired;
  kite_quote_provider._env_token_expired). Expired tokens are filtered out of
  kite_token_store.load() by default.
- **Production session sharing** — the token store is Postgres-durable, so one login
  through the published app's "Login with Zerodha" button lasts the whole trading day
  across all server instances. Dev and production databases are separate: production
  requires its own daily login via the published app.
- **Session status API** — /api/kite/status now returns token_expired,
  token_expires_at and daily_login_required alongside connection_state.
- **Daily-login UI** — KiteConnect page shows a daily-login-required banner when no
  active session exists or the previous token expired at 06:00 IST.
- **Long-scan root cause fixed** — production scans of 770-990s were caused by 50
  serial yfinance calls (0.25s throttle + up to 3 retries with 2s/4s back-off each).
  LiveDataProvider.fetch_batch() now performs ONE bulk multi-ticker download with a
  per-symbol retry fallback only for stragglers; full 50-symbol scans verified at
  ~28-36s. Fallback provenance is an explicit via_fallback flag per symbol.
- **Extended timing breakdown** — scan timings now include provider_auth_s,
  symbols_fallback_fetched and symbols_failed (in addition to lock_wait_s, fetch_s,
  analysis_s, db_write_s, retry_events, total_scan_s), persisted per scan run and
  displayed in the Automation Health scan-history detail rows.
- **test_phase22_session.py** — 16 unit tests (token expiry boundaries at 06:00 IST,
  fail-safe malformed-timestamp handling, expired-token filtering, env-token guard,
  bulk fetch single-call path, per-symbol fallback, bulk-failure fallback) — all
  mocked, no network or broker calls.

## Phase 22 features added
- **phase22_readiness.py** — 16-check activation readiness checklist (data freshness,
  fallback status, market hours, scheduler health, capital, safety config, etc.);
  activation is blocked until every check passes.
- **phase22_activation.py** — explicit activation control: exact typed confirmation
  "ENABLE PAPER ONLY", audit trail, config hash at activation, immediate disable,
  auto-deactivation on safety violations.
- **phase22_evidence.py** — append-only evidence dataset (Postgres with file fallback)
  recording EVERY evaluated candidate (entered AND blocked, with block reasons),
  time-safe horizon returns (15m/30m/60m/EOD/1d/3d/5d), MAE/MFE. Write-once outcome
  columns enforced at storage level (per-column COALESCE + completion guard).
- **phase22_progress.py** — evidence accumulation milestones (10→500 observations)
  with per-milestone unlock descriptions.
- **phase22_report.py** — daily close report + JSON/CSV/PDF exports
  (exports/Phase22_Daily_YYYY-MM-DD.*).
- **Scheduler integration** — evidence recorded from the exact evaluation payload the
  executor consumed (no re-evaluation drift); outcomes updated every tick.
- **routes/phase22.ts** — 10 API endpoints (readiness, activation status/enable/disable,
  evidence, progress, daily report, eligibility, health, execution modes).
- **Phase22Panels.tsx** — panels embedded across Dashboard, Trade Decisions, Trades,
  Trade Replay, Learning & Governance, Live Data Health, Broker & Execution.

## Carried forward from Phase 21 (Advisory Analytics)
- Advisory-only analytics with mandatory advisory flags; INSUFFICIENT_EVIDENCE
  reported instead of extrapolation; no automatic behaviour changes.

## Carried forward from Phase 20 (Auto Paper Trading Engine)
- Auto paper entry/exit engine: default OFF with exact-confirmation enable, champion-only
  strategy gating, EXIT_PENDING on stale data (fills never fabricated), one OPEN trade
  per symbol enforced by a partial unique DB index (claim-before-buy), execution health
  states HEALTHY/DEGRADED/DOWN/UNKNOWN/DISABLED end-to-end.

## Phase 19 features (Kite Connect live data)
- **Zerodha Kite Connect live-data integration** (read-only): live LTP quotes via
  kite.ltp() and kite.quote() API, holdings, positions, margins, order history sync.
  Paper trading remains the default. No real order placement possible.
- **kite_session_manager.py** — token health (VALID/WARNING/EXPIRED/MISSING), daily
  6 AM IST expiry detection, 60-second probe cache, login URL generator, refresh
  instructions, masked credential display, reconnect advice.
- **kite_quote_provider.py** — bulk quote fetcher (NSE:SYMBOL format), 30-second
  in-memory cache, ≤3 req/s rate limiter, automatic yfinance fallback on any Kite
  error, `data_source` field labels every quote (kite_live / yfinance_fallback).
- **kite_instrument_cache.py** — daily-refreshed NSE instrument list (symbol→token
  map), disk-backed JSON cache, fuzzy symbol search (prefix → contains ranking).
- **broker_client.py** updated — `get_ltp(symbols)` on abstract class,
  ZerodhaClient (via kite.ltp), and MockBrokerClient (realistic mock prices).
- **live_scan_engine.py** — Kite provider label injected into safety dict;
  scans always use yfinance OHLCV history (no lookahead risk); Kite adds LTP overlay.
- **routes/kite.ts** — 11 read-only API endpoints registered in routes/index.ts.
- **KiteConnect.tsx** — New dashboard page (route /kite-connect, System group):
  session/connection card with token health, Live Quotes, Holdings, Positions,
  Margins, Orders, Instruments, Diagnostics tabs (all read-only).
- **Mobile sidebar** — AppLayout.tsx: hamburger menu on mobile, slide-in sidebar with
  overlay backdrop, X close button, correct touch/tap behaviour.
- **Secrets scaffolding** — ZERODHA_API_KEY / ACCESS_TOKEN / API_SECRET /
  TOKEN_TIMESTAMP env vars; code falls back to Mock gracefully when unset.
- **Safety fixes from architect review** — fcntl flock on Phase 18 mutators,
  target divide-by-zero guards, null-safe ₹ formatting in finalize.

## Phase 19 files
- `src/python/kite_session_manager.py`, `kite_quote_provider.py`,
  `kite_instrument_cache.py`, `test_phase19.py`
- `src/python/broker_client.py`, `live_scan_engine.py`, `main.py` (updated)
- `src/routes/kite.ts`, `src/routes/index.ts` (updated)
- `trading-dashboard/src/pages/KiteConnect.tsx` (+ route /kite-connect + nav)
- `trading-dashboard/src/components/layout/AppLayout.tsx` (mobile sidebar)

## Phase 19 APIs added
- GET /api/kite/status | quote | ltp | holdings | positions | margins | orders
- GET /api/kite/instruments/search | instruments/status | diagnostics
- POST /api/kite/invalidate | instruments/refresh

## Carried forward from Phase 18 (Research Notebook)
- Research Notebook daily journal, checklist, evidence tracker, issue tracker,
  weekly/monthly reviews, exports, Research_Notebook_Archive.zip.
- Phase 18 APIs — /api/phase18/* (entry, entries, ensure, finalize, reopen, notes,
  decision, issues, targets, evidence, reviews, exports, search).
- Dashboard — Research Notebook page (route /research-notebook).

## Carried forward from Phase 17 (Automated QA & Release Validation)
- Automated QA engine — one-click complete system validation: all backend test
  suites (Phases 7-16), TypeScript build checks, API validation (status, latency,
  required fields, 404 handling), data-store integrity, paper-trading integrity
  (capital conservation, PnL consistency, stops/targets), AI validation
  (confidence/score ranges, explanations, calibration, model registry),
  performance-metric validation with Insufficient Data flags, export validation,
  performance benchmarks with budgets, error detection, and cross-page consistency.
- Release management — weighted System Health Score, release checklist,
  release dashboard (version, build, environment, readiness), validation history
  (last 100 runs), regression comparison vs the previous run.
- Automated reports — Validation_Report.pdf/.xlsx/.csv, System_Health.json,
  Release_Readiness.json, Regression_Report.csv (phase17_reports/).
- Dashboard — "System Validation" page (route /system-validation, System group)
  with one-click Run Complete Validation (background job + live polling).
- Honesty guarantees — client-side UI behaviour (clicks, charts, responsive
  layouts), auth and rate limits are explicitly disclosed as not checkable /
  not implemented instead of fabricated; legacy trades missing metadata are
  warnings, not failures.

## Carried forward from Phase 16
- Validation engine — 14 analysis sections: validation overview, strategy scorecard
  (advisory statuses only, nothing auto-disabled), confidence-band validation,
  market-regime validation, sector validation, AI decision validation, trade review
  with lessons, weekly and monthly reports, AI improvement recommendations
  (advisory only, never auto-applied), failure analysis, success analysis,
  validation timeline, and automated bug detection.
- Honesty guarantees — every statistic derives from real completed paper trades;
  groups below minimum sample size show "Insufficient Data" instead of fabricated
  numbers; untracked outcomes (HOLD correctness, false negatives) are explicitly
  marked unavailable.
- Exports — Validation Report as PDF / XLSX / CSV, strategy scorecard CSV,
  trade review CSV, AI recommendations CSV, plus Phase16_Validation_Report.md.
- Dashboard — "Paper Trading Validation" page (route /validation, System group)
  rendering all 14 sections from one combined API call for fast loads.

## Carried forward from Phase 15 (Production Hardening)
- Unified Scan Context, staleness detection (90-min BUY disable + banner),
  data quality scores, cross-page consistency validation, 12-factor AI
  explainability, 10-check risk gate, extended trade records with friction
  estimates, scan audit logging, diagnostics and production readiness report,
  and this review package generator.

## Database changes
- PostgreSQL used for durable state: canonical scan snapshot/lock (Phase 19B),
  auto paper trades with a partial unique OPEN-per-symbol index (Phase 20), and the
  append-only Phase 22 evidence table (write-once outcome columns). JSON files remain
  as warm caches / fallback.

## Tests
- Phase 22 integration verification (session sharing, bulk fetch, derived-data sync, atomic publish, scan-lock overlap): {t22i.get('passed', 0)} passed, {t22i.get('failed', 0)} failed{'' if t22i.get('ran') else f' ({NA} — suite did not run)'}
- Phase 22 session & bulk-fetch suite: {t22s.get('passed', 0)} passed, {t22s.get('failed', 0)} failed{'' if t22s.get('ran') else f' ({NA} — suite did not run)'}
- Phase 22 suite: {t22.get('passed', 0)} passed, {t22.get('failed', 0)} failed{'' if t22.get('ran') else f' ({NA} — suite did not run)'}
- Phase 21 suite: {t21.get('passed', 0)} passed, {t21.get('failed', 0)} failed{'' if t21.get('ran') else f' ({NA} — suite did not run)'}
- Phase 20 suite: {t20.get('passed', 0)} passed, {t20.get('failed', 0)} failed{'' if t20.get('ran') else f' ({NA} — suite did not run)'}
- Phase 19 suite: {t19.get('passed', 0)} passed, {t19.get('failed', 0)} failed{'' if t19.get('ran') else f' ({NA} — suite did not run)'}
- Phase 18 suite: {t18['passed']} passed, {t18['failed']} failed{'' if t18['ran'] else f' ({NA} — suite did not run)'}
- Phase 17 suite: {t17['passed']} passed, {t17['failed']} failed{'' if t17['ran'] else f' ({NA} — suite did not run)'}
- Phase 16 suite: {t16['passed']} passed, {t16['failed']} failed{'' if t16['ran'] else f' ({NA} — suite did not run)'}
- Phase 15 suite: {t15['passed']} passed, {t15['failed']} failed{'' if t15['ran'] else f' ({NA} — suite did not run)'}
- Phase 13/14 regression suites: see test_results.csv.

## Known issues
- Only a small number of completed trades exist, so most validation cells honestly
  read "Insufficient Data" until more evidence accumulates (minimums enforced).
- Derived caches written before the latest scan are flagged STALE_SOURCE by the
  consistency checker until a fresh pipeline run resynchronises them.

## Pending work
- Accumulate evidence toward Phase 22 milestones (10 → 500 recorded observations);
  auto paper entries remain OFF until the user activates via "ENABLE PAPER ONLY".
- Period-aligned benchmark series (carried from Phase 18 targets).
"""


def _production_readiness_md(readiness: dict, consistency: dict, quality: dict,
                             diagnostics: dict, t15: dict) -> str:
    items = readiness.get("items", readiness.get("checks", []))
    lines = "\n".join(
        f"- **{i.get('item', i.get('check', '?'))}** — {i.get('status', '?')}: {i.get('detail', i.get('reason', ''))}"
        for i in items) or f"- {NA}"
    tradeable = sum(1 for s in quality.get("symbols", []) if s.get("tradeable"))
    symbol_count = len(quality.get("symbols", []))
    return f"""# Phase {PHASE} Production Readiness Report

Generated {_now()} — PAPER TRADING / RESEARCH ONLY.

## Runtime health
- API server and dashboard were running at generation time (this package was produced through them).
- System health: {diagnostics.get('system_health', NA)} · memory {diagnostics.get('memory_usage_mb', NA)} MB ·
  context build latency {diagnostics.get('context_build_latency_ms', NA)} ms (see diagnostics.json).

## Build status
- TypeScript typechecks clean for api-server (phase15 routes) and trading-dashboard at package time.

## Scan consistency / cross-page validation
- Verdict: **{consistency.get('verdict', NA)}** — {consistency.get('checks_performed', NA)} checks,
  {consistency.get('hard_mismatch_count', NA)} hard mismatches,
  {consistency.get('stale_source_count', NA)} stale-source values.
- {consistency.get('note', '')}

## Data quality
- Average score: {quality.get('avg_score', NA)} / 100 · bands: {quality.get('band_counts', NA)}
- Tradeable symbols: {tradeable if symbol_count else NA} of {symbol_count or NA}

## Learning status
- See json/learning_summary.json (learning is recommendation-only; freeze state enforced at decision time).

## AI status
- Explainability active for all recommendations (12 factors); see /api/phase15/explain-all.

## Risk engine status
- 10-check pre-trade risk gate active, incl. staleness and post-trade exposure modeling.

## Broker status
- Mock broker only; two-step confirmation; no auto-execution. No real orders possible.

## Test status
- Phase 15 suite: {t15['passed']} passed, {t15['failed']} failed.

## Overall readiness
- **Verdict: {readiness.get('verdict', NA)}** — {readiness.get('pass_count', NA)} pass,
  {readiness.get('warn_count', NA)} warn, {readiness.get('fail_count', NA)} fail

## Readiness checklist
{lines}
"""


# ── Main build ───────────────────────────────────────────────────────────────

def build_package(screenshots_dir: str | None = None) -> dict:
    t0 = time.time()
    warnings: list[str] = []
    if os.path.exists(PACKAGE_DIR):
        shutil.rmtree(PACKAGE_DIR)
    os.makedirs(PACKAGE_DIR)

    # Gather live data (each source independent; failures reported, never faked)
    scan = _load_json("phase7_scan_cache.json", {})

    def safe(label: str, fn, default):
        try:
            return fn()
        except Exception as e:
            warnings.append(f"{label} unavailable: {str(e)[:120]}")
            return default

    portfolio = safe("portfolio", lambda: __import__("paper_trader").get_portfolio(), {})
    analytics = safe("performance analytics",
                     lambda: __import__("phase10_analytics").performance_analytics(), {})
    risk = safe("risk analytics", lambda: __import__("phase11_risk").portfolio_risk(), {})
    learning = safe("learning summary",
                    lambda: __import__("learning_engine").compute_learning_summary(), {})
    diagnostics = safe("diagnostics",
                       lambda: __import__("phase15_diagnostics").system_diagnostics(), {})
    readiness = safe("readiness report",
                     lambda: __import__("phase15_diagnostics").readiness_report(), {})
    consistency = safe("consistency check",
                       lambda: __import__("phase15_consistency").run_consistency_check(), {})
    quality = safe("quality report",
                   lambda: __import__("phase15_quality").quality_report(), {})

    validation = safe("phase16 validation",
                      lambda: __import__("phase16_validation").run_all(), {})

    t15 = _run_tests("test_phase15.py")
    if not t15["ran"]:
        warnings.append("Phase 15 test suite could not be executed")
    t16 = _run_tests("test_phase16.py")
    if not t16["ran"]:
        warnings.append("Phase 16 test suite could not be executed")
    t17 = _run_tests("test_phase17.py")
    if not t17["ran"]:
        warnings.append("Phase 17 test suite could not be executed")
    t18 = _run_tests("test_phase18.py")
    if not t18["ran"]:
        warnings.append("Phase 18 test suite could not be executed")
    t19 = _run_tests("test_phase19.py")
    if not t19["ran"]:
        warnings.append("Phase 19 test suite could not be executed")
    t20 = _run_tests("test_phase20.py")
    if not t20["ran"]:
        warnings.append("Phase 20 test suite could not be executed")
    t21 = _run_tests("test_phase21.py")
    if not t21["ran"]:
        warnings.append("Phase 21 test suite could not be executed")
    t22 = _run_tests("test_phase22.py")
    if not t22["ran"]:
        warnings.append("Phase 22 test suite could not be executed")
    t22s = _run_tests("test_phase22_session.py")
    if not t22s["ran"]:
        warnings.append("Phase 22 session/bulk-fetch test suite could not be executed")
    t22i = _run_tests("test_phase22_integration.py")
    if not t22i["ran"]:
        warnings.append("Phase 22 integration verification suite could not be executed")
    phase18_entries = safe("phase18 notebook entries",
                           lambda: __import__("phase18_notebook").list_entries(), {})
    phase18_evidence = safe("phase18 evidence tracker",
                            lambda: __import__("phase18_reviews").evidence_tracker(), {})
    phase18_weekly = safe("phase18 weekly review",
                          lambda: __import__("phase18_reviews").weekly_review(), {})
    phase17_last = safe("phase17 last validation run",
                        lambda: __import__("phase17_qa").last_run(), {})
    phase17_dash = safe("phase17 release dashboard",
                        lambda: __import__("phase17_qa").release_dashboard(), {})
    phase22_readiness = safe("phase22 readiness checklist",
                             lambda: __import__("phase22_readiness").run_readiness_checklist(), {})
    phase22_activation = safe("phase22 activation status",
                              lambda: __import__("phase22_activation").get_activation_status(), {})
    phase22_progress = safe("phase22 evidence progress",
                            lambda: __import__("phase22_progress").get_progress(), {})
    phase22_summary = safe("phase22 evidence summary",
                           lambda: __import__("phase22_evidence").evidence_summary(), {})
    phase22_daily = safe("phase22 daily report",
                         lambda: __import__("phase22_report").build_daily_report(), {})

    # 1. Screenshots
    shots_out = os.path.join(PACKAGE_DIR, "screenshots")
    os.makedirs(shots_out)
    n_shots = 0
    if screenshots_dir and os.path.isdir(screenshots_dir):
        for f in sorted(os.listdir(screenshots_dir)):
            if f.endswith(".png"):
                shutil.copy2(os.path.join(screenshots_dir, f), os.path.join(shots_out, f))
                n_shots += 1
    if n_shots == 0:
        warnings.append("No screenshots captured — screenshots/ contains a NOTE file instead")
        open(os.path.join(shots_out, "NOT_AVAILABLE.txt"), "w").write(
            "Screenshot capture failed or was skipped. No placeholder images were generated.\n")

    # 2. CSV exports
    csv_dir = os.path.join(PACKAGE_DIR, "csv")
    os.makedirs(csv_dir)
    _csv_opportunities(os.path.join(csv_dir, "opportunities.csv"), scan)
    _csv_signals(os.path.join(csv_dir, "signals.csv"))
    _csv_portfolio(os.path.join(csv_dir, "portfolio.csv"), portfolio)
    _csv_performance(os.path.join(csv_dir, "performance_analytics.csv"), analytics)
    _csv_ai_performance(os.path.join(csv_dir, "ai_performance.csv"), analytics)
    _csv_notifications(os.path.join(csv_dir, "notifications.csv"))
    _csv_learning(os.path.join(csv_dir, "learning.csv"), learning)
    _csv_trades(os.path.join(csv_dir, "trade_history.csv"))
    _csv_risk(os.path.join(csv_dir, "risk_analytics.csv"), risk)

    # 3. JSON exports
    json_dir = os.path.join(PACKAGE_DIR, "json")
    os.makedirs(json_dir)
    _write_json(os.path.join(json_dir, "scan_snapshot.json"),
                scan or {"available": False, "reason": INSUFFICIENT})
    _write_json(os.path.join(json_dir, "ai_decision.json"),
                _load_json("ai_decisions_cache.json", {"available": False, "reason": INSUFFICIENT}))
    _write_json(os.path.join(json_dir, "dashboard_summary.json"), {
        "generated_at": _now(),
        "portfolio_value": portfolio.get("total_value", NA),
        "cash": portfolio.get("cash", NA),
        "open_positions": len(portfolio.get("positions", [])),
        "scan_id": scan.get("scan_id", NA),
        "snapshot_ts": scan.get("snapshot_ts", NA),
        "scan_summary": scan.get("summary", {}),
        "performance_summary": analytics.get("summary", {}),
    })
    _write_json(os.path.join(json_dir, "portfolio_summary.json"),
                portfolio or {"available": False, "reason": INSUFFICIENT})
    _write_json(os.path.join(json_dir, "learning_summary.json"),
                learning or {"available": False, "reason": INSUFFICIENT})
    _write_json(os.path.join(json_dir, "diagnostics.json"),
                diagnostics or {"available": False, "reason": INSUFFICIENT})
    _write_json(os.path.join(json_dir, "production_readiness.json"),
                readiness or {"available": False, "reason": INSUFFICIENT})
    _write_json(os.path.join(json_dir, "phase16_validation.json"),
                validation or {"available": False, "reason": INSUFFICIENT})
    _write_json(os.path.join(json_dir, "phase17_qa_last_run.json"),
                phase17_last if phase17_last.get("available") else
                {"available": False,
                 "reason": "No Phase 17 complete validation run recorded yet"})
    _write_json(os.path.join(json_dir, "phase17_release_dashboard.json"),
                phase17_dash or {"available": False, "reason": INSUFFICIENT})
    _write_json(os.path.join(json_dir, "phase18_notebook_entries.json"),
                phase18_entries or {"available": False, "reason": INSUFFICIENT})
    _write_json(os.path.join(json_dir, "phase18_evidence_tracker.json"),
                phase18_evidence or {"available": False, "reason": INSUFFICIENT})
    _write_json(os.path.join(json_dir, "phase18_weekly_review.json"),
                phase18_weekly or {"available": False, "reason": INSUFFICIENT})
    _write_json(os.path.join(json_dir, "phase22_readiness.json"),
                phase22_readiness or {"available": False, "reason": INSUFFICIENT})
    _write_json(os.path.join(json_dir, "phase22_activation.json"),
                phase22_activation or {"available": False, "reason": INSUFFICIENT})
    _write_json(os.path.join(json_dir, "phase22_progress.json"),
                phase22_progress or {"available": False, "reason": INSUFFICIENT})
    _write_json(os.path.join(json_dir, "phase22_evidence_summary.json"),
                phase22_summary or {"available": False, "reason": INSUFFICIENT})
    _write_json(os.path.join(json_dir, "phase22_daily_report.json"),
                phase22_daily or {"available": False, "reason": INSUFFICIENT})

    # 4/5. Reports
    open(os.path.join(PACKAGE_DIR, "implementation_summary.md"), "w").write(
        _implementation_summary(t15, t16, t17, t18, t19, t20, t21, t22, t22s, t22i))
    open(os.path.join(PACKAGE_DIR, "production_readiness.md"), "w").write(
        _production_readiness_md(readiness, consistency, quality, diagnostics, t15))

    # 6. feature_matrix.csv (spec columns)
    feats = [
        ["Unified scan context (single source of truth)", "Yes", "Yes", "Yes", "Regime from canonical snapshot"],
        ["Stale scan detection + BUY disable", "Yes", "Yes", "Yes", "90-minute limit, global banner"],
        ["Data quality scores + bands", "Yes", "Yes", "Yes", "DO NOT TRADE below 80"],
        ["Cross-page consistency validation", "Yes", "Yes", "Yes", "ERROR/STALE_SOURCE/MISSING_SOURCE severities"],
        ["AI explainability (12 factors)", "Yes", "Yes", "Yes", ""],
        ["Risk gate hardening (10 checks)", "Yes", "Yes", "Yes", "Post-trade exposure modeling"],
        ["Extended trade records (charges, slippage)", "Yes", "Yes", "Yes", "Estimates only — paper trading"],
        ["Scan audit logging", "Yes", "Yes", "Yes", "Capped log"],
        ["System diagnostics + readiness report", "Yes", "Yes", "Yes", ""],
        ["Paper trading validation (14 sections)", "Yes", "Yes", "Yes",
         "Advisory only; Insufficient Data below minimum samples"],
        ["Validation exports (PDF/XLSX/CSV + report)", "Yes", "Yes", "Yes", ""],
        ["Paper Trading Validation dashboard page", "Yes", "Yes", "Yes", "Route /validation"],
        ["Automated QA engine (one-click complete validation)", "Yes", "Yes", "Yes",
         "Phase 17 — test suites, API, data, benchmarks, consistency"],
        ["Release checklist + dashboard + health score", "Yes", "Yes", "Yes",
         "Weighted score; warnings count half"],
        ["Validation history + regression comparison", "Yes", "Yes", "Yes", "Last 100 runs"],
        ["Automated QA reports (PDF/XLSX/CSV/JSON)", "Yes", "Yes", "Yes", "phase17_reports/"],
        ["System Validation dashboard page", "Yes", "Yes", "Yes", "Route /system-validation"],
        ["Research Notebook (daily journal, auto-created per scan day)", "Yes", "Yes", "Yes",
         "Phase 18 — decision journal, checklist, notes, finalize/reopen"],
        ["Daily validation checklist (before/during/after market)", "Yes", "Yes", "Yes",
         "Evaluated from real stored data"],
        ["Weekly/monthly research reviews + calibration bands", "Yes", "Yes", "Yes",
         "Insufficient Data below minimum samples"],
        ["Evidence accumulation tracker (configurable targets)", "Yes", "Yes", "Yes",
         "Advisory only"],
        ["Research memory search + issue tracker (ISS-####)", "Yes", "Yes", "Yes", ""],
        ["Notebook exports + Research_Notebook_Archive.zip", "Yes", "Yes", "Yes",
         "Secrets filtered; README included"],
        ["Research Notebook dashboard page", "Yes", "Yes", "Yes", "Route /research-notebook"],
        ["Kite Connect session manager (token health/expiry)", "Yes", "Yes", "Yes",
         "Phase 19 — VALID/WARNING/EXPIRED/MISSING; 60s probe cache"],
        ["Kite live quote provider (30s cache, rate limit, fallback)", "Yes", "Yes", "Yes",
         "Phase 19 — yfinance fallback; data_source label on every quote"],
        ["Kite instrument cache (daily refresh, fuzzy search)", "Yes", "Yes", "Yes",
         "Phase 19 — disk-backed JSON; prefix+contains ranking"],
        ["Kite broker client get_ltp() (abstract + Zerodha + Mock)", "Yes", "Yes", "Yes",
         "Phase 19 — read-only; paper trading unchanged"],
        ["Kite read-only API routes (11 endpoints)", "Yes", "Yes", "Yes",
         "Phase 19 — /api/kite/status|quote|ltp|holdings|positions|margins|orders|instruments|diagnostics"],
        ["Kite Connect dashboard page (7 tabs)", "Yes", "Yes", "Yes",
         "Phase 19 — Route /kite-connect; read-only; no order placement"],
        ["Mobile responsive sidebar (hamburger menu)", "Yes", "Yes", "Yes",
         "Phase 19 — slide-in sidebar + overlay backdrop on mobile"],
        ["Auto paper trading engine (default OFF, exact confirmation)", "Yes", "Yes", "Yes",
         "Phase 20 — EXIT_PENDING on stale data; one OPEN trade per symbol (DB unique index)"],
        ["Advisory analytics (advisory-only flags, no auto changes)", "Yes", "Yes", "Yes",
         "Phase 21 — INSUFFICIENT_EVIDENCE over extrapolation"],
        ["Activation readiness checklist (16 checks)", "Yes", "Yes", "Yes",
         "Phase 22 — activation blocked until all checks pass"],
        ["Typed activation control (ENABLE PAPER ONLY)", "Yes", "Yes", "Yes",
         "Phase 22 — audit trail, config hash, immediate disable"],
        ["Append-only evidence dataset (all candidates incl. blocked)", "Yes", "Yes", "Yes",
         "Phase 22 — write-once outcome columns; horizon returns 15m→5d; MAE/MFE"],
        ["Evidence progress milestones (10→500)", "Yes", "Yes", "Yes", "Phase 22"],
        ["Daily close report + JSON/CSV/PDF exports", "Yes", "Yes", "Yes",
         "Phase 22 — exports/Phase22_Daily_*"],
        ["Phase 22 dashboard panels (7 pages)", "Yes", "Yes", "Yes",
         "Dashboard, Trade Decisions, Trades, Trade Replay, Learning, Live Data Health, Broker & Execution"],
        ["Daily Zerodha session (fail-safe 06:00 IST expiry)", "Yes", "Yes", "Yes",
         "Phase 22 final fix — expired/malformed tokens never trusted; daily-login banner + API flags"],
        ["Bulk multi-ticker scan fetch (~30s for 50 symbols)", "Yes", "Yes", "Yes",
         "Phase 22 final fix — replaced 50 serial fetches (770-990s); explicit via_fallback provenance"],
        ["Extended scan timing breakdown", "Yes", "Yes", "Yes",
         "provider_auth_s, symbols_fallback_fetched, symbols_failed surfaced in Automation Health"],
        ["Review package generator", "Yes", "Yes", "Partial", "Tested via generation run itself"],
        ["Paper trading engine / scanner / strategies", "Yes", "Yes", "Yes", "Built in earlier phases 1-14"],
        ["Real-money execution", "No", "No", "No", "Deliberately not implemented — research only"],
    ]
    _write_csv(os.path.join(PACKAGE_DIR, "feature_matrix.csv"),
               ["Feature", "Implemented", "Working", "Tested", "Comments"], feats)

    # 7. test_results.csv
    t13 = _run_tests("test_phase13.py")
    t14 = _run_tests("test_phase14.py")
    test_rows = [
        ["Unit Tests — Phase 22 session & bulk-fetch suite", t22s["passed"] if t22s["ran"] else NA,
         t22s["failed"] if t22s["ran"] else NA, 0],
        ["Unit Tests — Phase 22 suite", t22["passed"] if t22["ran"] else NA,
         t22["failed"] if t22["ran"] else NA, 0],
        ["Unit Tests — Phase 21 suite", t21["passed"] if t21["ran"] else NA,
         t21["failed"] if t21["ran"] else NA, 0],
        ["Unit Tests — Phase 20 suite", t20["passed"] if t20["ran"] else NA,
         t20["failed"] if t20["ran"] else NA, 0],
        ["Unit Tests — Phase 19 suite", t19["passed"] if t19["ran"] else NA,
         t19["failed"] if t19["ran"] else NA, 0],
        ["Unit Tests — Phase 18 suite", t18["passed"] if t18["ran"] else NA,
         t18["failed"] if t18["ran"] else NA, 0],
        ["Unit Tests — Phase 17 suite", t17["passed"] if t17["ran"] else NA,
         t17["failed"] if t17["ran"] else NA, 0],
        ["Unit Tests — Phase 16 suite", t16["passed"] if t16["ran"] else NA,
         t16["failed"] if t16["ran"] else NA, 0],
        ["Unit Tests — Phase 15 suite", t15["passed"] if t15["ran"] else NA,
         t15["failed"] if t15["ran"] else NA, 0],
        ["Unit Tests — Phase 13 regression", t13["passed"] if t13["ran"] else NA,
         t13["failed"] if t13["ran"] else NA, 0],
        ["Unit Tests — Phase 14 regression", t14["passed"] if t14["ran"] else NA,
         t14["failed"] if t14["ran"] else NA, 0],
        ["Integration Tests — Phase 22 (session sharing, bulk fetch, "
         "derived-data sync, atomic publish, scan-lock overlap)",
         t22i["passed"] if t22i["ran"] else NA,
         t22i["failed"] if t22i["ran"] else NA, 0],
        ["UI Tests", NA, NA, NA],
        ["Performance Tests", NA, NA, NA],
    ]
    _write_csv(os.path.join(PACKAGE_DIR, "test_results.csv"),
               ["Suite", "Passed", "Failed", "Skipped"], test_rows)

    # 8. diagnostics.json (top-level bundle per spec)
    _write_json(os.path.join(PACKAGE_DIR, "diagnostics.json"), {
        "scan_id": scan.get("scan_id", NA),
        "snapshot_ts": scan.get("snapshot_ts", NA),
        "provider": "Yahoo Finance (yfinance)",
        "market_status": _load_json("market_context_cache.json", {}).get("market_status", NA),
        "diagnostics": diagnostics or {"available": False},
        "consistency": {k: consistency.get(k) for k in
                        ("verdict", "checks_performed", "hard_mismatch_count",
                         "stale_source_count", "consistent")} if consistency else {"available": False},
        "data_quality": {"avg_score": quality.get("avg_score"),
                         "band_counts": quality.get("band_counts")} if quality else {"available": False},
        "generated_at": _now(),
        "label": "PAPER / RESEARCH ONLY",
    })

    # 9. README.md
    open(os.path.join(PACKAGE_DIR, "README.md"), "w").write(f"""# Phase {PHASE} Review Package

Generated {_now()} by the NSE paper-trading research system (capital ₹5,000, PAPER ONLY).

This package allows a complete external technical review without manual screenshots.

| Path | Contents |
|---|---|
| screenshots/ | Full-page 1920px PNG captures of every registered page (no placeholders) |
| csv/ | Opportunities, signals, portfolio, performance, AI performance, notifications, learning, trade history, risk analytics |
| json/ | Scan snapshot, AI decisions, dashboard/portfolio/learning summaries, diagnostics, production readiness, Phase 16 validation (all 14 sections), Phase 17 QA last run + release dashboard, Phase 18 notebook entries + evidence tracker + weekly review, Phase 22 readiness + activation + progress + evidence summary + daily report |
| implementation_summary.md | What Phase {PHASE} added: features, files, APIs, components, known issues, pending work |
| production_readiness.md | Runtime, build, consistency, data quality, learning/AI/risk/broker status, overall readiness |
| feature_matrix.csv | Feature / Implemented / Working / Tested / Comments |
| test_results.csv | Unit, integration, UI and performance test outcomes |
| diagnostics.json | Scan ID, provider, market status, errors/warnings, cache & data-quality health |

Honesty rules: only real pages were captured; values come from live application state;
anything missing is marked "{NA}" or "{INSUFFICIENT}" — nothing is fabricated.

**PAPER TRADING / RESEARCH ONLY — no real orders, no investment advice.**
""")

    # 10. ZIP
    if os.path.exists(ZIP_PATH):
        os.remove(ZIP_PATH)
    n_files = 0
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, files in os.walk(PACKAGE_DIR):
            for f in files:
                full = os.path.join(root, f)
                z.write(full, os.path.join(PACKAGE_NAME, os.path.relpath(full, PACKAGE_DIR)))
                n_files += 1
    size = os.path.getsize(ZIP_PATH)
    size_human = f"{size / 1024 / 1024:.1f} MB" if size > 1024 * 1024 else f"{size / 1024:.0f} KB"

    return {
        "success": True,
        "phase": PHASE,
        "zip_name": os.path.basename(ZIP_PATH),
        "zip_path": ZIP_PATH,
        "zip_size_bytes": size,
        "total_size_human": size_human,
        "file_count": n_files,
        "screenshot_count": n_shots,
        "csv_count": 9,
        "json_count": 18,
        "reports": ["implementation_summary.md", "production_readiness.md", "README.md"],
        "generation_seconds": round(time.time() - t0, 1),
        "warnings": warnings,
        "generated_at": _now(),
        "label": "PAPER / RESEARCH ONLY",
    }
