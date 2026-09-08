"""Hermetic safety tests for the guarded custom-universe baseline migration."""

from __future__ import annotations

import datetime as dt
import inspect
import unittest
from contextlib import contextmanager
from decimal import Decimal
from unittest.mock import patch

import custom_universe_baseline_migration as migration


def source_rows():
    return [
        {
            "symbol": symbol,
            "company_name": f"{symbol} Ltd",
            "sector": "BANK" if "BANK" in symbol or symbol in {"CANBK", "PNB"} else "INFRA",
            "yahoo_symbol": f"{symbol}.NS",
            "kite_symbol": symbol,
            "instrument_token": index + 1000,
            "instrument_exchange": "NSE",
            "price_min": Decimal("1.25"),
            "price_max": Decimal("1000.00"),
            "ohlcv_available": True,
            "is_active": True,
        }
        for index, symbol in enumerate(migration.APPROVED_SYMBOLS)
    ]


def instruments():
    return [
        {
            "tradingsymbol": row["symbol"],
            "instrument_token": row["instrument_token"],
            "exchange": "NSE",
            "segment": "NSE",
            "instrument_type": "EQ",
        }
        for row in source_rows()
    ]


def valid_evidence():
    members, validation = migration._members_from_source(
        source_rows(), instruments(), instrument_cache_fresh=True
    )
    settings = {
        "active_intraday_universe": "CUSTOM_LOW_PRICE_SECTOR",
        "auto_paper_entries": False,
        "auto_paper_entries_confirmed_at": None,
        "bootstrap_paper_enabled": False,
        "auto_paper_exits": True,
    }
    return {
        "success": True,
        "ready": True,
        "validation": validation,
        "safety": {
            "valid": True,
            "active_intraday_universe": "CUSTOM_LOW_PRICE_SECTOR",
            "settings_digest": migration._settings_digest(settings),
        },
        "existing_revisions": [],
        "conflict": False,
        "idempotent": False,
        "members": members,
    }, settings


class RecordingCursor:
    def __init__(self, settings):
        self.settings = settings
        self.statements = []
        self.rowcount = 1
        self._fetchone = None
        self._fetchall = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, params=None):
        normalized = " ".join(str(sql).split()).upper()
        self.statements.append((normalized, params))
        self._fetchone = None
        self._fetchall = []
        if "INSERT INTO TRADING_UNIVERSE_SOURCES" in normalized:
            self._fetchone = (11,)
        elif "INSERT INTO TRADING_UNIVERSES" in normalized:
            self._fetchone = (22,)
        elif normalized.startswith("SELECT SYMBOL, INSTRUMENT_TOKEN, MAPPING_STATUS"):
            self._fetchall = [
                (row["symbol"], row["instrument_token"], "MAPPED")
                for row in source_rows()
            ]
        elif f"INSERT INTO {migration.AUDIT_TABLE.upper()}" in normalized:
            self._fetchone = (dt.datetime.now(dt.timezone.utc),)
        elif normalized.startswith("SELECT DATA FROM PHASE20_SETTINGS"):
            self._fetchone = (dict(self.settings),)

    def fetchone(self):
        return self._fetchone

    def fetchall(self):
        return self._fetchall


class RecordingConnection:
    def __init__(self, settings):
        self.cur = RecordingCursor(settings)
        self.committed = False
        self.rolled_back = False

    def cursor(self):
        return self.cur


def connection_context(connection):
    @contextmanager
    def connect():
        try:
            yield connection
            connection.committed = True
        except Exception:
            connection.rolled_back = True
            raise
    return connect


