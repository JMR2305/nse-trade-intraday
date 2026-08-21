"""Pure VWAP Pullback, Opening Range Breakout, and EMA Pullback scorers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, Mapping

from .contracts import advisory_output


class AdvisoryStrategy(ABC):
    name = "UNKNOWN"

    @abstractmethod
    def evaluate(
        self,
        symbol: str,
        data: Mapping[str, Any],
        regime: Mapping[str, Any] | None = None,
        **context: Any,
    ) -> Dict[str, Any]:
        raise NotImplementedError

    def _result(
        self,
        symbol: str,
        score: float,
        decision: str,
        reason: str,
        *,
        data_quality: str = "PASS",
        risk_flags: list[str] | None = None,
        **extra: Any,
    ) -> Dict[str, Any]:
        return advisory_output(
            symbol=symbol,
            bot_name="strategy-bot",
            strategy_name=self.name,
            score=score,
            decision=decision,
            reason=reason,
            data_quality=data_quality,
            risk_flags=risk_flags or [],
            **extra,
        )


class VWAPPullbackStrategy(AdvisoryStrategy):
    name = "VWAP_PULLBACK"

    def evaluate(self, symbol: str, data: Mapping[str, Any], regime: Mapping[str, Any] | None = None, **context: Any) -> Dict[str, Any]:
        close, vwap, volume_ratio = _number(data.get("close", data.get("current_price"))), _number(data.get("vwap")), _number(data.get("volume_ratio"))
        if close <= 0 or vwap <= 0:
            return self._result(symbol, 0, "INSUFFICIENT_CONTEXT", "VWAP and price evidence unavailable", data_quality="MISSING")
        if volume_ratio < 1.2:
            return self._result(symbol, 0, "WATCH", "volume confirmation is below the 1.2x threshold", risk_flags=["VOLUME_CONFIRMATION_MISSING"])
        distance_pct = abs(close - vwap) / vwap * 100
        pullback = bool(data.get("pullback_confirmed", distance_pct <= 1.0))
        score = 75 if pullback else 35
        if str((regime or {}).get("regime", "")).upper() == "WEAK":
            score -= 15
        return self._result(
            symbol,
            score,
            "CANDIDATE" if score >= 60 else "WATCH",
            f"price is {distance_pct:.2f}% from VWAP with {volume_ratio:.2f}x volume confirmation"
            if pullback
            else "price is near VWAP but pullback confirmation is incomplete",
            risk_flags=[] if pullback else ["PULLBACK_UNCONFIRMED"],
            distance_from_vwap_pct=round(distance_pct, 3),
            volume_ratio=volume_ratio,
        )


class OpeningRangeBreakoutStrategy(AdvisoryStrategy):
    name = "OPENING_RANGE_BREAKOUT"

    def evaluate(self, symbol: str, data: Mapping[str, Any], regime: Mapping[str, Any] | None = None, **context: Any) -> Dict[str, Any]:
        opening_complete = bool(data.get("opening_range_complete"))
        high, low = _number(data.get("orb_high")), _number(data.get("orb_low"))
        close, volume_ratio = _number(data.get("close", data.get("current_price"))), _number(data.get("volume_ratio"))
        if not opening_complete or high <= 0 or low <= 0 or close <= 0:
            return self._result(symbol, 0, "INSUFFICIENT_CONTEXT", "completed 15/30 minute opening range is unavailable", data_quality="MISSING")
        if volume_ratio < 1.2:
            return self._result(symbol, 0, "WATCH", "opening-range break lacks volume confirmation", risk_flags=["VOLUME_CONFIRMATION_MISSING"])
        broke_range = close > high or close < low
        score = 80 if broke_range else 25
        if str((regime or {}).get("regime", "")).upper() == "VOLATILE":
            score -= 20
        return self._result(
            symbol,
            score,
            "CANDIDATE" if score >= 60 else "WATCH",
            "price broke the completed opening range with volume confirmation"
            if broke_range
            else "price remains inside the completed opening range",
            risk_flags=[] if broke_range else ["RANGE_NOT_BROKEN"],
            opening_range_high=high,
            opening_range_low=low,
            volume_ratio=volume_ratio,
        )


class EMAPullbackStrategy(AdvisoryStrategy):
    name = "EMA_PULLBACK"

    def evaluate(self, symbol: str, data: Mapping[str, Any], regime: Mapping[str, Any] | None = None, **context: Any) -> Dict[str, Any]:
        close = _number(data.get("close", data.get("current_price")))
        ema_fast, ema_slow = _number(data.get("ema_fast")), _number(data.get("ema_slow"))
        if close <= 0 or ema_fast <= 0 or ema_slow <= 0:
            return self._result(symbol, 0, "INSUFFICIENT_CONTEXT", "EMA trend and pullback evidence unavailable", data_quality="MISSING")
        trend_up = ema_fast > ema_slow
        pullback = bool(data.get("pullback_confirmed"))
        if not pullback:
            return self._result(symbol, 0, "WATCH", "EMA trend exists but pullback confirmation is missing", risk_flags=["PULLBACK_UNCONFIRMED"])
        score = 78 if trend_up and close >= ema_slow else 35
        if str((regime or {}).get("regime", "")).upper() in {"WEAK", "VOLATILE"}:
            score -= 15
        return self._result(
            symbol,
            score,
            "CANDIDATE" if score >= 60 else "WATCH",
            "EMA trend and pullback confirmation align"
            if score >= 60
            else "EMA pullback is present but broader regime reduces confidence",
            risk_flags=[] if score >= 60 else ["ADVERSE_REGIME"],
            ema_fast=ema_fast,
            ema_slow=ema_slow,
        )


def default_strategies() -> list[AdvisoryStrategy]:
    return [VWAPPullbackStrategy(), OpeningRangeBreakoutStrategy(), EMAPullbackStrategy()]


def evaluate_strategies(
    symbol: str,
    data: Mapping[str, Any],
    regime: Mapping[str, Any] | None = None,
) -> list[Dict[str, Any]]:
    return [strategy.evaluate(symbol, data, regime) for strategy in default_strategies()]


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0