"""Durable master for the opt-in low-price IT/Infra/Bank scanner universe.

The table is deliberately separate from the NIFTY 50 company master. Rows are
kept even when excluded so operators can inspect the reason that a candidate
did not enter the active paper-trading universe.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from datetime import date, datetime, timezone
from typing import Any, Dict, Generator, List, Optional

logger = logging.getLogger(__name__)

TABLE = "custom_universe_master"
ALLOWED_UNIVERSE = "CUSTOM_LOW_PRICE_SECTOR"


def _db_available() -> bool:
    try:
        import psycopg2  # noqa: F401
        return bool(os.environ.get("DATABASE_URL"))
    except Exception:
        return False


@contextmanager
def _connect() -> Generator:
    import psycopg2
    conn = psycopg2.connect(os.environ["DATABASE_URL"])
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def ensure_table() -> bool:
    """Create the master lazily; callers can safely invoke this on every run."""
    if not _db_available():
        return False
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS {TABLE} (
                        symbol              TEXT PRIMARY KEY,
                        yahoo_symbol        TEXT,
                        kite_symbol         TEXT,
                        instrument_token    BIGINT,
                        company_name        TEXT,
                        sector              TEXT,
                        industry            TEXT,
                        allowed_universe    TEXT NOT NULL DEFAULT '{ALLOWED_UNIVERSE}',
                        price_min           NUMERIC(12,2),
                        price_max           NUMERIC(12,2),
                        is_active           BOOLEAN NOT NULL DEFAULT FALSE,
                        reason_included     TEXT,
                        reason_excluded     TEXT,
                        last_ltp            NUMERIC(14,4),
                        last_ltp_source     TEXT,
                        avg_volume_20d      NUMERIC(20,2),
                        avg_turnover_20d    NUMERIC(20,2),
                        ohlcv_available     BOOLEAN NOT NULL DEFAULT FALSE,
                        last_verified_at    TIMESTAMPTZ,
                        created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                """)
                cur.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_{TABLE}_active
                    ON {TABLE} (is_active, sector)
                """)
                # The master is current-state data. This append-only snapshot
                # table preserves membership changes for historical replay.
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS custom_universe_membership_history (
                        snapshot_at      TIMESTAMPTZ NOT NULL,
                        snapshot_date    DATE NOT NULL,
                        symbol           TEXT NOT NULL,
                        allowed_universe TEXT NOT NULL,
                        is_active        BOOLEAN NOT NULL,
                        sector           TEXT,
                        last_verified_at TIMESTAMPTZ,
                        PRIMARY KEY (snapshot_at, symbol)
                    )
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS idx_custom_universe_history_date
                    ON custom_universe_membership_history
                       (snapshot_date, snapshot_at, is_active)
                """)
        return True
    except Exception as exc:
        logger.warning("custom_universe_store.ensure_table: %s", exc)
        return False


_COLUMNS = [
    "symbol", "yahoo_symbol", "kite_symbol", "instrument_token",
    "company_name", "sector", "industry", "allowed_universe", "price_min",
    "price_max", "is_active", "reason_included", "reason_excluded",
    "last_ltp", "last_ltp_source", "avg_volume_20d", "avg_turnover_20d",
    "ohlcv_available", "last_verified_at", "created_at", "updated_at",
]

_ACTIVE_REQUIRED_FIELDS = (
    "sector", "company_name", "yahoo_symbol", "kite_symbol",
    "price_min", "price_max", "ohlcv_available",
)


def _serialise(row: Any) -> Dict[str, Any]:
    out = dict(zip(_COLUMNS, row))
    for key, value in list(out.items()):
        if hasattr(value, "isoformat"):
            out[key] = value.isoformat()
        elif key in {"last_ltp", "price_min", "price_max", "avg_volume_20d", "avg_turnover_20d"} and value is not None:
            out[key] = float(value)
    return out


