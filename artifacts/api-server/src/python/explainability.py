"""
explainability.py
Explainability Engine — generates structured natural-language trade
explanations that clearly communicate WHY a trade was approved or blocked.

Output format (based on user requirements):

  This trade is approved because:
  • Market trend is bullish.
  • 3 of 4 timeframes agree.
  • Price is above VWAP.
  • Volume is 2× average.
  • Risk reward is 1:2.4.

  Avoid because:
  • Resistance is only 1.8% away.

  Final Confidence: 86%
  Recommendation: BUY

Inputs: signal + ai_decision + trade_quality + position_sizing + market_context
No additional data fetching — all inputs already computed.
"""

from typing import TypedDict


# ── TypedDict ─────────────────────────────────────────────────────────────────

class ExplainabilityReport(TypedDict):
    approve_reasons:  list[str]
    avoid_reasons:    list[str]
    recommendation:   str          # BUY | SELL | WATCH | NO_TRADE
    final_confidence: float
    summary:          str          # full formatted plain-text block
    one_liner:        str          # single sentence for tooltips / lists


# ── Helpers ───────────────────────────────────────────────────────────────────

BULLISH = {"STRONG_BUY", "BUY"}
BEARISH = {"STRONG_SELL", "SELL"}
ACTIONABLE = BULLISH | BEARISH


def _market_bias_line(market_context: dict) -> str | None:
    bias = market_context.get("bias", "NEUTRAL")
    score = market_context.get("score", 50)
    breadth = market_context.get("breadth_label", "NEUTRAL")
    vix_cat = market_context.get("vix_category", "NORMAL")

    if bias == "BULLISH":
        return f"Overall market is bullish (score {score:.0f}/100, breadth {breadth.lower().replace('_', ' ')})."
    elif bias == "BEARISH":
        return f"Overall market is bearish (score {score:.0f}/100) — headwind for long trades."
    else:
        return f"Market is neutral (score {score:.0f}/100, VIX {vix_cat.lower()})."


def _tf_line(tf_align: int) -> str:
    labels = ["5M", "15M", "1H", "1D"]
    return f"{tf_align} of 4 timeframes agree ({', '.join(labels[:tf_align])})."


def _rr_line(rr: float) -> str:
    return f"Risk reward is 1:{rr:.1f}."


# ── Core function ─────────────────────────────────────────────────────────────

