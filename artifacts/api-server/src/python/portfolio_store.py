"""
portfolio_store.py — Durable persistence for paper trading state.

Stores portfolio state (cash, positions, pnl_history) and individual
trade records in PostgreSQL when DATABASE_URL is set.

Behaviour:
- With DATABASE_URL: Postgres is authoritative. DB failures raise so callers
  receive an explicit error; no silent degradation to ephemeral files.
  A local warm-cache file (state.json) is written AFTER a successful DB write
  to speed up same-instance reads, but it is never the primary write target.
- Without DATABASE_URL (local dev / no DB): falls back to the legacy
  state.json file. This mode should never be used in production.

Schema auto-created on first use (no migrations needed).
Paper trading only — no live orders anywhere in this module.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DIR = os.path.dirname(os.path.abspath(__file__))
WARM_CACHE_FILE = os.path.join(_DIR, "state.json")

_SCHEMA_READY = False

# Matches the Phase 20 trade id embedded in legacy reason strings, e.g.
# "Phase 20 AUTO paper entry (trade P20-4a5f909738)".
_P20_REASON_RE = r"trade (P20-[A-Za-z0-9]+)"


def extract_phase20_trade_id(reason: str) -> Optional[str]:
    """Parse the Phase 20 trade_id out of a legacy reason string, or None."""
    import re
    m = re.search(_P20_REASON_RE, reason or "")
    return m.group(1) if m else None


def _backfill_phase20_trade_ids(conn) -> int:
    """Idempotent migration: copy the Phase 20 trade_id from the reason string
    into metadata.phase20_trade_id for historical rows.

    - Only touches rows whose reason contains a P20 id AND whose metadata does
      not already carry phase20_trade_id (never overwrites populated IDs).
    - Safe to run on every schema bootstrap; matched set shrinks to zero.
    Returns the number of rows updated.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE paper_trades
            SET metadata = jsonb_set(
                COALESCE(metadata, '{}'::jsonb),
                '{phase20_trade_id}',
                to_jsonb(substring(reason from %s))
            )
            WHERE reason ~ %s
              AND (metadata ->> 'phase20_trade_id') IS NULL
            """,
            (_P20_REASON_RE, _P20_REASON_RE),
        )
        return cur.rowcount

INITIAL_CAPITAL = 100_000.0   # ₹100,000 fallback; actual value comes from Phase 20 settings


def get_initial_capital() -> float:
    """Return the configured starting capital from phase20 settings.

    Uses a lazy import to avoid circular dependencies. Falls back to the
    module-level INITIAL_CAPITAL constant when the settings store is
    unavailable (e.g. local dev without DATABASE_URL, or during cold start).
    """
    try:
        from phase20_store import get_settings as _get_p20_settings  # noqa: PLC0415
        cap = float(_get_p20_settings().get("initial_capital", INITIAL_CAPITAL))
        if cap >= 10_000:
            return cap
    except Exception:
        pass
    return INITIAL_CAPITAL


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
            CREATE TABLE IF NOT EXISTS paper_portfolio (
                id          INTEGER PRIMARY KEY,
                cash        DOUBLE PRECISION NOT NULL,
                positions   JSONB NOT NULL DEFAULT '{}',
                pnl_history JSONB NOT NULL DEFAULT '[]',
                updated_at  TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS paper_trades (
                id          TEXT PRIMARY KEY,
                symbol      TEXT NOT NULL,
                action      TEXT NOT NULL,
                quantity    INTEGER NOT NULL,
                price       DOUBLE PRECISION NOT NULL,
                total       DOUBLE PRECISION NOT NULL,
                trade_ts    TIMESTAMPTZ NOT NULL,
                reason      TEXT DEFAULT '',
                metadata    JSONB NOT NULL DEFAULT '{}',
                created_at  TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
        cur.execute(
            "ALTER TABLE paper_trades ADD COLUMN IF NOT EXISTS archived_at TIMESTAMPTZ"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS paper_trades_symbol_idx ON paper_trades (symbol)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS paper_trades_ts_idx ON paper_trades (trade_ts)"
        )
    # One-time (idempotent) correlation backfill for historical rows.
    try:
        n = _backfill_phase20_trade_ids(conn)
        if n:
            logger.info("portfolio_store: backfilled phase20_trade_id on %d trades", n)
    except Exception as exc:
        logger.warning("portfolio_store: phase20_trade_id backfill skipped: %s", exc)
    conn.commit()
    _SCHEMA_READY = True


# ── Load / save state ─────────────────────────────────────────────────────────

def load_state() -> Dict[str, Any]:
    """
    Load the full portfolio state dict (same shape as the old state.json).
    Returns default state if nothing is stored yet.

    With DATABASE_URL: reads from Postgres; raises on DB failure.
    Without DATABASE_URL: reads from the local state.json file.
    """
    if db_available():
        conn = _connect()  # raises on connection failure
        try:
            _ensure_schema(conn)
            portfolio = _load_portfolio_row(conn)
            trades    = _load_all_trades(conn)
        finally:
            conn.close()

        if portfolio is not None:
            portfolio["trades"] = trades
            return portfolio
        # No row yet — return default (first run)
        return _default_state()

    # Local-dev fallback: no DATABASE_URL set
    return _read_json_fallback()


def save_state(state: Dict[str, Any]) -> None:
    """
    Persist the portfolio state dict.

    With DATABASE_URL: writes to Postgres (authoritative). A warm-cache file
    is written AFTER a successful DB write for same-instance read speed.
    Raises on DB failure — callers must not swallow this.

    Without DATABASE_URL: writes to the local state.json file only.
    """
    if not db_available():
        _write_json_fallback(state)
        _invalidate_perf_cache()
        return

    conn = _connect()  # raises on connection failure
    try:
        _ensure_schema(conn)
        _upsert_portfolio_row(conn, state)
        _insert_new_trades(conn, state.get("trades", []))
        conn.commit()
    except Exception:
        conn.rollback()
        raise  # surface DB write failure to callers
    finally:
        conn.close()

    # Write warm-cache AFTER successful DB commit (read optimisation only)
    _write_json_fallback(state)
    # Immediately invalidate the performance analytics cache so the next
    # request reflects the new trade within one poll cycle (< 1 s) rather
    # than waiting for the 30-second TTL to expire.
    _invalidate_perf_cache()


def _invalidate_perf_cache() -> None:
    """
    Clear the portfolio-performance file-based TTL cache.

    Called immediately after every successful portfolio write so that
    performance endpoints reflect the new trade on the very next request
    rather than serving stale data for up to 30 seconds.

    Import is lazy to avoid a circular import between portfolio_store and
    performance_engine.  Failures are swallowed — cache invalidation must
    never block a committed trade write.
    """
    try:
        from portfolio_performance.performance_engine import _clear_perf_cache
        _clear_perf_cache()
    except Exception:
        pass


# ── Archive all trades (portfolio reset — soft reset, never deletes) ─────────

ARCHIVE_FALLBACK_FILE = os.path.join(_DIR, "trades_archive.json")


def archive_all_trades() -> None:
    """
    Mark all current-session trades as archived — called by portfolio reset.
    Trade rows are NEVER deleted; they are stamped with archived_at so the
    active session starts clean while history remains queryable.
    Raises on DB failure when DATABASE_URL is set.
    """
    if not db_available():
        # Local-dev fallback: move current trades into trades_archive.json
        state = _read_json_fallback()
        trades = state.get("trades", [])
        if not trades:
            return
        archived_at = datetime.now(timezone.utc).isoformat()
        existing: List[Dict[str, Any]] = []
        if os.path.exists(ARCHIVE_FALLBACK_FILE):
            try:
                with open(ARCHIVE_FALLBACK_FILE, "r") as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, IOError):
                existing = []
        for t in trades:
            t = dict(t)
            t["archived_at"] = archived_at
            existing.append(t)
        with open(ARCHIVE_FALLBACK_FILE, "w") as f:
            json.dump(existing, f, indent=2, default=str)
        return

    conn = _connect()
    try:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE paper_trades SET archived_at = NOW() WHERE archived_at IS NULL"
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def load_trades() -> List[Dict[str, Any]]:
    """
    Return the current-session (non-archived) trades, oldest first.

    Used by paper_trading_validation.validation_collector.collect_all_trade_records()
    to drive the analytics pipeline.  Only active trades are returned so that
    archived sessions from previous days do not pollute today's analytics.

    With DATABASE_URL: reads from Postgres.
    Without DATABASE_URL: falls back to state.json trades list.
    """
    if db_available():
        conn = _connect()
        try:
            _ensure_schema(conn)
            return _load_all_trades(conn, include_archived=False)
        finally:
            conn.close()

    # Local-dev fallback
    state = _read_json_fallback()
    return state.get("trades", [])


def load_all_trades_any() -> List[Dict[str, Any]]:
    """
    Return ALL trades — current session AND archived (all-time history),
    oldest first. Archived trades carry an `archived_at` field.
    """
    if db_available():
        conn = _connect()
        try:
            _ensure_schema(conn)
            return _load_all_trades(conn, include_archived=True)
        finally:
            conn.close()

    # Local-dev fallback: archive file + current state trades
    archived: List[Dict[str, Any]] = []
    if os.path.exists(ARCHIVE_FALLBACK_FILE):
        try:
            with open(ARCHIVE_FALLBACK_FILE, "r") as f:
                archived = json.load(f)
        except (json.JSONDecodeError, IOError):
            archived = []
    current = _read_json_fallback().get("trades", [])
    return archived + list(current)


# ── Internal DB helpers ───────────────────────────────────────────────────────

def _load_portfolio_row(conn) -> Optional[Dict[str, Any]]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT cash, positions, pnl_history FROM paper_portfolio WHERE id = 1"
        )
        row = cur.fetchone()
    if row is None:
        return None
    cash, positions, pnl_history = row
    if isinstance(positions, str):
        positions = json.loads(positions)
    if isinstance(pnl_history, str):
        pnl_history = json.loads(pnl_history)
    return {
        "cash":        float(cash),
        "positions":   positions or {},
        "pnl_history": pnl_history or [],
    }


def _load_all_trades(conn, include_archived: bool = False) -> List[Dict[str, Any]]:
    where = "" if include_archived else "WHERE archived_at IS NULL"
    with conn.cursor() as cur:
        cur.execute(
            f"""
            SELECT id, symbol, action, quantity, price, total,
                   trade_ts, reason, metadata, archived_at
            FROM paper_trades
            {where}
            ORDER BY trade_ts ASC, created_at ASC
            """
        )
        rows = cur.fetchall()

    trades = []
    for (tid, symbol, action, quantity, price, total,
         trade_ts, reason, metadata, archived_at) in rows:
        if isinstance(metadata, str):
            metadata = json.loads(metadata)
        meta = metadata or {}
        trade: Dict[str, Any] = {
            "id":        tid,
            "symbol":    symbol,
            "action":    action,
            "quantity":  quantity,
            "price":     float(price),
            "total":     float(total),
            "timestamp": (trade_ts.isoformat()
                          if hasattr(trade_ts, "isoformat") else str(trade_ts)),
            "reason":    reason or "",
        }
        if archived_at is not None:
            trade["archived_at"] = (archived_at.isoformat()
                                    if hasattr(archived_at, "isoformat")
                                    else str(archived_at))
        trade.update(meta)
        # Read-side safety net (also covers local-dev file mode via callers):
        # derive the correlation id from the reason string when missing.
        if not trade.get("phase20_trade_id"):
            p20 = extract_phase20_trade_id(trade.get("reason", ""))
            if p20:
                trade["phase20_trade_id"] = p20
        trades.append(trade)
    return trades


def _upsert_portfolio_row(conn, state: Dict[str, Any]) -> None:
    cash        = float(state.get("cash", 0.0))
    positions   = json.dumps(state.get("positions", {}), default=str)
    pnl_history = json.dumps(state.get("pnl_history", []), default=str)
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO paper_portfolio (id, cash, positions, pnl_history, updated_at)
            VALUES (1, %s, %s, %s, NOW())
            ON CONFLICT (id) DO UPDATE SET
                cash        = EXCLUDED.cash,
                positions   = EXCLUDED.positions,
                pnl_history = EXCLUDED.pnl_history,
                updated_at  = NOW()
            """,
            (cash, positions, pnl_history),
        )


