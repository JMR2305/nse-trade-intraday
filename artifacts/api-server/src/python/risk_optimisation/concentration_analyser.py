"""
concentration_analyser.py — Phase 6.4
Portfolio concentration: single position, sector, strategy, regime,
correlation risk, and diversification score.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
from typing import Dict, List
from collections import defaultdict

DEFAULT_CAPITAL = 500_000.0


def analyse_concentration(records: list, starting_capital: float = DEFAULT_CAPITAL) -> dict:
    """
    Measure portfolio concentration and compute diversification score.

    Returns:
      - single_position_max_pct: max fraction of capital in one symbol
      - sector_exposure: {sector: (count, pct_of_trades)}
      - strategy_exposure: {strategy: (count, pct_of_trades)}
      - regime_exposure: {regime: (count, pct_of_trades)}
      - hhi_sector: Herfindahl–Hirschman Index for sectors (0=perfect, 1=max concentration)
      - hhi_strategy: HHI for strategies
      - diversification_score: 0–1 (1 = well diversified)
      - correlation_risk: LOW / MEDIUM / HIGH
    """
    if not records:
        return _empty_concentration()

    n = len(records)

    # Symbol concentration
    symbol_caps: Dict[str, float] = defaultdict(float)
    for r in records:
        sym = r.get("symbol") or "UNKNOWN"
        cap = _capital_for(r)
        symbol_caps[sym] += cap
    max_sym_cap = max(symbol_caps.values()) if symbol_caps else 0.0
    single_position_max_pct = max_sym_cap / starting_capital if starting_capital > 0 else 0.0

    # Sector exposure
    sector_counts: Dict[str, int] = defaultdict(int)
    for r in records:
        s = r.get("sector") or "Unknown"
        sector_counts[s] += 1
    sector_exposure = {
        k: {"count": v, "pct_of_trades": round(v / n, 4)}
        for k, v in sorted(sector_counts.items(), key=lambda x: -x[1])
    }
    hhi_sector = _hhi(list(sector_counts.values()))

    # Strategy exposure
    strategy_counts: Dict[str, int] = defaultdict(int)
    for r in records:
        st = r.get("strategy") or "Unknown"
        strategy_counts[st] += 1
    strategy_exposure = {
        k: {"count": v, "pct_of_trades": round(v / n, 4)}
        for k, v in sorted(strategy_counts.items(), key=lambda x: -x[1])
    }
    hhi_strategy = _hhi(list(strategy_counts.values()))

    # Market regime exposure
    regime_counts: Dict[str, int] = defaultdict(int)
    for r in records:
        reg = r.get("market_regime") or "Unknown"
        regime_counts[reg] += 1
    regime_exposure = {
        k: {"count": v, "pct_of_trades": round(v / n, 4)}
        for k, v in sorted(regime_counts.items(), key=lambda x: -x[1])
    }

    # Diversification score (inverse of average HHI, penalised by single-pos concentration)
    avg_hhi = (hhi_sector + hhi_strategy) / 2.0
    sym_penalty = max(0.0, single_position_max_pct - 0.20) * 2.0  # penalty if > 20%
    diversification_score = max(0.0, min(1.0, (1.0 - avg_hhi) - sym_penalty))

    # Correlation risk: if dominant sector > 50% → HIGH; > 33% → MEDIUM; else LOW
    max_sector_pct = max(sector_counts.values()) / n if n > 0 else 0.0
    if max_sector_pct > 0.50 or single_position_max_pct > 0.30:
        correlation_risk = "HIGH"
    elif max_sector_pct > 0.33 or single_position_max_pct > 0.20:
        correlation_risk = "MEDIUM"
    else:
        correlation_risk = "LOW"

    return {
        "total_trades": n,
        "unique_symbols": len(symbol_caps),
        "unique_sectors": len(sector_counts),
        "unique_strategies": len(strategy_counts),
        "unique_regimes": len(regime_counts),
        "single_position_max_pct": round(single_position_max_pct, 4),
        "sector_exposure": sector_exposure,
        "strategy_exposure": strategy_exposure,
        "regime_exposure": regime_exposure,
        "hhi_sector": round(hhi_sector, 4),
        "hhi_strategy": round(hhi_strategy, 4),
        "diversification_score": round(diversification_score, 4),
        "correlation_risk": correlation_risk,
        "max_sector_concentration_pct": round(max_sector_pct, 4),
    }


def _hhi(counts: List[int]) -> float:
    """Normalised Herfindahl–Hirschman Index (0 = diverse, 1 = monopoly)."""
    total = sum(counts)
    if total == 0 or len(counts) <= 1:
        return 1.0 if len(counts) <= 1 else 0.0
    n = len(counts)
    raw = sum((c / total) ** 2 for c in counts)
    # Normalise to 0–1 where 0 = perfectly even, 1 = all in one
    hhi_min = 1.0 / n
    hhi_max = 1.0
    if hhi_max == hhi_min:
        return 0.0
    return (raw - hhi_min) / (hhi_max - hhi_min)


def _capital_for(r: dict) -> float:
    entry = r.get("entry_price") or 0.0
    qty = r.get("quantity") or 0.0
    cap = float(entry) * float(qty)
    return cap if cap > 0 else 1.0  # guard div-by-zero


def _empty_concentration() -> dict:
    return {
        "total_trades": 0,
        "unique_symbols": 0,
        "unique_sectors": 0,
        "unique_strategies": 0,
        "unique_regimes": 0,
        "single_position_max_pct": 0.0,
        "sector_exposure": {},
        "strategy_exposure": {},
        "regime_exposure": {},
        "hhi_sector": 0.0,
        "hhi_strategy": 0.0,
        "diversification_score": 0.0,
        "correlation_risk": "LOW",
        "max_sector_concentration_pct": 0.0,
    }
