"""Executor wiring tests for quality allocation overrides.

All persistence, portfolio, risk, and event dependencies are mocked.  These
tests never touch the development database or a broker API.
"""

from __future__ import annotations

from copy import deepcopy
from unittest.mock import MagicMock, patch

import pytest

import phase20_executor as executor


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


class _ApprovedRisk:
    verdict = "APPROVED"
    issues = []
    reason = "approved"
    summary = {}

    def to_dict(self):
        return {
            "verdict": "APPROVED",
            "approved": True,
            "summary": {},
            "issues": [],
        }


class _RejectedRisk:
    verdict = "REJECTED"
    issues = []
    reason = "portfolio risk gate rejected"
    summary = {}

    def to_dict(self):
        return {
            "verdict": "REJECTED",
            "approved": False,
            "reason": self.reason,
            "summary": {},
            "issues": [],
        }


def _settings(**overrides):
    result = {
        "fill_model": "LAST_TRADED_PRICE",
        "slippage_pct": 0.15,
        "charges_pct": 0.12,
        "config_hash": "quality-test",
        "per_stock_exposure_cap_pct": 25.0,
        "sector_exposure_cap_pct": 40.0,
        "portfolio_deployed_cap_pct": 80.0,
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
    }
    result.update(overrides)
    return result


