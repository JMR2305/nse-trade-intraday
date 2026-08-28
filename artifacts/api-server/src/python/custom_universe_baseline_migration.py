"""Guarded one-shot migration of the approved custom universe authority.

The candidate set is always read from ``custom_universe_master``.  The
hard-coded set below is only a reconciliation invariant: it is never returned
to runtime consumers and is never used as fallback membership.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

import universe_management as management
import universe_version_store as versions

APPROVED_SYMBOLS = (
    "BANKBARODA", "BANKINDIA", "CANBK", "COALINDIA", "FEDERALBNK", "GAIL",
    "HUDCO", "IDFCFIRSTB", "IRCON", "IRFC", "KTKBANK", "MAHABANK", "MRPL",
    "NBCC", "NMDC", "NTPC", "PFC", "PNB", "RECLTD", "RVNL", "SAIL",
    "UNIONBANK", "WIPRO",
)
APPROVED_SET_HASH = "22e5751f25686718f5572041834ce998b7c5ce9844d3b573bc3841749fe77016"
CONFIRMATION = "MIGRATE CUSTOM_LOW_PRICE_SECTOR BASELINE 23"
ACTOR = "authenticated_operator"
REASON = "MIGRATE_EXISTING_PRODUCTION_BASELINE_TO_VERSIONED_AUTHORITY"
AUDIT_TABLE = "trading_universe_baseline_migrations"
IST = ZoneInfo("Asia/Kolkata")


def _ensure_contract() -> None:
    symbols = versions.normalize_symbols(APPROVED_SYMBOLS)
    if len(symbols) != 23 or versions.exact_set_hash(symbols) != APPROVED_SET_HASH:
        raise RuntimeError("approved baseline contract is internally inconsistent")


def _ensure_audit_schema(conn: Any) -> None:
    with conn.cursor() as cur:
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {AUDIT_TABLE} (
                id BIGSERIAL PRIMARY KEY,
                occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                actor TEXT NOT NULL,
                action TEXT NOT NULL CHECK (action = 'BASELINE_MIGRATION'),
                universe_key TEXT NOT NULL,
                destination_universe_id BIGINT NOT NULL
                    REFERENCES trading_universes(id),
                destination_version INTEGER NOT NULL,
                source_authority TEXT NOT NULL,
                exact_symbol_count INTEGER NOT NULL CHECK (exact_symbol_count > 0),
                exact_set_hash TEXT NOT NULL,
                mapping_count INTEGER NOT NULL,
                previous_configured_universe_key TEXT NOT NULL,
                reason TEXT NOT NULL,
                correlation_id TEXT NOT NULL UNIQUE,
                evidence JSONB NOT NULL,
                UNIQUE (universe_key, destination_version)
            )
        """)
        cur.execute("""
            CREATE OR REPLACE FUNCTION reject_baseline_migration_history_mutation()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'Baseline migration audit is append-only';
            END;
            $$ LANGUAGE plpgsql
        """)
        cur.execute(f"""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_trigger
                    WHERE tgname = 'trg_baseline_migration_audit_immutable'
                ) THEN
                    CREATE TRIGGER trg_baseline_migration_audit_immutable
                    BEFORE UPDATE OR DELETE ON {AUDIT_TABLE}
                    FOR EACH ROW
                    EXECUTE FUNCTION reject_baseline_migration_history_mutation();
                END IF;
            END
            $$;
        """)


def ensure_schema() -> bool:
    if not versions._db_available():
        return False
    try:
        with versions._connect() as conn:
            management._ensure_management_schema(conn)
            _ensure_audit_schema(conn)
        return True
    except Exception:
        return False


def _json(value: Any) -> Any:
    return value.isoformat() if hasattr(value, "isoformat") else value


def _settings_digest(settings: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(settings, sort_keys=True, default=str, separators=(",", ":")).encode()
    ).hexdigest()


