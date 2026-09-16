from __future__ import annotations

import ast
import importlib.util
import json
import pathlib
import re
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "scripts" / "task978r_clean_authority.py"
SQL_PATH = ROOT / "scripts" / "task978r_application_authority_schema.sql"
MANIFEST_PATH = ROOT / "scripts" / "task978r_clean_authority_manifest.json"
PYTHON_ROOT = ROOT / "artifacts" / "api-server" / "src" / "python"

PROTECTED = {
    "trading_universe_sources",
    "trading_universes",
    "trading_universe_members",
    "trading_universe_audit_events",
    "runtime_universe_session_pins",
    "trading_universe_member_details",
    "trading_universe_validations",
    "trading_universe_baseline_migrations",
}


class TestStaticIsolation(unittest.TestCase):
    def test_bootstrap_has_only_standard_library_top_level_imports(self):
        tree = ast.parse(BOOTSTRAP.read_text(encoding="utf-8"))
        imported = set()
        for node in tree.body:
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                imported.add((node.module or "").split(".")[0])
        self.assertFalse(imported & {
            "phase20_store", "kite_token_store", "app", "routes",
            "phase20_scheduler", "market_scanner", "broker_client",
            "kiteconnect", "subprocess", "socket",
        })

    def test_no_runtime_or_mutation_entrypoints_appear(self):
        text = BOOTSTRAP.read_text(encoding="utf-8")
        for forbidden in (
            "startScanScheduler", "startBacktestScheduler", "reset_portfolio",
            "place_order", "run_tick", "initialize_daily_session",
            "startPipelineTail", "kiteconnect", "notification_worker",
        ):
            self.assertNotIn(forbidden, text)


class TestCoverageManifest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.sql = SQL_PATH.read_text(encoding="utf-8")

    def test_every_manifest_object_has_provenance_and_sql(self):
        objects = self.manifest["objects"]
        self.assertGreaterEqual(len(objects), 1)
        for obj in objects:
            self.assertTrue(obj["name"])
            self.assertTrue(obj["owner"])
            self.assertTrue(obj["source"])
            if obj["kind"] == "table":
                self.assertRegex(
                    self.sql,
                    rf'(?i)CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+"?{re.escape(obj["name"])}"?\b',
                )

    def test_checked_in_manifests_match_static_regeneration(self):
        generator_path = ROOT / "scripts" / "task978r_generate_schema.py"
        spec = importlib.util.spec_from_file_location("task978r_generate_schema", generator_path)
        self.assertIsNotNone(spec)
        self.assertIsNotNone(spec.loader)
        module = importlib.util.module_from_spec(spec)
        import sys
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        generated_sql, generated_manifest = module.build()
        self.assertEqual(generated_sql, self.sql)
        self.assertEqual(generated_manifest, self.manifest)

    def test_table_coverage_is_complete_and_conflict_free(self):
        table_objects = [o for o in self.manifest["objects"] if o["kind"] == "table"]
        self.assertEqual(len(table_objects), 91)
        names = [o["name"] for o in table_objects]
        self.assertEqual(len(names), len(set(names)))
        sql_names = [name.lower() for name in re.findall(
            r'(?i)CREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+"?([A-Za-z_][A-Za-z0-9_]*)"?',
            self.sql,
        )]
        self.assertEqual(sorted(sql_names), sorted(names))

    def test_destructive_runtime_compatibility_is_excluded(self):
        excluded = self.manifest["excluded_destructive_compatibility"]
        self.assertEqual(
            {entry["reason"] for entry in excluded},
            {
                "prohibited compatibility operation: DROP",
                "prohibited compatibility operation: RENAME COLUMN",
            },
        )

    def test_protected_chain_and_phase20_kv_are_exact(self):
        tables = {o["name"] for o in self.manifest["objects"] if o["kind"] == "table"}
        self.assertTrue(PROTECTED.issubset(tables))
        self.assertIn("phase20_kv", tables)
        self._assert_audit_order(self.sql)

    def test_changed_or_reordered_audit_unique_is_rejected(self):
        altered = re.sub(
            r'(?i)UNIQUE\s*\(\s*"?correlation_id"?\s*,\s*"?action"?\s*\)',
            "UNIQUE (action, correlation_id)",
            self.sql,
            count=1,
        )
        with self.assertRaises(AssertionError):
            self._assert_audit_order(altered)

    def _assert_audit_order(self, sql):
        self.assertRegex(sql, r'(?i)UNIQUE\s*\(\s*"?correlation_id"?\s*,\s*"?action"?\s*\)')
        self.assertNotRegex(sql, r'(?i)UNIQUE\s*\(\s*"?action"?\s*,\s*"?correlation_id"?\s*\)')

    def test_manifest_source_files_exist(self):
        for obj in self.manifest["objects"]:
            source = obj["source"].split(":", 1)[0]
            self.assertTrue((ROOT / source).is_file(), source)

    def test_no_unresolved_dynamic_create_table_tokens(self):
        self.assertNotRegex(self.sql, r"CREATE\s+TABLE[^;]*\{[^}]+\}")


if __name__ == "__main__":
    unittest.main()
