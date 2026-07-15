"""
phase16_validation.py — Phase 16: Paper Trading Validation & Strategy Proving.

Feature freeze phase: NO new indicators, NO new strategies, NO live trading,
NO changes to broker execution / risk engine / AI decision logic. This module
only READS existing paper-trading history and produces validation statistics,
reviews and recommendations. Recommendations are advisory only — nothing is
ever changed automatically.

Honesty rules: with few completed trades most statistics are not yet
significant; every section carries `sample_size` and an explicit
`sufficient_data` flag, and displays "Insufficient Data" semantics rather than
fabricating results. PAPER TRADING / RESEARCH ONLY.
"""

from __future__ import annotations

import json
import math
import os
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from config import SECTOR_MAP, INITIAL_CAPITAL as STARTING_CAPITAL
from paper_trader import get_trade_replay, get_trades, _load_state  # type: ignore

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LABEL = "PAPER / RESEARCH ONLY"

# Minimum completed trades before a statistic is considered meaningful.
MIN_TRADES_OVERALL = 20
MIN_TRADES_GROUP = 5
TARGET_TRADES = 500          # production-readiness goal from the spec
TARGET_TRADING_DAYS = 100

CONFIDENCE_BANDS = [(0, 20), (21, 40), (41, 60), (61, 80), (81, 100)]
REGIME_BUCKETS = ["TRENDING", "SIDEWAYS", "VOLATILE", "BULLISH", "BEARISH"]

NA = "Insufficient Data"


# ── shared helpers ───────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _round_trips() -> list[dict]:
    return list(get_trade_replay())


def _sector_of(symbol: str) -> str:
    for sector, symbols in SECTOR_MAP.items():
        if symbol in symbols:
            return sector
    return "UNKNOWN"


def _safe_div(a: float, b: float) -> float | None:
    return round(a / b, 4) if b else None


def _basic_stats(trades: list[dict]) -> dict:
    """Win rate / PF / expectancy / returns for a list of round trips."""
    n = len(trades)
    if n == 0:
        return {"trades": 0, "wins": 0, "losses": 0, "win_rate_pct": None,
                "profit_factor": None, "avg_return_pct": None,
                "expectancy": None, "total_pnl": 0.0, "sufficient_data": False}
    wins = [t for t in trades if (t.get("pnl") or 0) > 0]
    losses = [t for t in trades if (t.get("pnl") or 0) <= 0]
    gross_win = sum(t["pnl"] for t in wins)
    gross_loss = abs(sum(t["pnl"] for t in losses))
    avg_ret = sum(t.get("pnl_pct") or 0 for t in trades) / n
    expectancy = sum(t.get("pnl") or 0 for t in trades) / n
    return {
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate_pct": round(100 * len(wins) / n, 1),
        "profit_factor": _safe_div(gross_win, gross_loss) if gross_loss else (None if not wins else math.inf),
        "avg_return_pct": round(avg_ret, 2),
        "expectancy": round(expectancy, 2),
        "total_pnl": round(sum(t.get("pnl") or 0 for t in trades), 2),
        "sufficient_data": n >= MIN_TRADES_GROUP,
    }


def _json_safe(obj: Any) -> Any:
    if isinstance(obj, float) and (math.isinf(obj) or math.isnan(obj)):
        return None
    if isinstance(obj, dict):
        return {k: _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_json_safe(v) for v in obj]
    return obj


def _trading_days(trades: list[dict]) -> int:
    days = {str(t.get("entry_time", ""))[:10] for t in trades if t.get("entry_time")}
    days |= {str(t.get("exit_time", ""))[:10] for t in trades if t.get("exit_time")}
    days.discard("")
    return len(days)


def _max_drawdown_pct(trades: list[dict]) -> float | None:
    """Equity-curve drawdown over completed trades (chronological)."""
    if not trades:
        return None
    equity = STARTING_CAPITAL
    peak = equity
    max_dd = 0.0
    for t in sorted(trades, key=lambda x: str(x.get("exit_time", ""))):
        equity += t.get("pnl") or 0
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak * 100)
    return round(max_dd, 2)


def _sharpe(trades: list[dict]) -> float | None:
    rets = [t.get("pnl_pct") or 0 for t in trades]
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    sd = math.sqrt(var)
    return round(mean / sd * math.sqrt(252), 2) if sd > 0 else None


