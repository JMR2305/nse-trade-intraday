"""
phase4a_monitor.py — Phase 4A Section 2: Live Session Monitor.

Continuously samples 14 operational metrics during market hours and appends
JSON timeline events to docs/session_timeline_YYYYMMDD.jsonl.

Metrics sampled each tick:
  1.  market_data_freshness_s   — age of most recent scan snapshot
  2.  scanner_latency_ms        — time for the last completed scan
  3.  signals_generated         — signal count from /signals
  4.  ai_recommendations        — breakdown: BUY / WATCH / NO_TRADE
  5.  risk_blocks               — rejected orders from kill-switch or CB
  6.  paper_orders              — open Phase 20 paper positions count
  7.  portfolio_value           — total_equity from /portfolio/snapshot
  8.  realised_pnl              — realised_pnl from /portfolio/snapshot
  9.  sse_reconnect_count       — cumulative reconnect counter (kv)
  10. api_latency_ms            — p95 latency from 5 healthz probes
  11. memory_rss_mb             — RSS of the current process (psutil)
  12. cpu_pct                   — process CPU % (psutil)
  13. errors                    — critical error count since last tick
  14. warnings                  — warning count since last tick

Usage:
    uv run python phase4a_monitor.py --tick         # single sample
    uv run python phase4a_monitor.py --daemon       # loop every 60s until SIGINT
    uv run python phase4a_monitor.py --summary      # summarise today's JSONL
    uv run python phase4a_monitor.py --interval 30  # daemon with custom interval

Output: docs/session_timeline_YYYYMMDD.jsonl (one JSON object per line)

PAPER TRADING / RESEARCH ONLY.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
import datetime
from typing import Any, Optional

_DIR = os.path.dirname(os.path.abspath(__file__))
_DOCS = os.path.join(_DIR, "..", "..", "docs")
os.makedirs(_DOCS, exist_ok=True)

BASE_URL = "http://localhost:8080/api"
LABEL = "PAPER TRADING / RESEARCH ONLY"
DEFAULT_INTERVAL_S = 60

_stop_flag = False


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_ist() -> str:
    try:
        import zoneinfo
        return datetime.datetime.now(zoneinfo.ZoneInfo("Asia/Kolkata")).isoformat()
    except Exception:
        return datetime.datetime.utcnow().isoformat() + "Z"


def _today() -> str:
    return datetime.date.today().isoformat()


def _jsonl_path(date: Optional[str] = None) -> str:
    d = (date or _today()).replace("-", "")
    return os.path.join(_DOCS, f"session_timeline_{d}.jsonl")


def _get(path: str, timeout: float = 6.0) -> tuple[int, Any, float]:
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


def _api_p5_latency(n: int = 5) -> Optional[float]:
    lats = []
    for _ in range(n):
        _, _, ms = _get("/healthz")
        if ms > 0:
            lats.append(ms)
    if not lats:
        return None
    lats.sort()
    return lats[min(int(len(lats) * 0.95), len(lats) - 1)]


# ── Single metric tick ────────────────────────────────────────────────────────

def take_snapshot() -> dict:
    """Sample all 14 metrics and return a timeline event dict."""
    ts = _now_ist()
    event: dict[str, Any] = {
        "timestamp": ts,
        "label": LABEL,
        "event_type": "monitor_tick",
    }

    # 1. Market data freshness
    s, scan, ms = _get("/scan/status")
    freshness_s: Optional[float] = None
    scanner_latency_ms: Optional[float] = None
    if s == 200:
        snap_ts = scan.get("snapshot_ts") or scan.get("last_scan_ts")
        if snap_ts:
            try:
                snap_dt = datetime.datetime.fromisoformat(str(snap_ts).replace("Z", "+00:00"))
                now_utc = datetime.datetime.now(datetime.timezone.utc)
                freshness_s = round((now_utc - snap_dt).total_seconds(), 1)
            except Exception:
                pass
        scanner_latency_ms = scan.get("duration_ms") or scan.get("last_duration_ms")
    event["market_data_freshness_s"] = freshness_s
    event["scanner_latency_ms"] = scanner_latency_ms

    # 3 & 4. Signals + AI recommendations
    s, sigs, ms = _get("/signals")
    signals_generated: Optional[int] = None
    ai_recs: dict = {"BUY": 0, "WATCH": 0, "NO_TRADE": 0, "other": 0}
    if s == 200:
        sig_list = sigs if isinstance(sigs, list) else sigs.get("signals", [])
        signals_generated = len(sig_list)
        for sig in sig_list:
            action = str(sig.get("signal") or sig.get("final_action") or "").upper()
            if action in ("BUY", "STRONG_BUY"):
                ai_recs["BUY"] += 1
            elif action in ("WATCH", "HOLD"):
                ai_recs["WATCH"] += 1
            elif action in ("SELL", "AVOID", "NO_TRADE", "EXIT"):
                ai_recs["NO_TRADE"] += 1
            else:
                ai_recs["other"] += 1
    event["signals_generated"] = signals_generated
    event["ai_recommendations"] = ai_recs

    # 5. Risk blocks (kill switch + circuit breaker active)
    risk_blocks = 0
    s, ks_data, _ = _get("/risk/kill-switch")
    if s == 200 and ks_data.get("active"):
        risk_blocks += 1
    try:
        from phase20_circuit_breaker import is_tripped
        if is_tripped():
            risk_blocks += 1
    except Exception:
        pass
    event["risk_blocks"] = risk_blocks

    # 6. Paper orders (open Phase 20 positions)
    paper_orders: Optional[int] = None
    try:
        from phase20_executor import get_open_trades
        paper_orders = len(get_open_trades())
    except Exception:
        pass
    event["paper_orders"] = paper_orders

    # 7 & 8. Portfolio value + P&L
    s, port, ms = _get("/portfolio/snapshot")
    portfolio_value: Optional[float] = None
    realised_pnl: Optional[float] = None
    unrealised_pnl: Optional[float] = None
    if s == 200:
        portfolio_value = port.get("total_equity") or (
            float(port.get("cash", 0)) + float(port.get("invested_value", 0)))
        realised_pnl = port.get("realised_pnl")
        unrealised_pnl = port.get("unrealised_pnl")
    event["portfolio_value"] = portfolio_value
    event["realised_pnl"] = realised_pnl
    event["unrealised_pnl"] = unrealised_pnl

    # 9. SSE reconnect count (from kv store)
    sse_reconnects: Optional[int] = None
    try:
        import phase20_store as store
        sse_reconnects = int(store.kv_get("sse_reconnect_count") or 0)
    except Exception:
        pass
    event["sse_reconnect_count"] = sse_reconnects

    # 10. API latency p95
    event["api_latency_ms"] = _api_p5_latency(5)

    # 11 & 12. Memory + CPU (psutil optional)
    memory_rss_mb: Optional[float] = None
    cpu_pct: Optional[float] = None
    try:
        import psutil
        proc = psutil.Process(os.getpid())
        memory_rss_mb = round(proc.memory_info().rss / 1024 / 1024, 1)
        cpu_pct = round(psutil.cpu_percent(interval=0.5), 1)
    except ImportError:
        pass
    event["memory_rss_mb"] = memory_rss_mb
    event["cpu_pct"] = cpu_pct

    # 13 & 14. Errors + warnings (read from health endpoint)
    errors = 0
    warnings_count = 0
    s2, h_data, _ = _get("/health/details")
    if s2 == 200:
        errors = int(h_data.get("error_count", 0))
        warnings_count = int(h_data.get("warning_count", 0))
    event["errors"] = errors
    event["warnings"] = warnings_count

    return event


def append_event(event: dict) -> None:
    """Append a single event to today's JSONL file and persist latest tick."""
    path = _jsonl_path()
    with open(path, "a") as f:
        f.write(json.dumps(event, default=str) + "\n")
    # Also write the latest tick so API routes can read it without parsing logs
    latest_path = os.path.join(_DOCS, "monitor_tick_latest.json")
    with open(latest_path, "w") as f:
        json.dump(event, f, default=str)


