"""
quality_allocation_override.py — pure quality-based paper allocation policy.

This module has no persistence, network, broker, or order side effects.  It
only evaluates whether an already-eligible paper BUY may request 2x/3x sizing,
then constrains the final quantity by the existing cash, per-stock, sector,
portfolio, risk, and absolute caps.

Missing or contradictory evidence fails closed to NORMAL (1x).  Bootstrap
entries always retain their separate ₹15,000 sizing path.
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional


POLICY_NAME = "QUALITY_ALLOCATION_OVERRIDE"
NORMAL = "NORMAL"
HIGH_QUALITY_2X = "HIGH_QUALITY_2X"
EXCEPTIONAL_QUALITY_3X = "EXCEPTIONAL_QUALITY_3X"


def _float(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
        return number if math.isfinite(number) else default
    except (TypeError, ValueError):
        return default


def _bool(value: Any) -> bool:
    return value is True


def _gate_passed(candidate: Dict[str, Any], gate_name: str) -> bool:
    for gate in candidate.get("gates") or []:
        if gate.get("gate") == gate_name:
            return gate.get("passed") is True
    return False


def previous_scan_3x_valid(
    history: Any,
    current_scan_id: Optional[str],
    symbol: str,
) -> bool:
    """Return whether *symbol* was 3x-quality-valid in the immediately prior
    distinct allocation-evaluation scan.

    A repeated evaluation of the current scan ignores the current scan's prior
    record and checks the distinct scan before it.  Corrupt/missing history is
    treated as False.
    """
    if not isinstance(history, list):
        return False
    current = str(current_scan_id or "")
    sym = str(symbol or "").upper()
    for record in reversed(history):
        if not isinstance(record, dict):
            return False
        scan_id = str(record.get("scan_id") or "")
        if current and scan_id == current:
            continue
        symbols = record.get("symbols")
        if not isinstance(symbols, dict):
            return False
        item = symbols.get(sym)
        if not isinstance(item, dict):
            return False
        return bool(
            item.get(
                "continuity_eligible",
                item.get("three_x_quality_valid"),
            )
        )
    return False


def _normal_result(
    *,
    candidate: Dict[str, Any],
    fill_price: float,
    base_qty: int,
    reason: str,
    checks_2x: Optional[Dict[str, bool]] = None,
    checks_3x: Optional[Dict[str, bool]] = None,
    three_x_quality_valid: bool = False,
) -> Dict[str, Any]:
    sizing = candidate.get("sizing") or {}
    stop = _float(sizing.get("stop_loss"))
    base_notional = round(max(0, base_qty) * max(0.0, fill_price), 2)
    risk_per_share = max(0.0, fill_price - stop)
    risk_amount = round(max(0, base_qty) * risk_per_share, 2)
    context = candidate.get("allocation_context") or {}
    capital = _float(context.get("total_capital"))
    return {
        "policy": POLICY_NAME,
        "paper_only": True,
        "live_broker_orders_called": False,
        "enabled": False,
        "override_approved": False,
        "tier": NORMAL,
        "reason": reason,
        "rejection_reasons": [reason],
        "requested_multiplier": 1.0,
        "effective_multiplier": 1.0,
        "base_quantity": max(0, base_qty),
        "final_quantity": max(0, base_qty),
        "base_notional": base_notional,
        "requested_notional": base_notional,
        "final_notional": base_notional,
        "entry_price": round(fill_price, 4),
        "stop_loss": stop,
        "stop_distance_pct": (
            round(risk_per_share / fill_price * 100.0, 4)
            if fill_price > 0 else None
        ),
        "risk_per_share": round(risk_per_share, 4),
        "risk_budget_pct": _float(
            context.get("normal_risk_budget_pct"),
            _float(context.get("risk_per_trade_pct"), 1.0),
        ),
        "risk_budget_amount": round(
            capital * _float(
                context.get("normal_risk_budget_pct"),
                _float(context.get("risk_per_trade_pct"), 1.0),
            ) / 100.0,
            2,
        ),
        "final_risk_amount": risk_amount,
        "final_risk_pct": round(risk_amount / capital * 100.0, 4)
        if capital > 0 else None,
        "risk_based_max_notional": base_notional,
        "absolute_override_cap": None,
        "limiting_caps": [],
        "capacities": {},
        "exposure_after": {},
        "checks_2x": checks_2x or {},
        "checks_3x": checks_3x or {},
        "three_x_quality_valid": three_x_quality_valid,
        "continuity_eligible": three_x_quality_valid,
        "sector_override_applied": False,
    }


def evaluate_allocation_override(
    candidate: Dict[str, Any],
    settings: Dict[str, Any],
    fill_price: float,
    *,
    previous_scan_valid: Optional[bool] = None,
    trigger_source: str = "AUTO",
) -> Dict[str, Any]:
    """Evaluate and size the controlled 1x/2x/3x paper allocation policy.

    The caller must pass an already-eligible candidate enriched with
    ``allocation_context`` by ``phase20_gates``.  The function never mutates its
    inputs and never raises for malformed evidence.
    """
    sizing = candidate.get("sizing") or {}
    base_qty = max(0, int(_float(sizing.get("quantity"))))
    fill = _float(fill_price)

    if str(trigger_source or "").upper() == "BOOTSTRAP_AUTO":
        return _normal_result(
            candidate=candidate,
            fill_price=fill,
            base_qty=base_qty,
            reason="BOOTSTRAP_SIZING_PRESERVED",
        )
    if not settings.get("quality_allocation_override_enabled", True):
        return _normal_result(
            candidate=candidate,
            fill_price=fill,
            base_qty=base_qty,
            reason="QUALITY_ALLOCATION_OVERRIDE_DISABLED",
        )

    context = candidate.get("allocation_context")
    if not isinstance(context, dict):
        return _normal_result(
            candidate=candidate,
            fill_price=fill,
            base_qty=base_qty,
            reason="MISSING_ALLOCATION_CONTEXT",
        )

    stop = _float(sizing.get("stop_loss"))
    capital = _float(context.get("total_capital"))
    cash = max(0.0, _float(context.get("cash")))
    invested = max(0.0, _float(context.get("invested_value")))
    existing_stock = max(0.0, _float(context.get("existing_stock_value")))
    existing_sector = max(0.0, _float(context.get("existing_sector_value")))
    risk_per_share = fill - stop
    base_notional = round(base_qty * fill, 2)
    daily_pnl = _float(context.get("daily_realized_pnl"))
    data_quality = str(candidate.get("data_quality") or "").upper()
    cache_quality = str(context.get("ohlcv_cache_data_quality") or "").upper()
    execution_source = str(candidate.get("execution_price_source") or "").lower()

    if (
        base_qty < 1
        or fill <= 0
        or stop <= 0
        or risk_per_share <= 0
        or capital <= 0
    ):
        return _normal_result(
            candidate=candidate,
            fill_price=fill,
            base_qty=base_qty,
            reason="INVALID_BASE_SIZING_OR_PORTFOLIO_CONTEXT",
        )

    confidence = _float(candidate.get("confidence"))
    opportunity = _float(candidate.get("opportunity_score"))
    quality = _float(candidate.get("trade_quality_score"))
    rr_ratio = _float(sizing.get("rr_ratio"))
    stop_distance_pct = risk_per_share / fill * 100.0
    atr_pct = _float(context.get("atr_pct"))

    common_checks = {
        "already_eligible": (
            candidate.get("eligible") is True
            and not (candidate.get("failed_gates") or [])
        ),
        "scan_fresh": _gate_passed(candidate, "scan_fresh"),
        "snapshot_consistent": _gate_passed(candidate, "snapshot_consistency"),
        "circuit_breaker_clear": _gate_passed(
            candidate, "entry_circuit_breaker"
        ),
        "no_duplicate_position": _gate_passed(candidate, "no_open_duplicate"),
        "daily_trade_allowance": _gate_passed(candidate, "daily_trade_limit"),
        "sector_allowance": _gate_passed(candidate, "sector_cap"),
        "portfolio_allowance": _gate_passed(
            candidate, "portfolio_deployed_cap"
        ),
        "cash_allowance": _gate_passed(candidate, "sufficient_cash"),
        "no_loss_today": daily_pnl >= 0.0,
        "kite_ltp_available": _bool(candidate.get("kite_ltp_available")),
        "kite_session_verified": _bool(
            candidate.get("kite_session_verified_flag")
        ),
        "kite_execution_price": execution_source == "kite_live_ltp",
        "quote_reliable": _bool(candidate.get("quote_reliable")),
        "live_data_quality": data_quality in ("LIVE", "NEAR_LIVE"),
        "ohlcv_cache_hit": _bool(context.get("ohlcv_cache_hit")),
        "ohlcv_cache_fresh": (
            _bool(context.get("ohlcv_cache_fresh"))
            and cache_quality in ("LIVE", "NEAR_LIVE")
        ),
        "risk_budget_available": risk_per_share > 0 and capital > 0,
    }

    checks_2x = {
        **common_checks,
        "tier_enabled": bool(
            settings.get("quality_allocation_2x_enabled", True)
        ),
        "confidence": confidence >= _float(
            settings.get("quality_allocation_2x_min_confidence"), 85.0
        ),
        "opportunity_score": opportunity >= _float(
            settings.get("quality_allocation_2x_min_opportunity_score"), 80.0
        ),
        "trade_quality_score": quality >= _float(
            settings.get("quality_allocation_2x_min_trade_quality_score"), 80.0
        ),
        "risk_reward": rr_ratio >= _float(
            settings.get("quality_allocation_2x_min_risk_reward"), 2.5
        ),
    }
    two_x_valid = all(checks_2x.values())

    previous_valid = (
        bool(previous_scan_valid)
        if previous_scan_valid is not None
        else _bool(context.get("previous_scan_3x_valid"))
    )
    checks_3x = {
        **common_checks,
        "tier_enabled": bool(
            settings.get("quality_allocation_3x_enabled", True)
        ),
        "confidence": confidence >= _float(
            settings.get("quality_allocation_3x_min_confidence"), 90.0
        ),
        "opportunity_score": opportunity >= _float(
            settings.get("quality_allocation_3x_min_opportunity_score"), 85.0
        ),
        "trade_quality_score": quality >= _float(
            settings.get("quality_allocation_3x_min_trade_quality_score"), 88.0
        ),
        "risk_reward": rr_ratio >= _float(
            settings.get("quality_allocation_3x_min_risk_reward"), 3.0
        ),
        "low_or_normal_volatility": (
            atr_pct > 0
            and atr_pct <= _float(
                settings.get("quality_allocation_3x_max_atr_pct"), 3.0
            )
        ),
        "low_stop_distance": stop_distance_pct <= _float(
            settings.get("quality_allocation_3x_max_stop_distance_pct"), 2.5
        ),
        "no_stale_or_blocked_close_warning": not bool(
            context.get("stale_or_blocked_close_warning", True)
        ),
    }
    three_x_quality_valid = all(checks_3x.values())
    checks_3x["two_consecutive_valid_scans"] = previous_valid
    three_x_valid = all(checks_3x.values())

    if three_x_valid:
        tier = EXCEPTIONAL_QUALITY_3X
        requested_multiplier = 3.0
        risk_budget_pct = _float(
            settings.get("quality_allocation_3x_risk_budget_pct"), 2.0
        )
    elif two_x_valid:
        tier = HIGH_QUALITY_2X
        requested_multiplier = 2.0
        risk_budget_pct = _float(
            settings.get("quality_allocation_2x_risk_budget_pct"), 1.5
        )
    else:
        failed = [name for name, passed in checks_2x.items() if not passed]
        reason = (
            "2X_REQUIREMENTS_NOT_MET: " + ", ".join(failed)
            if failed else "NO_OVERRIDE_TIER_APPROVED"
        )
        normal = _normal_result(
            candidate=candidate,
            fill_price=fill,
            base_qty=base_qty,
            reason=reason,
            checks_2x=checks_2x,
            checks_3x=checks_3x,
            three_x_quality_valid=three_x_quality_valid,
        )
        normal["enabled"] = True
        return normal

    per_stock_cap_pct = _float(
        settings.get("per_stock_exposure_cap_pct"), 25.0
    )
    sector_cap_pct = _float(
        settings.get("sector_exposure_cap_pct"), 40.0
    )
    portfolio_cap_pct = _float(
        settings.get("portfolio_deployed_cap_pct"), 80.0
    )
    sector_override_applied = False
    effective_sector_cap_pct = sector_cap_pct
    if (
        tier == EXCEPTIONAL_QUALITY_3X
        and settings.get(
            "quality_allocation_3x_sector_override_enabled", False
        )
    ):
        override_cap = min(
            50.0,
            _float(
                settings.get(
                    "quality_allocation_3x_sector_override_cap_pct"
                ),
                50.0,
            ),
        )
        if override_cap > sector_cap_pct:
            effective_sector_cap_pct = override_cap

    absolute_cap = _float(
        settings.get("quality_allocation_absolute_cap"), 30_000.0
    )
    requested_notional = base_notional * requested_multiplier
    risk_budget_amount = capital * risk_budget_pct / 100.0
    risk_qty_cap = max(0, int(risk_budget_amount // risk_per_share))
    risk_based_max_notional = risk_qty_cap * fill

    capacities = {
        "cash": cash,
        "per_stock": max(
            0.0, capital * per_stock_cap_pct / 100.0 - existing_stock
        ),
        "sector": max(
            0.0,
            capital * effective_sector_cap_pct / 100.0 - existing_sector,
        ),
        "portfolio": max(
            0.0, capital * portfolio_cap_pct / 100.0 - invested
        ),
        "risk": max(0.0, risk_based_max_notional),
        "absolute": max(0.0, absolute_cap),
    }
    final_capacity = min(requested_notional, *capacities.values())
    final_qty = max(0, int(final_capacity // fill))
    final_notional = round(final_qty * fill, 2)
    final_risk = round(final_qty * risk_per_share, 2)

    limiting_caps: List[str] = []
    for name, amount in capacities.items():
        if amount + 0.01 < requested_notional:
            limiting_caps.append(name)
    if final_qty * fill + 0.01 < min(requested_notional, *capacities.values()):
        limiting_caps.append("whole_share_rounding")

    standard_sector_remaining = max(
        0.0, capital * sector_cap_pct / 100.0 - existing_sector
    )
    if (
        effective_sector_cap_pct > sector_cap_pct
        and final_notional > standard_sector_remaining + 0.01
    ):
        sector_override_applied = True

    if final_qty < 1:
        reason = "OVERRIDE_CAPS_REDUCED_FINAL_QUANTITY_BELOW_ONE"
        normal = _normal_result(
            candidate=candidate,
            fill_price=fill,
            base_qty=base_qty,
            reason=reason,
            checks_2x=checks_2x,
            checks_3x=checks_3x,
            three_x_quality_valid=three_x_quality_valid,
        )
        normal["limiting_caps"] = limiting_caps
        normal["capacities"] = {
            key: round(value, 2) for key, value in capacities.items()
        }
        normal["enabled"] = True
        return normal

    reason = (
        f"{tier} approved"
        + (
            f"; final quantity limited by {', '.join(limiting_caps)}"
            if limiting_caps else ""
        )
    )
    return {
        "policy": POLICY_NAME,
        "paper_only": True,
        "live_broker_orders_called": False,
        "enabled": True,
        "override_approved": True,
        "tier": tier,
        "reason": reason,
        "rejection_reasons": [],
        "requested_multiplier": requested_multiplier,
        "effective_multiplier": round(final_qty / base_qty, 4),
        "base_quantity": base_qty,
        "final_quantity": final_qty,
        "base_notional": base_notional,
        "requested_notional": round(requested_notional, 2),
        "final_notional": final_notional,
        "entry_price": round(fill, 4),
        "stop_loss": stop,
        "stop_distance_pct": round(stop_distance_pct, 4),
        "risk_per_share": round(risk_per_share, 4),
        "risk_budget_pct": risk_budget_pct,
        "risk_budget_amount": round(risk_budget_amount, 2),
        "final_risk_amount": final_risk,
        "final_risk_pct": round(final_risk / capital * 100.0, 4),
        "risk_based_max_notional": round(risk_based_max_notional, 2),
        "absolute_override_cap": round(absolute_cap, 2),
        "limiting_caps": limiting_caps,
        "capacities": {
            key: round(value, 2) for key, value in capacities.items()
        },
        "exposure_after": {
            "stock_value": round(existing_stock + final_notional, 2),
            "stock_pct": round(
                (existing_stock + final_notional) / capital * 100.0, 4
            ),
            "sector_value": round(existing_sector + final_notional, 2),
            "sector_pct": round(
                (existing_sector + final_notional) / capital * 100.0, 4
            ),
            "portfolio_deployed_value": round(invested + final_notional, 2),
            "portfolio_deployed_pct": round(
                (invested + final_notional) / capital * 100.0, 4
            ),
            "sector_cap_pct": effective_sector_cap_pct,
            "portfolio_cap_pct": portfolio_cap_pct,
            "per_stock_cap_pct": per_stock_cap_pct,
        },
        "checks_2x": checks_2x,
        "checks_3x": checks_3x,
        "three_x_quality_valid": three_x_quality_valid,
        "continuity_eligible": three_x_quality_valid,
        "sector_override_applied": sector_override_applied,
    }


def apply_final_quantity(
    decision: Dict[str, Any],
    final_quantity: int,
    fill_price: float,
    stop_loss: float,
    *,
    limiting_reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Return an updated decision after a downstream authoritative resize."""
    out = dict(decision)
    qty = max(0, int(final_quantity))
    fill = _float(fill_price)
    stop = _float(stop_loss)
    risk_per_share = max(0.0, fill - stop)
    base_qty = max(1, int(_float(out.get("base_quantity"), 1.0)))
    capital = 0.0
    exposure = out.get("exposure_after")
    if isinstance(exposure, dict):
        stock_value = _float(exposure.get("stock_value"))
        stock_pct = _float(exposure.get("stock_pct"))
        if stock_pct > 0:
            capital = stock_value / (stock_pct / 100.0)
    out["final_quantity"] = qty
    out["final_notional"] = round(qty * fill, 2)
    out["final_risk_amount"] = round(qty * risk_per_share, 2)
    out["final_risk_pct"] = (
        round(out["final_risk_amount"] / capital * 100.0, 4)
        if capital > 0 else out.get("final_risk_pct")
    )
    out["effective_multiplier"] = round(qty / base_qty, 4)
    limits = list(out.get("limiting_caps") or [])
    if limiting_reason and limiting_reason not in limits:
        limits.append(limiting_reason)
    out["limiting_caps"] = limits
    return out


