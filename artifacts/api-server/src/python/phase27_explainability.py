"""
phase27_explainability.py — Phase 27C: AI Explainability (READ-ONLY).

One aggregator that merges, for a single symbol:
  • the canonical scan snapshot row (scan_state_store — the same row every
    other page reads; nothing recomputed here),
  • the per-symbol stage journey (ops_centre.get_stock_journey),
  • the canonical portfolio (HOLD detection only).

Honesty rules
  • Factors the production pipeline does not compute (MACD, VWAP, ATR, news
    impact, corporate actions, explicit support/resistance levels) are
    reported with evaluated=False and a clear note — NEVER fabricated.
  • Decision states: BUY / SELL / WATCH / HOLD / REJECTED / NOT_SCANNED.

ADVISORY-ONLY · NEVER modifies any trading state.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _canonical_row(symbol: str) -> Optional[Dict[str, Any]]:
    try:
        from scan_state_store import load_latest_snapshot
        snap = load_latest_snapshot() or {}
        for r in snap.get("recommendations") or []:
            if str(r.get("symbol", "")).upper() == symbol:
                r = dict(r)
                r["_scan_meta"] = {
                    "scan_id": snap.get("scan_id") or r.get("scan_id"),
                    "snapshot_ts": snap.get("snapshot_ts") or r.get("snapshot_ts"),
                }
                return r
    except Exception:
        pass
    return None


def _open_position(symbol: str) -> Optional[Dict[str, Any]]:
    try:
        from canonical_portfolio import build_canonical_portfolio
        book = build_canonical_portfolio() or {}
        for p in book.get("positions") or []:
            if str(p.get("symbol", "")).upper() == symbol:
                return p
    except Exception:
        pass
    return None


def _decision_state(rec: Optional[Dict[str, Any]],
                    position: Optional[Dict[str, Any]]) -> str:
    """Map canonical final_action (+ open position) to the spec vocabulary."""
    if position:
        return "HOLD"
    if not rec:
        return "NOT_SCANNED"
    action = str(rec.get("final_action") or "").upper()
    if "BUY" in action:      # covers "STRONG BUY" and "BUY"
        return "BUY"
    if "SELL" in action:
        return "SELL"
    if "WATCH" in action:
        return "WATCH"
    return "REJECTED"        # IGNORE / empty → not taken forward


_NOT_EVALUATED_NOTE = "Not computed by the production pipeline — shown as unavailable, never fabricated."


def _factor(name: str, value: Any, source: str,
            evaluated: bool = True, note: str = "") -> Dict[str, Any]:
    return {"name": name, "value": value, "source": source,
            "evaluated": evaluated, "note": note}


def _build_factors(rec: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Spec factor list, values straight from the canonical scan row."""
    src = "canonical scan snapshot"
    f: List[Dict[str, Any]] = [
        _factor("Market regime", rec.get("regime"), src),
        _factor("Trend (price vs EMA20/EMA50)",
                {"above_ema20": rec.get("above_ema20"),
                 "above_ema50": rec.get("above_ema50"),
                 "adx": rec.get("adx")}, src),
        _factor("Momentum (RSI)", rec.get("rsi"), src),
        _factor("RSI", rec.get("rsi"), src),
        _factor("EMA alignment",
                {"above_ema20": rec.get("above_ema20"),
                 "above_ema50": rec.get("above_ema50")}, src),
        _factor("Volume (ratio vs average)", rec.get("volume_ratio"), src),
        _factor("Liquidity (volume ratio proxy)", rec.get("volume_ratio"), src),
        _factor("Sector strength (sector)", rec.get("sector"), src),
        _factor("Support (stop level)", rec.get("stop_loss"), src),
        _factor("Resistance (target level)", rec.get("target_price"), src),
        _factor("Risk score (portfolio heat)", rec.get("heat"), src),
        _factor("Risk/Reward ratio", rec.get("rr_ratio"), src),
        _factor("Expected reward (target vs entry)",
                _pct(rec.get("entry_price"), rec.get("target_price")), src),
        _factor("Maximum risk (stop vs entry)",
                _pct(rec.get("entry_price"), rec.get("stop_loss")), src),
        _factor("Confidence breakdown",
                {"technical_score": rec.get("technical_score"),
                 "calibrated_confidence": rec.get("calibrated_confidence"),
                 "opportunity_score": rec.get("opportunity_score"),
                 "historical_evidence_adjustment":
                     rec.get("historical_evidence_adjustment"),
                 "low_evidence": rec.get("low_evidence")}, src),
        _factor("Position size (paper eligibility)",
                {"paper_eligible": rec.get("paper_eligible"),
                 "paper_order_id": rec.get("paper_order_id"),
                 "paper_order_note": rec.get("paper_order_note")}, src),
        _factor("Historical evidence",
                {"total_trades": rec.get("total_trades"),
                 "win_rate": rec.get("win_rate"),
                 "profit_factor": rec.get("profit_factor")}, src),
        # Honestly not evaluated by the pipeline:
        _factor("VWAP", None, "—", evaluated=False, note=_NOT_EVALUATED_NOTE),
        _factor("MACD", None, "—", evaluated=False, note=_NOT_EVALUATED_NOTE),
        _factor("ATR", None, "—", evaluated=False, note=_NOT_EVALUATED_NOTE),
        _factor("News impact", None, "—", evaluated=False, note=_NOT_EVALUATED_NOTE),
        _factor("Corporate actions", None, "—", evaluated=False, note=_NOT_EVALUATED_NOTE),
    ]
    return f


