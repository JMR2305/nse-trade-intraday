"""Focused safety tests for the guarded ₹100,000 paper-capital migration."""

from __future__ import annotations

import copy
import importlib.util
import json
import sys
import threading
import time
import types
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import paper_capital_migration as migration

_PHASE20_SPEC = importlib.util.spec_from_file_location(
    "phase20_store_capital_guard_test",
    Path(__file__).with_name("phase20_store.py"),
)
assert _PHASE20_SPEC and _PHASE20_SPEC.loader
phase20_store_real = importlib.util.module_from_spec(_PHASE20_SPEC)
_PHASE20_SPEC.loader.exec_module(phase20_store_real)


def _load_real_executor():
    spec = importlib.util.spec_from_file_location(
        "phase20_executor_capital_guard_test",
        Path(__file__).with_name("phase20_executor.py"),
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, {"phase20_store": phase20_store_real}):
        spec.loader.exec_module(module)
    return module


def _settings(capital: float = 50_000.0, auto_entries: bool = True):
    return {
        "initial_capital": capital,
        "auto_paper_entries": auto_entries,
        "auto_paper_entries_confirmed_at": "2026-08-19T03:00:00Z",
        "per_stock_exposure_cap_pct": 25.0,
        "sector_exposure_cap_pct": 40.0,
        "portfolio_deployed_cap_pct": 80.0,
        "risk_per_trade_pct": 1.0,
        "daily_loss_limit_pct": 3.0,
    }


def _active(status: str):
    return [{
        "trade_id": f"P20-{status.lower()}",
        "symbol": "GRASIM",
        "status": status,
        "quantity": 3,
        "fill_price": 2765.0,
        "fill_ts": "2026-08-19T03:48:05Z",
        "trigger_source": "BOOTSTRAP_AUTO",
    }]


def _run_with_state(settings, active, closed=None, confirmation=None):
    conn = MagicMock()
    closed = closed or {"closed_trade_count": 1, "realized_pnl": 0.0}
    with patch.object(migration, "db_available", return_value=True), \
         patch.object(migration, "_connect", return_value=conn), \
         patch.object(migration, "_prepare_tables"), \
         patch.object(
             migration, "_load_locked_state",
             return_value=(settings, active, closed),
         ), \
         patch.object(migration, "_persist_settings_locked") as persist_settings, \
         patch.object(migration, "_persist_status_locked") as persist_status, \
         patch.object(
             migration,
             "_sync_legacy_portfolio_locked",
             return_value={
                 "legacy_cash_before": 50_000.0,
                 "cash_after_rebase": 100_000.0 + float(closed["realized_pnl"]),
                 "deployed_capital_after": 0.0,
                 "legacy_positions_cleared": True,
                 "legacy_pnl_history_preserved": True,
             },
         ) as sync_legacy, \
         patch.object(
             migration,
             "_sync_phase11_capital_locked",
             return_value={
                 "previous_phase11_starting_capital": 50_000.0,
                 "previous_phase11_topup_target": 50_000.0,
                 "phase11_starting_capital": 100_000.0,
                 "phase11_topup_target": 100_000.0,
             },
         ) as sync_phase11, \
         patch.object(migration, "_notify_once") as notify, \
         patch.object(migration, "_emit_rebased") as emit:
        result = migration.migrate_paper_capital_to_100000(
            confirmation_text=confirmation,
            reviewed_by="test-operator",
        )
    return {
        "result": result,
        "conn": conn,
        "persist_settings": persist_settings,
        "persist_status": persist_status,
        "sync_legacy": sync_legacy,
        "sync_phase11": sync_phase11,
        "notify": notify,
        "emit": emit,
    }


def test_open_position_blocks_rebase_and_pauses_entries():
    settings = _settings()
    run = _run_with_state(
        settings,
        _active("OPEN"),
        confirmation=migration.CONFIRMATION_TEXT,
    )

    result = run["result"]
    assert result["status"] == "BLOCKED_OPEN_POSITIONS"
    assert result["success"] is False
    assert result["current_capital"] == 50_000.0
    assert result["open_count"] == 1
    assert settings["initial_capital"] == 50_000.0
    assert settings["auto_paper_entries"] is False
    assert settings["auto_paper_entries_confirmed_at"] is None
    run["persist_settings"].assert_called_once()
    run["sync_legacy"].assert_not_called()
    run["sync_phase11"].assert_not_called()
    run["emit"].assert_not_called()
    run["conn"].commit.assert_called_once()


