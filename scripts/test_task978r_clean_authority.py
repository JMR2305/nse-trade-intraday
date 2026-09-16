from __future__ import annotations

import hashlib
import importlib.util
import json
import pathlib
import re
import sys
import unittest
from unittest import mock


ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "task978r_clean_authority.py"
SQL_PATH = ROOT / "scripts" / "task978r_application_authority_schema.sql"
MANIFEST_PATH = ROOT / "scripts" / "task978r_clean_authority_manifest.json"


def load_module():
    spec = importlib.util.spec_from_file_location("task978r_clean_authority", MODULE_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("bootstrap module is unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class TestBootstrapArtifacts(unittest.TestCase):
    def test_reviewed_artifacts_exist(self):
        self.assertTrue(MODULE_PATH.is_file())
        self.assertTrue(SQL_PATH.is_file())
        self.assertTrue(MANIFEST_PATH.is_file())

    def test_sql_is_additive_and_contains_required_authorities(self):
        sql = SQL_PATH.read_text(encoding="utf-8")
        upper = sql.upper()
        executable = re.sub(r"--.*?$|/\*.*?\*/", "", upper, flags=re.M | re.S)
        self.assertNotIn("DROP ", executable)
        self.assertNotIn("TRUNCATE ", executable)
        self.assertNotIn("DELETE FROM", executable)
        self.assertNotIn("RENAME COLUMN", executable)
        self.assertNotIn("RESET_PORTFOLIO", upper)
        self.assertRegex(sql, r'(?i)CREATE TABLE IF NOT EXISTS\s+"?phase20_kv"?')
        self.assertRegex(sql, r'(?i)UNIQUE\s*\(\s*"?correlation_id"?\s*,\s*"?action"?\s*\)')
        self.assertNotRegex(sql, r'(?i)UNIQUE\s*\(\s*"?action"?\s*,\s*"?correlation_id"?\s*\)')

    def test_manifest_classifies_clean_authority(self):
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        self.assertEqual(manifest["authority_class"], "CLEAN_RECONSTRUCTED_AUTHORITY")
        self.assertFalse(manifest["historically_equivalent_to_replit_db"])
        self.assertEqual(manifest["kite_token_authority"], {
            "table": "phase20_kv", "key": "kite_token_v1"
        })
        prohibited = set(manifest["prohibited_historical_domains"])
        self.assertTrue({
            "phase20_paper_trades", "historical_ledger_rows",
            "historical_audit_events", "runtime_universe_session_pins",
            "historical_token_rows", "historical_validation_rows",
        }.issubset(prohibited))
        seed = manifest["clean_seed_manifest"]
        self.assertEqual(seed["universe"]["universe_id"], 3)
        self.assertEqual(seed["universe"]["version"], 1)
        self.assertEqual(seed["universe"]["symbol_count"], 23)
        self.assertEqual(seed["universe"]["exact_set_hash"], "22e5751f25686718f5572041834ce998b7c5ce9844d3b573bc3841749fe77016")
        self.assertEqual(seed["history_rows"], 0)
        self.assertEqual(seed["kite_token_rows"], 0)


class TestIdentityGate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_exact_disposable_identity_is_accepted(self):
        target = self.module.parse_target_identity(
            "postgresql://task967:secret@127.0.0.1:5432/task978za_disposable_authority",
            purpose="TASK978ZA_NATIVE_PG16",
            acknowledgement="TASK978ZA_DISPOSABLE_AUTHORITY",
        )
        self.module.authorize_target(target)

    def test_prohibited_and_unknown_targets_are_rejected(self):
        urls = (
            "postgresql://apexquant_benchmark:x@postgres16-benchmark.zeabur.internal:5432/apexquant_disposable",
            "postgresql://task967:x@127.0.0.1:5432/task967_disposable_task968",
            "postgresql://task967:x@127.0.0.1:5432/unknown_database",
            "postgresql://unknown:x@127.0.0.1:5432/task978za_disposable_authority",
        )
        for url in urls:
            with self.subTest(url=url), self.assertRaises(self.module.IdentityRefused):
                target = self.module.parse_target_identity(
                    url,
                    purpose="TASK978ZA_NATIVE_PG16",
                    acknowledgement="TASK978ZA_DISPOSABLE_AUTHORITY",
                )
                self.module.authorize_target(target)

    def test_rejection_occurs_before_driver_import_or_sql(self):
        with mock.patch("builtins.__import__", side_effect=AssertionError("driver imported")):
            with self.assertRaises(self.module.IdentityRefused):
                self.module.preflight_authorize(
                    "postgresql://x:y@postgres16-benchmark.zeabur.internal/apexquant_disposable",
                    purpose="TASK978ZA_NATIVE_PG16",
                    acknowledgement="TASK978ZA_DISPOSABLE_AUTHORITY",
                )


class TestCleanSeed(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_module()

    def test_canonical_symbols_and_hash_are_exact(self):
        expected = (
            "BANKBARODA", "BANKINDIA", "CANBK", "FEDERALBNK", "IDFCFIRSTB",
            "KTKBANK", "MAHABANK", "PNB", "UNIONBANK", "COALINDIA", "GAIL",
            "HUDCO", "IRCON", "IRFC", "MRPL", "NBCC", "NMDC", "NTPC",
            "PFC", "RECLTD", "RVNL", "SAIL", "WIPRO",
        )
        self.assertEqual(self.module.CANONICAL_SYMBOLS, expected)
        digest = hashlib.sha256("\n".join(sorted(expected)).encode()).hexdigest()
        self.assertEqual(digest, self.module.CANONICAL_SET_HASH)
        self.assertEqual(digest, "22e5751f25686718f5572041834ce998b7c5ce9844d3b573bc3841749fe77016")

    def test_safety_settings_are_fail_closed(self):
        self.assertEqual(self.module.SAFETY_SETTINGS, {
            "PAPER_TRADING_MODE": True,
            "AUTO_EXECUTION_ENABLED": False,
            "LIVE_EXECUTION_ENABLED": False,
            "LIVE_ORDERS_ENABLED": False,
            "CONTROLLED_PAPER_ENTRY_ENABLED": False,
            "CONTROLLED_PAPER_ENTRY_FRAMEWORK_ENABLED": False,
            "BOOTSTRAP_PAPER_ENABLED": False,
            "AUTO_PAPER_ENTRIES": False,
        })

    def test_seed_statements_do_not_fabricate_history(self):
        seed_sql = "\n".join(self.module.seed_statements()).lower()
        for forbidden in (
            "phase20_paper_trades", "runtime_universe_session_pins",
            "trading_universe_audit_events", "trading_universe_validations",
            "kite_token_v1", "realized", "closed round", "exit_pending",
        ):
            self.assertNotIn(forbidden, seed_sql)

    def test_seed_creates_exact_current_universe_authority(self):
        seed_sql = "\n".join(self.module.seed_statements())
        self.assertIn("INSERT INTO trading_universe_sources", seed_sql)
        self.assertIn("INSERT INTO trading_universes", seed_sql)
        self.assertIn("INSERT INTO trading_universe_members", seed_sql)
        self.assertIn("CUSTOM_LOW_PRICE_SECTOR", seed_sql)
        self.assertIn("22e5751f25686718f5572041834ce998b7c5ce9844d3b573bc3841749fe77016", seed_sql)
        self.assertIn("2026-08-31T03:30:00Z", seed_sql)
        self.assertIn("CLEAN_RECONSTRUCTED_AUTHORITY", seed_sql)
        self.assertIn("NOT_HISTORICALLY_EQUIVALENT_TO_REPLIT_DB", seed_sql)

    def test_member_sector_counts_are_exact(self):
        sectors = self.module.CANONICAL_MEMBER_SECTORS
        self.assertEqual(set(sectors), set(self.module.CANONICAL_SYMBOLS))
        self.assertEqual(sum(value == "BANK" for value in sectors.values()), 9)
        self.assertEqual(sum(value == "INFRA" for value in sectors.values()), 13)
        self.assertEqual(sum(value == "IT" for value in sectors.values()), 1)

    def test_seed_is_second_run_stable(self):
        seed_sql = "\n".join(self.module.seed_statements()).upper()
        self.assertNotIn("SET DATA = EXCLUDED.DATA", seed_sql)
        self.assertNotIn("SET VALUE = EXCLUDED.VALUE", seed_sql)
        self.assertNotIn("UPDATED_AT = EXCLUDED.UPDATED_AT", seed_sql)
        self.assertIn("WHERE NOT EXISTS", seed_sql)

    def test_bootstrap_verifies_seed_before_commit(self):
        source = MODULE_PATH.read_text(encoding="utf-8")
        self.assertIn("verification = _verify_authority(cur)", source)
        self.assertIn('"verification": verification', source)


if __name__ == "__main__":
    unittest.main()
