"""Phase 7.4 – Operator-facing plain-language summary for one symbol."""
from __future__ import annotations
from typing import Any, Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from .models import ExplainableDecision


def build_operator_summary(decision: "ExplainableDecision") -> Dict[str, Any]:
    """
    Return a concise operator summary containing:
     - one-sentence 'why' statement
     - top 3 supporting factors
     - key risks
     - key opportunities
     - action items
    """
    symbol = decision.symbol
    sig    = decision.signal_type
    # confidence: prefer 0-1 `confidence` field; fall back to final_confidence (0-100)
    conf_raw = decision.confidence if decision.confidence > 0 else decision.final_confidence
    conf = conf_raw / 100.0 if conf_raw > 1.0 else conf_raw
    grade = decision.grade

    # primary_reasons property combines primary_reason + secondary_reasons
    all_reasons = decision.primary_reasons or []

    # ---------- why sentence ----------
    primary_reasons = [r for r in all_reasons if r][:3]
    if primary_reasons:
        reason_text = "; ".join(primary_reasons[:2])
        why = f"{symbol} shows a {sig} signal ({conf * 100:.0f}% confidence, grade {grade}): {reason_text}."
    else:
        why = f"{symbol} shows a {sig} signal with {conf * 100:.0f}% confidence (grade {grade})."

    # ---------- top 3 factors ----------
    top_factors: List[str] = []
    for r in all_reasons[:4]:
        if r and r not in top_factors:
            top_factors.append(r)
        if len(top_factors) == 3:
            break

    # ---------- risks ----------
    risks: List[str] = []
    risk_level = decision.risk_level or "MEDIUM"
    if risk_level == "HIGH":
        risks.append("High-risk setup — size conservatively and honour the stop-loss")
    elif risk_level == "MEDIUM":
        risks.append("Moderate risk — standard position sizing applies")
    else:
        risks.append("Low-risk profile — conditions are relatively favourable")

    if decision.stop_loss:
        risks.append(f"Hard stop-loss at ₹{decision.stop_loss:.2f} must not be moved lower")
    if conf < 0.5:
        risks.append("Sub-50% confidence — consider skipping or reducing size")

    # ---------- opportunities ----------
    opportunities: List[str] = []
    if decision.target and decision.price:
        upside = (decision.target - decision.price) / decision.price * 100
        opportunities.append(
            f"Target ₹{decision.target:.2f} represents ~{upside:.1f}% upside"
        )
    if conf >= 0.70:
        opportunities.append("High-confidence signal — full position sizing permissible")
    for r in (decision.secondary_reasons or [])[:2]:
        if r:
            opportunities.append(r)

    # ---------- action items ----------
    action_items: List[str] = []
    if sig in ("BUY", "STRONG_BUY"):
        action_items.append(f"Enter long position in {symbol} at or near current price")
        if decision.stop_loss:
            action_items.append(f"Set stop-loss at ₹{decision.stop_loss:.2f}")
        if decision.target:
            action_items.append(f"Set target at ₹{decision.target:.2f}")
    elif sig in ("SELL", "STRONG_SELL"):
        action_items.append(f"Consider shorting or exiting long position in {symbol}")
        if decision.stop_loss:
            action_items.append(f"Set stop-loss at ₹{decision.stop_loss:.2f}")
    else:
        action_items.append(f"Hold — no actionable signal for {symbol} at this time")
        action_items.append("Reassess at next scan cycle")

    return {
        "symbol":        symbol,
        "why":           why,
        "top_factors":   top_factors[:3],
        "risks":         risks,
        "opportunities": opportunities,
        "action_items":  action_items,
        "signal":        sig,
        "confidence":    conf,
        "grade":         grade,
        "risk_level":    risk_level,
    }