def print_event(event: dict) -> None:
    ts = event.get("timestamp", "?")[:19]
    print(f"\n  [{ts}] Monitor Tick")
    print(f"  Freshness: {event.get('market_data_freshness_s')}s  "
          f"Scanner: {event.get('scanner_latency_ms')}ms  "
          f"Signals: {event.get('signals_generated')}")
    recs = event.get("ai_recommendations", {})
    print(f"  AI:  BUY={recs.get('BUY',0)}  WATCH={recs.get('WATCH',0)}  "
          f"NO_TRADE={recs.get('NO_TRADE',0)}")
    print(f"  Portfolio: ₹{event.get('portfolio_value')}  "
          f"P&L: ₹{event.get('realised_pnl')}  "
          f"Unrealised: ₹{event.get('unrealised_pnl')}")
    print(f"  Paper orders: {event.get('paper_orders')}  "
          f"Risk blocks: {event.get('risk_blocks')}  "
          f"SSE reconnects: {event.get('sse_reconnect_count')}")
    print(f"  API p95: {event.get('api_latency_ms')}ms  "
          f"Memory: {event.get('memory_rss_mb')}MB  "
          f"CPU: {event.get('cpu_pct')}%  "
          f"Errors: {event.get('errors')}  Warnings: {event.get('warnings')}")


