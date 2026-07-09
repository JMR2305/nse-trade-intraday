"""
learning_engine.py
Strategy Learning Engine (v0.9).

Reads completed paper trades (Trade Journal) and Market Replay history to
compute per-strategy reliability and recommend a relative capital-allocation
weight for each strategy. This module NEVER places or modifies real orders
and NEVER auto-applies weights — it only produces a recommendation + reason
that a human can review on the Learning Summary panel.

Weighting rules:
  - win_rate >= 60% and profit_factor >= 1.5  -> recommend increasing weight
  - win_rate <  45% or  profit_factor <  1.0   -> recommend decreasing weight
  - otherwise                                  -> keep weight unchanged
  - fewer than MIN_SAMPLE_TRADES completed trades -> "not enough data", no change
"""

import json
import os
from datetime import datetime
from typing import TypedDict

from paper_trader import get_trade_replay
from strategies import LAB_STRATEGY_IDS, get_strategy

STATE_DIR = os.path.dirname(os.path.abspath(__file__))
WEIGHTS_FILE = os.path.join(STATE_DIR, "strategy_weights.json")

MIN_SAMPLE_TRADES = 10
WEIGHT_STEP = 0.25          # ±25% relative adjustment per recommendation
MIN_WEIGHT = 0.1
MAX_WEIGHT = 3.0


class StrategyLearning(TypedDict):
    strategy_id:         str
    strategy_name:       str
    total_trades:        int
    win_rate:            float
    profit_factor:       float
    expectancy:          float
    net_pnl:             float
    current_weight:      float
    recommended_weight:  float
    direction:           str    # increase | decrease | hold
    reason:              str
    reliability_warning: str | None


class LearningSummary(TypedDict):
    strategies:     list   # list[StrategyLearning]
    total_trades:   int
    computed_at:    str
    overall_warning: str | None


def _load_weights() -> dict[str, float]:
    if os.path.exists(WEIGHTS_FILE):
        try:
            with open(WEIGHTS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_weights(weights: dict[str, float]) -> None:
    with open(WEIGHTS_FILE, "w") as f:
        json.dump(weights, f, indent=2)


def _all_known_strategy_ids() -> list[str]:
    return list(LAB_STRATEGY_IDS)


def compute_learning_summary(persist_weights: bool = True) -> LearningSummary:
    """
    Group completed Trade Journal entries by strategy_id and compute
    reliability metrics + a recommended weight adjustment for each.
    """
    trades = get_trade_replay()
    weights = _load_weights()

    by_strategy: dict[str, list[dict]] = {}
    names: dict[str, str] = {}
    for t in trades:
        sid = t.get("strategy_id", "ai_scan")
        by_strategy.setdefault(sid, []).append(t)
        names[sid] = t.get("strategy_name", sid)

    # Ensure every known lab strategy shows up (even with 0 trades) so the
    # Learning Summary panel gives a complete picture, not just active ones.
    for sid in _all_known_strategy_ids():
        by_strategy.setdefault(sid, [])
        if sid not in names:
            try:
                names[sid] = get_strategy(sid).name
            except Exception:
                names[sid] = sid

    results: list[StrategyLearning] = []

    for sid, sid_trades in by_strategy.items():
        n = len(sid_trades)
        current_weight = float(weights.get(sid, 1.0))

        if n == 0:
            results.append(StrategyLearning(
                strategy_id=sid, strategy_name=names.get(sid, sid),
                total_trades=0, win_rate=0.0, profit_factor=0.0,
                expectancy=0.0, net_pnl=0.0,
                current_weight=current_weight, recommended_weight=current_weight,
                direction="hold", reason="No completed trades yet for this strategy.",
                reliability_warning="No data — weight unchanged.",
            ))
            continue

        wins = [t for t in sid_trades if t["pnl"] > 0]
        losses = [t for t in sid_trades if t["pnl"] < 0]
        win_rate = round(len(wins) / n * 100, 1)
        gross_profit = sum(t["pnl"] for t in wins)
        gross_loss = abs(sum(t["pnl"] for t in losses))
        profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else (99.0 if gross_profit > 0 else 0.0)
        net_pnl = round(sum(t["pnl"] for t in sid_trades), 2)
        expectancy = round(net_pnl / n, 2)

        reliability_warning = None
        if n < MIN_SAMPLE_TRADES:
            reliability_warning = (
                f"Only {n} completed trade(s) — sample size below the {MIN_SAMPLE_TRADES}-trade "
                f"threshold for reliable statistics. Recommendation held at current weight."
            )
            direction = "hold"
            recommended_weight = current_weight
            reason = "Not enough data yet to adjust weight."
        elif win_rate >= 60.0 and profit_factor >= 1.5:
            direction = "increase"
            recommended_weight = round(min(MAX_WEIGHT, current_weight * (1 + WEIGHT_STEP)), 2)
            reason = (
                f"Strong performance: {win_rate:.0f}% win rate, {profit_factor:.2f} profit factor "
                f"over {n} trades. Increasing allocation weight."
            )
        elif win_rate < 45.0 or profit_factor < 1.0:
            direction = "decrease"
            recommended_weight = round(max(MIN_WEIGHT, current_weight * (1 - WEIGHT_STEP)), 2)
            reason = (
                f"Weak performance: {win_rate:.0f}% win rate, {profit_factor:.2f} profit factor "
                f"over {n} trades. Reducing allocation weight."
            )
        else:
            direction = "hold"
            recommended_weight = current_weight
            reason = (
                f"Middling performance: {win_rate:.0f}% win rate, {profit_factor:.2f} profit factor "
                f"over {n} trades. No change recommended."
            )

        if expectancy < 0 and reliability_warning is None:
            reliability_warning = "Negative expectancy per trade — review this strategy's rules before increasing size."

        results.append(StrategyLearning(
            strategy_id=sid, strategy_name=names.get(sid, sid),
            total_trades=n, win_rate=win_rate, profit_factor=profit_factor,
            expectancy=expectancy, net_pnl=net_pnl,
            current_weight=current_weight, recommended_weight=recommended_weight,
            direction=direction, reason=reason,
            reliability_warning=reliability_warning,
        ))

        if persist_weights:
            weights[sid] = recommended_weight

    if persist_weights:
        _save_weights(weights)

    results.sort(key=lambda r: r["total_trades"], reverse=True)

    overall_warning = None
    if len(trades) < MIN_SAMPLE_TRADES:
        overall_warning = (
            f"Only {len(trades)} completed trade(s) across all strategies — the learning engine "
            f"needs at least {MIN_SAMPLE_TRADES} trades per strategy before recommendations are reliable."
        )

    return LearningSummary(
        strategies=results,
        total_trades=len(trades),
        computed_at=datetime.now().isoformat(),
        overall_warning=overall_warning,
    )
