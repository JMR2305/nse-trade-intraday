"""
Trade Intelligence Database (Sprint 3 — Modules 1 & 2).

A persistent SQLite table of every COMPLETED paper trade, captured from:
  • Paper Basket Test  (old model + improved filtered model)
  • Paper Trades       (portfolio buy/sell in paper_trader.py)
  • Historical Replay  (market_replay.py BUY/STRONG BUY signals)

This module only STORES history. No AI learning happens here — future
learning modules will read from this table.

Module 2 enhancements:
  • 7-way market regime classification — never "Unknown"
  • entry_strategy (how the trade was entered) is separate from
    exit_reason (why the trade was closed)
  • indicator + AI-metric snapshot frozen at entry time
  • deterministic unique key: symbol + entry strategy + entry date +
    holding period (INSERT OR REPLACE dedupe)
  • extended historical statistics (best/worst strategy, sector, regime,
    average win/loss, largest winner/loser)
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timedelta

_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(_DIR, "trade_intelligence.db")
_REGIME_CACHE_PATH = os.path.join(_DIR, "regime_cache.json")

INDICATOR_COLUMNS = [
    "ema9", "ema20", "ema50", "ema200", "rsi", "macd", "macd_signal",
    "vwap", "atr", "adx", "supertrend", "volume_ratio",
]

AI_METRIC_COLUMNS = ["opportunity_score", "trade_quality", "confidence", "risk_reward"]

VALID_REGIMES = [
    "Strong Bullish", "Bullish", "Neutral", "Bearish", "Strong Bearish",
    "High Volatility", "Low Volatility",
]

EXIT_REASON_LABELS = {
    "TARGET_HIT": "Target Hit",
    "STOP_HIT": "Stop Hit",
    "SIGNAL_EXIT": "Signal Exit",
    "TIME_EXIT": "Time Exit",
    "TIME": "Time Exit",
    "MANUAL": "Manual Exit",
    "MANUAL_EXIT": "Manual Exit",
}
VALID_EXIT_REASONS = ["Target Hit", "Stop Hit", "Signal Exit", "Time Exit", "Manual Exit"]

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS trade_intelligence (
    trade_id        TEXT PRIMARY KEY,
    source          TEXT NOT NULL,
    date            TEXT NOT NULL,
    symbol          TEXT NOT NULL,
    sector          TEXT,
    strategy        TEXT,
    entry_strategy  TEXT,
    exit_reason     TEXT,
    market_regime   TEXT,
    volatility      REAL,
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
    "entry_strategy", "exit_reason", "market_regime", "volatility",
    "holding_period", "entry_price", "exit_price",
    "quantity", "profit_loss", "return_percent",
    *INDICATOR_COLUMNS, *AI_METRIC_COLUMNS,
    "outcome", "outcome_classification", "recorded_at",
]

_NEW_COLUMNS = {  # added in Module 2 — migrated via ALTER TABLE
    "entry_strategy": "TEXT",
    "exit_reason": "TEXT",
    "volatility": "REAL",
}


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(_SCHEMA)
    existing = {row[1] for row in conn.execute("PRAGMA table_info(trade_intelligence)")}
    for col, typ in _NEW_COLUMNS.items():
        if col not in existing:
            conn.execute(f"ALTER TABLE trade_intelligence ADD COLUMN {col} {typ}")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ti_date ON trade_intelligence(date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ti_symbol ON trade_intelligence(symbol)")
    conn.commit()
    return conn


def _round(v, nd=2):
    try:
        return round(float(v), nd)
    except (TypeError, ValueError):
        return None


def make_trade_id(symbol: str, entry_strategy: str, entry_date: str,
                  holding_period) -> str:
    """
    Data-integrity unique key: Symbol + Entry Strategy + Entry Date +
    Holding Period. Re-recording the same historical trade always maps to
    the same row (INSERT OR REPLACE) so duplicates are impossible.
    """
    hp = holding_period if holding_period is not None else "na"
    strat = (entry_strategy or "unknown").strip().lower().replace(" ", "_")
    return f"{str(symbol).upper()}|{strat}|{entry_date}|{hp}"


# ── Market regime classification (7 categories, never Unknown) ───────────────

def _load_regime_cache() -> dict:
    try:
        with open(_REGIME_CACHE_PATH) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_regime_cache(cache: dict) -> None:
    try:
        with open(_REGIME_CACHE_PATH, "w") as f:
            json.dump(cache, f)
    except Exception:
        pass


def classify_regime(as_of_date: str | None = None) -> dict:
    """
    Classify the market regime for the Trade Intelligence Database from
    NIFTY 50 index data using ONLY candles up to `as_of_date`.

    Exactly one of 7 categories — never "Unknown":
      Strong Bullish / Bullish / Neutral / Bearish / Strong Bearish
      High Volatility / Low Volatility

    Returns {"regime": str, "volatility": float | None} where volatility is
    annualised NIFTY volatility in percent. Falls back to "Neutral" when
    index data is unavailable. Results are cached per date. This is a
    read-only classifier — it does not touch strategies or scoring logic.
    """
    key = as_of_date or datetime.now().strftime("%Y-%m-%d")
    cache = _load_regime_cache()
    if key in cache:
        return cache[key]

    result = {"regime": "Neutral", "volatility": None}
    try:
        import yfinance as yf

        end_dt = datetime.strptime(key, "%Y-%m-%d") + timedelta(days=1)
        start_dt = end_dt - timedelta(days=180)
        df = yf.Ticker("^NSEI").history(
            start=start_dt.strftime("%Y-%m-%d"),
            end=end_dt.strftime("%Y-%m-%d"),
            interval="1d",
        )
        if df is not None and not df.empty and len(df) >= 55:
            close = df["Close"]
            ema20 = float(close.ewm(span=20, adjust=False).mean().iloc[-1])
            ema50 = float(close.ewm(span=50, adjust=False).mean().iloc[-1])
            last = float(close.iloc[-1])
            ret5 = (last - float(close.iloc[-6])) / float(close.iloc[-6]) * 100.0
            daily = close.pct_change().dropna().tail(20)
            ann_vol = float(daily.std()) * (252 ** 0.5) * 100.0

            if ann_vol >= 22.0:
                regime = "High Volatility"
            elif ann_vol <= 8.0:
                regime = "Low Volatility"
            elif ema20 > ema50 and ret5 > 2.0:
                regime = "Strong Bullish"
            elif ema20 > ema50 and ret5 > 0.5:
                regime = "Bullish"
            elif ema20 > ema50:
                regime = "Neutral"
            elif ret5 < -2.0:
                regime = "Strong Bearish"
            elif ema20 < ema50:
                regime = "Bearish"
            else:
                regime = "Neutral"
            result = {"regime": regime, "volatility": round(ann_vol, 2)}
            cache[key] = result
            _save_regime_cache(cache)
    except Exception:
        pass  # keep the Neutral fallback — never Unknown, never crash
    return result


_LEGACY_REGIME_MAP = {
    "bullish": "Bullish",
    "strong bullish": "Strong Bullish",
    "neutral-bullish": "Neutral",
    "neutral": "Neutral",
    "neutral-bearish": "Neutral",
    "bearish": "Bearish",
    "strong bearish": "Strong Bearish",
    "high volatility": "High Volatility",
    "low volatility": "Low Volatility",
}


def normalize_regime(name: str | None, entry_date: str) -> dict:
    """Map any incoming regime label onto the 7 valid categories; when the
    label is missing/Unknown, classify from NIFTY data as of the entry date."""
    mapped = _LEGACY_REGIME_MAP.get((name or "").strip().lower())
    if mapped:
        return {"regime": mapped, "volatility": None}
    return classify_regime(entry_date)


def normalize_exit_reason(raw: str | None, default: str = "Signal Exit") -> str:
    if not raw:
        return default
    if raw in VALID_EXIT_REASONS:
        return raw
    return EXIT_REASON_LABELS.get(str(raw).strip().upper(), default)


# ── Storage ───────────────────────────────────────────────────────────────────

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
        # keep legacy `strategy` column mirroring entry_strategy
        row["strategy"] = row.get("entry_strategy") or row.get("strategy") or ""
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
    entry_strategy = it.get("best_strategy_name", "") or "Unknown"
    regime_info = normalize_regime(market_regime, it["scan_date"])
    rec = {
        "trade_id": make_trade_id(
            it["stock"], entry_strategy, it["scan_date"], it.get("holding_period")
        ),
        "source": source,
        "date": it["scan_date"],
        "symbol": it["stock"],
        "sector": it.get("sector", ""),
        "entry_strategy": entry_strategy,
        # basket/replay positions close when the holding period expires
        "exit_reason": "Time Exit",
        "market_regime": regime_info["regime"],
        "volatility": regime_info.get("volatility"),
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


def _holding_days(buy_ts: str | None, sell_ts: str | None) -> int | None:
    try:
        b = datetime.fromisoformat(str(buy_ts))
        s = datetime.fromisoformat(str(sell_ts))
        return max(0, (s.date() - b.date()).days)
    except (TypeError, ValueError):
        return None


def record_paper_trade(
    trade: dict,
    sector: str = "",
    market_regime: str = "",
    buy_trade: dict | None = None,
) -> int:
    """
    Store a completed live paper trade (a SELL from paper_trader).
    The matching BUY trade supplies the immutable entry snapshot:
    entry strategy, indicators at entry, and AI metrics captured at buy time.
    """
    if trade.get("action") != "SELL" or trade.get("entry_price") in (None, 0):
        return 0
    buy = buy_trade or {}
    sell_date = str(trade.get("timestamp", ""))[:10]
    entry_date = str(buy.get("timestamp", ""))[:10] or sell_date
    entry_strategy = buy.get("strategy_name", "") or trade.get("strategy_name", "") or "AI Scan"
    holding = _holding_days(buy.get("timestamp"), trade.get("timestamp"))
    regime_info = normalize_regime(
        market_regime or buy.get("market_regime_at_entry", "") or "", entry_date
    )
    ind = buy.get("indicators_at_entry") or {}
    # Per-exit discriminator: the sell timestamp is stable in state.json, so
    # re-imports stay idempotent while distinct partial exits from the same
    # entry (same day / holding period) never overwrite each other.
    base_id = make_trade_id(
        trade.get("symbol", ""), entry_strategy, entry_date, holding
    )
    sell_ts = str(trade.get("timestamp", "")).replace(" ", "_").replace(":", "-")
    rec = {
        "trade_id": f"{base_id}|{sell_ts}" if sell_ts else base_id,
        "source": "paper_trade",
        "date": entry_date,
        "symbol": trade.get("symbol", ""),
        "sector": sector,
        "entry_strategy": entry_strategy,
        "exit_reason": normalize_exit_reason(trade.get("exit_type")),
        "market_regime": regime_info["regime"],
        "volatility": regime_info.get("volatility") or _round(buy.get("volatility_at_entry")),
        "holding_period": holding,
        "entry_price": _round(trade.get("entry_price")),
        "exit_price": _round(trade.get("price")),
        "quantity": int(trade.get("quantity", 0) or 0),
        "profit_loss": _round(trade.get("pnl")),
        "return_percent": _round(trade.get("pnl_pct")),
        "opportunity_score": _round(buy.get("opportunity_score")),
        "trade_quality": _round(buy.get("trade_quality")),
        "confidence": _round(buy.get("signal_confidence") or trade.get("signal_confidence")),
        "risk_reward": _round(buy.get("rr_ratio") or trade.get("rr_ratio")),
        "outcome": trade.get("exit_type", "") or "COMPLETED",
    }
    for c in INDICATOR_COLUMNS:
        rec[c] = _round(ind.get(c), 4)
    return record_trades([rec])


def find_buy_trade(state: dict, symbol: str, before_ts: str | None = None) -> dict | None:
    """
    Lot-aware (FIFO) match: find the BUY lot that the SELL at `before_ts`
    consumed the most shares from.

    Walks the trade history in order, tracking the remaining quantity of
    each BUY lot. Every SELL consumes shares from the oldest open lots
    first (FIFO). For the SELL identified by `before_ts` (its timestamp),
    the lot that supplied the largest share count is returned so that the
    stored entry snapshot (strategy, indicators, holding period) reflects
    the position that was actually closed — even with multiple buys or
    partial exits.
    """
    sym = str(symbol).upper()
    lots: list[dict] = []  # [{"trade": buy_dict, "remaining": int}]
    target_ts = str(before_ts) if before_ts else None

    for t in state.get("trades", []):
        if str(t.get("symbol", "")).upper() != sym:
            continue
        action = t.get("action")
        if action == "BUY":
            lots.append({"trade": t, "remaining": int(t.get("quantity", 0) or 0)})
            continue
        if action != "SELL":
            continue
        # Consume FIFO lots for this sell
        qty = int(t.get("quantity", 0) or 0)
        consumed: dict[int, int] = {}  # lot index -> shares taken
        for i, lot in enumerate(lots):
            if qty <= 0:
                break
            take = min(lot["remaining"], qty)
            if take > 0:
                lot["remaining"] -= take
                qty -= take
                consumed[i] = take
        is_target = (
            target_ts is None or str(t.get("timestamp", "")) == target_ts
        )
        if is_target:
            if consumed:
                best_i = max(consumed, key=lambda i: consumed[i])
                return lots[best_i]["trade"]
            # Sell with no matching open lot: fall back to latest BUY
            return lots[-1]["trade"] if lots else None
    # target sell not found in history (e.g. recorded before _save_state):
    # fall back to the oldest lot that still has remaining shares
    for lot in lots:
        if lot["remaining"] > 0:
            return lot["trade"]
    return lots[-1]["trade"] if lots else None


# ── Backfill import ───────────────────────────────────────────────────────────

def import_existing() -> dict:
    """
    Backfill from data that already exists on disk:
      • completed SELL trades in the paper portfolio (state.json)
    Also repairs older rows: fills in valid market regimes and exit
    reasons for records stored before Module 2.
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
        buy = find_buy_trade(state, trade.get("symbol", ""), trade.get("timestamp"))
        imported += record_paper_trade(trade, sector=sector, buy_trade=buy)

    repaired = repair_legacy_rows()
    return {
        "imported_paper_trades": imported,
        "repaired_rows": repaired,
        "note": (
            "Paper Basket Tests and Historical Replays are recorded "
            "automatically each time they run."
        ),
        **get_summary(),
    }