def _candidate(**overrides):
    result = {
        "symbol": "TCS",
        "sector": "IT",
        "eligible": True,
        "failed_gates": [],
        "recommendation": "STRONG BUY",
        "confidence": 92.0,
        "opportunity_score": 90.0,
        "trade_quality_score": 92.0,
        "regime": "BULLISH",
        "strategy_id": "trend",
        "strategy_name": "Trend",
        "data_quality": "LIVE",
        "kite_ltp": 100.0,
        "kite_ltp_available": True,
        "kite_session_verified_flag": True,
        "execution_price_source": "kite_live_ltp",
        "quote_reliable": True,
        "indicator_source": "yfinance_daily_bars",
        "ohlcv_source": "yfinance_daily_bars",
        "gates": [
            {"gate": name, "passed": True, "reason": "ok"}
            for name in PASS_GATES
        ],
        "sizing": {
            "quantity": 10,
            "entry_price": 99.0,
            "stop_loss": 98.0,
            "target_price": 106.0,
            "rr_ratio": 3.0,
            "risk_amount": 10.0,
            "position_value": 990.0,
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


@pytest.fixture
def wired_executor():
    inserted = []
    events = []
    execute_buy = MagicMock(return_value=(True, "ok"))

    def capture_row(row):
        inserted.append(deepcopy(row))

    def capture_event(event_type, stage, scan_id=None, symbol=None, payload=None):
        events.append({
            "event_type": event_type,
            "stage": stage,
            "scan_id": scan_id,
            "symbol": symbol,
            "payload": deepcopy(payload or {}),
        })

    with patch.object(executor, "_insert_row", side_effect=capture_row), \
         patch.object(executor.store, "add_notification"), \
         patch("paper_trader.get_portfolio",
               return_value={"positions": [], "cash": 100_000.0,
                             "total_value": 100_000.0}), \
         patch("paper_trader.execute_buy", execute_buy), \
         patch("risk_validation.pre_trade.validate_pre_trade",
               return_value=_ApprovedRisk()), \
         patch("model_versioning.get_active_version",
               return_value={"version": "quality-test"}), \
         patch("pipeline_events.emit", side_effect=capture_event), \
         patch("canonical_portfolio.build_canonical_portfolio",
               return_value={
                   "cash": 98_000.0,
                   "equity": 100_000.0,
                   "positions": [{"symbol": "TCS"}],
                   "realized_pnl": 0.0,
                   "unrealized_pnl": 0.0,
               }), \
         patch("kite_ltp_overlay.is_overlay_enabled", return_value=True):
        yield {
            "inserted": inserted,
            "events": events,
            "execute_buy": execute_buy,
        }


def _create(candidate, settings=None, trigger_source="AUTO"):
    return executor.create_paper_entry(
        candidate,
        settings or _settings(),
        scan_id="scan-quality",
        snapshot_ts="2026-08-19T04:30:00Z",
        trigger_source=trigger_source,
    )


def test_2x_quantity_reaches_risk_and_paper_execution(wired_executor):
    candidate = _candidate(
        confidence=86.0,
        opportunity_score=82.0,
        trade_quality_score=82.0,
        allocation_context={"previous_scan_3x_valid": False},
    )
    result = _create(candidate)
    assert result["created"] is True
    assert result["quantity"] == 20
    assert result["allocation_override"]["tier"] == "HIGH_QUALITY_2X"
    assert wired_executor["execute_buy"].call_args.args[1] == 20
    assert wired_executor["inserted"][0]["quantity"] == 20


def test_3x_decision_is_persisted_in_immutable_evidence(wired_executor):
    result = _create(_candidate())
    assert result["quantity"] == 30
    decision = wired_executor["inserted"][0]["evidence"][
        "quality_allocation_override"
    ]
    assert decision["tier"] == "EXCEPTIONAL_QUALITY_3X"
    assert decision["base_notional"] == 1_000.0
    assert decision["final_notional"] == 3_000.0
    assert decision["final_risk_amount"] == 60.0
    assert decision["paper_only"] is True
    assert decision["live_broker_orders_called"] is False


def test_complete_audit_events_are_emitted_for_3x(wired_executor):
    _create(_candidate())
    event_types = [event["event_type"] for event in wired_executor["events"]]
    assert "ALLOCATION_OVERRIDE_EVALUATED" in event_types
    assert "ALLOCATION_OVERRIDE_APPROVED_3X" in event_types
    approval = next(
        event for event in wired_executor["events"]
        if event["event_type"] == "ALLOCATION_OVERRIDE_APPROVED_3X"
    )
    payload = approval["payload"]
    for key in (
        "confidence",
        "opportunity_score",
        "trade_quality_score",
        "risk_reward",
        "execution_price_source",
        "requested_multiplier",
        "effective_multiplier",
        "base_notional",
        "requested_notional",
        "final_notional",
        "final_quantity",
        "risk_budget_amount",
        "final_risk_amount",
        "final_risk_pct",
        "exposure_after",
        "limiting_caps",
    ):
        assert key in payload


def test_low_quality_keeps_1x_and_emits_rejected_override(wired_executor):
    result = _create(_candidate(confidence=70.0))
    assert result["quantity"] == 10
    assert result["allocation_override"]["tier"] == "NORMAL"
    event_types = [event["event_type"] for event in wired_executor["events"]]
    assert "ALLOCATION_OVERRIDE_EVALUATED" in event_types
    assert "ALLOCATION_OVERRIDE_REJECTED" in event_types
    assert "ALLOCATION_OVERRIDE_APPROVED_2X" not in event_types
    assert "ALLOCATION_OVERRIDE_APPROVED_3X" not in event_types


def test_bootstrap_keeps_parallel_sizing_and_emits_no_override_events(
    wired_executor,
):
    result = _create(_candidate(), trigger_source="BOOTSTRAP_AUTO")
    assert result["quantity"] == 10
    assert result["allocation_override"]["reason"] == (
        "BOOTSTRAP_SIZING_PRESERVED"
    )
    assert not any(
        event["event_type"].startswith("ALLOCATION_OVERRIDE_")
        for event in wired_executor["events"]
    )


def test_no_live_broker_module_or_order_method_is_used(wired_executor):
    live_order = MagicMock(
        side_effect=AssertionError("live broker order must never be called")
    )
    with patch.dict(
        "sys.modules",
        {"broker_client": MagicMock(place_order_live=live_order)},
    ):
        result = _create(_candidate())
    assert result["created"] is True
    live_order.assert_not_called()
    wired_executor["execute_buy"].assert_called_once()


def test_duplicate_position_blocks_before_any_allocation_or_order():
    execute_buy = MagicMock(return_value=(True, "unexpected"))
    with patch("paper_trader.get_portfolio",
               return_value={"positions": [{"symbol": "TCS"}]}), \
         patch("paper_trader.execute_buy", execute_buy), \
         patch("pipeline_events.emit") as emit:
        result = _create(_candidate())
    assert result["created"] is False
    assert result["reason"] == "Open position exists"
    execute_buy.assert_not_called()
    emit.assert_not_called()


def test_postgresql_admission_failure_cannot_create_position(
    wired_executor,
):
    wired_executor["inserted"].clear()
    with patch.object(
        executor,
        "_insert_row",
        side_effect=executor.PaperEntryAdmissionError("DB unavailable"),
    ):
        result = _create(_candidate())
    assert result["created"] is False
    assert result["reason"] == "DB unavailable"
    assert result["allocation_override"]["continuity_eligible"] is False
    assert result["allocation_override"]["downstream_outcome"] == (
        "ADMISSION_REJECTED"
    )
    wired_executor["execute_buy"].assert_not_called()


def test_downstream_risk_rejection_cannot_qualify_next_scan(
    wired_executor,
):
    with patch(
        "risk_validation.pre_trade.validate_pre_trade",
        return_value=_RejectedRisk(),
    ):
        result = _create(_candidate())
    assert result["created"] is False
    assert result["allocation_override"]["three_x_quality_valid"] is True
    assert result["allocation_override"]["continuity_eligible"] is False
    assert result["allocation_override"]["downstream_outcome"] == (
        "RISK_REJECTED"
    )
    wired_executor["execute_buy"].assert_not_called()
    rejected = [
        event for event in wired_executor["events"]
        if event["event_type"] == "ALLOCATION_OVERRIDE_REJECTED"
    ]
    assert rejected
    assert rejected[-1]["payload"]["outcome"] == "REJECTED"


def test_risk_validator_outage_fails_closed_for_override(wired_executor):
    with patch(
        "risk_validation.pre_trade.validate_pre_trade",
        side_effect=RuntimeError("validator offline"),
    ):
        result = _create(_candidate())
    assert result["created"] is False
    assert result["reason"] == (
        "Risk validator unavailable for allocation override"
    )
    assert result["allocation_override"]["continuity_eligible"] is False
    assert result["allocation_override"]["downstream_outcome"] == (
        "RISK_VALIDATOR_UNAVAILABLE"
    )
    wired_executor["execute_buy"].assert_not_called()
    assert not wired_executor["inserted"]


def test_candidate_and_historical_identity_are_not_rewritten(wired_executor):
    candidate = _candidate(symbol="DRREDDY")
    before = deepcopy(candidate)
    result = _create(candidate)
    assert result["created"] is True
    assert candidate == before
    assert wired_executor["inserted"][0]["symbol"] == "DRREDDY"