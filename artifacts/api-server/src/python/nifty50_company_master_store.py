"""
nifty50_company_master_store.py — Local company master for NIFTY 50 symbols.

* Stores symbol → company metadata (name, sector, Yahoo/Kite ticker, ISIN …).
* Bootstrapped from config.SECTOR_MAP; enriched from yfinance on demand.
* Refreshed weekly or on manual trigger; used during scans for display names,
  sector exposure, and Kite instrument-token lookup.
* Never raises; returns None / empty dict on DB errors.
* PAPER TRADING ONLY.
"""

from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Generator, List, Optional

logger = logging.getLogger(__name__)


def _db_available() -> bool:
    return bool(os.environ.get("DATABASE_URL", ""))


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
    """Create nifty50_company_master if absent. Returns True on success."""
    if not _db_available():
        return False
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS nifty50_company_master (
                        symbol              TEXT PRIMARY KEY,
                        yahoo_symbol        TEXT,
                        kite_symbol         TEXT,
                        instrument_token    BIGINT,
                        company_name        TEXT,
                        sector              TEXT,
                        industry            TEXT,
                        exchange            TEXT DEFAULT 'NSE',
                        lot_size            INTEGER,
                        tick_size           NUMERIC(10,4),
                        isin                TEXT,
                        index_membership    TEXT DEFAULT 'NIFTY_50',
                        is_active           BOOLEAN DEFAULT TRUE,
                        last_verified_at    TIMESTAMPTZ,
                        source              TEXT DEFAULT 'config'
                    )
                """)
        return True
    except Exception as exc:
        logger.warning("nifty50_company_master_store.ensure_table: %s", exc)
        return False


def bootstrap_from_config() -> Dict[str, Any]:
    """
    Reconcile the company master against config.SECTOR_MAP.
    Safe to call multiple times (upsert, no duplicates):
      * configured NIFTY_50 symbols are upserted and reactivated
        (is_active = TRUE);
      * rows no longer in the configured universe (e.g. LTIM after it left
        the index) are retained for history but marked is_active = FALSE.
    Returns summary dict.
    """
    if not _db_available():
        return {"success": False, "error": "db_unavailable"}
    try:
        from config import SECTOR_MAP
    except ImportError:
        return {"success": False, "error": "config not importable"}

    ensure_table()
    now = datetime.now(timezone.utc).isoformat()
    rows = []
    for sector, syms in SECTOR_MAP.items():
        for sym in syms:
            yahoo_sym = sym.upper() + ".NS"
            rows.append((sym.upper(), yahoo_sym, sym.upper(), sector, now, "config"))

    active_symbols = [r[0] for r in rows]

    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                from psycopg2.extras import execute_values
                execute_values(cur, """
                    INSERT INTO nifty50_company_master
                        (symbol, yahoo_symbol, kite_symbol, sector,
                         last_verified_at, source, is_active)
                    VALUES %s
                    ON CONFLICT (symbol) DO UPDATE SET
                        yahoo_symbol     = EXCLUDED.yahoo_symbol,
                        kite_symbol      = EXCLUDED.kite_symbol,
                        sector           = EXCLUDED.sector,
                        last_verified_at = EXCLUDED.last_verified_at,
                        source           = EXCLUDED.source,
                        is_active        = TRUE
                """, [(r[0], r[1], r[2], r[3], r[4], r[5], True) for r in rows])
                # Retain history but deactivate any row no longer in the
                # configured NIFTY_50 universe (e.g. LTIM after it left).
                cur.execute("""
                    UPDATE nifty50_company_master
                    SET is_active = FALSE
                    WHERE index_membership = 'NIFTY_50'
                      AND symbol <> ALL(%s)
                """, (active_symbols,))
                deactivated = cur.rowcount
        return {"success": True, "upserted": len(rows), "deactivated": deactivated}
    except Exception as exc:
        logger.warning("bootstrap_from_config: %s", exc)
        return {"success": False, "error": str(exc)[:200]}


def get_all() -> List[Dict[str, Any]]:
    """Return all company master rows as list of dicts."""
    if not _db_available():
        return []
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT symbol, yahoo_symbol, kite_symbol, instrument_token,
                           company_name, sector, industry, exchange,
                           lot_size, tick_size, isin, index_membership,
                           is_active, last_verified_at, source
                    FROM nifty50_company_master
                    ORDER BY symbol
                """)
                rows = cur.fetchall()
        cols = ["symbol", "yahoo_symbol", "kite_symbol", "instrument_token",
                "company_name", "sector", "industry", "exchange",
                "lot_size", "tick_size", "isin", "index_membership",
                "is_active", "last_verified_at", "source"]
        return [dict(zip(cols, r)) for r in rows]
    except Exception as exc:
        logger.warning("nifty50_company_master_store.get_all: %s", exc)
        return []