def repair_legacy_rows() -> int:
    """
    One-time data repair for rows stored before Module 2:
      • market_regime outside the 7 valid categories → reclassified by date
      • missing exit_reason → derived from outcome/source
      • missing entry_strategy → copied from legacy strategy column
      • trade_id migrated to the new unique key (dedupes automatically)
    """
    conn = _connect()
    repaired = 0
    try:
        rows = conn.execute(
            "SELECT trade_id, source, date, symbol, strategy, entry_strategy, "
            "exit_reason, market_regime, volatility, holding_period, outcome "
            "FROM trade_intelligence"
        ).fetchall()
        for (tid, source, date, symbol, strategy, entry_strategy,
             exit_reason, regime, vol, holding, outcome) in rows:
            if source == "paper_trade" and (":" in tid or tid.count("|") < 4):
                # legacy paper-trade row (pre-Module 2 key, or key without the
                # per-exit sell-timestamp discriminator);
                # import_existing() recreates it correctly from state.json
                conn.execute(
                    "DELETE FROM trade_intelligence WHERE trade_id = ?", (tid,)
                )
                repaired += 1
                continue
            new_entry = entry_strategy or ""
            if not new_entry:
                # legacy paper trades stored the exit type in `strategy`
                if (strategy or "").strip().upper() in EXIT_REASON_LABELS:
                    new_entry = "AI Scan"
                else:
                    new_entry = strategy or "Unknown"
            new_exit = exit_reason or ""
            if not new_exit:
                raw = (outcome or "").strip().upper()
                if raw in EXIT_REASON_LABELS:
                    new_exit = EXIT_REASON_LABELS[raw]
                elif source in ("paper_basket", "historical_replay"):
                    new_exit = "Time Exit"
                else:
                    new_exit = "Signal Exit"
            new_regime, new_vol = regime, vol
            if regime not in VALID_REGIMES:
                info = normalize_regime(regime, date)
                new_regime = info["regime"]
                new_vol = vol if vol is not None else info.get("volatility")
            if source == "paper_trade":
                # already carries the per-exit discriminator — keep it
                new_tid = tid
            else:
                new_tid = make_trade_id(symbol, new_entry, date, holding)
            if (new_entry, new_exit, new_regime, new_vol, new_tid) == (
                entry_strategy, exit_reason, regime, vol, tid
            ):
                continue
            if new_tid != tid:
                dup = conn.execute(
                    "SELECT 1 FROM trade_intelligence WHERE trade_id = ?", (new_tid,)
                ).fetchone()
                if dup:
                    conn.execute(
                        "DELETE FROM trade_intelligence WHERE trade_id = ?", (tid,)
                    )
                    repaired += 1
                    continue
            conn.execute(
                "UPDATE trade_intelligence SET trade_id = ?, entry_strategy = ?, "
                "strategy = ?, exit_reason = ?, market_regime = ?, volatility = ? "
                "WHERE trade_id = ?",
                (new_tid, new_entry, new_entry, new_exit, new_regime, new_vol, tid),
            )
            repaired += 1
        conn.commit()
        return repaired
    finally:
        conn.close()


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


