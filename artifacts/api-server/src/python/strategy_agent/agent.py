"""
agent.py — Phase 10B
Strategy Agent.

Responsibilities:
  - Evaluate every monitored symbol across 6 pluggable strategies
  - Produce per-symbol strategy scores (0–100) with confidence,
    supporting factors, risk flags, strength, and weakness
  - Publish strategy snapshot to SnapshotBus topic "strategy"
  - NEVER generate BUY/SELL signals. NEVER place orders.
  - Future strategies plug in automatically via StrategyRegistry.

Strategies:
  1. Breakout
  2. VWAP Pullback
  3. Opening Range Breakout (ORB)
  4. Momentum
  5. Mean Reversion
  6. Gap Strategy

READ-ONLY · ADVISORY-ONLY
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agent_framework.base_agent import BaseAgent


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe(fn, default=None):
    try:
        return fn()
    except Exception:
        return default


def _f(v) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _clamp(v: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, v))


# ── Strategy base ─────────────────────────────────────────────────────────────

class BaseStrategy(ABC):
    """Abstract strategy. Subclasses implement evaluate()."""

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def evaluate(self, symbol: str, data: Dict[str, Any], regime: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluate the symbol. Returns:
          {score, confidence, supporting_factors, risk_flags, strength, weakness}
        NEVER returns BUY/SELL.
        """
        ...

    @staticmethod
    def _result(symbol: str, strategy: str, score: float, confidence: float,
                supporting: List[str], risk_flags: List[str],
                strength: str, weakness: str) -> Dict[str, Any]:
        return {
            "symbol":             symbol,
            "strategy":           strategy,
            "score":              round(_clamp(score), 1),
            "confidence":         round(_clamp(confidence, 0.0, 1.0), 3),
            "supporting_factors": supporting,
            "risk_flags":         risk_flags,
            "strength":           strength,
            "weakness":           weakness,
            "advisory_only":      True,
            "evaluated_at":       _now_iso(),
        }


# ── Strategy implementations ──────────────────────────────────────────────────

class BreakoutStrategy(BaseStrategy):
    @property
    def name(self) -> str: return "Breakout"

    def evaluate(self, symbol: str, data: Dict, regime: Dict) -> Dict:
        chg = _f(data.get("change_pct")) or 0.0
        vol_ratio = _f(data.get("volume_ratio")) or 1.0
        near_high = bool(data.get("near_52w_high"))
        rsi = _f(data.get("rsi")) or 50.0
        reg = regime.get("regime", "SIDEWAYS")

        score = 0.0
        supporting = []
        risk_flags = []

        if near_high: score += 30; supporting.append("Near 52-week high")
        if chg > 1.5: score += 20; supporting.append(f"Strong move +{chg:.1f}%")
        if vol_ratio > 2.0: score += 20; supporting.append(f"Volume {vol_ratio:.1f}x avg")
        if 50 < rsi < 75: score += 15; supporting.append(f"RSI {rsi:.0f} — healthy momentum")
        if reg in ("BULL", "TRENDING", "BREAKOUT"): score += 15; supporting.append(f"Regime: {reg}")

        if rsi > 80: risk_flags.append("Overbought RSI")
        if vol_ratio < 1.2: risk_flags.append("Low volume confirmation")
        if reg in ("BEAR", "HIGH_VOLATILITY"): risk_flags.append("Adverse regime")

        confidence = _clamp(score / 100, 0, 1)
        strength = "Strong breakout setup" if score > 70 else "Moderate setup"
        weakness = ", ".join(risk_flags) if risk_flags else "No major weaknesses"
        return self._result(symbol, self.name, score, confidence, supporting, risk_flags, strength, weakness)


class VWAPPullbackStrategy(BaseStrategy):
    @property
    def name(self) -> str: return "VWAP Pullback"

    def evaluate(self, symbol: str, data: Dict, regime: Dict) -> Dict:
        vwap_above = bool(data.get("vwap_above"))
        chg = _f(data.get("change_pct")) or 0.0
        rsi = _f(data.get("rsi")) or 50.0
        vol_ratio = _f(data.get("volume_ratio")) or 1.0
        reg = regime.get("regime", "SIDEWAYS")

        score = 0.0
        supporting = []
        risk_flags = []

        if vwap_above: score += 30; supporting.append("Price above VWAP")
        if -1.0 < chg < 0: score += 20; supporting.append("Mild pullback — healthy retracement")
        if 40 < rsi < 60: score += 25; supporting.append(f"RSI {rsi:.0f} — neutral zone")
        if vol_ratio < 1.5: score += 10; supporting.append("Low-volume pullback")
        if reg in ("BULL", "TRENDING"): score += 15; supporting.append(f"Regime: {reg}")

        if not vwap_above: risk_flags.append("Price below VWAP")
        if chg < -2.0: risk_flags.append("Deep pullback — may not recover")
        if vol_ratio > 2.0: risk_flags.append("High-volume decline — possible distribution")

        confidence = _clamp(score / 100, 0, 1)
        strength = "Clean VWAP pullback" if score > 60 else "Weak setup"
        weakness = ", ".join(risk_flags) if risk_flags else "None identified"
        return self._result(symbol, self.name, score, confidence, supporting, risk_flags, strength, weakness)