def test_exit_pending_position_blocks_rebase():
    settings = _settings()
    run = _run_with_state(
        settings,
        _active("EXIT_PENDING"),
        confirmation=migration.CONFIRMATION_TEXT,
    )

    result = run["result"]
    assert result["status"] == "BLOCKED_OPEN_POSITIONS"
    assert result["exit_pending_count"] == 1
    assert result["open_count"] == 0
    assert settings["initial_capital"] == 50_000.0
    run["sync_legacy"].assert_not_called()
    run["sync_phase11"].assert_not_called()
    run["emit"].assert_not_called()


def test_target_capital_still_blocks_when_active_position_exists():
    settings = _settings(capital=100_000.0, auto_entries=True)
    run = _run_with_state(
        settings,
        _active("OPEN"),
        confirmation=migration.CONFIRMATION_TEXT,
    )

    assert run["result"]["status"] == "BLOCKED_OPEN_POSITIONS"
    assert run["result"]["success"] is False
    assert settings["auto_paper_entries"] is False
    run["sync_legacy"].assert_not_called()
    run["sync_phase11"].assert_not_called()


def test_unreadable_ledger_fails_closed_without_rebase():
    conn = MagicMock()
    with patch.object(migration, "db_available", return_value=True), \
         patch.object(migration, "_connect", return_value=conn), \
         patch.object(migration, "_prepare_tables"), \
         patch.object(
             migration, "_load_locked_state",
             side_effect=RuntimeError("ledger query failed"),
         ), \
         patch.object(
             migration, "_pause_entries_best_effort", return_value=True,
         ) as pause, \
         patch.object(migration, "_notify_once"):
        result = migration.migrate_paper_capital_to_100000(
            confirmation_text=migration.CONFIRMATION_TEXT,
        )

    assert result["status"] == "BLOCKED_STATE_UNREADABLE"
    assert result["success"] is False
    assert result["auto_paper_entries_paused"] is True
    assert "ledger query failed" in result["error"]
    pause.assert_called_once()
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()


def test_no_positions_requires_exact_confirmation_before_rebase():
    settings = _settings()
    run = _run_with_state(settings, [], confirmation="not the exact sentence")

    result = run["result"]
    assert result["status"] == "CONFIRMATION_REQUIRED"
    assert result["success"] is False
    assert settings["initial_capital"] == 50_000.0
    assert settings["auto_paper_entries"] is False
    run["sync_legacy"].assert_not_called()
    run["sync_phase11"].assert_not_called()
    run["emit"].assert_not_called()


def test_no_positions_applies_rebase_and_preserves_closed_history():
    settings = _settings()
    closed_trade = {
        "trade_id": "P20-DRREDDY-CLOSED",
        "symbol": "DRREDDY",
        "status": "CLOSED",
        "fill_price": 1234.5,
        "exit_price": 1234.5,
        "realized_pnl": 0.0,
    }
    before = copy.deepcopy(closed_trade)
    run = _run_with_state(
        settings,
        [],
        closed={"closed_trade_count": 1, "realized_pnl": 0.0},
        confirmation=migration.CONFIRMATION_TEXT,
    )

    result = run["result"]
    assert result["status"] == "APPLIED"
    assert result["success"] is True
    assert result["previous_capital"] == 50_000.0
    assert result["current_capital"] == 100_000.0
    assert result["cash_after_rebase"] == 100_000.0
    assert result["deployed_capital_after"] == 0.0
    assert result["phase11_starting_capital"] == 100_000.0
    assert result["phase11_topup_target"] == 100_000.0
    assert result["closed_history"] == {
        "closed_trade_count": 1,
        "realized_pnl": 0.0,
        "preserved": True,
    }
    assert result["derived_limits"] == {
        "initial_capital": 100_000.0,
        "per_stock_exposure_cap": 25_000.0,
        "sector_exposure_cap": 40_000.0,
        "portfolio_deployed_cap": 80_000.0,
        "risk_per_trade": 1_000.0,
        "daily_loss_limit": 3_000.0,
        "circuit_breaker_daily_loss_limit": 3_000.0,
        "bootstrap_max_order_value": 15_000.0,
    }
    assert closed_trade == before
    run["persist_settings"].assert_called_once()
    run["sync_legacy"].assert_called_once_with(
        run["conn"],
        realized_pnl=0.0,
    )
    run["sync_phase11"].assert_called_once_with(run["conn"])
    run["emit"].assert_called_once()