# ── Summary ───────────────────────────────────────────────────────────────────

def summarise(date: Optional[str] = None) -> dict:
    path = _jsonl_path(date)
    if not os.path.exists(path):
        print(f"  No timeline file found: {path}")
        return {}

    events = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except Exception:
                    pass

    if not events:
        print("  No events in timeline.")
        return {}

    n = len(events)
    date_str = (date or _today())
    first_ts = events[0].get("timestamp", "")
    last_ts = events[-1].get("timestamp", "")

    def _avg(key: str) -> Optional[float]:
        vals = [e[key] for e in events if e.get(key) is not None]
        return round(sum(vals) / len(vals), 2) if vals else None

    def _max(key: str) -> Optional[float]:
        vals = [e[key] for e in events if e.get(key) is not None]
        return max(vals) if vals else None

    def _min(key: str) -> Optional[float]:
        vals = [e[key] for e in events if e.get(key) is not None]
        return min(vals) if vals else None

    summary = {
        "date": date_str,
        "generated_at": _now_ist(),
        "label": LABEL,
        "events_recorded": n,
        "first_event": first_ts,
        "last_event": last_ts,
        "avg_freshness_s": _avg("market_data_freshness_s"),
        "avg_scanner_latency_ms": _avg("scanner_latency_ms"),
        "max_signals_generated": _max("signals_generated"),
        "avg_portfolio_value": _avg("portfolio_value"),
        "final_realised_pnl": events[-1].get("realised_pnl"),
        "max_risk_blocks": _max("risk_blocks"),
        "max_paper_orders": _max("paper_orders"),
        "total_sse_reconnects": events[-1].get("sse_reconnect_count"),
        "avg_api_latency_ms": _avg("api_latency_ms"),
        "max_memory_rss_mb": _max("memory_rss_mb"),
        "max_cpu_pct": _max("cpu_pct"),
        "total_errors": _max("errors"),
        "total_warnings": _max("warnings"),
    }

    print(f"\n{'=' * 60}")
    print(f"  Phase 4A Session Monitor Summary — {date_str}")
    print(f"  {n} ticks recorded  ({first_ts[:19]} → {last_ts[:19]})")
    print(f"{'=' * 60}")
    for k, v in summary.items():
        if k not in ("date", "generated_at", "label", "first_event", "last_event"):
            print(f"  {k}: {v}")

    # Persist so API routes can read without log parsing
    summary_path = os.path.join(_DOCS, f"monitor_summary_{date_str.replace('-', '')}.json")
    with open(summary_path, "w") as f:
        json.dump(summary, f, default=str)

    return summary


# ── Daemon ────────────────────────────────────────────────────────────────────

def _handle_sigint(sig, frame):  # type: ignore
    global _stop_flag
    print("\n  [monitor] SIGINT received — stopping gracefully…")
    _stop_flag = True


def run_daemon(interval_s: int = DEFAULT_INTERVAL_S) -> None:
    signal.signal(signal.SIGINT, _handle_sigint)
    print(f"\n{'=' * 60}")
    print(f"  ApexQuant AI — Phase 4A Live Session Monitor")
    print(f"  {LABEL}")
    print(f"  Interval: {interval_s}s  |  Ctrl-C to stop")
    print(f"  Output: {_jsonl_path()}")
    print(f"{'=' * 60}")

    while not _stop_flag:
        try:
            event = take_snapshot()
            append_event(event)
            print_event(event)
        except Exception as e:
            print(f"  [monitor] tick error: {e}")
        if _stop_flag:
            break
        t = 0
        while t < interval_s and not _stop_flag:
            time.sleep(1)
            t += 1

    print("\n  [monitor] stopped.")
    summarise()


# ── CLI ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 4A live session monitor")
    parser.add_argument("--tick", action="store_true", help="Single snapshot")
    parser.add_argument("--daemon", action="store_true", help="Continuous daemon")
    parser.add_argument("--summary", action="store_true", help="Summarise today's timeline")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL_S,
                        help=f"Daemon poll interval in seconds (default {DEFAULT_INTERVAL_S})")
    parser.add_argument("--date", type=str, default=None,
                        help="YYYY-MM-DD for --summary (default: today)")
    args = parser.parse_args()

    if args.tick:
        event = take_snapshot()
        append_event(event)
        print_event(event)
    elif args.summary:
        summarise(args.date)
    elif args.daemon:
        run_daemon(args.interval)
    else:
        # Default: single tick
        event = take_snapshot()
        append_event(event)
        print_event(event)
