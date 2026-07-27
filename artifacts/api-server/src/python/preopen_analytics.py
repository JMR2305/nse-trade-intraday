"""
preopen_analytics.py — Phase 5A Pre-Open Intelligence analytics engine.

Transparent, deterministic scoring. No opaque AI in the primary ranking.
Individual factor contributions are stored so operators can audit every score.

PAPER TRADING / ADVISORY ONLY. No BUY/SELL signals from this module alone.
"""
from __future__ import annotations

from typing import List, Optional, Dict, Any
from preopen_data_model import PreOpenSnapshot, Classification, ProviderState


# ── Core analytics formulas ───────────────────────────────────────────────────

def calc_gap_percent(indicative_price: Optional[float],
                     previous_close: float) -> Optional[float]:
    """gap_percent = (ind_open - prev_close) / prev_close × 100"""
    if indicative_price is None or previous_close <= 0:
        return None
    return round((indicative_price - previous_close) / previous_close * 100, 4)


def calc_imbalance(buy_qty: int, sell_qty: int) -> int:
    """imbalance = total_buy_qty - total_sell_qty"""
    return buy_qty - sell_qty


def calc_imbalance_percent(buy_qty: int, sell_qty: int) -> float:
    """imbalance_pct = (buy - sell) / max(buy + sell, 1) × 100"""
    denom = max(buy_qty + sell_qty, 1)
    return round((buy_qty - sell_qty) / denom * 100, 4)


def calc_participation_score(executed_qty: int,
                              universe_snapshots: List[PreOpenSnapshot]) -> float:
    """
    Participation score 0–100.
    Compare symbol's executed quantity against universe median + max.
    """
    if not universe_snapshots:
        return 0.0
    executed_values = [s.final_executed_quantity for s in universe_snapshots if s.final_executed_quantity > 0]
    if not executed_values:
        return 0.0
    max_qty = max(executed_values)
    if max_qty <= 0:
        return 0.0
    return round(min(executed_qty / max_qty * 100, 100), 2)


def calc_liquidity_score(snapshot: PreOpenSnapshot,
                         universe_snapshots: List[PreOpenSnapshot]) -> float:
    """
    Liquidity score 0–100 based on total traded value and executed quantity
    relative to the universe.
    """
    traded_values = [s.total_traded_value for s in universe_snapshots if s.total_traded_value > 0]
    exec_values = [s.final_executed_quantity for s in universe_snapshots if s.final_executed_quantity > 0]
    if not traded_values and not exec_values:
        return 0.0
    tv_score = 0.0
    eq_score = 0.0
    if traded_values:
        max_tv = max(traded_values)
        if max_tv > 0:
            tv_score = min(snapshot.total_traded_value / max_tv * 100, 100)
    if exec_values:
        max_eq = max(exec_values)
        if max_eq > 0:
            eq_score = min(snapshot.final_executed_quantity / max_eq * 100, 100)
    combined = (tv_score * 0.6 + eq_score * 0.4) if traded_values else eq_score
    return round(combined, 2)


# ── Opportunity score (0–100, transparent 8-factor) ──────────────────────────

def calc_opportunity_score(
    snapshot: PreOpenSnapshot,
    universe_snapshots: List[PreOpenSnapshot],
    index_direction: Optional[float] = None,   # e.g. NIFTY gap %
    sector_avg_gap: Optional[float] = None,
    india_vix: Optional[float] = None,
) -> tuple[float, dict]:
    """
    Returns (score, factor_contributions).

    Factor weights (sum = 100):
      gap_strength          25
      order_imbalance       20
      executed_quantity     15
      liquidity             15
      sector_confirmation   10
      index_direction        5
      data_freshness         5
      volatility_risk        5  (VIX — higher VIX = lower score)
    """
    factors: Dict[str, float] = {}

    # 1. Gap strength (25 pts)
    gap = abs(snapshot.gap_percent or 0.0)
    if gap >= 3.0:
        g_score = 25.0
    elif gap >= 1.5:
        g_score = 20.0
    elif gap >= 0.5:
        g_score = 12.0
    elif gap >= 0.1:
        g_score = 5.0
    else:
        g_score = 0.0
    factors["gap_strength"] = round(g_score, 2)

    # 2. Order imbalance (20 pts)
    imp = abs(snapshot.imbalance_percent)
    if imp >= 60:
        im_score = 20.0
    elif imp >= 40:
        im_score = 15.0
    elif imp >= 20:
        im_score = 8.0
    else:
        im_score = 0.0
    factors["order_imbalance"] = round(im_score, 2)

    # 3. Executed quantity (15 pts)
    eq_score = calc_participation_score(snapshot.final_executed_quantity, universe_snapshots)
    eq_pts = round(eq_score * 0.15, 2)
    factors["executed_quantity"] = eq_pts

    # 4. Liquidity (15 pts)
    liq_pts = round(snapshot.liquidity_score * 0.15, 2)
    factors["liquidity"] = liq_pts

    # 5. Sector confirmation (10 pts)
    if sector_avg_gap is not None and snapshot.gap_percent is not None:
        # Same direction as sector average
        same_dir = (snapshot.gap_percent * sector_avg_gap) > 0
        sec_pts = 10.0 if same_dir and abs(sector_avg_gap) > 0.5 else (5.0 if same_dir else 0.0)
    else:
        sec_pts = 5.0  # neutral when unknown
    factors["sector_confirmation"] = round(sec_pts, 2)

    # 6. Index direction (5 pts)
    if index_direction is not None and snapshot.gap_percent is not None:
        same_dir = (snapshot.gap_percent * index_direction) > 0
        idx_pts = 5.0 if same_dir else 0.0
    else:
        idx_pts = 2.5  # neutral
    factors["index_direction"] = round(idx_pts, 2)

    # 7. Data freshness (5 pts)
    age = snapshot.data_freshness_seconds
    if age <= 30:
        fresh_pts = 5.0
    elif age <= 60:
        fresh_pts = 4.0
    elif age <= 120:
        fresh_pts = 2.0
    elif age <= 300:
        fresh_pts = 1.0
    else:
        fresh_pts = 0.0
    factors["data_freshness"] = round(fresh_pts, 2)

    # 8. Volatility risk (5 pts) — high VIX = lower score
    if india_vix is not None:
        if india_vix < 15:
            vol_pts = 5.0
        elif india_vix < 20:
            vol_pts = 3.5
        elif india_vix < 25:
            vol_pts = 2.0
        else:
            vol_pts = 0.5
    else:
        vol_pts = 3.0  # neutral
    factors["volatility_risk"] = round(vol_pts, 2)

    # Stale data veto: zero score if data is stale (cannot create actionable recommendation)
    if snapshot.is_stale:
        for k in factors:
            factors[k] = 0.0
        return 0.0, factors

    raw_score = sum(factors.values())
    score = round(min(raw_score, 100.0), 2)
    return score, factors