class ORBStrategy(BaseStrategy):
    @property
    def name(self) -> str: return "Opening Range Breakout"

    def evaluate(self, symbol: str, data: Dict, regime: Dict) -> Dict:
        chg = _f(data.get("change_pct")) or 0.0
        vol_ratio = _f(data.get("volume_ratio")) or 1.0
        rsi = _f(data.get("rsi")) or 50.0
        reg = regime.get("regime", "SIDEWAYS")
        session = regime.get("session_phase", "OPEN")

        score = 0.0
        supporting = []
        risk_flags = []

        # ORB is most relevant in morning session
        if session in ("OPEN", "PRE_OPEN"):
            score += 20; supporting.append("Morning session active")
        if abs(chg) > 0.5: score += 25; supporting.append(f"Range breakout {chg:.1f}%")
        if vol_ratio > 1.5: score += 25; supporting.append(f"Volume {vol_ratio:.1f}x confirms break")
        if 45 < rsi < 65: score += 15; supporting.append("RSI in momentum zone")
        if reg not in ("BEAR", "HIGH_VOLATILITY"): score += 15; supporting.append("Regime supports trend")

        if session == "CLOSED": risk_flags.append("Market closed — ORB not applicable")
        if vol_ratio < 1.0: risk_flags.append("Below-average volume")
        if reg == "HIGH_VOLATILITY": risk_flags.append("High volatility increases false breakouts")

        confidence = _clamp(score / 100, 0, 1)
        strength = "Strong ORB setup" if score > 65 else "Moderate ORB"
        weakness = ", ".join(risk_flags) if risk_flags else "None"
        return self._result(symbol, self.name, score, confidence, supporting, risk_flags, strength, weakness)


class MomentumStrategy(BaseStrategy):
    @property
    def name(self) -> str: return "Momentum"

    def evaluate(self, symbol: str, data: Dict, regime: Dict) -> Dict:
        chg = _f(data.get("change_pct")) or 0.0
        rsi = _f(data.get("rsi")) or 50.0
        vol_ratio = _f(data.get("volume_ratio")) or 1.0
        score_val = _f(data.get("score")) or 50.0
        reg = regime.get("regime", "SIDEWAYS")

        score = 0.0
        supporting = []
        risk_flags = []

        if chg > 1.0: score += 25; supporting.append(f"Strong move +{chg:.1f}%")
        if rsi > 55: score += 20; supporting.append(f"RSI {rsi:.0f} — bullish momentum")
        if vol_ratio > 1.5: score += 20; supporting.append(f"Volume {vol_ratio:.1f}x average")
        if score_val > 60: score += 20; supporting.append(f"High composite score {score_val:.0f}")
        if reg in ("BULL", "TRENDING", "BREAKOUT"): score += 15; supporting.append(f"Regime: {reg}")

        if rsi > 80: risk_flags.append("Overbought — pullback risk")
        if chg < 0: risk_flags.append("Negative momentum")
        if reg in ("BEAR", "HIGH_VOLATILITY"): risk_flags.append("Adverse regime")

        confidence = _clamp(score / 100, 0, 1)
        strength = "Strong momentum" if score > 70 else "Moderate"
        weakness = ", ".join(risk_flags) if risk_flags else "None"
        return self._result(symbol, self.name, score, confidence, supporting, risk_flags, strength, weakness)