# ── 1. validation dashboard overview ─────────────────────────────────────────

def validation_overview() -> dict:
    rts = _round_trips()
    state = _load_state()
    open_trades = len(state.get("positions", {}))
    stats = _basic_stats(rts)
    holding = [t.get("holding_period_days") for t in rts if t.get("holding_period_days") is not None]
    rrs = [t.get("rr_ratio") for t in rts if t.get("rr_ratio")]
    capital_now = STARTING_CAPITAL + stats["total_pnl"]

    timeline = validation_timeline(rts)
    score = timeline["production_readiness_pct"]

    return _json_safe({
        "success": True,
        "generated_at": _now(),
        "label": LABEL,
        "overall_validation_score": score,
        "maturity": timeline["maturity"],
        "trading_days_completed": _trading_days(rts),
        "completed_trades": stats["trades"],
        "open_trades": open_trades,
        "win_rate_pct": stats["win_rate_pct"],
        "profit_factor": stats["profit_factor"],
        "expectancy": stats["expectancy"],
        "max_drawdown_pct": _max_drawdown_pct(rts),
        "sharpe_ratio": _sharpe(rts),
        "avg_holding_days": round(sum(holding) / len(holding), 2) if holding else None,
        "avg_risk_reward": round(sum(rrs) / len(rrs), 2) if rrs else None,
        "capital_start": STARTING_CAPITAL,
        "capital_now": round(capital_now, 2),
        "capital_growth_pct": round((capital_now - STARTING_CAPITAL) / STARTING_CAPITAL * 100, 2),
        "sufficient_data": stats["trades"] >= MIN_TRADES_OVERALL,
        "min_trades_for_significance": MIN_TRADES_OVERALL,
        "note": None if stats["trades"] >= MIN_TRADES_OVERALL else
                f"Only {stats['trades']} completed trades — statistics are not yet significant "
                f"(minimum {MIN_TRADES_OVERALL}).",
    })


# ── 2. strategy scorecard ────────────────────────────────────────────────────

def _strategy_status(s: dict) -> tuple[str, str]:
    """Return (status, recommendation). Advisory only — never auto-applied."""
    if not s["sufficient_data"]:
        return "Watch", f"Only {s['trades']} trades — keep collecting evidence (need {MIN_TRADES_GROUP}+)."
    wr, pf = s["win_rate_pct"] or 0, s["profit_factor"] or 0
    if wr >= 60 and pf and pf >= 1.8:
        return "Excellent", "Performing strongly — maintain current usage."
    if wr >= 50 and pf and pf >= 1.3:
        return "Good", "Positive edge — continue monitoring."
    if wr >= 40:
        return "Watch", "Marginal results — monitor closely."
    if pf and pf >= 0.8:
        return "Poor", "Underperforming — consider reducing reliance (recommendation only)."
    return "Disable", "Consistently losing — recommend disabling (never automatic; human decision)."


def strategy_scorecard() -> dict:
    rts = _round_trips()
    by_strategy: dict[str, list[dict]] = defaultdict(list)
    for t in rts:
        by_strategy[t.get("strategy_name") or "Unknown"].append(t)
    rows = []
    for name, trades in sorted(by_strategy.items()):
        s = _basic_stats(trades)
        best = max(trades, key=lambda t: t.get("pnl") or 0)
        worst = min(trades, key=lambda t: t.get("pnl") or 0)
        status, rec = _strategy_status(s)
        rows.append({**s, "strategy": name,
                     "max_drawdown_pct": _max_drawdown_pct(trades),
                     "best_trade": {"symbol": best.get("symbol"), "pnl": best.get("pnl")},
                     "worst_trade": {"symbol": worst.get("symbol"), "pnl": worst.get("pnl")},
                     "status": status, "recommendation": rec})
    return _json_safe({
        "success": True, "generated_at": _now(), "label": LABEL,
        "strategies": rows,
        "note": "Statuses are recommendations only — strategies are never disabled automatically.",
        "sample_size": len(rts),
    })


# ── 3. confidence validation ─────────────────────────────────────────────────

