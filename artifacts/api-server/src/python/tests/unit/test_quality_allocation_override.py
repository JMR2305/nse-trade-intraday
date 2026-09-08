"""Pure unit coverage for the paper-only quality allocation policy."""

from __future__ import annotations

import copy

import pytest

from quality_allocation_override import (
    EXCEPTIONAL_QUALITY_3X,
    HIGH_QUALITY_2X,
    NORMAL,
    apply_final_quantity,
    evaluate_allocation_override,
    previous_scan_3x_valid,
    revalidate_final_quantity,
)


PASS_GATES = (
    "scan_fresh",
    "snapshot_consistency",
    "entry_circuit_breaker",
    "no_open_duplicate",
    "daily_trade_limit",
    "sector_cap",
    "portfolio_deployed_cap",
    "sufficient_cash",
)


def _settings(**overrides):
    result = {
        "quality_allocation_override_enabled": True,
        "quality_allocation_2x_enabled": True,
        "quality_allocation_3x_enabled": True,
        "quality_allocation_2x_min_confidence": 85.0,
        "quality_allocation_2x_min_opportunity_score": 80.0,
        "quality_allocation_2x_min_trade_quality_score": 80.0,
        "quality_allocation_2x_min_risk_reward": 2.5,
        "quality_allocation_2x_risk_budget_pct": 1.5,
        "quality_allocation_3x_min_confidence": 90.0,
        "quality_allocation_3x_min_opportunity_score": 85.0,
        "quality_allocation_3x_min_trade_quality_score": 88.0,
        "quality_allocation_3x_min_risk_reward": 3.0,
        "quality_allocation_3x_risk_budget_pct": 2.0,
        "quality_allocation_3x_max_atr_pct": 3.0,
        "quality_allocation_3x_max_stop_distance_pct": 2.5,
        "quality_allocation_absolute_cap": 30_000.0,
        "quality_allocation_3x_sector_override_enabled": False,
        "quality_allocation_3x_sector_override_cap_pct": 50.0,
        "initial_capital": 100_000.0,
        "risk_per_trade_pct": 1.0,
        "per_stock_exposure_cap_pct": 25.0,
        "sector_exposure_cap_pct": 40.0,
        "portfolio_deployed_cap_pct": 80.0,
    }
    result.update(overrides)
    return result


def _candidate(**overrides):
    result = {
        "symbol": "TCS",
        "eligible": True,
        "failed_gates": [],
        "confidence": 92.0,
        "opportunity_score": 90.0,
        "trade_quality_score": 92.0,
        "data_quality": "LIVE",
        "kite_ltp_available": True,
        "kite_session_verified_flag": True,
        "execution_price_source": "kite_live_ltp",
        "quote_reliable": True,
        "gates": [
            {"gate": name, "passed": True, "reason": "ok"}
            for name in PASS_GATES
        ],
        "sizing": {
            "quantity": 10,
            "entry_price": 100.0,
            "stop_loss": 98.0,
            "target_price": 106.0,
            "rr_ratio": 3.0,
            "risk_amount": 20.0,
        },
        "allocation_context": {
            "total_capital": 100_000.0,
            "cash": 100_000.0,
            "invested_value": 0.0,
            "existing_stock_value": 0.0,
            "existing_sector_value": 0.0,
            "daily_realized_pnl": 0.0,
            "risk_per_trade_pct": 1.0,
            "normal_risk_budget_pct": 1.0,
            "ohlcv_cache_hit": True,
            "ohlcv_cache_fresh": True,
            "ohlcv_cache_data_quality": "LIVE",
            "atr_pct": 1.5,
            "stale_or_blocked_close_warning": False,
            "previous_scan_3x_valid": True,
        },
    }
    for key, value in overrides.items():
        if key == "sizing":
            result["sizing"].update(value)
        elif key == "allocation_context":
            result["allocation_context"].update(value)
        else:
            result[key] = value
    return result


def _evaluate(candidate=None, settings=None, previous=True, trigger="AUTO"):
    return evaluate_allocation_override(
        candidate or _candidate(),
        settings or _settings(),
        100.0,
        previous_scan_valid=previous,
        trigger_source=trigger,
    )


def test_normal_sizing_is_unchanged_when_quality_thresholds_fail():
    result = _evaluate(_candidate(confidence=70.0))
    assert result["tier"] == NORMAL
    assert result["final_quantity"] == 10
    assert result["effective_multiplier"] == 1.0
    assert result["override_approved"] is False


def test_high_quality_candidate_gets_2x_without_prior_3x_scan():
    result = _evaluate(previous=False)
    assert result["tier"] == HIGH_QUALITY_2X
    assert result["requested_multiplier"] == 2.0
    assert result["final_quantity"] == 20
    assert result["three_x_quality_valid"] is True


