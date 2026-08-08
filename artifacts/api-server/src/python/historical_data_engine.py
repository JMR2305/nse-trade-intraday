"""
Phase 23 Part 2A — Historical Data Engine.

Persistent local candle cache for the Historical Backtest Engine.

Design:
  * Candles are stored in Postgres table `backtest_candles` keyed by
    (symbol, interval, ts). File fallback (JSON, per symbol+interval) when
    DATABASE_URL is absent (dev/tests).
  * Coverage metadata in `backtest_candle_meta` records which
    (symbol, interval, date-range) windows have already been downloaded so
    identical data is NEVER re-downloaded.
  * Supported intervals: 5m, 10m, 15m, 1d. 10m candles are resampled from
    cached 5m candles (yfinance has no native 10m interval).
  * Corporate actions (splits + dividends) are cached per symbol in
    `backtest_corporate_actions`.

Provider limits (yfinance, NSE symbols):
  * 5m/15m intraday history is only available for roughly the last 60 days.
  * daily history is available for years.

This module NEVER fabricates candles — a failed download returns an explicit
error; callers must surface it, not paper over it.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, date
from typing import Any, Dict, List, Optional, Tuple

from scan_state_store import _connect, db_available

_DIR = os.path.dirname(os.path.abspath(__file__))
_CACHE_DIR = os.path.join(_DIR, "backtest_candle_cache")

SUPPORTED_INTERVALS = ("5m", "10m", "15m", "1d")
# yfinance-native intervals (10m is resampled from 5m)
_NATIVE = {"5m": "5m", "15m": "15m", "1d": "1d"}
INTRADAY_MAX_DAYS = 55   # conservative yfinance intraday history limit

_SCHEMA_READY = False


def _ensure_schema(conn) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS backtest_candles (
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL,
                ts TIMESTAMPTZ NOT NULL,
                open DOUBLE PRECISION NOT NULL,
                high DOUBLE PRECISION NOT NULL,
                low DOUBLE PRECISION NOT NULL,
                close DOUBLE PRECISION NOT NULL,
                volume BIGINT NOT NULL DEFAULT 0,
                PRIMARY KEY (symbol, interval, ts)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS backtest_candle_meta (
                symbol TEXT NOT NULL,
                interval TEXT NOT NULL,
                range_start DATE NOT NULL,
                range_end DATE NOT NULL,
                fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (symbol, interval, range_start, range_end)
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS backtest_corporate_actions (
                symbol TEXT NOT NULL,
                action_date DATE NOT NULL,
                kind TEXT NOT NULL,          -- SPLIT | DIVIDEND
                value DOUBLE PRECISION NOT NULL,
                fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                PRIMARY KEY (symbol, action_date, kind)
            )
            """
        )
    conn.commit()
    _SCHEMA_READY = True


# ── File fallback helpers ────────────────────────────────────────────────────

def _file_path(symbol: str, interval: str) -> str:
    os.makedirs(_CACHE_DIR, exist_ok=True)
    return os.path.join(_CACHE_DIR, f"{symbol.upper()}_{interval}.json")


def _file_load(symbol: str, interval: str) -> Dict[str, Any]:
    try:
        with open(_file_path(symbol, interval), "r") as f:
            return json.load(f)
    except Exception:
        return {"candles": {}, "coverage": []}


def _file_save(symbol: str, interval: str, data: Dict[str, Any]) -> None:
    path = _file_path(symbol, interval)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, default=str)
    os.replace(tmp, path)


# ── Coverage ─────────────────────────────────────────────────────────────────

def _covered(symbol: str, interval: str, start: date, end: date) -> bool:
    """True when an already-downloaded window fully contains [start, end]."""
    if db_available():
        conn = _connect()
        try:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM backtest_candle_meta"
                    " WHERE symbol=%s AND interval=%s"
                    "   AND range_start<=%s AND range_end>=%s LIMIT 1",
                    (symbol.upper(), interval, start, end),
                )
                return cur.fetchone() is not None
        finally:
            conn.close()
    data = _file_load(symbol, interval)
    for c in data.get("coverage", []):
        if c["start"] <= start.isoformat() and c["end"] >= end.isoformat():
            return True
    return False


def _record_coverage(symbol: str, interval: str, start: date, end: date) -> None:
    if db_available():
        conn = _connect()
        try:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO backtest_candle_meta"
                    " (symbol, interval, range_start, range_end)"
                    " VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (symbol.upper(), interval, start, end),
                )
            conn.commit()
        finally:
            conn.close()
        return
    data = _file_load(symbol, interval)
    data.setdefault("coverage", []).append(
        {"start": start.isoformat(), "end": end.isoformat()})
    _file_save(symbol, interval, data)


# ── Store / read candles ─────────────────────────────────────────────────────