def confidence_validation() -> dict:
    rts = _round_trips()
    bands = []
    for lo, hi in CONFIDENCE_BANDS:
        in_band = [t for t in rts
                   if t.get("signal_confidence") is not None and lo <= t["signal_confidence"] <= hi]
        s = _basic_stats(in_band)
        holding = [t.get("holding_period_days") for t in in_band if t.get("holding_period_days") is not None]
        bands.append({**s, "band": f"{lo}-{hi}",
                      "avg_holding_days": round(sum(holding) / len(holding), 2) if holding else None})
    # Does confidence predict success? Require at least 2 sufficiently-populated bands.
    populated = [b for b in bands if b["sufficient_data"]]
    if len(populated) >= 2:
        ordered = all(populated[i]["win_rate_pct"] <= populated[i + 1]["win_rate_pct"]
                      for i in range(len(populated) - 1))
        verdict = ("Confidence bands are monotonically predictive of win rate."
                   if ordered else
                   "Confidence does NOT yet cleanly predict win rate — calibration review recommended.")
    else:
        verdict = NA + f" — need {MIN_TRADES_GROUP}+ trades in at least 2 bands."
    return _json_safe({
        "success": True, "generated_at": _now(), "label": LABEL,
        "bands": bands, "verdict": verdict, "sample_size": len(rts),
        "sufficient_data": len(populated) >= 2,
    })


# ── 4. market regime validation ──────────────────────────────────────────────

def _regime_bucket(t: dict) -> str:
    raw = str(t.get("regime") or t.get("market_regime_at_entry") or "").upper()
    for b in REGIME_BUCKETS:
        if b in raw:
            return b
    if "UPTREND" in raw or "DOWNTREND" in raw or "TREND" in raw:
        return "TRENDING"
    if "RANG" in raw or "SIDEWAY" in raw:
        return "SIDEWAYS"
    if "VOLATIL" in raw or "CHOPPY" in raw:
        return "VOLATILE"
    return "UNKNOWN"


def regime_validation() -> dict:
    rts = _round_trips()
    by_regime: dict[str, list[dict]] = defaultdict(list)
    for t in rts:
        by_regime[_regime_bucket(t)].append(t)
    rows = []
    for regime in REGIME_BUCKETS + (["UNKNOWN"] if "UNKNOWN" in by_regime else []):
        trades = by_regime.get(regime, [])
        s = _basic_stats(trades)
        strat_stats = defaultdict(list)
        for t in trades:
            strat_stats[t.get("strategy_name") or "Unknown"].append(t.get("pnl") or 0)
        ranked = sorted(strat_stats.items(), key=lambda kv: sum(kv[1]), reverse=True)
        rows.append({**s, "regime": regime,
                     "risk_max_drawdown_pct": _max_drawdown_pct(trades),
                     "best_strategy": ranked[0][0] if ranked else None,
                     "worst_strategy": ranked[-1][0] if len(ranked) > 1 else None})
    return _json_safe({"success": True, "generated_at": _now(), "label": LABEL,
                       "regimes": rows, "sample_size": len(rts)})


# ── 5. sector validation ─────────────────────────────────────────────────────

def sector_validation() -> dict:
    rts = _round_trips()
    total_pnl = sum(t.get("pnl") or 0 for t in rts)
    by_sector: dict[str, list[dict]] = defaultdict(list)
    for t in rts:
        by_sector[_sector_of(t.get("symbol", ""))].append(t)
    rows = []
    for sector in sorted(set(list(SECTOR_MAP.keys()) + list(by_sector.keys()))):
        trades = by_sector.get(sector, [])
        s = _basic_stats(trades)
        rows.append({**s, "sector": sector,
                     "contribution_pct": round(100 * s["total_pnl"] / total_pnl, 1)
                                          if total_pnl else None})
    return _json_safe({"success": True, "generated_at": _now(), "label": LABEL,
                       "sectors": rows, "sample_size": len(rts)})


# ── 6. AI decision validation ────────────────────────────────────────────────