class TestBaselineContract(unittest.TestCase):
    def test_exact_approved_set_and_hash_are_stable(self):
        migration._ensure_contract()
        self.assertEqual(len(migration.APPROVED_SYMBOLS), 23)
        self.assertEqual(
            migration.versions.exact_set_hash(migration.APPROVED_SYMBOLS),
            migration.APPROVED_SET_HASH,
        )

    def test_empty_authority_fails_closed_without_fallback(self):
        members, result = migration._members_from_source(
            [], instruments(), instrument_cache_fresh=True
        )
        self.assertEqual(members, [])
        self.assertFalse(result["valid"])
        self.assertEqual(result["error"], "baseline_set_not_proven")
        self.assertEqual(result["source_symbols"], [])

    def test_exact_source_preserves_all_23_members_and_mappings(self):
        rows = source_rows()
        rows[0]["company_name"] = None
        members, result = migration._members_from_source(
            rows, instruments(), instrument_cache_fresh=True
        )
        self.assertTrue(result["valid"], result)
        self.assertEqual(result["source_symbols"], sorted(migration.APPROVED_SYMBOLS))
        self.assertEqual(result["mapping_coverage"]["mapped"], 23)
        self.assertEqual(result["mapping_coverage"]["total"], 23)
        self.assertEqual(len(members), 23)
        self.assertIsNone(members[0]["metadata"]["company_name"])

    def test_source_read_holds_table_lock_against_membership_phantoms(self):
        evidence, settings = valid_evidence()
        cur = RecordingCursor(settings)
        with patch.object(migration, "_load_master_rows", return_value=source_rows()), \
             patch.object(migration, "_existing_state", return_value=[]), \
             patch.object(migration, "_read_safety", return_value=evidence["safety"]):
            migration._evaluate(cur, instruments(), {"is_fresh": True})
        self.assertTrue(cur.statements)
        self.assertEqual(
            cur.statements[0][0],
            "LOCK TABLE CUSTOM_UNIVERSE_MASTER IN SHARE MODE",
        )

    def test_addition_removal_or_substitution_is_rejected(self):
        rows = source_rows()[1:]
        rows.append({**source_rows()[0], "symbol": "INFY", "kite_symbol": "INFY"})
        _members, result = migration._members_from_source(
            rows, instruments(), instrument_cache_fresh=True
        )
        self.assertFalse(result["valid"])
        self.assertEqual(result["error"], "baseline_set_not_proven")
        self.assertEqual(result["missing_symbols"], ["BANKBARODA"])
        self.assertEqual(result["unexpected_symbols"], ["INFY"])

    def test_non_nse_non_cash_non_eq_and_duplicate_tokens_fail_mapping(self):
        bad = instruments()
        bad[0] = {**bad[0], "exchange": "BSE"}
        bad[1] = {**bad[1], "segment": "NFO"}
        bad[2] = {**bad[2], "instrument_type": "FUT"}
        bad[3] = {**bad[3], "instrument_token": bad[4]["instrument_token"]}
        _members, result = migration._members_from_source(
            source_rows(), bad, instrument_cache_fresh=True
        )
        codes = {error["code"] for error in result["errors"]}
        self.assertFalse(result["valid"])
        self.assertIn("INVALID_EXCHANGE", codes)
        self.assertIn("INVALID_SEGMENT", codes)
        self.assertIn("UNSUPPORTED_INSTRUMENT_TYPE", codes)
        self.assertIn("PERSISTED_MAPPING_MISMATCH", codes)

    def test_stale_instrument_reference_fails_closed(self):
        _members, result = migration._members_from_source(
            source_rows(), instruments(), instrument_cache_fresh=False
        )
        self.assertFalse(result["valid"])
        self.assertIn(
            "STALE_KITE_INSTRUMENT_CACHE",
            {error["code"] for error in result["errors"]},
        )

    def test_activation_is_scheduled_for_next_natural_0900_ist_boundary(self):
        friday = dt.datetime(2026, 8, 28, 12, 0, tzinfo=dt.timezone.utc)
        boundary = migration._next_natural_session_boundary(friday)
        local = boundary.astimezone(migration.IST)
        self.assertGreater(local.date(), friday.astimezone(migration.IST).date())
        self.assertEqual((local.hour, local.minute), (9, 0))


