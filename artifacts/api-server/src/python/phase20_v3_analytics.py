"""
phase20_v3_analytics.py — V3 AI Risk Intelligence & Optimization Center.

Advisory-only. Read-only. Paper / Research only.
No threshold changes. No live execution.

Sections:
  1.  False Rejection Analysis
  2.  Risk Gate Accuracy
  3.  Opportunity Leakage
  4.  AI Threshold Optimizer
  5.  Market Regime Optimization
  6.  Strategy Effectiveness
  7.  Trade Outcome Predictor
  8.  Learning Feedback Loop
  9.  Threshold Impact Report
  10. AI Coach
  11. Weekly Optimization Report
  12. Monthly Optimization Report
  13. AI Confidence Calibration
  14. Decision Sandbox (data payload only — simulator is frontend)
  15. Optimization Dashboard
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import phase20_store as store

# ── Constants ─────────────────────────────────────────────────────────────────
CACHE_KEY          = "v3_analytics_cache"
TRACKER_KEY        = "rejection_tracker"
CACHE_TTL_S        = 1800   # 30 min
MAX_TRACKER        = 300    # max rejection_tracker entries
FALSE_REJ_GAIN_PCT = 5.0    # price rose ≥5% after rejection → false rejection
CORRECT_REJ_DROP   = 3.0    # price fell ≥3% after rejection → correct rejection
MAX_OUTCOME_FETCH  = 12     # max entries to price-check per analytics run

_GATE_LABEL: Dict[str, str] = {
    "min_confidence":           "Minimum Confidence",
    "min_opportunity_score":    "Minimum Opportunity Score",
    "min_risk_reward":          "Minimum Risk / Reward",
    "min_trade_quality":        "Minimum Trade Quality",
    "sector_cap":               "Sector Exposure Cap",
    "per_stock_cap":            "Per-Stock Exposure Cap",
    "portfolio_deployed_cap":   "Portfolio Deployed Cap",
    "daily_loss_limit":         "Daily Loss Limit",
    "daily_trade_limit":        "Daily Trade Limit",
    "no_open_duplicate":        "No Duplicate Open Trade",
    "cooldown":                 "Symbol Cooldown",
    "quote_available":          "Quote Available",
    "strategy_regime_eligible": "Strategy / Regime",
    "recommendation_buy":       "BUY Recommendation",
    "valid_stop_loss":          "Valid Stop-Loss",
    "position_size":            "Position Sizing",
    "sufficient_cash":          "Sufficient Cash",
    "scan_fresh":               "Scan Freshness",
    "snapshot_consistency":     "Snapshot Consistency",
    "provider_zerodha":         "Data Provider",
    "no_fallback_data":         "No Fallback/Mock Data",
    "market_open":              "Market Open",
    "entry_circuit_breaker":    "Circuit Breaker",
}

_CONFIGURABLE_GATES = [
    "min_confidence", "min_opportunity_score", "min_risk_reward",
    "min_trade_quality", "sector_cap", "per_stock_cap",
]

_REGIME_SUGGESTIONS: Dict[str, Dict[str, Any]] = {
    "Bull Market":      {"min_confidence": 62, "min_risk_reward": 1.8, "min_trade_quality": 52, "sector_cap": 45, "per_stock_cap": 25, "rationale": "Bullish conditions support higher approval rates with relaxed quality thresholds."},
    "Bear Market":      {"min_confidence": 78, "min_risk_reward": 2.8, "min_trade_quality": 72, "sector_cap": 28, "per_stock_cap": 14, "rationale": "Bear markets demand tighter filters to avoid catching falling knives."},
    "Sideways":         {"min_confidence": 70, "min_risk_reward": 2.2, "min_trade_quality": 65, "sector_cap": 35, "per_stock_cap": 18, "rationale": "Range-bound markets require disciplined R:R to overcome transaction costs."},
    "High Volatility":  {"min_confidence": 76, "min_risk_reward": 2.6, "min_trade_quality": 70, "sector_cap": 30, "per_stock_cap": 15, "rationale": "High volatility demands wider stops, which raises required R:R for the same risk budget."},
    "Low Volatility":   {"min_confidence": 60, "min_risk_reward": 1.7, "min_trade_quality": 50, "sector_cap": 50, "per_stock_cap": 28, "rationale": "Low-volatility environments historically support tighter stops and higher approval rates."},
}

_STRATEGY_LIST = [
    "Breakout", "Momentum", "VWAP", "ORB", "Gap", "Mean Reversion", "MACD Cross", "Trend Rider",
]

# ── Utilities ─────────────────────────────────────────────────────────────────

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


def _days_ago(dt: Optional[datetime], now: datetime) -> int:
    if not dt:
        return 9999
    return max(0, (now - dt).days)


def _pct(a: float, b: float, default: float = 0.0) -> float:
    return round(a / b * 100, 1) if b else default


# ── Rejection Tracker ─────────────────────────────────────────────────────────

def record_rejections(evaluation: Dict[str, Any]) -> None:
    """Append rejected candidates from an evaluation to the rejection_tracker KV.
    Called automatically from evaluate_entries() after history is saved."""
    candidates: List[Dict[str, Any]] = evaluation.get("candidates") or []
    rejected = [c for c in candidates if not c.get("eligible")]
    if not rejected:
        return
    try:
        tracker: List[Dict[str, Any]] = store.kv_get(TRACKER_KEY) or []
        scan_id = evaluation.get("scan_id")
        existing = {(e.get("symbol"), e.get("scan_id")) for e in tracker}
        for c in rejected:
            if (c.get("symbol"), scan_id) in existing:
                continue
            sz = c.get("sizing") or {}
            tracker.append({
                "symbol":               c.get("symbol", ""),
                "rejected_at":          evaluation.get("evaluated_at", _now().isoformat()),
                "scan_id":              scan_id,
                "confidence":           float(c.get("confidence", 0)),
                "opportunity_score":    float(c.get("opportunity_score", 0)),
                "trade_quality_score":  float(c.get("trade_quality_score", 0)),
                "rr_ratio":             float(sz.get("rr_ratio", 0)),
                "price_at_rejection":   float(sz.get("entry_price", 0)),
                "target_price":         float(sz.get("target_price", 0)),
                "stop_loss":            float(sz.get("stop_loss", 0)),
                "risk_amount":          float(sz.get("risk_amount", 0)),
                "position_value":       float(sz.get("position_value", 0)),
                "sector":               c.get("sector", ""),
                "strategy":             c.get("strategy_name") or c.get("strategy_id") or "",
                "regime":               c.get("regime", ""),
                "failed_gates":         [g for g in (c.get("failed_gates") or [])],
                # outcome fields — populated lazily
                "current_price":  None,
                "highest_price":  None,
                "lowest_price":   None,
                "max_gain_pct":   None,
                "max_loss_pct":   None,
                "classification": "still_monitoring",
                "days_monitored": 0,
                "last_checked":   None,
            })
        store.kv_set(TRACKER_KEY, tracker[-MAX_TRACKER:])
    except Exception:
        pass


def _fetch_price_outcomes(symbol: str, start_date: str) -> Dict[str, Optional[float]]:
    """Fetch current, highest, lowest prices since start_date from yfinance."""
    try:
        import yfinance as yf
        from datetime import date as _date
        end = _date.today().isoformat()
        if start_date >= end:
            return {}
        ticker = yf.Ticker(f"{symbol}.NS")
        hist = ticker.history(start=start_date, end=end, auto_adjust=True)
        if hist.empty:
            return {}
        return {
            "current": round(float(hist["Close"].iloc[-1]), 2),
            "high":    round(float(hist["High"].max()), 2),
            "low":     round(float(hist["Low"].min()),  2),
        }
    except Exception:
        return {}


def _classify_outcome(price0: float, high: Optional[float], low: Optional[float],
                       current: Optional[float], days: int) -> str:
    if days < 1 or current is None or price0 <= 0:
        return "still_monitoring"
    max_gain = ((high - price0) / price0 * 100) if high else 0.0
    max_drop = ((price0 - low) / price0 * 100)   if low  else 0.0
    if max_gain >= FALSE_REJ_GAIN_PCT:
        return "false_rejection"
    if max_drop >= CORRECT_REJ_DROP and max_gain < 2.0:
        return "correct_rejection"
    if days >= 5:
        curr_chg = (current - price0) / price0 * 100
        if curr_chg >= 3.0:
            return "false_rejection"
        if curr_chg <= -3.0:
            return "correct_rejection"
    return "still_monitoring"


def _update_outcomes(tracker: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Fetch outcome prices for unresolved entries. Limits fetches per call."""
    now   = _now()
    fetch_budget = MAX_OUTCOME_FETCH
    updated = []
    for entry in tracker:
        if fetch_budget <= 0:
            updated.append(entry)
            continue
        rejected_dt = _parse_dt(entry.get("rejected_at"))
        if not rejected_dt:
            updated.append(entry)
            continue
        days = (now - rejected_dt).days
        last_checked = _parse_dt(entry.get("last_checked"))
        # Skip if checked <2 h ago or already finalised past 30 days
        if last_checked and (now - last_checked).total_seconds() < 7200:
            updated.append(entry)
            continue
        if days >= 30 and entry.get("classification") in ("correct_rejection", "false_rejection"):
            updated.append(entry)
            continue
        prices = _fetch_price_outcomes(entry["symbol"], entry["rejected_at"][:10])
        if prices:
            p0 = entry.get("price_at_rejection") or 0.0
            h, l, c = prices.get("high"), prices.get("low"), prices.get("current")
            mxg = round((h - p0) / p0 * 100, 2) if h and p0 else None
            mxl = round((p0 - l) / p0 * 100, 2) if l and p0 else None
            entry = {**entry,
                "current_price":  c,
                "highest_price":  h,
                "lowest_price":   l,
                "max_gain_pct":   mxg,
                "max_loss_pct":   mxl,
                "classification": _classify_outcome(p0, h, l, c, days),
                "days_monitored": days,
                "last_checked":   now.isoformat(),
            }
            fetch_budget -= 1
        updated.append(entry)
    return updated


