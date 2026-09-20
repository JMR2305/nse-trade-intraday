from __future__ import annotations

import importlib.util
import pathlib
import sys
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "task978za_postgres_validation.py"


def load_module():
    spec = importlib.util.spec_from_file_location("task978za_postgres_validation", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("native validator module is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestNativeValidationIdentity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_exact_task969_ci_service_derives_separate_database(self):
        identity = self.module.derive_validation_identity(
            "postgresql://task967:secret@127.0.0.1:5432/task967_disposable_task968"
        )
        self.assertEqual(identity.maintenance_database, "postgres")
        self.assertEqual(identity.validation_database, "task978za_disposable_authority")
        self.assertIn("/task978za_disposable_authority", identity.validation_url)
        self.assertNotIn("/task967_disposable_task968", identity.validation_url)

    def test_protected_and_unknown_sources_are_rejected(self):
        for url in (
            "postgresql://x:y@postgres16-benchmark.zeabur.internal/apexquant_disposable",
            "postgresql://x:y@postgres16-apexquant-app.zeabur.internal/apexquant_app",
            "postgresql://task967:y@127.0.0.1/unknown",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.module.derive_validation_identity(url)

    def test_expected_protected_and_history_empty_sets_are_fixed(self):
        self.assertEqual(len(self.module.PROTECTED_TABLES), 8)
        self.assertIn("phase20_kv", self.module.REQUIRED_TABLES)
        self.assertEqual(
            self.module.PROHIBITED_HISTORY_TABLES,
            {
                "phase20_paper_trades",
                "trading_universe_audit_events",
                "trading_universe_validations",
                "runtime_universe_session_pins",
                "trading_universe_baseline_migrations",
            },
        )

    def test_task969_native_gate_invokes_task978za_validator(self):
        task969 = (ROOT / "scripts" / "task969_postgres_validation.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("task978za_postgres_validation.py", task969)

    def test_native_validator_exercises_actual_resolver_and_both_set_paths(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("runtime_universe.resolve_active_universe(probe_time)", source)
        self.assertIn("LOCALE_PROVIDER icu ICU_LOCALE 'en-US'", source)
        self.assertIn("ensure_builtin_nifty_baseline(conn)", source)
        self.assertIn("aaa_task978zn_corrupt_nifty_member", source)
        self.assertIn('"wrong_persisted_set_rejected": "PASS"', source)

    def test_order_independence_proof_is_deterministic_not_ambient_collation_dependent(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("deliberately_reordered = list(reversed(database_order))", source)
        self.assertIn(
            "python_order,\n            deliberately_reordered,",
            source,
        )
        self.assertNotIn(
            'raise AssertionError("native ICU ordering did not expose the prior comparison defect")',
            source,
        )


if __name__ == "__main__":
    unittest.main()