def ai_decision_validation() -> dict:
    rts = _round_trips()
    decisions = json.load(open(os.path.join(BASE_DIR, "ai_decisions_cache.json"))) \
        if os.path.exists(os.path.join(BASE_DIR, "ai_decisions_cache.json")) else []
    if isinstance(decisions, dict):
        decisions = decisions.get("decisions", [])
    counts = defaultdict(int)
    for d in decisions:
        if isinstance(d, dict):
            a = str(d.get("decision") or d.get("final_action") or d.get("action") or "").upper()
            if "BUY" in a:
                counts["BUY"] += 1
            elif "WATCH" in a or "MONITOR" in a:
                counts["WATCH"] += 1
            elif "IGNORE" in a or "AVOID" in a or "NO_TRADE" in a:
                counts["IGNORE"] += 1
    executed = len(rts)
    buys_correct = [t for t in rts if (t.get("pnl") or 0) > 0]
    exits_correct = [t for t in rts if t.get("exit_type") in ("TARGET_HIT", "SIGNAL_EXIT")
                     and (t.get("pnl") or 0) > 0]
    enough = executed >= MIN_TRADES_GROUP
    return _json_safe({
        "success": True, "generated_at": _now(), "label": LABEL,
        "buy_recommendations": counts["BUY"],
        "watch_recommendations": counts["WATCH"],
        "ignore_recommendations": counts["IGNORE"],
        "executed_recommendations": executed,
        "ignored_recommendations": max(counts["BUY"] - executed, 0),
        "correct_buy_pct": round(100 * len(buys_correct) / executed, 1) if enough else None,
        "correct_exit_pct": round(100 * len(exits_correct) / executed, 1) if enough else None,
        "correct_hold_pct": None,   # honest: no hold-decision outcome tracking exists yet
        "false_positives": len(rts) - len(buys_correct) if enough else None,
        "false_negatives": None,    # honest: unexecuted-signal outcomes are not tracked
        "sufficient_data": enough,
        "note": ("HOLD correctness and false negatives require outcome tracking of "
                 "non-executed recommendations, which does not exist yet — shown as Insufficient Data. "
                 f"Executed sample: {executed} trades."),
    })


# ── 7. trade review ──────────────────────────────────────────────────────────

def _lessons(t: dict) -> dict:
    pnl = t.get("pnl") or 0
    win = pnl > 0
    winning, losing, lessons = [], [], []
    conf = t.get("signal_confidence")
    rr = t.get("rr_ratio")
    if win:
        if conf and conf >= 70:
            winning.append(f"High entry confidence ({conf})")
        if rr and rr >= 2:
            winning.append(f"Favourable risk/reward ({rr}:1)")
        if t.get("exit_type") == "TARGET_HIT":
            winning.append("Exit discipline: target hit as planned")
        lessons.append("Setup conditions repeated here are worth prioritising.")
    else:
        if conf is not None and conf < 50:
            losing.append(f"Low entry confidence ({conf})")
        if t.get("exit_type") == "STOP_HIT":
            losing.append("Stop-loss hit — entry timing or stop placement to review")
        if rr and rr < 1.5:
            losing.append(f"Thin risk/reward ({rr}:1)")
        lessons.append("Review whether the entry matched the regime and quality gates.")
    if not winning and win:
        winning.append("No standout factor identified")
    if not losing and not win:
        losing.append("No standout factor identified")
    return {"lessons_learned": lessons, "winning_factors": winning, "losing_factors": losing}


def trade_review() -> dict:
    rts = _round_trips()
    reviews = []
    for t in rts:
        reviews.append(_json_safe({
            "symbol": t.get("symbol"),
            "entry_time": t.get("entry_time"), "exit_time": t.get("exit_time"),
            "entry_price": t.get("entry_price"), "exit_price": t.get("exit_price"),
            "quantity": t.get("quantity"),
            "pnl": t.get("pnl"), "pnl_pct": t.get("pnl_pct"),
            "market_regime": t.get("regime") or NA,
            "confidence": t.get("signal_confidence"),
            "opportunity_score": t.get("opportunity_score"),
            "strategy": t.get("strategy_name"),
            "ai_explanation": t.get("plain_english") or NA,
            "exit_reason": t.get("reason_exit") or t.get("exit_type") or NA,
            "risk_pct": t.get("risk_pct"), "reward_pct": t.get("reward_pct"),
            "holding_period_days": t.get("holding_period_days"),
            **_lessons(t),
        }))
    return {"success": True, "generated_at": _now(), "label": LABEL,
            "trades": reviews, "count": len(reviews)}