def explain_trade(
    signal: dict,
    ai_decision: dict,
    trade_quality: dict,
    position_sizing: dict,
    market_context: dict,
) -> ExplainabilityReport:
    """
    Generate a structured natural-language explanation for a trade decision.

    Args:
        signal          : Signal dict from signal_engine
        ai_decision     : AiDecision dict from ai_decision module
        trade_quality   : TradeQuality dict from trade_quality module
        position_sizing : PositionSizing dict from position_sizer module
        market_context  : MarketContext dict from market_context module

    Returns:
        ExplainabilityReport with approve/avoid lists and formatted summary.
    """
    stock        = signal.get("stock", "")
    sig_type     = signal.get("signal", "NO_TRADE")
    decision     = ai_decision.get("decision", "NO_TRADE")
    confidence   = ai_decision.get("confidence", 0.0)
    tf_align     = signal.get("timeframe_alignment", 0)
    regime       = signal.get("regime", "SIDEWAYS")
    explanation  = signal.get("explanation", {})
    rr_ratio     = ai_decision.get("rr_ratio", 0.0)
    pass_rules   = ai_decision.get("pass_all_rules", False)

    approve: list[str] = []
    avoid:   list[str] = []

    # ── Market context ────────────────────────────────────────────────────────
    bias = market_context.get("bias", "NEUTRAL")
    mkt_line = _market_bias_line(market_context)
    if mkt_line:
        if bias == "BULLISH" and sig_type in BULLISH:
            approve.append(mkt_line)
        elif bias == "BEARISH" and sig_type in BULLISH:
            avoid.append(mkt_line)
        elif bias == "BEARISH" and sig_type in BEARISH:
            approve.append(mkt_line)
        else:
            pass  # neutral — skip

    # ── Timeframe alignment ───────────────────────────────────────────────────
    if tf_align >= 3:
        approve.append(_tf_line(tf_align))
    elif sig_type in ACTIONABLE:
        avoid.append(f"Only {tf_align} of 4 timeframes agree — weak confirmation.")

    # ── VWAP ─────────────────────────────────────────────────────────────────
    indicator_text = explanation.get("indicator_summary", "").lower()
    reasons = signal.get("reasons", [])
    for r in reasons:
        rl = r.lower()
        if "above vwap" in rl and sig_type in BULLISH:
            approve.append("Price is above VWAP — institutional buying zone.")
            break
        elif "below vwap" in rl and sig_type in BULLISH:
            avoid.append("Price is below VWAP — selling pressure from institutions.")
            break

    # ── Volume ────────────────────────────────────────────────────────────────
    import re
    for r in reasons:
        m = re.search(r"volume\s+(\d+\.?\d*)\s*[×x×]", r.lower())
        if m:
            mult = float(m.group(1))
            if mult >= 1.5:
                approve.append(f"Volume is {mult:.1f}× average — strong conviction.")
            else:
                avoid.append(f"Volume is only {mult:.1f}× average — weak conviction.")
            break

    # ── RR ratio ─────────────────────────────────────────────────────────────
    if rr_ratio >= 2.0:
        approve.append(_rr_line(rr_ratio))
    elif sig_type in ACTIONABLE:
        avoid.append(f"Risk reward is only 1:{rr_ratio:.1f} — below the 1:2 minimum.")

    # ── Trade quality sub-scores ──────────────────────────────────────────────
    tq_total = trade_quality.get("total_score", 0.0)
    tq_grade = trade_quality.get("grade", "F")
    if tq_total >= 75:
        approve.append(f"Trade quality score is {tq_total:.0f}/100 (grade {tq_grade}) — high-quality setup.")
    elif tq_total >= 55:
        pass  # average — no strong statement
    elif sig_type in ACTIONABLE:
        avoid.append(f"Trade quality score is {tq_total:.0f}/100 (grade {tq_grade}) — below ideal.")

    # Momentum
    momentum_s = trade_quality.get("momentum_score", 50.0)
    momentum_text = explanation.get("momentum", "").lower()
    if momentum_s >= 70:
        approve.append(f"Momentum is strong ({momentum_text.split('.')[0].strip()}).")
    elif momentum_s < 35 and sig_type in ACTIONABLE:
        avoid.append(f"Momentum is weak ({momentum_text.split('.')[0].strip()}).")

    # ── Resistance proximity (avoid reason) ───────────────────────────────────
    entry  = signal.get("price", 0.0)
    target = signal.get("target", 0.0)
    stop   = signal.get("stop_loss", 0.0)
    if entry > 0 and target > 0 and sig_type in BULLISH:
        reward_pct = (target - entry) / entry * 100
        if reward_pct < 2.5:
            avoid.append(
                f"Target is only {reward_pct:.1f}% away — limited upside before resistance."
            )

    # ── Regime context ────────────────────────────────────────────────────────
    if regime == "HIGH_VOLATILITY":
        avoid.append("Market is in HIGH VOLATILITY regime — wider stops needed; risk is elevated.")
    elif regime == "LOW_VOLATILITY" and sig_type in BULLISH:
        approve.append("LOW VOLATILITY regime — compressed ranges favour breakout entries.")
    elif regime == "SIDEWAYS" and sig_type in BULLISH:
        avoid.append("SIDEWAYS market — trend-following signals have reduced reliability.")

    # ── AI upgrade reasons (add best one if positive) ─────────────────────────
    upgrades = ai_decision.get("upgrade_reasons", [])
    if upgrades and sig_type in ACTIONABLE:
        approve.append(upgrades[0].split("→")[0].strip() + ".")

    # ── Position feasibility ──────────────────────────────────────────────────
    feasible = position_sizing.get("feasible", False)
    if not feasible and sig_type in ACTIONABLE:
        avoid.append(position_sizing.get("sizing_note", "Insufficient capital for this trade."))
    elif feasible and position_sizing.get("suggested_quantity", 0) > 0:
        qty = position_sizing["suggested_quantity"]
        max_loss = position_sizing["max_loss"]
        exp_profit = position_sizing["expected_profit"]
        approve.append(
            f"Position sizing: {qty} share(s), max loss ₹{max_loss:.0f}, expected gain ₹{exp_profit:.0f}."
        )

    # ── Dedup and cap lists ───────────────────────────────────────────────────
    approve = list(dict.fromkeys(approve))[:6]
    avoid   = list(dict.fromkeys(avoid))[:4]

    # ── Build summary text ────────────────────────────────────────────────────
    lines: list[str] = []
    if approve:
        if decision in ACTIONABLE and pass_rules:
            lines.append("This trade is approved because:")
        elif decision in ACTIONABLE:
            lines.append("Partial approval — some conditions met:")
        else:
            lines.append("Factors in favour:")
        for r in approve:
            lines.append(f"  • {r}")

    if avoid:
        lines.append("")
        lines.append("Avoid because:" if decision not in ACTIONABLE else "Watch out for:")
        for r in avoid:
            lines.append(f"  • {r}")

    lines.append("")
    lines.append(f"Final Confidence: {confidence:.0f}%")
    lines.append(f"Recommendation: {decision.replace('_', ' ')}")

    summary = "\n".join(lines)

    # ── One-liner ─────────────────────────────────────────────────────────────
    if decision in BULLISH and pass_rules:
        one_liner = (
            f"{stock}: BUY approved — {tq_grade} quality, "
            f"RR {rr_ratio:.1f}:1, {tf_align}/4 TF, conf {confidence:.0f}%"
        )
    elif decision == "WATCH":
        top_avoid = avoid[0] if avoid else "conditions not fully met"
        one_liner = f"{stock}: WATCH — {top_avoid.lower().rstrip('.')}"
    elif decision == "NO_TRADE":
        top_avoid = avoid[0] if avoid else "below minimum thresholds"
        one_liner = f"{stock}: NO TRADE — {top_avoid.lower().rstrip('.')}"
    else:
        one_liner = f"{stock}: {decision} | conf {confidence:.0f}% | TQ {tq_total:.0f}/100"

    return ExplainabilityReport(
        approve_reasons  = approve,
        avoid_reasons    = avoid,
        recommendation   = decision,
        final_confidence = round(confidence, 1),
        summary          = summary,
        one_liner        = one_liner,
    )
