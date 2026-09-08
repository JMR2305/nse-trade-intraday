"""Pinned, versioned runtime universe authority.

Runtime scanners must never read a mutable watchlist or master membership
directly.  This module resolves one immutable version for the current natural
IST session and persists that choice before any collection or scan begins.

It is intentionally a read/claim boundary only: it never changes a universe
revision, activates a revision, or changes trading behaviour.
"""
from __future__ import annotations

from datetime import datetime, time, timezone
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

import universe_version_store as versions

_IST = ZoneInfo("Asia/Kolkata")
_SESSION_START = time(9, 0)


class RuntimeUniverseUnavailable(RuntimeError):
    """The durable universe authority cannot safely provide one exact set."""


def _session_clock(now: Optional[datetime] = None) -> tuple[str, datetime]:
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=timezone.utc)
    local = instant.astimezone(_IST)
    session_date = local.date().isoformat()
    session_start = datetime.combine(local.date(), _SESSION_START, tzinfo=_IST)
    return session_date, session_start.astimezone(timezone.utc)


def _compact(row: Dict[str, Any]) -> Dict[str, Any]:
    symbols = versions.normalize_symbols(row.get("enabled_symbols") or row.get("symbols") or [])
    expected_hash = versions.exact_set_hash(symbols)
    if not symbols:
        raise RuntimeUniverseUnavailable("Pinned universe has no enabled symbols")
    if int(row.get("symbol_count") or 0) != len(symbols):
        raise RuntimeUniverseUnavailable("Pinned universe symbol count does not match exact set")
    if str(row.get("exact_set_hash") or "") != expected_hash:
        raise RuntimeUniverseUnavailable("Pinned universe exact-set hash does not match symbols")
    return {
        "natural_session": str(row["natural_session"]),
        "universe_key": str(row["universe_key"]),
        "universe_id": int(row["universe_id"]),
        "version": int(row["version"]),
        "enabled_symbols": symbols,
        "symbol_count": len(symbols),
        "exact_set_hash": expected_hash,
        "effective_from": row.get("effective_from"),
        "pinned_at": row.get("pinned_at"),
    }


def provenance(context: Dict[str, Any], *, include_symbols: bool = True) -> Dict[str, Any]:
    """Return a JSON-safe immutable identity envelope for another record."""
    result = {
        "natural_session": context.get("natural_session"),
        "universe_key": context.get("universe_key"),
        "universe_id": context.get("universe_id"),
        "universe_version": context.get("version"),
        "universe_symbol_count": context.get("symbol_count"),
        "universe_set_hash": context.get("exact_set_hash"),
    }
    if include_symbols:
        result["universe_symbols"] = list(context.get("enabled_symbols") or [])
    return result


