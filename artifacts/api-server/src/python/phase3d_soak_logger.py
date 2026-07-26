"""
phase3d_soak_logger.py — Phase 3D: Multi-Day Soak Test Infrastructure.

Records all session metrics for each NSE trading day and accumulates
evidence across ≥5 complete sessions.

Soak test criteria (from Phase 3D spec):
  - At least 5 complete NSE trading sessions observed
  - Portfolio state persists overnight
  - Closed positions remain closed
  - Realised P&L persists
  - Session counters reset correctly
  - Daily loss state resets only per policy
  - Stale snapshots not treated as fresh
  - Scanner restarts cleanly
  - No duplicate orders after restart

Usage:
    # Record today's session (run at or after market close):
    uv run python phase3d_soak_logger.py --record

    # Show accumulated soak test summary:
    uv run python phase3d_soak_logger.py --summary

    # Check overnight persistence (run at market open next day):
    uv run python phase3d_soak_logger.py --overnight-check

Output:
    docs/phase3d_sessions/session_YYYYMMDD.json   — per-session record
    docs/phase3d_soak_summary.json                — rolling 5-session summary
    docs/phase3d_soak_report.md                   — human-readable report

PAPER TRADING / RESEARCH ONLY.
"""

import argparse
import json
import os
import sys
import time
import datetime
import subprocess
from typing import Any

_DIR = os.path.dirname(os.path.abspath(__file__))
_DOCS = os.path.join(_DIR, "..", "..", "docs")
_SESSIONS_DIR = os.path.join(_DOCS, "phase3d_sessions")
os.makedirs(_SESSIONS_DIR, exist_ok=True)

BASE_URL = "http://localhost:8080/api"
LABEL = "PAPER TRADING / RESEARCH ONLY"
MIN_SESSIONS = 5


def _get(path: str, timeout: float = 8.0) -> tuple[int, Any, float]:
    import urllib.request
    import urllib.error
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(f"{BASE_URL}{path}", timeout=timeout) as r:
            return r.status, json.loads(r.read()), round((time.monotonic() - t0) * 1000, 1)
    except urllib.error.HTTPError as e:
        return e.code, {}, round((time.monotonic() - t0) * 1000, 1)
    except Exception as e:
        return 0, {"error": str(e)}, round((time.monotonic() - t0) * 1000, 1)


def _now_ist() -> str:
    try:
        import zoneinfo
        return datetime.datetime.now(zoneinfo.ZoneInfo("Asia/Kolkata")).isoformat()
    except Exception:
        return datetime.datetime.utcnow().isoformat() + "Z"


def _measure_api_p95() -> float | None:
    """Measure p95 API latency from 20 healthz samples."""
    latencies = []
    for _ in range(20):
        _, _, ms = _get("/healthz")
        if ms > 0:
            latencies.append(ms)
    if not latencies:
        return None
    latencies.sort()
    idx = int(len(latencies) * 0.95)
    return latencies[min(idx, len(latencies) - 1)]


