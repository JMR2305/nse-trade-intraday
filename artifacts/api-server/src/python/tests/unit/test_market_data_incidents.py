"""Unit contracts for durable current-price authority incident classification."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PYTHON_DIR = Path(__file__).resolve().parents[2]
if str(PYTHON_DIR) not in sys.path:
    sys.path.insert(0, str(PYTHON_DIR))

# market_data_incidents intentionally imports these small store helpers at
# module import.  Stub them so classification remains hermetic and never
# reaches a developer database.
import types
_store = types.ModuleType("scan_state_store")
_store.db_available = lambda: False
_store._connect = lambda: None
sys.modules.setdefault("scan_state_store", _store)

import market_data_incidents as incidents


def healthy() -> dict:
    return {
        "active_universe_count": 3,
        "symbols_on_kite": 3,
        "symbols_fallback": 0,
        "symbols_stale": 0,
        "symbols_unavailable": 0,
        "symbols_synthetic": 0,
        "current_quote_provider": "ZERODHA_KITE",
        "current_quote_freshness": "LIVE",
        "kite_quote_timestamps_fresh": True,
        "market_timestamp_fresh": True,
        "historical_ohlcv_provider": "YFINANCE",
    }


class _State:
    active = None


class _Cursor:
    def __init__(self, state):
        self.state = state
        self.last_sql = ""
        self.last_args = ()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, sql, args=()):
        self.last_sql = " ".join(str(sql).split())
        self.last_args = args
        if "INSERT INTO market_data_fallback_incidents" in self.last_sql:
            self.state.active = (args[0], args[3], 1)
        elif "UPDATE market_data_fallback_incidents SET status='RECOVERED'" in self.last_sql:
            self.state.active = None
        elif "UPDATE market_data_fallback_incidents SET" in self.last_sql:
            self.state.active = (args[-1], args[1], self.state.active[2] + args[10])

    def fetchone(self):
        if "SELECT id, latest_scan_id, detection_count" in self.last_sql:
            return self.state.active
        return None


class _Connection:
    def __init__(self, state):
        self.state = state

    def cursor(self):
        return _Cursor(self.state)

    def commit(self):
        pass

    def close(self):
        pass


class MarketDataIncidentClassificationTests(unittest.TestCase):
    def test_custom_scan_health_uses_the_persisted_scan_authority_not_legacy_master(self):
        scan = {
            "scan_id": "scheduled-custom-1",
            "snapshot_ts": "2026-09-21T07:53:48Z",
            "trigger_origin": "SCHEDULED",
            "universe_mode": "CUSTOM_LOW_PRICE_SECTOR",
            "universe": ["BANKBARODA", "WIPRO"],
            "recommendations": [
                {
                    "symbol": symbol,
                    "data_source": "yfinance",
                    "current_price_source": "yfinance_daily_bars",
                    "execution_price_source": "yfinance_daily_bars",
                }
                for symbol in ("BANKBARODA", "WIPRO")
            ],
        }
        config = types.ModuleType("config")
        config.get_active_intraday_universe = lambda: types.SimpleNamespace(
            value="CUSTOM_LOW_PRICE_SECTOR")
        instruments = types.ModuleType("kite_instrument_cache")
        instruments.get_cached_instruments = lambda: [
            {"symbol": "BANKBARODA", "token": 1},
            {"symbol": "WIPRO", "token": 2},
        ]
        session = types.ModuleType("kite_session_manager")
        session.cached_session_metadata = lambda: {
            "kite_connected": True, "session_fresh": True}
        hours = types.ModuleType("market_hours")
        hours.market_status = lambda: {"state": "OPEN"}
        legacy = types.ModuleType("custom_universe_store")
        legacy.get_active_symbols = lambda: self.fail(
            "legacy custom-universe master must not replace scan authority")
        legacy.get_active_symbol_metadata = lambda: self.fail(
            "legacy custom-universe metadata must not replace instrument cache")

        with patch.dict(sys.modules, {
            "config": config,
            "kite_instrument_cache": instruments,
            "kite_session_manager": session,
            "market_hours": hours,
            "custom_universe_store": legacy,
        }):
            health = incidents.health_for_scan_snapshot(scan)

        self.assertEqual(health["active_universe_count"], 2)
        self.assertEqual(health["valid_token_count"], 2)
        self.assertEqual(health["symbols_fallback"], 2)
        self.assertEqual(health["symbols_unavailable"], 0)
        self.assertEqual(health["current_quote_provider"], "YFINANCE")
        classified = incidents.classify_health(health)
        self.assertTrue(classified["affected"])
        self.assertEqual(classified["severity"], "WARNING")

    def test_missing_scan_evidence_is_not_treated_as_healthy(self):
        result = incidents.classify_health(None)
        self.assertTrue(result["affected"])
        self.assertEqual(result["severity"], "CRITICAL")

    def test_healthy_kite_execution_data_recovers_even_with_yfinance_history(self):
        result = incidents.classify_health(healthy())
        self.assertFalse(result["affected"])
        self.assertEqual(result["provider"], "ZERODHA_KITE")

    def test_fallback_provider_opens_incident(self):
        data = healthy()
        data.update({
            "symbols_on_kite": 0,
            "symbols_fallback": 3,
            "current_quote_provider": "YFINANCE",
            "current_quote_freshness": "FALLBACK",
        })
        result = incidents.classify_health(data)
        self.assertTrue(result["affected"])
        self.assertEqual(result["severity"], "WARNING")

    def test_stale_kite_data_cannot_recover_an_episode(self):
        data = healthy()
        data.update({
            "symbols_stale": 1,
            "current_quote_freshness": "STALE",
            "kite_quote_timestamps_fresh": False,
        })
        result = incidents.classify_health(data)
        self.assertTrue(result["affected"])
        self.assertEqual(result["severity"], "HIGH")

    def test_unavailable_authority_is_critical(self):
        data = healthy()
        data.update({
            "symbols_on_kite": 0,
            "symbols_unavailable": 3,
            "current_quote_provider": "UNAVAILABLE_NOT_PROVEN",
            "current_quote_freshness": "UNAVAILABLE_NOT_PROVEN",
        })
        result = incidents.classify_health(data)
        self.assertTrue(result["affected"])
        self.assertEqual(result["severity"], "CRITICAL")

    def test_severity_override_is_explicit_and_deterministic(self):
        data = healthy()
        data.update({
            "symbols_on_kite": 0,
            "symbols_fallback": 3,
            "current_quote_provider": "YFINANCE",
            "current_quote_freshness": "FALLBACK",
        })
        with patch.dict(os.environ, {"MARKET_DATA_FALLBACK_INCIDENT_SEVERITY": "HIGH"}):
            self.assertEqual(incidents.classify_health(data)["severity"], "HIGH")

    def test_one_continuous_episode_updates_then_recovers(self):
        state = _State()
        degraded = healthy()
        degraded.update({
            "symbols_on_kite": 0,
            "symbols_fallback": 3,
            "current_quote_provider": "YFINANCE",
            "current_quote_freshness": "FALLBACK",
            "latest_scan": {"scan_id": "scan-a"},
        })
        with patch.object(incidents, "db_available", return_value=True), \
             patch.object(incidents, "_connect", side_effect=lambda: _Connection(state)), \
             patch.object(incidents, "_ensure_schema"):
            opened = incidents.observe_health(degraded)
            same_scan = incidents.observe_health(degraded)
            degraded["latest_scan"] = {"scan_id": "scan-b"}
            next_scan = incidents.observe_health(degraded)
            recovered = healthy()
            recovered["latest_scan"] = {"scan_id": "scan-c"}
            closed = incidents.observe_health(recovered)

        self.assertEqual(opened["action"], "OPENED")
        self.assertEqual(same_scan["action"], "UPDATED")
        self.assertEqual(next_scan["action"], "UPDATED")
        self.assertEqual(closed["action"], "RECOVERED")
        self.assertEqual(opened["id"], same_scan["id"])
        self.assertEqual(opened["id"], next_scan["id"])
        self.assertEqual(closed["id"], opened["id"])
        self.assertIsNone(state.active)


if __name__ == "__main__":
    unittest.main()