def _store_candles(symbol: str, interval: str,
                   candles: List[Dict[str, Any]]) -> int:
    if not candles:
        return 0
    if db_available():
        conn = _connect()
        try:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.executemany(
                    """
                    INSERT INTO backtest_candles
                        (symbol, interval, ts, open, high, low, close, volume)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT (symbol, interval, ts) DO UPDATE SET
                        open=EXCLUDED.open, high=EXCLUDED.high,
                        low=EXCLUDED.low, close=EXCLUDED.close,
                        volume=EXCLUDED.volume
                    """,
                    [(symbol.upper(), interval, c["ts"], c["open"], c["high"],
                      c["low"], c["close"], int(c.get("volume") or 0))
                     for c in candles],
                )
            conn.commit()
        finally:
            conn.close()
        return len(candles)
    data = _file_load(symbol, interval)
    book = data.setdefault("candles", {})
    for c in candles:
        book[str(c["ts"])] = {k: c[k] for k in
                              ("open", "high", "low", "close", "volume")}
    _file_save(symbol, interval, data)
    return len(candles)


def get_candles(symbol: str, interval: str, start: str, end: str
                ) -> List[Dict[str, Any]]:
    """Read cached candles in [start, end] (ISO dates/timestamps), ts asc."""
    if db_available():
        conn = _connect()
        try:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT ts, open, high, low, close, volume"
                    " FROM backtest_candles"
                    " WHERE symbol=%s AND interval=%s AND ts>=%s"
                    "   AND ts < (%s::date + 1)"
                    " ORDER BY ts ASC",
                    (symbol.upper(), interval, start, end[:10]),
                )
                return [
                    {"ts": r[0].isoformat(), "open": r[1], "high": r[2],
                     "low": r[3], "close": r[4], "volume": int(r[5] or 0)}
                    for r in cur.fetchall()
                ]
        finally:
            conn.close()
    data = _file_load(symbol, interval)
    out = []
    end_key = end[:10] + "T99"       # inclusive end date
    for ts, c in sorted(data.get("candles", {}).items()):
        if ts >= start and ts <= end_key:
            out.append({"ts": ts, **c})
    return out


# ── Download (yfinance) ──────────────────────────────────────────────────────

def _download(symbol: str, native_interval: str, start: date, end: date
              ) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    """Download OHLCV from yfinance. Returns (candles, error)."""
    try:
        import yfinance as yf
        from market_data_engine import to_yf_symbol
        hist = yf.Ticker(to_yf_symbol(symbol)).history(
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            interval=native_interval, auto_adjust=False)
        if hist is None or hist.empty:
            return [], f"No data returned for {symbol} {native_interval}"
        candles = []
        for ts, row in hist.iterrows():
            o, h, l, c = (row.get("Open"), row.get("High"),
                          row.get("Low"), row.get("Close"))
            if any(v is None or v != v for v in (o, h, l, c)):
                continue
            candles.append({
                "ts": ts.isoformat(),
                "open": float(o), "high": float(h),
                "low": float(l), "close": float(c),
                "volume": int(row.get("Volume") or 0),
            })
        return candles, None
    except Exception as exc:
        return [], f"Download failed for {symbol}: {exc}"


