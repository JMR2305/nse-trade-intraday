"""Phase 4A controlled paper-entry framework safety tests."""

from __future__ import annotations

from pathlib import Path
import sys
from unittest import TestCase

PYTHON_DIR = Path(__file__).parents[2]
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

from controlled_paper_entry_bridge import preview_advisory_candidate
from controlled_paper_entry_dry_run import DRY_RUN_MARKER, simulate_dry_run
from controlled_paper_entry_flags import (
    ControlledPaperEntryFlags,
    get_controlled_paper_entry_flags,
)
from controlled_paper_entry_readiness import (
    ALLOWED_VERDICTS,
    BLOCKED,
    GO_FOR_OPERATOR_REVIEW,
    NO_GO,
    check_readiness,
)


def _safe_flags(**overrides: bool) -> ControlledPaperEntryFlags:
    values = {
        "framework_enabled": True,
        "dry_run_only": True,
        "require_phase1h_pass": True,
        "require_operator_approval": True,
        "allow_auto_enable": False,
        "allow_bootstrap": False,
    }
    values.update(overrides)
    return ControlledPaperEntryFlags(**values)


def _complete_evidence() -> dict:
    return {
        "phase1h_watch": {"report_exists": True, "status": "PASS"},
        "universe": {
            "universe_mode": "CUSTOM_LOW_PRICE_SECTOR",
            "symbols_analysed": 23,
            "symbols_with_errors": 0,
            "nifty_50_fallback": False,
        },
        "custom_universe_status": {
            "sector_counts": {"BANK": 9, "INFRA": 13, "IT": 1},
            "active_count": 23,
        },
        "settings": {
            "initial_capital": 100000,
            "active_intraday_universe": "CUSTOM_LOW_PRICE_SECTOR",
            "auto_paper_entries": False,
            "bootstrap_paper_enabled": False,
        },
        "positions": [],
        "trades_during_watch": [],
        "eod": {"status_passed": True, "outcomes_passed": True},
        "reviews": {
            "advisory_core_reviewed": True,
            "advisory_integration_reviewed": True,
        },
        "operator_approval": True,
    }


class TestControlledPaperEntryFlags(TestCase):
    def test_missing_flags_use_safe_defaults(self):
        flags = get_controlled_paper_entry_flags({})
        self.assertFalse(flags.framework_enabled)
        self.assertTrue(flags.dry_run_only)
        self.assertTrue(flags.require_phase1h_pass)
        self.assertTrue(flags.require_operator_approval)
        self.assertFalse(flags.allow_auto_enable)
        self.assertFalse(flags.allow_bootstrap)
        self.assertFalse(flags.review_gate_safe)
        self.assertFalse(flags.execution_allowed)

    def test_unknown_values_use_safe_defaults_and_literal_values_are_explicit(self):
        flags = get_controlled_paper_entry_flags({
            "CONTROLLED_PAPER_ENTRY_FRAMEWORK_ENABLED": "1",
            "CONTROLLED_PAPER_ENTRY_DRY_RUN_ONLY": "no",
            "CONTROLLED_PAPER_ENTRY_REQUIRE_PHASE1H_PASS": "false",
            "CONTROLLED_PAPER_ENTRY_REQUIRE_OPERATOR_APPROVAL": "TRUE",
            "CONTROLLED_PAPER_ENTRY_ALLOW_AUTO_ENABLE": "yes",
            "CONTROLLED_PAPER_ENTRY_ALLOW_BOOTSTRAP": "1",
        })
        self.assertFalse(flags.framework_enabled)
        self.assertTrue(flags.dry_run_only)
        self.assertFalse(flags.require_phase1h_pass)
        self.assertTrue(flags.require_operator_approval)
        self.assertFalse(flags.allow_auto_enable)
        self.assertFalse(flags.allow_bootstrap)

    def test_unsafe_enablement_controls_cannot_open_a_review_gate(self):
        self.assertFalse(_safe_flags(dry_run_only=False).review_gate_safe)
        self.assertFalse(_safe_flags(allow_auto_enable=True).review_gate_safe)
        self.assertFalse(_safe_flags(allow_bootstrap=True).review_gate_safe)


