"""Phase 7.5 – Parameter experiment simulator (advisory-only, simulation only)."""
from __future__ import annotations
import uuid
from typing import Any, Dict, List

from .models import ParameterExperiment

# Default parameter baselines
_BASELINES: Dict[str, float] = {
    "confidence_threshold":  0.60,   # minimum confidence to generate a signal
    "rsi_buy_zone_low":      45.0,   # RSI lower bound for buy zone
    "rsi_buy_zone_high":     65.0,   # RSI upper bound for buy zone
    "ema_fast_period":       9.0,
    "ema_slow_period":       20.0,
    "stop_loss_pct":         2.0,    # %
    "target_pct":            3.0,    # %
    "min_volume_multiplier": 1.5,    # volume vs 20-period average
    "max_risk_per_trade":    2.0,    # % of capital
    "ranking_weight_trend":  0.40,
}

# Simulated test variants for each parameter
_VARIANTS: Dict[str, List[float]] = {
    "confidence_threshold":  [0.50, 0.55, 0.65, 0.70],
    "rsi_buy_zone_low":      [40.0, 50.0, 55.0],
    "rsi_buy_zone_high":     [60.0, 70.0, 75.0],
    "stop_loss_pct":         [1.5, 2.5, 3.0],
    "target_pct":            [2.5, 4.0, 5.0],
    "min_volume_multiplier": [1.2, 1.8, 2.0],
    "max_risk_per_trade":    [1.5, 2.5, 3.0],
    "ranking_weight_trend":  [0.30, 0.50, 0.60],
}

# Impact heuristics: expected delta in signal_count, confidence, win_rate, risk
_IMPACT: Dict[str, Dict[str, Any]] = {
    "confidence_threshold": {
        "higher": {"signal_delta": -3, "conf_delta": +5.0, "win_delta": +0.03, "risk_delta": -0.5},
        "lower":  {"signal_delta": +4, "conf_delta": -4.0, "win_delta": -0.02, "risk_delta": +0.8},
    },
    "rsi_buy_zone_low": {
        "higher": {"signal_delta": -2, "conf_delta": +2.0, "win_delta": +0.01, "risk_delta": -0.2},
        "lower":  {"signal_delta": +2, "conf_delta": -1.5, "win_delta": -0.01, "risk_delta": +0.3},
    },
    "stop_loss_pct": {
        "higher": {"signal_delta": 0,  "conf_delta":  0.0, "win_delta": -0.02, "risk_delta": +1.0},
        "lower":  {"signal_delta": 0,  "conf_delta":  0.0, "win_delta": +0.01, "risk_delta": -0.5},
    },
    "target_pct": {
        "higher": {"signal_delta": 0,  "conf_delta": +1.0, "win_delta": -0.03, "risk_delta":  0.0},
        "lower":  {"signal_delta": 0,  "conf_delta": -1.0, "win_delta": +0.04, "risk_delta":  0.0},
    },
    "min_volume_multiplier": {
        "higher": {"signal_delta": -2, "conf_delta": +3.0, "win_delta": +0.02, "risk_delta": -0.3},
        "lower":  {"signal_delta": +3, "conf_delta": -2.0, "win_delta": -0.01, "risk_delta": +0.4},
    },
}


def _impact_label(conf_delta: float, win_delta: float, risk_delta: float) -> str:
    score = conf_delta * 0.5 + win_delta * 100 * 0.3 - risk_delta * 0.2
    if score > 2:   return "IMPROVED"
    if score < -2:  return "DEGRADED"
    return "NEUTRAL"


def run_parameter_experiments(
    signals: List[Dict[str, Any]],
) -> List[ParameterExperiment]:
    """Generate advisory parameter experiment results for key parameters."""
    total = max(len(signals), 1)
    results: List[ParameterExperiment] = []

    for param, variants in _VARIANTS.items():
        baseline = _BASELINES.get(param, 1.0)
        impact_meta = _IMPACT.get(param, {})

        for variant in variants:
            direction = "higher" if variant > baseline else "lower"
            imp = impact_meta.get(direction, {"signal_delta": 0, "conf_delta": 0.0, "win_delta": 0.0, "risk_delta": 0.0})

            sig_delta  = imp["signal_delta"]
            conf_delta = imp["conf_delta"]
            win_delta  = imp["win_delta"]
            risk_delta = imp["risk_delta"]

            label = _impact_label(conf_delta, win_delta, risk_delta)

            narrative = (
                f"Setting {param.replace('_', ' ')} to {variant} (from baseline {baseline}) "
                f"is expected to {label.lower()} performance: "
                f"signal count {'+' if sig_delta >= 0 else ''}{sig_delta}, "
                f"confidence {'+' if conf_delta >= 0 else ''}{conf_delta:.1f}%, "
                f"win rate {'+' if win_delta >= 0 else ''}{win_delta*100:.1f}pp. "
                f"This is an advisory simulation only."
            )

            results.append(ParameterExperiment(
                experiment_id=str(uuid.uuid4())[:8],
                parameter_name=param,
                baseline_value=baseline,
                test_value=variant,
                impact_label=label,
                signal_count_delta=sig_delta,
                confidence_delta=round(conf_delta, 2),
                win_rate_delta=round(win_delta, 4),
                risk_delta=round(risk_delta, 2),
                narrative=narrative,
            ))

    return results
