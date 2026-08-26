"""Durable, advisory-only incidents for degraded execution-grade quote authority.

The only input to this module is the canonical market-data health contract.
It never fetches market data, touches provider configuration, or changes a
readiness/execution decision.  PostgreSQL is required for durability; when it
is unavailable the caller gets an explicit unavailable result rather than a
process-local approximation.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from scan_state_store import _connect, db_available

_SCHEMA_READY = False
_ACTIVE_KIND = "KITE_CURRENT_PRICE_AUTHORITY"
_VALID_SEVERITIES = {"WARNING", "HIGH", "CRITICAL"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: Any) -> Optional[str]:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value) if value is not None else None


def _severity(health: Dict[str, Any]) -> str:
    """Deterministic severity with an optional operator-configured override."""
    override = str(os.environ.get("MARKET_DATA_FALLBACK_INCIDENT_SEVERITY", "")).upper()
    if override in _VALID_SEVERITIES:
        return override
    active = max(0, int(health.get("active_universe_count") or 0))
    unavailable = int(health.get("symbols_unavailable") or 0)
    synthetic = int(health.get("symbols_synthetic") or 0)
    stale = int(health.get("symbols_stale") or 0)
    provider = str(health.get("current_quote_provider") or "UNAVAILABLE_NOT_PROVEN").upper()
    if provider == "UNAVAILABLE_NOT_PROVEN" or (active > 0 and unavailable + synthetic >= active):
        return "CRITICAL"
    if provider == "MIXED" or unavailable or synthetic or stale:
        return "HIGH"
    return "WARNING"


def classify_health(health: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Classify only execution-grade authority, never historical OHLCV labels."""
    health = health if isinstance(health, dict) else {}
    provider = str(health.get("current_quote_provider") or "UNAVAILABLE_NOT_PROVEN").upper()
    freshness = str(health.get("current_quote_freshness") or "UNAVAILABLE_NOT_PROVEN").upper()
    active = int(health.get("active_universe_count") or 0)
    unhealthy = sum(int(health.get(key) or 0) for key in (
        "symbols_fallback", "symbols_stale", "symbols_unavailable", "symbols_synthetic",
    ))
    # Recovery needs a complete, fresh execution-grade Kite observation.  A
    # healthy historical OHLCV label or a connected session is deliberately
    # insufficient evidence, and a closed-market last-known quote cannot close
    # a live fallback episode.
    recovered_proof = bool(
        active > 0
        and provider == "ZERODHA_KITE"
        and freshness == "LIVE"
        and int(health.get("symbols_on_kite") or 0) == active
        and unhealthy == 0
        and health.get("kite_quote_timestamps_fresh") is True
        and health.get("market_timestamp_fresh") is True
    )
    affected = not recovered_proof
    return {
        "affected": affected,
        "provider": provider,
        "freshness": freshness,
        "severity": _severity(health) if affected else None,
    }


def _ensure_schema(conn: Any) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS market_data_fallback_incidents (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                status TEXT NOT NULL CHECK (status IN ('ACTIVE', 'RECOVERED')),
                severity TEXT NOT NULL,
                started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                last_detected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                recovered_at TIMESTAMPTZ,
                latest_scan_id TEXT,
                active_universe_count INTEGER NOT NULL DEFAULT 0,
                symbols_on_kite INTEGER NOT NULL DEFAULT 0,
                symbols_fallback INTEGER NOT NULL DEFAULT 0,
                symbols_stale INTEGER NOT NULL DEFAULT 0,
                symbols_unavailable INTEGER NOT NULL DEFAULT 0,
                symbols_synthetic INTEGER NOT NULL DEFAULT 0,
                current_quote_provider TEXT NOT NULL,
                current_quote_freshness TEXT NOT NULL,
                detection_count INTEGER NOT NULL DEFAULT 1,
                evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
                recovery_summary TEXT
            )
            """
        )
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS market_data_fallback_incidents_one_active
            ON market_data_fallback_incidents (kind) WHERE status = 'ACTIVE'
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS market_data_fallback_incidents_history
            ON market_data_fallback_incidents (status, started_at DESC)
            """
        )
    conn.commit()
    _SCHEMA_READY = True