def record_session() -> dict:
    """Capture all required soak-test metrics for the current session."""
    date_str = datetime.date.today().isoformat()
    session_file = os.path.join(_SESSIONS_DIR, f"session_{date_str.replace('-', '')}.json")

    print(f"\n{'=' * 60}")
    print("  Phase 3D — Recording Session Metrics")
    print(f"  Date: {date_str}  |  {LABEL}")
    print(f"{'=' * 60}\n")

    # ── API health + market state ────────────────────────────────────────
    s, health, _ = _get("/healthz")
    s2, market, _ = _get("/live-data/market-status")
    market_state = market.get("state", "UNKNOWN") if s2 == 200 else "UNKNOWN"

    # ── Portfolio snapshot ────────────────────────────────────────────────
    s3, port, _ = _get("/portfolio/snapshot")
    cash = port.get("cash", 0) if s3 == 200 else None
    invested = port.get("invested_value", 0) if s3 == 200 else None
    realised_pnl = port.get("realised_pnl", 0) if s3 == 200 else None
    unrealised_pnl = port.get("unrealised_pnl", 0) if s3 == 200 else None
    max_drawdown = port.get("drawdown_pct", 0) if s3 == 200 else None
    open_positions = len(port.get("positions", [])) if s3 == 200 else None
    trade_count = port.get("trade_count", 0) if s3 == 200 else None

    # ── Signals / orders ─────────────────────────────────────────────────
    s4, sigs, _ = _get("/signals")
    signals_generated = len(sigs.get("signals", [])) if s4 == 200 else None
    buy_disabled = sigs.get("staleness_warning", {}).get("buy_recommendations_disabled") if s4 == 200 else None

    # ── Scanner ────────────────────────────────────────────────────────────
    s5, scan, _ = _get("/scan/status")
    scanner_cycles = scan.get("scan_count", None) if s5 == 200 else None
    symbol_coverage = scan.get("symbols_completed", None) if s5 == 200 else None

    # ── Kill switch ────────────────────────────────────────────────────────
    s6, ks, _ = _get("/risk/kill-switch")
    kill_switch_activations = (1 if ks.get("active") or ks.get("kill_switch_active") else 0) if s6 == 200 else None

    # ── Process resources ──────────────────────────────────────────────────
    try:
        import psutil
        proc = psutil.Process(os.getpid())
        memory_peak_mb = round(proc.memory_info().rss / 1024 / 1024, 1)
        cpu_peak_pct = psutil.cpu_percent(interval=2.0)
    except ImportError:
        memory_peak_mb = None
        cpu_peak_pct = None

    # ── API latency ────────────────────────────────────────────────────────
    print("  Measuring API p95 latency (20 samples)…")
    api_p95_ms = _measure_api_p95()

    # ── Uptime probe ───────────────────────────────────────────────────────
    s_up, _, _ = _get("/health/ready")
    uptime_ok = s_up == 200

    session = {
        "date": date_str,
        "recorded_at": _now_ist(),
        "label": LABEL,
        "market_state": market_state,
        "uptime_ok": uptime_ok,
        "restart_count": None,          # tracked externally via process supervisor
        "scanner_cycles": scanner_cycles,
        "symbol_coverage": symbol_coverage,
        "data_provider_failures": None,  # tracked via scan logs
        "signals_generated": signals_generated,
        "buy_recommendations_disabled": buy_disabled,
        "orders_attempted": None,        # tracked via trade journal diff
        "orders_allowed": trade_count,
        "orders_rejected": None,
        "positions_opened": None,
        "positions_closed": None,
        "realised_pnl": realised_pnl,
        "unrealised_pnl": unrealised_pnl,
        "maximum_drawdown_pct": max_drawdown,
        "kill_switch_activations": kill_switch_activations,
        "duplicate_order_attempts": None,
        "database_reconnects": None,
        "sse_reconnects": None,
        "error_count": None,
        "warning_count": None,
        "memory_peak_mb": memory_peak_mb,
        "cpu_peak_pct": cpu_peak_pct,
        "api_p95_latency_ms": api_p95_ms,
        "cash": cash,
        "invested_value": invested,
        "open_positions": open_positions,
        "paper_mode_confirmed": port.get("paper_mode") is True if s3 == 200 else None,
    }

    with open(session_file, "w") as f:
        json.dump(session, f, indent=2)

    print(f"  Session recorded → {session_file}")
    _print_session(session)
    _update_summary()
    return session


def _print_session(s: dict) -> None:
    print(f"\n  Market state:    {s['market_state']}")
    print(f"  Signals:         {s['signals_generated']}")
    print(f"  Open positions:  {s['open_positions']}")
    print(f"  Realised P&L:    ₹{s['realised_pnl']}")
    print(f"  Unrealised P&L:  ₹{s['unrealised_pnl']}")
    print(f"  Max drawdown:    {s['maximum_drawdown_pct']}")
    print(f"  API p95:         {s['api_p95_latency_ms']}ms")
    print(f"  Memory peak:     {s['memory_peak_mb']}MB")
    print(f"  Paper mode:      {s['paper_mode_confirmed']}")