# ── 8/9. weekly & monthly reviews ────────────────────────────────────────────

def _period_report(rts: list[dict], period_days: int, title: str) -> dict:
    cutoff = datetime.now(timezone.utc).timestamp() - period_days * 86400
    def _ts(t):
        try:
            return datetime.fromisoformat(str(t.get("exit_time"))).timestamp()
        except Exception:
            return 0
    recent = [t for t in rts if _ts(t) >= cutoff]
    s = _basic_stats(recent)
    by_strat = defaultdict(float)
    by_sector = defaultdict(float)
    for t in recent:
        by_strat[t.get("strategy_name") or "Unknown"] += t.get("pnl") or 0
        by_sector[_sector_of(t.get("symbol", ""))] += t.get("pnl") or 0
    strat_rank = sorted(by_strat.items(), key=lambda kv: kv[1], reverse=True)
    sector_rank = sorted(by_sector.items(), key=lambda kv: kv[1], reverse=True)
    biggest_win = max(recent, key=lambda t: t.get("pnl") or 0, default=None)
    biggest_loss = min(recent, key=lambda t: t.get("pnl") or 0, default=None)
    mistakes = []
    for t in recent:
        if (t.get("pnl") or 0) <= 0:
            mistakes.extend(_lessons(t)["losing_factors"])
    common = sorted({m for m in mistakes}, key=mistakes.count, reverse=True)[:3]
    return _json_safe({
        "title": title, "period_days": period_days, "stats": s,
        "best_strategy": strat_rank[0][0] if strat_rank else NA,
        "worst_strategy": strat_rank[-1][0] if len(strat_rank) > 1 else NA,
        "best_sector": sector_rank[0][0] if sector_rank else NA,
        "worst_sector": sector_rank[-1][0] if len(sector_rank) > 1 else NA,
        "biggest_winner": {"symbol": biggest_win.get("symbol"), "pnl": biggest_win.get("pnl")}
                          if biggest_win else NA,
        "biggest_loser": {"symbol": biggest_loss.get("symbol"), "pnl": biggest_loss.get("pnl")}
                         if biggest_loss else NA,
        "common_mistakes": common or ([NA] if not recent else ["No losing trades in period"]),
        "sufficient_data": s["sufficient_data"],
    })


def weekly_report() -> dict:
    rts = _round_trips()
    rpt = _period_report(rts, 7, "Weekly Paper Trading Report")
    rpt["ai_recommendations"] = improvement_recommendations()["recommendations"]
    rpt["portfolio_summary"] = validation_overview()
    rpt.update({"success": True, "generated_at": _now(), "label": LABEL})
    return rpt


def monthly_report() -> dict:
    rts = _round_trips()
    rpt = _period_report(rts, 30, "Monthly Validation Report")
    sc = strategy_scorecard()["strategies"]
    cal = _calibration_snapshot()
    rpt.update({
        "success": True, "generated_at": _now(), "label": LABEL,
        "portfolio_growth_pct": validation_overview()["capital_growth_pct"],
        "strategy_ranking": sorted(
            [{"strategy": s["strategy"], "total_pnl": s["total_pnl"], "status": s["status"]}
             for s in sc], key=lambda x: x["total_pnl"] or 0, reverse=True),
        "risk_summary": {"max_drawdown_pct": _max_drawdown_pct(rts), "sharpe": _sharpe(rts)},
        "accuracy_trend": NA if len(rts) < MIN_TRADES_OVERALL else "See confidence validation bands",
        "confidence_calibration": cal,
        "learning_progress": _learning_snapshot(),
    })
    return _json_safe(rpt)


def _calibration_snapshot() -> Any:
    try:
        cal = json.load(open(os.path.join(BASE_DIR, "calibration_state.json")))
        return {k: cal.get(k) for k in ("method", "brier_score", "ece", "sample_size")
                if k in cal} or NA
    except Exception:
        return NA


def _learning_snapshot() -> Any:
    try:
        from learning_engine import compute_learning_summary
        ls = compute_learning_summary()
        return {"strategies_tracked": len(ls.get("strategies", [])),
                "total_closed_trades": ls.get("total_closed_trades",
                                              ls.get("closed_trades", None))}
    except Exception:
        return NA