def test_exceptional_candidate_gets_3x_after_prior_valid_scan():
    result = _evaluate(previous=True)
    assert result["tier"] == EXCEPTIONAL_QUALITY_3X
    assert result["requested_multiplier"] == 3.0
    assert result["final_quantity"] == 30
    assert result["final_risk_amount"] == 60.0


@pytest.mark.parametrize(
    ("mutator", "failed_check"),
    [
        (lambda c: c.update(kite_ltp_available=False), "kite_ltp_available"),
        (
            lambda c: c.update(kite_session_verified_flag=False),
            "kite_session_verified",
        ),
        (
            lambda c: c.update(execution_price_source="yfinance_daily_bars"),
            "kite_execution_price",
        ),
        (lambda c: c.update(quote_reliable=False), "quote_reliable"),
        (lambda c: c.update(data_quality="STALE"), "live_data_quality"),
        (
            lambda c: c["allocation_context"].update(ohlcv_cache_hit=False),
            "ohlcv_cache_hit",
        ),
        (
            lambda c: c["allocation_context"].update(ohlcv_cache_fresh=False),
            "ohlcv_cache_fresh",
        ),
        (
            lambda c: c["allocation_context"].update(
                daily_realized_pnl=-0.01
            ),
            "no_loss_today",
        ),
    ],
)
def test_common_trusted_source_and_loss_failures_deny_override(
    mutator, failed_check
):
    candidate = _candidate()
    mutator(candidate)
    result = _evaluate(candidate)
    assert result["tier"] == NORMAL
    assert result["checks_2x"][failed_check] is False


@pytest.mark.parametrize(
    "gate_name",
    [
        "scan_fresh",
        "snapshot_consistency",
        "entry_circuit_breaker",
        "no_open_duplicate",
        "daily_trade_limit",
        "sector_cap",
        "portfolio_deployed_cap",
        "sufficient_cash",
    ],
)
def test_every_existing_safety_gate_can_deny_override(gate_name):
    candidate = _candidate()
    for gate in candidate["gates"]:
        if gate["gate"] == gate_name:
            gate["passed"] = False
    result = _evaluate(candidate)
    assert result["tier"] == NORMAL
    assert result["checks_2x"][
        {
            "snapshot_consistency": "snapshot_consistent",
            "entry_circuit_breaker": "circuit_breaker_clear",
            "no_open_duplicate": "no_duplicate_position",
            "daily_trade_limit": "daily_trade_allowance",
            "sector_cap": "sector_allowance",
            "portfolio_deployed_cap": "portfolio_allowance",
            "sufficient_cash": "cash_allowance",
        }.get(gate_name, gate_name)
    ] is False


@pytest.mark.parametrize(
    ("candidate", "failed_check"),
    [
        (
            _candidate(allocation_context={"atr_pct": 4.0}),
            "low_or_normal_volatility",
        ),
        (
            _candidate(sizing={"stop_loss": 96.0}),
            "low_stop_distance",
        ),
        (
            _candidate(
                allocation_context={"stale_or_blocked_close_warning": True}
            ),
            "no_stale_or_blocked_close_warning",
        ),
    ],
)
def test_3x_specific_failure_falls_back_to_2x(candidate, failed_check):
    result = _evaluate(candidate, previous=True)
    assert result["tier"] == HIGH_QUALITY_2X
    assert result["checks_3x"][failed_check] is False


def test_risk_budget_reduces_2x_quantity_without_weakening_limit():
    candidate = _candidate(
        confidence=86.0,
        opportunity_score=82.0,
        trade_quality_score=82.0,
        sizing={"quantity": 50, "stop_loss": 80.0, "rr_ratio": 2.5},
    )
    result = _evaluate(candidate, previous=False)
    assert result["tier"] == HIGH_QUALITY_2X
    assert result["base_quantity"] == 50
    assert result["final_quantity"] == 75
    assert result["final_risk_amount"] == 1_500.0
    assert "risk" in result["limiting_caps"]


def test_per_stock_cap_limits_multiplier():
    candidate = _candidate(sizing={"quantity": 200})
    result = _evaluate(candidate)
    assert result["tier"] == EXCEPTIONAL_QUALITY_3X
    assert result["final_quantity"] == 250
    assert result["exposure_after"]["stock_pct"] == 25.0
    assert "per_stock" in result["limiting_caps"]


def test_sector_cap_limits_multiplier_by_default():
    candidate = _candidate(
        sizing={"quantity": 100},
        allocation_context={"existing_sector_value": 35_000.0},
    )
    result = _evaluate(candidate)
    assert result["final_notional"] == 5_000.0
    assert result["exposure_after"]["sector_pct"] == 40.0
    assert "sector" in result["limiting_caps"]
    assert result["sector_override_applied"] is False