def test_migration_is_idempotent_at_target_capital():
    settings = _settings(capital=100_000.0, auto_entries=False)
    run = _run_with_state(settings, [], confirmation=None)

    result = run["result"]
    assert result["status"] == "ALREADY_APPLIED"
    assert result["success"] is True
    run["persist_settings"].assert_not_called()
    run["sync_legacy"].assert_called_once()
    run["sync_phase11"].assert_called_once()
    run["emit"].assert_not_called()


def test_migration_never_calls_broker_order_api():
    fake_broker = types.ModuleType("broker_client")
    fake_broker.get_broker_client = MagicMock()
    settings = _settings()
    with patch.dict(sys.modules, {"broker_client": fake_broker}):
        run = _run_with_state(
            settings,
            [],
            confirmation=migration.CONFIRMATION_TEXT,
        )

    assert run["result"]["broker_orders_called"] is False
    fake_broker.get_broker_client.assert_not_called()


def test_phase11_capital_keys_are_synchronised_transactionally():
    conn = MagicMock()
    cur = MagicMock()
    cur.fetchall.return_value = [
        ("phase11_starting_capital", 50_000.0),
        ("phase11_topup_target", 50_000.0),
    ]
    conn.cursor.return_value.__enter__.return_value = cur

    result = migration._sync_phase11_capital_locked(conn)

    assert result == {
        "previous_phase11_starting_capital": 50_000.0,
        "previous_phase11_topup_target": 50_000.0,
        "phase11_starting_capital": 100_000.0,
        "phase11_topup_target": 100_000.0,
    }
    assert cur.execute.call_count == 3
    for call in cur.execute.call_args_list[1:]:
        assert call.args[1][1] == "100000.0"


def test_prepare_tables_creates_phase20_kv_for_fresh_database():
    conn = MagicMock()
    cur = MagicMock()
    conn.cursor.return_value.__enter__.return_value = cur
    with patch.dict(
        sys.modules,
        {
            "phase20_executor": types.SimpleNamespace(_ensure_schema=MagicMock()),
            "phase20_store": types.SimpleNamespace(_ensure_schema=MagicMock()),
            "portfolio_store": types.SimpleNamespace(_ensure_schema=MagicMock()),
        },
    ):
        migration._prepare_tables(conn)

    sql = "\n".join(str(call.args[0]) for call in cur.execute.call_args_list)
    assert "CREATE TABLE IF NOT EXISTS phase20_kv" in sql


