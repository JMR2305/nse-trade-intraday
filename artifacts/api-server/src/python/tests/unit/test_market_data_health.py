from datetime import datetime, timezone

from market_data_health import build_market_data_health


NOW = datetime(2026, 8, 15, 10, 5, tzinfo=timezone.utc)


def _scan(rows, universe=("INFY", "TCS")):
    return {"snapshot_ts": "2026-08-15T10:00:00Z", "universe": list(universe),
            "recommendations": rows}


def test_authenticated_kite_coverage_is_trading_ready():
    rows = [
        {"symbol": s, "kite_ltp_available": True,
         "execution_price_source": "kite_live_ltp",
         "latest_price_time_ist": "2026-08-15T10:00:00Z"}
        for s in ("INFY", "TCS")
    ]
    result = build_market_data_health(
        _scan(rows), {"kite_connected": True, "session_fresh": True},
        [{"symbol": "INFY", "token": 1}, {"symbol": "TCS", "token": 2}], NOW)
    assert result["trading_data_ready"] is True
    assert result["token_coverage_pct"] == 100
    assert result["symbols_on_kite"] == 2
    assert result["latest_quote_age_s"] == 300


def test_fallback_and_missing_instrument_are_honest_and_not_trading_ready():
    rows = [
        {"symbol": "INFY", "data_source": "yfinance_fallback",
         "current_price_source": "yfinance_daily_bars",
         "execution_price_source": "yfinance_daily_bars"},
        {"symbol": "TCS", "data_quality": "UNAVAILABLE"},
    ]
    result = build_market_data_health(
        _scan(rows), {"kite_connected": True, "session_fresh": True},
        [{"symbol": "INFY", "token": 1}], NOW)
    assert result["symbols_fallback"] == 1
    assert result["symbols_unavailable"] == 1
    assert result["missing_token_count"] == 1
    assert result["missing_symbols"] == ["TCS"]
    assert result["latest_quote_timestamp"] is None
    assert result["trading_data_ready"] is False


def test_token_or_credentials_alone_do_not_claim_kite_connection():
    result = build_market_data_health(
        _scan([]), {"kite_connected": True, "session_fresh": False},
        [], NOW)
    assert result["kite_connected"] is False
    assert result["session_fresh"] is False
    assert result["service_ready"] is True
    assert result["data_ready"] is False


def test_all_kite_data_with_missing_instrument_tokens_fails_trading_ready():
    rows = [
        {"symbol": s, "kite_ltp_available": True,
         "execution_price_source": "kite_live_ltp",
         "latest_price_time_ist": "2026-08-15T10:00:00Z"}
        for s in ("INFY", "TCS")
    ]
    result = build_market_data_health(
        _scan(rows), {"kite_connected": True, "session_fresh": True},
        [{"symbol": "INFY", "token": 1}], NOW)
    assert result["data_ready"] is True
    assert result["missing_symbols"] == ["TCS"]
    assert result["trading_data_ready"] is False


def test_all_kite_data_with_stale_or_malformed_scan_timestamp_fails_closed():
    rows = [
        {"symbol": s, "kite_ltp_available": True,
         "execution_price_source": "kite_live_ltp",
         "latest_price_time_ist": "2026-08-15T10:00:00Z"}
        for s in ("INFY", "TCS")
    ]
    instruments = [{"symbol": "INFY", "token": 1}, {"symbol": "TCS", "token": 2}]
    for timestamp in ("2026-08-15T09:59:59Z", "not-a-timestamp"):
        scan = _scan(rows)
        scan["snapshot_ts"] = timestamp
        result = build_market_data_health(
            scan, {"kite_connected": True, "session_fresh": True}, instruments, NOW)
        assert result["data_ready"] is True
        assert result["market_timestamp_fresh"] is False
        assert result["trading_data_ready"] is False


def test_malformed_or_stale_live_quote_timestamp_fails_closed():
    instruments = [{"symbol": "INFY", "token": 1}, {"symbol": "TCS", "token": 2}]
    for bad_timestamp in ("not-a-timestamp", "2026-08-15T09:59:59Z"):
        rows = [
            {"symbol": "INFY", "kite_ltp_available": True,
             "execution_price_source": "kite_live_ltp",
             "latest_price_time_ist": "2026-08-15T10:00:00Z"},
            {"symbol": "TCS", "kite_ltp_available": True,
             "execution_price_source": "kite_live_ltp",
             "latest_price_time_ist": bad_timestamp},
        ]
        result = build_market_data_health(
            _scan(rows), {"kite_connected": True, "session_fresh": True},
            instruments, NOW)
        assert result["service_ready"] is True
        assert result["data_ready"] is True
        assert result["market_timestamp_fresh"] is True
        assert result["kite_quote_timestamps_fresh"] is False
        assert result["invalid_live_quote_timestamp_symbols"] == ["TCS"]
        assert result["trading_data_ready"] is False