def _load_master_rows(cur: Any) -> List[Dict[str, Any]]:
    cur.execute("""
        SELECT symbol, company_name, sector, yahoo_symbol, kite_symbol,
               instrument_token, is_active, instrument_exchange,
               instrument_tradingsymbol, instrument_cache_date,
               instrument_mapping_at, last_verified_at, price_min, price_max,
               ohlcv_available
        FROM custom_universe_master
        WHERE allowed_universe = %s AND is_active = TRUE
        ORDER BY symbol
        FOR SHARE
    """, (versions.CUSTOM_UNIVERSE_KEY,))
    columns = (
        "symbol", "company_name", "sector", "yahoo_symbol", "kite_symbol",
        "instrument_token", "is_active", "instrument_exchange",
        "instrument_tradingsymbol", "instrument_cache_date",
        "instrument_mapping_at", "last_verified_at", "price_min", "price_max",
        "ohlcv_available",
    )
    return [
        {key: _json(value) for key, value in zip(columns, row)}
        for row in cur.fetchall()
    ]


def _members_from_source(
    rows: Sequence[Mapping[str, Any]],
    instruments: Iterable[Mapping[str, Any]],
    *,
    instrument_cache_fresh: bool,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    approved = versions.normalize_symbols(APPROVED_SYMBOLS)
    try:
        source_symbols = versions.normalize_symbols(row.get("symbol") for row in rows)
    except ValueError as exc:
        return [], {
            "status": "VALIDATION_FAIL",
            "valid": False,
            "error": "baseline_set_not_proven",
            "detail": str(exc),
            "source_symbol_count": len(rows),
            "source_symbols": [],
            "missing_symbols": list(approved),
            "unexpected_symbols": [],
            "exact_set_hash": None,
        }
    missing = sorted(set(approved) - set(source_symbols))
    unexpected = sorted(set(source_symbols) - set(approved))
    if (
        len(source_symbols) != 23
        or source_symbols != approved
        or versions.exact_set_hash(source_symbols) != APPROVED_SET_HASH
    ):
        return [], {
            "status": "VALIDATION_FAIL",
            "valid": False,
            "error": "baseline_set_not_proven",
            "source_symbol_count": len(source_symbols),
            "source_symbols": source_symbols,
            "missing_symbols": missing,
            "unexpected_symbols": unexpected,
            "exact_set_hash": versions.exact_set_hash(source_symbols),
        }
    members = []
    for row in rows:
        members.append({
            "symbol": row["symbol"],
            "exchange": str(row.get("instrument_exchange") or "").upper(),
            "sector": row.get("sector"),
            "instrument_token": row.get("instrument_token"),
            "mapping_status": "MAPPED",
            "enabled": True,
            "metadata": {
                "sector": row.get("sector"),
                "company_name": row.get("company_name"),
                "yahoo_symbol": row.get("yahoo_symbol"),
                "kite_symbol": row.get("kite_symbol"),
                "price_min": row.get("price_min"),
                "price_max": row.get("price_max"),
                "ohlcv_available": row.get("ohlcv_available"),
                "instrument_tradingsymbol": row.get("instrument_tradingsymbol"),
                "instrument_cache_date": row.get("instrument_cache_date"),
                "instrument_mapping_at": row.get("instrument_mapping_at"),
                "last_verified_at": row.get("last_verified_at"),
            },
        })
    validation = management.validate_members(
        members,
        instruments,
        instrument_cache_fresh=instrument_cache_fresh,
        require_persisted_binding=True,
        required_metadata=("sector", "yahoo_symbol", "kite_symbol"),
    )
    validation.update({
        "source_symbol_count": len(source_symbols),
        "source_symbols": source_symbols,
        "missing_symbols": missing,
        "unexpected_symbols": unexpected,
        "exact_set_hash": versions.exact_set_hash(source_symbols),
    })
    if not validation.get("valid"):
        validation["error"] = "kite_mapping_failure"
    return members, validation


def _read_safety(cur: Any) -> Dict[str, Any]:
    # The zero-position assertion must remain true until commit. Row locks on
    # the currently matching set do not stop a new OPEN row (phantom), so hold
    # a table lock that conflicts with ledger inserts/updates for the short
    # migration transaction.
    cur.execute("LOCK TABLE phase20_paper_trades IN SHARE MODE")
    cur.execute("SELECT data FROM phase20_settings WHERE id = 1 FOR UPDATE")
    row = cur.fetchone()
    stored = row[0] if row and isinstance(row[0], dict) else {}
    cur.execute("""
        SELECT status
        FROM phase20_paper_trades
        WHERE status IN ('OPEN', 'EXIT_PENDING')
        FOR SHARE
    """)
    counts = {"OPEN": 0, "EXIT_PENDING": 0}
    for (status,) in cur.fetchall():
        key = str(status)
        counts[key] = counts.get(key, 0) + 1
    controlled_error = None
    try:
        from controlled_paper_entry_flags import get_controlled_paper_entry_flags
        controlled = get_controlled_paper_entry_flags().as_dict()
    except Exception as exc:
        controlled = {}
        controlled_error = str(exc)[:200]
    safety = {
        "automatic_paper_entries": stored.get("auto_paper_entries"),
        "entry_confirmation": stored.get("auto_paper_entries_confirmed_at"),
        "bootstrap": stored.get("bootstrap_paper_enabled"),
        "automatic_exits": stored.get("auto_paper_exits"),
        "active_intraday_universe": stored.get("active_intraday_universe"),
        "controlled_execution_enabled": controlled.get(
            "CONTROLLED_PAPER_ENTRY_FRAMEWORK_ENABLED", False
        ),
        "execution_allowed": controlled.get("execution_allowed", False),
        "live_broker_orders_enabled": str(
            os.environ.get("LIVE_EXECUTION_ENABLED", "false")
        ).lower() in {"1", "true", "yes"},
        "broker_mode": "PAPER_TRADING",
        "portfolio_source": "phase20_ledger",
        "open_positions": counts.get("OPEN", 0),
        "exit_pending": counts.get("EXIT_PENDING", 0),
        "settings_digest": _settings_digest(stored),
        "controlled_execution_inspection_ok": controlled_error is None,
        "controlled_execution_inspection_error": controlled_error,
    }
    safety["valid"] = (
        safety["automatic_paper_entries"] is False
        and safety["entry_confirmation"] is None
        and safety["bootstrap"] is False
        and safety["automatic_exits"] is True
        and safety["controlled_execution_enabled"] is False
        and safety["execution_allowed"] is False
        and safety["controlled_execution_inspection_ok"] is True
        and safety["live_broker_orders_enabled"] is False
        and safety["open_positions"] == 0
        and safety["exit_pending"] == 0
        and safety["active_intraday_universe"] == versions.CUSTOM_UNIVERSE_KEY
    )
    return safety


def _existing_state(cur: Any) -> List[Dict[str, Any]]:
    cur.execute("""
        SELECT id, version, status, exact_set_hash, enabled_symbol_count,
               effective_from, effective_until
        FROM trading_universes
        WHERE universe_key = %s
        ORDER BY version
        FOR UPDATE
    """, (versions.CUSTOM_UNIVERSE_KEY,))
    return [
        {
            "id": int(row[0]), "version": int(row[1]), "status": row[2],
            "exact_set_hash": row[3], "enabled_symbol_count": int(row[4]),
            "effective_from": _json(row[5]),
            "effective_until": _json(row[6]),
        }
        for row in cur.fetchall()
    ]


def _effective_interval_is_runtime_usable(revision: Mapping[str, Any]) -> bool:
    raw_from = revision.get("effective_from")
    raw_until = revision.get("effective_until")
    if not raw_from or raw_until is not None:
        return False
    try:
        effective_from = (
            raw_from if isinstance(raw_from, datetime)
            else datetime.fromisoformat(str(raw_from).replace("Z", "+00:00"))
        )
        if effective_from.tzinfo is None:
            effective_from = effective_from.replace(tzinfo=timezone.utc)
        return effective_from <= _next_natural_session_boundary()
    except (TypeError, ValueError):
        return False


def _existing_revision_integrity(cur: Any, revision_id: int) -> bool:
    cur.execute("""
        SELECT symbol, exchange, instrument_token, mapping_status
        FROM trading_universe_members
        WHERE universe_id = %s AND enabled = TRUE
        ORDER BY symbol
    """, (revision_id,))
    rows = cur.fetchall()
    symbols = [row[0] for row in rows]
    try:
        return (
            symbols == list(versions.normalize_symbols(APPROVED_SYMBOLS))
            and versions.exact_set_hash(symbols) == APPROVED_SET_HASH
            and len(rows) == 23
            and len({int(row[2]) for row in rows if row[2] is not None}) == 23
            and all(row[1] == "NSE" and row[3] == "MAPPED" for row in rows)
        )
    except (TypeError, ValueError):
        return False


def _audit_for_revision(cur: Any, revision_id: int) -> Optional[Dict[str, Any]]:
    cur.execute(f"""
        SELECT action, occurred_at, actor, destination_version, exact_symbol_count,
               exact_set_hash, mapping_count, source_authority, reason, evidence
        FROM {AUDIT_TABLE}
        WHERE destination_universe_id = %s
    """, (revision_id,))
    row = cur.fetchone()
    if not row:
        return None
    keys = (
        "action", "occurred_at", "actor", "destination_version",
        "exact_symbol_count", "exact_set_hash", "mapping_count",
        "source_authority", "reason", "evidence",
    )
    return {key: _json(value) for key, value in zip(keys, row)}


def _evaluate(cur: Any, instruments: Sequence[Mapping[str, Any]], reference: Mapping[str, Any]) -> Dict[str, Any]:
    # Predicate row locks do not prevent a concurrent refresh from inserting a
    # new active custom symbol. Hold a table lock through the transaction so
    # the source exact-set assertion remains true at commit.
    cur.execute("LOCK TABLE custom_universe_master IN SHARE MODE")
    rows = _load_master_rows(cur)
    members, validation = _members_from_source(
        rows, instruments, instrument_cache_fresh=bool(reference.get("is_fresh"))
    )
    existing = _existing_state(cur)
    safety = _read_safety(cur)
    exact_existing = [
        item for item in existing
        if item["status"] == "ACTIVE"
        and item["version"] == 1
        and item["enabled_symbol_count"] == 23
        and item["exact_set_hash"] == APPROVED_SET_HASH
    ]
    idempotent = (
        len(existing) == 1
        and len(exact_existing) == 1
        and _effective_interval_is_runtime_usable(exact_existing[0])
        and _existing_revision_integrity(cur, exact_existing[0]["id"])
    )
    conflict = bool(existing) and not idempotent
    ready = bool(validation.get("valid")) and safety["valid"] and not conflict
    return {
        "success": True,
        "ready": ready,
        "universe_key": versions.CUSTOM_UNIVERSE_KEY,
        "source_authority": "custom_universe_master",
        "expected_symbol_count": 23,
        "expected_set_hash": APPROVED_SET_HASH,
        "candidate_symbols": validation.get("source_symbols", []),
        "candidate_set_hash": validation.get("exact_set_hash"),
        "validation": validation,
        "instrument_reference": dict(reference),
        "safety": safety,
        "existing_revisions": existing,
        "conflict": conflict,
        "idempotent": idempotent,
        "members": members,
    }


def _next_natural_session_boundary(now: Optional[datetime] = None) -> datetime:
    from market_hours import is_trading_day

    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    candidate = instant.astimezone(IST).date() + timedelta(days=1)
    while not is_trading_day(candidate):
        candidate += timedelta(days=1)
    return datetime.combine(candidate, time(9, 0), tzinfo=IST).astimezone(timezone.utc)


def readiness() -> Dict[str, Any]:
    _ensure_contract()
    if not versions._db_available():
        return {"success": False, "error": "db_unavailable", "ready": False}
    instruments, reference = management._instrument_reference()
    try:
        with versions._connect() as conn:
            with conn.cursor() as cur:
                result = _evaluate(cur, instruments, reference)
                result["scheduled_effective_from"] = (
                    result["existing_revisions"][0].get("effective_from")
                    if result["idempotent"] else
                    _next_natural_session_boundary().isoformat()
                )
                if result["idempotent"]:
                    revision = result["existing_revisions"][0]
                    result["migration_audit"] = _audit_for_revision(cur, revision["id"])
                result.pop("members", None)
                return result
    except Exception as exc:
        return {"success": False, "error": str(exc)[:300], "ready": False}


def execute(
    *, confirmation: str, actor: str = ACTOR, correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    _ensure_contract()
    if confirmation != CONFIRMATION:
        return {
            "success": False, "error": "typed_confirmation_mismatch",
            "confirmation_required": CONFIRMATION,
        }
    if not versions._db_available():
        return {"success": False, "error": "db_unavailable"}
    if not ensure_schema():
        return {"success": False, "error": "schema_unavailable"}
    instruments, reference = management._instrument_reference()
    correlation_id = correlation_id or str(uuid.uuid4())
    try:
        with versions._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))",
                    ("custom-universe-baseline-migration",),
                )
                evidence = _evaluate(cur, instruments, reference)
                if evidence["idempotent"]:
                    revision = evidence["existing_revisions"][0]
                    audit = _audit_for_revision(cur, revision["id"])
                    if not audit:
                        raise RuntimeError("matching active baseline has no migration audit")
                    return {
                        "success": True, "status": "ALREADY_MIGRATED",
                        "idempotent": True, "active_revision": revision,
                        "migration_audit": audit,
                    }
                if evidence["conflict"]:
                    return {
                        "success": False, "error": "conflicting_revision",
                        "existing_revisions": evidence["existing_revisions"],
                    }
                if not evidence["validation"].get("valid"):
                    return {
                        "success": False,
                        "error": evidence["validation"].get("error", "validation_failed"),
                        "validation": evidence["validation"],
                    }
                if not evidence["safety"]["valid"]:
                    return {
                        "success": False, "error": "safety_baseline_failed",
                        "safety": evidence["safety"],
                    }
                members = evidence.pop("members")
                now = datetime.now(timezone.utc)
                effective_from = _next_natural_session_boundary(now)
                cur.execute("""
                    INSERT INTO trading_universe_sources (
                        source_type, source_reference, source_table,
                        source_snapshot_at, source_set_hash, imported_by, metadata
                    ) VALUES (
                        'BASELINE_MIGRATION', %s, 'custom_universe_master',
                        %s, %s, %s, %s
                    ) RETURNING id
                """, (
                    f"approved-production-baseline:{APPROVED_SET_HASH}",
                    now, APPROVED_SET_HASH, actor,
                    json.dumps({
                        "reason": REASON, "symbol_count": 23,
                        "mapping_count": 23,
                    }),
                ))
                source_id = int(cur.fetchone()[0])
                cur.execute("""
                    INSERT INTO trading_universes (
                        universe_key, display_name, version, status,
                        effective_from, created_by, approved_at, approved_by,
                        notes, exact_set_hash, enabled_symbol_count, source_id
                    ) VALUES (%s, %s, 1, 'DRAFT', NULL, %s, NULL, NULL, %s, %s, 23, %s)
                    RETURNING id
                """, (
                    versions.CUSTOM_UNIVERSE_KEY, versions.DISPLAY_NAME, actor,
                    "Exact approved production baseline migrated to versioned authority.",
                    APPROVED_SET_HASH, source_id,
                ))
                revision_id = int(cur.fetchone()[0])
                for member in members:
                    cur.execute("""
                        INSERT INTO trading_universe_members (
                            universe_id, symbol, exchange, sector, instrument_token,
                            mapping_status, enabled, added_by, notes
                        ) VALUES (%s, %s, %s, %s, %s, 'MAPPED', TRUE, %s, %s)
                    """, (
                        revision_id, member["symbol"], member["exchange"],
                        member["sector"], member["instrument_token"], actor,
                        "Existing approved production baseline member.",
                    ))
                    cur.execute("""
                        INSERT INTO trading_universe_member_details (
                            universe_id, symbol, metadata, created_by
                        ) VALUES (%s, %s, %s, %s)
                    """, (
                        revision_id, member["symbol"],
                        json.dumps(member["metadata"]), actor,
                    ))
                cur.execute("""
                    SELECT symbol, instrument_token, mapping_status
                    FROM trading_universe_members
                    WHERE universe_id = %s AND enabled = TRUE
                    ORDER BY symbol
                """, (revision_id,))
                persisted = cur.fetchall()
                persisted_symbols = [row[0] for row in persisted]
                if (
                    persisted_symbols != list(versions.normalize_symbols(APPROVED_SYMBOLS))
                    or versions.exact_set_hash(persisted_symbols) != APPROVED_SET_HASH
                    or len({int(row[1]) for row in persisted}) != 23
                    or any(row[2] != "MAPPED" for row in persisted)
                ):
                    raise RuntimeError("persisted baseline integrity verification failed")
                validation_evidence = {
                    **evidence["validation"],
                    "migration_reason": REASON,
                    "instrument_reference": dict(reference),
                }
                cur.execute("""
                    INSERT INTO trading_universe_validations (
                        universe_id, result, checked_by, correlation_id, evidence
                    ) VALUES (%s, 'VALIDATION_PASS', %s, %s, %s)
                """, (
                    revision_id, actor, correlation_id,
                    json.dumps(validation_evidence),
                ))
                cur.execute("""
                    UPDATE trading_universes
                    SET status = 'ACTIVE', effective_from = %s,
                        approved_at = %s, approved_by = %s
                    WHERE id = %s AND status = 'DRAFT'
                """, (effective_from, now, actor, revision_id))
                if cur.rowcount != 1:
                    raise RuntimeError("atomic baseline activation failed")
                audit_evidence = {
                    "source_authority": "custom_universe_master",
                    "destination_universe_id": revision_id,
                    "destination_version": 1,
                    "exact_symbol_count": 23,
                    "exact_set_hash": APPROVED_SET_HASH,
                    "mapping_completeness": {"mapped": 23, "total": 23},
                    "previous_configured_universe_key":
                        evidence["safety"]["active_intraday_universe"],
                    "reason": REASON,
                    "safety_before": evidence["safety"],
                }
                cur.execute(f"""
                    INSERT INTO {AUDIT_TABLE} (
                        actor, action, universe_key, destination_universe_id,
                        destination_version, source_authority, exact_symbol_count,
                        exact_set_hash, mapping_count,
                        previous_configured_universe_key, reason, correlation_id,
                        evidence
                    ) VALUES (
                        %s, 'BASELINE_MIGRATION', %s, %s, 1,
                        'custom_universe_master', 23, %s, 23, %s, %s, %s, %s
                    ) RETURNING occurred_at
                """, (
                    actor, versions.CUSTOM_UNIVERSE_KEY, revision_id,
                    APPROVED_SET_HASH,
                    evidence["safety"]["active_intraday_universe"],
                    REASON, correlation_id, json.dumps(audit_evidence),
                ))
                occurred_at = cur.fetchone()[0]
                cur.execute("SELECT data FROM phase20_settings WHERE id = 1")
                settings_after = cur.fetchone()
                after = settings_after[0] if settings_after and isinstance(settings_after[0], dict) else {}
                if _settings_digest(after) != evidence["safety"]["settings_digest"]:
                    raise RuntimeError("safety settings changed during migration")
                return {
                    "success": True, "status": "MIGRATED", "idempotent": False,
                    "active_revision": {
                        "id": revision_id, "universe_key": versions.CUSTOM_UNIVERSE_KEY,
                        "version": 1, "status": "ACTIVE",
                        "enabled_symbol_count": 23,
                        "exact_set_hash": APPROVED_SET_HASH,
                        "effective_from": effective_from.isoformat(),
                        "natural_session_policy": "NEXT_NATURAL_SESSION_09_00_IST",
                    },
                    "mapping_coverage": {"mapped": 23, "total": 23, "complete": True},
                    "migration_audit": {
                        "action": "BASELINE_MIGRATION",
                        "occurred_at": _json(occurred_at), **audit_evidence,
                    },
                    "safety": evidence["safety"],
                }
    except Exception as exc:
        return {"success": False, "error": str(exc)[:300]}