# ── Classification ────────────────────────────────────────────────────────────

def classify_snapshot(snapshot: PreOpenSnapshot) -> str:
    """
    Assign one advisory classification label.
    Classification is advisory only — never BUY or SELL from pre-open data.
    """
    # Data quality checks first
    if snapshot.is_stale or snapshot.validation_status in ("STALE", "UNVALIDATED"):
        return Classification.DATA_INCOMPLETE

    gap = snapshot.gap_percent or 0.0
    imp = snapshot.imbalance_percent or 0.0
    liq = snapshot.liquidity_score

    # Low liquidity check
    total_qty = snapshot.total_buy_quantity + snapshot.total_sell_quantity
    if total_qty < 1000 and liq < 5:
        return Classification.LOW_LIQUIDITY

    # Gap classifications
    if gap >= 2.0:
        return Classification.STRONG_GAP_UP
    if gap >= 0.5:
        return Classification.MODERATE_GAP_UP
    if gap <= -2.0:
        return Classification.STRONG_GAP_DOWN
    if gap <= -0.5:
        return Classification.MODERATE_GAP_DOWN

    # Order imbalance (only in roughly flat territory)
    if imp >= 30:
        return Classification.BUY_IMBALANCE
    if imp <= -30:
        return Classification.SELL_IMBALANCE

    # High participation without strong gap
    if snapshot.final_executed_quantity > 50000:
        return Classification.HIGH_PARTICIPATION

    # Flat open
    if abs(gap) < 0.5:
        return Classification.FLAT_OPEN

    # Avoid if multiple risk factors
    if snapshot.opportunity_score < 10 and abs(gap) < 0.3:
        return Classification.AVOID_AT_OPEN

    return Classification.WATCH_AFTER_OPEN


# ── Ranking ───────────────────────────────────────────────────────────────────

def rank_snapshots(snapshots: List[PreOpenSnapshot]) -> List[PreOpenSnapshot]:
    """Sort by opportunity_score DESC, then gap_percent DESC, stable."""
    return sorted(
        snapshots,
        key=lambda s: (-(s.opportunity_score or 0), -abs(s.gap_percent or 0), s.symbol),
    )


def enrich_universe(snapshots: List[PreOpenSnapshot],
                    index_direction: Optional[float] = None,
                    india_vix: Optional[float] = None) -> List[PreOpenSnapshot]:
    """
    Enrich all snapshots in-place with derived metrics, then rank.
    Returns the ranked list.
    """
    # Sector average gaps
    sector_gaps: Dict[str, list] = {}
    for s in snapshots:
        if s.gap_percent is not None and not s.is_stale:
            sector_gaps.setdefault(s.sector, []).append(s.gap_percent)
    sector_avg = {sec: sum(gs) / len(gs) for sec, gs in sector_gaps.items() if gs}

    for s in snapshots:
        # Derived imbalance metrics
        s.buy_sell_imbalance = calc_imbalance(s.total_buy_quantity, s.total_sell_quantity)
        s.imbalance_percent = calc_imbalance_percent(s.total_buy_quantity, s.total_sell_quantity)
        # Liquidity
        s.liquidity_score = calc_liquidity_score(s, snapshots)
        # Opportunity score
        score, factors = calc_opportunity_score(
            s, snapshots,
            index_direction=index_direction,
            sector_avg_gap=sector_avg.get(s.sector),
            india_vix=india_vix,
        )
        s.opportunity_score = score
        s.factor_scores = factors
        # Classification
        s.classification = classify_snapshot(s)

    ranked = rank_snapshots(snapshots)
    for i, s in enumerate(ranked):
        s.volume_rank = i + 1

    # Gap rank separately
    by_gap = sorted([s for s in snapshots if s.gap_percent is not None],
                    key=lambda s: -abs(s.gap_percent or 0))
    for i, s in enumerate(by_gap):
        s.gap_rank = i + 1

    return ranked