class MeanReversionStrategy(BaseStrategy):
    @property
    def name(self) -> str: return "Mean Reversion"

    def evaluate(self, symbol: str, data: Dict, regime: Dict) -> Dict:
        chg = _f(data.get("change_pct")) or 0.0
        rsi = _f(data.get("rsi")) or 50.0
        near_low = bool(data.get("near_52w_low"))
        vol_ratio = _f(data.get("volume_ratio")) or 1.0
        reg = regime.get("regime", "SIDEWAYS")

        score = 0.0
        supporting = []
        risk_flags = []

        if chg < -2.0: score += 25; supporting.append(f"Oversold move {chg:.1f}%")
        if rsi < 35: score += 25; supporting.append(f"RSI {rsi:.0f} — oversold")
        if near_low: score += 20; supporting.append("Near 52-week low — potential floor")
        if vol_ratio > 1.5: score += 15; supporting.append("Volume spike at extremes")
        if reg in ("SIDEWAYS", "LOW_VOLATILITY"): score += 15; supporting.append(f"Regime: {reg}")

        if reg in ("BEAR",): risk_flags.append("Bear regime — mean may not hold")
        if rsi < 20: risk_flags.append("Extremely oversold — knife-catching risk")
        if vol_ratio < 0.8: risk_flags.append("Low volume — weak conviction")

        confidence = _clamp(score / 100, 0, 1)
        strength = "Strong reversion candidate" if score > 65 else "Moderate"
        weakness = ", ".join(risk_flags) if risk_flags else "None"
        return self._result(symbol, self.name, score, confidence, supporting, risk_flags, strength, weakness)


class GapStrategy(BaseStrategy):
    @property
    def name(self) -> str: return "Gap Strategy"

    def evaluate(self, symbol: str, data: Dict, regime: Dict) -> Dict:
        chg = _f(data.get("change_pct")) or 0.0
        vol_ratio = _f(data.get("volume_ratio")) or 1.0
        rsi = _f(data.get("rsi")) or 50.0
        reg = regime.get("regime", "SIDEWAYS")

        score = 0.0
        supporting = []
        risk_flags = []

        if abs(chg) > 2.0: score += 30; supporting.append(f"Gap {chg:.1f}%")
        if abs(chg) > 3.0: score += 10; supporting.append("Large gap — high probability fill")
        if vol_ratio > 2.0: score += 25; supporting.append(f"Volume {vol_ratio:.1f}x confirms gap")
        if 35 < rsi < 65: score += 20; supporting.append("RSI neutral — gap fill space")
        if reg not in ("HIGH_VOLATILITY",): score += 15; supporting.append("Stable regime")

        if abs(chg) < 1.0: risk_flags.append("Small gap — limited opportunity")
        if vol_ratio < 1.0: risk_flags.append("Low volume gap — may not fill")
        if reg == "HIGH_VOLATILITY": risk_flags.append("High volatility — gap may extend")

        confidence = _clamp(score / 100, 0, 1)
        strength = "Strong gap setup" if score > 65 else "Moderate"
        weakness = ", ".join(risk_flags) if risk_flags else "None"
        return self._result(symbol, self.name, score, confidence, supporting, risk_flags, strength, weakness)


# ── Strategy Registry ─────────────────────────────────────────────────────────

class StrategyRegistry:
    """
    Pluggable registry. Future strategies are added without architectural change.
    """
    def __init__(self) -> None:
        self._strategies: Dict[str, BaseStrategy] = {}

    def register(self, strategy: BaseStrategy) -> None:
        self._strategies[strategy.name] = strategy

    def all(self) -> List[BaseStrategy]:
        return list(self._strategies.values())

    def get(self, name: str) -> Optional[BaseStrategy]:
        return self._strategies.get(name)


def _default_registry() -> StrategyRegistry:
    reg = StrategyRegistry()
    for s in [BreakoutStrategy(), VWAPPullbackStrategy(), ORBStrategy(),
              MomentumStrategy(), MeanReversionStrategy(), GapStrategy()]:
        reg.register(s)
    return reg


# ── Strategy Agent ────────────────────────────────────────────────────────────

