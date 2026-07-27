"""
signal_validation_attribution.py — Phase 5C attribution analytics.

Calculates performance metrics grouped by:
  - Strategy (Parts 5, 11)
  - AI agreement (Part 6)
  - Pre-open context (Part 7)
  - Market regime (Part 8)

All with sample-size gates and confidence labels.
No strategy parameters are read or changed.

PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

import statistics
from decimal import Decimal
from typing import Any, Dict, List, Optional

from signal_validation_model import SignalValidationRecord, OutcomeClass, LifecycleState
from signal_validation_outcomes import is_success, is_failure

# ── Sample-size gates ──────────────────────────────────────────────────────────

MIN_SIGNALS_FOR_COMPARISON = 20
MIN_TRADES_FOR_COMPARISON  = 10


def _confidence_label(n: int) -> str:
    if n >= MIN_TRADES_FOR_COMPARISON:
        return "SUFFICIENT"
    if n >= 5:
        return "LOW_SAMPLE"
    return "INSUFFICIENT_DATA"


# ── Shared metric calculation ──────────────────────────────────────────────────

def _metrics_from_records(records: List[SignalValidationRecord]) -> Dict[str, Any]:
    """Compute the 16 standard attribution metrics from a list of records."""
    closed = [r for r in records
              if r.validation_status == LifecycleState.CLOSED_POSITION
              and r.outcome_class is not None
              and not r.is_hypothetical]
    trades = [r for r in records if r.paper_order_created and not r.is_hypothetical]
    approved = [r for r in records
                if r.validation_status not in (LifecycleState.GENERATED,
                                                LifecycleState.AI_REVIEWED,
                                                LifecycleState.RISK_REVIEWED,
                                                LifecycleState.RISK_REJECTED)
                and not r.is_hypothetical]

    wins   = [r for r in closed if is_success(r.outcome_class)]
    losses = [r for r in closed if is_failure(r.outcome_class)]

    n       = len(closed)
    win_r   = (len(wins) / n) if n > 0 else None
    loss_r  = (len(losses) / n) if n > 0 else None

    returns = [_to_float(r.realised_pnl) for r in closed if r.realised_pnl is not None]
    r_mults = [_to_float(r.R_multiple) for r in closed if r.R_multiple is not None]
    mfes    = [_to_float(r.max_favourable_excursion) for r in closed if r.max_favourable_excursion is not None]
    maes    = [_to_float(r.max_adverse_excursion) for r in closed if r.max_adverse_excursion is not None]

    avg_ret  = statistics.mean(returns)  if returns  else None
    med_ret  = statistics.median(returns) if returns else None
    avg_r    = statistics.mean(r_mults)  if r_mults  else None
    avg_mfe  = statistics.mean(mfes)     if mfes     else None
    avg_mae  = statistics.mean(maes)     if maes     else None

    gross_profit = sum(r for r in returns if r > 0) if returns else 0
    gross_loss   = abs(sum(r for r in returns if r < 0)) if returns else 0
    profit_factor = (gross_profit / gross_loss) if gross_loss > 0 else None

    expectancy = None
    if win_r is not None and avg_ret is not None and returns:
        win_avg  = statistics.mean([r for r in returns if r > 0]) if any(r > 0 for r in returns) else 0
        loss_avg = statistics.mean([abs(r) for r in returns if r < 0]) if any(r < 0 for r in returns) else 0
        expectancy = (win_r * win_avg) - ((1 - win_r) * loss_avg)

    rejected = [r for r in records if r.validation_status == LifecycleState.RISK_REJECTED]
    false_pos = [r for r in closed if r.outcome_class in (
        OutcomeClass.FALSE_BREAKOUT, OutcomeClass.STRONG_FAILURE, OutcomeClass.MODERATE_FAILURE)]
    fp_rate = (len(false_pos) / n) if n > 0 else None

    missed = [r for r in records if r.validation_status == LifecycleState.MISSED]
    total = len(records)
    missed_rate = (len(missed) / total) if total > 0 else None

    # Max drawdown contribution (simplified: largest single loss)
    max_dd = min(returns) if returns else None

    return {
        "signals_generated":    len(records),
        "signals_approved":     len(approved),
        "paper_trades":         len(trades),
        "closed_trades":        n,
        "win_count":            len(wins),
        "loss_count":           len(losses),
        "win_rate":             win_r,
        "loss_rate":            loss_r,
        "avg_return":           avg_ret,
        "median_return":        med_ret,
        "avg_r_multiple":       avg_r,
        "profit_factor":        profit_factor,
        "expectancy":           expectancy,
        "avg_mfe":              avg_mfe,
        "avg_mae":              avg_mae,
        "max_drawdown_contrib": max_dd,
        "false_positive_rate":  fp_rate,
        "missed_opp_rate":      missed_rate,
        "sample_size":          n,
        "confidence_level":     _confidence_label(n),
    }


def _to_float(v) -> float:
    if isinstance(v, Decimal):
        return float(v)
    return float(v) if v is not None else 0.0


# ── Strategy attribution ───────────────────────────────────────────────────────

def calculate_strategy_attribution(
    records: List[SignalValidationRecord],
    trading_date: str,
    session_id: str,
) -> List[Dict[str, Any]]:
    """Group records by strategy and compute metrics."""
    groups: Dict[str, List[SignalValidationRecord]] = {}
    for r in records:
        key = r.strategy_id or "unknown"
        groups.setdefault(key, []).append(r)

    rows = []
    for strategy_id, recs in groups.items():
        m = _metrics_from_records(recs)
        sample = recs[0] if recs else None
        rows.append({
            "trading_date":      trading_date,
            "session_id":        session_id,
            "strategy_id":       strategy_id,
            "strategy_name":     (sample.strategy_name if sample else strategy_id),
            "strategy_version":  (sample.strategy_version if sample else ""),
            "grouping_key":      "strategy",
            "grouping_value":    strategy_id,
            **m,
        })
    return rows


def calculate_strategy_sector_attribution(
    records: List[SignalValidationRecord],
    trading_date: str,
    session_id: str,
) -> List[Dict[str, Any]]:
    """Group by strategy + sector."""
    groups: Dict[str, List[SignalValidationRecord]] = {}
    for r in records:
        key = f"{r.strategy_id}|{r.sector}"
        groups.setdefault(key, []).append(r)

    rows = []
    for key, recs in groups.items():
        strategy_id, sector = key.split("|", 1)
        m = _metrics_from_records(recs)
        rows.append({
            "trading_date":   trading_date,
            "session_id":     session_id,
            "strategy_id":    strategy_id,
            "strategy_name":  recs[0].strategy_name if recs else strategy_id,
            "strategy_version": recs[0].strategy_version if recs else "",
            "grouping_key":   "sector",
            "grouping_value": sector or "Unknown",
            **m,
        })
    return rows


# ── AI attribution ─────────────────────────────────────────────────────────────

_AI_GROUPS = ["AGREE", "DISAGREE", "WATCH", "NO_RESULT", "STALE"]


def calculate_ai_attribution(
    records: List[SignalValidationRecord],
    trading_date: str,
    session_id: str,
) -> List[Dict[str, Any]]:
    """Compare outcomes across 5 AI agreement groups."""
    groups: Dict[str, List[SignalValidationRecord]] = {g: [] for g in _AI_GROUPS}
    for r in records:
        grp = r.AI_agreement or "NO_RESULT"
        if grp not in groups:
            grp = "NO_RESULT"
        groups[grp].append(r)

    rows = []
    for grp, recs in groups.items():
        if not recs:
            continue
        m = _metrics_from_records(recs)
        closed = [r for r in recs
                  if r.validation_status == LifecycleState.CLOSED_POSITION
                  and r.outcome_class]
        wins = [r for r in closed if is_success(r.outcome_class)]
        losses = [r for r in closed if is_failure(r.outcome_class)]
        n = len(closed)
        cont_rate = (len(wins) / n) if n > 0 else None
        rev_rate  = (len(losses) / n) if n > 0 else None

        latencies = [r.AI_explanation_latency_ms for r in recs
                     if r.AI_explanation_latency_ms is not None]
        avg_lat = statistics.mean(latencies) if latencies else None

        rows.append({
            "trading_date":       trading_date,
            "session_id":         session_id,
            "agreement_group":    grp,
            "signals_count":      len(recs),
            "continuation_rate":  cont_rate,
            "reversal_rate":      rev_rate,
            "win_rate":           m["win_rate"],
            "expectancy":         m["expectancy"],
            "avg_mfe":            m["avg_mfe"],
            "avg_mae":            m["avg_mae"],
            "false_positive_rate": m["false_positive_rate"],
            "missed_opp_rate":    m["missed_opp_rate"],
            "avg_latency_ms":     avg_lat,
            "sample_size":        n,
        })
    return rows


# ── Pre-open attribution ───────────────────────────────────────────────────────

_PREOPEN_GROUPS = ["STRONG", "MODERATE", "CONFLICTING", "NONE", "STALE"]


def _preopen_group(rec: SignalValidationRecord) -> str:
    """Assign pre-open confirmation group."""
    if rec.preopen_classification is None:
        return "NONE"
    cls = (rec.preopen_classification or "").upper()
    if "STRONG" in cls or (rec.preopen_opportunity_score or Decimal("0")) > Decimal("70"):
        return "STRONG"
    if "MODERATE" in cls or (rec.preopen_opportunity_score or Decimal("0")) > Decimal("50"):
        return "MODERATE"
    if "CONFLICT" in cls:
        return "CONFLICTING"
    if "STALE" in cls:
        return "STALE"
    return "NONE"


def calculate_preopen_attribution(
    records: List[SignalValidationRecord],
    trading_date: str,
    session_id: str,
    valid_phase5b_sessions: int = 0,
) -> List[Dict[str, Any]]:
    """
    Attribution by pre-open confirmation group.
    Does not declare predictive value until Phase 5B has ≥5 valid sessions.
    """
    groups: Dict[str, List[SignalValidationRecord]] = {g: [] for g in _PREOPEN_GROUPS}
    for r in records:
        grp = _preopen_group(r)
        groups[grp].append(r)

    predictive_declared = valid_phase5b_sessions >= 5

    rows = []
    for grp, recs in groups.items():
        if not recs:
            continue
        m = _metrics_from_records(recs)
        rows.append({
            "trading_date":              trading_date,
            "session_id":                session_id,
            "confirmation_group":        grp,
            "signals_count":             len(recs),
            "win_rate":                  m["win_rate"],
            "expectancy":                m["expectancy"],
            "avg_r_multiple":            m["avg_r_multiple"],
            "avg_mfe":                   m["avg_mfe"],
            "avg_mae":                   m["avg_mae"],
            "sample_size":               m["sample_size"],
            "predictive_value_declared": predictive_declared,
        })
    return rows


# ── Regime attribution ─────────────────────────────────────────────────────────

def calculate_regime_attribution(
    records: List[SignalValidationRecord],
    trading_date: str,
    session_id: str,
) -> List[Dict[str, Any]]:
    """Group by market regime from RC-10. Does not modify regime logic."""
    groups: Dict[str, List[SignalValidationRecord]] = {}
    for r in records:
        regime = r.market_regime or "UNKNOWN"
        groups.setdefault(regime, []).append(r)

    rows = []
    for regime, recs in groups.items():
        m = _metrics_from_records(recs)
        # Per-strategy within regime
        strategy_groups: Dict[str, List[SignalValidationRecord]] = {}
        for r in recs:
            strategy_groups.setdefault(r.strategy_id or "unknown", []).append(r)

        for sid, srecs in strategy_groups.items():
            sm = _metrics_from_records(srecs)
            rows.append({
                "trading_date":   trading_date,
                "session_id":     session_id,
                "regime":         regime,
                "strategy_id":    sid,
                "signals_count":  len(srecs),
                "win_rate":       sm["win_rate"],
                "expectancy":     sm["expectancy"],
                "avg_r_multiple": sm["avg_r_multiple"],
                "sample_size":    sm["sample_size"],
            })
    return rows


# ── Funnel calculation ────────────────────────────────────────────────────────

def calculate_funnel(records: List[SignalValidationRecord]) -> Dict[str, Any]:
    """Signal funnel: Generated → AI Reviewed → Risk Approved → Paper Order → Filled → Closed → Successful."""
    total = len(records)
    if total == 0:
        return {s: {"count": 0, "pct": 0.0} for s in [
            "generated", "ai_reviewed", "risk_approved", "paper_order",
            "filled", "closed", "successful"]}

    def _pct(n: int) -> float:
        return round(n / total * 100, 1) if total > 0 else 0.0

    ai_rev     = sum(1 for r in records if r.validation_status not in
                     (LifecycleState.GENERATED,))
    risk_appr  = sum(1 for r in records if r.validation_status in (
                     LifecycleState.APPROVED, LifecycleState.PAPER_ORDER_CREATED,
                     LifecycleState.PAPER_ORDER_FILLED, LifecycleState.OPEN_POSITION,
                     LifecycleState.CLOSED_POSITION))
    paper_ord  = sum(1 for r in records if r.paper_order_created)
    filled     = sum(1 for r in records if r.validation_status in (
                     LifecycleState.PAPER_ORDER_FILLED, LifecycleState.OPEN_POSITION,
                     LifecycleState.CLOSED_POSITION))
    closed     = sum(1 for r in records if r.validation_status == LifecycleState.CLOSED_POSITION)
    successful = sum(1 for r in records if r.outcome_class and is_success(r.outcome_class))

    return {
        "generated":    {"count": total,      "pct": 100.0},
        "ai_reviewed":  {"count": ai_rev,      "pct": _pct(ai_rev)},
        "risk_approved":{"count": risk_appr,   "pct": _pct(risk_appr)},
        "paper_order":  {"count": paper_ord,   "pct": _pct(paper_ord)},
        "filled":       {"count": filled,      "pct": _pct(filled)},
        "closed":       {"count": closed,      "pct": _pct(closed)},
        "successful":   {"count": successful,  "pct": _pct(successful)},
    }


# ── Summary card data ─────────────────────────────────────────────────────────

def calculate_summary(records: List[SignalValidationRecord]) -> Dict[str, Any]:
    """9 summary card values."""
    m = _metrics_from_records(records)
    rejected = sum(1 for r in records if r.validation_status == LifecycleState.RISK_REJECTED)
    missed   = sum(1 for r in records if r.validation_status == LifecycleState.MISSED)
    total    = len(records)
    complete = sum(1 for r in records if r.outcome_class is not None
                   and r.outcome_class != OutcomeClass.DATA_INCOMPLETE)
    completeness = round(complete / total * 100, 1) if total > 0 else 0.0

    return {
        "signals_generated":     m["signals_generated"],
        "signals_approved":      m["signals_approved"],
        "paper_trades":          m["paper_trades"],
        "risk_rejections":       rejected,
        "win_rate":              m["win_rate"],
        "expectancy":            m["expectancy"],
        "false_positives":       int(round(m["false_positive_rate"] * m["closed_trades"]))
                                  if m["false_positive_rate"] and m["closed_trades"] else 0,
        "missed_opportunities":  missed,
        "data_completeness_pct": completeness,
    }
