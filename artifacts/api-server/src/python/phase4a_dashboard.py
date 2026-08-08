"""
phase4a_dashboard.py — Aggregated dashboard data for:
  1. Phase 4A – Controlled Paper Trading Operations  (build_phase4a_dashboard)
  2. Paper Trading Validation page                    (build_validation_dashboard)

SOURCE-OF-TRUTH RULES (no duplicated calculations, no placeholders):
  - Paper trade ledger  : phase20_paper_trades (via phase20_executor connection)
  - Portfolio store     : portfolio_store.INITIAL_CAPITAL
  - Replay store        : replay_engine.build_replay() pipeline_counts / stages
  - Pipeline snapshot   : scan_state_store.load_latest_snapshot()
  - Risk snapshot       : gate_* fields inside the scan snapshot recommendations
  - Decision snapshot   : ai_decisions_cache.json + snapshot final_action counts
  - Market context      : intelligence.get_cached_market_context()

Every metric returned here can be traced to one of those stores. Values that
genuinely have no backend source are returned as null with a `note`, never as
a fabricated number.
"""
from __future__ import annotations

import json
import os
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from statistics import mean, pstdev
from typing import Any, Dict, List, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IST = timezone(timedelta(hours=5, minutes=30))


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _parse_ts(v: Any) -> Optional[datetime]:
    if not v:
        return None
    try:
        s = str(v).replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _ist_date(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    return dt.astimezone(IST).date().isoformat()


def _load_ledger() -> List[Dict[str, Any]]:
    """All rows from phase20_paper_trades (the canonical paper trade ledger)."""
    import phase20_executor as p20
    return p20.get_ledger(limit=10_000)


def _load_snapshot() -> Optional[Dict[str, Any]]:
    import scan_state_store
    return scan_state_store.load_latest_snapshot()


def _load_market_context() -> Dict[str, Any]:
    try:
        from intelligence import get_cached_market_context
        return get_cached_market_context() or {}
    except Exception:
        return {}


def _load_ai_decisions() -> List[Dict[str, Any]]:
    try:
        with open(os.path.join(BASE_DIR, "ai_decisions_cache.json")) as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _build_replay_cached() -> Optional[Dict[str, Any]]:
    try:
        import replay_engine
        snap = _load_snapshot()
        if not snap:
            return None
        rep = replay_engine.build_replay(snap.get("scan_id") or "")
        if rep.get("error"):
            return None
        return rep
    except Exception:
        return None


def _proc_system_metrics() -> Dict[str, Any]:
    """CPU / memory from /proc (no psutil dependency)."""
    out: Dict[str, Any] = {"cpu_pct": None, "memory_pct": None, "memory_used_mb": None}
    try:
        def cpu_sample():
            with open("/proc/stat") as f:
                parts = f.readline().split()[1:]
            vals = [int(x) for x in parts]
            idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
            return idle, sum(vals)
        i1, t1 = cpu_sample()
        time.sleep(0.25)
        i2, t2 = cpu_sample()
        dt_total = t2 - t1
        if dt_total > 0:
            out["cpu_pct"] = round(100.0 * (1 - (i2 - i1) / dt_total), 1)
    except Exception:
        pass
    try:
        mem: Dict[str, int] = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":", 1)
                mem[k] = int(v.strip().split()[0])  # kB
        total = mem.get("MemTotal", 0)
        avail = mem.get("MemAvailable", 0)
        if total:
            out["memory_pct"] = round(100.0 * (total - avail) / total, 1)
            out["memory_used_mb"] = round((total - avail) / 1024.0, 0)
    except Exception:
        pass
    return out


def _stage_duration(rep: Optional[Dict], stage_id: str) -> Optional[float]:
    if not rep:
        return None
    for s in rep.get("stages") or []:
        if s.get("id") == stage_id:
            d = s.get("duration_ms")
            return round(d / 1000.0, 3) if isinstance(d, (int, float)) else None
    return None


# ---------------------------------------------------------------------------
# ledger slicing
# ---------------------------------------------------------------------------

def _ledger_rows_for_day(rows: List[Dict], day_ist: str) -> Dict[str, List[Dict]]:
    fills = [r for r in rows if r.get("fill_ts") and _ist_date(_parse_ts(r["fill_ts"])) == day_ist
             and r.get("status") != "CANCELLED"]
    exits = [r for r in rows if r.get("exit_ts") and _ist_date(_parse_ts(r["exit_ts"])) == day_ist
             and r.get("status") == "CLOSED"]
    cancelled = [r for r in rows if r.get("status") == "CANCELLED"
                 and _ist_date(_parse_ts(r.get("fill_ts") or r.get("created_at"))) == day_ist]
    return {"fills": fills, "exits": exits, "cancelled": cancelled}


