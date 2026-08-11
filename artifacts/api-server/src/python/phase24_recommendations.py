"""
phase24_recommendations.py — Phase 24 recommendation engine + automated reports.

ADVISORY ONLY. Recommendations carry a manual approve/dismiss lifecycle
(phase24_store). Approval records INTENT only — nothing in this module (or
anywhere in Phase 24) writes to trading rules, thresholds, gates, or
strategy enablement.

Reports (daily/weekly/monthly/quarterly) are generated once per period,
scheduler-guarded via the phase20 KV store (same pattern as the daily
session report).
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

import phase24_store as store

IST = timezone(timedelta(hours=5, minutes=30))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today_ist() -> str:
    return datetime.now(IST).date().isoformat()


# ── Recommendation generation ────────────────────────────────────────────────

def generate_recommendations(force: bool = False) -> Dict[str, Any]:
    """Generate today's advisory recommendations (once per IST day unless
    forced). Derived from phase24 analytics; stored as PROPOSED."""
    today = _today_ist()
    existing_today = [r for r in store.list_recommendations(limit=500)
                      if r.get("rec_date") == today]
    if existing_today and not force:
        return {"generated": False, "reason": "Already generated today",
                "date": today, "existing": len(existing_today),
                "advisory_only": True}

    proposals: List[Dict[str, Any]] = []

    import phase24_analytics as ana
    from phase24_engine import risk_rule_learning

    # Strategy signals
    sr = ana.strategy_ranking()
    for item in sr.get("items", []):
        if item["trades"] >= 5 and (item.get("win_rate") or 0) < 0.35 \
                and (item.get("total_pnl") or 0) < 0:
            proposals.append({
                "kind": "STRATEGY",
                "title": f"Consider disabling strategy {item['strategy']}",
                "detail": (f"{item['trades']} trades, win rate "
                           f"{round((item['win_rate'] or 0) * 100, 1)}%, total "
                           f"P&L {item['total_pnl']}"),
                "evidence": {"strategy": item["strategy"],
                             "win_rate": item.get("win_rate"),
                             "total_pnl": item.get("total_pnl")},
            })
        if item["trades"] >= 5 and (item.get("profit_factor") or 0) > 2.0:
            proposals.append({
                "kind": "STRATEGY",
                "title": f"Consider larger allocation to {item['strategy']}",
                "detail": (f"Profit factor {item['profit_factor']} over "
                           f"{item['trades']} trades"),
                "evidence": {"strategy": item["strategy"],
                             "profit_factor": item.get("profit_factor")},
            })

    # Risk-rule signals
    rl = risk_rule_learning()
    for rule in rl.get("rules", []):
        if rule.get("verdict") == "BLOCKS_PROFITS":
            proposals.append({
                "kind": "RISK_RULE",
                "title": f"Review gate '{rule['rule']}' — it blocks profitable trades",
                "detail": (f"Only {round((rule['effectiveness'] or 0) * 100, 1)}% of "
                           f"its rejections were correct over {rule['evaluated']} "
                           f"evaluated rejections"),
                "evidence": rule,
            })
        elif rule.get("verdict") == "SAVES_MONEY":
            proposals.append({
                "kind": "RISK_RULE",
                "title": f"Gate '{rule['rule']}' is effective — keep it",
                "detail": (f"{round((rule['effectiveness'] or 0) * 100, 1)}% of its "
                           f"rejections were correct"),
                "evidence": rule,
            })

    # Calibration signals
    try:
        cal = ana.calibration()
        for b in cal.get("buckets", []):
            if b.get("status") == "OK" and b.get("calibration_error") is not None \
                    and b["calibration_error"] > 0.15:
                proposals.append({
                    "kind": "CALIBRATION",
                    "title": f"Confidence bucket {b['bucket']} is miscalibrated",
                    "detail": (f"Predicted {b['predicted_confidence']}% vs observed "
                               f"{round((b['win_rate'] or 0) * 100, 1)}% win rate over "
                               f"{b['trades']} trades"),
                    "evidence": {"bucket": b["bucket"],
                                 "calibration_error": b["calibration_error"]},
                })
    except Exception:
        pass

    # Sector signals
    sec = ana.sector_ranking()
    for item in sec.get("items", []):
        if item["trades"] >= 5 and (item.get("total_pnl") or 0) < 0 \
                and (item.get("win_rate") or 0) < 0.35:
            proposals.append({
                "kind": "SECTOR",
                "title": f"Consider reducing exposure in {item['sector']}",
                "detail": (f"{item['trades']} trades, total P&L {item['total_pnl']}"),
                "evidence": {"sector": item["sector"],
                             "total_pnl": item.get("total_pnl")},
            })

    # Backtest-sourced missed opportunity signals (Task 6)
    try:
        all_opps = store.list_missed_opps(limit=5000)
        bt_opps = [o for o in all_opps
                   if (o.get("record") or {}).get("source") == "backtest"]
        # Group by backtest_run_id
        by_run: Dict[str, List[Dict[str, Any]]] = {}
        for o in bt_opps:
            rec = o.get("record") or {}
            rid = str(rec.get("backtest_run_id") or "unknown")
            by_run.setdefault(rid, []).append(rec)

        for rid, entries in by_run.items():
            sample = len(entries)
            if sample < 10:  # insufficient evidence
                continue
            profitable_count = sum(
                1 for e in entries if e.get("would_have_been_profitable")
            )
            win_rate = round(profitable_count / sample, 3)
            fwd_returns = sorted(
                float(e["return_at_horizon_pct"]) for e in entries
                if e.get("return_at_horizon_pct") is not None
            )
            median_fwd = (round(fwd_returns[len(fwd_returns) // 2], 2)
                          if fwd_returns else None)
            false_pos_risk = round(1.0 - win_rate, 3)
            confidence_level = ("HIGH" if sample >= 50
                                 else "MEDIUM" if sample >= 20 else "LOW")
            interval = entries[0].get("interval", "unknown") if entries else "unknown"

            # Per-symbol breakdown
            by_sym: Dict[str, List] = {}
            for e in entries:
                sym = str(e.get("symbol") or "UNKNOWN")
                by_sym.setdefault(sym, []).append(e)
            symbol_breakdown = {
                sym: {
                    "count": len(syms),
                    "win_rate": round(
                        sum(1 for e in syms if e.get("would_have_been_profitable"))
                        / len(syms), 3),
                }
                for sym, syms in by_sym.items()
            }

            if win_rate >= 0.55:  # majority of WATCH/REJECTED signals were profitable
                proposals.append({
                    "kind": "BACKTEST_LEARNING",
                    "source": "backtest",
                    "backtest_run_id": rid,
                    "title": (f"Backtest {rid}: {round(win_rate * 100, 1)}% of "
                              f"WATCH/REJECTED signals were profitable"),
                    "detail": (
                        f"Run {rid} ({interval}, n={sample}): "
                        f"win rate {round(win_rate * 100, 1)}%, "
                        f"median forward return {median_fwd}%, "
                        f"false-positive risk {round(false_pos_risk * 100, 1)}%, "
                        f"confidence: {confidence_level}. "
                        f"Evidence suggests some decisions blocked profitable moves. "
                        f"Advisory only — no gates or thresholds changed."
                    ),
                    "evidence": {
                        "backtest_run_id": rid,
                        "interval": interval,
                        "sample_size": sample,
                        "win_rate": win_rate,
                        "profitable_count": profitable_count,
                        "median_forward_return_pct": median_fwd,
                        "false_positive_risk": false_pos_risk,
                        "confidence_level": confidence_level,
                        "source": "backtest",
                        "symbol_breakdown": symbol_breakdown,
                    },
                })
    except Exception:
        pass  # backtest section must never block live recommendations

    stored = []
    for p in proposals:
        p["advisory_only"] = True
        p["requires_manual_approval"] = True
        p["generated_at"] = _now()
        stored.append(store.insert_recommendation(today, p))

    return {"generated": True, "date": today, "count": len(stored),
            "recommendations": stored, "advisory_only": True,
            "note": "Recommendations are NEVER applied automatically. "
                    "Approval records intent only."}


# ── Reports ──────────────────────────────────────────────────────────────────

def _period_key(period: str, now: datetime) -> str:
    d = now.astimezone(IST).date()
    if period == "daily":
        return d.isoformat()
    if period == "weekly":
        iso = d.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    if period == "monthly":
        return f"{d.year}-{d.month:02d}"
    if period == "quarterly":
        return f"{d.year}-Q{(d.month - 1) // 3 + 1}"
    raise ValueError(f"unknown period {period}")


def _period_days(period: str) -> int:
    return {"daily": 1, "weekly": 7, "monthly": 30, "quarterly": 92}[period]


def build_report(period: str) -> Dict[str, Any]:
    """Assemble a report payload for the current period from phase24 analytics."""
    import phase24_analytics as ana
    days = _period_days(period)
    lessons = ana.lessons(days, period)
    recs = [r for r in store.list_recommendations(limit=200)
            if r.get("status") == "PROPOSED"]
    scorecard = ana.ai_scorecard()
    expected: List[str] = []
    for m in lessons.get("mistakes", []):
        expected.append(f"Addressing: {m}")
    return {
        "period": period,
        "period_key": _period_key(period, datetime.now(timezone.utc)),
        "generated_at": _now(),
        "performance": lessons.get("stats"),
        "trades": lessons.get("trades"),
        "mistakes": lessons.get("mistakes"),
        "improvements": lessons.get("improvements"),
        "recommendations": [r.get("record") for r in recs][:20],
        "expected_improvements": expected,
        "scorecard": {"overall": scorecard.get("overall"),
                      "scores": scorecard.get("scores"),
                      "strengths": scorecard.get("strengths"),
                      "weaknesses": scorecard.get("weaknesses")},
        "advisory_only": True,
        "label": "PAPER / RESEARCH ONLY",
    }


def generate_report(period: str, force: bool = False) -> Dict[str, Any]:
    """Generate + persist the report for the current period (idempotent)."""
    if period not in store.REPORT_PERIODS:
        return {"error": f"period must be one of {store.REPORT_PERIODS}"}
    key = _period_key(period, datetime.now(timezone.utc))
    if not force and store.get_report(period, key):
        return {"generated": False, "reason": "Report already exists",
                "period": period, "period_key": key}
    report = build_report(period)
    saved = store.save_report(period, key, report)
    return {"generated": saved["inserted"], "period": period,
            "period_key": key, "report": report}


# ── Scheduler tick (KV-guarded, mirrors the daily session report) ────────────

def maybe_run_daily_learning(force: bool = False) -> Dict[str, Any]:
    """Once per IST day after market close: capture closed trades, run
    missed-opportunity analysis, generate recommendations and any due
    reports. KV-guarded so concurrent ticks never duplicate work.
    Never raises — designed to run inside the phase20 scheduler tick."""
    out: Dict[str, Any] = {"ran": False}
    try:
        import phase20_store as p20s
        today = _today_ist()
        if not force:
            try:
                from market_hours import market_status
                m = market_status()
                mstate = str(m.get("state") or m.get("market_state") or "").upper()
                if mstate != "CLOSED":
                    return {"ran": False, "reason": f"Market not closed ({mstate})"}
            except Exception:
                pass
            if p20s.kv_get("phase24_learning_date") == today:
                return {"ran": False, "reason": "Already ran today"}
        prev = p20s.kv_get("phase24_learning_date")
        p20s.kv_set("phase24_learning_date", today)
        try:
            from phase24_engine import capture_closed_trades, \
                run_missed_opportunity_analysis
            out["capture"] = capture_closed_trades()
            out["missed"] = {k: v for k, v in
                             run_missed_opportunity_analysis().items()
                             if k != "items"}
            out["recommendations"] = {
                k: v for k, v in generate_recommendations().items()
                if k != "recommendations"}
            reports = {}
            for period in store.REPORT_PERIODS:
                reports[period] = {k: v for k, v in
                                   generate_report(period).items()
                                   if k != "report"}
            out["reports"] = reports
            out["ran"] = True
        except Exception:
            p20s.kv_set("phase24_learning_date", prev)  # allow retry next tick
            raise
    except Exception as exc:
        out["error"] = str(exc)[:300]
    return out
