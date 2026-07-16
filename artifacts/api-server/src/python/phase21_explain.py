"""
phase21_explain.py — Phase 21: "Why this trade?" rule-based explanations.

PAPER / RESEARCH ONLY.
- Every statement is generated from stored factors on the canonical scan item,
  the regime matrix, and the calibration table. No external LLM is used and
  nothing is invented.
"""
from __future__ import annotations

from phase15_scan_context import build_scan_context, symbol_context
from phase21_calibration import calibrate_confidence_advisory
from phase21_regime import load_regime_matrix, normalize_regime


def _regime_pair(strategy: str | None, regime: str | None) -> dict:
    matrix = load_regime_matrix()
    reg = normalize_regime(regime)
    for p in matrix.get("pairs", []):
        if p.get("strategy") == (strategy or "UNKNOWN") and p.get("regime") == reg:
            return p
    return {"classification": "INSUFFICIENT_DATA", "sample_size": 0}


def explain_trade(symbol: str) -> dict:
    item = symbol_context(symbol)
    if not item.get("available"):
        return {"available": False, "reason": item.get("reason")}

    ind = item.get("indicators") or {}
    gates = item.get("gates") or {}
    strat = item.get("strategy_name") or item.get("strategy_id")
    pair = _regime_pair(strat, item.get("regime"))
    cal = calibrate_confidence_advisory(item.get("confidence"))

    reasons: list[dict] = []
    risks: list[dict] = []

    def add(lst, text, factor, value):
        lst.append({"text": text, "evidence_factor": factor, "value": value})

    # ── Supporting reasons (evidence-backed) ─────────────────────────────────
    if ind.get("above_ema20"):
        add(reasons, "Price is trading above its 20-day EMA (short-term uptrend).",
            "indicators.above_ema20", True)
    if ind.get("above_ema50"):
        add(reasons, "Price is holding above its 50-day EMA (medium-term trend intact).",
            "indicators.above_ema50", True)
    rsi = ind.get("rsi")
    if rsi is not None and 45 <= float(rsi) <= 65:
        add(reasons, f"RSI at {round(float(rsi),1)} shows momentum without being overbought.",
            "indicators.rsi", rsi)
    adx = ind.get("adx")
    if adx is not None and float(adx) >= 25:
        add(reasons, f"ADX at {round(float(adx),1)} confirms a trending move.",
            "indicators.adx", adx)
    vr = ind.get("volume_ratio")
    if vr is not None and float(vr) >= 1.2:
        add(reasons, f"Volume is {round(float(vr),2)}x its average — participation confirms the move.",
            "indicators.volume_ratio", vr)
    rr = item.get("rr_ratio")
    if rr is not None and float(rr) >= 2.0:
        add(reasons, f"Risk/reward of {round(float(rr),2)}:1 meets the 2:1 minimum.",
            "rr_ratio", rr)
    if pair.get("classification") == "ELIGIBLE":
        add(reasons, f"Strategy '{strat}' has positive historical expectancy in the "
            f"current {normalize_regime(item.get('regime'))} regime "
            f"({pair.get('sample_size')} completed trades).",
            "regime_matrix.classification", "ELIGIBLE")

    # ── Risks / blockers (evidence-backed) ───────────────────────────────────
    if rsi is not None and float(rsi) > 70:
        add(risks, f"RSI at {round(float(rsi),1)} is overbought — entry may be extended.",
            "indicators.rsi", rsi)
    if rr is not None and float(rr) < 2.0:
        add(risks, f"Risk/reward is only {round(float(rr),2)}:1, below the 2:1 minimum.",
            "rr_ratio", rr)
    if vr is not None and float(vr) < 0.8:
        add(risks, f"Volume is weak at {round(float(vr),2)}x average — poor confirmation.",
            "indicators.volume_ratio", vr)
    if item.get("stale"):
        add(risks, "Scan data is stale — BUY recommendations are disabled until fresh data arrives.",
            "stale", True)
    if pair.get("classification") in ("DISABLED", "WATCHLIST"):
        add(risks, f"Strategy '{strat}' is classified {pair['classification']} in this regime "
            f"based on historical results.", "regime_matrix.classification",
            pair.get("classification"))
    if pair.get("classification") == "INSUFFICIENT_DATA":
        add(risks, "Not enough completed trades to judge this strategy in the current regime.",
            "regime_matrix.sample_size", pair.get("sample_size"))
    dq = str(item.get("data_quality") or "").upper()
    if dq and dq not in ("LIVE", "OK", "NEAR_LIVE"):
        add(risks, f"Data quality is {dq} — reduced trust in current quotes.",
            "data_quality", dq)

    failed_gates = [g for g, ok in gates.items() if ok is False]

    # ── Stop / target rationale ──────────────────────────────────────────────
    stop_rationale = None
    if item.get("entry_price") and item.get("stop_loss"):
        stop_rationale = (
            f"Stop at {item['stop_loss']} risks {item.get('risk_pct')}% from entry "
            f"{item['entry_price']}; target {item.get('target_price')} offers "
            f"{item.get('reward_pct')}% upside ({item.get('rr_ratio')}:1 R:R).")

    return {
        "available": True,
        "symbol": item["symbol"],
        "scan_id": item.get("scan_id"),
        "final_action": item.get("final_action"),
        "effective_action": item.get("effective_action"),
        "reasons": reasons[:3],
        "risks": risks[:3],
        "all_reasons": reasons,
        "all_risks": risks,
        "regime_compatibility": {
            "regime": normalize_regime(item.get("regime")),
            "strategy": strat,
            "classification": pair.get("classification"),
            "sample_size": pair.get("sample_size"),
            "expectancy": pair.get("expectancy"),
        },
        "confidence_reliability": {
            "raw_confidence": item.get("confidence"),
            "calibrated_advisory": cal.get("calibrated_advisory"),
            "bucket": cal.get("bucket"),
            "bucket_status": cal.get("status"),
        },
        "stop_target_rationale": stop_rationale,
        "failed_gates": failed_gates,
        "eligible": item.get("all_gates_passed") is True and not item.get("stale"),
        "evidence_backed": True,
        "generator": "rule_based (no external LLM)",
        "label": "PAPER / RESEARCH ONLY",
    }


def explain_all() -> dict:
    ctx = build_scan_context()
    if not ctx.get("available"):
        return {"available": False, "reason": ctx.get("reason")}
    items = []
    for sym in sorted(ctx["symbols"]):
        if ctx["symbols"][sym].get("error"):
            continue
        items.append(explain_trade(sym))
    return {"available": True, "scan_id": ctx["scan_id"],
            "items": items, "label": "PAPER / RESEARCH ONLY"}