def _evidence(health: Dict[str, Any]) -> Dict[str, Any]:
    latest = health.get("latest_scan") if isinstance(health.get("latest_scan"), dict) else {}
    return {
        "market_timestamp": health.get("market_timestamp"),
        "market_timestamp_fresh": health.get("market_timestamp_fresh"),
        "kite_quote_timestamps_fresh": health.get("kite_quote_timestamps_fresh"),
        "invalid_live_quote_timestamp_symbols": health.get("invalid_live_quote_timestamp_symbols") or [],
        "scan_provenance_state": health.get("scan_provenance_state"),
        "trigger_origin": latest.get("trigger_origin"),
        "historical_ohlcv_provider": health.get("historical_ohlcv_provider"),
    }


def _values(health: Dict[str, Any], classification: Dict[str, Any]) -> tuple:
    latest = health.get("latest_scan") if isinstance(health.get("latest_scan"), dict) else {}
    return (
        classification["severity"],
        latest.get("scan_id"),
        int(health.get("active_universe_count") or 0),
        int(health.get("symbols_on_kite") or 0),
        int(health.get("symbols_fallback") or 0),
        int(health.get("symbols_stale") or 0),
        int(health.get("symbols_unavailable") or 0),
        int(health.get("symbols_synthetic") or 0),
        classification["provider"],
        classification["freshness"],
        json.dumps(_evidence(health)),
    )


