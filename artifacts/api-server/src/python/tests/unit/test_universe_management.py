"""Hermetic safety tests for the versioned universe-management workflow."""

from __future__ import annotations

import unittest
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


if __name__ == "__main__":
    unittest.main()