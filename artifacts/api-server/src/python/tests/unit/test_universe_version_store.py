"""Hermetic tests for the additive versioned-universe foundation."""

from __future__ import annotations

import datetime as dt
import unittest
from contextlib import contextmanager
from unittest.mock import MagicMock, patch


BASELINE = [
    "BANKBARODA", "BANKINDIA", "CANBK", "COALINDIA", "FEDERALBNK",
    "GAIL", "HUDCO", "IDFCFIRSTB", "IRCON", "IRFC", "KTKBANK", "MAHABANK",
    "MRPL", "NBCC", "NMDC", "NTPC", "PFC", "PNB", "RECLTD", "RVNL",
    "SAIL", "UNIONBANK", "WIPRO",
]


def _source_row(symbol: str, **overrides):
    row = {
        "symbol": symbol,
        "company_name": f"{symbol} Ltd",
        "sector": "BANK",
        "yahoo_symbol": f"{symbol}.NS",
        "kite_symbol": symbol,
        "instrument_token": None,
        "is_active": True,
        "instrument_exchange": None,
    }
    row.update(overrides)
    return row


class TestNormalization(unittest.TestCase):
    def test_normalization_is_uppercase_trimmed_and_sorted(self):
        import universe_version_store as store

        self.assertEqual(
            store.normalize_symbols([" wipro ", "irfc"]),
            ["IRFC", "WIPRO"],
        )

    def test_duplicate_after_normalization_fails(self):
        import universe_version_store as store

        with self.assertRaisesRegex(ValueError, "duplicate normalized"):
            store.normalize_symbols(["wipro", " WIPRO "])

    def test_malformed_symbol_fails(self):
        import universe_version_store as store

        with self.assertRaises(ValueError):
            store.normalize_symbol("BAD SYMBOL")

    def test_hash_is_order_independent(self):
        import universe_version_store as store

        self.assertEqual(
            store.exact_set_hash(["WIPRO", "IRFC"]),
            store.exact_set_hash(["irfc", "wipro"]),
        )


class TestSchemaSafety(unittest.TestCase):
    def test_schema_is_additive_and_idempotent(self):
        import universe_version_store as store

        cur = MagicMock()
        cur.__enter__ = MagicMock(return_value=cur)
        cur.__exit__ = MagicMock(return_value=False)
        conn = MagicMock()
        conn.cursor.return_value = cur
        cur.rowcount = 1

        store._ensure_schema(conn)
        store._ensure_schema(conn)
        sql = "\n".join(str(call.args[0]) for call in cur.execute.call_args_list).upper()
        self.assertIn("CREATE TABLE IF NOT EXISTS TRADING_UNIVERSES", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS TRADING_UNIVERSE_MEMBERS", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS TRADING_UNIVERSE_AUDIT_EVENTS", sql)
        self.assertIn("UNIQUE (UNIVERSE_ID, SYMBOL)", sql)
        self.assertIn("ENABLED BOOLEAN NOT NULL", sql)
        self.assertIn("REMOVED_AT TIMESTAMPTZ", sql)
        self.assertIn("REMOVED_BY TEXT", sql)
        self.assertIn("TASK946_REJECT_HISTORY_MUTATION", sql)
        self.assertIn("TRG_TASK946_AUDIT_IMMUTABLE", sql)
        self.assertIn("TRG_TASK946_MEMBER_GUARD", sql)
        self.assertNotIn("DROP ", sql)
        self.assertNotIn("TRUNCATE ", sql)
        self.assertNotIn("ALTER TABLE", sql)


class TestBaselineValidation(unittest.TestCase):
    def test_exact_23_symbol_baseline_is_normalized_without_membership_change(self):
        import universe_version_store as store

        rows = [_source_row(symbol.lower()) for symbol in BASELINE]
        projected = store._validate_baseline_rows(rows)
        self.assertEqual([row["symbol"] for row in projected], sorted(BASELINE))
        self.assertEqual(store.exact_set_hash(BASELINE), store.exact_set_hash(
            row["symbol"] for row in projected
        ))
        self.assertTrue(all(row["mapping_status"] == "UNVERIFIED" for row in projected))

    def test_missing_identity_metadata_fails_before_any_database_write(self):
        import universe_version_store as store

        with self.assertRaisesRegex(ValueError, "yahoo_symbol"):
            store._validate_baseline_rows([_source_row("WIPRO", yahoo_symbol=None)])

    def test_duplicate_instrument_token_fails_before_insert(self):
        import universe_version_store as store

        rows = [
            _source_row("WIPRO", instrument_token=100),
            _source_row("IRFC", instrument_token=100),
        ]
        with self.assertRaisesRegex(ValueError, "duplicate enabled instrument"):
            store._validate_baseline_rows(rows)


