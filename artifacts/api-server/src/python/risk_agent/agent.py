"""
agent.py — Phase 10B
Risk Agent.

Responsibilities:
  - Read portfolio state, market intelligence, and strategy snapshots
  - Evaluate 9 risk dimensions:
      1. Portfolio Exposure
      2. Position Sizing
      3. Sector Concentration
      4. Correlation
      5. Portfolio Heat
      6. Daily Risk
      7. Capital Utilisation
      8. Maximum Drawdown
      9. Tail Risk
  - Determine overall Risk Level (LOW / MODERATE / HIGH / CRITICAL)
  - Publish risk snapshot to SnapshotBus topic "risk"
  - NEVER modify portfolio, orders, or strategies.

READ-ONLY · ADVISORY-ONLY
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from agent_framework.base_agent import BaseAgent

def _default_capital() -> float:
    """Configured paper capital — single source of truth (portfolio_store)."""
    try:
        from portfolio_store import INITIAL_CAPITAL
        return float(INITIAL_CAPITAL)
    except Exception:
        return 50_000.0



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


class RiskAgent(BaseAgent):
    """
    Evaluates portfolio risk across 9 dimensions.
    Publishes risk snapshots. Never modifies portfolio.

    READ-ONLY · ADVISORY-ONLY
    """

    HEARTBEAT_INTERVAL_S: float = 60.0

    def __init__(self) -> None:
        super().__init__(
            agent_id="risk-agent",
            name="Risk Agent",
            version="1.0.0",
            owner="ApexQuant AI",
            priority=2,
            dependencies=["market-intelligence-agent", "strategy-agent"],
            capabilities=[
                "portfolio_exposure", "position_sizing", "sector_concentration",
                "correlation_analysis", "portfolio_heat", "daily_risk",
                "capital_utilisation", "max_drawdown", "tail_risk",
            ],
        )
        self._last_snapshot: Optional[Dict[str, Any]] = None

    @property
    def default_topic(self) -> str:
        return "risk"

    def execute_task(self) -> Optional[Dict[str, Any]]:
        start_ms = time.monotonic() * 1000

        # Load data sources (all read-only)
        portfolio = _safe(self._load_portfolio) or {}
        mi_snap   = _safe(self._load_market_intelligence) or {}
        strategy_snap = _safe(self._load_strategy_snapshot) or {}
        trades    = _safe(self._load_trades) or []

        # Compute 9 risk dimensions
        exposure    = self._calc_exposure(portfolio)
        sizing      = self._calc_sizing(portfolio)
        sector_conc = self._calc_sector_concentration(portfolio)
        correlation = self._calc_correlation(portfolio, mi_snap)
        heat        = self._calc_portfolio_heat(portfolio, exposure)
        daily_risk  = self._calc_daily_risk(trades, portfolio)
        capital_util= self._calc_capital_utilisation(portfolio)
        drawdown    = self._calc_drawdown(trades)
        tail_risk   = self._calc_tail_risk(mi_snap, exposure)

        # Aggregate risk level
        risk_level, risk_score, risk_breakdown = self._aggregate_risk(
            exposure, sizing, sector_conc, correlation, heat,
            daily_risk, capital_util, drawdown, tail_risk
        )

        elapsed_ms = round((time.monotonic() * 1000) - start_ms, 1)

        payload = {
            "agent_id":   "risk-agent",
            "agent_name": "Risk Agent",
            "advisory_only": True,
            "read_only":     True,
            "never_modifies_portfolio": True,

            # Overall risk
            "risk_level":  risk_level,
            "risk_score":  round(risk_score, 1),
            "risk_grade":  self._grade(risk_score),

            # 9 Risk dimensions
            "exposure":            exposure,
            "position_sizing":     sizing,
            "sector_concentration":sector_conc,
            "correlation":         correlation,
            "portfolio_heat":      heat,
            "daily_risk":          daily_risk,
            "capital_utilisation": capital_util,
            "max_drawdown":        drawdown,
            "tail_risk":           tail_risk,

            # Breakdown
            "risk_breakdown": risk_breakdown,

            # Context
            "regime":          mi_snap.get("market_regime", "UNKNOWN"),
            "volatility_regime": mi_snap.get("volatility_regime", "NORMAL_VOLATILITY"),
            "top_strategy":    strategy_snap.get("top_strategy"),

            "evaluation_latency_ms": elapsed_ms,
            "generated_at": _now_iso(),
        }
        self._last_snapshot = payload
        return payload

    # ── Data loaders (all read-only) ──────────────────────────────────────────

    @staticmethod
    def _load_portfolio() -> Dict[str, Any]:
        from portfolio_store import load_state
        return load_state() or {}

    @staticmethod
    def _load_market_intelligence() -> Dict[str, Any]:
        from agent_framework.snapshot_bus import SnapshotBus
        bus = SnapshotBus.instance()
        env = bus.latest("market_intelligence")
        if env and env.payload:
            return env.payload
        # Fallback to hub
        from market_intelligence_hub.shared_services import _get_regime
        regime = _safe(_get_regime) or {}
        return {"market_regime": regime.get("regime", "UNKNOWN"),
                "volatility_regime": "NORMAL_VOLATILITY",
                "vix_value": regime.get("vix_value", 18.0)}

    @staticmethod
    def _load_strategy_snapshot() -> Dict[str, Any]:
        from agent_framework.snapshot_bus import SnapshotBus
        bus = SnapshotBus.instance()
        env = bus.latest("strategy")
        return env.payload if env else {}

    @staticmethod
    def _load_trades() -> List[Dict[str, Any]]:
        try:
            from portfolio_store import load_all_trades_any
            return load_all_trades_any() or []
        except Exception:
            return []

    # ── Risk dimension calculators ────────────────────────────────────────────

    @staticmethod
    def _calc_exposure(portfolio: Dict) -> Dict[str, Any]:
        positions = portfolio.get("positions") or []
        capital = _f(portfolio.get("capital")) or _default_capital()
        invested = sum(
            (_f(p.get("current_value")) or (_f(p.get("qty")) or 0) * (_f(p.get("avg_price")) or 0))
            for p in positions
        )
        pct = round((invested / capital * 100), 1) if capital > 0 else 0.0
        return {
            "total_invested": round(invested, 2),
            "capital":        round(capital, 2),
            "exposure_pct":   pct,
            "position_count": len(positions),
            "risk_flag":      pct > 80,
            "note":           f"{pct:.1f}% of capital deployed",
        }

    @staticmethod
    def _calc_sizing(portfolio: Dict) -> Dict[str, Any]:
        positions = portfolio.get("positions") or []
        capital = _f(portfolio.get("capital")) or _default_capital()
        sizes = []
        oversized = []
        for p in positions:
            val = (_f(p.get("current_value")) or
                   (_f(p.get("qty")) or 0) * (_f(p.get("avg_price")) or 0))
            pct = (val / capital * 100) if capital > 0 else 0.0
            sizes.append(pct)
            if pct > 20:
                oversized.append({"symbol": p.get("symbol"), "pct": round(pct, 1)})
        avg_size = round(sum(sizes) / len(sizes), 1) if sizes else 0.0
        max_size = round(max(sizes), 1) if sizes else 0.0
        return {
            "avg_position_pct": avg_size,
            "max_position_pct": max_size,
            "oversized_positions": oversized,
            "risk_flag": bool(oversized),
            "note": f"Max single position: {max_size:.1f}%",
        }

    @staticmethod
    def _calc_sector_concentration(portfolio: Dict) -> Dict[str, Any]:
        positions = portfolio.get("positions") or []
        capital = _f(portfolio.get("capital")) or _default_capital()
        sector_map: Dict[str, float] = {}
        for p in positions:
            sector = p.get("sector") or "Unknown"
            val = (_f(p.get("current_value")) or
                   (_f(p.get("qty")) or 0) * (_f(p.get("avg_price")) or 0))
            sector_map[sector] = sector_map.get(sector, 0.0) + val
        total = sum(sector_map.values())
        sector_pcts = {k: round(v / capital * 100, 1) for k, v in sector_map.items()} if capital > 0 else {}
        max_sector = max(sector_pcts, key=sector_pcts.get) if sector_pcts else "N/A"
        max_pct = sector_pcts.get(max_sector, 0.0)
        return {
            "sector_breakdown":    sector_pcts,
            "max_sector":          max_sector,
            "max_sector_pct":      max_pct,
            "sector_count":        len(sector_map),
            "hhi":                 round(sum(v**2 for v in sector_pcts.values()) / 10000, 4),
            "risk_flag":           max_pct > 40,
            "note":                f"Largest sector: {max_sector} ({max_pct:.1f}%)",
        }

    @staticmethod
    def _calc_correlation(portfolio: Dict, mi: Dict) -> Dict[str, Any]:
        positions = portfolio.get("positions") or []
        regime = mi.get("market_regime", "UNKNOWN")
        # In high correlation regimes (BULL/BEAR), all holdings move together
        high_corr_regime = regime in ("BULL", "BEAR", "HIGH_VOLATILITY")
        n = len(positions)
        est_corr = 0.75 if high_corr_regime and n > 3 else (0.5 if n > 3 else 0.3)
        return {
            "estimated_correlation": round(est_corr, 2),
            "regime":                regime,
            "high_correlation_regime": high_corr_regime,
            "position_count":        n,
            "risk_flag":             est_corr > 0.7,
            "note":                  "Advisory estimate — correlation is regime-adjusted",
            "advisory_only":         True,
        }

    @staticmethod
    def _calc_portfolio_heat(portfolio: Dict, exposure: Dict) -> Dict[str, Any]:
        positions = portfolio.get("positions") or []
        total_pnl = sum(_f(p.get("pnl")) or 0.0 for p in positions)
        capital = exposure.get("capital") or _default_capital()
        heat_pct = round((abs(total_pnl) / capital * 100), 2) if capital > 0 else 0.0
        return {
            "total_unrealised_pnl": round(total_pnl, 2),
            "heat_pct":             heat_pct,
            "heat_level":           "HIGH" if heat_pct > 3 else ("MEDIUM" if heat_pct > 1.5 else "LOW"),
            "risk_flag":            heat_pct > 3,
            "note":                 f"Portfolio heat: {heat_pct:.2f}% of capital at risk",
        }

    @staticmethod
    def _calc_daily_risk(trades: List[Dict], portfolio: Dict) -> Dict[str, Any]:
        capital = _f(portfolio.get("capital")) or _default_capital()
        today_pnl = sum(_f(t.get("pnl")) or 0.0 for t in trades if t.get("status") == "CLOSED")
        daily_risk_pct = round(abs(today_pnl) / capital * 100, 2) if capital > 0 else 0.0
        return {
            "today_realised_pnl":  round(today_pnl, 2),
            "daily_risk_pct":      daily_risk_pct,
            "daily_trade_count":   len(trades),
            "risk_flag":           daily_risk_pct > 2,
            "note":                f"Daily P&L: ₹{today_pnl:,.0f} ({daily_risk_pct:.2f}% of capital)",
        }

    @staticmethod
    def _calc_capital_utilisation(portfolio: Dict) -> Dict[str, Any]:
        capital = _f(portfolio.get("capital")) or _default_capital()
        available = _f(portfolio.get("available_capital")) or capital
        utilised = capital - available
        util_pct = round(utilised / capital * 100, 1) if capital > 0 else 0.0
        return {
            "total_capital":     round(capital, 2),
            "available_capital": round(available, 2),
            "utilised_capital":  round(utilised, 2),
            "utilisation_pct":   util_pct,
            "risk_flag":         util_pct > 85,
            "note":              f"{util_pct:.1f}% of capital utilised",
        }

    @staticmethod
    def _calc_drawdown(trades: List[Dict]) -> Dict[str, Any]:
        if not trades:
            return {"max_drawdown_pct": 0.0, "current_drawdown_pct": 0.0,
                    "risk_flag": False, "note": "No closed trades"}
        pnls = [_f(t.get("pnl")) or 0.0 for t in trades]
        cumulative = []
        running = 0.0
        for p in pnls:
            running += p
            cumulative.append(running)
        peak = max(cumulative) if cumulative else 0.0
        trough_after_peak = min(cumulative[cumulative.index(peak):]) if peak > 0 else 0.0
        max_dd = round(peak - trough_after_peak, 2)
        capital_proxy = abs(sum(pnls)) or _default_capital()
        max_dd_pct = round(max_dd / capital_proxy * 100, 2) if capital_proxy > 0 else 0.0
        return {
            "max_drawdown_value": max_dd,
            "max_drawdown_pct":   max_dd_pct,
            "current_drawdown_pct": 0.0,
            "risk_flag":          max_dd_pct > 5,
            "note":               f"Max drawdown: {max_dd_pct:.2f}%",
        }

    @staticmethod
    def _calc_tail_risk(mi: Dict, exposure: Dict) -> Dict[str, Any]:
        vix = _f(mi.get("vix_value")) or 18.0
        vol_regime = mi.get("volatility_regime", "NORMAL_VOLATILITY")
        exposure_pct = exposure.get("exposure_pct") or 0.0
        # Simple VaR proxy at 99% confidence
        daily_vol = vix / 16.0  # annualised VIX → daily σ approx
        var_99 = round(daily_vol * 2.33, 2)  # 99% 1-day VaR %
        tail_score = _clamp(vix * 2 + (exposure_pct * 0.5))
        return {
            "vix_value":        round(vix, 1),
            "volatility_regime":vol_regime,
            "var_99_pct":       var_99,
            "tail_risk_score":  round(tail_score, 1),
            "tail_risk_level":  "HIGH" if tail_score > 60 else ("MEDIUM" if tail_score > 35 else "LOW"),
            "risk_flag":        tail_score > 60,
            "note":             f"Advisory 99% VaR estimate: {var_99:.1f}% daily",
            "advisory_only":    True,
        }

    @staticmethod
    def _aggregate_risk(exposure, sizing, sector_conc, correlation,
                        heat, daily_risk, capital_util, drawdown, tail_risk) -> tuple:
        flags = {
            "Exposure":        exposure.get("risk_flag", False),
            "Sizing":          sizing.get("risk_flag", False),
            "Sector":          sector_conc.get("risk_flag", False),
            "Correlation":     correlation.get("risk_flag", False),
            "Heat":            heat.get("risk_flag", False),
            "Daily Risk":      daily_risk.get("risk_flag", False),
            "Capital Util":    capital_util.get("risk_flag", False),
            "Drawdown":        drawdown.get("risk_flag", False),
            "Tail Risk":       tail_risk.get("risk_flag", False),
        }
        flagged_count = sum(1 for f in flags.values() if f)
        # Score = 100 - penalty
        score = _clamp(100 - flagged_count * 12)

        if flagged_count >= 5:
            level = "CRITICAL"
        elif flagged_count >= 3:
            level = "HIGH"
        elif flagged_count >= 1:
            level = "MODERATE"
        else:
            level = "LOW"

        breakdown = {name: ("⚠ FLAGGED" if flagged else "✓ OK")
                     for name, flagged in flags.items()}
        return level, score, breakdown

    @staticmethod
    def _grade(score: float) -> str:
        if score >= 85: return "A"
        if score >= 70: return "B"
        if score >= 55: return "C"
        if score >= 40: return "D"
        return "F"

    def get_risk_detail(self) -> Optional[Dict[str, Any]]:
        return self._last_snapshot

    def last_snapshot(self) -> Optional[Dict[str, Any]]:
        return self._last_snapshot
