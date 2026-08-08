"""
phase24_analytics.py — Phase 24 aggregate analytics.

Strategy ranking, sector ranking, time/regime analysis, confidence
calibration (delegates to phase21_calibration), and the daily AI scorecard.

READ-ONLY · ADVISORY ONLY. Computes exclusively from the permanent
phase24 Trade Intelligence records (which themselves derive from the
canonical phase20 ledger). No duplicate ledger math, no writes.
"""
from __future__ import annotations

import math
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import phase24_store as store

IST = timezone(timedelta(hours=5, minutes=30))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _records() -> List[Dict[str, Any]]:
    return [r.get("record") or {} for r in store.list_trade_records(limit=5000)]


def _pnls(rows: List[Dict[str, Any]]) -> List[float]:
    return [float(r.get("realized_pnl") or 0) for r in rows]


def _std(vals: List[float]) -> float:
    if len(vals) < 2:
        return 0.0
    m = sum(vals) / len(vals)
    return math.sqrt(sum((v - m) ** 2 for v in vals) / (len(vals) - 1))


def _group_stats(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    n = len(rows)
    pnls = _pnls(rows)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    gross_win, gross_loss = sum(wins), abs(sum(losses))
    total = round(sum(pnls), 2)
    returns = []
    holding = []
    conf_correct = 0
    conf_n = 0
    capital = []
    for r in rows:
        cap = float(r.get("capital_used") or 0)
        pnl = float(r.get("realized_pnl") or 0)
        if cap > 0:
            returns.append(100.0 * pnl / cap)
            capital.append(cap)
        h = r.get("holding_time_minutes")
        if h is not None:
            holding.append(float(h))
        c = r.get("confidence")
        if c is not None:
            conf_n += 1
            # confidence "accurate" when a high-confidence trade won or a
            # low-confidence trade lost
            if (float(c) >= 60 and pnl > 0) or (float(c) < 60 and pnl <= 0):
                conf_correct += 1
    # Max drawdown over the cumulative P&L path (trade order = list order)
    peak, dd = 0.0, 0.0
    cum = 0.0
    for p in pnls:
        cum += p
        peak = max(peak, cum)
        dd = min(dd, cum - peak)
    mean_ret = (sum(returns) / len(returns)) if returns else 0.0
    sd = _std(returns)
    downside = _std([r for r in returns if r < 0]) if any(r < 0 for r in returns) else 0.0
    return {
        "trades": n,
        "win_rate": round(len(wins) / n, 4) if n else None,
        "total_pnl": total,
        "avg_return_pct": round(mean_ret, 3) if returns else None,
        "max_drawdown": round(dd, 2),
        "profit_factor": round(gross_win / gross_loss, 3) if gross_loss else None,
        "expectancy": round(total / n, 2) if n else None,
        "recovery_factor": (round(total / abs(dd), 3) if dd < 0 else None),
        "sharpe": round(mean_ret / sd, 3) if sd else None,
        "sortino": round(mean_ret / downside, 3) if downside else None,
        "capital_efficiency": (round(total / (sum(capital) / len(capital)), 4)
                               if capital else None),
        "avg_holding_minutes": round(sum(holding) / len(holding), 1) if holding else None,
        "confidence_accuracy": round(conf_correct / conf_n, 4) if conf_n else None,
    }


def _ranked_by(key: str, min_trades: int = 1) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in _records():
        groups[str(r.get(key) or "UNKNOWN")].append(r)
    out = []
    for name, rows in groups.items():
        if len(rows) < min_trades:
            continue
        s = _group_stats(rows)
        s[key] = name
        out.append(s)
    out.sort(key=lambda s: (-(s["total_pnl"] or 0), s[key]))
    for i, s in enumerate(out):
        s["rank"] = i + 1
    return out


def strategy_ranking() -> Dict[str, Any]:
    items = _ranked_by("strategy")
    return {"items": items, "generated_at": _now(), "advisory_only": True,
            "source": "phase24_trade_intelligence",
            "note": "Ranking is advisory — no strategy is ever enabled or "
                    "disabled automatically."}


def sector_ranking() -> Dict[str, Any]:
    items = _ranked_by("sector")
    summary = {}
    if items:
        summary = {
            "best_sector": items[0]["sector"],
            "worst_sector": items[-1]["sector"],
            "most_consistent": max(
                (i for i in items if i.get("win_rate") is not None),
                key=lambda i: i["win_rate"], default=items[0]).get("sector"),
            "highest_drawdown": min(
                items, key=lambda i: i.get("max_drawdown") or 0).get("sector"),
        }
    return {"items": items, "summary": summary, "generated_at": _now(),
            "advisory_only": True}


def time_analysis() -> Dict[str, Any]:
    """Best/worst hour (IST), weekday, market regime, volatility band."""
    by_hour: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    by_weekday: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    by_regime: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    by_vol: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in _records():
        try:
            dt = datetime.fromisoformat(str(r.get("entry_time")).replace("Z", "+00:00"))
            ist = dt.astimezone(IST)
            by_hour[f"{ist.hour:02d}:00"].append(r)
            by_weekday[ist.strftime("%A")].append(r)
        except Exception:
            pass
        try:
            from phase21_regime import normalize_regime
            by_regime[normalize_regime(r.get("market_regime"))].append(r)
        except Exception:
            by_regime[str(r.get("market_regime") or "UNKNOWN")].append(r)
        vol = r.get("volatility")
        if vol is not None:
            v = float(vol)
            band = "LOW" if v < 1.0 else ("MEDIUM" if v < 2.5 else "HIGH")
            by_vol[band].append(r)

    def summarize(groups: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        out = []
        for name, rows in groups.items():
            s = _group_stats(rows)
            s["bucket"] = name
            out.append(s)
        out.sort(key=lambda s: -(s["total_pnl"] or 0))
        return out

    hours = summarize(by_hour)
    weekdays = summarize(by_weekday)
    regimes = summarize(by_regime)
    vols = summarize(by_vol)

    def best_worst(items):
        if not items:
            return {"best": None, "worst": None}
        return {"best": items[0]["bucket"], "worst": items[-1]["bucket"]}

    return {
        "hours": hours, "weekdays": weekdays, "regimes": regimes,
        "volatility_bands": vols,
        "summary": {
            "hour": best_worst(hours), "weekday": best_worst(weekdays),
            "regime": best_worst(regimes), "volatility": best_worst(vols),
        },
        "generated_at": _now(), "advisory_only": True,
    }


def calibration() -> Dict[str, Any]:
    """Confidence calibration — reuses the phase21 calibration engine
    (one source of truth) and overlays phase24 trade counts."""
    from phase21_calibration import run_calibration
    cal = run_calibration()
    cal["phase24_trade_records"] = len(_records())
    cal["advisory_only"] = True
    return cal


# ── Daily AI scorecard ───────────────────────────────────────────────────────

def _clamp10(v: float) -> float:
    return round(max(0.0, min(10.0, v)), 1)


def ai_scorecard() -> Dict[str, Any]:
    """Grade each subsystem 0-10 from existing snapshots + phase24 analytics.
    No recalculation of upstream data — reads cached/summary values only."""
    recs = _records()
    stats = _group_stats(recs) if recs else None
    scores: Dict[str, Any] = {}
    notes: Dict[str, str] = {}

    # Scanner — freshness / availability of the canonical scan
    try:
        from scan_state_store import load_latest_snapshot
        snap = load_latest_snapshot() or {}
        n_recs = len(snap.get("recommendations") or [])
        scores["scanner"] = _clamp10(10.0 if n_recs >= 30 else n_recs / 3.0)
        notes["scanner"] = f"{n_recs} symbols in latest canonical scan"
    except Exception:
        scores["scanner"] = None

    # Research — opportunity score quality of captured trades
    opp = [float(r["opportunity_score"]) for r in recs
           if r.get("opportunity_score") is not None]
    scores["research"] = _clamp10(sum(opp) / len(opp) / 10.0) if opp else None

    # Market intelligence — regime coverage on captured trades
    reg_known = [r for r in recs if r.get("market_regime")]
    scores["market_intelligence"] = (_clamp10(10.0 * len(reg_known) / len(recs))
                                     if recs else None)

    # Monitoring — excursion capture coverage (MFE/MAE available)
    exc = [r for r in recs if r.get("mfe") is not None]
    scores["monitoring"] = _clamp10(10.0 * len(exc) / len(recs)) if recs else None

    # Strategy — win rate + profit factor
    if stats and stats.get("win_rate") is not None:
        pf = stats.get("profit_factor")
        scores["strategy"] = _clamp10(stats["win_rate"] * 10.0
                                      + (1.0 if pf and pf > 1.5 else 0.0))
    else:
        scores["strategy"] = None

    # Risk — rule effectiveness from risk learning
    try:
        from phase24_engine import risk_rule_learning
        rl = risk_rule_learning()
        evald = [r for r in rl["rules"] if r.get("effectiveness") is not None]
        scores["risk"] = (_clamp10(10.0 * sum(r["effectiveness"] for r in evald)
                                   / len(evald)) if evald else None)
        notes["risk"] = f"{len(evald)} rules with sufficient evidence"
    except Exception:
        scores["risk"] = None

    # Execution — slippage discipline on captured trades
    slip = [abs(float(r["slippage"])) / float(r["entry_price"]) * 100
            for r in recs
            if r.get("slippage") is not None and float(r.get("entry_price") or 0) > 0]
    scores["execution"] = (_clamp10(10.0 - min(sum(slip) / len(slip) * 10.0, 10.0))
                           if slip else None)

    # Portfolio — equity vs initial capital (canonical portfolio)
    try:
        from canonical_portfolio import build_canonical_portfolio
        c = build_canonical_portfolio()
        cap = float(c.get("initial_capital") or 0)
        eq = float(c.get("equity") or 0)
        scores["portfolio"] = _clamp10(5.0 + 100.0 * (eq - cap) / cap) if cap else None
        notes["portfolio"] = f"equity {eq} vs capital {cap}"
    except Exception:
        scores["portfolio"] = None

    known = [v for v in scores.values() if v is not None]
    overall = round(sum(known) / len(known), 1) if known else None
    ranked = sorted(((k, v) for k, v in scores.items() if v is not None),
                    key=lambda kv: -kv[1])
    return {
        "date": datetime.now(IST).date().isoformat(),
        "scores": scores,
        "overall": overall,
        "strengths": [k for k, v in ranked[:3] if v >= 7.0],
        "weaknesses": [k for k, v in ranked[::-1][:3] if v < 6.0],
        "notes": notes,
        "trades_analysed": len(recs),
        "generated_at": _now(),
        "advisory_only": True,
        "note": "Scorecard grades subsystems from existing snapshots and the "
                "permanent Trade Intelligence store. INSUFFICIENT data → null.",
    }


# ── Lessons + best/worst trades (dashboard) ──────────────────────────────────

def _period_records(days: int) -> List[Dict[str, Any]]:
    cutoff = (datetime.now(IST) - timedelta(days=days)).date().isoformat()
    return [r for r in _records() if str(r.get("date") or "") >= cutoff]


def lessons(days: int, label: str) -> Dict[str, Any]:
    rows = _period_records(days)
    stats = _group_stats(rows) if rows else None
    mistakes: List[str] = []
    improvements: List[str] = []
    analyses = [(rec.get("record") or {}, rec.get("analysis") or {})
                for rec in store.list_trade_records(limit=5000)
                if str((rec.get("record") or {}).get("date") or "")
                >= (datetime.now(IST) - timedelta(days=days)).date().isoformat()]
    early_exits = sum(1 for _, a in analyses if a.get("exit_timing") == "EARLY")
    late_exits = sum(1 for _, a in analyses if a.get("exit_timing") == "LATE")
    tight_stops = sum(1 for _, a in analyses if a.get("stop_verdict") == "TOO_TIGHT")
    could_more = sum(1 for _, a in analyses if a.get("could_have_earned_more"))
    if early_exits:
        mistakes.append(f"{early_exits} trade(s) exited early, leaving profit on the table")
    if late_exits:
        mistakes.append(f"{late_exits} trade(s) turned profitable but were closed at a loss")
    if tight_stops:
        mistakes.append(f"{tight_stops} stop(s) were too tight — trades stopped out then recovered")
    if could_more:
        improvements.append(f"Trailing exits could have improved {could_more} trade(s)")
    if stats and stats.get("win_rate") is not None and stats["win_rate"] >= 0.5:
        improvements.append(f"Win rate {round(stats['win_rate'] * 100, 1)}% — maintain current selection quality")
    return {"period": label, "days": days, "trades": len(rows),
            "stats": stats, "mistakes": mistakes, "improvements": improvements,
            "advisory_only": True}


def best_worst_trades(limit: int = 5) -> Dict[str, Any]:
    rows = sorted(_records(), key=lambda r: float(r.get("realized_pnl") or 0))
    keep = ["trade_id", "symbol", "strategy", "date", "entry_price", "exit_price",
            "quantity", "realized_pnl", "exit_reason", "confidence", "mfe", "mae"]
    slim = lambda r: {k: r.get(k) for k in keep}  # noqa: E731
    return {"best": [slim(r) for r in rows[::-1][:limit]],
            "worst": [slim(r) for r in rows[:limit]],
            "advisory_only": True}


def overview() -> Dict[str, Any]:
    """Aggregate payload for the AI Learning Center page (one call)."""
    from phase24_engine import risk_rule_learning
    recs = _records()
    return {
        "generated_at": _now(),
        "trade_records": len(recs),
        "daily_lessons": lessons(1, "daily"),
        "weekly_lessons": lessons(7, "weekly"),
        "monthly_lessons": lessons(30, "monthly"),
        "best_worst": best_worst_trades(),
        "calibration": calibration(),
        "risk_learning": risk_rule_learning(),
        "strategy_ranking": strategy_ranking(),
        "sector_ranking": sector_ranking(),
        "time_analysis": time_analysis(),
        "scorecard": ai_scorecard(),
        "capital_efficiency": (_group_stats(recs).get("capital_efficiency")
                               if recs else None),
        "advisory_only": True,
        "label": "PAPER / RESEARCH ONLY — advisory, never auto-applied",
    }