def _hold_minutes(r: Dict) -> Optional[float]:
    a, b = _parse_ts(r.get("fill_ts")), _parse_ts(r.get("exit_ts"))
    if a and b:
        return round((b - a).total_seconds() / 60.0, 1)
    return None


def _closed_stats(closed: List[Dict]) -> Dict[str, Any]:
    """Win/loss stats over CLOSED rows (realized_pnl is the ledger's net figure)."""
    pnls = [float(r.get("realized_pnl") or 0.0) for r in closed]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    holds = [h for h in (_hold_minutes(r) for r in closed) if h is not None]
    gross_win, gross_loss = sum(wins), abs(sum(losses))
    return {
        "trades": len(closed),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(100.0 * len(wins) / len(closed), 1) if closed else None,
        "net_pnl": round(sum(pnls), 2),
        "gross_profit": round(gross_win, 2),
        "gross_loss": round(-gross_loss, 2),
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else None,
        "expectancy": round(mean(pnls), 2) if pnls else None,
        "largest_winner": round(max(pnls), 2) if pnls else None,
        "largest_loser": round(min(pnls), 2) if pnls else None,
        "avg_winner": round(mean(wins), 2) if wins else None,
        "avg_loser": round(mean(losses), 2) if losses else None,
        "avg_hold_minutes": round(mean(holds), 1) if holds else None,
    }


def _risk_windows(closed: List[Dict]) -> Dict[str, Any]:
    """Sharpe / Sortino / max drawdown / recovery over per-trade returns."""
    ordered = sorted(closed, key=lambda r: str(r.get("exit_ts") or ""))
    import portfolio_store
    cap = float(portfolio_store.INITIAL_CAPITAL)
    rets = [float(r.get("realized_pnl") or 0.0) / cap for r in ordered]
    if not rets:
        return {"sharpe": None, "sortino": None, "max_drawdown": None,
                "recovery_factor": None, "avg_return_pct": None}
    avg = mean(rets)
    sd = pstdev(rets) if len(rets) > 1 else 0.0
    downside = [r for r in rets if r < 0]
    dsd = pstdev(downside) if len(downside) > 1 else (abs(downside[0]) if downside else 0.0)
    equity, peak, max_dd = 0.0, 0.0, 0.0
    for r in ordered:
        equity += float(r.get("realized_pnl") or 0.0)
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    net = sum(float(r.get("realized_pnl") or 0.0) for r in ordered)
    return {
        "sharpe": round(avg / sd, 2) if sd > 0 else None,
        "sortino": round(avg / dsd, 2) if dsd > 0 else None,
        "max_drawdown": round(-max_dd, 2),
        "recovery_factor": round(net / max_dd, 2) if max_dd > 0 else None,
        "avg_return_pct": round(avg * 100.0, 3),
    }


# ---------------------------------------------------------------------------
# PART 1 — Phase 4A dashboard
# ---------------------------------------------------------------------------

MARK_STALE_AFTER_S = 900  # scan marks older than one scan interval are stale


def _mark_meta(open_rows: List[Dict], live_marks: Dict[str, float],
               live_fetched_at: Optional[str], snap: Dict[str, Any],
               scan_age_s: Optional[float], session_verified: bool = False,
               quote_error: Optional[str] = None) -> Dict[str, Any]:
    """Describe where open-position marks came from and how old they are.

    Honesty rules: never claim "no session" when the session was verified
    but the quote fetch failed; for mixed sources report the scan age too,
    since some marks are that old.
    """
    open_syms = {r.get("symbol") for r in open_rows if r.get("symbol")}
    live_dt = _parse_ts(live_fetched_at)
    live_age = round((_now_utc() - live_dt).total_seconds()) if live_dt else None
    scan_stale = bool(scan_age_s is not None and scan_age_s > MARK_STALE_AFTER_S)
    base = {
        "mark_session_verified": session_verified,
        "mark_quote_error": quote_error,
        "live_mark_age_s": live_age,
        "scan_mark_age_s": scan_age_s,
    }
    if open_syms and live_marks and open_syms <= set(live_marks):
        return {**base,
                "mark_source": "live quotes (Zerodha Kite)",
                "mark_age_s": live_age,
                "mark_stale": False,
                "mark_note": None}
    if live_marks:
        missing = sorted(open_syms - set(live_marks))
        # Some marks are as old as the scan — report the older age honestly.
        return {**base,
                "mark_source": f"live quotes (Zerodha Kite) + latest scan {snap.get('scan_id')} for {', '.join(missing)}",
                "mark_age_s": scan_age_s if scan_age_s is not None else live_age,
                "mark_stale": scan_stale,
                "mark_note": (f"live quote unavailable for {', '.join(missing)}; "
                              "scan marks used for those (see scan mark age)")}
    if session_verified:
        return {**base,
                "mark_source": f"latest scan {snap.get('scan_id')}",
                "mark_age_s": scan_age_s,
                "mark_stale": scan_stale,
                "mark_note": ((f"broker session is active but {quote_error or 'live quotes were unavailable'}"
                               " — falling back to last-scan prices, which may lag reality")
                              if open_syms else None)}
    return {**base,
            "mark_source": f"latest scan {snap.get('scan_id')}",
            "mark_age_s": scan_age_s,
            "mark_stale": scan_stale,
            "mark_note": ("no live broker session — marks are last-scan prices and may lag reality"
                          if open_syms else None)}