# ── Data Loaders ──────────────────────────────────────────────────────────────

def _load_paper_trades() -> List[Dict[str, Any]]:
    try:
        import portfolio_store as ps
        conn = ps._get_conn()
        with conn.cursor() as cur:
            cur.execute("""
                SELECT symbol, action, quantity, price, total, trade_ts, metadata
                FROM paper_trades ORDER BY trade_ts DESC LIMIT 500
            """)
            rows = cur.fetchall()
        result = []
        for r in rows:
            meta = r[6] if isinstance(r[6], dict) else {}
            result.append({
                "symbol": r[0], "action": r[1], "quantity": r[2],
                "price": float(r[3]), "total": float(r[4]),
                "trade_ts": r[5].isoformat() if r[5] else None, "metadata": meta,
            })
        return result
    except Exception:
        return []


# ── Section computations ──────────────────────────────────────────────────────

def _s1_false_rejections(tracker: List[Dict[str, Any]], now: datetime) -> Dict[str, Any]:
    """Section 1: False Rejection Analysis."""
    periods = [1, 3, 5, 10, 30]
    period_data: Dict[str, List[Dict[str, Any]]] = {str(p): [] for p in periods}
    summary = {"false": 0, "correct": 0, "monitoring": 0, "total": len(tracker)}

    for e in tracker:
        days = _days_ago(_parse_dt(e.get("rejected_at")), now)
        cls  = e.get("classification", "still_monitoring")
        if cls == "false_rejection":   summary["false"]      += 1
        elif cls == "correct_rejection": summary["correct"]   += 1
        else:                            summary["monitoring"] += 1
        for p in periods:
            if days <= p:
                period_data[str(p)].append({
                    "symbol":          e.get("symbol"),
                    "rejected_at":     e.get("rejected_at", "")[:16],
                    "failed_gates":    e.get("failed_gates") or [],
                    "confidence":      round(e.get("confidence", 0), 1),
                    "rr_ratio":        round(e.get("rr_ratio", 0), 2),
                    "price_at_rejection": e.get("price_at_rejection"),
                    "highest_price":   e.get("highest_price"),
                    "lowest_price":    e.get("lowest_price"),
                    "current_price":   e.get("current_price"),
                    "max_gain_pct":    e.get("max_gain_pct"),
                    "max_loss_pct":    e.get("max_loss_pct"),
                    "classification":  cls,
                    "days_monitored":  e.get("days_monitored", 0),
                    "strategy":        e.get("strategy", ""),
                    "sector":          e.get("sector", ""),
                    "regime":          e.get("regime", ""),
                })
    return {"summary": summary, "by_period": period_data}


