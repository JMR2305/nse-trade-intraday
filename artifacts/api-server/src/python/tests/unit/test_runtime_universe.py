"""Regression tests for the immutable runtime-universe session boundary."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


def _context():
    return {
        "natural_session": "2026-08-26",
        "universe_key": "CUSTOM_LOW_PRICE_SECTOR",
        "universe_id": 42,
        "version": 7,
        "enabled_symbols": ["IRFC", "WIPRO"],
        "symbol_count": 2,
        "exact_set_hash": "ignored",
        "effective_from": "2026-08-26T03:30:00+00:00",
        "pinned_at": "2026-08-26T03:31:00+00:00",
    }


def _resolved():
    import universe_version_store as versions
    symbols = ["IRFC", "WIPRO"]
    return {
        "success": True,
        "universe_key": "CUSTOM_LOW_PRICE_SECTOR",
        "universe_id": 42,
        "version": 7,
        "symbols": symbols,
        "symbol_count": 2,
        "exact_set_hash": versions.exact_set_hash(symbols),
        "effective_from": "2026-08-26T03:30:00+00:00",
    }


def test_existing_session_pin_wins_over_a_later_configuration_change():
    import runtime_universe as runtime
    import universe_version_store as versions

    pin = _context()
    pin["exact_set_hash"] = versions.exact_set_hash(pin["enabled_symbols"])
    conn = MagicMock()

    @contextmanager
    def connection():
        yield conn

    with (
        patch.object(versions, "_db_available", return_value=True),
        patch.object(versions, "_connect", connection),
        patch.object(runtime, "_load_pin", return_value=pin),
        patch.object(runtime, "_configured_key",
                     side_effect=AssertionError("existing pin must be used")),
    ):
        got = runtime.resolve_active_universe(
            datetime(2026, 8, 26, 8, 0, tzinfo=timezone.utc)
        )

    assert got["version"] == 7
    assert got["enabled_symbols"] == ["IRFC", "WIPRO"]


def test_first_session_resolution_uses_session_open_not_current_time():
    import runtime_universe as runtime
    import universe_version_store as versions

    conn = MagicMock()
    pinned = _context()
    pinned["exact_set_hash"] = versions.exact_set_hash(pinned["enabled_symbols"])

    @contextmanager
    def connection():
        yield conn

    with (
        patch.object(versions, "_db_available", return_value=True),
        patch.object(versions, "_connect", connection),
        patch.object(runtime, "_configured_key",
                     return_value="CUSTOM_LOW_PRICE_SECTOR"),
        patch.object(runtime, "_load_pin", side_effect=[None, pinned]),
        patch.object(versions, "resolve_enabled_symbols",
                     return_value=_resolved()) as resolve,
    ):
        runtime.resolve_active_universe(
            datetime(2026, 8, 26, 10, 30, tzinfo=timezone.utc)
        )

    assert resolve.call_args.kwargs["effective_at"] == datetime(
        2026, 8, 26, 3, 30, tzinfo=timezone.utc
    )


def test_default_nifty_mode_bootstraps_and_resolves_durable_baseline():
    """A fresh deployment's configured default must not become a list fallback."""
    import runtime_universe as runtime
    import universe_version_store as versions

    conn = MagicMock()
    pinned = _context()
    pinned.update({
        "universe_key": "NIFTY_50",
        "enabled_symbols": ["RELIANCE", "TCS"],
        "symbol_count": 2,
        "exact_set_hash": versions.exact_set_hash(["RELIANCE", "TCS"]),
    })
    resolved = {
        "success": True,
        "universe_key": "NIFTY_50",
        "universe_id": 1,
        "version": 1,
        "symbols": ["RELIANCE", "TCS"],
        "symbol_count": 2,
        "exact_set_hash": versions.exact_set_hash(["RELIANCE", "TCS"]),
        "effective_from": "1970-01-01T00:00:00+00:00",
    }

    @contextmanager
    def connection():
        yield conn

    with (
        patch.object(versions, "_db_available", return_value=True),
        patch.object(versions, "_connect", connection),
        patch.object(runtime, "_configured_key", return_value="NIFTY_50"),
        patch.object(runtime, "_load_pin", side_effect=[None, pinned]),
        patch.object(versions, "resolve_enabled_symbols", return_value=resolved),
        patch.object(versions, "ensure_builtin_nifty_baseline") as bootstrap,
    ):
        got = runtime.resolve_active_universe(
            datetime(2026, 8, 26, 10, 30, tzinfo=timezone.utc)
        )

    bootstrap.assert_called_once_with(conn)
    assert got["universe_key"] == "NIFTY_50"
    assert got["exact_set_hash"] == resolved["exact_set_hash"]


@pytest.mark.parametrize("current_key", ["CUSTOM_LOW_PRICE_SECTOR", "NIFTY_50"])
def test_post_boundary_selector_change_fails_before_first_pin(current_key):
    import runtime_universe as runtime
    import universe_version_store as versions

    conn = MagicMock()
    cur = MagicMock()
    cur.fetchone.return_value = (
        current_key,
        datetime(2026, 8, 26, 4, 0, tzinfo=timezone.utc),
    )
    conn.cursor.return_value.__enter__.return_value = cur

    @contextmanager
    def connection():
        yield conn

    with (
        patch.object(versions, "_db_available", return_value=True),
        patch.object(versions, "_connect", connection),
        patch.object(versions, "ensure_builtin_nifty_baseline"),
        patch.object(runtime, "_load_pin", return_value=None),
        patch.object(runtime, "_configured_key", return_value=current_key),
    ):
        with pytest.raises(runtime.RuntimeUniverseUnavailable, match="changed after"):
            runtime.resolve_active_universe(
                datetime(2026, 8, 26, 10, 30, tzinfo=timezone.utc)
            )


def test_malformed_pinned_count_fails_closed():
    import runtime_universe as runtime

    context = _context()
    context["symbol_count"] = 3
    with pytest.raises(runtime.RuntimeUniverseUnavailable, match="count"):
        runtime._compact(context)