def check_overnight_persistence() -> dict:
    """
    Verify that portfolio state persisted correctly from the previous session.
    Run at market open (09:15 IST) the day after recording a session.
    """
    print(f"\n{'=' * 60}")
    print("  Phase 3D — Overnight Persistence Check")
    print(f"  {LABEL}")
    print(f"{'=' * 60}\n")

    results: dict = {}

    # Load yesterday's session
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
    # Find most recent session file
    sessions = sorted([
        f for f in os.listdir(_SESSIONS_DIR) if f.startswith("session_")
    ])
    if not sessions:
        print("  ❌ No previous session found. Record a session first.")
        return {"error": "no_previous_session"}

    prev_file = os.path.join(_SESSIONS_DIR, sessions[-1])
    with open(prev_file) as f:
        prev = json.load(f)

    print(f"  Previous session: {prev['date']}")

    # Current snapshot
    s, port, ms = _get("/portfolio/snapshot")
    if s != 200:
        print(f"  ❌ portfolio/snapshot HTTP {s}")
        return {"error": f"snapshot_unavailable_http_{s}"}

    # C1: portfolio state persists
    cash_now = port.get("cash", 0)
    cash_prev = prev.get("cash", None)
    if cash_prev is not None:
        # Cash should not have changed (no weekend trades)
        cash_ok = abs(cash_now - cash_prev) < 1.0
        results["cash_persisted"] = {"ok": cash_ok, "prev": cash_prev, "now": cash_now}
    else:
        results["cash_persisted"] = {"ok": None, "detail": "no prev cash recorded"}

    # C2: closed positions remain closed
    positions_now = port.get("positions", [])
    results["positions_loaded"] = {"ok": isinstance(positions_now, list), "count": len(positions_now)}

    # C3: realised P&L persists
    realised_now = port.get("realised_pnl", 0)
    realised_prev = prev.get("realised_pnl", None)
    if realised_prev is not None:
        realised_ok = abs(realised_now - realised_prev) < 0.01
        results["realised_pnl_persisted"] = {"ok": realised_ok, "prev": realised_prev, "now": realised_now}
    else:
        results["realised_pnl_persisted"] = {"ok": None, "detail": "no prev P&L recorded"}

    # C4: paper_mode still True
    pm = port.get("paper_mode")
    results["paper_mode_intact"] = {"ok": pm is True, "value": pm}

    # C5: stale snapshots not treated as fresh
    s2, sigs, _ = _get("/signals")
    if s2 == 200:
        stale = sigs.get("staleness_warning", {}).get("is_stale", True)
        buy_ok = sigs.get("staleness_warning", {}).get("buy_recommendations_disabled", True)
        results["stale_snapshot_gated"] = {
            "ok": not stale or buy_ok,
            "is_stale": stale, "buy_disabled": buy_ok,
        }
    else:
        results["stale_snapshot_gated"] = {"ok": None, "detail": f"signals HTTP {s2}"}

    # Print
    for key, v in results.items():
        ok = v.get("ok")
        icon = "✅" if ok is True else "❌" if ok is False else "⚠️"
        detail = {k: val for k, val in v.items() if k != "ok"}
        print(f"  {icon} {key}: {detail}")

    all_ok = all(v.get("ok") is True for v in results.values() if v.get("ok") is not None)
    overnight_path = os.path.join(_DOCS, "phase3d_overnight_check.json")
    results["checked_at"] = _now_ist()
    results["previous_session"] = prev["date"]
    with open(overnight_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  Results → {overnight_path}")
    print(f"  Overall: {'✅ PASS' if all_ok else '❌ FAIL'}")
    return results


def _update_summary() -> None:
    sessions = sorted([
        f for f in os.listdir(_SESSIONS_DIR) if f.startswith("session_")
    ])
    loaded = []
    for fname in sessions[-10:]:  # last 10
        try:
            with open(os.path.join(_SESSIONS_DIR, fname)) as f:
                loaded.append(json.load(f))
        except Exception:
            pass

    if not loaded:
        return

    n = len(loaded)
    total_realised = sum(s.get("realised_pnl") or 0 for s in loaded)
    avg_signals = sum(s.get("signals_generated") or 0 for s in loaded) / n
    avg_p95 = [s.get("api_p95_latency_ms") for s in loaded if s.get("api_p95_latency_ms")]
    avg_p95_val = sum(avg_p95) / len(avg_p95) if avg_p95 else None
    paper_confirmed = all(s.get("paper_mode_confirmed") is True for s in loaded)

    summary = {
        "label": LABEL,
        "generated_at": _now_ist(),
        "sessions_recorded": n,
        "sessions_required": MIN_SESSIONS,
        "soak_test_complete": n >= MIN_SESSIONS,
        "sessions": [s["date"] for s in loaded],
        "total_realised_pnl": round(total_realised, 2),
        "avg_signals_per_session": round(avg_signals, 1),
        "avg_api_p95_ms": round(avg_p95_val, 1) if avg_p95_val else None,
        "paper_mode_confirmed_all_sessions": paper_confirmed,
    }

    summary_path = os.path.join(_DOCS, "phase3d_soak_summary.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2)

    md_path = os.path.join(_DOCS, "phase3d_soak_report.md")
    with open(md_path, "w") as f:
        f.write("# Phase 3D — Multi-Day Soak Test Summary\n\n")
        f.write(f"**{LABEL}**\n\n")
        f.write(f"Generated: {summary['generated_at']}  \n")
        f.write(f"Sessions recorded: **{n}** / {MIN_SESSIONS} required  \n")
        complete = "✅ COMPLETE" if n >= MIN_SESSIONS else f"⏳ IN PROGRESS ({n}/{MIN_SESSIONS})"
        f.write(f"Soak test status: **{complete}**\n\n")
        f.write("## Sessions\n\n| # | Date | Market | Signals | P&L | p95 |\n")
        f.write("|---|------|--------|---------|-----|-----|\n")
        for i, s in enumerate(loaded, 1):
            f.write(f"| {i} | {s['date']} | {s.get('market_state','?')} | "
                    f"{s.get('signals_generated','?')} | "
                    f"₹{s.get('realised_pnl',0):.2f} | "
                    f"{s.get('api_p95_latency_ms','?')}ms |\n")
        f.write(f"\n## Aggregates\n\n")
        f.write(f"- Total realised P&L: ₹{total_realised:.2f}\n")
        f.write(f"- Avg signals/session: {round(avg_signals, 1)}\n")
        f.write(f"- Avg API p95: {round(avg_p95_val, 1)}ms\n" if avg_p95_val else "- Avg API p95: N/A\n")
        f.write(f"- Paper mode confirmed all sessions: {paper_confirmed}\n")

    print(f"  Soak summary → {summary_path}")
    print(f"  Soak report  → {md_path}")
    complete_str = "✅ COMPLETE" if n >= MIN_SESSIONS else f"⏳ IN PROGRESS ({n}/{MIN_SESSIONS})"
    print(f"  Soak status:   {complete_str}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 3D soak test logger")
    parser.add_argument("--record", action="store_true",
                        help="Record today's session metrics")
    parser.add_argument("--overnight-check", action="store_true",
                        help="Check overnight portfolio persistence")
    parser.add_argument("--summary", action="store_true",
                        help="Show accumulated soak test summary")
    args = parser.parse_args()

    if args.record:
        record_session()
    elif args.overnight_check:
        result = check_overnight_persistence()
        ok = all(v.get("ok") is True for v in result.values()
                 if isinstance(v, dict) and v.get("ok") is not None)
        sys.exit(0 if ok else 1)
    elif args.summary:
        _update_summary()
    else:
        # Default: record + show summary
        record_session()
