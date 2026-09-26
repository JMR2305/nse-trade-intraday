"""TASK978ZR-R24 regressions for natural-session price and health authority."""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


CANONICAL = """BANKBARODA BANKINDIA CANBK FEDERALBNK IDFCFIRSTB KTKBANK
MAHABANK PNB UNIONBANK COALINDIA GAIL HUDCO IRCON IRFC MRPL NBCC NMDC NTPC
PFC RECLTD RVNL SAIL WIPRO""".split()
CANONICAL_HASH = "22e5751f25686718f5572041834ce998b7c5ce9844d3b573bc3841749fe77016"


def _quote(symbol="IRFC", *, ltp=101.0, opening=97.0,
           source="kite_live", quality="LIVE"):
    return {"symbol": symbol, "ltp": ltp, "open": opening,
            "data_source": source, "data_quality": quality}


def _evidence(opens=None, ltps=None, missing=None):
    opens, ltps, missing = opens or {}, ltps or {}, missing or []
    requested = len(ltps) + len(missing)
    return {"open_prices": opens, "ltp_prices": ltps,
            "requested_count": requested, "live_count": len(ltps),
            "missing_count": len(missing), "missing_symbols": missing,
            "provider": "kite_quote_provider", "provenance": "kite_live/LIVE",
            "status": "COMPLETE" if not missing else "INCOMPLETE"}


def test_0920_keeps_actual_open_and_ltp_distinct():
    from certified_quote_authority import certified_prices
    with patch("kite_quote_provider.get_quotes",
               return_value={"IRFC": _quote(ltp=101, opening=97)}):
        got = certified_prices(["IRFC"], require_open=True)
    assert got["open_prices"] == {"IRFC": 97.0}
    assert got["ltp_prices"] == {"IRFC": 101.0}


def test_legacy_price_key_is_not_required_for_ltp():
    from certified_quote_authority import certified_prices
    row = _quote()
    assert "price" not in row
    with patch("kite_quote_provider.get_quotes", return_value={"IRFC": row}):
        assert certified_prices(["IRFC"])["ltp_prices"] == {"IRFC": 101.0}


@pytest.mark.parametrize("source,quality", [
    ("yfinance_fallback", "NEAR_LIVE"), ("kite_live", "STALE"),
    ("synthetic", "LIVE"), ("kite_unavailable", "UNAVAILABLE"),
])
def test_non_live_or_wrong_provenance_is_rejected(source, quality):
    from certified_quote_authority import certified_prices
    with patch("kite_quote_provider.get_quotes",
               return_value={"IRFC": _quote(source=source, quality=quality)}):
        got = certified_prices(["IRFC"], require_open=True)
    assert got["status"] == "INCOMPLETE"
    assert got["ltp_prices"] == {}


@pytest.mark.parametrize("ltp,opening", [(0, 97), (-1, 97), ("bad", 97),
                                           (101, 0), (101, None)])
def test_zero_negative_or_non_numeric_required_values_are_rejected(ltp, opening):
    from certified_quote_authority import certified_prices
    with patch("kite_quote_provider.get_quotes",
               return_value={"IRFC": _quote(ltp=ltp, opening=opening)}):
        assert certified_prices(["IRFC"], require_open=True)["status"] == "INCOMPLETE"


def test_missing_or_substituted_exact_symbol_stays_missing():
    from certified_quote_authority import certified_prices
    with patch("kite_quote_provider.get_quotes",
               return_value={"IRFC": _quote(symbol="WIPRO")}):
        got = certified_prices(["IRFC"])
    assert got["missing_symbols"] == ["IRFC"]
    assert got["ltp_prices"] == {}


def test_custom_symbol_bypasses_legacy_nifty_whitelist_without_substitution():
    import live_quote_service
    from certified_quote_authority import certified_prices
    assert live_quote_service.is_allowed_symbol("IRFC") is False
    with patch("kite_quote_provider.get_quotes",
               return_value={"IRFC": _quote()}):
        got = certified_prices(["IRFC"])
    assert got["status"] == "COMPLETE"
    assert list(got["ltp_prices"]) == ["IRFC"]


def test_full_23_live_coverage_is_complete_and_partial_is_incomplete():
    from certified_quote_authority import certified_prices
    with patch("kite_quote_provider.get_quotes",
               return_value={s: _quote(s) for s in CANONICAL}):
        complete = certified_prices(CANONICAL)
    assert complete["requested_count"] == complete["live_count"] == 23
    assert complete["status"] == "COMPLETE"
    with patch("kite_quote_provider.get_quotes",
               return_value={s: _quote(s) for s in CANONICAL[:-1]}):
        partial = certified_prices(CANONICAL)
    assert partial["live_count"] == 22
    assert partial["missing_symbols"] == ["WIPRO"]
    assert partial["status"] == "INCOMPLETE"


