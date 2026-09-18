from __future__ import annotations

import hashlib
import ast
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

    def test_exact_zeabur_application_identity_is_accepted(self):
        """Task978ZD: only the exact Zeabur application host/database is authorized."""
        target = self.module.parse_target_identity(
            "postgresql://apexquant_app:secret@postgres16-apexquant-app-emon.zeabur.internal:5432/apexquant_app",
            purpose="TASK978ZA_ZEABUR_APPLICATION",
            acknowledgement="apexquant_app",
        )
        self.module.authorize_target(target, expected_user="apexquant_app")
        self.assertEqual(target.host, "postgres16-apexquant-app-emon.zeabur.internal")
        self.assertEqual(target.port, 5432)
        self.assertEqual(target.database, "apexquant_app")
        self.assertEqual(target.user, "apexquant_app")

    def test_wrong_zeabur_host_and_missing_user_are_rejected(self):
        """The bare service name, wrong DB, wrong user, and missing expected_user all fail closed."""
        for url, expected_user in (
            # Historical bare-service pin must no longer be accepted.
            ("postgresql://apexquant_app:secret@postgres16-apexquant-app.zeabur.internal:5432/apexquant_app", "apexquant_app"),
            ("postgresql://apexquant_app:secret@postgres16-apexquant-app-emon.zeabur.internal:5432/apexquant_disposable", "apexquant_app"),
            ("postgresql://apexquant_app:secret@postgres16-apexquant-app-emon.zeabur.internal:5432/apexquant_app", "apexquant_benchmark"),
            ("postgresql://apexquant_app:secret@postgres16-apexquant-app-emon.zeabur.internal:5432/apexquant_app", ""),
            ("postgresql://apexquant_app:secret@postgres16-apexquant-app-emon.zeabur.internal:5433/apexquant_app", "apexquant_app"),
        ):
            with self.subTest(url=url, expected_user=expected_user), \
                    self.assertRaises(self.module.IdentityRefused):
                target = self.module.parse_target_identity(
                    url,
                    purpose="TASK978ZA_ZEABUR_APPLICATION",
                    acknowledgement="apexquant_app",
                )
                self.module.authorize_target(target, expected_user=expected_user)


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


