"""
ai_decision.py
AI Decision Engine — post-processing layer on top of signal_engine signals.

Reviews each signal using:
  - Market regime
  - Multi-timeframe confirmation (3/4 rule)
  - Risk/reward ratio (minimum 1:2)
  - ATR volatility level
  - Stop-loss distance from entry
  - Available capital
  - Raw signal confidence score

Rules (downgrades):
  1. RR < 1:2           → BUY/SELL capped at WATCH (or NO_TRADE if <60 confidence)
  2. MTF < 3/4          → BUY/SELL capped at WATCH
  3. HIGH_VOLATILITY + confidence < 70 → downgrade to WATCH
  4. SIDEWAYS + confidence < 72 → avoid weak trend-following → WATCH
  5. Stop too tight (<0.5% from entry) → WATCH (whipsaw risk)
  6. Insufficient capital for 1 share → NO_TRADE

Upgrades:
  A. RR ≥ 3:1 AND MTF = 4/4 → confidence +5
  B. Regime matches signal direction → confidence +3
  C. LOW_VOLATILITY + confidence ≥ 80 → confidence +3

Output: AiDecision TypedDict with all data needed for Trade Replay and UI.
"""

from datetime import datetime
from typing import TypedDict


# ── Type definition ────────────────────────────────────────────────────────────

class AiDecision(TypedDict):
    stock: str
    raw_signal: str            # signal_engine output before AI review
    decision: str              # STRONG_BUY | BUY | STRONG_SELL | SELL | WATCH | NO_TRADE
    confidence: float          # 0–100, adjusted
    risk_level: str            # LOW | MEDIUM | HIGH
    entry_price: float
    stop_loss: float
    target: float
    rr_ratio: float            # reward:risk (e.g. 2.5 means 2.5:1)
    upgrade_reasons: list[str]
    downgrade_reasons: list[str]
    plain_english: str
    regime: str
    timeframe_alignment: int
    pass_all_rules: bool
    time: str


# ── Helpers ────────────────────────────────────────────────────────────────────

BULLISH_SIGNALS = {"STRONG_BUY", "BUY"}
BEARISH_SIGNALS = {"STRONG_SELL", "SELL"}
ACTIONABLE_SIGNALS = BULLISH_SIGNALS | BEARISH_SIGNALS

REGIME_BULLISH = {"BULLISH", "LOW_VOLATILITY"}
REGIME_BEARISH = {"BEARISH"}


def _compute_rr(signal: dict) -> float:
    """Compute reward:risk ratio from signal fields."""
    entry = signal.get("price", 0.0)
    stop = signal.get("stop_loss", 0.0)
    target = signal.get("target", 0.0)
    if entry <= 0 or stop <= 0 or target <= 0:
        return 0.0

    is_long = signal.get("signal", "") in BULLISH_SIGNALS
    if is_long:
        risk = entry - stop
        reward = target - entry
    else:
        risk = stop - entry
        reward = entry - target

    if risk <= 0:
        return 0.0
    return round(reward / risk, 2)


def _classify(confidence: float, is_bullish: bool) -> str:
    if confidence >= 90:
        return "STRONG_BUY" if is_bullish else "STRONG_SELL"
    elif confidence >= 75:
        return "BUY" if is_bullish else "SELL"
    elif confidence >= 60:
        return "WATCH"
    return "NO_TRADE"


# ── Core decision function ─────────────────────────────────────────────────────

