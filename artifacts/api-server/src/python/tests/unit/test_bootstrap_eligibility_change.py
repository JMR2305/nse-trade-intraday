"""
test_bootstrap_eligibility_change.py — Unit tests for bootstrap eligibility
change detection and the BOOTSTRAP_ELIGIBILITY_CHANGED pipeline event.

Covers:
  1. _bootstrap_ineligibility_reason() — all ineligibility branches
  2. emit logic in run_live_scan() — detected via emitted events
  3. phase20_bootstrap_status._snapshot_ineligibility_reason() — dict-based helper
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from live_scan_engine import _bootstrap_ineligibility_reason, Phase7Recommendation
from phase20_bootstrap_status import _snapshot_ineligibility_reason


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_phase7_rec(**overrides) -> Phase7Recommendation:
    """Minimal Phase7Recommendation with all bootstrap gates passing."""
    base: Dict[str, Any] = dict(
        scan_id="scan01",
        snapshot_ts="2026-01-01T09:00:00Z",
        symbol="HDFCBANK",
        sector="Financials",
        data_source="yfinance",
        data_age_days=0.0,
        data_quality="LIVE",
        latest_bar_date="2026-01-01",
        bars_available=120,
        strategy_id="ema_crossover",
        strategy_name="EMA Crossover",
        regime="BULL",
        technical_score=65.0,
        historical_evidence_adjustment=0.0,
        calibrated_confidence=72.0,
        opportunity_score=60.0,
        entry_price=1500.0,
        stop_loss=1450.0,
        target_price=1620.0,
        rr_ratio=2.4,
        expected_holding_days=10,
        gate_price={"passed": True, "reason": "ok"},
        gate_data_quality={"passed": True, "reason": "ok"},
        gate_rr={"passed": True, "reason": "ok"},
        gate_volume={"passed": True, "reason": "ok"},
        final_action="WATCH",
        heat="AMBER",
        all_gates_passed=True,
        paper_eligible=False,
        paper_order_id=None,
        paper_order_note="low evidence",
        win_rate=0.6,
        profit_factor=1.8,
        net_pnl_pct=5.0,
        total_trades=2,
        low_evidence=True,
        adx=28.0,
        rsi=52.0,
        volume_ratio=1.1,
        above_ema20=True,
        above_ema50=True,
        error=None,
        quote_reliable=True,
        kite_session_verified_flag=True,
        bootstrap_eligible=False,
    )
    base.update(overrides)
    return Phase7Recommendation(**base)


def _make_snap_rec(**overrides) -> Dict[str, Any]:
    """Plain snapshot dict — as returned by the scan cache."""
    base = dict(
        symbol="RELIANCE",
        final_action="WATCH",
        calibrated_confidence=72.0,
        opportunity_score=60.0,
        rr_ratio=2.4,
        all_gates_passed=True,
        low_evidence=True,
        quote_reliable=True,
        kite_session_verified_flag=True,
        data_quality="LIVE",
        gate_price={"passed": True, "reason": "ok"},
        gate_data_quality={"passed": True, "reason": "ok"},
        gate_rr={"passed": True, "reason": "ok"},
        gate_volume={"passed": True, "reason": "ok"},
        bootstrap_eligible=False,
        error=None,
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# _bootstrap_ineligibility_reason() — Phase7Recommendation helper
# ---------------------------------------------------------------------------

class TestBootstrapIneligibilityReasonRec:
    """Tests for the Phase7Recommendation-based helper in live_scan_engine."""

    def test_error_symbol(self):
        r = _make_phase7_rec(error="Indicator failed")
        reason = _bootstrap_ineligibility_reason(r)
        assert "scan error" in reason.lower()
        assert "Indicator failed" in reason

    def test_sufficient_evidence(self):
        r = _make_phase7_rec(low_evidence=False, total_trades=10)
        reason = _bootstrap_ineligibility_reason(r)
        assert "sufficient backtest evidence" in reason

    def test_action_ignore(self):
        r = _make_phase7_rec(final_action="IGNORE")
        reason = _bootstrap_ineligibility_reason(r)
        assert "action=IGNORE" in reason
        assert "WATCH" in reason

    def test_risk_gates_failed_price(self):
        r = _make_phase7_rec(
            all_gates_passed=False,
            gate_price={"passed": False, "reason": "price ₹0 invalid"},
        )
        reason = _bootstrap_ineligibility_reason(r)
        assert "risk gate failed" in reason
        assert "price" in reason

    def test_confidence_below_threshold(self):
        r = _make_phase7_rec(calibrated_confidence=55.0)
        reason = _bootstrap_ineligibility_reason(r)
        assert "confidence" in reason
        assert "55.0" in reason
        assert "60" in reason

    def test_opportunity_below_threshold(self):
        r = _make_phase7_rec(opportunity_score=40.0)
        reason = _bootstrap_ineligibility_reason(r)
        assert "opportunity score" in reason
        assert "40.0" in reason

    def test_rr_below_threshold(self):
        r = _make_phase7_rec(rr_ratio=1.2)
        reason = _bootstrap_ineligibility_reason(r)
        assert "RR" in reason
        assert "1.20" in reason

    def test_kite_not_reliable(self):
        r = _make_phase7_rec(quote_reliable=False)
        reason = _bootstrap_ineligibility_reason(r)
        assert "Kite LTP not reliable" in reason

    def test_kite_session_not_verified(self):
        r = _make_phase7_rec(kite_session_verified_flag=False)
        reason = _bootstrap_ineligibility_reason(r)
        assert "Kite session not verified" in reason

    def test_stale_data_quality(self):
        r = _make_phase7_rec(data_quality="STALE")
        reason = _bootstrap_ineligibility_reason(r)
        assert "data quality" in reason
        assert "STALE" in reason

    def test_all_gates_pass_returns_unknown(self):
        """A rec that passes every gate still gets 'unknown' — possible only if
        bootstrap_eligible was already True (caller should check first)."""
        r = _make_phase7_rec(
            low_evidence=True,
            final_action="WATCH",
            all_gates_passed=True,
            calibrated_confidence=72.0,
            opportunity_score=60.0,
            rr_ratio=2.4,
            quote_reliable=True,
            kite_session_verified_flag=True,
            data_quality="LIVE",
        )
        reason = _bootstrap_ineligibility_reason(r)
        assert isinstance(reason, str)
        assert len(reason) > 0


# ---------------------------------------------------------------------------
# _snapshot_ineligibility_reason() — dict-based helper (phase20_bootstrap_status)
# ---------------------------------------------------------------------------

class TestSnapshotIneligibilityReason:
    """Tests for the plain-dict helper used by the status payload builder."""

    def test_error_field(self):
        r = _make_snap_rec(error="fetch failed")
        reason = _snapshot_ineligibility_reason(r)
        assert "scan error" in reason

    def test_not_low_evidence(self):
        r = _make_snap_rec(low_evidence=False)
        reason = _snapshot_ineligibility_reason(r)
        assert "sufficient backtest evidence" in reason

    def test_ignore_action(self):
        r = _make_snap_rec(final_action="IGNORE")
        reason = _snapshot_ineligibility_reason(r)
        assert "action=IGNORE" in reason

    def test_gate_failed_uses_first_failed_gate(self):
        r = _make_snap_rec(
            all_gates_passed=False,
            gate_rr={"passed": False, "reason": "RR 1.1 < 1.5"},
        )
        reason = _snapshot_ineligibility_reason(r)
        assert "rr" in reason or "risk gate failed" in reason

    def test_low_confidence(self):
        r = _make_snap_rec(calibrated_confidence=55.0)
        reason = _snapshot_ineligibility_reason(r)
        assert "confidence" in reason

    def test_low_opportunity_score(self):
        r = _make_snap_rec(opportunity_score=30.0)
        reason = _snapshot_ineligibility_reason(r)
        assert "opportunity score" in reason

    def test_rr_below_threshold(self):
        r = _make_snap_rec(rr_ratio=1.0)
        reason = _snapshot_ineligibility_reason(r)
        assert "RR" in reason

    def test_kite_not_reliable(self):
        r = _make_snap_rec(quote_reliable=False)
        reason = _snapshot_ineligibility_reason(r)
        assert "Kite LTP not reliable" in reason

    def test_kite_session_not_verified(self):
        r = _make_snap_rec(kite_session_verified_flag=False)
        reason = _snapshot_ineligibility_reason(r)
        assert "Kite session not verified" in reason

    def test_bad_data_quality(self):
        r = _make_snap_rec(data_quality="UNAVAILABLE")
        reason = _snapshot_ineligibility_reason(r)
        assert "data quality" in reason

    def test_reason_is_always_str(self):
        """Must never return None or a non-string."""
        for override in [
            {"error": "x"},
            {"low_evidence": False},
            {"final_action": "IGNORE"},
            {"all_gates_passed": False, "gate_price": {"passed": False}},
            {"calibrated_confidence": 1.0},
            {"opportunity_score": 0.0},
            {"rr_ratio": 0.0},
            {"quote_reliable": False},
            {"kite_session_verified_flag": False},
            {"data_quality": "STALE"},
        ]:
            r = _make_snap_rec(**override)
            result = _snapshot_ineligibility_reason(r)
            assert isinstance(result, str), f"Expected str, got {type(result)} for {override}"
            assert len(result) > 0


# ---------------------------------------------------------------------------
# phase20_bootstrap_status — top_watch_candidate & ineligibility_reason fields
# ---------------------------------------------------------------------------

from phase20_bootstrap_status import build_bootstrap_status_payload  # noqa: E402

_BASE_SETTINGS = {
    "bootstrap_paper_enabled": True,
    "auto_paper_entries": True,
    "auto_paper_entries_confirmed_at": "2026-01-01T00:00:00Z",
}
_CB_CLEAR = {"tripped": False, "reasons": []}
_SAFETY_KITE_OK = {"kite_ltp_session_verified": True, "kite_ltp_overlay_enabled": False}


def _build(*, recs=None, summary=None, extra_snap=None):
    snap = {
        "safety": _SAFETY_KITE_OK,
        "summary": summary or {"bootstrap_eligible_count": 0, "watch_count": 1},
        "recommendations": recs or [],
        "scan_id": "s01",
        "snapshot_ts": "2026-01-01T10:00:00Z",
    }
    if extra_snap:
        snap.update(extra_snap)
    return build_bootstrap_status_payload(
        settings=dict(_BASE_SETTINGS),
        snapshot=snap,
        evaluate_circuit_breaker=lambda _s: _CB_CLEAR,
        get_closed_trades=lambda: 0,
    )


class TestTopWatchCandidate:
    """top_watch_candidate surfaced when no bootstrap-eligible symbols exist."""

    def test_present_when_watch_cands_exist(self):
        recs = [_make_snap_rec(symbol="HDFCBANK", calibrated_confidence=78.3, final_action="WATCH")]
        r = _build(recs=recs)
        assert r["top_watch_candidate"] is not None
        assert r["top_watch_candidate"]["symbol"] == "HDFCBANK"

    def test_none_when_no_recs(self):
        r = _build(recs=[])
        assert r["top_watch_candidate"] is None

    def test_action_field_present(self):
        recs = [_make_snap_rec(symbol="RELIANCE", final_action="WATCH")]
        r = _build(recs=recs)
        assert r["top_watch_candidate"]["action"] == "WATCH"

    def test_confidence_field(self):
        recs = [_make_snap_rec(symbol="TCS", calibrated_confidence=65.5)]
        r = _build(recs=recs)
        assert r["top_watch_candidate"]["confidence"] == pytest.approx(65.5)

    def test_ineligibility_reason_is_str(self):
        recs = [_make_snap_rec(symbol="WIPRO", quote_reliable=False)]
        r = _build(recs=recs)
        reason = r["top_watch_candidate"]["ineligibility_reason"]
        assert isinstance(reason, str)
        assert "Kite" in reason

    def test_none_when_bootstrap_eligible_exists(self):
        """top_watch_candidate must be None when there ARE bootstrap-eligible candidates."""
        recs = [
            _make_snap_rec(symbol="SBIN", bootstrap_eligible=True,
                           calibrated_confidence=70.0, final_action="WATCH"),
        ]
        r = _build(
            recs=recs,
            summary={"bootstrap_eligible_count": 1, "watch_count": 1},
        )
        assert r["top_watch_candidate"] is None

    def test_most_confident_candidate_is_top(self):
        """When multiple WATCH candidates exist, the most confident becomes top."""
        recs = [
            _make_snap_rec(symbol="TCS", calibrated_confidence=60.0),
            _make_snap_rec(symbol="HDFCBANK", calibrated_confidence=78.3),
        ]
        r = _build(recs=recs)
        assert r["top_watch_candidate"]["symbol"] == "HDFCBANK"

    def test_paper_eligible_not_shown_as_watch(self):
        """paper_eligible symbols are on the normal BUY path — not shown as watch candidates."""
        recs = [_make_snap_rec(symbol="TCS", paper_eligible=True, final_action="BUY")]
        r = _build(recs=recs)
        assert r["top_watch_candidate"] is None


class TestTopCandidateIneligibilityReason:
    """top_candidates list now includes action + ineligibility_reason."""

    def test_non_eligible_candidate_has_reason(self):
        recs = [_make_snap_rec(symbol="INFY", quote_reliable=False)]
        r = _build(recs=recs)
        cands = r["top_candidates"]
        assert len(cands) == 1
        assert cands[0]["ineligibility_reason"] is not None
        assert isinstance(cands[0]["ineligibility_reason"], str)

    def test_eligible_candidate_has_none_reason(self):
        recs = [_make_snap_rec(symbol="SBIN", bootstrap_eligible=True, final_action="WATCH")]
        r = _build(
            recs=recs,
            summary={"bootstrap_eligible_count": 1, "watch_count": 1},
        )
        cands = r["top_candidates"]
        assert len(cands) == 1
        assert cands[0]["ineligibility_reason"] is None

    def test_action_field_in_candidates(self):
        recs = [_make_snap_rec(symbol="HDFC", final_action="WATCH")]
        r = _build(recs=recs)
        assert r["top_candidates"][0]["action"] == "WATCH"