def observe_health(health: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Open/update one active episode or recover it from a canonical health observation."""
    health = health if isinstance(health, dict) else {}
    classification = classify_health(health)
    if not db_available():
        return {"available": False, "reason": "DATABASE_URL is not configured", "classification": classification}
    conn = _connect()
    try:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            # Serialise the one-active-episode lifecycle across Autoscale workers.
            cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (_ACTIVE_KIND,))
            cur.execute(
                """
                SELECT id, latest_scan_id, detection_count FROM market_data_fallback_incidents
                WHERE kind = %s AND status = 'ACTIVE' FOR UPDATE
                """,
                (_ACTIVE_KIND,),
            )
            active = cur.fetchone()
            if classification["affected"]:
                values = _values(health, classification)
                if active:
                    # A poll of the same durable scan must not inflate detection_count.
                    increment = bool(values[1] and values[1] != active[1])
                    cur.execute(
                        """
                        UPDATE market_data_fallback_incidents SET
                            severity=%s, last_detected_at=NOW(), latest_scan_id=%s,
                            active_universe_count=%s, symbols_on_kite=%s, symbols_fallback=%s,
                            symbols_stale=%s, symbols_unavailable=%s, symbols_synthetic=%s,
                            current_quote_provider=%s, current_quote_freshness=%s,
                            detection_count=detection_count + %s, evidence=%s::jsonb
                        WHERE id=%s
                        """,
                        (*values[:10], 1 if increment else 0, values[10], active[0]),
                    )
                    incident_id = active[0]
                    action = "UPDATED"
                else:
                    incident_id = uuid.uuid4().hex
                    cur.execute(
                        """
                        INSERT INTO market_data_fallback_incidents (
                            id, kind, status, severity, latest_scan_id, active_universe_count,
                            symbols_on_kite, symbols_fallback, symbols_stale, symbols_unavailable,
                            symbols_synthetic, current_quote_provider, current_quote_freshness, evidence
                        ) VALUES (%s, %s, 'ACTIVE', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
                        """,
                        (incident_id, _ACTIVE_KIND, *values),
                    )
                    action = "OPENED"
            elif active:
                latest = health.get("latest_scan") if isinstance(health.get("latest_scan"), dict) else {}
                cur.execute(
                    """
                    UPDATE market_data_fallback_incidents SET
                        status='RECOVERED', recovered_at=NOW(), latest_scan_id=%s,
                        current_quote_provider=%s, current_quote_freshness=%s,
                        recovery_summary=%s, evidence=%s::jsonb
                    WHERE id=%s
                    """,
                    (
                        latest.get("scan_id"), classification["provider"], classification["freshness"],
                        "Recovered only after authoritative Zerodha Kite current-price coverage was healthy and fresh.",
                        json.dumps(_evidence(health)), active[0],
                    ),
                )
                incident_id, action = active[0], "RECOVERED"
            else:
                incident_id, action = None, "HEALTHY"
        conn.commit()
        return {"available": True, "id": incident_id, "action": action, "classification": classification}
    finally:
        conn.close()


def health_for_scan_snapshot(scan: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Build the canonical health contract for an already-persisted scan."""
    from config import get_active_intraday_universe
    from kite_instrument_cache import get_cached_instruments
    from kite_session_manager import cached_session_metadata
    from market_data_health import build_market_data_health
    from market_hours import market_status

    active_mode = get_active_intraday_universe().value
    current_universe = None
    instruments = get_cached_instruments()
    if active_mode == "CUSTOM_LOW_PRICE_SECTOR":
        from custom_universe_store import get_active_symbol_metadata, get_active_symbols
        current_universe = get_active_symbols()
        metadata = get_active_symbol_metadata()
        instruments = [
            {"symbol": symbol, "token": metadata.get(symbol, {}).get("instrument_token")}
            for symbol in current_universe
        ]
    health = build_market_data_health(
        scan if isinstance(scan, dict) else None,
        cached_session_metadata(),
        instruments,
        current_universe=current_universe,
        active_universe=active_mode,
        market_state=market_status().get("state"),
    )
    return health


def observe_scan_snapshot(scan: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Evaluate an already-persisted scan with the same health contract as health-v2."""
    return observe_health(health_for_scan_snapshot(scan))


def current_health() -> Dict[str, Any]:
    """Read current canonical evidence without starting a scan or fetching quotes."""
    from live_scan_engine import load_cached_scan
    return health_for_scan_snapshot(load_cached_scan())


def _row(row: Any) -> Dict[str, Any]:
    duration = None
    if row[2] and row[3]:
        end = row[4] or _now()
        duration = max(0, round((end - row[2]).total_seconds()))
    return {
        "id": row[0], "status": row[1], "started_at": _iso(row[2]),
        "last_detected_at": _iso(row[3]), "recovered_at": _iso(row[4]),
        "severity": row[5], "latest_scan_id": row[6],
        "active_universe_count": row[7], "symbols_on_kite": row[8],
        "symbols_fallback": row[9], "symbols_stale": row[10],
        "symbols_unavailable": row[11], "symbols_synthetic": row[12],
        "current_quote_provider": row[13], "current_quote_freshness": row[14],
        "detection_count": row[15], "evidence": row[16] or {},
        "recovery_summary": row[17], "duration_s": duration, "read_only": True,
    }


_SELECT = """
SELECT id, status, started_at, last_detected_at, recovered_at, severity, latest_scan_id,
       active_universe_count, symbols_on_kite, symbols_fallback, symbols_stale,
       symbols_unavailable, symbols_synthetic, current_quote_provider,
       current_quote_freshness, detection_count, evidence, recovery_summary
FROM market_data_fallback_incidents
"""


def list_incidents(status: Optional[str] = None, severity: Optional[str] = None, limit: int = 100) -> Dict[str, Any]:
    if not db_available():
        return {"incidents": [], "total": 0, "storage_available": False, "read_only": True}
    conn = _connect()
    try:
        _ensure_schema(conn)
        where: List[str] = []
        args: List[Any] = []
        if status in {"ACTIVE", "RECOVERED"}:
            where.append("status = %s"); args.append(status)
        if severity in _VALID_SEVERITIES:
            where.append("severity = %s"); args.append(severity)
        clause = f" WHERE {' AND '.join(where)}" if where else ""
        with conn.cursor() as cur:
            cur.execute(f"{_SELECT}{clause} ORDER BY started_at DESC LIMIT %s", (*args, max(1, min(int(limit), 500))))
            rows = cur.fetchall()
        return {"incidents": [_row(row) for row in rows], "total": len(rows), "storage_available": True, "read_only": True}
    finally:
        conn.close()


def get_incident(incident_id: str) -> Dict[str, Any]:
    if not db_available():
        return {"incident": None, "storage_available": False, "read_only": True}
    conn = _connect()
    try:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(f"{_SELECT} WHERE id = %s", (incident_id,))
            row = cur.fetchone()
        return {"incident": _row(row) if row else None, "storage_available": True, "read_only": True}
    finally:
        conn.close()