class StrategyAgent(BaseAgent):
    """
    Evaluates monitored symbols across 6 pluggable strategies.
    Produces strategy scores and confidence metrics.
    NEVER generates BUY/SELL. NEVER places orders.

    READ-ONLY · ADVISORY-ONLY
    """

    HEARTBEAT_INTERVAL_S: float = 60.0

    def __init__(self) -> None:
        super().__init__(
            agent_id="strategy-agent",
            name="Strategy Agent",
            version="1.0.0",
            owner="ApexQuant AI",
            priority=3,
            dependencies=["market-intelligence-agent", "stock-monitoring-agent"],
            capabilities=[
                "breakout_strategy", "vwap_pullback", "orb_strategy",
                "momentum_strategy", "mean_reversion", "gap_strategy",
                "strategy_scoring", "confidence_estimation",
            ],
        )
        self._registry = _default_registry()
        self._last_snapshot: Optional[Dict[str, Any]] = None

    @property
    def default_topic(self) -> str:
        return "strategy"

    def execute_task(self) -> Optional[Dict[str, Any]]:
        start_ms = time.monotonic() * 1000

        # Load scan items + regime
        scan_items = _safe(self._load_scan_items) or []
        regime     = _safe(self._load_regime)     or {}

        # Build sym_map
        sym_map: Dict[str, Dict] = {}
        for item in scan_items:
            if isinstance(item, dict):
                sym = item.get("symbol") or item.get("Symbol")
                if sym:
                    sym_map[sym] = item

        # Evaluate top-60 symbols across all strategies
        symbols = list(sym_map.keys())[:60]
        all_results: List[Dict[str, Any]] = []
        strategy_names = [s.name for s in self._registry.all()]

        for sym in symbols:
            data = sym_map[sym]
            sym_results = []
            for strategy in self._registry.all():
                res = _safe(lambda s=strategy, d=data, r=regime: s.evaluate(sym, d, r))
                if res:
                    sym_results.append(res)
            if sym_results:
                # Best strategy for this symbol
                best = max(sym_results, key=lambda r: r["score"])
                all_results.append({
                    "symbol":          sym,
                    "best_strategy":   best["strategy"],
                    "best_score":      best["score"],
                    "best_confidence": best["confidence"],
                    "all_strategies":  sym_results,
                    "advisory_only":   True,
                })

        # Top setups by score
        top_setups = sorted(all_results, key=lambda r: r["best_score"], reverse=True)[:20]

        elapsed_ms = round((time.monotonic() * 1000) - start_ms, 1)

        payload = {
            "agent_id":   "strategy-agent",
            "agent_name": "Strategy Agent",
            "advisory_only": True,
            "read_only":     True,

            "strategies_registered": len(strategy_names),
            "strategy_names":        strategy_names,
            "symbols_evaluated":     len(all_results),
            "total_evaluations":     len(all_results) * len(strategy_names),

            # Top setups
            "top_setups":            top_setups[:10],
            "top_strategy":          top_setups[0]["best_strategy"] if top_setups else None,
            "highest_score":         top_setups[0]["best_score"] if top_setups else 0.0,
            "highest_confidence":    top_setups[0]["best_confidence"] if top_setups else 0.0,
            "highest_confidence_symbol": top_setups[0]["symbol"] if top_setups else None,

            # Per-strategy breakdown
            "strategy_breakdown":    self._strategy_breakdown(all_results, strategy_names),

            "evaluation_latency_ms": elapsed_ms,
            "generated_at":          _now_iso(),
        }
        self._last_snapshot = payload
        return payload

    # ── Data loaders ──────────────────────────────────────────────────────────

    @staticmethod
    def _load_scan_items() -> List[Any]:
        from scan_state_store import load_latest_snapshot
        snap = load_latest_snapshot() or {}
        return snap.get("items") or snap.get("watchlist") or []

    @staticmethod
    def _load_regime() -> Dict[str, Any]:
        from market_intelligence_hub.shared_services import _get_regime
        return _get_regime()

    @staticmethod
    def _strategy_breakdown(results: List[Dict], strategy_names: List[str]) -> Dict[str, Any]:
        from collections import Counter
        best_counts = Counter(r["best_strategy"] for r in results)
        avg_scores: Dict[str, List[float]] = {n: [] for n in strategy_names}
        for r in results:
            for sr in r.get("all_strategies", []):
                sn = sr.get("strategy")
                if sn in avg_scores:
                    avg_scores[sn].append(sr["score"])
        return {
            name: {
                "times_best": best_counts.get(name, 0),
                "avg_score": round(sum(avg_scores[name]) / len(avg_scores[name]), 1)
                             if avg_scores[name] else 0.0,
            }
            for name in strategy_names
        }

    def evaluate_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Evaluate a single symbol across all strategies."""
        scan_items = _safe(self._load_scan_items) or []
        regime = _safe(self._load_regime) or {}
        sym_map: Dict[str, Dict] = {}
        for item in scan_items:
            if isinstance(item, dict):
                sym = item.get("symbol") or item.get("Symbol")
                if sym:
                    sym_map[sym] = item

        data = sym_map.get(symbol) or {}
        results = []
        for strategy in self._registry.all():
            res = _safe(lambda s=strategy: s.evaluate(symbol, data, regime))
            if res:
                results.append(res)
        if not results:
            return None
        best = max(results, key=lambda r: r["score"])
        return {
            "symbol":          symbol,
            "best_strategy":   best["strategy"],
            "best_score":      best["score"],
            "best_confidence": best["confidence"],
            "all_strategies":  results,
            "advisory_only":   True,
            "evaluated_at":    _now_iso(),
        }

    def last_snapshot(self) -> Optional[Dict[str, Any]]:
        return self._last_snapshot