class TestControlledPaperEntryReadiness(TestCase):
    def test_complete_evidence_returns_only_go_for_operator_review(self):
        verdict = check_readiness(_complete_evidence(), flags=_safe_flags())
        self.assertEqual(verdict, GO_FOR_OPERATOR_REVIEW)
        self.assertIn(verdict, ALLOWED_VERDICTS)

    def test_disabled_controls_return_blocked(self):
        self.assertEqual(
            check_readiness(_complete_evidence(), flags=get_controlled_paper_entry_flags({})),
            BLOCKED,
        )

    def test_missing_or_failed_phase1h_returns_no_go(self):
        for phase1h in (
            None,
            {"report_exists": False, "status": "PASS"},
            {"report_exists": True, "status": "WARN"},
        ):
            evidence = _complete_evidence()
            if phase1h is None:
                del evidence["phase1h_watch"]
            else:
                evidence["phase1h_watch"] = phase1h
            self.assertEqual(check_readiness(evidence, flags=_safe_flags()), NO_GO)

    def test_positions_must_be_empty(self):
        evidence = _complete_evidence()
        evidence["positions"] = [{"symbol": "INFY"}]
        self.assertEqual(check_readiness(evidence, flags=_safe_flags()), NO_GO)

    def test_universe_mode_and_symbol_counts_are_exact(self):
        for key, value in (
            ("universe_mode", "NIFTY_50"),
            ("symbols_analysed", 22),
            ("symbols_with_errors", 1),
            ("nifty_50_fallback", True),
        ):
            evidence = _complete_evidence()
            evidence["universe"][key] = value
            self.assertEqual(check_readiness(evidence, flags=_safe_flags()), NO_GO)

    def test_custom_universe_counts_are_exact(self):
        evidence = _complete_evidence()
        evidence["custom_universe_status"]["sector_counts"]["IT"] = 2
        self.assertEqual(check_readiness(evidence, flags=_safe_flags()), NO_GO)

        evidence = _complete_evidence()
        evidence["custom_universe_status"]["active_count"] = 22
        self.assertEqual(check_readiness(evidence, flags=_safe_flags()), NO_GO)

    def test_settings_are_exact_and_auto_controls_must_be_off(self):
        for key, value in (
            ("initial_capital", 50000),
            ("active_intraday_universe", "NIFTY_50"),
            ("auto_paper_entries", True),
            ("bootstrap_paper_enabled", True),
        ):
            evidence = _complete_evidence()
            evidence["settings"][key] = value
            self.assertEqual(check_readiness(evidence, flags=_safe_flags()), NO_GO)

    def test_auto_and_bootstrap_trade_audit_must_be_empty(self):
        for trade_type in ("AUTO", "BOOTSTRAP_AUTO"):
            evidence = _complete_evidence()
            evidence["trades_during_watch"] = [{"trade_type": trade_type}]
            self.assertEqual(check_readiness(evidence, flags=_safe_flags()), NO_GO)

        evidence = _complete_evidence()
        evidence["trades_during_watch"] = [{"action": "AUTO"}]
        self.assertEqual(check_readiness(evidence, flags=_safe_flags()), NO_GO)

        evidence = _complete_evidence()
        del evidence["trades_during_watch"]
        self.assertEqual(check_readiness(evidence, flags=_safe_flags()), NO_GO)

    def test_eod_proof_and_independent_reviews_are_required(self):
        for key in ("status_passed", "outcomes_passed"):
            evidence = _complete_evidence()
            evidence["eod"][key] = False
            self.assertEqual(check_readiness(evidence, flags=_safe_flags()), NO_GO)
        for key in ("advisory_core_reviewed", "advisory_integration_reviewed"):
            evidence = _complete_evidence()
            evidence["reviews"][key] = False
            self.assertEqual(check_readiness(evidence, flags=_safe_flags()), NO_GO)

        evidence = _complete_evidence()
        evidence["operator_approval"] = False
        self.assertEqual(check_readiness(evidence, flags=_safe_flags()), NO_GO)

    def test_invalid_evidence_returns_blocked_and_no_other_verdicts_escape(self):
        verdict = check_readiness(None, flags=_safe_flags())
        self.assertEqual(verdict, BLOCKED)
        self.assertTrue({verdict, NO_GO, GO_FOR_OPERATOR_REVIEW}.issubset(ALLOWED_VERDICTS))