def test_inflight_entry_cannot_insert_after_migration_pauses_entries():
    """Two DB sessions prove a pre-approved entry rechecks after migration."""
    from scan_state_store import _connect as real_connect, db_available

    executor = _load_real_executor()
    store = phase20_store_real
    if not db_available():
        pytest.skip("PostgreSQL is unavailable")

    schema = f"capital_migration_race_{uuid.uuid4().hex}"
    original_executor_ready = executor._SCHEMA_READY
    original_store_ready = store._SCHEMA_READY
    migration_conn = None

    def scoped_connect():
        conn = real_connect()
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}")
        conn.commit()
        return conn

    try:
        setup_conn = real_connect()
        try:
            with setup_conn.cursor() as cur:
                cur.execute(f"CREATE SCHEMA {schema}")
                cur.execute(f"SET search_path TO {schema}")
            setup_conn.commit()
            executor._SCHEMA_READY = False
            store._SCHEMA_READY = False
            executor._ensure_schema(setup_conn)
            store._ensure_schema(setup_conn)
            with setup_conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO phase20_settings (id, data, updated_at)
                    VALUES (1, %s::jsonb, NOW())
                    ON CONFLICT (id) DO UPDATE
                    SET data = EXCLUDED.data, updated_at = NOW()
                    """,
                    (json.dumps({
                        **store.DEFAULT_SETTINGS,
                        "auto_paper_entries": True,
                        "auto_paper_entries_confirmed_at": "2026-08-19T03:00:00Z",
                    }),),
                )
            setup_conn.commit()
        finally:
            setup_conn.close()

        migration_conn = scoped_connect()
        migration._acquire_entry_admission_lock(migration_conn)

        row = {column: None for column in executor._COLS}
        row.update({
            "trade_id": f"RACE-{uuid.uuid4().hex}",
            "symbol": "GRASIM",
            "side": "BUY",
            "status": "OPEN",
            "quantity": 1,
            "fill_price": 100.0,
            "evidence": {},
            "recomputed": False,
        })
        started = threading.Event()
        outcome = {}

        def attempt_insert():
            started.set()
            try:
                executor._insert_row(row)
                outcome["inserted"] = True
            except Exception as exc:
                outcome["error"] = exc

        with patch.object(executor, "db_available", return_value=True), \
             patch.object(executor, "_connect", side_effect=scoped_connect):
            worker = threading.Thread(target=attempt_insert, daemon=True)
            worker.start()
            assert started.wait(timeout=2)
            time.sleep(0.2)
            assert worker.is_alive(), "entry must wait behind migration lock"

            with migration_conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE phase20_settings
                    SET data = jsonb_set(
                        jsonb_set(data, '{auto_paper_entries}', 'false'::jsonb),
                        '{auto_paper_entries_confirmed_at}', 'null'::jsonb
                    ),
                    updated_at = NOW()
                    WHERE id = 1
                    """
                )
            migration_conn.commit()
            migration._release_entry_admission_lock(migration_conn)

            worker.join(timeout=5)
            assert not worker.is_alive()

        assert isinstance(outcome.get("error"), executor.PaperEntriesPaused)
        assert outcome.get("inserted") is not True
        verify_conn = scoped_connect()
        try:
            with verify_conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) FROM phase20_paper_trades WHERE status = 'OPEN'"
                )
                assert cur.fetchone()[0] == 0
        finally:
            verify_conn.close()
    finally:
        if migration_conn is not None:
            try:
                with migration_conn.cursor() as cur:
                    cur.execute("SELECT pg_advisory_unlock_all()")
            except Exception:
                pass
            migration_conn.close()
        cleanup_conn = real_connect()
        try:
            with cleanup_conn.cursor() as cur:
                cur.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
            cleanup_conn.commit()
        finally:
            cleanup_conn.close()
        executor._SCHEMA_READY = original_executor_ready
        store._SCHEMA_READY = original_store_ready