def test_phase5a_0920_passes_open_and_ltp_to_independent_fields():
    import preopen_scheduler
    captured = {}
    database = SimpleNamespace(
        get_session=lambda _: {"status": "FROZEN", "frozen_collection_batch_id": "b"},
        get_session_snapshots=lambda *_: [{"symbol": "IRFC"}],
        get_session_watchlists=lambda _: {}, upsert_session=MagicMock(return_value=True),
        record_collection_failure=MagicMock())
    reconciliation = SimpleNamespace(
        reconcile_session=lambda *args, **kwargs: captured.update(kwargs) or {"ok": True})
    scheduler = preopen_scheduler.PreOpenScheduler(session_id="s", test_mode=True)
    evidence = _evidence({"IRFC": 97.0}, {"IRFC": 101.0})
    with (patch.dict("sys.modules", {"preopen_db": database,
                                      "preopen_reconciliation": reconciliation}),
          patch("certified_quote_authority.certified_prices", return_value=evidence)):
        assert scheduler._phase_09_20_reconcile() is True
    assert captured["actual_prices"] == {"IRFC": 97.0}
    assert captured["prices_0920"] == {"IRFC": 101.0}


def test_phase5a_0930_uses_ltp_and_retains_incomplete_evidence():
    import preopen_scheduler
    database = SimpleNamespace(
        get_session=lambda _: {"status": "RECONCILED", "frozen_collection_batch_id": "b"},
        get_session_snapshots=lambda *_: [{"symbol": "IRFC"}, {"symbol": "WIPRO"}],
        update_reconciliation_0930=MagicMock(), upsert_session=MagicMock(return_value=True),
        record_collection_failure=MagicMock())
    scheduler = preopen_scheduler.PreOpenScheduler(session_id="s", test_mode=True)
    evidence = _evidence(ltps={"IRFC": 101.0}, missing=["WIPRO"])
    with (patch.dict("sys.modules", {"preopen_db": database}),
          patch("certified_quote_authority.certified_prices", return_value=evidence)):
        assert scheduler._phase_09_30_post_open_reconcile() is True
    database.update_reconciliation_0930.assert_called_once_with("s", {"IRFC": 101.0})
    assert scheduler._log[-1]["quote_evidence"]["status"] == "INCOMPLETE"


def test_phase5b_actual_open_uses_open_and_later_checkpoint_uses_ltp():
    import preopen_validation_scheduler as validation
    record = SimpleNamespace(symbol="IRFC", actual_open=None, price_at_0920=None,
                             update_returns=lambda: None,
                             to_dict=lambda: {"symbol": "IRFC"})
    database = SimpleNamespace(upsert_candidate_outcome=MagicMock())
    scheduler = validation.PreOpenValidationScheduler(test_mode=True)
    evidence = _evidence({"IRFC": 97.0}, {"IRFC": 101.0})
    with (patch("preopen_validation_scheduler._fetch_prices", return_value=evidence),
          patch.dict("sys.modules", {"preopen_validation_db": database})):
        scheduler._record_price_checkpoint([record], "actual_open")
        scheduler._record_price_checkpoint([record], "price_at_0920")
    assert record.actual_open == 97.0
    assert record.price_at_0920 == 101.0
    assert scheduler._log[-1]["provider"] == "kite_quote_provider"


def test_phase5b_incomplete_checkpoint_exposes_exact_accounting():
    import preopen_validation_scheduler as validation
    records = [SimpleNamespace(symbol=s, price_at_0930=None,
                               update_returns=lambda: None, to_dict=lambda: {})
               for s in ("IRFC", "WIPRO")]
    scheduler = validation.PreOpenValidationScheduler(test_mode=True)
    evidence = _evidence(ltps={"IRFC": 101.0}, missing=["WIPRO"])
    database = SimpleNamespace(upsert_candidate_outcome=MagicMock())
    with (patch("preopen_validation_scheduler._fetch_prices", return_value=evidence),
          patch.dict("sys.modules", {"preopen_validation_db": database})):
        scheduler._record_price_checkpoint(records, "price_at_0930")
    log = scheduler._log[-1]
    assert (log["requested_count"], log["live_count"], log["missing_count"]) == (2, 1, 1)
    assert log["missing_symbols"] == ["WIPRO"]
    assert log["status"] == "INCOMPLETE"