def make_ai_decision(signal: dict, available_cash: float = 5000.0) -> AiDecision:
    """
    Review a single signal from signal_engine and produce a final trade decision.

    Args:
        signal: Signal dict from scan_watchlist / generate_signal
        available_cash: current available cash for position sizing

    Returns:
        AiDecision with adjusted confidence, decision, and reasoning
    """
    stock = signal.get("stock", "")
    raw_signal = signal.get("signal", "NO_TRADE")
    raw_confidence = float(signal.get("confidence", 0.0))
    regime = signal.get("regime", "SIDEWAYS")
    tf_align = int(signal.get("timeframe_alignment", 0))
    risk_level = signal.get("risk_level", "MEDIUM")
    entry = float(signal.get("price", 0.0))
    stop = float(signal.get("stop_loss", 0.0))
    target = float(signal.get("target", 0.0))

    is_bullish = raw_signal in BULLISH_SIGNALS
    is_bearish = raw_signal in BEARISH_SIGNALS
    is_actionable = raw_signal in ACTIONABLE_SIGNALS

    rr_ratio = _compute_rr(signal)
    confidence = raw_confidence
    upgrade_reasons: list[str] = []
    downgrade_reasons: list[str] = []

    # ── Upgrades (applied first so downgrades can override) ────────────────────

    # A: Excellent RR + full MTF alignment
    if rr_ratio >= 3.0 and tf_align >= 4 and is_actionable:
        confidence = min(100.0, confidence + 5)
        upgrade_reasons.append(
            f"Excellent RR {rr_ratio:.1f}:1 with full 4/4 timeframe agreement → +5 confidence"
        )

    # B: Market regime aligns with trade direction
    if is_bullish and regime in REGIME_BULLISH:
        confidence = min(100.0, confidence + 3)
        upgrade_reasons.append(f"{regime} regime supports long position → +3 confidence")
    elif is_bearish and regime in REGIME_BEARISH:
        confidence = min(100.0, confidence + 3)
        upgrade_reasons.append(f"{regime} regime supports short position → +3 confidence")

    # C: Low volatility with strong setup
    if regime == "LOW_VOLATILITY" and raw_confidence >= 80 and is_actionable:
        confidence = min(100.0, confidence + 3)
        upgrade_reasons.append(
            "LOW VOLATILITY with strong base confidence → +3 confidence"
        )

    # ── Downgrades ─────────────────────────────────────────────────────────────

    # Rule 1: Risk/reward ratio < 1:2
    if is_actionable and rr_ratio < 2.0:
        downgrade_reasons.append(
            f"RR {rr_ratio:.1f}:1 below required minimum 2:1 — trade not worth the risk"
        )
        confidence = min(confidence, 68.0)

    # Rule 2: Multi-timeframe alignment < 3/4
    if is_actionable and tf_align < 3:
        downgrade_reasons.append(
            f"Only {tf_align}/4 timeframes confirm the direction — need at least 3"
        )
        confidence = min(confidence, 70.0)

    # Rule 3: High volatility + low-confidence trade
    if regime == "HIGH_VOLATILITY" and raw_confidence < 70 and is_actionable:
        downgrade_reasons.append(
            "HIGH VOLATILITY: downgrading low-confidence signal to WATCH"
        )
        confidence = min(confidence, 65.0)
        risk_level = "HIGH"

    # Rule 4: Sideways market — avoid weak trend-following
    if regime == "SIDEWAYS" and raw_confidence < 72 and is_actionable:
        downgrade_reasons.append(
            "SIDEWAYS market: trend-following signal lacks conviction — avoid"
        )
        confidence = min(confidence, 65.0)

    # Rule 5: Stop loss too tight (whipsaw risk)
    if entry > 0 and stop > 0:
        stop_distance_pct = abs(entry - stop) / entry * 100
        if stop_distance_pct < 0.5 and is_actionable:
            downgrade_reasons.append(
                f"Stop loss only {stop_distance_pct:.1f}% from entry — too tight for volatile markets"
            )
            confidence = min(confidence, 65.0)

    # Rule 6: Insufficient capital
    if entry > 0 and available_cash < entry:
        downgrade_reasons.append(
            f"Cannot afford even 1 share at ₹{entry:.0f} — capital ₹{available_cash:.0f} insufficient"
        )
        confidence = 0.0

    # ── Final decision ─────────────────────────────────────────────────────────
    confidence = round(max(0.0, min(100.0, confidence)), 1)

    if not is_actionable:
        # Non-actionable raw signals pass through unchanged
        decision = raw_signal
    elif not downgrade_reasons:
        # No rules triggered — reclassify based on adjusted confidence
        decision = _classify(confidence, is_bullish)
    else:
        # Downgrades triggered — reclassify (can only go down from raw_signal)
        candidate = _classify(confidence, is_bullish)
        # Ensure we never upgrade via downgrade path
        order = ["STRONG_BUY", "BUY", "WATCH", "NO_TRADE",
                 "STRONG_SELL", "SELL", "WATCH", "NO_TRADE"]
        raw_rank = order.index(raw_signal) if raw_signal in order else 3
        cand_rank = order.index(candidate) if candidate in order else 3
        decision = candidate if cand_rank >= raw_rank else raw_signal

    # Sanity: if no raw action, don't promote to STRONG
    if raw_signal == "NO_TRADE":
        decision = "NO_TRADE"
    elif raw_signal == "WATCH":
        if decision in ACTIONABLE_SIGNALS:
            decision = "WATCH"

    pass_all_rules = (is_actionable and not downgrade_reasons) or not is_actionable

    # ── Plain English summary ──────────────────────────────────────────────────
    if not is_actionable:
        plain = (
            f"The raw signal for {stock} is {raw_signal} with confidence {raw_confidence:.0f}. "
            "No actionable trade — monitoring only."
        )
    elif pass_all_rules:
        plain = (
            f"AI engine APPROVES the {raw_signal} signal for {stock}. "
            f"RR is {rr_ratio:.1f}:1, {tf_align}/4 timeframes agree, and the {regime} regime "
            f"supports this direction. Adjusted confidence: {confidence:.0f}/100. "
            + (f"Upgrades applied: {'; '.join(upgrade_reasons)}" if upgrade_reasons else "")
        )
    elif decision == "NO_TRADE":
        plain = (
            f"AI engine BLOCKS the {raw_signal} signal for {stock}. "
            f"Critical rule failures: {'; '.join(downgrade_reasons[:2])}. "
            "Stand aside — no trade."
        )
    else:
        plain = (
            f"AI engine DOWNGRADES the {raw_signal} signal for {stock} to {decision}. "
            f"Reasons: {'; '.join(downgrade_reasons[:2])}. "
            f"Confidence adjusted to {confidence:.0f}/100."
        )

    return AiDecision(
        stock=stock,
        raw_signal=raw_signal,
        decision=decision,
        confidence=confidence,
        risk_level=risk_level,
        entry_price=round(entry, 2),
        stop_loss=round(stop, 2),
        target=round(target, 2),
        rr_ratio=rr_ratio,
        upgrade_reasons=upgrade_reasons,
        downgrade_reasons=downgrade_reasons,
        plain_english=plain,
        regime=regime,
        timeframe_alignment=tf_align,
        pass_all_rules=pass_all_rules,
        time=datetime.now().isoformat(),
    )


def scan_ai_decisions(signals: list[dict], available_cash: float = 5000.0) -> list[AiDecision]:
    """
    Run the AI Decision Engine across a full list of signals.

    Args:
        signals: list of Signal dicts from scan_watchlist
        available_cash: current cash for capital checks

    Returns:
        List of AiDecision dicts aligned 1:1 with input signals
    """
    return [make_ai_decision(sig, available_cash) for sig in signals]
