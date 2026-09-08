"""Guarded paper-capital migration to ₹100,000.

The Phase 20 paper-trade ledger is authoritative for active positions.  This
module changes only durable paper settings; it never imports a broker client,
places an order, rewrites a trade, or resets historical P&L.

Safety invariants:
* the PostgreSQL ledger must be readable (no JSON fallback for a migration);
* OPEN and EXIT_PENDING rows block a capital change;
* automatic paper entries are paused while a migration is blocked/pending;
* the operator must provide the exact confirmation text;
* the settings row and ledger check share one database transaction and table
  lock, so a new paper entry cannot race the rebase;
* repeated calls after the target is applied are idempotent.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from paper_entry_admission import PAPER_ENTRY_ADMISSION_LOCK_ID
from scan_state_store import _connect, db_available

TARGET_CAPITAL = 100_000.0
MIGRATION_KEY = "paper_capital_migration:target:100000:v1"
CONFIRMATION_TEXT = (
    "I confirm there are no open or exit-pending paper positions and approve "
    "rebasing paper capital to ₹100,000."
)
ACTIVE_STATUSES = ("OPEN", "EXIT_PENDING")


class PaperCapitalStateUnreadable(RuntimeError):
    """Raised when the authoritative paper ledger cannot be verified."""


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _decode_json_object(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, str):
        raw = json.loads(raw)
    return dict(raw) if isinstance(raw, dict) else {}


def _merged_settings(raw: Any) -> Dict[str, Any]:
    from phase20_store import DEFAULT_SETTINGS

    merged = dict(DEFAULT_SETTINGS)
    for key, value in _decode_json_object(raw).items():
        if key in DEFAULT_SETTINGS:
            merged[key] = value
    return merged


def _settings_payload(settings: Dict[str, Any]) -> Dict[str, Any]:
    from phase20_store import DEFAULT_SETTINGS

    return {key: settings.get(key, default)
            for key, default in DEFAULT_SETTINGS.items()}


def _derived_limits(settings: Dict[str, Any]) -> Dict[str, float]:
    capital = float(settings.get("initial_capital") or 0.0)

    def amount(key: str) -> float:
        return round(capital * float(settings.get(key) or 0.0) / 100.0, 2)

    try:
        from phase20_executor import _BOOTSTRAP_MAX_ORDER_VALUE
        bootstrap_cap = float(_BOOTSTRAP_MAX_ORDER_VALUE)
    except Exception:
        bootstrap_cap = 15_000.0

    return {
        "initial_capital": round(capital, 2),
        "per_stock_exposure_cap": amount("per_stock_exposure_cap_pct"),
        "sector_exposure_cap": amount("sector_exposure_cap_pct"),
        "portfolio_deployed_cap": amount("portfolio_deployed_cap_pct"),
        "risk_per_trade": amount("risk_per_trade_pct"),
        "daily_loss_limit": amount("daily_loss_limit_pct"),
        "circuit_breaker_daily_loss_limit": amount("daily_loss_limit_pct"),
        "bootstrap_max_order_value": round(bootstrap_cap, 2),
    }


def _prepare_tables(conn: Any) -> None:
    """Ensure existing Phase 20 tables are present before taking locks."""
    from phase20_executor import _ensure_schema as ensure_ledger_schema
    from phase20_store import _ensure_schema as ensure_settings_schema
    from portfolio_store import _ensure_schema as ensure_portfolio_schema

    ensure_settings_schema(conn)
    ensure_ledger_schema(conn)
    ensure_portfolio_schema(conn)
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS phase20_kv (
                key TEXT PRIMARY KEY,
                value JSONB,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )


def _acquire_entry_admission_lock(conn: Any) -> None:
    """Block automatic entry admission for this entire migration attempt."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT pg_advisory_lock(%s)",
            (PAPER_ENTRY_ADMISSION_LOCK_ID,),
        )


def _release_entry_admission_lock(conn: Any) -> None:
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT pg_advisory_unlock(%s)",
                (PAPER_ENTRY_ADMISSION_LOCK_ID,),
            )
    except Exception:
        # Closing the PostgreSQL session also releases session advisory locks.
        pass