def _pct(entry: Any, level: Any) -> Optional[Dict[str, Any]]:
    try:
        e, l = float(entry), float(level)
        if e <= 0:
            return None
        return {"level": l, "pct_from_entry": round((l - e) / e * 100, 2)}
    except Exception:
        return None


def _rejection(rec: Optional[Dict[str, Any]],
               journey: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Spec-labelled rejection detail: rejected_by / rule / threshold /
    actual / reason / recommendation. Sources: journey why_not + gate flags."""
    why = journey.get("why_not") if isinstance(journey, dict) else None
    entries: List[Dict[str, Any]] = []
    if isinstance(why, dict):
        for c in why.get("failing_criteria") or []:
            entries.append({
                "rejected_by": why.get("rejected_by") or "Pipeline",
                "rule": c.get("field"),
                "threshold": c.get("threshold"),
                "actual": c.get("current"),
                "reason": why.get("reason"),
                "recommendation": why.get("alternative"),
            })
        if not entries and (why.get("reason") or why.get("rejected_by")):
            entries.append({
                "rejected_by": why.get("rejected_by") or "Pipeline",
                "rule": None, "threshold": None, "actual": None,
                "reason": why.get("reason"),
                "recommendation": why.get("alternative"),
            })
    if rec:
        gate_names = {
            "gate_price": "Price gate",
            "gate_rr": "Risk/Reward gate",
            "gate_volume": "Volume gate",
            "gate_data_quality": "Data-quality gate",
        }
        for key, label in gate_names.items():
            gate = rec.get(key)
            # canonical shape: {"passed": bool, "reason": str}
            failed = (gate.get("passed") is False) if isinstance(gate, dict) \
                else (gate is False)
            if failed:
                reason = gate.get("reason") if isinstance(gate, dict) else None
                entries.append({
                    "rejected_by": "Quality gates",
                    "rule": label,
                    "threshold": "configured gate threshold",
                    "actual": _gate_actual(rec, key),
                    "reason": reason or f"{label} not satisfied on the canonical scan",
                    "recommendation":
                        "Symbol re-evaluated automatically on the next scan.",
                })
    return {"rejections": entries} if entries else None


def _gate_actual(rec: Dict[str, Any], gate: str) -> Any:
    return {
        "gate_price": rec.get("entry_price"),
        "gate_rr": rec.get("rr_ratio"),
        "gate_volume": rec.get("volume_ratio"),
        "gate_data_quality": rec.get("data_quality"),
    }.get(gate)


def explain_symbol(symbol: str) -> Dict[str, Any]:
    symbol = (symbol or "").strip().upper()
    if not symbol:
        return {"ok": False, "error": "symbol required", "advisory_only": True}

    rec = _canonical_row(symbol)
    position = _open_position(symbol)

    journey: Dict[str, Any] = {}
    try:
        from ops_centre import get_stock_journey
        journey = get_stock_journey(symbol) or {}
    except Exception:
        journey = {}

    stages = journey.get("stages") or []
    # The ops journey can lag or disagree with the canonical scan (e.g. it
    # reports "Not in universe" for a symbol present in the latest snapshot).
    # The canonical scan is authoritative; flag the conflict honestly.
    journey_found = bool(journey.get("found"))
    journey_conflict = rec is not None and not journey_found
    if journey_conflict:
        stages = []
    current_stage = None
    current_status = None
    for st in stages:
        if st.get("status") not in (None, "", "PENDING"):
            current_stage = st.get("agent")
            current_status = st.get("status")
    if current_stage is None and rec is not None:
        current_stage = "Scanner (canonical scan)"
        current_status = "COMPLETED"

    decision = _decision_state(rec, position)
    confidence = None
    if rec is not None:
        confidence = rec.get("calibrated_confidence")
    if confidence is None and isinstance(journey.get("confidence"), (int, float)):
        confidence = journey.get("confidence") or None

    return {
        "ok": True,
        "advisory_only": True,
        "read_only": True,
        "symbol": symbol,
        "scanned": rec is not None,
        "scan_meta": (rec or {}).get("_scan_meta"),
        "current_stage": current_stage,
        "current_status": current_status,
        "decision": decision,
        "confidence": confidence,
        "strategy": (rec or {}).get("strategy_name") or (rec or {}).get("strategy_id"),
        "position": position,
        "factors": _build_factors(rec) if rec else [],
        "agents_timeline": stages,
        "factor_breakdown": journey.get("factor_breakdown") or [],
        "explanation": journey.get("explanation"),
        "rejection": _rejection(rec, journey if not journey_conflict else {}),
        "journey_available": journey_found and not journey_conflict,
        "note": (
            "Stage journey is out of sync with the canonical scan for this "
            "symbol — timeline hidden rather than shown stale."
            if journey_conflict else
            None if rec else
            "Symbol was not part of the latest canonical scan — no data fabricated."),
    }