def test_health_auto_entry_requires_window_and_durable_enablement():
    import market_hours
    open_time = datetime(2026, 1, 2, 10, 0, tzinfo=market_hours.IST)
    with patch("phase20_store.get_settings", return_value={"auto_paper_entries": False}):
        disabled = market_hours.market_status(open_time)
    assert disabled["market_window_allows_paper_entry"] is True
    assert disabled["automatic_paper_entry_enabled"] is False
    assert disabled["automatic_paper_entry_allowed"] is False
    with patch("phase20_store.get_settings", return_value={"auto_paper_entries": True}):
        enabled = market_hours.market_status(open_time)
    assert enabled["automatic_paper_entry_allowed"] is True


def test_health_auto_entry_fails_closed_when_settings_unreadable():
    import market_hours
    open_time = datetime(2026, 1, 2, 10, 0, tzinfo=market_hours.IST)
    with patch("phase20_store.get_settings", side_effect=RuntimeError("unavailable")):
        got = market_hours.market_status(open_time)
    assert got["automatic_paper_entry_allowed"] is False
    assert "unavailable" in got["automatic_paper_entry_reason"].lower()


def _pin():
    import universe_version_store as versions
    return {"natural_session": "2026-09-23", "universe_key": "CUSTOM_LOW_PRICE_SECTOR",
            "universe_id": 3, "version": 1, "enabled_symbols": CANONICAL,
            "symbol_count": 23, "exact_set_hash": versions.exact_set_hash(CANONICAL),
            "effective_from": "2026-09-23T03:30:00+00:00",
            "pinned_at": "2026-09-23T03:31:00+00:00"}


def test_passive_existing_pin_read_has_no_schema_or_insert_mutation():
    import runtime_universe as runtime
    import universe_version_store as versions
    conn = MagicMock()
    @contextmanager
    def connection():
        yield conn
    with (patch.object(versions, "_db_available", return_value=True),
          patch.object(versions, "_connect", connection),
          patch.object(runtime, "_load_pin", return_value=_pin()),
          patch.object(versions, "_ensure_schema",
                       side_effect=AssertionError("passive health must not mutate"))):
        got = runtime.get_pinned_universe_for_session(
            datetime(2026, 9, 23, 10, 0, tzinfo=runtime._IST))
    assert got["universe_id"] == 3 and got["symbol_count"] == 23
    statements = " ".join(str(c) for c in conn.cursor.return_value.execute.call_args_list)
    assert "INSERT" not in statements.upper() and "CREATE" not in statements.upper()


def test_passive_missing_pin_returns_none_without_substitution_or_creation():
    import runtime_universe as runtime
    import universe_version_store as versions
    @contextmanager
    def connection():
        yield MagicMock()
    with (patch.object(versions, "_db_available", return_value=True),
          patch.object(versions, "_connect", connection),
          patch.object(runtime, "_load_pin", return_value=None),
          patch.object(runtime, "resolve_active_universe") as resolver):
        assert runtime.get_pinned_universe_for_session() is None
    resolver.assert_not_called()


def test_invalid_pin_fails_closed():
    import runtime_universe as runtime
    import universe_version_store as versions
    bad = _pin() | {"symbol_count": 22}
    @contextmanager
    def connection():
        yield MagicMock()
    with (patch.object(versions, "_db_available", return_value=True),
          patch.object(versions, "_connect", connection),
          patch.object(runtime, "_load_pin", return_value=bad)):
        with pytest.raises(runtime.RuntimeUniverseUnavailable):
            runtime.get_pinned_universe_for_session()


def test_health_contract_reports_exact_canonical_pin_identity():
    from market_data_health import build_market_data_health
    import universe_version_store as versions
    assert versions.exact_set_hash(CANONICAL) == CANONICAL_HASH
    authority = {"universe_id": 3, "version": 1, "exact_set_hash": CANONICAL_HASH}
    got = build_market_data_health(None, None, [], current_universe=CANONICAL,
                                   active_universe="CUSTOM_LOW_PRICE_SECTOR",
                                   universe_authority=authority)
    assert got["active_universe_count"] == 23
    assert (got["universe_id"], got["universe_version"]) == (3, 1)
    assert got["universe_set_hash"] == CANONICAL_HASH
    assert got["universe_pin_present"] is True