def _resample_10m(five: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Aggregate 5m candles into 10m buckets (bucket start = even 10 min)."""
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    order: List[str] = []
    for c in five:
        ts = c["ts"]
        # normalise minute to the 10-minute bucket start
        try:
            dt = datetime.fromisoformat(ts)
            bstart = dt.replace(minute=(dt.minute // 10) * 10,
                                second=0, microsecond=0).isoformat()
        except Exception:
            continue
        if bstart not in buckets:
            buckets[bstart] = []
            order.append(bstart)
        buckets[bstart].append(c)
    out = []
    for b in order:
        grp = buckets[b]
        out.append({
            "ts": b,
            "open": grp[0]["open"],
            "high": max(g["high"] for g in grp),
            "low": min(g["low"] for g in grp),
            "close": grp[-1]["close"],
            "volume": sum(int(g.get("volume") or 0) for g in grp),
        })
    return out


def ensure_candles(symbol: str, interval: str, start: str, end: str
                   ) -> Dict[str, Any]:
    """
    Ensure candles for [start, end] are cached locally; download only what is
    not already covered. Returns {ok, cached, downloaded, candles, error}.
    """
    if interval not in SUPPORTED_INTERVALS:
        return {"ok": False, "error": f"Unsupported interval {interval}",
                "candles": []}
    s, e = date.fromisoformat(start[:10]), date.fromisoformat(end[:10])
    if e < s:
        return {"ok": False, "error": "end before start", "candles": []}

    # Intraday provider limit — be explicit, never silently truncate.
    if interval != "1d":
        oldest = date.today() - timedelta(days=INTRADAY_MAX_DAYS)
        if s < oldest:
            return {"ok": False, "candles": [],
                    "error": (f"Intraday ({interval}) history older than "
                              f"{INTRADAY_MAX_DAYS} days is not available from "
                              f"the data provider. Earliest: {oldest.isoformat()}. "
                              f"Use interval=1d for older ranges.")}

    downloaded = 0
    if not _covered(symbol, interval, s, e):
        if interval == "10m":
            # ensure 5m base coverage, then resample
            base = ensure_candles(symbol, "5m", start, end)
            if not base["ok"]:
                return base
            ten = _resample_10m(base["candles"])
            downloaded = _store_candles(symbol, "10m", ten)
        else:
            candles, err = _download(symbol, _NATIVE[interval], s, e)
            if err:
                return {"ok": False, "error": err, "candles": []}
            downloaded = _store_candles(symbol, interval, candles)
        _record_coverage(symbol, interval, s, e)

    out = get_candles(symbol, interval, start, end)
    return {"ok": True, "cached": len(out) - downloaded if downloaded else len(out),
            "downloaded": downloaded, "candles": out, "error": None}


# ── Corporate actions ────────────────────────────────────────────────────────

def ensure_corporate_actions(symbol: str) -> Dict[str, Any]:
    """Cache splits + dividends for a symbol (refreshed at most once/day)."""
    sym = symbol.upper()
    try:
        if db_available():
            conn = _connect()
            try:
                _ensure_schema(conn)
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT MAX(fetched_at) FROM backtest_corporate_actions"
                        " WHERE symbol=%s", (sym,))
                    row = cur.fetchone()
                    if row and row[0] is not None:
                        age = datetime.now(row[0].tzinfo) - row[0]
                        if age < timedelta(days=1):
                            return _read_corporate_actions(sym)
            finally:
                conn.close()
        import yfinance as yf
        from market_data_engine import to_yf_symbol
        t = yf.Ticker(to_yf_symbol(sym))
        rows: List[Tuple[str, str, float]] = []
        try:
            for d, v in (t.splits or {}).items():
                if v:
                    rows.append((d.date().isoformat(), "SPLIT", float(v)))
        except Exception:
            pass
        try:
            for d, v in (t.dividends or {}).items():
                if v:
                    rows.append((d.date().isoformat(), "DIVIDEND", float(v)))
        except Exception:
            pass
        if db_available() and rows:
            conn = _connect()
            try:
                _ensure_schema(conn)
                with conn.cursor() as cur:
                    cur.executemany(
                        "INSERT INTO backtest_corporate_actions"
                        " (symbol, action_date, kind, value)"
                        " VALUES (%s,%s,%s,%s)"
                        " ON CONFLICT (symbol, action_date, kind)"
                        " DO UPDATE SET value=EXCLUDED.value, fetched_at=NOW()",
                        [(sym, d, k, v) for d, k, v in rows],
                    )
                conn.commit()
            finally:
                conn.close()
        return {"ok": True, "symbol": sym,
                "actions": [{"date": d, "kind": k, "value": v}
                            for d, k, v in sorted(rows)]}
    except Exception as exc:
        return {"ok": False, "symbol": sym, "actions": [],
                "error": str(exc)[:200]}


def _read_corporate_actions(sym: str) -> Dict[str, Any]:
    conn = _connect()
    try:
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT action_date, kind, value FROM backtest_corporate_actions"
                " WHERE symbol=%s ORDER BY action_date", (sym,))
            return {"ok": True, "symbol": sym,
                    "actions": [{"date": r[0].isoformat(), "kind": r[1],
                                 "value": r[2]} for r in cur.fetchall()]}
    finally:
        conn.close()


def cache_stats() -> Dict[str, Any]:
    """Summary of the local candle cache."""
    if db_available():
        conn = _connect()
        try:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT interval, COUNT(DISTINCT symbol), COUNT(*),"
                    " MIN(ts), MAX(ts) FROM backtest_candles GROUP BY interval")
                rows = [{"interval": r[0], "symbols": r[1], "candles": r[2],
                         "first": r[3].isoformat() if r[3] else None,
                         "last": r[4].isoformat() if r[4] else None}
                        for r in cur.fetchall()]
            return {"backend": "postgres", "intervals": rows}
        finally:
            conn.close()
    rows = []
    if os.path.isdir(_CACHE_DIR):
        for fn in sorted(os.listdir(_CACHE_DIR)):
            if fn.endswith(".json"):
                data = _file_load(*fn[:-5].rsplit("_", 1))
                rows.append({"file": fn, "candles": len(data.get("candles", {}))})
    return {"backend": "file", "files": rows}
