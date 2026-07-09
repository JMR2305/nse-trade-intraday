"""
Trade Intelligence Database (Sprint 3 — Module 1).

A persistent SQLite table of every COMPLETED paper trade, captured from:
  • Paper Basket Test  (old model + improved filtered model)
  • Paper Trades       (portfolio buy/sell in paper_trader.py)
  • Historical Replay  (market_replay.py BUY/STRONG BUY signals)

This module only STORES history. No AI learning happens here — future
learning modules will read from this table.

Deduplication: trade_id is deterministic per (source, date, symbol,
holding_period, model), so re-running the same basket test / replay date
never creates duplicate rows (INSERT OR REPLACE).
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime

_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_DIR, "trade_intelligence.db")

INDICATOR_COLUMNS = [
    "ema9", "ema20", "ema50", "ema200", "rsi", "macd", "macd_signal",
    "vwap", "atr", "adx", "supertrend", "volume_ratio",
]

AI_METRIC_COLUMNS = ["opportunity_score", "trade_quality", "confidence", "risk_reward"]

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS trade_intelligence (
    trade_id        TEXT PRIMARY KEY,
    source          TEXT NOT NULL,
    date            TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    sector          TEXT,
    strategy        TEXT,
    market_regime   TEXT,
    holding_period  INTEGER,
    entry_price     REAL,
    exit_price      REAL,
    quantity        INTEGER,
    profit_loss     REAL,
    return_percent  REAL,
    {", ".join(f"{c} REAL" for c in INDICATOR_COLUMNS)},
    {", ".join(f"{c} REAL" for c in AI_METRIC_COLUMNS)},
    outcome         TEXT,
    outcome_classification INTEGER,
    recorded_at     TEXT
);
"""