def upsert_symbols(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Upsert included and excluded candidates atomically."""
    if not rows:
        return {"success": True, "upserted": 0}
    for index, raw in enumerate(rows):
        if not isinstance(raw, dict):
            return {
                "success": False,
                "upserted": 0,
                "error": f"row {index} must be an object",
            }
        if not str(raw.get("symbol") or "").upper().strip():
            # Preserve the historic behavior: malformed blank symbols are
            # ignored rather than turning a whole operator batch into a failure.
            continue
        if raw.get("is_active") is True:
            missing = [
                field for field in _ACTIVE_REQUIRED_FIELDS
                if field not in raw
                or raw.get(field) is None
                or (isinstance(raw.get(field), str) and not raw[field].strip())
            ]
            if missing:
                symbol = str(raw.get("symbol") or "").strip().upper()
                label = f" for {symbol}" if symbol else ""
                return {
                    "success": False,
                    "upserted": 0,
                    "error": (
                        f"active row {index}{label} must include non-null: "
                        f"{', '.join(missing)}"
                    ),
                }
    if not ensure_table():
        return {"success": False, "upserted": 0, "error": "db_unavailable"}
    values = []
    for raw in rows:
        symbol = str(raw.get("symbol") or "").upper().strip()
        if not symbol:
            continue
        values.append((
            symbol, raw.get("yahoo_symbol"),
            raw.get("kite_symbol"), raw.get("instrument_token"),
            raw.get("company_name"), raw.get("sector"), raw.get("industry"),
            raw.get("allowed_universe") or ALLOWED_UNIVERSE,
            raw.get("price_min"), raw.get("price_max"),
            bool(raw.get("is_active")), raw.get("reason_included"),
            raw.get("reason_excluded"), raw.get("last_ltp"),
            raw.get("last_ltp_source"), raw.get("avg_volume_20d"),
            raw.get("avg_turnover_20d"), bool(raw.get("ohlcv_available")),
            raw.get("last_verified_at"),
        ))
    if not values:
        return {"success": True, "upserted": 0}
    try:
        snapshot_at = datetime.now(timezone.utc)
        snapshot_date = snapshot_at.date()
        with _connect() as conn:
            with conn.cursor() as cur:
                from psycopg2.extras import execute_values
                execute_values(cur, f"""
                    INSERT INTO {TABLE} (
                        symbol, yahoo_symbol, kite_symbol, instrument_token,
                        company_name, sector, industry, allowed_universe,
                        price_min, price_max, is_active, reason_included,
                        reason_excluded, last_ltp, last_ltp_source,
                        avg_volume_20d, avg_turnover_20d, ohlcv_available,
                        last_verified_at
                    ) VALUES %s
                    ON CONFLICT (symbol) DO UPDATE SET
                        yahoo_symbol = EXCLUDED.yahoo_symbol,
                        kite_symbol = EXCLUDED.kite_symbol,
                        instrument_token = EXCLUDED.instrument_token,
                        company_name = EXCLUDED.company_name,
                        sector = EXCLUDED.sector,
                        industry = EXCLUDED.industry,
                        allowed_universe = EXCLUDED.allowed_universe,
                        price_min = EXCLUDED.price_min,
                        price_max = EXCLUDED.price_max,
                        is_active = EXCLUDED.is_active,
                        reason_included = EXCLUDED.reason_included,
                        reason_excluded = EXCLUDED.reason_excluded,
                        last_ltp = EXCLUDED.last_ltp,
                        last_ltp_source = EXCLUDED.last_ltp_source,
                        avg_volume_20d = EXCLUDED.avg_volume_20d,
                        avg_turnover_20d = EXCLUDED.avg_turnover_20d,
                        ohlcv_available = EXCLUDED.ohlcv_available,
                        last_verified_at = EXCLUDED.last_verified_at,
                        updated_at = NOW()
                """, values)
                # A refresh is an immutable observation. Do not update an
                # earlier snapshot when a second refresh happens on the same
                # day; snapshot_at makes each refresh independently replayable.
                history_values = [
                    (
                        snapshot_at, snapshot_date, value[0], value[7],
                        value[10], value[5], value[18],
                    )
                    for value in values
                ]
                execute_values(cur, """
                    INSERT INTO custom_universe_membership_history (
                        snapshot_at, snapshot_date, symbol, allowed_universe,
                        is_active, sector, last_verified_at
                    ) VALUES %s
                    ON CONFLICT (snapshot_at, symbol) DO NOTHING
                """, history_values)
        return {"success": True, "upserted": len(values)}
    except Exception as exc:
        logger.warning("custom_universe_store.upsert_symbols: %s", exc)
        return {"success": False, "upserted": 0, "error": str(exc)[:200]}


def get_all_symbols() -> List[Dict[str, Any]]:
    if not ensure_table():
        return []
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT {", ".join(_COLUMNS)}
                    FROM {TABLE}
                    WHERE allowed_universe = %s
                    ORDER BY is_active DESC, sector, symbol
                """, (ALLOWED_UNIVERSE,))
                return [_serialise(row) for row in cur.fetchall()]
    except Exception as exc:
        logger.warning("custom_universe_store.get_all_symbols: %s", exc)
        return []


def get_active_symbols() -> List[str]:
    if not ensure_table():
        return []
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute(f"""
                    SELECT symbol FROM {TABLE}
                    WHERE allowed_universe = %s AND is_active = TRUE
                    ORDER BY symbol
                """, (ALLOWED_UNIVERSE,))
                return [str(row[0]).upper() for row in cur.fetchall()]
    except Exception as exc:
        logger.warning("custom_universe_store.get_active_symbols: %s", exc)
        return []


def get_active_symbol_metadata() -> Dict[str, Dict[str, Any]]:
    return {
        str(row["symbol"]).upper(): row
        for row in get_all_symbols() if row.get("is_active")
    }