# ── 10. AI improvement recommendations ───────────────────────────────────────

def improvement_recommendations() -> dict:
    rts = _round_trips()
    recs: list[dict] = []
    # strategy × regime weaknesses/strengths
    cells: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for t in rts:
        cells[(t.get("strategy_name") or "Unknown", _regime_bucket(t))].append(t)
    for (strat, regime), trades in cells.items():
        s = _basic_stats(trades)
        if not s["sufficient_data"]:
            continue
        if (s["win_rate_pct"] or 0) < 40:
            recs.append({"type": "WEAKNESS", "target": strat,
                         "detail": f"{strat} performs poorly in {regime} markets "
                                   f"(win rate {s['win_rate_pct']}% over {s['trades']} trades).",
                         "suggestion": "Consider reducing confidence weighting by ~5% in this regime.",
                         "auto_applied": False})
        elif (s["win_rate_pct"] or 0) >= 65:
            recs.append({"type": "STRENGTH", "target": strat,
                         "detail": f"{strat} performs best in {regime} markets "
                                   f"(win rate {s['win_rate_pct']}% over {s['trades']} trades).",
                         "suggestion": "Consider increasing priority in this regime.",
                         "auto_applied": False})
    # sector strengths
    by_sector: dict[str, list[dict]] = defaultdict(list)
    for t in rts:
        by_sector[_sector_of(t.get("symbol", ""))].append(t)
    for sector, trades in by_sector.items():
        s = _basic_stats(trades)
        if s["sufficient_data"] and (s["win_rate_pct"] or 0) >= 65:
            recs.append({"type": "STRENGTH", "target": sector,
                         "detail": f"Strong results in {sector} "
                                   f"(win rate {s['win_rate_pct']}% over {s['trades']} trades).",
                         "suggestion": "Consider increasing sector priority.",
                         "auto_applied": False})
    if not recs:
        recs.append({"type": "INFO", "target": "ALL",
                     "detail": f"{NA} — only {len(rts)} completed trades; "
                               f"need {MIN_TRADES_GROUP}+ per strategy/regime cell before "
                               "recommendations become meaningful.",
                     "suggestion": "Continue paper trading to accumulate evidence.",
                     "auto_applied": False})
    return {"success": True, "generated_at": _now(), "label": LABEL,
            "recommendations": recs,
            "note": "Recommendations only — rules are NEVER changed automatically."}


# ── 11/12. failure & success analysis ────────────────────────────────────────