class TestControlledPaperEntryDryRun(TestCase):
    def test_candidate_is_estimated_without_executable_fields(self):
        result = simulate_dry_run({
            "symbol": "INFY",
            "strategy_source": "VWAP",
            "advisory_score": 82.5,
            "final_action": "BUY",
            "risk_flags": [],
        })
        self.assertEqual(result["status"], "DRY_RUN_CANDIDATE")
        self.assertEqual(result["marker"], DRY_RUN_MARKER)
        self.assertEqual(result["candidate_symbol"], "INFY")
        self.assertEqual(result["theoretical_notional"], 20000.0)
        self.assertFalse(result["execution_allowed"])
        self.assertNotIn("quantity", result)
        self.assertNotIn("order_quantity", result)
        self.assertNotIn("order_id", result)

    def test_unsafe_candidate_is_rejected_and_prohibited_input_is_not_echoed(self):
        result = simulate_dry_run({
            "symbol": "INFY",
            "strategy": "VWAP",
            "score": 82,
            "decision": "BUY",
            "risk_flags": ["STALE_DATA"],
            "quantity": 10,
        })
        self.assertEqual(result["status"], "DRY_RUN_REJECTED")
        self.assertIn("risk flags", result["rejection_reason"])
        self.assertIn("executable fields", result["rejection_reason"])
        self.assertNotIn("quantity", result)
        self.assertNotIn("order_id", result)

    def test_dry_run_is_safe_for_malformed_candidates(self):
        result = simulate_dry_run({"final_action": "SELL"})
        self.assertEqual(result["status"], "DRY_RUN_REJECTED")
        self.assertFalse(result["execution_allowed"])
        self.assertTrue(result["dry_run_only"])


class TestControlledPaperEntryBridge(TestCase):
    def test_disabled_bridge_stops_before_simulation(self):
        result = preview_advisory_candidate({"symbol": "INFY"}, flags=get_controlled_paper_entry_flags({}))
        self.assertEqual(result["status"], "BRIDGE_DISABLED")
        self.assertIsNone(result["simulation"])
        self.assertFalse(result["execution_allowed"])

    def test_enabled_bridge_still_returns_only_dry_run(self):
        result = preview_advisory_candidate(
            {
                "symbol": "INFY",
                "strategy_source": "VWAP",
                "advisory_score": 82,
                "final_action": "BUY",
                "risk_flags": [],
            },
            flags=_safe_flags(),
        )
        self.assertEqual(result["status"], "DRY_RUN_ONLY")
        self.assertEqual(result["marker"], DRY_RUN_MARKER)
        self.assertFalse(result["execution_allowed"])
        self.assertEqual(result["simulation"]["marker"], DRY_RUN_MARKER)

    def test_bootstrap_or_auto_enable_controls_block_bridge(self):
        for override in ("allow_bootstrap", "allow_auto_enable", "dry_run_only"):
            result = preview_advisory_candidate(
                {"symbol": "INFY"},
                flags=_safe_flags(**{override: True} if override != "dry_run_only" else {override: False}),
            )
            self.assertEqual(result["status"], BLOCKED)
            self.assertFalse(result["execution_allowed"])

    def test_bridge_source_has_no_forbidden_module_imports(self):
        source = Path(__file__).parents[2].joinpath("controlled_paper_entry_bridge.py").read_text()
        for forbidden in (
            "import phase20",
            "from phase20",
            "import paper_trader",
            "from paper_trader",
            "import broker",
            "from broker",
            "import kite",
            "from kite",
            "import settings",
            "from settings",
        ):
            self.assertNotIn(forbidden, source.lower())


if __name__ == "__main__":
    import unittest

    unittest.main()