def build_phase4a_dashboard() -> Dict[str, Any]:
    snap = _load_snapshot() or {}
    summary = snap.get("summary") or {}
    timings = snap.get("timings") or {}
    ph = snap.get("provider_health") or {}
    safety = snap.get("safety") or {}
    recs = snap.get("recommendations") or []
    rep = _build_replay_cached()
    rows = _load_ledger()
    today = _ist_date(_now_utc())

    # ---- scanner tile -------------------------------------------------
    snap_dt = _parse_ts(snap.get("snapshot_ts"))
    freshness_s = round((_now_utc() - snap_dt).total_seconds()) if snap_dt else None
    universe_size = int(snap.get("universe_size") or 0)
    analysed = int(summary.get("symbols_analysed") or 0)
    passed = int(summary.get("all_gates_passed_count") or 0)
    watchlist_path = os.path.join(BASE_DIR, "watchlist.json")
    universe_source = "watchlist.json" if os.path.exists(watchlist_path) else "config.DEFAULT_WATCHLIST"
    scanner = {
        "universe_source": f"{universe_source} ({universe_size} symbols)",
        "symbols_loaded": universe_size,
        "symbols_scanned": analysed,
        "symbols_passed": passed,
        "symbols_rejected": max(0, analysed - passed),
        "scan_duration_s": snap.get("duration_s"),
        "scan_timestamp": snap.get("snapshot_ts"),
        "scan_id": snap.get("scan_id"),
        "data_freshness_s": freshness_s,
        "quality_breakdown": summary.get("data_quality_breakdown") or {},
    }

    # ---- market data tile ---------------------------------------------
    market_data = {
        "zerodha_status": "CONNECTED" if safety.get("kite_connected") else "NOT CONNECTED",
        "yahoo_status": ph.get("connection_status") or "NOT REPORTED IN SCAN",
        "nse_status": "PRE-OPEN ONLY (08:45–09:15 IST)",
        "active_provider": ph.get("provider"),
        "missing_symbols": ph.get("symbols_unavailable") or 0,
        "missing_symbol_list": ph.get("unavailable_symbols") or [],
        "failed_requests": len(ph.get("errors") or []),
        "retry_events": ph.get("retry_events") or 0,
        "last_tick_age_s": freshness_s,
        "data_latency_ms": ph.get("avg_latency_ms"),
        "max_latency_ms": ph.get("max_latency_ms"),
        "symbol_coverage_pct": ph.get("symbol_coverage_pct"),
    }

    # ---- risk engine tile ----------------------------------------------
    gate_fail_reasons: Counter = Counter()
    rr_vals: List[float] = []
    for r in recs:
        for gk in ("gate_rr", "gate_price", "gate_volume", "gate_data_quality"):
            g = r.get(gk) or {}
            if g and g.get("passed") is False:
                gate_fail_reasons[gk.replace("gate_", "")] += 1
        if isinstance(r.get("rr_ratio"), (int, float)):
            rr_vals.append(float(r["rr_ratio"]))
    top_reject = gate_fail_reasons.most_common(1)
    risk_engine = {
        "candidates_received": analysed,
        "candidates_approved": passed,
        "candidates_rejected": max(0, analysed - passed),
        "top_rejection_reason": top_reject[0][0] if top_reject else "none (all gates passed)",
        "rejection_breakdown": dict(gate_fail_reasons),
        "avg_rr_ratio": round(mean(rr_vals), 2) if rr_vals else None,
        "avg_opportunity_score": summary.get("avg_opportunity_score"),
        "processing_time_s": timings.get("analysis_s"),
    }

    # ---- open positions tile --------------------------------------------
    import portfolio_store
    cap = float(portfolio_store.INITIAL_CAPITAL)
    open_rows = [r for r in rows if r.get("status") in ("OPEN", "EXIT_PENDING")]
    mark: Dict[str, float] = {}
    sector_of: Dict[str, str] = {}
    for r in recs:
        if isinstance(r.get("entry_price"), (int, float)):
            mark[r.get("symbol")] = float(r["entry_price"])
        if r.get("sector"):
            sector_of[r.get("symbol")] = r["sector"]
    # Live quote overlay: when a verified Zerodha session is available,
    # mark open positions with live LTPs instead of last-scan entry prices.
    live_marks: Dict[str, float] = {}
    live_fetched_at: Optional[str] = None
    session_verified = False
    quote_error: Optional[str] = None
    if open_rows:
        try:
            import kite_quote_provider as kqp
            session_verified = bool(kqp.kite_session_verified())
            if session_verified:
                open_syms = sorted({r.get("symbol") for r in open_rows if r.get("symbol")})
                quotes = kqp.get_quotes(open_syms) or {}
                non_live_sources = set()
                for s, q in quotes.items():
                    if q.get("data_source") == "kite_live" and isinstance(q.get("ltp"), (int, float)):
                        live_marks[s] = float(q["ltp"])
                        live_fetched_at = q.get("fetched_at") or live_fetched_at
                    else:
                        non_live_sources.add(q.get("data_source") or "unknown")
                if not live_marks:
                    quote_error = ("live quote fetch returned no usable Kite quotes"
                                   + (f" (provider fell back to: {', '.join(sorted(non_live_sources))})"
                                      if non_live_sources else ""))
        except Exception as exc:
            live_marks = {}
            quote_error = f"live quote fetch failed: {str(exc)[:200]}"

    positions = []
    exposure = 0.0
    unreal = 0.0
    unreal_known = True
    sector_exp: Dict[str, float] = defaultdict(float)
    for r in open_rows:
        qty = int(r.get("quantity") or 0)
        fp = float(r.get("fill_price") or 0.0)
        cost = qty * fp
        exposure += cost
        sym = r.get("symbol")
        sector = r.get("sector") or sector_of.get(sym) or "UNKNOWN"
        sector_exp[sector] += cost
        if sym in live_marks:
            m: Optional[float] = live_marks[sym]
            m_src = "live"
        else:
            m = mark.get(sym)
            m_src = "scan" if m is not None else None
        u = round((m - fp) * qty, 2) if m is not None else None
        if u is None:
            unreal_known = False
        else:
            unreal += u
        positions.append({
            "trade_id": r.get("trade_id"), "symbol": sym, "qty": qty,
            "fill_price": fp, "cost": round(cost, 2), "mark_price": m,
            "mark_source": m_src,
            "unrealized_pnl": u, "status": r.get("status"), "sector": sector,
        })
    largest = max(positions, key=lambda p: p["cost"]) if positions else None
    open_positions = {
        "count": len(open_rows),
        "exposure": round(exposure, 2),
        "capital_used_pct": round(100.0 * exposure / cap, 1) if cap else None,
        "largest_position": (f"{largest['symbol']} ₹{largest['cost']:.0f}" if largest else "none"),
        "unrealized_pnl": round(unreal, 2) if unreal_known else None,
        "unrealized_note": None if unreal_known else "mark price missing for some symbols in latest scan",
        **_mark_meta(open_rows, live_marks, live_fetched_at, snap, freshness_s,
                     session_verified=session_verified, quote_error=quote_error),
        "sector_exposure": {k: round(v, 2) for k, v in sorted(sector_exp.items(), key=lambda x: -x[1])},
        "positions": positions,
    }

    # ---- pending trades tile ---------------------------------------------
    blocked: List[Dict] = []
    if rep:
        for s in rep.get("stages") or []:
            if s.get("id") == "execution":
                blocked = s.get("blocked_entries") or []
    executed_this_scan = {r.get("symbol") for r in rows if r.get("scan_id") == snap.get("scan_id")
                          and r.get("status") != "CANCELLED"}
    eligible = [r for r in recs if r.get("final_action") == "BUY"]
    buy_pending = [r.get("symbol") for r in eligible
                   if r.get("symbol") not in executed_this_scan
                   and not any(b.get("symbol") == r.get("symbol") for b in blocked)]
    cancelled_rows = [r for r in rows if r.get("status") == "CANCELLED"]
    expired = [r for r in cancelled_rows if "expire" in str(r.get("exit_rule") or "").lower()]
    pending_trades = {
        "buy_pending": len(buy_pending),
        "buy_pending_symbols": buy_pending,
        "buy_pending_note": "paper-eligible BUYs awaiting automation (auto entries " +
                            ("ON" if os.getenv("AUTO_PAPER_ENTRIES", "").lower() == "true" else "OFF") + ")",
        "sell_pending": sum(1 for r in rows if r.get("status") == "EXIT_PENDING"),
        "cancelled": len(cancelled_rows),
        "expired": len(expired),
        "rejected": len(blocked),
        "rejected_scope": f"current scan {snap.get('scan_id')}",
        "rejected_detail": [{"symbol": b.get("symbol"), "reasons": b.get("reasons")} for b in blocked[:10]],
    }

    # ---- previous session tile --------------------------------------------
    day_activity: Dict[str, int] = defaultdict(int)
    for r in rows:
        for ts_key in ("fill_ts", "exit_ts"):
            d = _ist_date(_parse_ts(r.get(ts_key)))
            if d and d != today:
                day_activity[d] += 1
    prev_day = max(day_activity) if day_activity else None
    if prev_day:
        prev = _ledger_rows_for_day(rows, prev_day)
        prev_closed = _closed_stats(prev["exits"])
        previous_session = {
            "date": prev_day,
            "trades": len(prev["fills"]) + len(prev["exits"]),
            "entries": len(prev["fills"]),
            "exits": len(prev["exits"]),
            "win_rate_pct": prev_closed["win_rate_pct"],
            "net_pnl": prev_closed["net_pnl"] if prev["exits"] else 0.0,
            "largest_winner": prev_closed["largest_winner"],
            "largest_loser": prev_closed["largest_loser"],
            "avg_hold_minutes": prev_closed["avg_hold_minutes"],
        }
    else:
        previous_session = {"date": None, "trades": 0, "entries": 0, "exits": 0,
                            "win_rate_pct": None, "net_pnl": 0.0, "largest_winner": None,
                            "largest_loser": None, "avg_hold_minutes": None,
                            "note": "no prior-day ledger activity yet"}

    # ---- live session monitor extras ----------------------------------------
    sysm = _proc_system_metrics()
    today_rows = _ledger_rows_for_day(rows, today)
    realized_today = round(sum(float(r.get("realized_pnl") or 0.0) for r in today_rows["exits"]), 2)
    realized_all = sum(float(r.get("realized_pnl") or 0.0)
                       for r in rows if r.get("status") == "CLOSED")
    # equity = capital + realized + unrealized mark-to-market (marks: latest scan)
    portfolio_value = round(cap + realized_all + (unreal if unreal_known else 0.0), 2)
    monitor = {
        "signals_generated": len(recs),
        "portfolio_value": portfolio_value,
        "portfolio_value_note": ("incl. open-position MTM at latest scan prices" if unreal_known
                                 else "excl. MTM — mark price missing for some open symbols"),
        "freshness_s": freshness_s,
        "scanner_latency_s": snap.get("duration_s"),
        "realized_pnl_today": realized_today,
        "cpu_pct": sysm["cpu_pct"],
        "memory_pct": sysm["memory_pct"],
        "memory_used_mb": sysm["memory_used_mb"],
        "queue_depth": pending_trades["sell_pending"],
        "queue_note": "EXIT_PENDING ledger rows awaiting fresh data",
        "api_response_ms": ph.get("avg_latency_ms"),
        "paper_orders_today": len(today_rows["fills"]) + len(today_rows["exits"]),
        "risk_blocks": len(blocked),
        "decision_time_s": timings.get("analysis_s"),
        "execution_time_s": _stage_duration(rep, "execution"),
    }

    # ---- decision distribution (BUY/WATCH/SELL/AVOID/TOTAL) --------------------
    actions = Counter(str(r.get("final_action") or "").upper() for r in recs)
    sells_today = len(today_rows["exits"])
    decision_distribution = {
        "buy": actions.get("BUY", 0),
        "watch": actions.get("WATCH", 0),
        "sell": sells_today,
        "sell_note": "paper exits filled today (scanner emits BUY/WATCH/IGNORE only)",
        "avoid": actions.get("IGNORE", 0),
        "total": len(recs),
    }

    # ---- pipeline summary -----------------------------------------------------
    pipeline: List[Dict[str, Any]] = []
    if rep:
        counts = rep.get("pipeline_counts") or {}
        order = [s.get("id") for s in rep.get("stages") or []]
        for sid in order + [k for k in counts if k not in order]:
            c = counts.get(sid)
            if not c:
                continue
            pipeline.append({
                "id": sid, "label": c.get("label"),
                "input": c.get("in"), "passed": c.get("out"),
                "rejected": c.get("rejected"), "pending": c.get("pending"),
                "cancelled": c.get("cancelled"),
                "processing_time_s": _stage_duration(rep, sid),
            })

    return {
        "generated_at": _now_utc().isoformat(),
        "scan_id": snap.get("scan_id"),
        "snapshot_ts": snap.get("snapshot_ts"),
        "scanner": scanner,
        "market_data": market_data,
        "risk_engine": risk_engine,
        "open_positions": open_positions,
        "pending_trades": pending_trades,
        "previous_session": previous_session,
        "monitor": monitor,
        "decision_distribution": decision_distribution,
        "pipeline": pipeline,
    }


