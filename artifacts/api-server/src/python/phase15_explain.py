"""
phase15_explain.py — Phase 15: AI Explainability

Replaces bare BUY/WATCH/IGNORE outputs with a structured, human-readable
explanation covering: trend strength, momentum, volume, sector strength,
market regime, risk, reward, risk/reward ratio, confidence, opportunity
score, strategy match, and the final decision — answering explicitly
"Why Buy?", "Why Watch?", or "Why Ignore?".

Uses ONLY cached platform data — never invents information.
PAPER TRADING / RESEARCH ONLY.
"""

from __future__ import annotations

from typing import Any, Dict, List

from phase15_scan_context import symbol_context, build_scan_context
from phase15_quality import score_symbol


def _factor(name: str, value: Any, assessment: str, favourable: bool) -> Dict[str, Any]:
    return {"factor": name, "value": value, "assessment": assessment,
            "favourable": favourable}


def explain_symbol(symbol: str) -> Dict[str, Any]:
    ctx = symbol_context(symbol)
    if not ctx.get("available"):
        return {"available": False, "reason": ctx.get("reason")}

    ind = ctx.get("indicators", {})
    adx = float(ind.get("adx") or 0)
    rsi = float(ind.get("rsi") or 0)
    vr = float(ind.get("volume_ratio") or 0)
    conf = float(ctx.get("confidence") or 0)
    opp = float(ctx.get("opportunity_score") or 0)
    rr = float(ctx.get("rr_ratio") or 0)
    action = str(ctx.get("final_action") or "IGNORE")
    effective = str(ctx.get("effective_action") or action)
    regime = ctx.get("market_regime") or "UNKNOWN"
    strat = ctx.get("strategy_name") or "—"
    strat_regime = ctx.get("regime") or "UNKNOWN"

    factors: List[Dict[str, Any]] = []

    # Trend strength (ADX + EMA positioning)
    trend_ok = adx >= 20 and bool(ind.get("above_ema20"))
    factors.append(_factor(
        "trend_strength", {"adx": adx, "above_ema20": ind.get("above_ema20"),
                           "above_ema50": ind.get("above_ema50")},
        f"ADX {adx:.1f} ({'strong' if adx >= 25 else 'developing' if adx >= 20 else 'weak'} trend); "
        f"price {'above' if ind.get('above_ema20') else 'below'} EMA20, "
        f"{'above' if ind.get('above_ema50') else 'below'} EMA50", trend_ok))

    # Momentum (RSI)
    mom_ok = 45 <= rsi <= 70
    factors.append(_factor(
        "momentum", {"rsi": rsi},
        f"RSI {rsi:.1f} — " + ("overbought" if rsi > 70 else "oversold" if rsi < 30
                               else "healthy zone" if mom_ok else "neutral/soft"), mom_ok))

    # Volume
    vol_ok = vr >= 0.8
    factors.append(_factor(
        "volume", {"volume_ratio": vr},
        f"Volume {vr:.2f}× average — " + ("strong participation" if vr >= 1.2
                                          else "normal" if vol_ok else "below average (liquidity risk)"),
        vol_ok))

    # Sector strength
    sector_rank = ctx.get("sector_rank")
    sector_ok = isinstance(sector_rank, int) and sector_rank <= 3
    factors.append(_factor(
        "sector_strength", {"sector": ctx.get("sector"), "rank": sector_rank},
        f"{ctx.get('sector')} ranked #{sector_rank} by average opportunity score in this scan",
        sector_ok))

    # Market regime vs strategy fit
    regime_ok = strat_regime.upper() in (str(regime).upper(), "ALL", "ANY", "UNKNOWN")
    factors.append(_factor(
        "market_regime", {"market": regime, "strategy_best_regime": strat_regime},
        f"Market regime {regime}; strategy '{strat}' performs best in {strat_regime}",
        regime_ok))

    # Risk / Reward
    risk_pct = ctx.get("risk_pct")
    reward_pct = ctx.get("reward_pct")
    rr_ok = rr >= 1.5
    factors.append(_factor("risk", {"risk_pct": risk_pct, "stop_loss": ctx.get("stop_loss")},
                           f"Stop-loss risk {risk_pct}% of entry" if risk_pct is not None
                           else "No stop-loss computed", risk_pct is not None and risk_pct <= 5))
    factors.append(_factor("reward", {"reward_pct": reward_pct, "target": ctx.get("target_price")},
                           f"Target reward {reward_pct}% of entry" if reward_pct is not None
                           else "No target computed", reward_pct is not None and reward_pct >= 2))
    factors.append(_factor("risk_reward_ratio", {"rr_ratio": rr},
                           f"RR {rr:.2f} {'meets' if rr_ok else 'below'} the 1.5 minimum for BUY",
                           rr_ok))

    # Confidence & opportunity
    factors.append(_factor("confidence", {"calibrated_confidence": conf},
                           f"Calibrated confidence {conf:.1f}/100", conf >= 60))
    factors.append(_factor("opportunity_score", {"opportunity_score": opp},
                           f"Opportunity score {opp:.1f}/100", opp >= 60))

    # Strategy match
    factors.append(_factor("strategy_match",
                           {"strategy": strat, "technical_score": ctx.get("technical_score")},
                           f"Best strategy '{strat}' with 6-month walk score "
                           f"{ctx.get('technical_score')}", float(ctx.get("technical_score") or 0) >= 50))

    # Data quality
    q = score_symbol(ctx)
    factors.append(_factor("data_quality",
                           {"score": q["data_quality_score"], "band": q["band"]},
                           f"Data quality {q['data_quality_score']}/100 ({q['band']})",
                           q["tradeable"]))

    positives = [f for f in factors if f["favourable"]]
    negatives = [f for f in factors if not f["favourable"]]

    def _list(fs: List[Dict[str, Any]]) -> str:
        return "; ".join(f["assessment"] for f in fs) if fs else "none"

    if effective in ("STRONG BUY", "BUY"):
        headline = (f"Why Buy? {len(positives)}/{len(factors)} factors favourable — "
                    f"{_list(positives[:4])}.")
    elif effective == "WATCH":
        headline = (f"Why Watch (not Buy)? Held back by: {_list(negatives[:4])}."
                    if negatives else
                    "Why Watch? Score falls in the WATCH band despite favourable factors.")
        if ctx.get("stale") and action in ("STRONG BUY", "BUY"):
            headline = ("Why Watch (not Buy)? Scan data is stale — BUY recommendations "
                        "are disabled until the scan is refreshed. " + headline)
    else:
        headline = f"Why Ignore? Blocking factors: {_list(negatives[:5])}."

    return {
        "available": True,
        "symbol": ctx["symbol"],
        "scan_id": ctx["scan_id"], "snapshot_ts": ctx["snapshot_ts"],
        "final_decision": action,
        "effective_decision": effective,
        "stale": ctx.get("stale"),
        "factors": factors,
        "favourable_count": len(positives),
        "unfavourable_count": len(negatives),
        "headline": headline,
        "explanation": headline + (
            f" Strategy: {strat}. Regime: {regime}. Confidence {conf:.1f}, "
            f"opportunity {opp:.1f}, RR {rr:.2f}."),
        "label": "PAPER / RESEARCH ONLY",
    }


def explain_all(limit: int = 50) -> Dict[str, Any]:
    ctx = build_scan_context()
    if not ctx.get("available"):
        return {"available": False, "reason": ctx.get("reason")}
    out = []
    for sym in list(ctx["symbols"].keys())[:limit]:
        e = explain_symbol(sym)
        if e.get("available"):
            out.append({k: e[k] for k in ("symbol", "final_decision", "effective_decision",
                                          "favourable_count", "unfavourable_count", "headline")})
    return {"available": True, "scan_id": ctx["scan_id"], "items": out,
            "label": "PAPER / RESEARCH ONLY"}
