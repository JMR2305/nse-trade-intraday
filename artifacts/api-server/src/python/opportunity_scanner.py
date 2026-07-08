"""
opportunity_scanner.py
Opportunity Scanner — ranks all watchlist stocks from best to worst
trading opportunity, combining signal quality, AI decision, and market context.

Opportunity Score formula (0–100):
  trade_quality × 0.40   — quality of the setup
  ai_confidence × 0.30   — AI-adjusted confidence
  rr_score      × 0.20   — normalized RR ratio quality
  mkt_alignment × 0.10   — market context bonus

Status mapping:
  HOT_BUY  : opportunity_score ≥ 85  (exceptional setup — act fast)
  BUY      : ≥ 70                    (good opportunity)
  WATCH    : ≥ 50                    (worth monitoring)
  IGNORE   : < 50                    (no edge)
"""

from datetime import datetime
from typing import TypedDict
from config import (
    OPP_HOT_BUY_THRESHOLD, OPP_BUY_THRESHOLD, OPP_WATCH_THRESHOLD,
    OPP_WEIGHTS,
)


# ── TypedDict ─────────────────────────────────────────────────────────────────

class OpportunityItem(TypedDict):
    rank:              int
    stock:             str
    opportunity_score: float    # 0–100 composite
    confidence:        float    # AI-adjusted confidence
    expected_risk:     float    # max_loss (₹)
    expected_reward:   float    # expected_profit (₹)
    rr_ratio:          float
    status:            str      # HOT_BUY | BUY | WATCH | IGNORE
    entry_price:       float
    stop_loss:         float
    target:            float
    # Trade quality
    trade_quality:     float    # total_score
    tq_grade:          str      # A+ | A | B | C | D | F
    tq_trend:          float
    tq_momentum:       float
    tq_volume:         float
    tq_breakout:       float
    tq_risk:           float
    tq_market:         float
    # Position sizing
    suggested_qty:     int
    position_value:    float
    capital_used_pct:  float
    sizing_note:       str
    feasible:          bool
    # Explainability
    approve_reasons:   list
    avoid_reasons:     list
    one_liner:         str
    summary:           str
    # Context
    regime:            str
    ai_decision:       str
    raw_signal:        str


# ── Helpers ───────────────────────────────────────────────────────────────────

BULLISH = {"STRONG_BUY", "BUY"}
BEARISH = {"STRONG_SELL", "SELL"}
ACTIONABLE = BULLISH | BEARISH


def _opportunity_status(score: float) -> str:
    if score >= OPP_HOT_BUY_THRESHOLD:
        return "HOT_BUY"
    elif score >= OPP_BUY_THRESHOLD:
        return "BUY"
    elif score >= OPP_WATCH_THRESHOLD:
        return "WATCH"
    return "IGNORE"


def _rr_normalized(rr_ratio: float) -> float:
    """Normalize RR ratio to 0–100 score. 3:1 → ~75, 4:1 → ~100."""
    return min(100.0, rr_ratio / 4.0 * 100)


def _market_alignment_bonus(ai_decision: str, market_context: dict) -> float:
    """
    Market alignment bonus (0–100): how well the trade direction aligns with
    the broad market context.
    """
    bias = market_context.get("bias", "NEUTRAL")
    score = float(market_context.get("score", 50.0))

    if ai_decision in BULLISH and bias == "BULLISH":
        return min(100.0, score + 10)
    elif ai_decision in BULLISH and bias == "BEARISH":
        return max(0.0, score - 15)
    elif ai_decision in BEARISH and bias == "BEARISH":
        return min(100.0, score + 10)
    elif ai_decision in BEARISH and bias == "BULLISH":
        return max(0.0, score - 15)
    return score  # neutral


# ── Core function ─────────────────────────────────────────────────────────────