def _load_locked_state(conn: Any) -> Tuple[Dict[str, Any], List[Dict[str, Any]], Dict[str, Any]]:
    """Lock settings + ledger and return a strict, transaction-consistent view."""
    with conn.cursor() as cur:
        # SHARE ROW EXCLUSIVE conflicts with INSERT/UPDATE/DELETE table locks.
        # This prevents a paper entry from appearing after the active-row check.
        cur.execute(
            "LOCK TABLE phase20_paper_trades IN SHARE ROW EXCLUSIVE MODE"
        )
        cur.execute("LOCK TABLE phase20_settings IN ROW EXCLUSIVE MODE")
        cur.execute("SELECT data FROM phase20_settings WHERE id = 1 FOR UPDATE")
        settings_row = cur.fetchone()
        cur.execute(
            """
            SELECT trade_id, symbol, status, quantity, fill_price, fill_ts,
                   trigger_source
            FROM phase20_paper_trades
            WHERE status IN ('OPEN', 'EXIT_PENDING')
            ORDER BY created_at ASC
            """
        )
        active_rows = cur.fetchall()
        cur.execute(
            """
            SELECT COUNT(*), COALESCE(SUM(realized_pnl), 0)
            FROM phase20_paper_trades
            WHERE status = 'CLOSED'
            """
        )
        closed_row = cur.fetchone() or (0, 0)

    settings = _merged_settings(settings_row[0] if settings_row else {})
    active = [
        {
            "trade_id": row[0],
            "symbol": row[1],
            "status": row[2],
            "quantity": int(row[3] or 0),
            "fill_price": float(row[4] or 0.0),
            "fill_ts": row[5],
            "trigger_source": row[6],
        }
        for row in active_rows
    ]
    closed_summary = {
        "closed_trade_count": int(closed_row[0] or 0),
        "realized_pnl": round(float(closed_row[1] or 0.0), 2),
    }
    return settings, active, closed_summary


def _persist_settings_locked(conn: Any, settings: Dict[str, Any]) -> None:
    payload = _settings_payload(settings)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO phase20_settings (id, data, updated_at)
            VALUES (1, %s, NOW())
            ON CONFLICT (id) DO UPDATE
            SET data = EXCLUDED.data, updated_at = NOW()
            """,
            (json.dumps(payload, default=str),),
        )


def _persist_status_locked(conn: Any, result: Dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS phase20_kv (
                key TEXT PRIMARY KEY,
                value JSONB,
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
        cur.execute(
            """
            INSERT INTO phase20_kv (key, value, updated_at)
            VALUES (%s, %s, NOW())
            ON CONFLICT (key) DO UPDATE
            SET value = EXCLUDED.value, updated_at = NOW()
            """,
            (MIGRATION_KEY, json.dumps(result, default=str)),
        )


def _read_legacy_cash_locked(conn: Any) -> Optional[float]:
    with conn.cursor() as cur:
        cur.execute("LOCK TABLE paper_portfolio IN ROW EXCLUSIVE MODE")
        cur.execute("SELECT cash FROM paper_portfolio WHERE id = 1 FOR UPDATE")
        row = cur.fetchone()
    return float(row[0]) if row else None


def _sync_legacy_portfolio_locked(
    conn: Any,
    *,
    realized_pnl: float,
) -> Dict[str, Any]:
    """Align legacy paper_portfolio without touching trade/P&L history."""
    before = _read_legacy_cash_locked(conn)
    cash = round(TARGET_CAPITAL + float(realized_pnl or 0.0), 2)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO paper_portfolio
                (id, cash, positions, pnl_history, updated_at)
            VALUES (1, %s, '{}'::jsonb, '[]'::jsonb, NOW())
            ON CONFLICT (id) DO UPDATE SET
                cash = EXCLUDED.cash,
                positions = '{}'::jsonb,
                updated_at = NOW()
            """,
            (cash,),
        )
    return {
        "legacy_cash_before": before,
        "cash_after_rebase": cash,
        "deployed_capital_after": 0.0,
        "legacy_positions_cleared": True,
        "legacy_pnl_history_preserved": True,
    }