class TestBaselineImport(unittest.TestCase):
    def _db(self, active_rows, existing_rows=None, persisted_symbols=None):
        cur = MagicMock()
        cur.__enter__ = MagicMock(return_value=cur)
        cur.__exit__ = MagicMock(return_value=False)
        # seed: current rows, existing revisions, persisted members
        cur.fetchall.side_effect = [
            [
                (
                    row["symbol"], row["company_name"], row["sector"],
                    row["yahoo_symbol"], row["kite_symbol"],
                    row["instrument_token"], row["is_active"],
                    row.get("instrument_exchange"),
                    None, None, None, None,
                )
                for row in active_rows
            ],
            existing_rows or [],
            [(symbol,) for symbol in (persisted_symbols or [])],
        ]
        cur.fetchone.side_effect = [(77,), (88, 1, "ACTIVE")]
        cur.rowcount = 1
        conn = MagicMock()
        conn.cursor.return_value = cur

        @contextmanager
        def connect():
            try:
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        return conn, cur, connect

    def test_seed_is_atomic_and_verifies_exact_persisted_set(self):
        import universe_version_store as store

        rows = [_source_row(symbol) for symbol in BASELINE]
        conn, cur, connect = self._db(rows, persisted_symbols=BASELINE)
        with patch.object(store, "_db_available", return_value=True), \
             patch.object(store, "_connect", connect), \
             patch("psycopg2.extras.execute_values") as execute_values:
            result = store.seed_baseline()

        self.assertTrue(result["success"], result)
        self.assertEqual(result["symbol_count"], 23)
        self.assertEqual(result["version"], 1)
        self.assertEqual(result["mapping_coverage"], 0)
        self.assertTrue(any(
            "trading_universe_audit_events" in str(call.args[0])
            for call in cur.execute.call_args_list
        ))
        execute_values.assert_called_once()
        # Schema creation commits before the import transaction; the seeded
        # source/revision/members/audit batch commits once at the context exit.
        self.assertEqual(conn.commit.call_count, 2)

    def test_persisted_set_mismatch_fails_closed(self):
        import universe_version_store as store

        rows = [_source_row(symbol) for symbol in BASELINE]
        conn, _cur, connect = self._db(rows, persisted_symbols=BASELINE[:-1])
        with patch.object(store, "_db_available", return_value=True), \
             patch.object(store, "_connect", connect), \
             patch("psycopg2.extras.execute_values"):
            result = store.seed_baseline()

        self.assertFalse(result["success"])
        self.assertIn("exact-set", result["error"])
        self.assertGreaterEqual(conn.rollback.call_count, 1)

    def test_conflicting_existing_revision_is_not_duplicated(self):
        import universe_version_store as store

        rows = [_source_row(symbol) for symbol in BASELINE]
        conn, cur, connect = self._db(
            rows,
            existing_rows=[(44, 4, "ACTIVE", "different-hash")],
        )
        with patch.object(store, "_db_available", return_value=True), \
             patch.object(store, "_connect", connect):
            result = store.seed_baseline()

        self.assertFalse(result["success"])
        self.assertIn("conflicting revision", result["error"])
        inserts = [
            str(call.args[0]).upper()
            for call in cur.execute.call_args_list
            if "INSERT INTO" in str(call.args[0]).upper()
        ]
        self.assertEqual(inserts, [])


class TestAuditContract(unittest.TestCase):
    def test_unknown_audit_action_is_rejected(self):
        import universe_version_store as store

        with patch.object(store, "_db_available", return_value=True):
            result = store.append_audit_event(actor="test", action="UPDATE")
        self.assertFalse(result["success"])
        self.assertIn("unsupported audit action", result["error"])


class TestResolutionIntegrity(unittest.TestCase):
    def test_resolver_fails_closed_when_enabled_count_or_hash_drift(self):
        import universe_version_store as store

        revision = {
            "id": 1,
            "universe_key": store.CUSTOM_UNIVERSE_KEY,
            "version": 1,
            "status": "ACTIVE",
            "effective_from": dt.datetime.now(dt.timezone.utc).isoformat(),
            "enabled_symbol_count": 23,
            "exact_set_hash": store.exact_set_hash(BASELINE),
        }
        with patch.object(store, "get_revision", return_value=revision), \
             patch.object(store, "get_members", return_value=[
                 {"symbol": "WIPRO", "mapping_status": "UNVERIFIED"}
             ]):
            result = store.resolve_enabled_symbols(version=1)

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "revision_integrity_mismatch")


if __name__ == "__main__":
    unittest.main()