def test_locked_entry_admission_revalidates_latest_sector_capacity():
    """A later entry sees earlier committed exposure under the shared lock."""
    from scan_state_store import _connect as real_connect, db_available

    executor = _load_real_executor()
    store = phase20_store_real
    if not db_available():
        pytest.skip("PostgreSQL is unavailable")

    schema = f"allocation_admission_{uuid.uuid4().hex}"
    original_executor_ready = executor._SCHEMA_READY
    original_store_ready = store._SCHEMA_READY

    def scoped_connect():
        conn = real_connect()
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}")
        conn.commit()
        return conn

    try:
        setup_conn = real_connect()
        try:
            with setup_conn.cursor() as cur:
                cur.execute(f"CREATE SCHEMA {schema}")
                cur.execute(f"SET search_path TO {schema}")
            setup_conn.commit()
            executor._SCHEMA_READY = False
            store._SCHEMA_READY = False
            executor._ensure_schema(setup_conn)
            store._ensure_schema(setup_conn)
            settings = {
                **store.DEFAULT_SETTINGS,
                "initial_capital": 100_000.0,
                "auto_paper_entries": True,
                "auto_paper_entries_confirmed_at":
                    "2026-08-19T03:00:00Z",
            }
            with setup_conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO phase20_settings (id, data, updated_at)
                    VALUES (1, %s::jsonb, NOW())
                    ON CONFLICT (id) DO UPDATE
                    SET data = EXCLUDED.data, updated_at = NOW()
                    """,
                    (json.dumps(settings),),
                )
                existing = {column: None for column in executor._COLS}
                existing.update({
                    "trade_id": "EXISTING-IT",
                    "symbol": "INFY",
                    "sector": "IT",
                    "side": "BUY",
                    "status": "OPEN",
                    "quantity": 390,
                    "fill_price": 100.0,
                    "stop_loss": 98.0,
                    "risk_amount": 780.0,
                    "evidence": {},
                    "recomputed": False,
                })
                placeholders = ", ".join(
                    ["%s"] * len(executor._COLS)
                )
                cur.execute(
                    f"INSERT INTO phase20_paper_trades "
                    f"({', '.join(executor._COLS)}) "
                    f"VALUES ({placeholders})",
                    [
                        json.dumps(existing.get(column))
                        if column == "evidence"
                        else existing.get(column)
                        for column in executor._COLS
                    ],
                )
            setup_conn.commit()
        finally:
            setup_conn.close()

        row = {column: None for column in executor._COLS}
        row.update({
            "trade_id": "NEW-TCS",
            "scan_id": "scan-locked",
            "symbol": "TCS",
            "sector": "IT",
            "side": "BUY",
            "status": "OPEN",
            "quantity": 30,
            "fill_price": 100.0,
            "stop_loss": 98.0,
            "risk_amount": 60.0,
            "evidence": {
                "sizing": {
                    "quantity": 30,
                    "stop_loss": 98.0,
                    "risk_amount": 60.0,
                },
                "quality_allocation_override": {
                    "policy": "QUALITY_ALLOCATION_OVERRIDE",
                    "paper_only": True,
                    "live_broker_orders_called": False,
                    "override_approved": True,
                    "tier": "EXCEPTIONAL_QUALITY_3X",
                    "base_quantity": 10,
                    "final_quantity": 30,
                    "effective_multiplier": 3.0,
                    "three_x_quality_valid": True,
                    "limiting_caps": [],
                },
            },
            "recomputed": False,
        })

        with patch.object(executor, "db_available", return_value=True), \
             patch.object(executor, "_connect", side_effect=scoped_connect):
            admitted = executor._insert_row(row)

        assert admitted["quantity"] == 10
        decision = admitted["evidence"]["quality_allocation_override"]
        assert decision["effective_multiplier"] == 1.0
        assert decision["exposure_after"]["sector_pct"] == 40.0
        assert "sector" in decision["limiting_caps"]
        assert admitted["evidence"][
            "locked_allocation_admission"
        ]["reason"] == "LOCKED_QUANTITY_REDUCED"

        verify_conn = scoped_connect()
        try:
            with verify_conn.cursor() as cur:
                cur.execute(
                    "SELECT quantity, evidence "
                    "FROM phase20_paper_trades WHERE trade_id = 'NEW-TCS'"
                )
                quantity, evidence = cur.fetchone()
            assert quantity == 10
            assert evidence["locked_allocation_admission"][
                "authoritative_state"
            ]["existing_sector_exposure"] == 39_000.0
        finally:
            verify_conn.close()
    finally:
        cleanup_conn = real_connect()
        try:
            with cleanup_conn.cursor() as cur:
                cur.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
            cleanup_conn.commit()
        finally:
            cleanup_conn.close()
        executor._SCHEMA_READY = original_executor_ready
        store._SCHEMA_READY = original_store_ready


def test_open_entry_never_falls_back_to_json_without_postgres():
    executor = _load_real_executor()

    row = {column: None for column in executor._COLS}
    row.update({
        "trade_id": "NO-DB-ENTRY",
        "symbol": "GRASIM",
        "status": "OPEN",
        "evidence": {},
    })
    with patch.object(executor, "db_available", return_value=False), \
         patch.object(executor, "_read_ledger_file") as read_file, \
         pytest.raises(executor.PaperEntryAdmissionError, match="fail-closed"):
        executor._insert_row(row)

    read_file.assert_not_called()


def test_generic_settings_update_cannot_bypass_capital_guard():
    settings = {
        "initial_capital": 50_000.0,
        "auto_paper_entries": False,
    }
    with patch.object(phase20_store_real, "get_settings", return_value=settings), \
         patch.object(phase20_store_real, "_persist_settings") as persist:
        try:
            phase20_store_real.update_settings({"initial_capital": 100_000.0})
        except ValueError as exc:
            assert "guarded" in str(exc)
        else:
            raise AssertionError("unguarded initial_capital update was accepted")
    persist.assert_not_called()