def test_optional_3x_sector_override_is_separate_and_capped_at_50_pct():
    candidate = _candidate(
        sizing={"quantity": 100},
        allocation_context={"existing_sector_value": 35_000.0},
    )
    result = _evaluate(
        candidate,
        _settings(
            quality_allocation_3x_sector_override_enabled=True,
            quality_allocation_3x_sector_override_cap_pct=50.0,
        ),
    )
    assert result["final_notional"] == 15_000.0
    assert result["exposure_after"]["sector_pct"] == 50.0
    assert result["sector_override_applied"] is True


def test_portfolio_cash_and_absolute_caps_are_all_enforced():
    candidate = _candidate(
        sizing={"quantity": 100},
        allocation_context={
            "cash": 9_000.0,
            "invested_value": 73_000.0,
        },
    )
    result = _evaluate(
        candidate, _settings(quality_allocation_absolute_cap=8_000.0)
    )
    assert result["final_notional"] == 7_000.0
    assert {"portfolio", "absolute"}.issubset(result["limiting_caps"])


def test_bootstrap_path_never_receives_override():
    result = _evaluate(trigger="BOOTSTRAP_AUTO")
    assert result["tier"] == NORMAL
    assert result["reason"] == "BOOTSTRAP_SIZING_PRESERVED"
    assert result["final_quantity"] == 10


def test_policy_never_reports_live_broker_order():
    result = _evaluate()
    assert result["paper_only"] is True
    assert result["live_broker_orders_called"] is False


def test_evaluator_does_not_mutate_candidate_or_settings():
    candidate = _candidate()
    settings = _settings()
    before_candidate = copy.deepcopy(candidate)
    before_settings = copy.deepcopy(settings)
    _evaluate(candidate, settings)
    assert candidate == before_candidate
    assert settings == before_settings


def test_downstream_authoritative_resize_updates_audit_values():
    decision = _evaluate()
    resized = apply_final_quantity(
        decision,
        15,
        100.0,
        98.0,
        limiting_reason="risk_validation_per_stock_cap",
    )
    assert resized["final_quantity"] == 15
    assert resized["final_notional"] == 1_500.0
    assert resized["final_risk_amount"] == 30.0
    assert resized["effective_multiplier"] == 1.5
    assert "risk_validation_per_stock_cap" in resized["limiting_caps"]


def test_previous_scan_history_requires_immediately_prior_distinct_scan():
    history = [
        {
            "scan_id": "scan-1",
            "symbols": {"TCS": {"three_x_quality_valid": True}},
        },
        {
            "scan_id": "scan-2",
            "symbols": {"INFY": {"three_x_quality_valid": True}},
        },
    ]
    assert previous_scan_3x_valid(history, "scan-3", "TCS") is False
    assert previous_scan_3x_valid(history, "scan-3", "INFY") is True


def test_repeated_current_scan_cannot_satisfy_continuity_by_itself():
    history = [
        {
            "scan_id": "scan-1",
            "symbols": {"TCS": {"three_x_quality_valid": False}},
        },
        {
            "scan_id": "scan-2",
            "symbols": {"TCS": {"three_x_quality_valid": True}},
        },
    ]
    assert previous_scan_3x_valid(history, "scan-2", "TCS") is False


def test_locked_revalidation_uses_latest_sector_exposure_and_resizes():
    decision = _evaluate()
    result = revalidate_final_quantity(
        decision,
        _settings(),
        [{
            "symbol": "INFY",
            "sector": "IT",
            "quantity": 390,
            "fill_price": 100.0,
        }],
        symbol="TCS",
        sector="IT",
        fill_price=100.0,
        stop_loss=98.0,
    )
    assert result["allowed"] is True
    assert result["requested_quantity"] == 30
    assert result["quantity"] == 10
    assert result["decision"]["effective_multiplier"] == 1.0
    assert result["decision"]["exposure_after"]["sector_pct"] == 40.0
    assert "sector" in result["decision"]["limiting_caps"]
    assert result["decision"]["admission_revalidated"] is True


def test_locked_revalidation_blocks_when_normal_base_no_longer_fits():
    decision = _evaluate()
    result = revalidate_final_quantity(
        decision,
        _settings(),
        [{
            "symbol": "INFY",
            "sector": "IT",
            "quantity": 395,
            "fill_price": 100.0,
        }],
        symbol="TCS",
        sector="IT",
        fill_price=100.0,
        stop_loss=98.0,
    )
    assert result["allowed"] is False
    assert result["reason"] == "NORMAL_BASE_QUANTITY_NO_LONGER_FITS"


def test_locked_revalidation_fails_closed_on_malformed_open_ledger():
    decision = _evaluate()
    result = revalidate_final_quantity(
        decision,
        _settings(),
        [{"symbol": "INFY", "sector": "IT", "quantity": None,
          "fill_price": 100.0}],
        symbol="TCS",
        sector="IT",
        fill_price=100.0,
        stop_loss=98.0,
    )
    assert result["allowed"] is False
    assert result["reason"] == "AUTHORITATIVE_OPEN_LEDGER_ROW_INVALID"