def revalidate_final_quantity(
    decision: Dict[str, Any],
    settings: Dict[str, Any],
    existing_open_rows: List[Dict[str, Any]],
    *,
    symbol: str,
    sector: Optional[str],
    fill_price: float,
    stop_loss: float,
    realized_pnl: float = 0.0,
) -> Dict[str, Any]:
    """Recompute final paper quantity from authoritative ledger state.

    This pure helper is intended to run while the PostgreSQL paper-entry
    admission lock is held.  It treats malformed ledger rows, settings, or risk
    inputs as a hard admission failure.  The caller may safely resize an
    override downward, but it must not admit an override when even its original
    NORMAL quantity no longer fits.
    """
    fill = _float(fill_price)
    stop = _float(stop_loss)
    capital = _float(settings.get("initial_capital"))
    sym = str(symbol or "").upper()
    sec = str(sector or "UNKNOWN").upper()
    requested_qty = int(_float(decision.get("final_quantity"), 0.0))
    base_qty = int(_float(decision.get("base_quantity"), requested_qty))
    override_approved = decision.get("override_approved") is True

    if not sym or fill <= 0 or stop <= 0 or stop >= fill:
        return {
            "allowed": False,
            "reason": "INVALID_ENTRY_OR_STOP_FOR_LOCKED_REVALIDATION",
        }
    if capital <= 0 or requested_qty < 1 or base_qty < 1:
        return {
            "allowed": False,
            "reason": "INVALID_CAPITAL_OR_QUANTITY_FOR_LOCKED_REVALIDATION",
        }
    if not isinstance(existing_open_rows, list):
        return {
            "allowed": False,
            "reason": "AUTHORITATIVE_OPEN_LEDGER_UNREADABLE",
        }

    invested = 0.0
    existing_stock = 0.0
    existing_sector = 0.0
    for row in existing_open_rows:
        if not isinstance(row, dict):
            return {
                "allowed": False,
                "reason": "AUTHORITATIVE_OPEN_LEDGER_ROW_INVALID",
            }
        row_qty = int(_float(row.get("quantity"), -1.0))
        row_fill = _float(row.get("fill_price"), -1.0)
        if row_qty < 1 or row_fill <= 0:
            return {
                "allowed": False,
                "reason": "AUTHORITATIVE_OPEN_LEDGER_ROW_INVALID",
            }
        notional = row_qty * row_fill
        invested += notional
        if str(row.get("symbol") or "").upper() == sym:
            existing_stock += notional
        if str(row.get("sector") or "UNKNOWN").upper() == sec:
            existing_sector += notional

    realized = _float(realized_pnl)
    cash = capital - invested + realized
    per_stock_cap_pct = _float(
        settings.get("per_stock_exposure_cap_pct"), 25.0
    )
    standard_sector_cap_pct = _float(
        settings.get("sector_exposure_cap_pct"), 40.0
    )
    portfolio_cap_pct = _float(
        settings.get("portfolio_deployed_cap_pct"), 80.0
    )

    effective_sector_cap_pct = standard_sector_cap_pct
    if (
        override_approved
        and decision.get("tier") == EXCEPTIONAL_QUALITY_3X
        and decision.get("three_x_quality_valid") is True
        and settings.get("quality_allocation_3x_sector_override_enabled")
        is True
    ):
        effective_sector_cap_pct = min(
            50.0,
            max(
                standard_sector_cap_pct,
                _float(
                    settings.get(
                        "quality_allocation_3x_sector_override_cap_pct"
                    ),
                    standard_sector_cap_pct,
                ),
            ),
        )

    tier_risk_budget_pct = _float(
        settings.get("risk_per_trade_pct"), 1.0
    )
    if override_approved and decision.get("tier") == HIGH_QUALITY_2X:
        tier_risk_budget_pct = _float(
            settings.get("quality_allocation_2x_risk_budget_pct"), 1.5
        )
    elif (
        override_approved
        and decision.get("tier") == EXCEPTIONAL_QUALITY_3X
    ):
        tier_risk_budget_pct = _float(
            settings.get("quality_allocation_3x_risk_budget_pct"), 2.0
        )

    risk_per_share = fill - stop
    risk_budget_amount = capital * tier_risk_budget_pct / 100.0
    risk_qty_cap = int(risk_budget_amount // risk_per_share)

    capacities = {
        "cash": max(0.0, cash),
        "per_stock": max(
            0.0,
            capital * per_stock_cap_pct / 100.0 - existing_stock,
        ),
        "sector": max(
            0.0,
            capital * effective_sector_cap_pct / 100.0 - existing_sector,
        ),
        "portfolio": max(
            0.0,
            capital * portfolio_cap_pct / 100.0 - invested,
        ),
        "risk": max(0.0, risk_qty_cap * fill),
    }
    if override_approved:
        capacities["absolute"] = max(
            0.0,
            _float(settings.get("quality_allocation_absolute_cap"), 30_000.0),
        )

    requested_notional = requested_qty * fill
    final_capacity = min(requested_notional, *capacities.values())
    final_qty = max(0, int(final_capacity // fill))
    limiting_caps = [
        name
        for name, amount in capacities.items()
        if amount + 0.01 < requested_notional
    ]
    if final_qty * fill + 0.01 < final_capacity:
        limiting_caps.append("whole_share_rounding")

    if final_qty < 1:
        return {
            "allowed": False,
            "reason": "NO_AUTHORITATIVE_CAPACITY_REMAINS",
            "capacities": {
                key: round(value, 2) for key, value in capacities.items()
            },
        }
    if override_approved and final_qty < base_qty:
        return {
            "allowed": False,
            "reason": "NORMAL_BASE_QUANTITY_NO_LONGER_FITS",
            "final_quantity": final_qty,
            "base_quantity": base_qty,
            "capacities": {
                key: round(value, 2) for key, value in capacities.items()
            },
        }

    updated = apply_final_quantity(
        decision,
        final_qty,
        fill,
        stop,
        limiting_reason=(
            "locked_authoritative_revalidation"
            if final_qty != requested_qty
            else None
        ),
    )
    final_notional = round(final_qty * fill, 2)
    updated["capacities"] = {
        key: round(value, 2) for key, value in capacities.items()
    }
    updated["limiting_caps"] = list(
        dict.fromkeys(
            list(updated.get("limiting_caps") or []) + limiting_caps
        )
    )
    updated["exposure_after"] = {
        "stock_value": round(existing_stock + final_notional, 2),
        "stock_pct": round(
            (existing_stock + final_notional) / capital * 100.0, 4
        ),
        "sector_value": round(existing_sector + final_notional, 2),
        "sector_pct": round(
            (existing_sector + final_notional) / capital * 100.0, 4
        ),
        "portfolio_deployed_value": round(invested + final_notional, 2),
        "portfolio_deployed_pct": round(
            (invested + final_notional) / capital * 100.0, 4
        ),
        "sector_cap_pct": effective_sector_cap_pct,
        "portfolio_cap_pct": portfolio_cap_pct,
        "per_stock_cap_pct": per_stock_cap_pct,
    }
    updated["risk_budget_pct"] = tier_risk_budget_pct
    updated["risk_budget_amount"] = round(risk_budget_amount, 2)
    updated["final_risk_amount"] = round(final_qty * risk_per_share, 2)
    updated["final_risk_pct"] = round(
        updated["final_risk_amount"] / capital * 100.0, 4
    )
    updated["admission_revalidated"] = True

    return {
        "allowed": True,
        "reason": (
            "LOCKED_QUANTITY_REDUCED"
            if final_qty != requested_qty
            else "LOCKED_QUANTITY_CONFIRMED"
        ),
        "quantity": final_qty,
        "requested_quantity": requested_qty,
        "decision": updated,
        "authoritative_state": {
            "initial_capital": round(capital, 2),
            "cash_before": round(cash, 2),
            "invested_before": round(invested, 2),
            "realized_pnl": round(realized, 2),
            "existing_stock_exposure": round(existing_stock, 2),
            "existing_sector_exposure": round(existing_sector, 2),
            "open_position_count": len(existing_open_rows),
        },
    }