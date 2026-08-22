"""Safety tests for the disabled-by-default Phase 3A integration boundary."""

from __future__ import annotations

import os
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from advisory_bots.flags import get_advisory_flags
from advisory_bots.manual_runner import run_fixture


class TestPhase3AFlags(TestCase):
    def test_all_flags_default_false_when_missing(self):
        flags = get_advisory_flags({})
        self.assertFalse(flags.bots_enabled)
        self.assertFalse(flags.api_enabled)
        self.assertFalse(flags.ui_enabled)
        self.assertFalse(flags.persist_enabled)
        self.assertFalse(flags.scheduler_enabled)

    def test_only_literal_true_enables_a_flag(self):
        flags = get_advisory_flags({
            "ADVISORY_BOTS_ENABLED": "TRUE",
            "ADVISORY_BOTS_API_ENABLED": "1",
            "ADVISORY_BOTS_UI_ENABLED": "yes",
            "ADVISORY_BOTS_PERSIST_ENABLED": " true ",
            "ADVISORY_BOTS_SCHEDULER_ENABLED": "false",
        })
        self.assertTrue(flags.bots_enabled)
        self.assertFalse(flags.api_enabled)
        self.assertFalse(flags.ui_enabled)
        self.assertTrue(flags.persist_enabled)
        self.assertFalse(flags.scheduler_enabled)

    def test_persistence_requires_explicit_non_conflicting_development_or_test_environment(self):
        self.assertTrue(
            get_advisory_flags({"NODE_ENV": "development"}).persistence_environment_allowed
        )
        self.assertTrue(
            get_advisory_flags({
                "NODE_ENV": "test",
                "ENVIRONMENT": "TEST",
            }).persistence_environment_allowed
        )
        for environment in (
            {},
            {"NODE_ENV": "staging"},
            {"NODE_ENV": "development", "ENVIRONMENT": "production"},
        ):
            self.assertFalse(
                get_advisory_flags(environment).persistence_environment_allowed
            )


class TestPhase3AManualRunner(TestCase):
    def test_runner_defaults_to_non_persisting_analysis(self):
        payload = {
            "scan_id": "dev-fixture",
            "universe_rows": [],
            "scan_items": [],
            "settings": {},
        }
        analysis = {"decisions": [], "advisory_only": True, "paper_only": True}
        with patch.dict(os.environ, {"ADVISORY_BOTS_ENABLED": "true"}, clear=True), patch(
            "advisory_bots.manual_runner._load_payload", return_value=payload
        ), patch(
            "advisory_bots.manual_runner.run_advisory_analysis", return_value=analysis
        ) as run:
            result = run_fixture(None)

        self.assertFalse(run.call_args.kwargs["persist"])
        self.assertTrue(result["manual_invocation_only"])
        self.assertTrue(result["not_trade_instructions"])

    def test_runner_rejects_persistence_without_explicit_safe_flag(self):
        with patch.dict(os.environ, {"ADVISORY_BOTS_ENABLED": "true"}, clear=True), self.assertRaises(ValueError):
            run_fixture(None, persist=True)

    def test_runner_rejects_persistence_for_missing_unknown_or_conflicting_environment(self):
        advisory_flags = {
            "ADVISORY_BOTS_ENABLED": "true",
            "ADVISORY_BOTS_PERSIST_ENABLED": "true",
        }
        unsafe_environments = (
            {},
            {"NODE_ENV": "staging"},
            {"NODE_ENV": "development", "ENVIRONMENT": "production"},
        )
        for environment in unsafe_environments:
            with self.subTest(environment=environment), patch.dict(
                os.environ, {**advisory_flags, **environment}, clear=True
            ), self.assertRaises(ValueError):
                run_fixture(None, persist=True)

    def test_runner_accepts_persistence_only_with_explicit_development_attestation(self):
        payload = {
            "scan_id": "dev-fixture",
            "universe_rows": [],
            "scan_items": [],
            "settings": {},
        }
        with patch.dict(os.environ, {
            "ADVISORY_BOTS_ENABLED": "true",
            "ADVISORY_BOTS_PERSIST_ENABLED": "true",
            "NODE_ENV": "development",
        }, clear=True), patch(
            "advisory_bots.manual_runner._load_payload", return_value=payload
        ), patch(
            "advisory_bots.manual_runner.run_advisory_analysis", return_value={"decisions": []}
        ) as run:
            run_fixture(None, persist=True)

        self.assertTrue(run.call_args.kwargs["persist"])

    def test_runner_requires_explicit_master_enablement(self):
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            run_fixture(None)

    def test_runner_source_has_no_scheduler_or_execution_hook(self):
        package = Path(__file__).parents[2] / "advisory_bots"
        source = "\n".join(path.read_text() for path in package.glob("*.py"))
        self.assertNotIn("startScanScheduler", source)
        self.assertNotIn("execute_buy", source)
        self.assertNotIn("execute_sell", source)
        self.assertNotIn("place_order", source)
        self.assertNotIn("broker_client", source)