def rank_opportunities(
    signals:         list[dict],
    ai_decisions:    list[dict],
    trade_qualities: list[dict],
    position_sizes:  list[dict],
    explainabilities: list[dict],
    market_context:  dict,
) -> list[OpportunityItem]:
    """
    Rank all scanned stocks by opportunity score.

    All input lists are aligned 1:1 with the signals list.
    Returns a sorted list (best opportunity first).

    Args:
        signals           : from signal_engine.scan_watchlist()
        ai_decisions      : from ai_decision.scan_ai_decisions()
        trade_qualities   : from trade_quality.compute_trade_quality()
        position_sizes    : from position_sizer.compute_from_signal()
        explainabilities  : from explainability.explain_trade()
        market_context    : from market_context.compute_market_context()

    Returns:
        List of OpportunityItem sorted by opportunity_score descending.
    """
    items: list[OpportunityItem] = []
    w = OPP_WEIGHTS

    for i, sig in enumerate(signals):
        ai_dec    = ai_decisions[i]    if i < len(ai_decisions)    else {}
        tq        = trade_qualities[i] if i < len(trade_qualities) else {}
        ps        = position_sizes[i]  if i < len(position_sizes)  else {}
        expl      = explainabilities[i] if i < len(explainabilities) else {}

        stock      = sig.get("stock", "")
        ai_decision_str = ai_dec.get("decision", "NO_TRADE")
        raw_signal = ai_dec.get("raw_signal", sig.get("signal", "NO_TRADE"))
        confidence = ai_dec.get("confidence", 0.0)
        rr_ratio   = ai_dec.get("rr_ratio", 0.0)
        tq_total   = tq.get("total_score", 0.0)

        # For NON-TRADE decisions, opportunity is low but still ranked
        if ai_decision_str == "NO_TRADE":
            opp_score = min(40.0, tq_total * 0.3 + confidence * 0.1)
        elif ai_decision_str == "WATCH":
            opp_score = min(65.0, (
                tq_total             * w["trade_quality"]    +
                confidence           * w["ai_confidence"]    +
                _rr_normalized(rr_ratio) * w["rr_score"]    +
                _market_alignment_bonus(ai_decision_str, market_context) * w["market_alignment"]
            ))
        else:
            # Actionable: full score
            opp_score = (
                tq_total             * w["trade_quality"]    +
                confidence           * w["ai_confidence"]    +
                _rr_normalized(rr_ratio) * w["rr_score"]    +
                _market_alignment_bonus(ai_decision_str, market_context) * w["market_alignment"]
            )

        opp_score = round(min(100.0, max(0.0, opp_score)), 1)

        items.append(OpportunityItem(
            rank              = 0,
            stock             = stock,
            opportunity_score = opp_score,
            confidence        = confidence,
            expected_risk     = ps.get("max_loss", 0.0),
            expected_reward   = ps.get("expected_profit", 0.0),
            rr_ratio          = rr_ratio,
            status            = _opportunity_status(opp_score),
            entry_price       = ai_dec.get("entry_price", sig.get("price", 0.0)),
            stop_loss         = ai_dec.get("stop_loss", sig.get("stop_loss", 0.0)),
            target            = ai_dec.get("target", sig.get("target", 0.0)),
            trade_quality     = tq_total,
            tq_grade          = tq.get("grade", "F"),
            tq_trend          = tq.get("trend_score", 50.0),
            tq_momentum       = tq.get("momentum_score", 50.0),
            tq_volume         = tq.get("volume_score", 50.0),
            tq_breakout       = tq.get("breakout_score", 50.0),
            tq_risk           = tq.get("risk_score", 50.0),
            tq_market         = tq.get("market_score", 50.0),
            suggested_qty     = ps.get("suggested_quantity", 0),
            position_value    = ps.get("position_value", 0.0),
            capital_used_pct  = ps.get("capital_utilization_pct", 0.0),
            sizing_note       = ps.get("sizing_note", ""),
            feasible          = ps.get("feasible", False),
            approve_reasons   = expl.get("approve_reasons", []),
            avoid_reasons     = expl.get("avoid_reasons", []),
            one_liner         = expl.get("one_liner", ""),
            summary           = expl.get("summary", ""),
            regime            = sig.get("regime", "UNKNOWN"),
            ai_decision       = ai_decision_str,
            raw_signal        = raw_signal,
        ))

    # Sort best first
    items.sort(key=lambda x: x["opportunity_score"], reverse=True)

    # Assign ranks
    for rank_idx, item in enumerate(items, start=1):
        item["rank"] = rank_idx

    return items
