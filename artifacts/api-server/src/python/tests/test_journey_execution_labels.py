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
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from replay_engine import (  # noqa: E402
    _build_symbol_journey,
    _pick_highest_priority_exec_event,
    _get_rr_gap_symbols_for_scan,
    _load_risk_approved_for_scan,
    get_rr_gap_symbols,
)

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

    def test_case10_fallback_reflects_live_settings_not_hardcoded(self):
        """Fallback path (no gate-reason string in payload) reads live settings.

        When the execution event carries min_risk_reward in failed_gates but
        provides NO gate-reason string, the fallback must read the live
        configured min_risk_reward from phase20_store.get_settings() rather than
        emitting a hardcoded "2.0".  Mocking get_settings to return 2.8 confirms
        the fallback text tracks the live value.
        """
        eo = {
            "event_type": "EXECUTION_SKIPPED_WITH_REASON",
            "failed_gates": ["min_risk_reward"],
            # Intentionally omit failed_gate_reasons so the fallback path fires
            "failed_gate_reasons": {},
        }
        with patch(
            "replay_engine.phase20_store",
            create=True,
        ):
            # Patch get_settings inside the replay_engine module's import scope
            import replay_engine as _re_mod
            import types
            _fake_store = types.ModuleType("phase20_store")
            _fake_store.get_settings = lambda: {"min_risk_reward": 2.8}
            import sys as _sys
            _sys.modules["phase20_store"] = _fake_store

            try:
                journey = _build_symbol_journey(
                    _rec(all_gates_passed=True, rr_ratio=1.6),
                    _SNAP,
                    execution_outcome=eo,
                )
            finally:
                # Restore the real module so other tests are unaffected
                import importlib as _il
                try:
                    _sys.modules["phase20_store"] = _il.import_module("phase20_store")
                except Exception:
                    _sys.modules.pop("phase20_store", None)

        step = _exec_step(journey)
        warning = (step.get("detail") or {}).get("dual_threshold_warning")

        assert isinstance(warning, str) and warning, (
            f"dual_threshold_warning must be a non-empty string in fallback path, got: {warning!r}"
        )
        assert "2.8" in warning, (
            f"Fallback warning must reflect live configured min_risk_reward (2.8), not a "
            f"hardcoded constant: {warning!r}"
        )
        assert "2.0" not in warning, (
            f"Hardcoded 2.0 must not appear when live min_risk_reward is 2.8: {warning!r}"
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


# ── R:R gap symbol detection ──────────────────────────────────────────────────

class TestGetRrGapSymbolsForScan:
    """
    Unit tests for _get_rr_gap_symbols_for_scan() and get_rr_gap_symbols().

    Regression guard: the rr_gap annotation on /live-data/scan must be scoped
    to the concrete scan_id returned by the scan fetch — never resolved
    independently from scan_state, which could produce cross-scan annotations
    during a forced refresh or scan-state transition.
    """

    def _make_skip_event(self, scan_id: str, symbol: str, failed_gates: list,
                         ev_id: int = 1) -> dict:
        """Build an EXECUTION_SKIPPED_WITH_REASON event row."""
        return {
            "id": ev_id,
            "scan_id": scan_id,
            "symbol": symbol,
            "event_type": "EXECUTION_SKIPPED_WITH_REASON",
            "payload": {
                "failed_gates": failed_gates,
                "failed_gate_reasons": {g: f"{g} reason" for g in failed_gates},
            },
        }

    def _make_executed_event(self, scan_id: str, symbol: str,
                             ev_id: int = 2) -> dict:
        """Build an ORDER_EXECUTED event row (higher priority than SKIPPED)."""
        return {
            "id": ev_id,
            "scan_id": scan_id,
            "symbol": symbol,
            "event_type": "ORDER_EXECUTED",
            "payload": {},
        }

    # ── Patch helper ─────────────────────────────────────────────────────────
    # _get_rr_gap_symbols_for_scan imports pipeline_events locally (inside the
    # function), so we must patch via patch.object on the already-imported
    # module — not via "replay_engine.pipeline_events" which is not a
    # module-level attribute.
    @staticmethod
    def _pe_module():
        import pipeline_events as _pe
        return _pe

    def test_returns_symbols_with_rr_gate_in_failed_gates(self):
        """_get_rr_gap_symbols_for_scan returns only symbols whose canonical
        terminal event is SKIPPED with min_risk_reward in failed_gates AND the
        symbol is risk-approved."""
        events = [
            self._make_skip_event("scan_A", "AAPL", ["min_risk_reward"], ev_id=1),
            self._make_skip_event("scan_A", "MSFT", ["per_stock_cap"], ev_id=2),
        ]
        risk_approved = {"AAPL", "MSFT"}
        with patch.object(self._pe_module(), "query_events", return_value=events):
            conn = MagicMock()
            result = _get_rr_gap_symbols_for_scan(conn, "scan_A", risk_approved)
        assert result == {"AAPL"}, f"Only AAPL has min_risk_reward gate; got {result!r}"

    def test_excludes_symbols_not_risk_approved(self):
        """A symbol with EXECUTION_SKIPPED_WITH_REASON + min_risk_reward but
        all_gates_passed=False (Risk rejected) must NOT appear in the gap set."""
        events = [
            self._make_skip_event("scan_A", "TSLA", ["min_risk_reward"], ev_id=1),
        ]
        # TSLA is NOT in risk_approved — Risk Agent rejected it
        risk_approved = {"AAPL"}
        with patch.object(self._pe_module(), "query_events", return_value=events):
            conn = MagicMock()
            result = _get_rr_gap_symbols_for_scan(conn, "scan_A", risk_approved)
        assert "TSLA" not in result, (
            f"TSLA must be excluded when not risk-approved; got {result!r}"
        )

    def test_order_executed_beats_skip_no_false_gap_flag(self):
        """Seal-vs-executor race regression: when both ORDER_EXECUTED and
        EXECUTION_SKIPPED_WITH_REASON exist for the same (scan_id, symbol),
        ORDER_EXECUTED wins (higher priority) and the symbol must NOT be
        flagged as having an R:R gap — the order was actually placed."""
        events = [
            # Executor emitted ORDER_EXECUTED first (lower id)
            self._make_executed_event("scan_A", "AAPL", ev_id=10),
            # Seal emitted EXECUTION_SKIPPED_WITH_REASON later (higher id)
            self._make_skip_event("scan_A", "AAPL", ["min_risk_reward"], ev_id=11),
        ]
        risk_approved = {"AAPL"}
        with patch.object(self._pe_module(), "query_events", return_value=events):
            conn = MagicMock()
            result = _get_rr_gap_symbols_for_scan(conn, "scan_A", risk_approved)
        assert "AAPL" not in result, (
            "ORDER_EXECUTED must win over EXECUTION_SKIPPED_WITH_REASON; "
            f"AAPL must NOT be flagged as R:R gap; got {result!r}"
        )

    def test_order_executed_beats_skip_id_reversed(self):
        """Same race scenario with ids reversed (seal had a lower id but
        ORDER_EXECUTED still wins on priority, not insertion order)."""
        events = [
            # Seal emitted SKIPPED first (lower id, arrived earlier)
            self._make_skip_event("scan_A", "TCS", ["min_risk_reward"], ev_id=5),
            # Executor emitted ORDER_EXECUTED later (higher id)
            self._make_executed_event("scan_A", "TCS", ev_id=6),
        ]
        risk_approved = {"TCS"}
        with patch.object(self._pe_module(), "query_events", return_value=events):
            conn = MagicMock()
            result = _get_rr_gap_symbols_for_scan(conn, "scan_A", risk_approved)
        assert "TCS" not in result, (
            "ORDER_EXECUTED must beat EXECUTION_SKIPPED_WITH_REASON regardless "
            f"of id ordering; TCS must NOT be flagged; got {result!r}"
        )

    def test_scan_id_binding_prevents_cross_scan_annotation(self):
        """Regression: when a scan-state transition occurs between the scan
        fetch and the rr_gap lookup, the lookup must use the scan_id from the
        RETURNED scan, not from scan_state.

        Simulates two scans (scan_old, scan_new) where only scan_old has an
        R:R gap symbol.  When the caller binds to scan_new (the fetched scan),
        the result must be empty — proving no cross-scan annotation.
        """
        # scan_old has INFOSYS with an RR gap; scan_new has none
        def fake_query_events(*, scan_id=None, stage=None, limit=2000):
            if scan_id == "scan_old":
                return [self._make_skip_event("scan_old", "INFOSYS",
                                              ["min_risk_reward"], ev_id=1)]
            return []  # scan_new has no execution events

        with patch.object(self._pe_module(), "query_events", side_effect=fake_query_events):
            conn = MagicMock()
            # Caller binds to scan_new (the scan that was actually fetched)
            gap_new = _get_rr_gap_symbols_for_scan(
                conn, "scan_new", {"INFOSYS", "RELIANCE"})
        assert gap_new == set(), (
            f"scan_new has no RR-gap events; must return empty set; got {gap_new!r}"
        )

    def test_empty_risk_approved_returns_empty(self):
        """If no symbols are risk-approved, the gap set must be empty
        (short-circuits before calling pipeline_events)."""
        # Pass an empty risk_approved set — helper returns early without querying
        conn = MagicMock()
        result = _get_rr_gap_symbols_for_scan(conn, "scan_X", set())
        assert result == set(), f"Empty risk_approved must yield empty gap set; got {result!r}"

    def test_pipeline_events_error_returns_empty(self):
        """If pipeline_events raises, the helper must return an empty set
        (fail-open: no annotation is safer than a crash)."""
        with patch.object(self._pe_module(), "query_events",
                          side_effect=RuntimeError("DB unavailable")):
            conn = MagicMock()
            result = _get_rr_gap_symbols_for_scan(conn, "scan_Y", {"WIPRO"})
        assert result == set(), (
            f"Exception in pipeline_events must yield empty gap set; got {result!r}"
        )


# ── scan_id-binding integration tests ────────────────────────────────────────

class TestLoadRiskApprovedForScan:
    """
    Integration guard for _load_risk_approved_for_scan() and get_rr_gap_symbols().

    The core invariant: risk-approved symbols must come from the SAME scan as
    the requested scan_id.  This prevents cross-scan annotation when scan_state
    is updated between the /live-data/scan fetch and the rr_gap lookup.
    """

    def _make_snap_row(self, scan_id: str, symbols_approved: list) -> dict:
        """Build a fake scan_state row."""
        import json
        recs = [
            {"symbol": s, "all_gates_passed": True, "final_action": "BUY"}
            for s in symbols_approved
        ]
        return {"scan_id": scan_id, "snapshot": json.dumps({"recommendations": recs})}

    def _make_signal_row(self, symbols_approved: list) -> dict:
        """Build a fake signal_snapshots row."""
        import json
        recs = [
            {"symbol": s, "all_gates_passed": True, "final_action": "BUY"}
            for s in symbols_approved
        ]
        return {"signals": json.dumps(recs)}

    def test_uses_scan_state_when_ids_match(self):
        """When scan_state.scan_id == requested scan_id, use scan_state.snapshot."""
        conn = MagicMock()
        # scan_state belongs to scan_A — IDs match
        conn.cursor.return_value.__enter__.return_value.fetchall.return_value = [
            self._make_snap_row("scan_A", ["RELIANCE", "TCS"])
        ]
        with patch("replay_engine._q1", return_value=self._make_snap_row("scan_A", ["RELIANCE", "TCS"])):
            result = _load_risk_approved_for_scan(conn, "scan_A")
        assert "RELIANCE" in result and "TCS" in result, (
            f"Must return scan_A's approved symbols; got {result!r}"
        )

    def test_falls_back_to_signal_snapshots_on_scan_state_transition(self):
        """
        Regression: when scan_state has advanced to scan_new but the caller
        requests scan_old, _load_risk_approved_for_scan must NOT use
        scan_new's risk-approved set.  It falls back to signal_snapshots for
        scan_old and returns its correct approved symbols.
        """
        # scan_state is now scan_new; scan_old was archived in signal_snapshots
        scan_state_row = self._make_snap_row("scan_new", ["WIPRO"])  # new scan
        signal_row = self._make_signal_row(["INFOSYS"])              # old scan

        call_count = [0]

        def fake_q1(conn, sql, params=()):
            call_count[0] += 1
            if "scan_state" in sql:
                return scan_state_row
            if "signal_snapshots" in sql:
                return signal_row
            return None

        with patch("replay_engine._q1", side_effect=fake_q1):
            result = _load_risk_approved_for_scan(MagicMock(), "scan_old")

        # Must return scan_old's symbol (INFOSYS), not scan_new's (WIPRO)
        assert "INFOSYS" in result, (
            f"Must return scan_old's approved symbol INFOSYS; got {result!r}"
        )
        assert "WIPRO" not in result, (
            f"Must NOT include scan_new's symbol WIPRO; got {result!r}"
        )

    def test_get_rr_gap_symbols_scan_transition_integration(self):
        """
        Full integration regression: get_rr_gap_symbols(scan_id='scan_old')
        called after scan_state has transitioned to scan_new must:
          - derive risk_approved from scan_old's archived snapshot (not scan_new's)
          - return R:R gap symbols for scan_old only

        Simulates the /live-data/scan route scenario where getP7Scan() returns
        scan_old but scan_state is updated to scan_new before get_rr_gap_symbols
        is called.
        """
        import json

        # scan_old: INFOSYS risk-approved, has R:R gap event
        # scan_new: WIPRO risk-approved, no events
        scan_old_recs = [{"symbol": "INFOSYS", "all_gates_passed": True, "final_action": "BUY"}]
        scan_new_recs = [{"symbol": "WIPRO", "all_gates_passed": True, "final_action": "BUY"}]

        fake_scan_state = {"scan_id": "scan_new", "snapshot": json.dumps({"recommendations": scan_new_recs})}
        fake_signal_row = {"signals": json.dumps(scan_old_recs)}

        def fake_q1(conn, sql, params=()):
            if "scan_state" in sql and "snapshot" in sql:
                return fake_scan_state
            if "scan_state" in sql:
                return {"scan_id": "scan_new"}
            if "signal_snapshots" in sql:
                return fake_signal_row
            return None

        def fake_get_conn():
            return MagicMock()

        # scan_old has an R:R gap event for INFOSYS; scan_new has none.
        # Uses **kwargs to accept any combination of scan_id/stage/event_type/limit.
        def fake_query_events(**kwargs):
            if kwargs.get("scan_id") == "scan_old":
                return [{
                    "id": 1,
                    "scan_id": "scan_old",
                    "symbol": "INFOSYS",
                    "event_type": "EXECUTION_SKIPPED_WITH_REASON",
                    "payload": {
                        "failed_gates": ["min_risk_reward"],
                        "failed_gate_reasons": {"min_risk_reward": "R:R 1.5 vs minimum 2.0"},
                    },
                }]
            return []

        pe_mod = __import__("pipeline_events")
        with (
            patch("replay_engine._q1", side_effect=fake_q1),
            patch("replay_engine._get_conn", side_effect=fake_get_conn),
            patch.object(pe_mod, "query_events", side_effect=fake_query_events),
        ):
            result = get_rr_gap_symbols("scan_old")

        assert result["scan_id"] == "scan_old", (
            f"scan_id in result must be scan_old; got {result['scan_id']!r}"
        )
        assert "INFOSYS" in result["symbols"], (
            f"INFOSYS must appear as R:R gap symbol for scan_old; got {result['symbols']!r}"
        )
        assert "WIPRO" not in result["symbols"], (
            f"WIPRO from scan_new must NOT appear; got {result['symbols']!r}"
        )