def _s2_gate_accuracy(tracker: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Section 2: Risk Gate Accuracy — how accurate each gate is."""
    gate_stats: Dict[str, Dict[str, int]] = {}
    for e in tracker:
        cls = e.get("classification", "still_monitoring")
        if cls == "still_monitoring":
            continue  # not yet resolved
        for g in (e.get("failed_gates") or []):
            if g not in gate_stats:
                gate_stats[g] = {"blocked": 0, "correct": 0, "incorrect": 0}
            gate_stats[g]["blocked"] += 1
            if cls == "correct_rejection":
                gate_stats[g]["correct"]   += 1
            else:
                gate_stats[g]["incorrect"] += 1

    rows = []
    for gid, s in sorted(gate_stats.items(), key=lambda x: -x[1]["blocked"]):
        total = s["blocked"]
        acc   = _pct(s["correct"], total)
        rows.append({
            "gate_id":              gid,
            "label":                _GATE_LABEL.get(gid, gid),
            "trades_blocked":       total,
            "correct_decisions":    s["correct"],
            "incorrect_decisions":  s["incorrect"],
            "trades_became_winners":s["incorrect"],  # false rejection = trade would have won
            "trades_became_losers": s["correct"],    # correct rejection = blocked a loser
            "accuracy_pct":         acc,
        })
    return rows


def _s3_opportunity_leakage(tracker: List[Dict[str, Any]], history: List[Dict[str, Any]], now: datetime) -> Dict[str, Any]:
    """Section 3: Opportunity Leakage."""
    def _filter(days_max: int) -> List[Dict[str, Any]]:
        return [e for e in tracker if _days_ago(_parse_dt(e.get("rejected_at")), now) <= days_max]

    today_rej  = _filter(1)
    week_rej   = _filter(7)
    month_rej  = _filter(30)

    def _stats(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
        resolved = [e for e in entries if e.get("classification") != "still_monitoring"]
        false_   = [e for e in resolved if e.get("classification") == "false_rejection"]
        correct_ = [e for e in resolved if e.get("classification") == "correct_rejection"]
        profit_missed = sum((e.get("max_gain_pct", 0) or 0) * (e.get("position_value", 0) or 0) / 100 for e in false_)
        loss_avoided  = sum((e.get("max_loss_pct", 0) or 0) * (e.get("position_value", 0) or 0) / 100 for e in correct_)
        # Estimated alpha lost = profit_missed - loss_avoided (net missed edge)
        alpha_lost    = max(0.0, profit_missed - loss_avoided)
        return {
            "total_rejected":        len(entries),
            "resolved":              len(resolved),
            "potential_winners_missed": len(false_),
            "correct_rejections":    len(correct_),
            "potential_profit_missed_inr": round(profit_missed, 0),
            "potential_loss_avoided_inr":  round(loss_avoided, 0),
            "estimated_alpha_lost_inr":    round(alpha_lost, 0),
            "false_rejection_pct":   _pct(len(false_), len(resolved)) if resolved else None,
        }

    # Historical daily trend from evaluation_history
    daily_trend = []
    for h in history[-30:]:
        daily_trend.append({
            "date":          h.get("date") or h.get("evaluated_at", "")[:10],
            "total_rejected": h.get("blocked_count", 0),
            "total_evaluated":h.get("total_count", 0),
        })

    return {
        "today":          _stats(today_rej),
        "this_week":      _stats(week_rej),
        "this_month":     _stats(month_rej),
        "daily_trend":    daily_trend,
    }


def _s4_threshold_optimizer(tracker: List[Dict[str, Any]], current_eval: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Section 4: AI Threshold Optimizer — suggestions per configurable gate."""
    # Compute false rejection pct per gate
    gate_false: Dict[str, int] = {}
    gate_correct: Dict[str, int] = {}
    gate_actuals: Dict[str, List[float]] = {}  # actual values for false rejections

    resolved = [e for e in tracker if e.get("classification") != "still_monitoring"]
    for e in resolved:
        for g in (e.get("failed_gates") or []):
            if g not in _CONFIGURABLE_GATES:
                continue
            if g not in gate_false:
                gate_false[g]   = 0
                gate_correct[g] = 0
                gate_actuals[g] = []
            if e.get("classification") == "false_rejection":
                gate_false[g] += 1
                # Approximate actual value from gate name
                if g == "min_confidence":
                    gate_actuals[g].append(e.get("confidence", 0))
                elif g == "min_opportunity_score":
                    gate_actuals[g].append(e.get("opportunity_score", 0))
                elif g == "min_risk_reward":
                    gate_actuals[g].append(e.get("rr_ratio", 0))
                elif g == "min_trade_quality":
                    gate_actuals[g].append(e.get("trade_quality_score", 0))
            else:
                gate_correct[g] += 1

    # Current thresholds from latest evaluation
    current_thresholds: Dict[str, float] = {}
    if current_eval:
        for c in (current_eval.get("candidates") or []):
            for g_obj in (c.get("gates") or []):
                gid   = g_obj.get("gate", "")
                reason= g_obj.get("reason", "")
                if gid in _CONFIGURABLE_GATES and gid not in current_thresholds:
                    import re
                    m = re.search(r"minimum\s+([\d.]+)", reason, re.I)
                    if m:
                        current_thresholds[gid] = float(m.group(1))
                    m2 = re.search(r"cap\s+([\d.]+)%", reason, re.I)
                    if m2:
                        current_thresholds[gid] = float(m2.group(1))

    defaults = {
        "min_confidence": 60.0, "min_opportunity_score": 60.0,
        "min_risk_reward": 2.0, "min_trade_quality": 50.0,
        "sector_cap": 40.0, "per_stock_cap": 20.0,
    }

    rows = []
    for gid in _CONFIGURABLE_GATES:
        current = current_thresholds.get(gid, defaults[gid])
        false_n = gate_false.get(gid, 0)
        corr_n  = gate_correct.get(gid, 0)
        total   = false_n + corr_n
        actuals = gate_actuals.get(gid, [])

        # Suggestion logic
        false_pct = _pct(false_n, total) if total else 0.0
        suggested = current
        direction = "keep"
        reason    = "Insufficient data — continuing to monitor."

        if total >= 5:
            if false_pct >= 50:
                # Relax: use 10th percentile of actual values in false rejections
                if actuals:
                    actuals_sorted = sorted(actuals)
                    p10 = actuals_sorted[max(0, int(len(actuals_sorted) * 0.10))]
                    suggested = round(p10 * 0.95, 1)  # slightly below 10th percentile
                else:
                    suggested = round(current * 0.90, 1)
                direction = "relax"
                reason = f"This gate caused false rejections {false_pct:.0f}% of the time ({false_n}/{total} resolved). Relaxing may capture missed winners."
            elif false_pct >= 30:
                suggested = round(current * 0.95, 1)
                direction = "slightly_relax"
                reason = f"This gate has a {false_pct:.0f}% false rejection rate ({false_n}/{total}). A slight relaxation may improve opportunity capture."
            elif false_pct <= 10 and corr_n >= 3:
                suggested = round(current * 1.05, 1)
                direction = "tighten"
                reason = f"This gate correctly blocked {corr_n}/{total} trades ({_pct(corr_n, total):.0f}%). Tightening may further protect capital."
            else:
                reason = f"Gate accuracy: {_pct(corr_n, total):.0f}% correct. Current threshold appears well-calibrated."

        # Expected impact estimates
        current_candidates = len(current_eval.get("candidates") or []) if current_eval else 0
        approved_today = len([c for c in (current_eval.get("candidates") or []) if c.get("eligible")]) if current_eval else 0

        rows.append({
            "gate_id":               gid,
            "label":                 _GATE_LABEL.get(gid, gid),
            "current_value":         current,
            "suggested_value":       suggested,
            "direction":             direction,
            "false_rejection_pct":   round(false_pct, 1),
            "correct_rejection_pct": round(_pct(corr_n, total), 1) if total else None,
            "sample_size":           total,
            "reason":                reason,
            "expected_approved_trades": approved_today,  # advisory estimate
            "expected_win_rate":     round(max(0, 50 - false_pct * 0.3), 1) if total else None,
        })
    return rows


def _s5_regime_optimization() -> List[Dict[str, Any]]:
    """Section 5: Market Regime Optimization — suggested thresholds per regime."""
    rows = []
    for regime, suggestions in _REGIME_SUGGESTIONS.items():
        rows.append({
            "regime":                regime,
            "min_confidence":        suggestions["min_confidence"],
            "min_risk_reward":       suggestions["min_risk_reward"],
            "min_trade_quality":     suggestions["min_trade_quality"],
            "sector_cap":            suggestions["sector_cap"],
            "per_stock_cap":         suggestions["per_stock_cap"],
            "rationale":             suggestions["rationale"],
        })
    return rows


def _s6_strategy_effectiveness(tracker: List[Dict[str, Any]], paper_trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Section 6: Strategy Effectiveness."""
    # Build strategy stats from tracker
    strat_stats: Dict[str, Dict[str, Any]] = {}
    for e in tracker:
        strat = e.get("strategy") or "Unknown"
        if strat not in strat_stats:
            strat_stats[strat] = {
                "rejections": 0, "false_rejections": 0, "correct_rejections": 0,
                "confidences": [], "rrs": [],
            }
        strat_stats[strat]["rejections"] += 1
        cls = e.get("classification", "still_monitoring")
        if cls == "false_rejection":   strat_stats[strat]["false_rejections"]   += 1
        elif cls == "correct_rejection":strat_stats[strat]["correct_rejections"] += 1
        strat_stats[strat]["confidences"].append(e.get("confidence", 0))
        strat_stats[strat]["rrs"].append(e.get("rr_ratio", 0))

    # Build strategy stats from paper trades (completed trades)
    trade_strat: Dict[str, List[Dict[str, Any]]] = {}
    for t in paper_trades:
        meta  = t.get("metadata") or {}
        strat = meta.get("strategy_name") or meta.get("strategy_id") or "Unknown"
        if strat not in trade_strat:
            trade_strat[strat] = []
        trade_strat[strat].append(t)

    all_strats = set(list(strat_stats.keys()) + list(trade_strat.keys()))
    rows = []
    for strat in sorted(all_strats):
        ss   = strat_stats.get(strat, {})
        ts   = trade_strat.get(strat, [])
        rej  = ss.get("rejections", 0)
        false_rej = ss.get("false_rejections", 0)
        resolved = ss.get("false_rejections", 0) + ss.get("correct_rejections", 0)
        confs = ss.get("confidences", [])
        rrs   = ss.get("rrs", [])
        rows.append({
            "strategy":              strat,
            "total_rejections":      rej,
            "false_rejection_pct":   round(false_rej / resolved * 100, 1) if resolved else None,
            "avg_confidence":        round(sum(confs) / len(confs), 1) if confs else None,
            "avg_rr":                round(sum(rrs) / len(rrs), 2)   if rrs   else None,
            "paper_trades_count":    len(ts),
            "data_source":           "rejection_tracker + paper_trades",
        })
    return rows


def _s7_outcome_predictor(candidates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Section 7: Trade Outcome Predictor — probability estimates per candidate."""
    rows = []
    for c in candidates:
        conf  = float(c.get("confidence", 0))
        opp   = float(c.get("opportunity_score", 0))
        qual  = float(c.get("trade_quality_score", 0))
        rr    = float((c.get("sizing") or {}).get("rr_ratio", 0))
        sz    = c.get("sizing") or {}
        entry = float(sz.get("entry_price", 0))
        tgt   = float(sz.get("target_price", 0))
        stop  = float(sz.get("stop_loss", 0))

        # Weighted probability of success (advisory heuristic)
        raw_prob = (conf * 0.35 + opp * 0.30 + qual * 0.20 + min(rr / 3.0, 1.0) * 100 * 0.15) / 100
        prob_success = round(min(0.90, max(0.05, raw_prob)), 3)
        prob_failure = round(1.0 - prob_success, 3)

        expected_return_pct = round((tgt - entry) / entry * 100, 2) if entry else 0.0
        expected_drawdown   = round((entry - stop) / entry * 100, 2) if entry else 0.0
        pred_conf_label = "High" if prob_success >= 0.65 else "Medium" if prob_success >= 0.45 else "Low"

        rows.append({
            "symbol":               c.get("symbol"),
            "eligible":             c.get("eligible"),
            "probability_success":  prob_success,
            "probability_failure":  prob_failure,
            "expected_return_pct":  expected_return_pct,
            "expected_drawdown_pct":expected_drawdown,
            "expected_holding_days":c.get("expected_holding_days") or 3,
            "prediction_confidence":pred_conf_label,
            "confidence_score":     conf,
            "opportunity_score":    opp,
            "trade_quality_score":  qual,
            "rr_ratio":             rr,
        })
    return rows


def _s8_learning_loop() -> Dict[str, Any]:
    """Section 8: Learning Feedback Loop — read learning agent state."""
    try:
        learning_state = store.kv_get("learning_agent_state") or {}
        return {
            "has_data": bool(learning_state),
            "patterns_discovered": learning_state.get("patterns_discovered", 0),
            "knowledge_updates":   learning_state.get("knowledge_updates", 0),
            "last_learning_at":    learning_state.get("last_run"),
            "threshold_impacts":   learning_state.get("threshold_impacts") or [],
            "future_recommendations": learning_state.get("recommendations") or [],
            "stages": [
                {"id": "completed_trade",    "label": "Completed Trade",        "status": "active"},
                {"id": "learning_generated", "label": "Learning Generated",     "status": "active" if learning_state.get("patterns_discovered", 0) > 0 else "pending"},
                {"id": "knowledge_updated",  "label": "Knowledge Updated",      "status": "active" if learning_state.get("knowledge_updates", 0) > 0 else "pending"},
                {"id": "threshold_impact",   "label": "Threshold Impact",       "status": "active" if learning_state.get("threshold_impacts") else "pending"},
                {"id": "future_reco",        "label": "Future Recommendation",  "status": "active" if learning_state.get("recommendations") else "pending"},
            ],
        }
    except Exception:
        return {
            "has_data": False,
            "stages": [
                {"id": "completed_trade",    "label": "Completed Trade",       "status": "pending"},
                {"id": "learning_generated", "label": "Learning Generated",    "status": "pending"},
                {"id": "knowledge_updated",  "label": "Knowledge Updated",     "status": "pending"},
                {"id": "threshold_impact",   "label": "Threshold Impact",      "status": "pending"},
                {"id": "future_reco",        "label": "Future Recommendation", "status": "pending"},
            ],
        }


def _s9_threshold_impact(tracker: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Section 9: Threshold Impact Report — per gate."""
    gate_data: Dict[str, Dict[str, Any]] = {}
    resolved = [e for e in tracker if e.get("classification") != "still_monitoring"]
    for e in resolved:
        for g in (e.get("failed_gates") or []):
            if g not in gate_data:
                gate_data[g] = {"rejected": 0, "winners": 0, "losers": 0, "profit_missed": 0.0, "loss_avoided": 0.0}
            gate_data[g]["rejected"] += 1
            pv = e.get("position_value") or 0
            if e.get("classification") == "false_rejection":
                gate_data[g]["winners"]       += 1
                gate_data[g]["profit_missed"] += (e.get("max_gain_pct", 0) or 0) * pv / 100
            else:
                gate_data[g]["losers"]        += 1
                gate_data[g]["loss_avoided"]  += (e.get("max_loss_pct", 0) or 0) * pv / 100

    rows = []
    for gid, d in sorted(gate_data.items(), key=lambda x: -x[1]["rejected"]):
        rej    = d["rejected"]
        win    = d["winners"]
        lose   = d["losers"]
        net    = d["loss_avoided"] - d["profit_missed"]
        # Recommendation
        if rej == 0:
            recommendation = "keep"
        elif _pct(win, rej) >= 60:
            recommendation = "relax"
        elif _pct(win, rej) >= 35:
            recommendation = "review"
        elif net > 0:
            recommendation = "keep"
        else:
            recommendation = "tighten"

        rows.append({
            "gate_id":             gid,
            "label":               _GATE_LABEL.get(gid, gid),
            "rejected_trades":     rej,
            "would_have_been_winners": win,
            "would_have_been_losers":  lose,
            "estimated_profit_missed_inr": round(d["profit_missed"], 0),
            "estimated_loss_avoided_inr":  round(d["loss_avoided"], 0),
            "net_impact_inr":              round(net, 0),
            "recommendation":              recommendation,
        })
    return rows


def _s10_ai_coach(tracker: List[Dict[str, Any]], gate_accuracy: List[Dict[str, Any]],
                   leakage: Dict[str, Any], threshold_opt: List[Dict[str, Any]]) -> List[str]:
    """Section 10: AI Coach — plain-English advisory sentences."""
    advisories: List[str] = []
    resolved = [e for e in tracker if e.get("classification") != "still_monitoring"]

    # False rejection rate overall
    false_n = sum(1 for e in resolved if e.get("classification") == "false_rejection")
    if resolved:
        fr_pct = _pct(false_n, len(resolved))
        if fr_pct >= 40:
            advisories.append(
                f"The overall false rejection rate is {fr_pct:.0f}% ({false_n}/{len(resolved)} resolved). "
                "Risk gates are blocking trades that would have been profitable. Consider reviewing configurable thresholds."
            )
        elif fr_pct >= 20:
            advisories.append(
                f"The false rejection rate is {fr_pct:.0f}%. Some opportunity leakage is occurring, "
                "but the current gates are still blocking more losers than winners."
            )
        else:
            advisories.append(
                f"The false rejection rate is {fr_pct:.0f}%, indicating the gates are well-calibrated for the current market."
            )

    # Top gate accuracy
    for g in gate_accuracy[:3]:
        acc = g.get("accuracy_pct", 0)
        if acc >= 75:
            advisories.append(
                f"The {g['label']} gate is highly effective — {acc:.0f}% of its rejections were correct decisions."
            )
        elif acc <= 35 and g.get("trades_blocked", 0) >= 3:
            advisories.append(
                f"The {g['label']} gate has a {acc:.0f}% accuracy rate. "
                "It may be blocking more winners than losers — review suggested."
            )

    # Threshold suggestions
    for t in threshold_opt:
        if t.get("direction") in ("relax", "slightly_relax") and t.get("sample_size", 0) >= 5:
            advisories.append(
                f"The {t['label']} threshold ({t['current_value']}) appears conservative — "
                f"a suggested value of {t['suggested_value']} may reduce false rejections without increasing loss exposure."
            )
            break  # one suggestion is enough

    # Opportunity leakage
    month = leakage.get("this_month", {})
    alpha = month.get("estimated_alpha_lost_inr", 0)
    if alpha > 10_000:
        advisories.append(
            f"Estimated alpha lost this month: ₹{alpha:,.0f}. "
            "This represents the net opportunity cost of false rejections after accounting for avoided losses."
        )

    # General advisory
    if not advisories:
        advisories.append(
            "Insufficient resolved trades to generate targeted advisories. "
            "Analytics will improve after more rejection outcomes are resolved (typically 3–10 trading days)."
        )

    # Prefix
    advisories = ["[Advisory only — no automatic changes made] " + a if i == 0 else a
                  for i, a in enumerate(advisories)]
    return advisories


def _s11_weekly_report(tracker: List[Dict[str, Any]], history: List[Dict[str, Any]], now: datetime) -> Dict[str, Any]:
    """Section 11: Weekly Optimization Report."""
    week_ago = now - timedelta(days=7)
    week_tracker = [e for e in tracker if (_parse_dt(e.get("rejected_at")) or now) >= week_ago]
    week_history = [h for h in history if (_parse_dt(h.get("evaluated_at")) or now) >= week_ago]

    # Gate frequency this week
    gate_freq: Dict[str, int] = {}
    for e in week_tracker:
        for g in (e.get("failed_gates") or []):
            gate_freq[g] = gate_freq.get(g, 0) + 1
    most_restrictive = max(gate_freq, key=gate_freq.get) if gate_freq else None

    # Gate accuracy this week
    gate_acc_week = _s2_gate_accuracy(week_tracker)
    most_accurate  = max(gate_acc_week, key=lambda x: x["accuracy_pct"], default=None)

    # Strategy this week
    strat_freq: Dict[str, int] = {}
    for e in week_tracker:
        s = e.get("strategy") or "Unknown"
        strat_freq[s] = strat_freq.get(s, 0) + 1

    false_rej_week = [e for e in week_tracker if e.get("classification") == "false_rejection"]
    largest_missed = max(false_rej_week, key=lambda x: x.get("max_gain_pct", 0) or 0, default=None)

    correct_rej_week = [e for e in week_tracker if e.get("classification") == "correct_rejection"]
    largest_avoided = max(correct_rej_week, key=lambda x: x.get("max_loss_pct", 0) or 0, default=None)

    avg_blocked = (sum(h.get("blocked_count", 0) for h in week_history) / len(week_history)
                   if week_history else 0)

    return {
        "period":              "last_7_days",
        "total_rejected":      len(week_tracker),
        "false_rejections":    len(false_rej_week),
        "correct_rejections":  len(correct_rej_week),
        "avg_blocked_per_scan":round(avg_blocked, 1),
        "most_restrictive_gate": _GATE_LABEL.get(most_restrictive, most_restrictive) if most_restrictive else None,
        "most_accurate_gate":  most_accurate.get("label") if most_accurate else None,
        "largest_missed_opportunity": {
            "symbol":    largest_missed.get("symbol") if largest_missed else None,
            "gain_pct":  largest_missed.get("max_gain_pct") if largest_missed else None,
        },
        "largest_avoided_loss": {
            "symbol":    largest_avoided.get("symbol") if largest_avoided else None,
            "loss_pct":  largest_avoided.get("max_loss_pct") if largest_avoided else None,
        },
        "review_items": [
            _GATE_LABEL.get(g, g) for g in (list(gate_freq.keys())[:3])
        ],
        "generated_at": now.isoformat(),
    }


def _s12_monthly_report(tracker: List[Dict[str, Any]], history: List[Dict[str, Any]], now: datetime) -> Dict[str, Any]:
    """Section 12: Monthly Optimization Report."""
    month_ago    = now - timedelta(days=30)
    month_tracker= [e for e in tracker if (_parse_dt(e.get("rejected_at")) or now) >= month_ago]
    month_history= [h for h in history if (_parse_dt(h.get("evaluated_at")) or now) >= month_ago]

    # Gate trend (weekly buckets)
    gate_weekly: Dict[str, List[int]] = {}
    for week_offset in range(4):
        w_start = now - timedelta(days=(week_offset + 1) * 7)
        w_end   = now - timedelta(days=week_offset * 7)
        w_rej   = [e for e in month_tracker
                   if w_start <= (_parse_dt(e.get("rejected_at")) or now) < w_end]
        for e in w_rej:
            for g in (e.get("failed_gates") or []):
                if g not in gate_weekly:
                    gate_weekly[g] = [0, 0, 0, 0]
                gate_weekly[g][3 - week_offset] += 1

    gate_trends = [
        {"gate_id": gid, "label": _GATE_LABEL.get(gid, gid), "weekly_counts": counts}
        for gid, counts in sorted(gate_weekly.items(), key=lambda x: -sum(x[1]))[:8]
    ]

    # Strategy trend
    strat_monthly: Dict[str, int] = {}
    for e in month_tracker:
        s = e.get("strategy") or "Unknown"
        strat_monthly[s] = strat_monthly.get(s, 0) + 1

    # Regime distribution
    regime_dist: Dict[str, int] = {}
    for e in month_tracker:
        r = e.get("regime") or "Unknown"
        regime_dist[r] = regime_dist.get(r, 0) + 1

    # Pass rate trend (weekly)
    pass_rate_trend = []
    for week_offset in range(4):
        w_start = now - timedelta(days=(week_offset + 1) * 7)
        w_end   = now - timedelta(days=week_offset * 7)
        w_hist  = [h for h in month_history
                   if w_start <= (_parse_dt(h.get("evaluated_at")) or now) < w_end]
        total   = sum(h.get("total_count", 0)   for h in w_hist)
        blocked = sum(h.get("blocked_count", 0) for h in w_hist)
        pass_rate_trend.append({
            "week":        f"Week -{week_offset + 1}",
            "pass_rate":   round(_pct(total - blocked, total), 1) if total else None,
            "scans":       len(w_hist),
        })
    pass_rate_trend.reverse()

    return {
        "period":           "last_30_days",
        "total_rejected":   len(month_tracker),
        "gate_trends":      gate_trends,
        "strategy_trends":  [{"strategy": s, "rejections": n} for s, n in sorted(strat_monthly.items(), key=lambda x: -x[1])],
        "regime_distribution": [{"regime": r, "count": n} for r, n in sorted(regime_dist.items(), key=lambda x: -x[1])],
        "pass_rate_trend":  pass_rate_trend,
        "generated_at":     now.isoformat(),
    }


def _s13_confidence_calibration(tracker: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Section 13: AI Confidence Calibration."""
    # Group resolved entries by confidence bucket
    buckets: Dict[str, Dict[str, int]] = {}
    bucket_ranges = [(0, 50), (50, 60), (60, 70), (70, 80), (80, 90), (90, 100)]

    for low, high in bucket_ranges:
        label = f"{low}–{high}%"
        buckets[label] = {"predicted_confidence": (low + high) / 2, "total": 0, "false_rejections": 0}

    resolved = [e for e in tracker if e.get("classification") != "still_monitoring"]
    for e in resolved:
        conf = e.get("confidence", 0)
        for low, high in bucket_ranges:
            if low <= conf < high:
                label = f"{low}–{high}%"
                buckets[label]["total"] += 1
                if e.get("classification") == "false_rejection":
                    buckets[label]["false_rejections"] += 1
                break

    calibration_points = []
    overall_drift = 0.0
    calibration_error = 0.0
    n_buckets = 0

    for label, b in buckets.items():
        if b["total"] == 0:
            continue
        actual_success_rate = _pct(b["false_rejections"], b["total"])  # false rejection = would have succeeded
        pred = b["predicted_confidence"]
        drift = actual_success_rate - pred
        calibration_points.append({
            "bucket":                   label,
            "predicted_confidence_pct": pred,
            "actual_success_rate_pct":  round(actual_success_rate, 1),
            "confidence_drift":         round(drift, 1),
            "sample_size":              b["total"],
        })
        overall_drift      += drift
        calibration_error  += abs(drift)
        n_buckets          += 1

    avg_drift  = round(overall_drift / n_buckets, 1) if n_buckets else 0.0
    avg_error  = round(calibration_error / n_buckets, 1) if n_buckets else 0.0

    if abs(avg_drift) < 5:
        calibration_status = "well_calibrated"
        calibration_note   = "Confidence scores align closely with actual outcomes."
    elif avg_drift > 5:
        calibration_status = "overconservative"
        calibration_note   = "Confidence is systematically too low — the model is underconfident relative to actual trade outcomes."
    else:
        calibration_status = "overoptimistic"
        calibration_note   = "Confidence is systematically too high — the model may be overestimating signal quality."

    return {
        "calibration_points":  calibration_points,
        "average_drift":       avg_drift,
        "calibration_error":   avg_error,
        "calibration_status":  calibration_status,
        "calibration_note":    calibration_note,
        "sample_size":         len(resolved),
        "insufficient_data":   len(resolved) < 10,
    }


def _s15_optimization_dashboard(tracker: List[Dict[str, Any]], history: List[Dict[str, Any]],
                                  gate_acc: List[Dict[str, Any]], leakage: Dict[str, Any],
                                  threshold_opt: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Section 15: Optimization Dashboard top-line metrics."""
    resolved = [e for e in tracker if e.get("classification") != "still_monitoring"]
    false_n  = sum(1 for e in resolved if e.get("classification") == "false_rejection")
    correct_n= sum(1 for e in resolved if e.get("classification") == "correct_rejection")
    total_r  = len(resolved)

    risk_accuracy       = _pct(correct_n, total_r) if total_r else None
    false_rej_rate      = _pct(false_n,   total_r) if total_r else None
    correct_rej_rate    = _pct(correct_n, total_r) if total_r else None

    # Opportunity leakage score (lower is better: 0=no leakage, 100=all rejections were winners)
    opp_leakage = false_rej_rate

    # Threshold stability: how many configurable gates are "keep" direction
    stable_gates = sum(1 for t in threshold_opt if t.get("direction") == "keep")
    threshold_stability = _pct(stable_gates, len(threshold_opt)) if threshold_opt else None

    # Learning progress: 0–100 based on history depth and resolved outcomes
    history_days = len(set(h.get("date") or h.get("evaluated_at", "")[:10] for h in history))
    lp_raw = min(100, (history_days / 30) * 50 + (total_r / 50) * 50)
    learning_progress = round(lp_raw, 0)

    # Optimization score: composite
    if risk_accuracy is not None and threshold_stability is not None:
        opt_score = round(risk_accuracy * 0.35 + (100 - (opp_leakage or 0)) * 0.25
                          + threshold_stability * 0.20 + learning_progress * 0.20, 1)
    else:
        opt_score = None

    return {
        "overall_risk_accuracy":    risk_accuracy,
        "false_rejection_rate":     false_rej_rate,
        "correct_rejection_rate":   correct_rej_rate,
        "opportunity_leakage_pct":  opp_leakage,
        "threshold_stability_pct":  threshold_stability,
        "learning_progress_pct":    learning_progress,
        "optimization_score":       opt_score,
        "total_tracked":            len(tracker),
        "total_resolved":           total_r,
        "history_days":             history_days,
        "data_quality":             "live" if total_r >= 10 else "accumulating",
    }


# ── Main entry point ──────────────────────────────────────────────────────────

def get_v3_analytics() -> Dict[str, Any]:
    """
    Compute all 15 V3 sections. Uses cache (30 min TTL) to avoid repeated slow yfinance calls.
    """
    now = _now()

    # ── Cache hit check ───────────────────────────────────────────────────────
    cached = store.kv_get(CACHE_KEY)
    if cached and isinstance(cached, dict):
        cached_at = _parse_dt(cached.get("generated_at"))
        if cached_at and (now - cached_at).total_seconds() < CACHE_TTL_S:
            return cached

    # ── Load raw data ─────────────────────────────────────────────────────────
    tracker: List[Dict[str, Any]] = store.kv_get(TRACKER_KEY) or []
    history: List[Dict[str, Any]] = store.kv_get("evaluation_history") or []
    current_eval = store.kv_get("last_entry_evaluation") or {}
    paper_trades = _load_paper_trades()

    # ── Update price outcomes for pending entries ──────────────────────────────
    try:
        tracker = _update_outcomes(tracker)
        store.kv_set(TRACKER_KEY, tracker[-MAX_TRACKER:])
    except Exception:
        pass

    candidates: List[Dict[str, Any]] = current_eval.get("candidates") or []

    # ── Compute all sections ──────────────────────────────────────────────────
    try:
        s1  = _s1_false_rejections(tracker, now)
    except Exception:
        s1  = {"summary": {}, "by_period": {}}

    try:
        s2  = _s2_gate_accuracy(tracker)
    except Exception:
        s2  = []

    try:
        s3  = _s3_opportunity_leakage(tracker, history, now)
    except Exception:
        s3  = {}

    try:
        s4  = _s4_threshold_optimizer(tracker, current_eval)
    except Exception:
        s4  = []

    try:
        s5  = _s5_regime_optimization()
    except Exception:
        s5  = []

    try:
        s6  = _s6_strategy_effectiveness(tracker, paper_trades)
    except Exception:
        s6  = []

    try:
        s7  = _s7_outcome_predictor(candidates)
    except Exception:
        s7  = []

    try:
        s8  = _s8_learning_loop()
    except Exception:
        s8  = {"has_data": False, "stages": []}

    try:
        s9  = _s9_threshold_impact(tracker)
    except Exception:
        s9  = []

    try:
        s10 = _s10_ai_coach(tracker, s2, s3, s4)
    except Exception:
        s10 = ["Advisory data is still accumulating."]

    try:
        s11 = _s11_weekly_report(tracker, history, now)
    except Exception:
        s11 = {}

    try:
        s12 = _s12_monthly_report(tracker, history, now)
    except Exception:
        s12 = {}

    try:
        s13 = _s13_confidence_calibration(tracker)
    except Exception:
        s13 = {"insufficient_data": True}

    # S14 (Decision Sandbox) data payload: same threshold data used by frontend simulator
    s14 = {
        "current_thresholds": {t["gate_id"]: t["current_value"] for t in s4} if s4 else {},
        "suggested_thresholds": {t["gate_id"]: t["suggested_value"] for t in s4} if s4 else {},
        "historical_tracker_count": len(tracker),
        "resolved_count":           len([e for e in tracker if e.get("classification") != "still_monitoring"]),
    }

    try:
        s15 = _s15_optimization_dashboard(tracker, history, s2, s3, s4)
    except Exception:
        s15 = {"data_quality": "accumulating"}

    result = {
        "available":      True,
        "generated_at":   now.isoformat(),
        "cache_ttl_s":    CACHE_TTL_S,
        "tracker_count":  len(tracker),
        "history_entries":len(history),
        "s1_false_rejections":    s1,
        "s2_gate_accuracy":       s2,
        "s3_opportunity_leakage": s3,
        "s4_threshold_optimizer": s4,
        "s5_regime_optimization": s5,
        "s6_strategy_effectiveness": s6,
        "s7_outcome_predictor":   s7,
        "s8_learning_loop":       s8,
        "s9_threshold_impact":    s9,
        "s10_ai_coach":           s10,
        "s11_weekly_report":      s11,
        "s12_monthly_report":     s12,
        "s13_confidence_calibration": s13,
        "s14_sandbox_data":       s14,
        "s15_optimization_dashboard": s15,
        "label": "PAPER / RESEARCH ONLY",
    }

    try:
        store.kv_set(CACHE_KEY, result)
    except Exception:
        pass

    return result