class TestDependencyClosure(unittest.TestCase):
    """The standalone bootstrap must be relation-self-contained.

    Every relation referenced by the clean seed SQL or by the bootstrap's
    own verification SQL must be created by the standalone authority schema
    itself (the checked-in generated SQL + manifest).  A future seed or
    verification reference introduced without schema coverage must fail
    here, before any database is touched.
    """

    @classmethod
    def setUpClass(cls):
        cls.module = load_module()
        cls.source = MODULE_PATH.read_text(encoding="utf-8")
        cls.manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
        cls.created_tables = {
            obj["name"] for obj in cls.manifest["objects"] if obj["kind"] == "table"
        }

    @staticmethod
    def _referenced_relations(sql_text: str) -> set[str]:
        candidates: set[str] = set()
        for match in re.finditer(
            r'(?i)\b(?:FROM|JOIN|INSERT\s+INTO|UPDATE|REFERENCES|DELETE\s+FROM)\s+"?'
            r'([A-Za-z_][A-Za-z0-9_]*)"?',
            sql_text,
        ):
            candidates.add(match.group(1).lower())
        return candidates

    @classmethod
    def _bootstrap_sql_fragments(cls) -> list[str]:
        """Collect every SQL string the bootstrap module can execute."""
        tree = ast.parse(cls.source)
        fragments: list[str] = []
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "execute"
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                fragments.append(node.args[0].value)
        # Table names referenced through f-strings (e.g. the forbidden-history
        # probe loop) are declared as local literal tuples inside functions;
        # collect those too.  Module-level symbol tuples are not SQL.
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for statement in node.body:
                    if (
                        isinstance(statement, ast.Assign)
                        and len(statement.targets) == 1
                        and isinstance(statement.targets[0], ast.Name)
                        and isinstance(statement.value, ast.Tuple)
                    ):
                        for element in statement.value.elts:
                            if isinstance(element, ast.Constant) and isinstance(element.value, str):
                                fragments.append(f"FROM {element.value}")
        fragments.extend(cls.module.seed_statements())
        return fragments

    def test_every_referenced_relation_is_created_by_the_standalone_schema(self):
        fragments = self._bootstrap_sql_fragments()
        self.assertGreater(len(fragments), 0)
        referenced = self._referenced_relations("\n".join(fragments))
        # PostgreSQL built-in catalog schemas/functions, seed-statement CTEs,
        # and SQL keywords caught by the JOIN heuristic are not bootstrap-owned
        # relations.
        non_tables = {
            name for name in referenced
            if name.startswith("pg_")
            or name in {"information_schema", "expected", "unnest", "lateral"}
        }
        unresolved = sorted(referenced - non_tables - self.created_tables)
        self.assertEqual(unresolved, [], "bootstrap references relations the standalone schema never creates")

    def test_phase20_settings_and_phase20_kv_are_referenced_and_created(self):
        referenced = self._referenced_relations("\n".join(self._bootstrap_sql_fragments()))
        for required in ("phase20_settings", "phase20_kv"):
            self.assertIn(required, referenced, f"{required} is not exercised by the bootstrap")
            self.assertIn(required, self.created_tables, f"{required} is absent from the standalone schema manifest")

    def test_closure_fails_for_an_uncovered_future_reference(self):
        # A relation referenced by bootstrap SQL but missing from the manifest
        # must be flagged by the same closure computation the test above uses.
        referenced = self._referenced_relations("SELECT count(*) FROM some_future_runtime_lazy_table")
        unresolved = referenced - self.created_tables
        self.assertEqual(unresolved, {"some_future_runtime_lazy_table"})