class TestMigrationExecution(unittest.TestCase):
    def test_exact_confirmation_is_required_before_database_access(self):
        with patch.object(migration.versions, "_db_available") as available:
            result = migration.execute(confirmation="MIGRATE")
        self.assertEqual(result["error"], "typed_confirmation_mismatch")
        available.assert_not_called()

    def test_controlled_execution_inspection_failure_blocks_safety_gate(self):
        settings = {
            "active_intraday_universe": "CUSTOM_LOW_PRICE_SECTOR",
            "auto_paper_entries": False,
            "auto_paper_entries_confirmed_at": None,
            "bootstrap_paper_enabled": False,
            "auto_paper_exits": True,
        }
        cur = RecordingCursor(settings)
        with patch(
            "controlled_paper_entry_flags.get_controlled_paper_entry_flags",
            side_effect=RuntimeError("flags unavailable"),
        ):
            safety = migration._read_safety(cur)
        self.assertFalse(safety["valid"])
        self.assertFalse(safety["controlled_execution_inspection_ok"])
        self.assertIn("flags unavailable", safety["controlled_execution_inspection_error"])
        self.assertEqual(
            cur.statements[0][0],
            "LOCK TABLE PHASE20_PAPER_TRADES IN SHARE MODE",
        )

    def test_atomic_write_creates_active_revision_validation_and_audit(self):
        evidence, settings = valid_evidence()
        conn = RecordingConnection(settings)
        with patch.object(migration.versions, "_db_available", return_value=True), \
             patch.object(migration, "ensure_schema", return_value=True), \
             patch.object(
                 migration.management, "_instrument_reference",
                 return_value=(instruments(), {"is_fresh": True}),
             ), \
             patch.object(migration, "_evaluate", return_value=evidence), \
             patch.object(migration.versions, "_connect", connection_context(conn)):
            result = migration.execute(confirmation=migration.CONFIRMATION)

        self.assertTrue(result["success"], result)
        self.assertEqual(result["status"], "MIGRATED")
        self.assertEqual(result["active_revision"]["status"], "ACTIVE")
        self.assertEqual(result["active_revision"]["enabled_symbol_count"], 23)
        self.assertEqual(result["migration_audit"]["action"], "BASELINE_MIGRATION")
        self.assertTrue(conn.committed)
        sql = "\n".join(statement for statement, _params in conn.cur.statements)
        self.assertIn("INSERT INTO TRADING_UNIVERSE_VALIDATIONS", sql)
        self.assertIn(f"INSERT INTO {migration.AUDIT_TABLE.upper()}", sql)
        self.assertIn("UPDATE TRADING_UNIVERSES SET STATUS = 'ACTIVE'", sql)
        self.assertNotIn("UPDATE CUSTOM_UNIVERSE_MASTER", sql)

    def test_migration_source_cannot_mutate_settings_portfolio_or_ledger(self):
        source = inspect.getsource(migration.execute).upper()
        self.assertNotIn("UPDATE PHASE20_SETTINGS", source)
        self.assertNotIn("INSERT INTO PHASE20_PAPER_TRADES", source)
        self.assertNotIn("UPDATE PHASE20_PAPER_TRADES", source)
        self.assertNotIn("DELETE FROM PHASE20_PAPER_TRADES", source)
        self.assertNotIn("PAPER_PORTFOLIO", source)

    def test_existing_conflicting_revision_is_rejected_before_insert(self):
        evidence, settings = valid_evidence()
        evidence.update({
            "ready": False,
            "conflict": True,
            "existing_revisions": [{
                "id": 9, "version": 1, "status": "ACTIVE",
                "enabled_symbol_count": 22, "exact_set_hash": "wrong",
            }],
        })
        conn = RecordingConnection(settings)
        with patch.object(migration.versions, "_db_available", return_value=True), \
             patch.object(migration, "ensure_schema", return_value=True), \
             patch.object(
                 migration.management, "_instrument_reference",
                 return_value=(instruments(), {"is_fresh": True}),
             ), \
             patch.object(migration, "_evaluate", return_value=evidence), \
             patch.object(migration.versions, "_connect", connection_context(conn)):
            result = migration.execute(confirmation=migration.CONFIRMATION)
        self.assertEqual(result["error"], "conflicting_revision")
        self.assertFalse(any(
            "INSERT INTO TRADING_UNIVERSES" in statement
            for statement, _params in conn.cur.statements
        ))

    def test_malformed_active_effective_interval_is_not_idempotent(self):
        evidence, _settings = valid_evidence()
        base_revision = {
            "id": 9, "version": 1, "status": "ACTIVE",
            "enabled_symbol_count": 23,
            "exact_set_hash": migration.APPROVED_SET_HASH,
            "effective_from": None,
            "effective_until": None,
        }
        for revision in (
            base_revision,
            {
                **base_revision,
                "effective_from": "2026-08-31T03:30:00+00:00",
                "effective_until": "2026-09-01T03:30:00+00:00",
            },
        ):
            cur = RecordingCursor({})
            with patch.object(migration, "_load_master_rows", return_value=source_rows()), \
                 patch.object(migration, "_existing_state", return_value=[revision]), \
                 patch.object(migration, "_read_safety", return_value=evidence["safety"]), \
                 patch.object(migration, "_existing_revision_integrity", return_value=True):
                result = migration._evaluate(cur, instruments(), {"is_fresh": True})
            self.assertFalse(result["idempotent"])
            self.assertTrue(result["conflict"])

    def test_failed_persisted_exact_set_rolls_back_whole_transaction(self):
        evidence, settings = valid_evidence()
        conn = RecordingConnection(settings)
        original_execute = conn.cur.execute

        def execute_with_partial(sql, params=None):
            original_execute(sql, params)
            if "SELECT SYMBOL, INSTRUMENT_TOKEN" in " ".join(str(sql).split()).upper():
                conn.cur._fetchall = conn.cur._fetchall[:-1]

        conn.cur.execute = execute_with_partial
        with patch.object(migration.versions, "_db_available", return_value=True), \
             patch.object(migration, "ensure_schema", return_value=True), \
             patch.object(
                 migration.management, "_instrument_reference",
                 return_value=(instruments(), {"is_fresh": True}),
             ), \
             patch.object(migration, "_evaluate", return_value=evidence), \
             patch.object(migration.versions, "_connect", connection_context(conn)):
            result = migration.execute(confirmation=migration.CONFIRMATION)
        self.assertFalse(result["success"])
        self.assertIn("persisted baseline integrity", result["error"])
        self.assertTrue(conn.rolled_back)


if __name__ == "__main__":
    unittest.main()