def _load_pin(conn: Any, session_date: str) -> Optional[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT natural_session, universe_key, universe_id, universe_version,
                   universe_symbols, universe_symbol_count, universe_set_hash,
                   effective_from, pinned_at
            FROM runtime_universe_session_pins
            WHERE natural_session = %s
            """,
            (session_date,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return {
        "natural_session": row[0],
        "universe_key": row[1],
        "universe_id": row[2],
        "version": row[3],
        "enabled_symbols": row[4] or [],
        "symbol_count": row[5],
        "exact_set_hash": row[6],
        "effective_from": row[7].isoformat() if hasattr(row[7], "isoformat") else row[7],
        "pinned_at": row[8].isoformat() if hasattr(row[8], "isoformat") else row[8],
    }


def _configured_key() -> str:
    try:
        import config
        return config.get_active_intraday_universe_strict().value
    except Exception as exc:
        raise RuntimeUniverseUnavailable(
            f"Durable active-universe selection is unavailable: {exc}"
        ) from exc


def _configured_key_at_session_boundary(conn: Any, effective_at: datetime) -> str:
    """Refuse an unpinned session if a non-default selector changed after 09:00.

    The current settings table stores only its latest value, not a revision
    history.  A post-boundary custom-mode update therefore has no auditable
    way to establish which key was selected at 09:00, so it must not become
    the first session claim.  The static NIFTY default is separately recorded
    as an immutable baseline and remains safe to resolve.
    """
    key = _configured_key()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT data->>'active_intraday_universe', updated_at
                FROM phase20_settings WHERE id = 1
                """
            )
            row = cur.fetchone()
        if not isinstance(row, (tuple, list)) or len(row) < 2:
            return key
        selected, updated_at = row[0], row[1]
        if (
            str(selected or "").upper() in ("NIFTY_50", "CUSTOM_LOW_PRICE_SECTOR")
            and isinstance(updated_at, datetime)
            and updated_at.astimezone(timezone.utc) > effective_at
        ):
            raise RuntimeUniverseUnavailable(
                "Active universe selection changed after the 09:00 IST "
                "session boundary before a durable session pin was claimed"
            )
    except RuntimeUniverseUnavailable:
        raise
    except Exception:
        # The settings row is not the authority itself; absence during a
        # fresh default deployment is allowed because NIFTY has its immutable
        # built-in baseline.  Non-default selection remains fail-closed above.
        pass
    return key


def resolve_active_universe(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Return the exact durable universe pinned for the server's IST session.

    The first resolver call in a natural session claims a revision effective at
    that session's 09:00 IST boundary.  Later calls return the same stored
    identity even if an operator schedules a future revision or changes the
    selected universe mode during the session.
    """
    session_date, effective_at = _session_clock(now)
    if not versions._db_available():
        raise RuntimeUniverseUnavailable("Durable versioned universe store is unavailable")

    try:
        with versions._connect() as conn:
            # The version authority owns the additive pin-table bootstrap so a
            # fresh durable deployment can make its first safe session claim.
            versions._ensure_schema(conn)
            versions.ensure_builtin_nifty_baseline(conn)
            existing = _load_pin(conn, session_date)
            if existing:
                return _compact(existing)

            universe_key = _configured_key_at_session_boundary(conn, effective_at)
            resolved = versions.resolve_enabled_symbols(
                universe_key=universe_key,
                effective_at=effective_at,
            )
            if not resolved.get("success"):
                raise RuntimeUniverseUnavailable(
                    f"Effective universe {universe_key} is unavailable: "
                    f"{resolved.get('error') or 'unknown error'}"
                )
            symbols = versions.normalize_symbols(resolved.get("symbols") or [])
            if not symbols:
                raise RuntimeUniverseUnavailable(
                    f"Effective universe {universe_key} has no enabled symbols"
                )
            if int(resolved.get("symbol_count") or 0) != len(symbols):
                raise RuntimeUniverseUnavailable(
                    "Effective universe count does not match its exact symbol set"
                )
            if resolved.get("exact_set_hash") != versions.exact_set_hash(symbols):
                raise RuntimeUniverseUnavailable(
                    "Effective universe exact-set hash does not match its symbols"
                )

            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO runtime_universe_session_pins (
                        natural_session, universe_key, universe_id, universe_version,
                        universe_symbols, universe_symbol_count, universe_set_hash,
                        effective_from
                    ) VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s,%s)
                    ON CONFLICT (natural_session) DO NOTHING
                    """,
                    (
                        session_date, resolved["universe_key"], resolved["universe_id"],
                        resolved["version"], __import__("json").dumps(symbols),
                        len(symbols), resolved["exact_set_hash"],
                        resolved.get("effective_from"),
                    ),
                )
            pinned = _load_pin(conn, session_date)
            if not pinned:
                raise RuntimeUniverseUnavailable("Could not durably pin the active universe")
            return _compact(pinned)
    except RuntimeUniverseUnavailable:
        raise
    except Exception as exc:
        raise RuntimeUniverseUnavailable(
            f"Durable runtime universe pin is unavailable: {exc}"
        ) from exc