def get_symbol(symbol: str) -> Optional[Dict[str, Any]]:
    """Return master row for one symbol, or None."""
    if not _db_available():
        return None
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT symbol, yahoo_symbol, kite_symbol, instrument_token,
                           company_name, sector, industry, exchange,
                           lot_size, tick_size, isin, index_membership,
                           is_active, last_verified_at, source
                    FROM nifty50_company_master WHERE symbol = %s
                """, (symbol.upper(),))
                row = cur.fetchone()
        if not row:
            return None
        cols = ["symbol", "yahoo_symbol", "kite_symbol", "instrument_token",
                "company_name", "sector", "industry", "exchange",
                "lot_size", "tick_size", "isin", "index_membership",
                "is_active", "last_verified_at", "source"]
        return dict(zip(cols, row))
    except Exception as exc:
        logger.warning("nifty50_company_master_store.get_symbol(%s): %s", symbol, exc)
        return None


def update_from_yfinance(symbols: List[str]) -> Dict[str, Any]:
    """
    Enrich company master rows with yfinance Ticker.info for given symbols.
    Updates company_name, industry, isin if available. Never raises.
    """
    if not _db_available():
        return {"success": False, "error": "db_unavailable"}
    ensure_table()
    enriched: List[str] = []
    failed: List[str] = []
    try:
        import yfinance as yf
    except ImportError:
        return {"success": False, "error": "yfinance not installed"}

    now = datetime.now(timezone.utc).isoformat()
    for sym in symbols:
        try:
            ticker = yf.Ticker(sym.upper() + ".NS")
            info = ticker.info or {}
            name = info.get("longName") or info.get("shortName")
            industry = info.get("industry")
            isin = info.get("isin")
            if not (name or industry or isin):
                continue
            with _connect() as conn:
                with conn.cursor() as cur:
                    cur.execute("""
                        INSERT INTO nifty50_company_master (symbol, last_verified_at, source)
                        VALUES (%s, %s, 'yfinance')
                        ON CONFLICT (symbol) DO UPDATE SET
                            company_name     = COALESCE(%s, nifty50_company_master.company_name),
                            industry         = COALESCE(%s, nifty50_company_master.industry),
                            isin             = COALESCE(%s, nifty50_company_master.isin),
                            last_verified_at = %s,
                            source           = 'yfinance'
                    """, (sym.upper(), now, name, industry, isin, now))
            enriched.append(sym.upper())
        except Exception as exc:
            logger.warning("update_from_yfinance(%s): %s", sym, exc)
            failed.append(sym.upper())

    return {
        "success": True,
        "enriched": enriched,
        "failed": failed,
    }


def get_sector_for_symbol(symbol: str) -> Optional[str]:
    """Quick lookup: return sector string or None."""
    row = get_symbol(symbol)
    return row["sector"] if row else None


def get_missing_symbols(universe: List[str]) -> List[str]:
    """Return symbols from universe that have no ACTIVE master entry.

    A row that exists but is marked is_active = FALSE (e.g. a symbol retained
    for history after leaving the index) counts as missing.
    """
    if not _db_available():
        return universe
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT symbol FROM nifty50_company_master
                    WHERE symbol = ANY(%s) AND is_active = TRUE
                """, ([s.upper() for s in universe],))
                found = {r[0] for r in cur.fetchall()}
        return [s.upper() for s in universe if s.upper() not in found]
    except Exception:
        return []