_ALL_COLUMNS = [
    "trade_id", "source", "date", "symbol", "sector", "strategy",
    "market_regime", "holding_period", "entry_price", "exit_price",
    "quantity", "profit_loss", "return_percent",
    *INDICATOR_COLUMNS, *AI_METRIC_COLUMNS,
    "outcome", "outcome_classification", "recorded_at",
]


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(_SCHEMA)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ti_date ON trade_intelligence(date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ti_symbol ON trade_intelligence(symbol)")
    return conn


def _round(v, nd=2):
    try:
        return round(float(v), nd)
    except (TypeError, ValueError):
        return None


def record_trades(records: list[dict]) -> int:
    """Insert (or replace) completed trade records. Returns rows written."""
    if not records:
        return 0
    now = datetime.now().isoformat()
    rows = []
    for r in records:
        pnl = _round(r.get("profit_loss"))
        row = {c: r.get(c) for c in _ALL_COLUMNS}
        row["recorded_at"] = now
        row["profit_loss"] = pnl
        row["outcome_classification"] = 1 if (pnl or 0.0) > 0 else 0
        rows.append(tuple(row[c] for c in _ALL_COLUMNS))
    conn = _connect()
    try:
        conn.executemany(
            f"INSERT OR REPLACE INTO trade_intelligence ({', '.join(_ALL_COLUMNS)}) "
            f"VALUES ({', '.join('?' for _ in _ALL_COLUMNS)})",
            rows,
        )
        conn.commit()
        return len(rows)
    finally:
        conn.close()


# ── Builders for each source ──────────────────────────────────────────────────

def _from_replay_item(
    it: dict,
    *,
    source: str,
    model: str,
    quantity: int,
    market_regime: str,
    entry_price: float | None = None,
    exit_price: float | None = None,
    pnl: float | None = None,
    pnl_pct: float | None = None,
    outcome: str | None = None,
) -> dict | None:
    """Build a record from a ReplayItem (used by basket + historical replay)."""
    if it.get("error") is not None:
        return None
    entry = entry_price if entry_price is not None else it.get("price_on_scan_date")
    exit_ = exit_price if exit_price is not None else it.get("price_after_holding")
    ret = pnl_pct if pnl_pct is not None else it.get("return_pct")
    if not entry or exit_ is None or ret is None:
        return None  # unresolved (Pending) — only completed trades are stored
    profit = pnl if pnl is not None else _round((exit_ - entry) * quantity)
    ind = it.get("indicators_at_entry") or {}
    rec = {
        "trade_id": f"{source}:{model}:{it['scan_date']}:{it['stock']}:{it['holding_period']}",
        "source": source,
        "date": it["scan_date"],
        "symbol": it["stock"],
        "sector": it.get("sector", ""),
        "strategy": it.get("best_strategy_name", ""),
        "market_regime": market_regime,
        "holding_period": it.get("holding_period"),
        "entry_price": _round(entry),
        "exit_price": _round(exit_),
        "quantity": quantity,
        "profit_loss": profit,
        "return_percent": _round(ret),
        "opportunity_score": _round(it.get("opportunity_score")),
        "trade_quality": _round(it.get("trade_quality")),
        "confidence": _round(it.get("confidence")),
        "risk_reward": _round(it.get("rr_ratio")),
        "outcome": outcome or it.get("outcome_label") or it.get("outcome") or "",
    }
    for c in INDICATOR_COLUMNS:
        rec[c] = _round(ind.get(c), 4)
    return rec


def record_basket_trades(
    replay_items: dict[str, dict],
    basket_items: list[dict],
    *,
    model: str,
    holding_period: int,
    market_regime: str,
) -> int:
    """
    Store completed Paper Basket Test trades (one call per model —
    "old" or "improved"). Basket items carry the actual simulated buy/sell
    prices and P&L; the matching replay item supplies indicators + AI metrics.
    """
    records = []
    for b in basket_items:
        if b.get("error") is not None or b.get("sell_price") in (None, 0):
            continue
        it = replay_items.get(b["stock"]) or replay_items.get(f"{b['stock']}.NS")
        if it is None or it.get("error") is not None:
            continue
        it = {**it, "holding_period": holding_period}
        rec = _from_replay_item(
            it,
            source="paper_basket",
            model=model,
            quantity=int(b.get("quantity", 0) or 0),
            market_regime=market_regime,
            entry_price=b.get("buy_price"),
            exit_price=b.get("sell_price"),
            pnl=b.get("pnl_rupees"),
            pnl_pct=b.get("pnl_pct"),
            outcome=b.get("outcome"),
        )
        if rec:
            records.append(rec)
    return record_trades(records)


def record_replay_trades(items: list[dict], market_regime: str = "") -> int:
    """
    Store completed Historical Replay trades — only signals the system would
    have actually taken (BUY / STRONG BUY) with a resolved outcome.
    Simulated with quantity 1 (replay has no position sizing).
    """
    records = []
    for it in items:
        if it.get("historical_action") not in ("BUY", "STRONG BUY"):
            continue
        rec = _from_replay_item(
            it, source="historical_replay", model="replay",
            quantity=1, market_regime=market_regime,
        )
        if rec:
            records.append(rec)
    return record_trades(records)


def record_paper_trade(trade: dict, sector: str = "", market_regime: str = "") -> int:
    """
    Store a completed live paper trade (a SELL from paper_trader).
    Indicators at entry are not available for portfolio trades (entry
    snapshot was not captured at buy time) and are stored as NULL.
    """
    if trade.get("action") != "SELL" or trade.get("entry_price") in (None, 0):
        return 0
    date = str(trade.get("timestamp", ""))[:10]
    rec = {
        "trade_id": f"paper_trade:{trade.get('id', '')}",
        "source": "paper_trade",
        "date": date,
        "symbol": trade.get("symbol", ""),
        "sector": sector,
        "strategy": trade.get("strategy_name", "") or trade.get("exit_type", ""),
        "market_regime": market_regime or trade.get("regime", "") or "",
        "holding_period": None,
        "entry_price": _round(trade.get("entry_price")),
        "exit_price": _round(trade.get("price")),
        "quantity": int(trade.get("quantity", 0) or 0),
        "profit_loss": _round(trade.get("pnl")),
        "return_percent": _round(trade.get("pnl_pct")),
        "opportunity_score": None,
        "trade_quality": None,
        "confidence": _round(trade.get("signal_confidence")),
        "risk_reward": _round(trade.get("rr_ratio")),
        "outcome": trade.get("exit_type", "") or "COMPLETED",
    }
    for c in INDICATOR_COLUMNS:
        rec[c] = None
    return record_trades([rec])


# ── Backfill import ───────────────────────────────────────────────────────────

def import_existing() -> dict:
    """
    Backfill from data that already exists on disk:
      • completed SELL trades in the paper portfolio (state.json)
    Basket tests and replays populate automatically the next time they run.
    """
    from paper_trader import _load_state
    try:
        from market_scanner import _sector_of as _get_sector  # type: ignore
    except ImportError:
        _get_sector = None

    state = _load_state()
    imported = 0
    for trade in state.get("trades", []):
        if trade.get("action") != "SELL":
            continue
        sector = ""
        if _get_sector is not None:
            try:
                sector = _get_sector(trade.get("symbol", "")) or ""
            except Exception:
                sector = ""
        imported += record_paper_trade(trade, sector=sector)
    return {
        "imported_paper_trades": imported,
        "note": (
            "Paper Basket Tests and Historical Replays are recorded "
            "automatically each time they run."
        ),
        **get_summary(),
    }


# ── Queries ───────────────────────────────────────────────────────────────────

def get_trades(limit: int = 200, offset: int = 0) -> list[dict]:
    conn = _connect()
    try:
        cur = conn.execute(
            f"SELECT {', '.join(_ALL_COLUMNS)} FROM trade_intelligence "
            "ORDER BY date DESC, recorded_at DESC LIMIT ? OFFSET ?",
            (max(1, min(int(limit), 1000)), max(0, int(offset))),
        )
        return [dict(zip(_ALL_COLUMNS, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def get_summary() -> dict:
    conn = _connect()
    try:
        total, wins, losses, avg_ret, avg_hold, total_pnl = conn.execute(
            """
            SELECT COUNT(*),
                   COALESCE(SUM(outcome_classification), 0),
                   COALESCE(SUM(1 - outcome_classification), 0),
                   COALESCE(AVG(return_percent), 0),
                   COALESCE(AVG(holding_period), 0),
                   COALESCE(SUM(profit_loss), 0)
            FROM trade_intelligence
            """
        ).fetchone()

        def _breakdown(col: str) -> list[dict]:
            cur = conn.execute(
                f"""
                SELECT COALESCE(NULLIF({col}, ''), 'Unknown') AS k,
                       COUNT(*),
                       COALESCE(SUM(outcome_classification), 0),
                       COALESCE(AVG(return_percent), 0),
                       COALESCE(SUM(profit_loss), 0)
                FROM trade_intelligence GROUP BY k ORDER BY COUNT(*) DESC
                """
            )
            out = []
            for k, n, w, avg_r, pnl in cur.fetchall():
                out.append({
                    "name": k,
                    "trades": n,
                    "wins": w,
                    "losses": n - w,
                    "win_rate": round(100.0 * w / n, 1) if n else 0.0,
                    "avg_return_pct": round(avg_r, 2),
                    "total_pnl": round(pnl, 2),
                })
            return out

        return {
            "total_trades": total,
            "winning_trades": wins,
            "losing_trades": losses,
            "win_rate": round(100.0 * wins / total, 1) if total else 0.0,
            "average_return_pct": round(avg_ret, 2),
            "average_holding_days": round(avg_hold, 1),
            "total_pnl": round(total_pnl, 2),
            "regime_breakdown": _breakdown("market_regime"),
            "strategy_breakdown": _breakdown("strategy"),
            "source_breakdown": _breakdown("source"),
        }
    finally:
        conn.close()


def get_intelligence(limit: int = 200) -> dict:
    return {
        "summary": get_summary(),
        "trades": get_trades(limit=limit),
        "generated_at": datetime.now().isoformat(),
    }