def _best_worst(breakdown: list[dict]) -> tuple[dict | None, dict | None]:
    ranked = sorted(
        (b for b in breakdown if b["trades"] > 0),
        key=lambda b: b["avg_return_pct"],
        reverse=True,
    )
    if not ranked:
        return None, None
    best = {"name": ranked[0]["name"], "avg_return_pct": ranked[0]["avg_return_pct"],
            "trades": ranked[0]["trades"]}
    worst = {"name": ranked[-1]["name"], "avg_return_pct": ranked[-1]["avg_return_pct"],
             "trades": ranked[-1]["trades"]}
    return best, worst


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
                SELECT COALESCE(NULLIF({col}, ''), 'Unclassified') AS k,
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

        regime_breakdown = _breakdown("market_regime")
        strategy_breakdown = _breakdown("entry_strategy")
        exit_reason_breakdown = _breakdown("exit_reason")
        sector_breakdown = _breakdown("sector")

        avg_win, avg_loss = conn.execute(
            """
            SELECT
              (SELECT AVG(profit_loss) FROM trade_intelligence WHERE outcome_classification = 1),
              (SELECT AVG(profit_loss) FROM trade_intelligence WHERE outcome_classification = 0)
            """
        ).fetchone()

        def _extreme(order: str) -> dict | None:
            row = conn.execute(
                "SELECT symbol, profit_loss, return_percent, date FROM trade_intelligence "
                f"WHERE profit_loss IS NOT NULL ORDER BY profit_loss {order} LIMIT 1"
            ).fetchone()
            if not row:
                return None
            return {"symbol": row[0], "profit_loss": round(row[1] or 0, 2),
                    "return_percent": round(row[2] or 0, 2), "date": row[3]}

        best_strategy, worst_strategy = _best_worst(strategy_breakdown)
        best_sector, worst_sector = _best_worst(sector_breakdown)
        best_regime, worst_regime = _best_worst(regime_breakdown)

        return {
            "total_trades": total,
            "winning_trades": wins,
            "losing_trades": losses,
            "win_rate": round(100.0 * wins / total, 1) if total else 0.0,
            "average_return_pct": round(avg_ret, 2),
            "average_holding_days": round(avg_hold, 1),
            "total_pnl": round(total_pnl, 2),
            "regime_breakdown": regime_breakdown,
            "strategy_breakdown": strategy_breakdown,
            "exit_reason_breakdown": exit_reason_breakdown,
            "sector_breakdown": sector_breakdown,
            "source_breakdown": _breakdown("source"),
            "statistics": {
                "best_strategy": best_strategy,
                "worst_strategy": worst_strategy,
                "best_sector": best_sector,
                "worst_sector": worst_sector,
                "best_regime": best_regime,
                "worst_regime": worst_regime,
                "average_winning_trade": round(avg_win, 2) if avg_win is not None else None,
                "average_losing_trade": round(avg_loss, 2) if avg_loss is not None else None,
                "average_holding_days": round(avg_hold, 1),
                "largest_winner": _extreme("DESC"),
                "largest_loser": _extreme("ASC"),
            },
        }
    finally:
        conn.close()


def get_intelligence(limit: int = 200) -> dict:
    return {
        "summary": get_summary(),
        "trades": get_trades(limit=limit),
        "generated_at": datetime.now().isoformat(),
    }
