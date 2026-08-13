"""
test_journey_execution_labels.py

Regression guard for _build_symbol_journey() execution step labelling.

The old bug: paper_eligible=True in the snapshot caused the journey to show
"Paper order placed" even when no order existed in the ledger.  These tests
confirm the fix cannot silently revert.

Cases covered
─────────────
1. EXECUTION_SKIPPED_WITH_REASON (R:R gate) → SKIPPED, never "Paper order placed"
2. ORDER_REJECTED                            → REJECTED
3. ORDER_SUBMITTED                           → PAPER BUY, reason = "Paper order placed and recorded"
4. No execution event, paper_eligible=True   → ELIGIBLE, reason contains "not recorded"
5. No execution event, paper_eligible=False  → SKIPPED

Dual-threshold R:R gap warning (Task #672)
──────────────────────────────────────────
6. Risk Agent approved + SKIPPED + min_risk_reward in failed_gates
   → dual_threshold_warning is a non-empty string
7. Risk Agent rejected + SKIPPED + min_risk_reward in failed_gates
   → dual_threshold_warning is None (gap only when Risk approved)
8. Risk Agent approved + ORDER_REJECTED + min_risk_reward in failed_gates
   → dual_threshold_warning is None (gap only for SKIPPED, not REJECTED)
9. Risk Agent approved + SKIPPED, only per_stock_cap failed (no RR gate)
   → dual_threshold_warning is None (no RR gap)
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from replay_engine import _build_symbol_journey, _pick_highest_priority_exec_event  # noqa: E402

# ── Minimal helpers ──────────────────────────────────────────────────────────

def _rec(**kw):
    """Build a minimal snapshot recommendation row."""
    base = {
        "symbol": "TEST",
        "final_action": "BUY",
        "paper_eligible": True,
        "all_gates_passed": True,
        "strategy_id": "mean_reversion",
        "data_quality": "LIVE",
        "rr_ratio": 1.5,
        "technical_score": 70.0,
        "calibrated_confidence": 73.0,
        "opportunity_score": 63.0,
    }
    base.update(kw)
    return base


_SNAP = {"snapshot_ts": "2026-08-13T09:30:00Z"}

NEVER_LABEL = "Paper order placed"  # must NEVER appear in result or reason


def _exec_step(journey):
    """Return the execution step from a journey list."""
    for step in journey:
        if step["stage"] == "execution":
            return step
    raise AssertionError("execution step missing from journey")


# ── Label tests ──────────────────────────────────────────────────────────────

class TestExecutionStepLabels:
    """Each test targets one concrete execution_outcome path."""

    def test_case1_skipped_with_rr_reason_never_paper_order_placed(self):
        """EXECUTION_SKIPPED_WITH_REASON → SKIPPED; 'Paper order placed' never appears."""
        eo = {
            "event_type": "EXECUTION_SKIPPED_WITH_REASON",
            "failed_gates": ["min_risk_reward"],
            "failed_gate_reasons": {"min_risk_reward": "R:R 1.5 vs minimum 2.0"},
        }
        journey = _build_symbol_journey(_rec(), _SNAP, execution_outcome=eo)
        step = _exec_step(journey)

        assert step["result"] == "SKIPPED", f"expected SKIPPED, got {step['result']!r}"
        assert NEVER_LABEL not in step["reason"], (
            f"'Paper order placed' must not appear in reason: {step['reason']!r}"
        )
        # Gate text from the event payload must surface in the reason
        assert "1.5" in step["reason"] or "2.0" in step["reason"] or "skipped" in step["reason"].lower(), (
            f"Gate text missing from reason: {step['reason']!r}"
        )

    def test_case2_order_rejected(self):
        """ORDER_REJECTED → REJECTED."""
        eo = {"event_type": "ORDER_REJECTED"}
        journey = _build_symbol_journey(_rec(), _SNAP, execution_outcome=eo)
        step = _exec_step(journey)

        assert step["result"] == "REJECTED", f"expected REJECTED, got {step['result']!r}"
        assert NEVER_LABEL not in step["reason"]

    def test_case3_order_submitted_is_paper_buy(self):
        """ORDER_SUBMITTED → PAPER BUY with 'Paper order placed and recorded'."""
        eo = {"event_type": "ORDER_SUBMITTED"}
        journey = _build_symbol_journey(_rec(), _SNAP, execution_outcome=eo)
        step = _exec_step(journey)

        assert step["result"] == "PAPER BUY", f"expected PAPER BUY, got {step['result']!r}"
        assert step["reason"] == "Paper order placed and recorded", (
            f"unexpected reason: {step['reason']!r}"
        )

    def test_case3_order_executed_also_is_paper_buy(self):
        """ORDER_EXECUTED is treated identically to ORDER_SUBMITTED."""
        eo = {"event_type": "ORDER_EXECUTED"}
        journey = _build_symbol_journey(_rec(), _SNAP, execution_outcome=eo)
        step = _exec_step(journey)

        assert step["result"] == "PAPER BUY"
        assert step["reason"] == "Paper order placed and recorded"

    def test_case4_no_event_paper_eligible_true_never_paper_order_placed(self):
        """No execution event + paper_eligible=True → ELIGIBLE, reason contains 'not recorded'."""
        journey = _build_symbol_journey(_rec(paper_eligible=True), _SNAP, execution_outcome=None)
        step = _exec_step(journey)

        assert step["result"] == "ELIGIBLE", f"expected ELIGIBLE, got {step['result']!r}"
        assert NEVER_LABEL not in step["reason"], (
            f"'Paper order placed' must not appear: {step['reason']!r}"
        )
        assert "not recorded" in step["reason"], (
            f"Reason should mention 'not recorded': {step['reason']!r}"
        )

    def test_case5_no_event_paper_eligible_false_skipped(self):
        """No execution event + paper_eligible=False + non-BUY action → SKIPPED."""
        journey = _build_symbol_journey(
            _rec(paper_eligible=False, final_action="WATCH"),
            _SNAP,
            execution_outcome=None,
        )
        step = _exec_step(journey)

        assert step["result"] == "SKIPPED", f"expected SKIPPED, got {step['result']!r}"
        assert NEVER_LABEL not in step["reason"]

    def test_case5_no_event_paper_eligible_false_buy_action_rejected(self):
        """No execution event + paper_eligible=False + BUY action → REJECTED (not eligible)."""
        journey = _build_symbol_journey(
            _rec(paper_eligible=False, final_action="BUY"),
            _SNAP,
            execution_outcome=None,
        )
        step = _exec_step(journey)

        assert step["result"] == "REJECTED", f"expected REJECTED, got {step['result']!r}"
        assert NEVER_LABEL not in step["reason"]


# ── Dual-threshold warning tests (Task #672 guard) ──────────────────────────

class TestDualThresholdWarning:
    """The execution step detail.dual_threshold_warning must fire exactly when
    the Risk Agent approved AND the execution skipped due to R:R."""

    def test_case6_rr_gap_warning_fires_when_risk_approved_and_skipped(self):
        """Risk Agent approved + SKIPPED + min_risk_reward in failed_gates → warning."""
        eo = {
            "event_type": "EXECUTION_SKIPPED_WITH_REASON",
            "failed_gates": ["min_risk_reward"],
            "failed_gate_reasons": {"min_risk_reward": "R:R 1.50 vs minimum 2.0"},
        }
        journey = _build_symbol_journey(
            _rec(all_gates_passed=True, rr_ratio=1.5),
            _SNAP,
            execution_outcome=eo,
        )
        step = _exec_step(journey)
        warning = (step.get("detail") or {}).get("dual_threshold_warning")

        assert isinstance(warning, str) and warning, (
            f"dual_threshold_warning should be a non-empty string, got: {warning!r}"
        )
        # Must not hardcode a specific threshold — threshold comes from the event payload
        assert "2.0" in warning, (
            f"Warning should reference the configured execution minimum from the payload: {warning!r}"
        )
        assert "1.50" in warning or "1.5" in warning, (
            f"Warning should show the actual R:R from the payload: {warning!r}"
        )

    def test_case6_rr_gap_custom_threshold_reflected(self):
        """Warning shows the configured threshold (2.5), not a hardcoded 2.0."""
        eo = {
            "event_type": "EXECUTION_SKIPPED_WITH_REASON",
            "failed_gates": ["min_risk_reward"],
            "failed_gate_reasons": {"min_risk_reward": "R:R 1.80 vs minimum 2.5"},
        }
        journey = _build_symbol_journey(
            _rec(all_gates_passed=True, rr_ratio=1.8),
            _SNAP,
            execution_outcome=eo,
        )
        step = _exec_step(journey)
        warning = (step.get("detail") or {}).get("dual_threshold_warning")

        assert isinstance(warning, str) and warning
        assert "2.5" in warning, (
            f"Warning must reflect live threshold (2.5), not a hardcoded constant: {warning!r}"
        )
        assert "2.0" not in warning, (
            f"Hardcoded 2.0 must not appear when configured threshold is 2.5: {warning!r}"
        )

    def test_case7_no_warning_when_risk_agent_also_rejected(self):
        """Risk Agent rejected (all_gates_passed=False) + SKIPPED → no warning (no gap)."""
        eo = {
            "event_type": "EXECUTION_SKIPPED_WITH_REASON",
            "failed_gates": ["min_risk_reward"],
            "failed_gate_reasons": {"min_risk_reward": "R:R 1.50 vs minimum 2.0"},
        }
        journey = _build_symbol_journey(
            _rec(all_gates_passed=False, rr_ratio=1.5),
            _SNAP,
            execution_outcome=eo,
        )
        step = _exec_step(journey)
        warning = (step.get("detail") or {}).get("dual_threshold_warning")

        assert warning is None, (
            f"dual_threshold_warning must be None when Risk Agent also rejected: {warning!r}"
        )

    def test_case8_no_warning_for_order_rejected_event(self):
        """ORDER_REJECTED (not SKIPPED) + min_risk_reward → no warning; gap is SKIPPED-only."""
        eo = {
            "event_type": "ORDER_REJECTED",
            "failed_gates": ["min_risk_reward"],
            "failed_gate_reasons": {"min_risk_reward": "R:R 1.50 vs minimum 2.0"},
        }
        journey = _build_symbol_journey(
            _rec(all_gates_passed=True, rr_ratio=1.5),
            _SNAP,
            execution_outcome=eo,
        )
        step = _exec_step(journey)
        warning = (step.get("detail") or {}).get("dual_threshold_warning")

        assert warning is None, (
            f"dual_threshold_warning must be None for ORDER_REJECTED events: {warning!r}"
        )

    def test_case9_no_warning_when_rr_gate_not_in_failed_gates(self):
        """SKIPPED for per_stock_cap only (no RR gate failure) → no dual-threshold warning."""
        eo = {
            "event_type": "EXECUTION_SKIPPED_WITH_REASON",
            "failed_gates": ["per_stock_cap"],
            "failed_gate_reasons": {"per_stock_cap": "Post-trade exposure 34.4% (cap 25%)"},
        }
        journey = _build_symbol_journey(
            _rec(all_gates_passed=True, rr_ratio=1.5),
            _SNAP,
            execution_outcome=eo,
        )
        step = _exec_step(journey)
        warning = (step.get("detail") or {}).get("dual_threshold_warning")

        assert warning is None, (
            f"dual_threshold_warning must be None when only per_stock_cap blocked: {warning!r}"
        )


# ── Seal-vs-executor race condition guard (Task #681) ───────────────────────

class TestPickHighestPriorityExecEvent:
    """
    Unit tests for _pick_highest_priority_exec_event — the consumer-side guard
    that ensures ORDER_EXECUTED always wins over EXECUTION_SKIPPED_WITH_REASON
    even when the seal inserted the SKIPPED event at a later timestamp (and
    therefore a higher id) than the executor's ORDER_EXECUTED row.
    """

    def _ev(self, event_type: str, id_: int) -> dict:
        return {"id": id_, "event_type": event_type, "payload": {}}

    def test_empty_list_returns_none(self):
        assert _pick_highest_priority_exec_event([]) is None

    def test_single_event_returned_as_is(self):
        ev = self._ev("ORDER_EXECUTED", 1)
        assert _pick_highest_priority_exec_event([ev]) is ev

    def test_order_executed_beats_skipped_regardless_of_id(self):
        """Core race-condition guard: ORDER_EXECUTED (lower id) wins over
        EXECUTION_SKIPPED_WITH_REASON (higher id = arrived later)."""
        executed = self._ev("ORDER_EXECUTED",                1)
        skipped  = self._ev("EXECUTION_SKIPPED_WITH_REASON", 2)
        result = _pick_highest_priority_exec_event([skipped, executed])
        assert result["event_type"] == "ORDER_EXECUTED", (
            f"ORDER_EXECUTED must win even with a smaller id; got {result['event_type']!r}"
        )

    def test_order_executed_beats_skipped_when_ids_reversed(self):
        """Same priority test with the list in opposite insertion order."""
        executed = self._ev("ORDER_EXECUTED",                5)
        skipped  = self._ev("EXECUTION_SKIPPED_WITH_REASON", 10)
        result = _pick_highest_priority_exec_event([executed, skipped])
        assert result["event_type"] == "ORDER_EXECUTED"

    def test_order_executed_beats_order_rejected(self):
        executed = self._ev("ORDER_EXECUTED", 1)
        rejected = self._ev("ORDER_REJECTED", 2)
        result = _pick_highest_priority_exec_event([rejected, executed])
        assert result["event_type"] == "ORDER_EXECUTED"

    def test_order_rejected_beats_submitted(self):
        """Lifecycle regression: ORDER_SUBMITTED is a progress marker; a later
        ORDER_REJECTED (definitive failure) must always win over it."""
        submitted = self._ev("ORDER_SUBMITTED", 10)
        rejected  = self._ev("ORDER_REJECTED",  11)   # higher id = arrived later
        result = _pick_highest_priority_exec_event([submitted, rejected])
        assert result["event_type"] == "ORDER_REJECTED", (
            f"ORDER_REJECTED must beat ORDER_SUBMITTED; got {result['event_type']!r}"
        )

    def test_order_cancelled_beats_submitted(self):
        """Lifecycle regression: ORDER_SUBMITTED emitted before duplicate-slot
        claim; ORDER_CANCELLED (concurrent duplicate) must win even with a
        smaller id (arrived first in the same atomic sequence)."""
        submitted = self._ev("ORDER_SUBMITTED", 10)
        cancelled = self._ev("ORDER_CANCELLED",  11)   # higher id = arrived later
        result = _pick_highest_priority_exec_event([submitted, cancelled])
        assert result["event_type"] == "ORDER_CANCELLED", (
            f"ORDER_CANCELLED must beat ORDER_SUBMITTED; got {result['event_type']!r}"
        )

    def test_skipped_beats_submitted(self):
        """ORDER_SUBMITTED is the lowest-priority event; even the seal fallback
        EXECUTION_SKIPPED_WITH_REASON wins over it."""
        submitted = self._ev("ORDER_SUBMITTED",              5)
        skipped   = self._ev("EXECUTION_SKIPPED_WITH_REASON", 6)
        result = _pick_highest_priority_exec_event([submitted, skipped])
        assert result["event_type"] == "EXECUTION_SKIPPED_WITH_REASON", (
            f"EXECUTION_SKIPPED_WITH_REASON must beat ORDER_SUBMITTED; got {result['event_type']!r}"
        )

    def test_same_priority_picks_highest_id(self):
        """Two SKIPPED events for the same symbol → pick the most recent (highest id)."""
        old_skip = self._ev("EXECUTION_SKIPPED_WITH_REASON", 10)
        new_skip = self._ev("EXECUTION_SKIPPED_WITH_REASON", 20)
        result = _pick_highest_priority_exec_event([old_skip, new_skip])
        assert result["id"] == 20, (
            f"Most recent (highest id) skipped event should be chosen; got id={result['id']}"
        )

    def test_full_priority_ladder(self):
        """ORDER_EXECUTED wins over all other terminal types regardless of id."""
        events = [
            self._ev("EXECUTION_SKIPPED_WITH_REASON", 100),
            self._ev("ORDER_CANCELLED",                90),
            self._ev("ORDER_REJECTED",                 80),
            self._ev("ORDER_SUBMITTED",                70),
            self._ev("ORDER_EXECUTED",                  1),   # lowest id but highest priority
        ]
        result = _pick_highest_priority_exec_event(events)
        assert result["event_type"] == "ORDER_EXECUTED"


class TestRaceConditionJourneyOutcome:
    """
    Regression guard: when both ORDER_EXECUTED and EXECUTION_SKIPPED_WITH_REASON
    exist for the same (scan_id, symbol), the Agent Journey must show PAPER BUY
    (not SKIPPED).  The consumer selects ORDER_EXECUTED via priority ordering;
    _build_symbol_journey receives only the winner.
    """

    def test_journey_shows_paper_buy_when_executed_wins_race(self):
        """Simulates the consumer selecting ORDER_EXECUTED despite the seal's
        EXECUTION_SKIPPED_WITH_REASON arriving later (higher id/ts)."""
        events = [
            {"id": 1, "event_type": "ORDER_EXECUTED",                "payload": {}},
            {"id": 2, "event_type": "EXECUTION_SKIPPED_WITH_REASON", "payload": {
                "reason": "auto_paper_entries_off",
                "auto_entry_attempted": False,
            }},
        ]
        # Consumer picks the winner via priority ordering
        winner = _pick_highest_priority_exec_event(events)
        assert winner is not None
        assert winner["event_type"] == "ORDER_EXECUTED"

        # Journey built from the winner shows PAPER BUY, not SKIPPED
        eo = {"event_type": winner["event_type"], **winner["payload"]}
        journey = _build_symbol_journey(_rec(), _SNAP, execution_outcome=eo)
        step = _exec_step(journey)
        assert step["result"] == "PAPER BUY", (
            f"Journey must show PAPER BUY when ORDER_EXECUTED wins the race; "
            f"got {step['result']!r}"
        )

    def test_journey_shows_skipped_when_no_execution_event_only_seal(self):
        """When only a seal SKIPPED event exists (auto OFF, no race), SKIPPED is correct."""
        events = [
            {"id": 5, "event_type": "EXECUTION_SKIPPED_WITH_REASON", "payload": {
                "reason": "auto_paper_entries_off",
                "auto_entry_attempted": False,
            }},
        ]
        winner = _pick_highest_priority_exec_event(events)
        assert winner["event_type"] == "EXECUTION_SKIPPED_WITH_REASON"

        eo = {"event_type": winner["event_type"], **winner["payload"]}
        journey = _build_symbol_journey(_rec(), _SNAP, execution_outcome=eo)
        step = _exec_step(journey)
        assert step["result"] == "SKIPPED", (
            f"Journey must show SKIPPED when only seal event exists; got {step['result']!r}"
        )

    def test_submitted_then_cancelled_shows_cancelled(self):
        """Lifecycle regression: ORDER_SUBMITTED emitted first, then ORDER_CANCELLED
        on a concurrent duplicate claim.  Journey must show REJECTED, not PAPER BUY."""
        events = [
            {"id": 10, "event_type": "ORDER_SUBMITTED", "payload": {}},
            {"id": 11, "event_type": "ORDER_CANCELLED",  "payload": {
                "reason": "Open Phase 20 trade already exists (concurrent claim)"}},
        ]
        winner = _pick_highest_priority_exec_event(events)
        assert winner["event_type"] == "ORDER_CANCELLED", (
            f"ORDER_CANCELLED must win over ORDER_SUBMITTED; got {winner['event_type']!r}"
        )
        # The journey must NOT show PAPER BUY for a cancelled order
        eo = {"event_type": winner["event_type"], **winner["payload"]}
        journey = _build_symbol_journey(_rec(), _SNAP, execution_outcome=eo)
        step = _exec_step(journey)
        assert step["result"] != "PAPER BUY", (
            f"Journey must not show PAPER BUY for a cancelled order; got {step['result']!r}"
        )

    def test_submitted_then_rejected_shows_rejected(self):
        """Lifecycle regression: ORDER_SUBMITTED emitted first, then ORDER_REJECTED
        when execute_buy() fails.  Journey must show REJECTED, not PAPER BUY."""
        events = [
            {"id": 20, "event_type": "ORDER_SUBMITTED", "payload": {}},
            {"id": 21, "event_type": "ORDER_REJECTED",  "payload": {
                "reason": "Insufficient paper cash"}},
        ]
        winner = _pick_highest_priority_exec_event(events)
        assert winner["event_type"] == "ORDER_REJECTED", (
            f"ORDER_REJECTED must win over ORDER_SUBMITTED; got {winner['event_type']!r}"
        )
        eo = {"event_type": winner["event_type"], **winner["payload"]}
        journey = _build_symbol_journey(_rec(), _SNAP, execution_outcome=eo)
        step = _exec_step(journey)
        assert step["result"] == "REJECTED", (
            f"Journey must show REJECTED when order was rejected; got {step['result']!r}"
        )
