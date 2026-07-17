"""
signals_store.py — Durable persistence for intelligence scan signals.

Stores the latest enriched signal list in PostgreSQL when DATABASE_URL is set.

Behaviour:
- With DATABASE_URL: Postgres is authoritative. DB failures raise so callers
  receive an explicit error; no silent degradation to ephemeral files.
  Local warm-cache files are written AFTER a successful DB write to speed up
  same-instance reads but are never the primary write target.
- Without DATABASE_URL (local dev / no DB): falls back to JSON files.

Schema auto-created on first use.
Paper trading / research only — no live orders anywhere in this module.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, List, Optional

logger = logging.getLogger(__name__)

_DIR = os.path.dirname(os.path.abspath(__file__))

# Warm-cache / local-dev file paths (one per signal type)
_PATHS = {
    "signals":          os.path.join(_DIR, "signals_cache.json"),
    "ai_decisions":     os.path.join(_DIR, "ai_decisions_cache.json"),
    "opportunity_scan": os.path.join(_DIR, "opportunity_cache.json"),
    "market_context":   os.path.join(_DIR, "market_context_cache.json"),
}

_SCHEMA_READY = False


# ── Connection helpers ────────────────────────────────────────────────────────

def db_available() -> bool:
    return bool(os.environ.get("DATABASE_URL"))


def _connect():
    import psycopg2
    return psycopg2.connect(os.environ["DATABASE_URL"], connect_timeout=10)


def _ensure_schema(conn) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS signals_cache (
                key        TEXT PRIMARY KEY,
                payload    JSONB NOT NULL DEFAULT '[]',
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
    conn.commit()
    _SCHEMA_READY = True


# ── Generic save / load ───────────────────────────────────────────────────────

def _save(key: str, data: Any) -> None:
    """
    Persist data under `key`.

    With DATABASE_URL: writes to Postgres (authoritative). Warm-cache file is
    written AFTER a successful DB write. Raises on DB failure.
    Without DATABASE_URL: writes to the local JSON file only.
    """
    fallback_path = _PATHS.get(key)

    if not db_available():
        if fallback_path:
            _write_json(fallback_path, data)
        return

    conn = _connect()  # raises on connection failure
    try:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO signals_cache (key, payload, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (key) DO UPDATE SET
                    payload    = EXCLUDED.payload,
                    updated_at = NOW()
                """,
                (key, json.dumps(data, default=str)),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise  # surface DB write failure
    finally:
        conn.close()

    # Write warm-cache AFTER successful DB commit (read optimisation only)
    if fallback_path:
        _write_json(fallback_path, data)


def _load(key: str) -> Optional[Any]:
    """
    Load data for `key`.

    With DATABASE_URL: reads from Postgres; raises on DB failure.
    Without DATABASE_URL: reads from the local JSON file.
    """
    fallback_path = _PATHS.get(key)

    if db_available():
        conn = _connect()  # raises on connection failure
        try:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT payload FROM signals_cache WHERE key = %s", (key,)
                )
                row = cur.fetchone()
        finally:
            conn.close()

        if row and row[0] is not None:
            payload = row[0]
            if isinstance(payload, str):
                payload = json.loads(payload)
            # Refresh warm-cache for fast same-instance reads
            if fallback_path:
                _write_json(fallback_path, payload)
            return payload
        return None  # key not in DB yet

    # Local-dev fallback
    if fallback_path:
        return _read_json(fallback_path)
    return None


# ── File helpers ──────────────────────────────────────────────────────────────

def _read_json(path: str) -> Optional[Any]:
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return None


def _write_json(path: str, data: Any) -> None:
    try:
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)
    except Exception as exc:
        logger.warning("signals_store: could not write warm-cache %s: %s", path, exc)


# ── Public helpers ────────────────────────────────────────────────────────────

def save_signals(signals: List[Any]) -> None:
    _save("signals", signals)


def load_signals() -> Optional[List[Any]]:
    return _load("signals")


def save_ai_decisions(decisions: List[Any]) -> None:
    _save("ai_decisions", decisions)


def load_ai_decisions() -> Optional[List[Any]]:
    return _load("ai_decisions")


def save_opportunity_scan(opportunities: List[Any]) -> None:
    _save("opportunity_scan", opportunities)


def load_opportunity_scan() -> Optional[List[Any]]:
    return _load("opportunity_scan")


def save_market_context(context: Any) -> None:
    _save("market_context", context)


def load_market_context() -> Optional[Any]:
    return _load("market_context")
