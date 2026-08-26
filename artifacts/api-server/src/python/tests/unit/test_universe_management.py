"""Hermetic safety tests for the versioned universe-management workflow."""

from __future__ import annotations

import unittest
from unittest.mock import patch
from datetime import datetime


def _member(symbol: str = "WIPRO", **overrides):
    member = {
        "symbol": symbol,
        "sector": "IT",
        "company_name": "Wipro Limited",
        "yahoo_symbol": "WIPRO.NS",
        "kite_symbol": symbol,
        "price_min": 20,
        "price_max": 500,
        "ohlcv_available": True,
    }
    member.update(overrides)
    return member


def _instrument(symbol: str = "WIPRO", token: int = 969473, **overrides):
    instrument = {
        "symbol": symbol,
        "exchange": "NSE",
        "segment": "NSE",
        "instrument_type": "EQ",
        "token": token,
    }
    instrument.update(overrides)
    return instrument


class TestDraftValidation(unittest.TestCase):
    def test_normalises_and_accepts_exact_nse_equity_mapping(self):
        from universe_management import validate_members

        result = validate_members([_member(" wipro ")], [_instrument()])

        self.assertTrue(result["valid"])
        self.assertEqual(result["status"], "VALIDATION_PASS")
        self.assertEqual(result["normalized_members"][0]["symbol"], "WIPRO")
        self.assertEqual(result["mapping_coverage"], {
            "mapped": 1, "total": 1, "percent": 100.0, "complete": True,
        })

    def test_missing_required_metadata_blocks_draft_member(self):
        from universe_management import validate_members

        result = validate_members(
            [_member(company_name="")],
            [_instrument()],
        )

        self.assertFalse(result["valid"])
        self.assertIn(
            "MISSING_REQUIRED_METADATA",
            {error["code"] for error in result["errors"]},
        )

    def test_wrong_exchange_segment_or_type_is_explicit(self):
        from universe_management import validate_members

        result = validate_members(
            [_member()],
            [_instrument(exchange="BSE", segment="BSE", instrument_type="BE")],
        )

        codes = {error["code"] for error in result["errors"]}
        self.assertTrue({
            "INVALID_EXCHANGE", "INVALID_SEGMENT", "UNSUPPORTED_INSTRUMENT_TYPE",
        }.issubset(codes))

    def test_duplicate_kite_token_is_rejected(self):
        from universe_management import validate_members

        result = validate_members(
            [_member("WIPRO"), _member("INFY")],
            [_instrument("WIPRO", 123), _instrument("INFY", 123)],
        )

        self.assertFalse(result["valid"])
        self.assertIn(
            "DUPLICATE_INSTRUMENT_TOKEN",
            {error["code"] for error in result["errors"]},
        )

    def test_persisted_mapping_must_equal_current_kite_binding(self):
        from universe_management import validate_members

        stale = _member(
            exchange="NSE",
            instrument_token=1,
            mapping_status="MAPPED",
        )
        result = validate_members(
            [stale],
            [_instrument(token=969473)],
            require_persisted_binding=True,
        )

        self.assertFalse(result["valid"])
        self.assertIn(
            "PERSISTED_MAPPING_MISMATCH",
            {error["code"] for error in result["errors"]},
        )
        self.assertEqual(
            result["mapping_bindings"]["WIPRO"]["instrument_token"],
            969473,
        )

    def test_empty_enabled_set_cannot_pass_validation(self):
        from universe_management import validate_members

        result = validate_members([], [])

        self.assertFalse(result["valid"])
        self.assertEqual(result["status"], "VALIDATION_FAIL")
        self.assertIn(
            "EMPTY_ENABLED_UNIVERSE",
            {error["code"] for error in result["errors"]},
        )


class TestInitialReleaseActivationLock(unittest.TestCase):
    def test_activation_request_requires_exact_version_confirmation_before_validation(self):
        from universe_management import request_activation

        result = request_activation(
            version=7,
            confirmation="ACTIVATE 6",
            expected_confirmation="ACTIVATE 7",
        )

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "typed_confirmation_mismatch")

    def test_activation_is_locked_before_any_database_or_state_change(self):
        from universe_management import ACTIVATION_LOCKED, activate

        self.assertTrue(ACTIVATION_LOCKED)
        result = activate(
            version=7,
            confirmation="ACTIVATE 7",
            expected_confirmation="ACTIVATE 7",
        )
        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "activation_locked")
        self.assertEqual(result["status"], "LOCKED")

    def test_next_eligible_session_is_an_nse_open_in_ist(self):
        from universe_management import _next_session_open

        effective_at = datetime.fromisoformat(_next_session_open())
        self.assertEqual((effective_at.hour, effective_at.minute), (3, 45))
        self.assertEqual(effective_at.tzinfo.utcoffset(effective_at).total_seconds(), 0)


class TestDraftLifecycleGuard(unittest.TestCase):
    def test_create_draft_refuses_when_another_draft_is_already_open(self):
        import universe_management

        class Cursor:
            def __init__(self):
                self.last_sql = ""
                self.statements = []

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def execute(self, sql, _params=None):
                self.last_sql = sql
                self.statements.append(sql)

            def fetchone(self):
                if "status = 'DRAFT'" in self.last_sql:
                    return (12,)
                return None

        class Connection:
            def __init__(self, cursor):
                self._cursor = cursor

            def cursor(self):
                return self._cursor

        class ConnectionContext:
            def __init__(self, connection):
                self._connection = connection

            def __enter__(self):
                return self._connection

            def __exit__(self, *_args):
                return False

        cursor = Cursor()
        with (
            patch.object(universe_management.versions, "_db_available", return_value=True),
            patch.object(
                universe_management.versions,
                "_connect",
                return_value=ConnectionContext(Connection(cursor)),
            ),
            patch.object(universe_management, "_ensure_management_schema"),
        ):
            result = universe_management.create_draft()

        self.assertFalse(result["success"])
        self.assertEqual(result["error"], "draft_already_open")
        self.assertEqual(result["draft_version"], 12)
        self.assertFalse(any("INSERT INTO trading_universes" in sql for sql in cursor.statements))


if __name__ == "__main__":
    unittest.main()