def _grouped(trades: list[dict], key_fn, label: str) -> list[dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for t in trades:
        groups[str(key_fn(t))].append(t)
    return [{"group": k, "dimension": label, **_basic_stats(v)}
            for k, v in sorted(groups.items())]


def failure_analysis() -> dict:
    losers = [t for t in _round_trips() if (t.get("pnl") or 0) <= 0]
    def conf_band(t):
        c = t.get("signal_confidence")
        if c is None:
            return "unknown"
        for lo, hi in CONFIDENCE_BANDS:
            if lo <= c <= hi:
                return f"{lo}-{hi}"
        return "unknown"
    def hold_band(t):
        h = t.get("holding_period_days")
        if h is None:
            return "unknown"
        return "intraday" if h < 1 else ("1-5d" if h <= 5 else ">5d")
    def risk_band(t):
        r = t.get("risk_pct")
        if r is None:
            return "unknown"
        return "<2%" if r < 2 else ("2-5%" if r <= 5 else ">5%")
    return _json_safe({
        "success": True, "generated_at": _now(), "label": LABEL,
        "losing_trades": len(losers),
        "by_sector": _grouped(losers, lambda t: _sector_of(t.get("symbol", "")), "sector"),
        "by_strategy": _grouped(losers, lambda t: t.get("strategy_name") or "Unknown", "strategy"),
        "by_regime": _grouped(losers, _regime_bucket, "regime"),
        "by_confidence": _grouped(losers, conf_band, "confidence"),
        "by_holding_time": _grouped(losers, hold_band, "holding_time"),
        "by_risk": _grouped(losers, risk_band, "risk"),
        "sufficient_data": len(losers) >= MIN_TRADES_GROUP,
        "note": None if len(losers) >= MIN_TRADES_GROUP else
                f"{NA} — only {len(losers)} losing trades recorded.",
    })


def success_analysis() -> dict:
    winners = [t for t in _round_trips() if (t.get("pnl") or 0) > 0]
    regimes = defaultdict(int)
    holds = []
    confs = []
    risks = defaultdict(int)
    for t in winners:
        regimes[_regime_bucket(t)] += 1
        if t.get("holding_period_days") is not None:
            holds.append(t["holding_period_days"])
        if t.get("signal_confidence") is not None:
            confs.append(t["signal_confidence"])
        r = t.get("risk_pct")
        risks["unknown" if r is None else ("<2%" if r < 2 else ("2-5%" if r <= 5 else ">5%"))] += 1
    indicators = defaultdict(int)
    for t in winners:
        snap = t.get("indicators_at_entry") or {}
        if isinstance(snap, dict):
            for k, v in snap.items():
                if isinstance(v, (int, float)) and v:
                    indicators[k] += 1
    enough = len(winners) >= MIN_TRADES_GROUP
    return _json_safe({
        "success": True, "generated_at": _now(), "label": LABEL,
        "winning_trades": len(winners),
        "common_indicators": sorted(indicators, key=indicators.get, reverse=True)[:5] or [NA],
        "common_regimes": sorted(regimes, key=regimes.get, reverse=True) or [NA],
        "common_risk_levels": sorted(risks, key=risks.get, reverse=True) or [NA],
        "avg_holding_days": round(sum(holds) / len(holds), 2) if holds else None,
        "best_confidence_range": (f"{min(confs):.0f}-{max(confs):.0f}" if confs else NA),
        "sufficient_data": enough,
        "note": None if enough else f"{NA} — only {len(winners)} winning trades recorded.",
    })


# ── 13. validation timeline ──────────────────────────────────────────────────

def validation_timeline(rts: list[dict] | None = None) -> dict:
    rts = rts if rts is not None else _round_trips()
    days = _trading_days(rts)
    trades = len(rts)
    cal = _calibration_snapshot()
    cal_pct = None
    if isinstance(cal, dict) and cal.get("brier_score") is not None:
        cal_pct = round(max(0.0, (1 - cal["brier_score"])) * 100, 1)
    # Strategy stability: share of strategies with sufficient data that are Good/Excellent
    sc = []
    by_strategy: dict[str, list[dict]] = defaultdict(list)
    for t in rts:
        by_strategy[t.get("strategy_name") or "Unknown"].append(t)
    for name, ts in by_strategy.items():
        s = _basic_stats(ts)
        if s["sufficient_data"]:
            sc.append(_strategy_status(s)[0] in ("Excellent", "Good"))
    stability = round(100 * sum(sc) / len(sc), 1) if sc else None
    progress_days = min(100.0, 100 * days / TARGET_TRADING_DAYS)
    progress_trades = min(100.0, 100 * trades / TARGET_TRADES)
    components = [progress_days, progress_trades]
    if cal_pct is not None:
        components.append(cal_pct)
    if stability is not None:
        components.append(stability)
    readiness = round(sum(components) / len(components), 1)
    maturity = ("VALIDATED" if readiness >= 85 else
                "MATURING" if readiness >= 50 else
                "EARLY VALIDATION" if readiness >= 15 else
                "COLLECTING EVIDENCE")
    return _json_safe({
        "success": True, "generated_at": _now(), "label": LABEL,
        "trading_days": days, "trading_days_goal": TARGET_TRADING_DAYS,
        "completed_trades": trades, "completed_trades_goal": TARGET_TRADES,
        "confidence_calibration_pct": cal_pct,
        "strategy_stability_pct": stability,
        "production_readiness_pct": readiness,
        "maturity": maturity,
        "note": ("Calibration and stability shown as Insufficient Data until enough "
                 "closed trades exist.") if (cal_pct is None or stability is None) else None,
    })


# ── 14. bug detection / health report ────────────────────────────────────────

def bug_detection() -> dict:
    issues: list[dict] = []
    checks = 0

    def check(name: str, problem: bool, detail: str, severity: str = "WARN"):
        nonlocal checks
        checks += 1
        if problem:
            issues.append({"check": name, "severity": severity, "detail": detail})

    # repeated scan failures (phase15 audit log)
    audit = []
    try:
        audit_raw = json.load(open(os.path.join(BASE_DIR, "phase15_audit_log.json")))
        audit = audit_raw if isinstance(audit_raw, list) else audit_raw.get("entries", [])
    except Exception:
        pass
    fails = [a for a in audit if isinstance(a, dict)
             and str(a.get("status", a.get("result", ""))).upper() in ("FAIL", "FAILED", "ERROR")]
    check("repeated_scan_failures", len(fails) >= 3,
          f"{len(fails)} failed scan entries in audit log", "ERROR")

    # duplicate trades (same symbol+action+timestamp)
    trades = list(get_trades())
    seen = defaultdict(int)
    for t in trades:
        seen[(t.get("symbol"), t.get("action"), t.get("timestamp"))] += 1
    dups = [k for k, v in seen.items() if v > 1]
    check("duplicate_trades", bool(dups), f"{len(dups)} duplicated trade record(s)", "ERROR")

    # duplicate alerts
    alerts = []
    try:
        raw = json.load(open(os.path.join(BASE_DIR, "phase9_alerts.json")))
        alerts = raw if isinstance(raw, list) else raw.get("alerts", [])
    except Exception:
        pass
    aseen = defaultdict(int)
    for a in alerts:
        if isinstance(a, dict):
            aseen[(a.get("type"), a.get("symbol"), a.get("scan_id"))] += 1
    adups = [k for k, v in aseen.items() if v > 1]
    check("duplicate_alerts", bool(adups), f"{len(adups)} duplicated alert group(s)")

    # missing prices & stale data from canonical scan
    scan = {}
    try:
        scan = json.load(open(os.path.join(BASE_DIR, "phase7_scan_cache.json")))
    except Exception:
        pass
    recs = scan.get("recommendations", [])
    missing_price = [r.get("symbol") for r in recs
                     if not r.get("entry_price") and not r.get("error")]
    check("missing_prices", bool(missing_price),
          f"{len(missing_price)} symbol(s) without price: {missing_price[:5]}")
    stale = False
    stale_detail = "scan age unknown"
    try:
        from phase15_scan_context import build_scan_context  # type: ignore
        ctx = build_scan_context()
        stale = bool(ctx.get("stale"))
        age_s = ctx.get("scan_age_seconds")
        stale_detail = f"scan age {round(age_s/60) if age_s is not None else '?'} min (limit 90)"
    except Exception:
        ts = scan.get("snapshot_ts")
        if ts:
            try:
                age = (datetime.now(timezone.utc)
                       - datetime.fromisoformat(str(ts).replace("Z", "+00:00"))).total_seconds() / 60
                stale = age > 90
                stale_detail = f"scan age {age:.0f} min"
            except Exception:
                pass
    check("stale_data", stale, stale_detail)

    # missing recommendations
    check("missing_recommendations", len(recs) == 0,
          "canonical scan has no recommendations", "ERROR")

    # broken charts: honest — cannot be detected server-side
    verdict = ("FAIL" if any(i["severity"] == "ERROR" for i in issues)
               else "WARN" if issues else "PASS")
    return _json_safe({
        "success": True, "generated_at": _now(), "label": LABEL,
        "checks_performed": checks, "issues": issues, "verdict": verdict,
        "not_checkable": ["broken_charts (client-side rendering — cannot be verified server-side)"],
    })


# ── combined runner ──────────────────────────────────────────────────────────

def run_all() -> dict:
    """All 14 validation sections in one call (used by phase16_all CLI and the review package)."""
    return {
        "success": True,
        "overview": validation_overview(),
        "scorecard": strategy_scorecard(),
        "confidence": confidence_validation(),
        "regimes": regime_validation(),
        "sectors": sector_validation(),
        "ai": ai_decision_validation(),
        "trades": trade_review(),
        "weekly": {"success": True, **weekly_report()},
        "monthly": {"success": True, **monthly_report()},
        "recommendations": improvement_recommendations(),
        "failures": failure_analysis(),
        "successes": success_analysis(),
        "timeline": validation_timeline(),
        "bugs": bug_detection(),
    }