def _insert_new_trades(conn, trades: List[Dict[str, Any]]) -> None:
    """
    Insert trades not yet in the DB. ON CONFLICT DO NOTHING prevents duplicates
    when save_state() is called multiple times with the same data.
    """
    if not trades:
        return

    CORE_COLS = {"id", "symbol", "action", "quantity", "price", "total",
                 "timestamp", "reason"}

    with conn.cursor() as cur:
        for trade in trades:
            tid        = trade.get("id", "")
            symbol     = trade.get("symbol", "")
            action     = trade.get("action", "")
            quantity   = int(trade.get("quantity", 0))
            price      = float(trade.get("price", 0.0))
            total      = float(trade.get("total", 0.0))
            ts_raw     = trade.get("timestamp", "")
            reason     = trade.get("reason", "")
            metadata   = {k: v for k, v in trade.items() if k not in CORE_COLS}

            try:
                trade_ts = datetime.fromisoformat(ts_raw)
            except Exception:
                trade_ts = datetime.now(timezone.utc)

            cur.execute(
                """
                INSERT INTO paper_trades
                    (id, symbol, action, quantity, price, total,
                     trade_ts, reason, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
                """,
                (
                    tid, symbol, action, quantity, price, total,
                    trade_ts, reason, json.dumps(metadata, default=str),
                ),
            )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _default_state() -> Dict[str, Any]:
    cap = get_initial_capital()
    return {
        "cash":        cap,
        "positions":   {},
        "trades":      [],
        "pnl_history": [{"timestamp": datetime.now().isoformat(), "value": cap}],
    }


def _read_json_fallback() -> Dict[str, Any]:
    """Used ONLY when DATABASE_URL is not set (local dev)."""
    if os.path.exists(WARM_CACHE_FILE):
        try:
            with open(WARM_CACHE_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return _default_state()


def _write_json_fallback(state: Dict[str, Any]) -> None:
    """
    Write warm-cache file for same-instance reads.
    In DB mode: called only after a successful DB commit.
    In local-dev mode: the primary persistence target.
    """
    try:
        with open(WARM_CACHE_FILE, "w") as f:
            json.dump(state, f, indent=2, default=str)
    except Exception as exc:
        logger.warning("portfolio_store: could not write warm-cache file: %s", exc)