# ---------------------------------------------------------------------------
# PART 2 — Paper Trading Validation dashboard
# ---------------------------------------------------------------------------

def _market_open_now() -> str:
    now = datetime.now(IST)
    if now.weekday() >= 5:
        return "CLOSED (weekend)"
    hm = now.hour * 60 + now.minute
    if 9 * 60 + 15 <= hm <= 15 * 60 + 30:
        return "OPEN"
    if 8 * 60 + 45 <= hm < 9 * 60 + 15:
        return "PRE-OPEN"
    return "CLOSED"


def build_validation_dashboard() -> Dict[str, Any]:
    snap = _load_snapshot() or {}
    summary = snap.get("summary") or {}
    ph = snap.get("provider_health") or {}
    recs = snap.get("recommendations") or []
    ctx = _load_market_context()
    rows = _load_ledger()
    rep = _build_replay_cached()
    decisions = _load_ai_decisions()
    today = _ist_date(_now_utc())
    today_rows = _ledger_rows_for_day(rows, today)

    # ---- today's session -------------------------------------------------
    sectors = ctx.get("sector_strength") or {}
    top_sector = max(sectors, key=sectors.get) if sectors else None
    worst_sector = min(sectors, key=sectors.get) if sectors else None
    breadth = ctx.get("market_breadth")
    universe = int(snap.get("universe_size") or 0)
    advances = round(breadth * universe) if isinstance(breadth, (int, float)) and universe else None
    declines = (universe - advances) if advances is not None else None
    session = {
        "market_status": _market_open_now(),
        "market_regime": ctx.get("regime") or summary.get("regime"),
        "market_bias": ctx.get("bias"),
        "nifty": ctx.get("nifty_price"),
        "nifty_change_pct": ctx.get("nifty_change_pct"),
        "bank_nifty": ctx.get("banknifty_price"),
        "bank_nifty_change_pct": ctx.get("banknifty_change_pct"),
        "india_vix": ctx.get("vix"),
        "vix_category": ctx.get("vix_category"),
        "top_sector": f"{top_sector} ({sectors.get(top_sector)})" if top_sector else None,
        "worst_sector": f"{worst_sector} ({sectors.get(worst_sector)})" if worst_sector else None,
        "advance_decline": f"{advances}/{declines}" if advances is not None else None,
        "advance_decline_note": "market_breadth × scanned universe",
        "market_breadth": breadth,
        "breadth_label": ctx.get("breadth_label"),
        "gap_pct": ctx.get("nifty_change_pct"),
        "gap_note": "Nifty day change (dedicated open-gap feed not captured)",
        "leading_theme": (f"{top_sector} strength, {ctx.get('bias', '').lower()} bias"
                          if top_sector and ctx.get("bias") else None),
        "context_computed_at": ctx.get("computed_at"),
    }

    # ---- trading statistics (today) ------------------------------------------
    blocked: List[Dict] = []
    if rep:
        for s in rep.get("stages") or []:
            if s.get("id") == "execution":
                blocked = s.get("blocked_entries") or []
    closed_today = _closed_stats(today_rows["exits"])
    gross_today = 0.0
    for r in today_rows["exits"]:
        qty = int(r.get("quantity") or 0)
        if r.get("exit_price") is not None and r.get("fill_price") is not None:
            gross_today += (float(r["exit_price"]) - float(r["fill_price"])) * qty
    rr_exec = [float(r.get("target", 0) - r.get("fill_price", 0)) /
               max(1e-9, float(r.get("fill_price", 0)) - float(r.get("stop_loss", 0)))
               for r in today_rows["fills"]
               if r.get("target") and r.get("stop_loss") and r.get("fill_price")
               and float(r["fill_price"]) > float(r["stop_loss"])]
    # distinct trade records with activity today (a same-day round trip = 1 trade)
    active_today = {r.get("trade_id") for r in today_rows["fills"]} | \
                   {r.get("trade_id") for r in today_rows["exits"]}
    trading_statistics = {
        "trades": len(active_today),
        "buy_orders": len(today_rows["fills"]),
        "sell_orders": len(today_rows["exits"]),
        "cancelled": len(today_rows["cancelled"]),
        "rejected": len(blocked),
        "risk_blocks": len(blocked),
        "net_pnl": closed_today["net_pnl"],
        "gross_pnl": round(gross_today, 2),
        "avg_rr": round(mean(rr_exec), 2) if rr_exec else None,
        "avg_hold_minutes": closed_today["avg_hold_minutes"],
        "largest_winner": closed_today["largest_winner"],
        "largest_loser": closed_today["largest_loser"],
        "avg_winner": closed_today["avg_winner"],
        "avg_loser": closed_today["avg_loser"],
    }

    # ---- historical performance ------------------------------------------------
    closed_all = [r for r in rows if r.get("status") == "CLOSED"]
    now = _now_utc()
    periods = {"7d": 7, "30d": 30, "90d": 90, "180d": 180, "all": None}
    historical: Dict[str, Any] = {}
    for label, days in periods.items():
        closed_dated = [r for r in closed_all if _parse_ts(r.get("exit_ts")) is not None]
        if days is None:
            sel = closed_dated
        else:
            # IST calendar-day windowing: include the last N calendar days incl. today.
            cutoff_date = (_now_utc().astimezone(IST).date() - timedelta(days=days - 1)).isoformat()
            sel = [r for r in closed_dated if _ist_date(_parse_ts(r["exit_ts"])) >= cutoff_date]
        st = _closed_stats(sel)
        st.update(_risk_windows(sel))
        historical[label] = st
    historical["note"] = (f"{len(closed_all)} closed trades in ledger; "
                          "risk ratios need larger samples to be meaningful") if len(closed_all) < 20 else None

    # ---- data quality --------------------------------------------------------
    ids = [r.get("trade_id") for r in rows]
    dup_ids = len(ids) - len(set(ids))
    scan_sym = Counter((r.get("scan_id"), r.get("symbol")) for r in rows if r.get("status") != "CANCELLED")
    dup_trades = sum(c - 1 for c in scan_sym.values() if c > 1)
    open_syms = Counter(r.get("symbol") for r in rows if r.get("status") == "OPEN")
    dup_open = sum(c - 1 for c in open_syms.values() if c > 1)
    audit = snap.get("scan_audit") or {}
    exec_bad = [r for r in rows if r.get("status") in ("OPEN", "CLOSED", "EXIT_PENDING")
                and not r.get("fill_price")]
    closed_no_pnl = [r for r in closed_all if r.get("realized_pnl") is None]
    closed_no_exit_ts = [r for r in closed_all if _parse_ts(r.get("exit_ts")) is None]
    import portfolio_store
    cap = float(portfolio_store.INITIAL_CAPITAL)
    deployed = sum(int(r.get("quantity") or 0) * float(r.get("fill_price") or 0.0)
                   for r in rows if r.get("status") in ("OPEN", "EXIT_PENDING"))
    realized = sum(float(r.get("realized_pnl") or 0.0) for r in closed_all)
    cash = cap - deployed + realized
    data_quality = {
        "duplicate_orders": dup_ids,
        "duplicate_trades": dup_trades,
        "duplicate_open_symbols": dup_open,
        "missing_candles": ph.get("symbols_unavailable") or 0,
        "missing_candle_symbols": ph.get("unavailable_symbols") or [],
        "missing_ticks": ph.get("symbols_stale") or 0,
        "api_errors": len(ph.get("errors") or []),
        "retry_events": ph.get("retry_events") or 0,
        "replay_integrity": audit.get("audit_verdict") or ("PASS" if rep else "NO SCAN"),
        "execution_integrity": "PASS" if not exec_bad else f"FAIL ({len(exec_bad)} filled rows missing fill price)",
        "closed_missing_exit_ts": len(closed_no_exit_ts),
        "closed_missing_exit_ts_note": ("CLOSED rows without exit_ts are excluded from historical windows"
                                        if closed_no_exit_ts else None),
        "portfolio_integrity": ("PASS" if not closed_no_pnl else
                                f"FAIL ({len(closed_no_pnl)} closed trades missing realized P&L)"),
        "portfolio_cash_check": {"initial": cap, "deployed": round(deployed, 2),
                                 "realized": round(realized, 2), "cash": round(cash, 2),
                                 "formula": "cash = initial − deployed + realized"},
        "database_consistency": "PASS" if dup_ids == 0 and dup_open == 0 else "FAIL (duplicate keys)",
    }

    # ---- validation pipeline checklist ------------------------------------------
    def verdict(ok: bool, warn: bool, reason: str) -> Dict[str, str]:
        return {"status": "PASS" if ok else ("WARNING" if warn else "FAIL"), "reason": reason}

    counts = (rep or {}).get("pipeline_counts") or {}

    def stage_check(sid: str, label: str) -> Dict[str, Any]:
        c = counts.get(sid)
        if not c:
            return {"stage": label, **verdict(False, True, "stage not present in replay snapshot")}
        inn, out, rej = c.get("in", 0), c.get("out", 0), c.get("rejected", 0)
        if inn == 0:
            return {"stage": label, **verdict(False, True, "no input reached this stage")}
        if out > 0:
            return {"stage": label, **verdict(True, False, f"{out}/{inn} passed, {rej} rejected")}
        return {"stage": label, **verdict(False, True, f"0/{inn} passed ({rej} rejected) — gates blocked all")}

    conn_status = ph.get("connection_status")
    checklist = [
        {"stage": "Market Data", **verdict(conn_status == "OK", conn_status == "DEGRADED",
         f"provider {ph.get('provider')} status {conn_status}, coverage {ph.get('symbol_coverage_pct')}%")},
        stage_check("research", "Research"),
        stage_check("strategy", "Strategy"),
        stage_check("risk", "Risk"),
        stage_check("ai_decision", "Decision"),
        stage_check("execution", "Execution"),
        {"stage": "Paper Trader", **verdict(dup_open == 0 and not exec_bad, False,
         "one-open-per-symbol invariant and fill completeness on the phase20 ledger")},
        {"stage": "Portfolio", **verdict(not closed_no_pnl, False,
         data_quality["portfolio_cash_check"]["formula"] + f" → ₹{round(cash, 2)}")},
        {"stage": "Trade History", **verdict(dup_ids == 0, False,
         f"{len(rows)} ledger rows, {dup_ids} duplicate ids")},
        {"stage": "Performance", **verdict(True, len(closed_all) < 5,
         f"{len(closed_all)} closed trades available for statistics")},
        {"stage": "Replay", **verdict(audit.get("audit_verdict") == "PASS", audit.get("audit_verdict") is None,
         f"scan audit verdict {audit.get('audit_verdict')}, single scan_id: {audit.get('all_items_share_same_scan_id')}")},
    ]

    # ---- AI validation -------------------------------------------------------
    confs = [float(d.get("calibrated_confidence"))
             for d in decisions if isinstance(d.get("calibrated_confidence"), (int, float))]
    buckets = {"0-25": 0, "25-50": 0, "50-75": 0, "75-100": 0}
    for c in confs:
        k = "0-25" if c < 25 else "25-50" if c < 50 else "50-75" if c < 75 else "75-100"
        buckets[k] += 1
    strat_dist = Counter(str(r.get("strategy_id") or "unknown") for r in recs)
    sector_dist = Counter(str(r.get("sector") or "unknown") for r in recs)
    strat_pnl: Dict[str, List[float]] = defaultdict(list)
    for r in closed_all:
        strat_pnl[str(r.get("strategy_id") or r.get("strategy_name") or "unknown")].append(
            float(r.get("realized_pnl") or 0.0))
    strat_src = "closed paper trades"
    if not strat_pnl:
        for r in recs:
            if isinstance(r.get("net_pnl_pct"), (int, float)):
                strat_pnl[str(r.get("strategy_id") or "unknown")].append(float(r["net_pnl_pct"]))
        strat_src = "scan backtest net_pnl_pct (no closed paper trades yet)"
    strat_avg = {k: round(mean(v), 2) for k, v in strat_pnl.items() if v}
    ai_validation = {
        "decisions_analysed": len(decisions),
        "avg_confidence": round(mean(confs), 1) if confs else None,
        "highest_confidence": round(max(confs), 1) if confs else None,
        "lowest_confidence": round(min(confs), 1) if confs else None,
        "confidence_distribution": buckets,
        "confidence_source": "calibrated_confidence in ai_decisions_cache",
        "strategy_distribution": dict(strat_dist.most_common()),
        "sector_distribution": dict(sector_dist.most_common()),
        "top_strategy": max(strat_avg, key=strat_avg.get) if strat_avg else None,
        "worst_strategy": min(strat_avg, key=strat_avg.get) if strat_avg else None,
        "strategy_performance": strat_avg,
        "strategy_performance_source": strat_src,
    }

    return {
        "generated_at": _now_utc().isoformat(),
        "scan_id": snap.get("scan_id"),
        "session": session,
        "trading_statistics": trading_statistics,
        "historical_performance": historical,
        "data_quality": data_quality,
        "validation_pipeline": checklist,
        "ai_validation": ai_validation,
    }


if __name__ == "__main__":
    import sys
    which = sys.argv[1] if len(sys.argv) > 1 else "phase4a"
    fn = build_phase4a_dashboard if which == "phase4a" else build_validation_dashboard
    print(json.dumps(fn(), indent=2, default=str))