class TestBootstrapDurability(unittest.TestCase):
    """Task978ZC/ZG: the bootstrap must durably commit what it verified.

    Regression for Task969 run 35055139734: a bootstrap that reported PASS
    while a fresh connection saw UndefinedTable on phase20_settings proved
    that verification without a durable commit is meaningless.
    Task978ZG additionally pins the repository-locked PostgreSQL driver
    (psycopg2-binary==2.9.12 per pyproject.toml and uv.lock — the exact
    driver already shipped in the Zeabur container).  With psycopg2 and
    autocommit disabled, every statement runs inside one implicit
    transaction: conn.commit() after the verified seeding is the durability
    boundary and conn.rollback() in the failure path is the atomicity
    boundary.
    """

    @classmethod
    def setUpClass(cls):
        cls.source = MODULE_PATH.read_text(encoding="utf-8")
        cls.tree = ast.parse(cls.source)

    def _bootstrap_function(self) -> ast.FunctionDef:
        for node in self.tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == "bootstrap":
                return node
        raise AssertionError("bootstrap() is missing")

    @staticmethod
    def _calls_with_attr(function: ast.FunctionDef, attr: str) -> list[ast.Call]:
        return [
            node for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == attr
        ]

    def test_bootstrap_uses_repository_locked_psycopg2_driver(self):
        self.assertIn(
            "import psycopg2  # loaded only after the static identity gate",
            self.source,
            "bootstrap must import the repository-locked psycopg2 driver",
        )
        connect_calls = self._calls_with_attr(self._bootstrap_function(), "connect")
        self.assertEqual(len(connect_calls), 1)
        self.assertEqual(
            getattr(connect_calls[0].func, "value", None).id,
            "psycopg2",
            "connect must be called on the locked psycopg2 module",
        )
        # The undeclared psycopg3 package must not be imported or used
        # anywhere (mentions in explanatory comments are permitted).
        self.assertNotRegex(self.source, r"(?m)^\s*import psycopg\s*$")
        self.assertNotIn("psycopg.connect(", self.source)
        self.assertNotIn("psycopg2.sql", self.source)

    def test_connection_pins_autocommit_false_for_one_atomic_transaction(self):
        self.assertIn(
            "conn.autocommit = False",
            self.source,
            "psycopg2 must run with autocommit disabled so the whole "
            "bootstrap is one transaction",
        )

    def test_every_statement_executes_before_the_single_commit(self):
        function = self._bootstrap_function()
        commit_calls = self._calls_with_attr(function, "commit")
        self.assertEqual(
            len(commit_calls), 1,
            "bootstrap must have exactly one conn.commit() durability boundary",
        )
        execute_nodes = [
            node for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "execute"
            and getattr(node.func.value, "id", None) == "cur"
        ]
        self.assertGreater(len(execute_nodes), 0)
        self.assertLess(
            max(node.lineno for node in execute_nodes), commit_calls[0].lineno,
            "every statement must execute before the commit",
        )
        # The identity probe must still execute before any schema mutation
        # (its inner catalog execute is the first statement of the
        # transaction) so a refused target never touches the database.
        self.assertIn("_verify_live_identity(conn, target)", self.source)
        verify_nodes = [
            node for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_verify_live_identity"
        ]
        self.assertEqual(len(verify_nodes), 1)
        seed_call = next(
            node for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "seed_statements"
        )
        self.assertLess(verify_nodes[0].lineno, seed_call.lineno,
                        "identity probe must precede the seed statements")

    def test_identity_probe_executes_before_seed_statements(self):
        function = self._bootstrap_function()
        verify_nodes = [
            node for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_verify_live_identity"
        ]
        self.assertEqual(len(verify_nodes), 1)
        seed_call = next(
            node for node in ast.walk(function)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "seed_statements"
        )
        self.assertLess(verify_nodes[0].lineno, seed_call.lineno)

    def test_rollback_is_the_atomic_failure_boundary(self):
        function = self._bootstrap_function()
        rollback_calls = self._calls_with_attr(function, "rollback")
        self.assertEqual(len(rollback_calls), 1)
        handlers = [
            node for node in ast.walk(function)
            if isinstance(node, ast.ExceptHandler)
        ]
        self.assertTrue(
            any(rollback_calls[0] in ast.walk(handler) for handler in handlers),
            "conn.rollback() must run inside the exception handler",
        )
        try_nodes = [node for node in ast.walk(function) if isinstance(node, ast.Try)]
        self.assertEqual(len(try_nodes), 1)
        finally_calls = self._calls_with_attr(try_nodes[0], "close")
        self.assertEqual(len(finally_calls), 1, "connection must always be closed")

    def test_failure_rolls_back_and_never_commits(self):
        """Task978ZG: a mid-bootstrap failure must leave zero durable changes."""
        module = load_module()
        fake_conn = mock.MagicMock(name="psycopg2_connection")
        fake_cursor = mock.MagicMock(name="cursor")
        fake_conn.cursor.return_value.__enter__.return_value = fake_cursor
        # First execute: live identity probe succeeds.  Second execute: the
        # very first schema statement fails.
        fake_cursor.fetchone.return_value = (
            "task978za_disposable_authority", "task967", 160000,
        )
        fake_cursor.execute.side_effect = [None, RuntimeError("simulated DDL failure")]
        fake_psycopg2 = mock.MagicMock(name="psycopg2")
        fake_psycopg2.connect.return_value = fake_conn
        with mock.patch.dict(sys.modules, {"psycopg2": fake_psycopg2}):
            with self.assertRaises(RuntimeError):
                module.bootstrap(
                    "postgresql://task967:secret@127.0.0.1:5432/task978za_disposable_authority",
                    purpose="TASK978ZA_NATIVE_PG16",
                    acknowledgement="TASK978ZA_DISPOSABLE_AUTHORITY",
                )
        fake_psycopg2.connect.assert_called_once_with(
            "postgresql://task967:secret@127.0.0.1:5432/task978za_disposable_authority",
        )
        fake_conn.rollback.assert_called_once()
        fake_conn.commit.assert_not_called()
        fake_conn.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
