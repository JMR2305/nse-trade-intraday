"""Authenticated custom-universe management workflow.

This module is deliberately separate from the scanner's current-state master.
Management revisions are append-only snapshots.  A draft edit creates a new
draft successor rather than updating or deleting a historical member row.
Activation is intentionally locked for the first production release.
"""

from __future__ import annotations

import json
import logging
import os
import uuid
import hashlib
from copy import deepcopy
from datetime import datetime, time, timedelta, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

import universe_version_store as versions

logger = logging.getLogger(__name__)

ACTIVATION_LOCKED = True
ACTIVATION_LOCK_REASON = (
    "Production activation is locked for the initial release pending universe "
    "management certification. Draft review and validation remain available."
)
ACTOR = "authenticated_operator"
IST = ZoneInfo("Asia/Kolkata")

_DETAILS_TABLE = "trading_universe_member_details"
_VALIDATION_TABLE = "trading_universe_validations"
_REQUIRED_METADATA = (
    "sector",
    "company_name",
    "yahoo_symbol",
    "kite_symbol",
    "price_min",
    "price_max",
    "ohlcv_available",
)


def _json(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def _error(code: str, message: str, **extra: Any) -> Dict[str, Any]:
    return {"code": code, "message": message, **extra}


def _normalise_member(raw: Mapping[str, Any], *, enabled: Optional[bool] = None) -> Dict[str, Any]:
    symbol = versions.normalize_symbol(raw.get("symbol"))
    metadata = dict(raw.get("metadata") or {})
    for key in _REQUIRED_METADATA:
        if key in raw and key not in metadata:
            metadata[key] = raw[key]
    kite_symbol = raw.get("kite_symbol")
    if kite_symbol is not None and "kite_symbol" not in metadata:
        metadata["kite_symbol"] = str(kite_symbol).strip().upper()
    return {
        "symbol": symbol,
        "exchange": str(raw.get("exchange") or "NSE").strip().upper() or "NSE",
        "sector": str(raw.get("sector") or metadata.get("sector") or "").strip().upper() or None,
        "instrument_token": raw.get("instrument_token"),
        "mapping_status": str(raw.get("mapping_status") or "UNVERIFIED").upper(),
        "enabled": bool(raw.get("enabled", True) if enabled is None else enabled),
        "notes": raw.get("notes"),
        "metadata": metadata,
    }


def _metadata_from_member(member: Mapping[str, Any]) -> Dict[str, Any]:
    metadata = dict(member.get("metadata") or {})
    for key in _REQUIRED_METADATA:
        if key not in metadata and key in member:
            metadata[key] = member[key]
    return metadata


def _member_for_validation(member: Mapping[str, Any]) -> Dict[str, Any]:
    metadata = _metadata_from_member(member)
    out = dict(member)
    out["metadata"] = metadata
    out["kite_symbol"] = metadata.get("kite_symbol")
    out["sector"] = metadata.get("sector", member.get("sector"))
    return out


def _instrument_index(instruments: Iterable[Mapping[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    by_symbol: Dict[str, List[Dict[str, Any]]] = {}
    for raw in instruments:
        if not isinstance(raw, Mapping):
            continue
        name = str(raw.get("symbol") or raw.get("tradingsymbol") or "").strip().upper()
        if not name:
            continue
        token = raw.get("token", raw.get("instrument_token"))
        try:
            token_int = int(token)
        except (TypeError, ValueError):
            token_int = 0
        by_symbol.setdefault(name, []).append({
            "symbol": name,
            "exchange": str(raw.get("exchange") or "").strip().upper(),
            "segment": str(raw.get("segment") or "").strip().upper(),
            "instrument_type": str(raw.get("instrument_type") or "").strip().upper(),
            "token": token_int,
        })
    return by_symbol


def validate_members(
    members: Sequence[Mapping[str, Any]],
    instruments: Optional[Iterable[Mapping[str, Any]]] = None,
    *,
    instrument_cache_fresh: Optional[bool] = None,
    require_persisted_binding: bool = False,
) -> Dict[str, Any]:
    """Validate a complete enabled member set without mutating anything."""
    errors: List[Dict[str, Any]] = []
    normalized: List[Dict[str, Any]] = []
    seen_symbols: Dict[str, int] = {}
    seen_tokens: Dict[int, str] = {}
    mapping_bindings: Dict[str, Dict[str, Any]] = {}
    by_symbol = _instrument_index(instruments or [])

    if instrument_cache_fresh is False:
        errors.append(_error(
            "STALE_KITE_INSTRUMENT_CACHE",
            "Kite instrument cache is not fresh for the current session",
        ))

    for index, raw in enumerate(members):
        try:
            member = _normalise_member(raw)
        except (TypeError, ValueError) as exc:
            errors.append(_error("INVALID_NORMALIZED_SYMBOL", str(exc), index=index))
            continue
        normalized.append(member)
        symbol = member["symbol"]
        if symbol in seen_symbols:
            errors.append(_error(
                "DUPLICATE_SYMBOL", f"duplicate normalized symbol {symbol}",
                symbol=symbol, index=index,
            ))
        else:
            seen_symbols[symbol] = index

        metadata = member["metadata"]
        missing = [
            field for field in _REQUIRED_METADATA
            if metadata.get(field) is None
            or (isinstance(metadata.get(field), str) and not metadata[field].strip())
        ]
        for field in missing:
            errors.append(_error(
                "MISSING_REQUIRED_METADATA",
                f"{symbol} is missing required metadata: {field}",
                symbol=symbol, field=field,
            ))

        kite_name = str(metadata.get("kite_symbol") or symbol).strip().upper()
        candidates = by_symbol.get(kite_name, [])
        if not candidates:
            errors.append(_error(
                "MISSING_KITE_MAPPING",
                f"{symbol} has no exact Kite instrument mapping",
                symbol=symbol, kite_symbol=kite_name,
            ))
            continue
        if len(candidates) > 1:
            errors.append(_error(
                "DUPLICATE_KITE_MAPPING",
                f"{kite_name} has multiple Kite instrument mappings",
                symbol=symbol, kite_symbol=kite_name,
            ))
            continue
        instrument = candidates[0]
        candidate_error_count = len(errors)
        if instrument["exchange"] != "NSE":
            errors.append(_error(
                "INVALID_EXCHANGE", f"{kite_name} is not an NSE instrument",
                symbol=symbol, exchange=instrument["exchange"],
            ))
        if instrument["segment"] not in {"NSE", "NSE-CM", "NSE_EQ"}:
            errors.append(_error(
                "INVALID_SEGMENT", f"{kite_name} is not in the NSE cash segment",
                symbol=symbol, segment=instrument["segment"],
            ))
        if instrument["instrument_type"] != "EQ":
            errors.append(_error(
                "UNSUPPORTED_INSTRUMENT_TYPE",
                f"{kite_name} is not an NSE/EQ instrument",
                symbol=symbol, instrument_type=instrument["instrument_type"],
            ))
        if instrument["token"] <= 0:
            errors.append(_error(
                "INVALID_KITE_TOKEN", f"{kite_name} has no positive Kite token",
                symbol=symbol,
            ))
        elif instrument["token"] in seen_tokens:
            errors.append(_error(
                "DUPLICATE_INSTRUMENT_TOKEN",
                f"Kite token {instrument['token']} is used by multiple symbols",
                symbol=symbol, token=instrument["token"],
                other_symbol=seen_tokens[instrument["token"]],
            ))
        else:
            seen_tokens[instrument["token"]] = symbol
        if len(errors) == candidate_error_count:
            mapping_bindings[symbol] = {
                "exchange": instrument["exchange"],
                "instrument_token": instrument["token"],
                "mapping_status": "MAPPED",
                "kite_symbol": kite_name,
            }
            if require_persisted_binding and (
                member.get("instrument_token") != instrument["token"]
                or member.get("exchange") != instrument["exchange"]
                or member.get("mapping_status") != "MAPPED"
            ):
                errors.append(_error(
                    "PERSISTED_MAPPING_MISMATCH",
                    f"{symbol} does not retain the current exact Kite mapping",
                    symbol=symbol,
                    expected=mapping_bindings[symbol],
                    persisted={
                        "exchange": member.get("exchange"),
                        "instrument_token": member.get("instrument_token"),
                        "mapping_status": member.get("mapping_status"),
                    },
                ))

    unique_enabled = len({member["symbol"] for member in normalized})
    if unique_enabled == 0:
        errors.append(_error(
            "EMPTY_ENABLED_UNIVERSE",
            "A revision must contain at least one enabled symbol",
        ))
    mapping_errors = {
        "MISSING_KITE_MAPPING", "DUPLICATE_KITE_MAPPING", "INVALID_EXCHANGE",
        "INVALID_SEGMENT", "UNSUPPORTED_INSTRUMENT_TYPE", "INVALID_KITE_TOKEN",
        "DUPLICATE_INSTRUMENT_TOKEN", "PERSISTED_MAPPING_MISMATCH",
    }
    mapping_error_count = sum(1 for item in errors if item["code"] in mapping_errors)
    mapped_count = max(0, unique_enabled - mapping_error_count)
    complete = not errors and (unique_enabled == mapped_count)
    return {
        "status": "VALIDATION_PASS" if complete else "VALIDATION_FAIL",
        "valid": complete,
        "errors": errors,
        "normalized_members": normalized,
        "mapping_bindings": mapping_bindings,
        "enabled_symbol_count": unique_enabled,
        "mapping_coverage": {
            "mapped": mapped_count if complete else max(0, unique_enabled - mapping_error_count),
            "total": unique_enabled,
            "percent": round(
                (mapped_count / unique_enabled * 100) if unique_enabled else 0.0, 2
            ),
            "complete": bool(unique_enabled == mapped_count and unique_enabled > 0),
        },
        "provider_compatibility": {
            "provider": "KITE",
            "instrument_reference": "current_kite_instrument_cache",
            "nse_equity_required": True,
            "compatible": complete,
        },
        "phase5a_compatibility": {
            "expected_enabled_symbols": unique_enabled,
            "exact_symbol_set_available": complete,
            "provider_coverage_required": True,
            "compatible": complete,
        },
        "readiness_compatibility": {
            "kite_mapping_coverage_100_percent": bool(unique_enabled == mapped_count and unique_enabled > 0),
            "ready_for_activation": complete,
            "activation_allowed": False,
        },
    }


def _ensure_management_schema(conn: Any) -> None:
    versions._ensure_schema(conn)
    with conn.cursor() as cur:
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {_DETAILS_TABLE} (
                universe_id BIGINT NOT NULL REFERENCES trading_universes(id),
                symbol TEXT NOT NULL,
                metadata JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                created_by TEXT NOT NULL,
                PRIMARY KEY (universe_id, symbol)
            )
        """)
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {_VALIDATION_TABLE} (
                id BIGSERIAL PRIMARY KEY,
                universe_id BIGINT NOT NULL REFERENCES trading_universes(id),
                result TEXT NOT NULL CHECK (result IN ('VALIDATION_PASS', 'VALIDATION_FAIL')),
                checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                checked_by TEXT NOT NULL,
                correlation_id TEXT,
                evidence JSONB NOT NULL DEFAULT '{{}}'::jsonb
            )
        """)
        cur.execute(f"""
            CREATE INDEX IF NOT EXISTS idx_{_VALIDATION_TABLE}_revision
            ON {_VALIDATION_TABLE} (universe_id, checked_at DESC)
        """)
        cur.execute(f"""
            CREATE OR REPLACE FUNCTION task947_reject_management_history()
            RETURNS trigger AS $$
            BEGIN
                RAISE EXCEPTION 'Universe management history is append-only';
            END;
            $$ LANGUAGE plpgsql
        """)
        cur.execute("""
            DO $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM pg_trigger
                    WHERE tgname = 'trg_task947_details_immutable'
                ) THEN
                    CREATE TRIGGER trg_task947_details_immutable
                    BEFORE UPDATE OR DELETE ON trading_universe_member_details
                    FOR EACH ROW EXECUTE FUNCTION task947_reject_management_history();
                END IF;
                IF NOT EXISTS (
                    SELECT 1 FROM pg_trigger
                    WHERE tgname = 'trg_task947_validation_immutable'
                ) THEN
                    CREATE TRIGGER trg_task947_validation_immutable
                    BEFORE UPDATE OR DELETE ON trading_universe_validations
                    FOR EACH ROW EXECUTE FUNCTION task947_reject_management_history();
                END IF;
            END
            $$;
        """)


def ensure_schema() -> bool:
    if not versions._db_available():
        return False
    try:
        with versions._connect() as conn:
            _ensure_management_schema(conn)
        return True
    except Exception as exc:
        logger.warning("universe_management.ensure_schema: %s", exc)
        return False


def _revision_with_members(cur: Any, revision: Mapping[str, Any]) -> Dict[str, Any]:
    cur.execute("""
        SELECT m.id, m.universe_id, m.symbol, m.exchange, m.sector,
               m.instrument_token, m.mapping_status, m.enabled, m.added_at,
               m.added_by, m.removed_at, m.removed_by, m.notes,
               d.metadata
        FROM trading_universe_members m
        LEFT JOIN trading_universe_member_details d
          ON d.universe_id = m.universe_id AND d.symbol = m.symbol
        WHERE m.universe_id = %s
        ORDER BY m.symbol
    """, (revision["id"],))
    members = []
    for row in cur.fetchall():
        data = dict(zip(
            ("id", "universe_id", "symbol", "exchange", "sector",
             "instrument_token", "mapping_status", "enabled", "added_at",
             "added_by", "removed_at", "removed_by", "notes", "metadata"),
            row,
        ))
        data = {key: _json(value) for key, value in data.items()}
        data["metadata"] = data.get("metadata") or {}
        members.append(data)
    return {**dict(revision), "members": members}


def _revision_from_row(row: Sequence[Any]) -> Dict[str, Any]:
    return versions._revision_dict(row)


def get_revision_view(*, version: Optional[int] = None, revision_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
    revision = versions.get_revision(version=version, revision_id=revision_id)
    if not revision or not versions._db_available():
        return None
    try:
        with versions._connect() as conn:
            with conn.cursor() as cur:
                return _revision_with_members(cur, revision)
    except Exception as exc:
        logger.warning("universe_management.get_revision_view: %s", exc)
        return None


def list_revisions() -> Dict[str, Any]:
    if not versions._db_available():
        return {"success": False, "error": "db_unavailable", "revisions": []}
    try:
        with versions._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, universe_key, display_name, version, status,
                           effective_from, effective_until, created_at, created_by,
                           approved_at, approved_by, notes, exact_set_hash,
                           enabled_symbol_count, source_id
                    FROM trading_universes
                    WHERE universe_key = %s
                    ORDER BY version DESC
                """, (versions.CUSTOM_UNIVERSE_KEY,))
                rows = [_revision_from_row(row) for row in cur.fetchall()]
        return {"success": True, "universe_key": versions.CUSTOM_UNIVERSE_KEY, "revisions": rows}
    except Exception as exc:
        return {"success": False, "error": str(exc)[:300], "revisions": []}


def active_view() -> Dict[str, Any]:
    revision = get_revision_view()
    return {
        "success": True,
        "active_revision": revision,
        "activation": {
            "locked": ACTIVATION_LOCKED,
            "lock_reason": ACTIVATION_LOCK_REASON if ACTIVATION_LOCKED else None,
            "production_release": "INITIAL",
        },
    }


def _audit_in_tx(
    cur: Any, *, action: str, actor: str, correlation_id: str,
    old_version: Optional[int] = None, new_version: Optional[int] = None,
    symbol: Optional[str] = None, old_value: Any = None,
    new_value: Any = None, notes: Optional[str] = None,
    approval_state: Optional[str] = None, change_type: Optional[str] = None,
) -> None:
    if action not in versions.AUDIT_ACTIONS:
        raise ValueError(f"unsupported audit action: {action}")
    cur.execute("""
        INSERT INTO trading_universe_audit_events (
            actor, action, universe_key, old_version, new_version, symbol,
            change_type, old_value, new_value, notes, correlation_id, approval_state
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
    """, (
        actor, action, versions.CUSTOM_UNIVERSE_KEY, old_version, new_version,
        symbol, change_type or action, json.dumps(old_value) if old_value is not None else None,
        json.dumps(new_value) if new_value is not None else None, notes,
        correlation_id, approval_state,
    ))


def _next_version(cur: Any) -> int:
    # PostgreSQL does not permit FOR UPDATE on an aggregate, so lock the
    # highest existing revision row and derive the next monotonic version.
    cur.execute("""
        SELECT version FROM trading_universes
        WHERE universe_key = %s
        ORDER BY version DESC LIMIT 1 FOR UPDATE
    """, (versions.CUSTOM_UNIVERSE_KEY,))
    row = cur.fetchone()
    return int(row[0]) + 1 if row else 1


def _insert_snapshot(
    cur: Any, *, version: int, status: str, actor: str, notes: Optional[str],
    members: Sequence[Mapping[str, Any]], exact_hash: str,
    effective_from: Any = None,
) -> int:
    cur.execute("""
        INSERT INTO trading_universes (
            universe_key, display_name, version, status, effective_from,
            created_by, notes, exact_set_hash, enabled_symbol_count
        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
    """, (
        versions.CUSTOM_UNIVERSE_KEY, versions.DISPLAY_NAME, version, status,
        effective_from, actor, notes, exact_hash,
        sum(1 for member in members if member.get("enabled", True)),
    ))
    universe_id = int(cur.fetchone()[0])
    for member in members:
        symbol = versions.normalize_symbol(member["symbol"])
        enabled = bool(member.get("enabled", True))
        cur.execute("""
            INSERT INTO trading_universe_members (
                universe_id, symbol, exchange, sector, instrument_token,
                mapping_status, enabled, added_by, removed_at, removed_by, notes
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s,
                      CASE WHEN %s THEN NULL ELSE NOW() END,
                      CASE WHEN %s THEN NULL ELSE %s END, %s)
        """, (
            universe_id, symbol, member.get("exchange") or "NSE",
            member.get("sector"), member.get("instrument_token"),
            member.get("mapping_status") or "UNVERIFIED", enabled, actor,
            enabled, enabled, actor, member.get("notes"),
        ))
        cur.execute(f"""
            INSERT INTO {_DETAILS_TABLE} (universe_id, symbol, metadata, created_by)
            VALUES (%s, %s, %s, %s)
        """, (
            universe_id, symbol, json.dumps(_metadata_from_member(member)), actor,
        ))
    return universe_id


def create_draft(
    *, actor: str = ACTOR, correlation_id: Optional[str] = None,
    base_version: Optional[int] = None, notes: Optional[str] = None,
) -> Dict[str, Any]:
    correlation_id = correlation_id or str(uuid.uuid4())
    if not versions._db_available():
        return {"success": False, "error": "db_unavailable"}
    try:
        with versions._connect() as conn:
            _ensure_management_schema(conn)
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("task947-draft",))
                # The advisory lock serializes create/edit workflows; the
                # partial unique index is the database backstop. Check within
                # this transaction so callers receive a clear recoverable
                # response rather than making the editable revision ambiguous.
                cur.execute("""
                    SELECT version FROM trading_universes
                    WHERE universe_key = %s AND status = 'DRAFT'
                    ORDER BY version DESC LIMIT 1 FOR UPDATE
                """, (versions.CUSTOM_UNIVERSE_KEY,))
                open_draft = cur.fetchone()
                if open_draft:
                    return {
                        "success": False,
                        "error": "draft_already_open",
                        "draft_version": int(open_draft[0]),
                    }
                base = get_revision_view(version=base_version) if base_version is not None else None
                if base_version is None:
                    cur.execute("""
                        SELECT id, universe_key, display_name, version, status,
                               effective_from, effective_until, created_at, created_by,
                               approved_at, approved_by, notes, exact_set_hash,
                               enabled_symbol_count, source_id
                        FROM trading_universes
                        WHERE universe_key = %s AND status = 'ACTIVE'
                        ORDER BY version DESC LIMIT 1
                    """, (versions.CUSTOM_UNIVERSE_KEY,))
                    row = cur.fetchone()
                    base = _revision_from_row(row) if row else None
                    if base:
                        base = _revision_with_members(cur, base)
                if not base:
                    return {"success": False, "error": "base_revision_not_found"}
                members = [dict(member) for member in base.get("members", [])]
                next_version = _next_version(cur)
                enabled_symbols = [member["symbol"] for member in members if member.get("enabled")]
                revision_id = _insert_snapshot(
                    cur, version=next_version, status="DRAFT", actor=actor,
                    notes=notes, members=members,
                    exact_hash=versions.exact_set_hash(enabled_symbols),
                )
                _audit_in_tx(
                    cur, action="DRAFT_CREATED", actor=actor,
                    correlation_id=correlation_id, old_version=base["version"],
                    new_version=next_version, notes=notes,
                )
        return {"success": True, "version": next_version, "revision_id": revision_id}
    except Exception as exc:
        logger.warning("universe_management.create_draft: %s", exc)
        return {"success": False, "error": str(exc)[:300]}


def edit_draft(
    *, version: int, operation: str, actor: str = ACTOR,
    correlation_id: Optional[str] = None, expected_hash: Optional[str] = None,
    member: Optional[Mapping[str, Any]] = None,
    symbol: Optional[str] = None, metadata: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    correlation_id = correlation_id or str(uuid.uuid4())
    operation = str(operation or "").strip().lower()
    if operation not in {"add", "remove", "restore", "update"}:
        return {"success": False, "error": "operation must be add, remove, restore, or update"}
    draft = get_revision_view(version=version)
    if not draft:
        return {"success": False, "error": "revision_not_found"}
    if draft["status"] != "DRAFT":
        return {"success": False, "error": "draft_only_edit"}
    if expected_hash and expected_hash != draft["exact_set_hash"]:
        return {"success": False, "error": "stale_revision", "current_hash": draft["exact_set_hash"]}
    members = [dict(item) for item in draft.get("members", [])]
    by_symbol = {str(item["symbol"]).upper(): item for item in members}
    previous_by_symbol = deepcopy(by_symbol)
    try:
        target = versions.normalize_symbol(symbol or (member or {}).get("symbol"))
    except ValueError as exc:
        return {"success": False, "error": "invalid_normalized_symbol", "detail": str(exc)}

    if operation == "add":
        if target in by_symbol:
            return {"success": False, "error": "duplicate_symbol", "symbol": target}
        candidate = _normalise_member({**dict(member or {}), "symbol": target})
        # A client-supplied token/status is never a trusted Kite mapping. Only
        # a current cache validation below can bind those fields.
        candidate["instrument_token"] = None
        candidate["mapping_status"] = "UNVERIFIED"
        members.append(candidate)
    elif operation == "remove":
        if target not in by_symbol:
            return {"success": False, "error": "symbol_not_found", "symbol": target}
        by_symbol[target]["enabled"] = False
        by_symbol[target]["mapping_status"] = "REMOVED"
    elif operation == "restore":
        if target not in by_symbol:
            return {"success": False, "error": "symbol_not_found", "symbol": target}
        by_symbol[target]["enabled"] = True
        by_symbol[target]["instrument_token"] = None
        by_symbol[target]["mapping_status"] = "UNVERIFIED"
    else:
        if target not in by_symbol:
            return {"success": False, "error": "symbol_not_found", "symbol": target}
        merged = {**_metadata_from_member(by_symbol[target]), **dict(metadata or {})}
        by_symbol[target]["metadata"] = merged
        by_symbol[target]["sector"] = merged.get("sector", by_symbol[target].get("sector"))
        by_symbol[target]["instrument_token"] = None
        by_symbol[target]["mapping_status"] = "UNVERIFIED"
    if operation in {"remove", "restore"}:
        members = list(by_symbol.values())

    enabled = [item for item in members if item.get("enabled", True)]
    instruments, reference = _instrument_reference()
    validation = validate_members(
        [_member_for_validation(item) for item in enabled],
        instruments,
        instrument_cache_fresh=reference["is_fresh"],
    )
    if operation in {"add", "restore", "update"}:
        target_member = next(
            (item for item in members if str(item.get("symbol")).upper() == target),
            None,
        )
        target_validation = validate_members(
            [_member_for_validation(target_member)] if target_member else [],
            instruments,
            instrument_cache_fresh=reference["is_fresh"],
        )
        if not target_validation["valid"]:
            return {
                "success": False, "error": "member_validation_failed",
                "validation": target_validation,
            }
        binding = target_validation["mapping_bindings"][target]
        target_member.update({
            "exchange": binding["exchange"],
            "instrument_token": binding["instrument_token"],
            "mapping_status": binding["mapping_status"],
        })
        target_member["metadata"] = {
            **_metadata_from_member(target_member),
            "kite_symbol": binding["kite_symbol"],
        }
    successor_by_symbol = {
        str(item["symbol"]).upper(): item for item in members
    }
    if operation == "add" and not validation["valid"]:
        # A new member must not make an otherwise valid draft invalid. Existing
        # baseline rows may be completed through explicit metadata updates.
        return {
            "success": False, "error": "member_validation_failed",
            "validation": validation,
        }

    if not versions._db_available():
        return {"success": False, "error": "db_unavailable"}
    try:
        with versions._connect() as conn:
            _ensure_management_schema(conn)
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("task947-draft",))
                # Re-read under the lock so two operators cannot both edit the
                # same optimistic version.
                cur.execute("""
                    SELECT status, exact_set_hash FROM trading_universes
                    WHERE universe_key = %s AND version = %s FOR UPDATE
                """, (versions.CUSTOM_UNIVERSE_KEY, version))
                current = cur.fetchone()
                if not current or current[0] != "DRAFT":
                    return {"success": False, "error": "draft_only_edit"}
                if expected_hash and current[1] != expected_hash:
                    return {"success": False, "error": "stale_revision", "current_hash": current[1]}
                # Cancel first so the database's single-DRAFT constraint
                # remains true throughout the successor transition. If the
                # insert fails, this transaction rolls the cancellation back.
                cur.execute("""
                    UPDATE trading_universes
                    SET status = 'CANCELLED'
                    WHERE universe_key = %s AND version = %s AND status = 'DRAFT'
                """, (versions.CUSTOM_UNIVERSE_KEY, version))
                if cur.rowcount != 1:
                    return {"success": False, "error": "draft_only_edit"}
                next_version = _next_version(cur)
                new_hash = versions.exact_set_hash([
                    item["symbol"] for item in members if item.get("enabled", True)
                ])
                new_id = _insert_snapshot(
                    cur, version=next_version, status="DRAFT", actor=actor,
                    notes=f"Successor of v{version}", members=members,
                    exact_hash=new_hash,
                )
                action = {
                    "add": "SYMBOL_ADDED", "remove": "SYMBOL_REMOVED",
                    "restore": "SYMBOL_RESTORED", "update": "SYMBOL_ADDED",
                }[operation]
                _audit_in_tx(
                    cur, action=action, actor=actor, correlation_id=correlation_id,
                    old_version=version, new_version=next_version, symbol=target,
                    old_value=previous_by_symbol.get(target),
                    new_value=successor_by_symbol.get(target),
                    change_type="METADATA_CHANGED" if operation == "update" else None,
                    notes="superseded_draft_cancelled",
                )
        return {
            "success": True, "version": next_version, "revision_id": new_id,
            "validation": validation,
        }
    except Exception as exc:
        logger.warning("universe_management.edit_draft: %s", exc)
        return {"success": False, "error": str(exc)[:300]}


def _cached_instruments() -> List[Dict[str, Any]]:
    try:
        from kite_instrument_cache import get_cached_instruments
        return get_cached_instruments()
    except Exception:
        return []


def _instrument_reference() -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    try:
        from kite_instrument_cache import cache_status, get_cached_instruments
        status = cache_status()
        instruments = get_cached_instruments()
        stable_rows = [
            {
                "symbol": str(item.get("symbol") or ""),
                "token": item.get("token"),
                "exchange": item.get("exchange"),
                "segment": item.get("segment"),
                "instrument_type": item.get("instrument_type"),
            }
            for item in instruments
        ]
        digest = hashlib.sha256(
            json.dumps(stable_rows, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        return instruments, {
            "date": status.get("date"),
            "fetched_at": status.get("fetched_at"),
            "is_fresh": bool(status.get("is_fresh")),
            "count": len(instruments),
            "exact_set_hash": digest,
        }
    except Exception:
        return [], {
            "date": None, "fetched_at": None, "is_fresh": False,
            "count": 0, "exact_set_hash": None,
        }


def validate_draft(
    *, version: int, actor: str = ACTOR, correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    correlation_id = correlation_id or str(uuid.uuid4())
    revision = get_revision_view(version=version)
    if not revision:
        return {"success": False, "error": "revision_not_found"}
    enabled = [_member_for_validation(item) for item in revision.get("members", []) if item.get("enabled")]
    instruments, reference = _instrument_reference()
    evidence = validate_members(
        enabled,
        instruments,
        instrument_cache_fresh=reference["is_fresh"],
        require_persisted_binding=True,
    )
    evidence.update({
        "success": True,
        "version": version,
        "revision_id": revision["id"],
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "activation_lock": ACTIVATION_LOCKED,
        "instrument_reference": reference,
    })
    if not versions._db_available():
        return {"success": False, "error": "db_unavailable", "validation": evidence}
    try:
        with versions._connect() as conn:
            _ensure_management_schema(conn)
            with conn.cursor() as cur:
                cur.execute(f"""
                    INSERT INTO {_VALIDATION_TABLE}
                        (universe_id, result, checked_by, correlation_id, evidence)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id, checked_at
                """, (
                    revision["id"], evidence["status"], actor, correlation_id,
                    json.dumps(evidence),
                ))
                validation_id, checked_at = cur.fetchone()
                _audit_in_tx(
                    cur, action="VALIDATION_RUN", actor=actor,
                    correlation_id=correlation_id, new_version=version,
                    new_value=evidence, notes=evidence["status"],
                )
        evidence["validation_id"] = validation_id
        evidence["checked_at"] = _json(checked_at)
        return {"success": True, "validation": evidence}
    except Exception as exc:
        return {"success": False, "error": str(exc)[:300], "validation": evidence}


def latest_validation(version: int) -> Optional[Dict[str, Any]]:
    if not versions._db_available():
        return None
    revision = versions.get_revision(version=version)
    if not revision:
        return None
    try:
        with versions._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT id, result, checked_at, checked_by, correlation_id, evidence
                    FROM {_VALIDATION_TABLE}
                    WHERE universe_id = %s
                    ORDER BY checked_at DESC, id DESC LIMIT 1
                """, (revision["id"],))
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "id": row[0], "result": row[1], "checked_at": _json(row[2]),
                    "checked_by": row[3], "correlation_id": row[4],
                    "evidence": row[5] or {},
                }
    except Exception:
        return None


def mapping_coverage(version: int) -> Dict[str, Any]:
    revision = get_revision_view(version=version)
    if not revision:
        return {"success": False, "error": "revision_not_found"}
    enabled = [item for item in revision.get("members", []) if item.get("enabled")]
    latest = latest_validation(version)
    latest_evidence = (latest or {}).get("evidence", {})
    bindings = (
        latest_evidence.get("mapping_bindings", {})
        if isinstance(latest_evidence, dict) else {}
    )
    mapped = [
        item for item in enabled
        if (
            item.get("mapping_status") == "MAPPED"
            and item.get("instrument_token")
            and (
                not bindings
                or (
                    bindings.get(item["symbol"], {}).get("instrument_token") == item.get("instrument_token")
                    and bindings.get(item["symbol"], {}).get("exchange") == item.get("exchange")
                )
            )
        )
    ]
    validation_coverage = (
        latest_evidence.get("mapping_coverage")
        if isinstance(latest_evidence, dict) else None
    )
    validated_complete = bool(
        isinstance(validation_coverage, dict) and validation_coverage.get("complete")
    )
    return {
        "success": True, "version": version, "total": len(enabled),
        "mapped": len(mapped),
        "unmapped": [item["symbol"] for item in enabled if item not in mapped],
        "percent": round(len(mapped) / len(enabled) * 100, 2) if enabled else 0.0,
        "complete": bool(enabled) and len(mapped) == len(enabled),
        "latest_validation": latest,
        "validated_mapping_coverage": validation_coverage,
        "activation_mapping_complete": validated_complete,
    }


def diff_versions(left_version: int, right_version: int) -> Dict[str, Any]:
    left = get_revision_view(version=left_version)
    right = get_revision_view(version=right_version)
    if not left or not right:
        return {"success": False, "error": "revision_not_found"}
    lm = {str(item["symbol"]).upper(): item for item in left["members"] if item.get("enabled")}
    rm = {str(item["symbol"]).upper(): item for item in right["members"] if item.get("enabled")}
    added = sorted(set(rm) - set(lm))
    removed = sorted(set(lm) - set(rm))
    changed = sorted(
        symbol for symbol in set(lm) & set(rm)
        if _metadata_from_member(lm[symbol]) != _metadata_from_member(rm[symbol])
        or lm[symbol].get("exchange") != rm[symbol].get("exchange")
    )
    return {
        "success": True, "left_version": left_version, "right_version": right_version,
        "added": added, "removed": removed, "changed": changed,
        "unchanged": sorted(set(lm) & set(rm) - set(changed)),
    }


def audit_history(limit: int = 200) -> Dict[str, Any]:
    if not versions._db_available():
        return {"success": False, "error": "db_unavailable", "events": []}
    limit = max(1, min(int(limit), 500))
    try:
        with versions._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, occurred_at, actor, action, universe_key,
                           old_version, new_version, symbol, change_type,
                           old_value, new_value, notes, correlation_id, approval_state
                    FROM trading_universe_audit_events
                    WHERE universe_key = %s
                    ORDER BY occurred_at DESC, id DESC LIMIT %s
                """, (versions.CUSTOM_UNIVERSE_KEY, limit))
                cols = (
                    "id", "occurred_at", "actor", "action", "universe_key",
                    "old_version", "new_version", "symbol", "change_type",
                    "old_value", "new_value", "notes", "correlation_id",
                    "approval_state",
                )
                return {
                    "success": True,
                    "events": [
                        {key: _json(value) for key, value in zip(cols, row)}
                        for row in cur.fetchall()
                    ],
                }
    except Exception as exc:
        return {"success": False, "error": str(exc)[:300], "events": []}


def _next_session_open() -> str:
    from market_hours import is_trading_day
    now = datetime.now(IST)
    candidate = now.date()
    if now.time() >= time(9, 15) or not is_trading_day(candidate):
        candidate += timedelta(days=1)
    while not is_trading_day(candidate):
        candidate += timedelta(days=1)
    return datetime.combine(candidate, time(9, 15), tzinfo=IST).astimezone(timezone.utc).isoformat()


def request_activation(
    *, version: int, confirmation: str, expected_confirmation: str,
    actor: str = ACTOR, correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    correlation_id = correlation_id or str(uuid.uuid4())
    expected = expected_confirmation
    if confirmation != expected:
        return {
            "success": False, "error": "typed_confirmation_mismatch",
            "expected_format": expected,
        }
    validation = validate_draft(version=version, actor=actor, correlation_id=correlation_id)
    if not validation.get("success") or validation.get("validation", {}).get("status") != "VALIDATION_PASS":
        return {
            "success": False, "error": "fresh_validation_required",
            "validation": validation.get("validation"),
        }
    effective_from = _next_session_open()
    if not versions._db_available():
        return {"success": False, "error": "db_unavailable"}
    try:
        with versions._connect() as conn:
            _ensure_management_schema(conn)
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT status FROM trading_universes
                    WHERE universe_key = %s AND version = %s FOR UPDATE
                """, (versions.CUSTOM_UNIVERSE_KEY, version))
                row = cur.fetchone()
                if not row or row[0] != "DRAFT":
                    return {"success": False, "error": "draft_only_activation"}
                _audit_in_tx(
                    cur, action="ACTIVATION_REQUESTED", actor=actor,
                    correlation_id=correlation_id, new_version=version,
                    notes=ACTIVATION_LOCK_REASON if ACTIVATION_LOCKED else None,
                    approval_state="LOCKED" if ACTIVATION_LOCKED else "PENDING",
                )
                if ACTIVATION_LOCKED:
                    return {
                        "success": False, "error": "activation_locked",
                        "status": "LOCKED", "lock_reason": ACTIVATION_LOCK_REASON,
                        "version": version, "effective_from": effective_from,
                    }
                cur.execute("""
                    UPDATE trading_universes
                    SET status = 'PENDING_ACTIVATION', effective_from = %s
                    WHERE universe_key = %s AND version = %s
                """, (effective_from, versions.CUSTOM_UNIVERSE_KEY, version))
        return {
            "success": True, "status": "PENDING_ACTIVATION",
            "version": version, "effective_from": effective_from,
        }
    except Exception as exc:
        return {"success": False, "error": str(exc)[:300]}


def activate(
    *, version: int, confirmation: str, expected_confirmation: str,
    actor: str = ACTOR, correlation_id: Optional[str] = None,
) -> Dict[str, Any]:
    correlation_id = correlation_id or str(uuid.uuid4())
    if confirmation != expected_confirmation:
        return {"success": False, "error": "typed_confirmation_mismatch"}
    if ACTIVATION_LOCKED:
        return {
            "success": False, "error": "activation_locked", "status": "LOCKED",
            "lock_reason": ACTIVATION_LOCK_REASON,
        }
    # This branch is intentionally unreachable in the initial release. Keep
    # the checks here so changing the release flag cannot skip revalidation.
    validation = validate_draft(version=version, actor=actor, correlation_id=correlation_id)
    if validation.get("validation", {}).get("status") != "VALIDATION_PASS":
        return {"success": False, "error": "fresh_validation_required"}
    return {"success": False, "error": "activation_disabled"}