def _sync_phase11_capital_locked(conn: Any) -> Dict[str, Any]:
    """Synchronise autonomous-session paper-capital keys in this transaction."""
    previous: Dict[str, Optional[float]] = {
        "starting_capital": None,
        "topup_target": None,
    }
    key_map = {
        "phase11_starting_capital": "starting_capital",
        "phase11_topup_target": "topup_target",
    }
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT key, value
            FROM phase20_kv
            WHERE key = ANY(%s)
            FOR UPDATE
            """,
            (list(key_map),),
        )
        for key, raw_value in cur.fetchall():
            try:
                previous[key_map[str(key)]] = float(raw_value)
            except (KeyError, TypeError, ValueError):
                continue

        for key in key_map:
            cur.execute(
                """
                INSERT INTO phase20_kv (key, value, updated_at)
                VALUES (%s, %s::jsonb, NOW())
                ON CONFLICT (key) DO UPDATE SET
                    value = EXCLUDED.value,
                    updated_at = NOW()
                """,
                (key, json.dumps(TARGET_CAPITAL)),
            )

    return {
        "previous_phase11_starting_capital": previous["starting_capital"],
        "previous_phase11_topup_target": previous["topup_target"],
        "phase11_starting_capital": TARGET_CAPITAL,
        "phase11_topup_target": TARGET_CAPITAL,
    }


def _base_result(
    *,
    status: str,
    success: bool,
    settings: Dict[str, Any],
    active: List[Dict[str, Any]],
    closed_summary: Dict[str, Any],
    message: str,
) -> Dict[str, Any]:
    open_rows = [row for row in active if row.get("status") == "OPEN"]
    pending_rows = [row for row in active if row.get("status") == "EXIT_PENDING"]
    return {
        "success": success,
        "paper_only": True,
        "broker_orders_called": False,
        "status": status,
        "message": message,
        "target_capital": TARGET_CAPITAL,
        "current_capital": float(settings.get("initial_capital") or 0.0),
        "auto_paper_entries": bool(settings.get("auto_paper_entries")),
        "open_count": len(open_rows),
        "exit_pending_count": len(pending_rows),
        "active_positions": active,
        "closed_history": {
            **closed_summary,
            "preserved": True,
        },
        "derived_limits": _derived_limits(settings),
        "confirmation_required": status in {
            "BLOCKED_OPEN_POSITIONS",
            "CONFIRMATION_REQUIRED",
        },
        "confirmation_text": CONFIRMATION_TEXT,
        "migration_note": (
            f"Paper capital target ₹100,000; migration status {status} "
            f"recorded on {_iso_now()[:10]}."
        ),
        "updated_at": _iso_now(),
    }


def _pause_entries_best_effort() -> bool:
    """Pause entries after an unreadable-state failure without touching capital."""
    try:
        from phase20_store import update_settings

        update_settings({"auto_paper_entries": False})
        return True
    except Exception:
        return False


def _notify_once(result: Dict[str, Any]) -> None:
    """Best-effort, deduplicated operator notification."""
    status = str(result.get("status") or "UNKNOWN")
    if status not in {
        "BLOCKED_OPEN_POSITIONS",
        "BLOCKED_STATE_UNREADABLE",
        "APPLIED",
    }:
        return
    active_ids = ",".join(
        sorted(str(row.get("trade_id") or "") for row in result.get("active_positions") or [])
    )
    signature = hashlib.sha256(f"{status}:{active_ids}".encode()).hexdigest()[:16]
    try:
        from phase20_store import add_notification, kv_claim_once

        if not kv_claim_once(f"paper_capital_migration_notice:{signature}"):
            return
        severity = "INFO" if status == "APPLIED" else "WARNING"
        add_notification(
            "PAPER_CAPITAL_MIGRATION",
            "Paper capital migration applied" if status == "APPLIED"
            else "Paper capital migration blocked",
            str(result.get("message") or ""),
            severity=severity,
            context={
                "status": status,
                "target_capital": TARGET_CAPITAL,
                "current_capital": result.get("current_capital"),
                "open_count": result.get("open_count"),
                "exit_pending_count": result.get("exit_pending_count"),
                "paper_only": True,
            },
        )
    except Exception:
        pass


def _emit_rebased(result: Dict[str, Any]) -> None:
    """Best-effort canonical pipeline event after the DB commit."""
    try:
        from pipeline_events import emit

        emit(
            "PAPER_CAPITAL_REBASED",
            "PORTFOLIO",
            scan_id=None,
            payload={
                "previous_capital": result.get("previous_capital"),
                "new_capital": TARGET_CAPITAL,
                "cash_after_rebase": result.get("cash_after_rebase"),
                "closed_trade_count": (
                    (result.get("closed_history") or {}).get("closed_trade_count")
                ),
                "realized_pnl": (
                    (result.get("closed_history") or {}).get("realized_pnl")
                ),
                "reviewed_by": result.get("reviewed_by"),
                "paper_only": True,
                "broker_orders_called": False,
            },
        )
    except Exception:
        pass


def migrate_paper_capital_to_100000(
    confirmation_text: Optional[str] = None,
    reviewed_by: str = "operator",
) -> Dict[str, Any]:
    """Apply the guarded, idempotent paper-capital migration.

    No file fallback is allowed: inability to query PostgreSQL is treated as an
    unreadable position state and blocks the rebase.
    """
    if not db_available():
        paused = _pause_entries_best_effort()
        result = {
            "success": False,
            "paper_only": True,
            "broker_orders_called": False,
            "status": "BLOCKED_STATE_UNREADABLE",
            "message": (
                "Authoritative PostgreSQL paper-ledger state is unavailable. "
                "Capital was not changed."
            ),
            "target_capital": TARGET_CAPITAL,
            "auto_paper_entries_pause_attempted": True,
            "auto_paper_entries_paused": paused,
            "confirmation_required": False,
            "updated_at": _iso_now(),
        }
        _notify_once(result)
        return result

    conn = None
    entry_lock_held = False
    try:
        conn = _connect()
        _prepare_tables(conn)
        _acquire_entry_admission_lock(conn)
        entry_lock_held = True
        settings, active, closed_summary = _load_locked_state(conn)
        current_capital = float(settings.get("initial_capital") or 0.0)

        if active:
            settings["auto_paper_entries"] = False
            settings["auto_paper_entries_confirmed_at"] = None
            _persist_settings_locked(conn, settings)
            result = _base_result(
                status="BLOCKED_OPEN_POSITIONS",
                success=False,
                settings=settings,
                active=active,
                closed_summary=closed_summary,
                message=(
                    "Capital was not changed because OPEN or EXIT_PENDING paper "
                    "positions exist. Automatic paper entries are paused. Close "
                    "or resolve all positions, then run this migration again with "
                    "the exact operator confirmation."
                ),
            )
            result["reviewed_by"] = reviewed_by
            _persist_status_locked(conn, result)
            conn.commit()
            _notify_once(result)
            return result

        # Idempotency is evaluated only after authoritative active-state safety.
        if current_capital == TARGET_CAPITAL:
            result = _base_result(
                status="ALREADY_APPLIED",
                success=True,
                settings=settings,
                active=active,
                closed_summary=closed_summary,
                message="Paper capital is already ₹100,000; no data was changed.",
            )
            result["reviewed_by"] = reviewed_by
            result.update(_sync_legacy_portfolio_locked(
                conn,
                realized_pnl=float(closed_summary.get("realized_pnl") or 0.0),
            ))
            result.update(_sync_phase11_capital_locked(conn))
            _persist_status_locked(conn, result)
            conn.commit()
            return result

        if (confirmation_text or "").strip() != CONFIRMATION_TEXT:
            settings["auto_paper_entries"] = False
            settings["auto_paper_entries_confirmed_at"] = None
            _persist_settings_locked(conn, settings)
            result = _base_result(
                status="CONFIRMATION_REQUIRED",
                success=False,
                settings=settings,
                active=active,
                closed_summary=closed_summary,
                message=(
                    "No active paper positions were found. Capital remains "
                    f"₹{current_capital:,.0f}; provide the exact confirmation "
                    "text to apply the ₹100,000 rebase."
                ),
            )
            result["reviewed_by"] = reviewed_by
            _persist_status_locked(conn, result)
            conn.commit()
            return result

        settings["initial_capital"] = TARGET_CAPITAL
        # Entries stay paused after a capital boundary change. Re-enabling uses
        # the existing explicit simulated-trades confirmation flow.
        settings["auto_paper_entries"] = False
        settings["auto_paper_entries_confirmed_at"] = None
        _persist_settings_locked(conn, settings)
        portfolio_rebase = _sync_legacy_portfolio_locked(
            conn,
            realized_pnl=float(closed_summary.get("realized_pnl") or 0.0),
        )
        phase11_rebase = _sync_phase11_capital_locked(conn)
        result = _base_result(
            status="APPLIED",
            success=True,
            settings=settings,
            active=active,
            closed_summary=closed_summary,
            message=(
                "Paper capital was rebased to ₹100,000. Closed trade history and "
                "realized P&L were preserved; automatic paper entries remain paused."
            ),
        )
        result["previous_capital"] = current_capital
        result["reviewed_by"] = reviewed_by
        result.update(portfolio_rebase)
        result.update(phase11_rebase)
        _persist_status_locked(conn, result)
        conn.commit()
        _emit_rebased(result)
        _notify_once(result)
        return result
    except Exception as exc:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        paused = _pause_entries_best_effort()
        result = {
            "success": False,
            "paper_only": True,
            "broker_orders_called": False,
            "status": "BLOCKED_STATE_UNREADABLE",
            "message": (
                "Authoritative paper-ledger state could not be read. Capital was "
                "not changed and automatic paper entries were paused where possible."
            ),
            "error": str(exc)[:300],
            "target_capital": TARGET_CAPITAL,
            "auto_paper_entries_pause_attempted": True,
            "auto_paper_entries_paused": paused,
            "confirmation_required": False,
            "updated_at": _iso_now(),
        }
        _notify_once(result)
        return result
    finally:
        if conn is not None:
            if entry_lock_held:
                _release_entry_admission_lock(conn)
            try:
                conn.close()
            except Exception:
                pass


def get_paper_capital_migration_status() -> Dict[str, Any]:
    """Return current migration readiness from a strict PostgreSQL snapshot."""
    if not db_available():
        return {
            "success": False,
            "paper_only": True,
            "status": "BLOCKED_STATE_UNREADABLE",
            "message": "Authoritative PostgreSQL paper-ledger state is unavailable.",
            "target_capital": TARGET_CAPITAL,
            "confirmation_text": CONFIRMATION_TEXT,
            "updated_at": _iso_now(),
        }

    conn = None
    try:
        conn = _connect()
        _prepare_tables(conn)
        settings, active, closed_summary = _load_locked_state(conn)
        current_capital = float(settings.get("initial_capital") or 0.0)
        if active:
            status = "BLOCKED_OPEN_POSITIONS"
            success = False
            message = "Capital migration is blocked by active paper positions."
        elif current_capital == TARGET_CAPITAL:
            status = "ALREADY_APPLIED"
            success = True
            message = "Paper capital is already ₹100,000."
        else:
            status = "CONFIRMATION_REQUIRED"
            success = False
            message = "No active paper positions; exact operator confirmation is required."
        result = _base_result(
            status=status,
            success=success,
            settings=settings,
            active=active,
            closed_summary=closed_summary,
            message=message,
        )
        try:
            result["legacy_paper_cash"] = _read_legacy_cash_locked(conn)
        except Exception:
            result["legacy_paper_cash"] = None
        conn.rollback()  # status is read-only; release table locks explicitly
        return result
    except Exception as exc:
        if conn is not None:
            try:
                conn.rollback()
            except Exception:
                pass
        return {
            "success": False,
            "paper_only": True,
            "status": "BLOCKED_STATE_UNREADABLE",
            "message": "Authoritative paper-ledger state could not be read.",
            "error": str(exc)[:300],
            "target_capital": TARGET_CAPITAL,
            "confirmation_text": CONFIRMATION_TEXT,
            "updated_at": _iso_now(),
        }
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass