"""
phase14_adjustments.py — Phase 14: Conservative adaptive learning adjustments.

RESEARCH / PAPER LEARNING ONLY.
Rules enforced here:
- Max ±5 confidence points per evidence source.
- Max ±10 points total adaptive adjustment.
- INSUFFICIENT/LOW evidence contributes 0.
- Negative expectancy with MODERATE+ evidence may reduce confidence.
- Positive adjustment requires profit factor > 1.0 AND MODERATE+ evidence.
- Never turns IGNORE into BUY, never bypasses risk/stale/regime gates
  (the adjustment layer only re-ranks; gate decisions are upstream).
- When drift is CRITICAL, positive adjustments are frozen (0), while
  risk-reducing (negative) adjustments are retained.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone

from phase14_learning import (
    run_evaluation, load_evaluation, confidence_band, opportunity_band,
    holding_band, quality_grade,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ADJUSTMENTS_FILE = os.path.join(BASE_DIR, "phase14_adjustments.json")
FREEZE_FILE = os.path.join(BASE_DIR, "phase14_learning_freeze.json")

MAX_PER_SOURCE = 5.0
MAX_TOTAL = 10.0
OK_RELIABILITY = ("MODERATE", "STRONG", "HIGH")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def learning_frozen() -> dict:
    if os.path.exists(FREEZE_FILE):
        with open(FREEZE_FILE) as f:
            return json.load(f)
    return {"frozen": False}


def set_learning_frozen(frozen: bool, reason: str = "") -> dict:
    state = {"frozen": frozen, "reason": reason, "updated_at": _now()}
    with open(FREEZE_FILE, "w") as f:
        json.dump(state, f, indent=1)
    return state


def _adjustment_from_metrics(m: dict) -> tuple[float, str]:
    """Derive a bounded adjustment from a metric group. Returns (value, reason)."""
    n = m.get("sample_size", 0)
    rel = m.get("reliability", "INSUFFICIENT")
    if rel not in OK_RELIABILITY:
        return 0.0, f"insufficient evidence ({n} trades, {rel})"
    exp = m.get("expectancy") or 0.0
    pf = m.get("profit_factor")
    wr = m.get("win_rate") or 0.0
    if exp < 0:
        # Scale reduction by how bad expectancy is relative to avg loss magnitude
        severity = min(abs(exp) / max(abs(m.get("avg_loss") or 1.0), 1.0), 1.0)
        val = -round(min(MAX_PER_SOURCE, 1.0 + 4.0 * severity), 1)
        return val, (f"negative expectancy ₹{exp:.2f} over {n} trades "
                     f"(PF {pf}, win rate {wr:.0%}, {rel})")
    if exp > 0 and pf is not None and pf > 1.0:
        strength = min((pf - 1.0) / 0.5, 1.0)  # PF 1.5+ = full strength
        val = round(min(MAX_PER_SOURCE, 1.0 + 4.0 * strength), 1)
        return val, (f"positive expectancy ₹{exp:.2f} over {n} trades "
                     f"(PF {pf}, win rate {wr:.0%}, {rel})")
    return 0.0, f"expectancy positive but profit factor not > 1 ({n} trades, {rel})"


def compute_adjustments(force: bool = False) -> dict:
    """Compute all adaptive adjustment tables from the latest evaluation."""
    ev = run_evaluation() if force else load_evaluation()
    freeze = learning_frozen()
    sources: dict[str, dict] = {}

    def add_table(source: str, table: dict):
        entries = {}
        for key, m in (table or {}).items():
            val, reason = _adjustment_from_metrics(m)
            if freeze.get("frozen") and val > 0:
                val, reason = 0.0, f"positive learning frozen (drift): {reason}"
            entries[key] = {
                "adjustment": val,
                "sample_size": m.get("sample_size", 0),
                "expectancy": m.get("expectancy"),
                "profit_factor": m.get("profit_factor"),
                "win_rate": m.get("win_rate"),
                "reliability": m.get("reliability"),
                "reason": reason,
                "bounds": {"lower": -MAX_PER_SOURCE, "upper": MAX_PER_SOURCE},
                "last_updated": _now(),
                "evidence_period": {"from": None, "to": ev.get("generated_at")},
            }
        sources[source] = entries

    add_table("strategy", ev.get("by_strategy"))
    add_table("confidence_band", ev.get("by_confidence_band"))
    add_table("opportunity_band", ev.get("by_opportunity_band"))
    add_table("holding_band", ev.get("by_holding_band"))
    add_table("quality_grade", ev.get("by_quality_grade"))

    # Cross tables strategy×regime, strategy×sector from raw rows
    from phase14_learning import learning_rows, group_metrics
    rows = learning_rows(only_audited=True)

    def cross(keyfn):
        groups: dict[str, list] = {}
        for r in rows:
            groups.setdefault(keyfn(r), []).append(r)
        return {k: group_metrics(v) for k, v in sorted(groups.items())}

    add_table("strategy_x_regime",
              cross(lambda r: f"{r.get('strategy')}|{r.get('market_regime_at_entry')}"))
    add_table("strategy_x_sector",
              cross(lambda r: f"{r.get('strategy')}|{r.get('sector')}"))

    result = {
        "generated_at": _now(),
        "learning_frozen": freeze,
        "caps": {"per_source": MAX_PER_SOURCE, "total": MAX_TOTAL},
        "sources": sources,
        "note": "RESEARCH / PAPER LEARNING ONLY — adjustments re-rank "
                "conservatively; they never create trade signals, never turn "
                "IGNORE into BUY, and never bypass risk, stale-data, or "
                "regime gates.",
    }
    with open(ADJUSTMENTS_FILE, "w") as f:
        json.dump(result, f, indent=1, default=str)
    return result


def load_adjustments() -> dict:
    if os.path.exists(ADJUSTMENTS_FILE):
        with open(ADJUSTMENTS_FILE) as f:
            return json.load(f)
    return compute_adjustments()


def adaptive_adjustment_for(strategy: str | None, regime: str | None,
                            sector: str | None, raw_confidence: float | None,
                            opportunity_score: float | None = None,
                            holding_days: float | None = None,
                            trade_quality: float | None = None,
                            recommendation: str | None = None) -> dict:
    """Compute the bounded total adjustment + contributions for one decision."""
    adj = load_adjustments()
    src = adj.get("sources", {})
    contributions: list[dict] = []

    def take(source: str, key: str | None):
        if key is None:
            return
        entry = src.get(source, {}).get(str(key))
        if entry and entry.get("adjustment"):
            contributions.append({
                "source": source, "key": key,
                "value": entry["adjustment"],
                "reason": entry["reason"],
                "reliability": entry["reliability"],
                "sample_size": entry["sample_size"],
            })

    take("strategy", strategy)
    take("strategy_x_regime", f"{strategy}|{regime}" if strategy and regime else None)
    take("strategy_x_sector", f"{strategy}|{sector}" if strategy and sector else None)
    take("confidence_band", confidence_band(raw_confidence))
    take("opportunity_band", opportunity_band(opportunity_score))
    take("holding_band", holding_band(holding_days))
    take("quality_grade", quality_grade(trade_quality))

    # Decision-time freeze enforcement: read the authoritative freeze state
    # directly (not the cached adjustments file). When frozen, positive
    # contributions are suppressed regardless of stale stored adjustments;
    # risk-reducing (negative) contributions are retained.
    frozen_state = learning_frozen()
    is_frozen = bool(frozen_state.get("frozen", False))
    if is_frozen:
        contributions = [c for c in contributions if c["value"] < 0]

    total = sum(c["value"] for c in contributions)
    capped = max(-MAX_TOTAL, min(MAX_TOTAL, total))

    # Safety: adaptive learning must never turn an IGNORE/AVOID into a BUY.
    ignore_locked = (recommendation or "").upper() in ("IGNORE", "AVOID")
    if ignore_locked and capped > 0:
        capped = 0.0

    if not contributions:
        explanation = "Adaptive adjustment: 0. Reason: insufficient completed paper-trade evidence."
    else:
        parts = "; ".join(f"{c['source']}={c['value']:+.1f} ({c['reason']})" for c in contributions)
        explanation = f"Adaptive adjustment {capped:+.1f} (cap ±{MAX_TOTAL:.0f}). Evidence: {parts}"
        if ignore_locked:
            explanation += ". Positive adjustment suppressed: recommendation is IGNORE/AVOID."
    if is_frozen:
        explanation += " Learning is FROZEN (drift): positive adjustments suppressed."

    return {
        "adjustment": round(capped, 1),
        "uncapped_total": round(total, 1),
        "contributions": contributions,
        "explanation": explanation,
        "learning_frozen": is_frozen,
    }