def get_historical_universe_resolution(as_of_date: str) -> Dict[str, Any]:
    """Resolve custom-universe membership and preserve the evidence source.

    ``symbols`` alone cannot distinguish a genuinely missing snapshot from a
    snapshot whose recorded active membership is empty.  Backtests need that
    distinction so an explicitly opted-in current-list fallback is only used
    when immutable historical evidence is actually absent.
    """
    try:
        target = date.fromisoformat(str(as_of_date)[:10])
    except (TypeError, ValueError):
        return {
            "status": "HISTORICAL_SNAPSHOT_UNAVAILABLE",
            "symbols": [],
            "as_of_date": str(as_of_date or "")[:10] or None,
        }
    if not ensure_table():
        return {
            "status": "HISTORICAL_SNAPSHOT_UNAVAILABLE",
            "symbols": [],
            "as_of_date": target.isoformat(),
        }
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT snapshot_at, snapshot_date
                    FROM custom_universe_membership_history
                    WHERE allowed_universe = %s
                      AND snapshot_date <= %s
                    ORDER BY snapshot_at DESC
                    LIMIT 1
                """, (ALLOWED_UNIVERSE, target))
                snapshot = cur.fetchone()
                if not snapshot:
                    return {
                        "status": "HISTORICAL_SNAPSHOT_UNAVAILABLE",
                        "symbols": [],
                        "as_of_date": target.isoformat(),
                    }
                snapshot_at, snapshot_date = snapshot
                cur.execute("""
                    SELECT symbol
                    FROM custom_universe_membership_history
                    WHERE allowed_universe = %s
                      AND is_active = TRUE
                      AND snapshot_at = %s
                    ORDER BY symbol
                """, (ALLOWED_UNIVERSE, snapshot_at))
                return {
                    "status": "HISTORICAL_SNAPSHOT",
                    "symbols": [str(row[0]).upper() for row in cur.fetchall()],
                    "as_of_date": target.isoformat(),
                    "snapshot_at": (
                        snapshot_at.isoformat()
                        if hasattr(snapshot_at, "isoformat") else str(snapshot_at)
                    ),
                    "snapshot_date": (
                        snapshot_date.isoformat()
                        if hasattr(snapshot_date, "isoformat") else str(snapshot_date)
                    ),
                }
    except Exception as exc:
        logger.warning("custom_universe_store.get_historical_universe_resolution: %s", exc)
        return {
            "status": "HISTORICAL_SNAPSHOT_UNAVAILABLE",
            "symbols": [],
            "as_of_date": target.isoformat(),
        }


def get_active_symbols_as_of(as_of_date: str) -> List[str]:
    """Compatibility helper returning only immutable active membership."""
    return list(get_historical_universe_resolution(as_of_date).get("symbols") or [])


def get_status() -> Dict[str, Any]:
    rows = get_all_symbols()
    active = [row for row in rows if row.get("is_active")]
    sector_counts: Dict[str, int] = {}
    for row in active:
        sector = str(row.get("sector") or "OTHER")
        sector_counts[sector] = sector_counts.get(sector, 0) + 1
    ohlcv_hits = sum(1 for row in active if row.get("ohlcv_available"))
    kite_ltp_count = sum(
        1 for row in active if str(row.get("last_ltp_source") or "").startswith("kite")
    )
    latest = max(
        (str(row.get("last_verified_at")) for row in rows if row.get("last_verified_at")),
        default=None,
    )
    # Derive actual price band from stored rows rather than a hardcoded constant.
    price_mins = [row["price_min"] for row in rows if row.get("price_min") is not None]
    price_maxs = [row["price_max"] for row in rows if row.get("price_max") is not None]
    price_filter = {
        "min": min(price_mins) if price_mins else 20.0,
        "max": max(price_maxs) if price_maxs else 500.0,
    }
    try:
        from config import get_active_intraday_universe
        mode = get_active_intraday_universe().value
    except Exception:
        mode = "NIFTY_50"
    return {
        "success": True,
        "active_universe": mode,
        "custom_universe_name": ALLOWED_UNIVERSE,
        "price_filter": price_filter,
        "sectors": ["IT", "INFRA", "BANK"],
        "active_count": len(active),
        "excluded_count": max(0, len(rows) - len(active)),
        "total_candidates": len(rows),
        "sector_counts": sector_counts,
        "last_refresh": latest,
        "ohlcv_cache_hit_rate_pct": round(ohlcv_hits / len(active) * 100, 1) if active else 0.0,
        "kite_ltp": {
            "available_symbols": kite_ltp_count,
            "status": "AVAILABLE" if kite_ltp_count else "FALLBACK_OR_UNAVAILABLE",
        },
        "asm_gsm": "unavailable_skip",
        "paper_trading_only": True,
        "no_live_broker_orders": True,
    }