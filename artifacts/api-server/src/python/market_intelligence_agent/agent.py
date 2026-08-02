"""
agent.py — Phase 10B
Market Intelligence Agent.

Responsibilities:
  - Consume market_data and research snapshots from SnapshotBus
  - Call market_intelligence_hub for regime, trend strength, sector rotation,
    breadth, volatility, momentum, gap analysis, data freshness, session info
  - Publish market_intelligence snapshot to SnapshotBus topic "market_intelligence"
  - NEVER recommend trades. NEVER modify portfolio or orders.

READ-ONLY · ADVISORY-ONLY
"""
from __future__ import annotations

import time
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


class MarketIntelligenceAgent(BaseAgent):
    """
    Analytical agent that determines market regime, sector rotation,
    breadth, volatility, and momentum state from existing infrastructure.

    READ-ONLY: reads from market_intelligence_hub and SnapshotBus only.
    ADVISORY-ONLY: publishes intelligence snapshots; never places orders.
    """

    HEARTBEAT_INTERVAL_S: float = 60.0

    def __init__(self) -> None:
        super().__init__(
            agent_id="market-intelligence-agent",
            name="Market Intelligence Agent",
            version="1.0.0",
            owner="ApexQuant AI",
            priority=2,
            dependencies=["market-data-agent"],
            capabilities=[
                "market_regime", "trend_strength", "sector_rotation",
                "sector_leadership", "market_breadth", "volatility_regime",
                "liquidity", "momentum_state", "gap_analysis",
                "data_freshness", "trading_session",
            ],
        )
        self._last_snapshot: Optional[Dict[str, Any]] = None
        # Subscribe to upstream bus topics
        from agent_framework.snapshot_bus import SnapshotBus
        bus = SnapshotBus.instance()
        bus.subscribe("market_data", self._on_market_data)
        bus.subscribe("research", self._on_research)
        self._latest_market_data: Optional[Dict[str, Any]] = None
        self._latest_research: Optional[Dict[str, Any]] = None

    @property
    def default_topic(self) -> str:
        return "market_intelligence"

    # ── Bus callbacks ─────────────────────────────────────────────────────────

    def _on_market_data(self, envelope) -> None:
        self._latest_market_data = envelope.payload

    def _on_research(self, envelope) -> None:
        self._latest_research = envelope.payload

    # ── Main task ─────────────────────────────────────────────────────────────

    def execute_task(self) -> Optional[Dict[str, Any]]:
        start_ms = time.monotonic() * 1000

        # Pull upstream snapshots from bus (non-blocking)
        from agent_framework.snapshot_bus import SnapshotBus
        bus = SnapshotBus.instance()
        md_env = bus.latest("market_data")
        res_env = bus.latest("research")
        market_data = (md_env.payload if md_env else None) or self._latest_market_data or {}
        research = (res_env.payload if res_env else None) or self._latest_research or {}

        # Pull intelligence from hub modules
        regime = _safe(self._load_regime) or {}
        sectors = _safe(self._load_sectors) or {}
        breadth = _safe(self._load_breadth) or {}
        volatility = _safe(self._load_volatility) or {}
        overview = _safe(self._load_overview) or {}

        payload = self._build_snapshot(
            market_data, research, regime, sectors, breadth, volatility, overview
        )
        payload["evaluation_latency_ms"] = round((time.monotonic() * 1000) - start_ms, 1)
        self._last_snapshot = payload
        return payload

    # ── Data loading (all read-only) ──────────────────────────────────────────

    @staticmethod
    def _load_regime() -> Dict[str, Any]:
        from market_intelligence_hub.shared_services import _get_regime
        return _get_regime()

    @staticmethod
    def _load_sectors() -> Dict[str, Any]:
        from market_intelligence_hub.shared_services import _get_scan_items, _analyse_sectors
        items = _get_scan_items()
        return _analyse_sectors(items)

    @staticmethod
    def _load_breadth() -> Dict[str, Any]:
        from market_intelligence_hub.shared_services import (
            _get_scan_items, _get_regime, _analyse_breadth
        )
        items = _get_scan_items()
        regime = _get_regime()
        return _analyse_breadth(items, regime)

    @staticmethod
    def _load_volatility() -> Dict[str, Any]:
        from market_intelligence_hub.shared_services import (
            _get_scan_items, _get_regime, _analyse_volatility
        )
        items = _get_scan_items()
        regime = _get_regime()
        return _analyse_volatility(items, regime)

    @staticmethod
    def _load_overview() -> Dict[str, Any]:
        from market_intelligence_hub.shared_services import get_overview
        return get_overview()

    # ── Snapshot builder ──────────────────────────────────────────────────────

    def _build_snapshot(
        self,
        market_data: Dict[str, Any],
        research: Dict[str, Any],
        regime: Dict[str, Any],
        sectors: Dict[str, Any],
        breadth: Dict[str, Any],
        volatility: Dict[str, Any],
        overview: Dict[str, Any],
    ) -> Dict[str, Any]:

        # Momentum state derived from regime + breadth
        momentum_state = self._derive_momentum(regime, breadth)

        # Gap analysis from market data
        gap_analysis = self._derive_gap(market_data)

        # Session info
        session_info = self._derive_session()

        # Liquidity proxy from breadth + volume
        liquidity_score = self._derive_liquidity(breadth, market_data)

        # Data freshness
        freshness_s = market_data.get("data_freshness_s")
        data_quality = "FRESH" if (freshness_s is not None and freshness_s < 3600) else (
            "STALE" if freshness_s is not None else "UNKNOWN"
        )

        # Sector rotation: strongest → weakest movement
        rotation_leaders = sectors.get("rotation_leaders") or []
        rotation_laggards = sectors.get("rotation_laggards") or []

        return {
            # Metadata
            "agent_id":   "market-intelligence-agent",
            "agent_name": "Market Intelligence Agent",
            "advisory_only": True,
            "read_only":     True,

            # Market Regime
            "market_regime":      regime.get("regime", "UNKNOWN"),
            "sub_regime":         regime.get("sub_regime", "NORMAL"),
            "regime_confidence":  _f(regime.get("confidence")) or 50.0,
            "regime_description": regime.get("description", ""),

            # Trend Strength
            "trend_strength":     _f(regime.get("trend_strength")) or 0.0,
            "nifty_trend":        regime.get("nifty_trend", "SIDEWAYS"),
            "banknifty_trend":    regime.get("banknifty_trend", "SIDEWAYS"),
            "nifty_change_pct":   _f(regime.get("nifty_change_pct")) or 0.0,
            "banknifty_change_pct": _f(regime.get("banknifty_change_pct")) or 0.0,

            # Sector Rotation
            "strongest_sector":   sectors.get("strongest_sector", "N/A"),
            "weakest_sector":     sectors.get("weakest_sector", "N/A"),
            "leadership_sector":  sectors.get("leadership_sector", "N/A"),
            "sector_count":       int(sectors.get("total_sectors") or 0),
            "avg_sector_strength": _f(sectors.get("avg_sector_strength")) or 0.0,
            "rotation_leaders":   rotation_leaders[:5],
            "rotation_laggards":  rotation_laggards[:5],

            # Market Breadth
            "breadth_score":          _f(breadth.get("breadth_score")) or 50.0,
            "breadth_status":         breadth.get("breadth_status", "NEUTRAL"),
            "advancers":              int(breadth.get("advancers") or 0),
            "decliners":              int(breadth.get("decliners") or 0),
            "advance_decline_ratio":  _f(breadth.get("advance_decline_ratio")) or 1.0,
            "new_highs":              int(breadth.get("new_highs") or 0),
            "new_lows":               int(breadth.get("new_lows") or 0),
            "sector_participation":   _f(breadth.get("sector_participation")) or 0.0,

            # Volatility Regime
            "volatility_regime":  volatility.get("volatility_regime", "NORMAL_VOLATILITY"),
            "volatility_score":   _f(volatility.get("volatility_score")) or 55.0,
            "vix_value":          _f(regime.get("vix_value")) or 18.0,
            "vix_status":         regime.get("vix_status", "MODERATE"),
            "atr_avg":            _f(volatility.get("atr_avg")) or 0.0,
            "high_volatility":    bool(regime.get("high_volatility", False)),

            # Liquidity
            "liquidity_score":    liquidity_score,
            "liquidity_status":   "HIGH" if liquidity_score > 70 else ("LOW" if liquidity_score < 40 else "MODERATE"),

            # Momentum State
            "momentum_state":     momentum_state,

            # Gap Analysis
            "gap_analysis":       gap_analysis,

            # Data Freshness
            "data_freshness_s":   freshness_s,
            "data_quality":       data_quality,

            # Trading Session
            "session_info":       session_info,

            # Research context
            "macro_regime":       research.get("macro_regime", "UNKNOWN"),
            "rbi_stance":         research.get("rbi_policy_stance", "UNKNOWN"),
            "global_risk_score":  _f(research.get("global_risk_score")) or 0.0,

            # Generated
            "generated_at": _now_iso(),
        }

    # ── Derived metrics ───────────────────────────────────────────────────────

    @staticmethod
    def _derive_momentum(regime: Dict, breadth: Dict) -> str:
        trend_strength = _f(regime.get("trend_strength")) or 0.0
        breadth_score = _f(breadth.get("breadth_score")) or 50.0
        adv = int(breadth.get("advancers") or 0)
        dec = int(breadth.get("decliners") or 0)
        net_breadth = adv - dec

        if trend_strength > 60 and net_breadth > 10:
            return "STRONG_BULLISH"
        if trend_strength > 40 and net_breadth > 0:
            return "BULLISH"
        if trend_strength > 60 and net_breadth < -10:
            return "STRONG_BEARISH"
        if trend_strength > 40 and net_breadth < 0:
            return "BEARISH"
        if breadth_score > 60:
            return "IMPROVING"
        if breadth_score < 40:
            return "DETERIORATING"
        return "NEUTRAL"

    @staticmethod
    def _derive_gap(market_data: Dict) -> Dict[str, Any]:
        nifty_chg = _f(market_data.get("nifty50_change_pct")) or 0.0
        return {
            "nifty_gap_pct": round(nifty_chg, 4),
            "gap_direction": "UP" if nifty_chg > 0.3 else ("DOWN" if nifty_chg < -0.3 else "FLAT"),
            "gap_magnitude": "LARGE" if abs(nifty_chg) > 1.0 else (
                "MEDIUM" if abs(nifty_chg) > 0.3 else "SMALL"
            ),
            "gap_risk": abs(nifty_chg) > 0.5,
        }

    @staticmethod
    def _derive_session() -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        # IST = UTC+5:30
        ist_hour = (now.hour + 5) % 24
        ist_minute = (now.minute + 30) % 60
        if ist_hour >= 5 and ist_hour < 6:
            ist_hour += 1 if ist_minute >= 30 else 0
        ist_time = f"{ist_hour:02d}:{now.minute:02d}"
        # Market hours: 9:15 – 15:30 IST
        h, m = ist_hour, now.minute
        in_session = (h == 9 and m >= 15) or (10 <= h <= 14) or (h == 15 and m <= 30)
        pre_open = h == 9 and m < 15
        phase = "PRE_OPEN" if pre_open else ("OPEN" if in_session else "CLOSED")
        return {
            "phase": phase,
            "in_session": in_session,
            "ist_time": ist_time,
        }

    @staticmethod
    def _derive_liquidity(breadth: Dict, market_data: Dict) -> float:
        adv = int(breadth.get("advancers") or 0)
        dec = int(breadth.get("decliners") or 0)
        total = adv + dec
        if total == 0:
            return 50.0
        participation = total / max(50, total)
        coverage = _f(market_data.get("coverage_pct")) or 50.0
        return round(min(100.0, (participation * 50 + coverage * 0.5)), 1)

    def last_snapshot(self) -> Optional[Dict[str, Any]]:
        return self._last_snapshot
