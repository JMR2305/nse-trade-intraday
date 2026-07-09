"""
market_scanner.py
Sprint 1.5 — Universe Scanner.

Scans the full NIFTY 50 universe, runs every validated strategy on each
stock (using the exact same walk-forward engine as the Strategy Lab /
Optimizer), selects the best-performing strategy per stock, and produces:

  1. Opportunity ranking      — Opportunity Score, Trade Quality, Confidence,
                                 Expected Risk/Reward, Final Action
  2. Sector Strength          — stocks grouped by sector, ranked by avg score
  3. Dynamic AI Watchlist     — top 10 opportunities, auto-selected
  4. Heat Map                 — GREEN / YELLOW / RED per stock
  5. Dashboard Summary        — scan-wide aggregate stats

PAPER TRADING ONLY — this module never places real orders. It only reads
historical market data and ranks opportunities for informational purposes.
"""

import math
from datetime import datetime
from typing import TypedDict

from config import SECTOR_MAP, NIFTY_50, INITIAL_CAPITAL
from market_data_engine import fetch_candles_df
from indicator_engine import compute_indicators_df
from strategies import get_strategy, LAB_STRATEGY_IDS
from backtesting_engine import _run_lab_walk, WARMUP_BARS

# ── Scan configuration ──────────────────────────────────────────────────────────

SCAN_PERIOD   = "6mo"     # lookback window used to evaluate strategies per stock
SCAN_INTERVAL = "1d"
MIN_BARS      = WARMUP_BARS + 10

# Final Action thresholds (0–100 Opportunity Score)
ACTION_STRONG_BUY = 78.0
ACTION_BUY        = 62.0
ACTION_WATCH      = 42.0
# below ACTION_WATCH => IGNORE

WATCHLIST_SIZE = 10


# ── TypedDicts ───────────────────────────────────────────────────────────────────

class ScanItem(TypedDict):
    rank:               int
    stock:              str
    sector:             str
    price:              float
    # Strategy selection
    best_strategy_id:   str
    best_strategy_name: str
    strategy_type:      str
    best_regime:        str
    strategies_tested:  int
    live_signal:        bool     # is best strategy's entry condition true on the latest bar right now?
    signal_reason:      str
    # Ranking metrics
    opportunity_score:  float    # 0–100 composite
    trade_quality:      float    # 0–100 (historical performance quality of chosen strategy)
    confidence:         float    # 0–100 (reliability-adjusted)
    expected_risk:      float    # ₹ risk per share position (approx, 1% capital rule)
    expected_reward:    float    # ₹ reward per share position
    rr_ratio:           float
    final_action:       str      # STRONG BUY | BUY | WATCH | IGNORE
    heat:               str      # GREEN | YELLOW | RED
    # Backing performance stats (from 6mo backtest of the chosen strategy)
    win_rate:           float
    profit_factor:      float
    net_pnl_pct:        float
    total_trades:       int
    sharpe_ratio:       float
    # Trade levels (paper only — indicative)
    entry_price:        float
    stop_loss:          float
    target:             float
    # Signal Quality Layer (v1.0) raw inputs
    above_ema20:        bool
    above_ema50:        bool
    volume_ratio:       float
    rsi:                float
    macd_hist:          float
    error:              str | None


class SectorStrength(TypedDict):
    rank:              int
    sector:            str
    stock_count:       int
    avg_opportunity:   float
    strong_buys:       int
    buys:              int
    watches:           int
    ignores:           int
    strength_label:    str    # STRONG | NEUTRAL | WEAK


class DashboardSummary(TypedDict):
    total_scanned:      int
    strong_buy_count:   int
    buy_count:          int
    watch_count:        int
    ignore_count:       int
    strongest_sector:   str
    weakest_sector:     str
    best_stock:         str
    best_stock_score:   float
    avg_market_score:   float
    scanned_at:         str


class MarketScanResult(TypedDict):
    scanned_at:   str
    universe_size: int
    items:        list         # ScanItem[], sorted by opportunity_score desc
    watchlist:    list         # top N stocks (list[str])
    sectors:      list         # SectorStrength[], sorted by avg_opportunity desc
    summary:      DashboardSummary


# ── Helpers ───────────────────────────────────────────────────────────────────

_SECTOR_LOOKUP: dict[str, str] = {
    sym: sector for sector, syms in SECTOR_MAP.items() for sym in syms
}


def _sector_of(symbol: str) -> str:
    return _SECTOR_LOOKUP.get(symbol.upper(), "OTHER")


def _final_action(score: float) -> str:
    if score >= ACTION_STRONG_BUY:
        return "STRONG BUY"
    if score >= ACTION_BUY:
        return "BUY"
    if score >= ACTION_WATCH:
        return "WATCH"
    return "IGNORE"


def _heat_of(action: str) -> str:
    if action in ("STRONG BUY", "BUY"):
        return "GREEN"
    if action == "WATCH":
        return "YELLOW"
    return "RED"


def _strategy_perf_score(m: dict) -> float:
    """
    Composite historical-performance score (0–100) for one strategy on one
    stock, using the same backtest metrics computed for the Optimizer/Lab.
    Rewards win rate, profit factor, net return, and Sharpe — scaled down
    for strategies with very few trades (low reliability).
    """
    trades = m.get("total_trades", 0)
    if trades == 0:
        return 0.0

    wr      = max(0.0, min(m.get("win_rate", 0.0), 100.0))
    pf      = max(0.0, min(m.get("profit_factor", 0.0), 5.0))
    pnl_pct = max(-30.0, min(m.get("net_pnl_pct", 0.0), 30.0))
    sharpe  = max(-3.0, min(m.get("sharpe_ratio", 0.0), 3.0))

    raw = (
        (wr / 100.0) * 35.0 +
        (pf / 5.0)   * 30.0 +
        ((pnl_pct + 30.0) / 60.0) * 20.0 +
        ((sharpe + 3.0) / 6.0)    * 15.0
    )

    # Reliability discount: strategies with <8 trades over 6mo are less trustworthy
    reliability = min(1.0, trades / 8.0)
    score = raw * (0.35 + 0.65 * reliability)
    return round(max(0.0, min(100.0, score)), 1)


def _confidence_score(perf_score: float, trades: int, live_signal: bool) -> float:
    """0–100 confidence in the current recommendation."""
    reliability = min(1.0, trades / 10.0)
    base = perf_score * 0.75 + reliability * 25.0
    if live_signal:
        base = min(100.0, base + 8.0)
    return round(max(0.0, min(100.0, base)), 1)


def _rr_normalized(rr_ratio: float) -> float:
    return round(min(100.0, max(0.0, rr_ratio / 4.0 * 100.0)), 1)


def _opportunity_score(perf_score: float, confidence: float, rr_ratio: float, live_signal: bool) -> float:
    """
    Opportunity Score (0–100):
      trade_quality (perf_score) × 0.45
      confidence               × 0.30
      rr_score                 × 0.15
      live-signal bonus        × 0.10  (fires now vs. merely a good historical setup)
    """
    rr_score   = _rr_normalized(rr_ratio)
    live_bonus = 100.0 if live_signal else 40.0
    score = (
        perf_score * 0.45 +
        confidence * 0.30 +
        rr_score   * 0.15 +
        live_bonus * 0.10
    )
    return round(max(0.0, min(100.0, score)), 1)


def _empty_scan_item(symbol: str, error: str) -> ScanItem:
    return ScanItem(
        rank=0, stock=symbol.upper(), sector=_sector_of(symbol), price=0.0,
        best_strategy_id="", best_strategy_name="", strategy_type="", best_regime="",
        strategies_tested=0, live_signal=False, signal_reason=error,
        opportunity_score=0.0, trade_quality=0.0, confidence=0.0,
        expected_risk=0.0, expected_reward=0.0, rr_ratio=0.0,
        final_action="IGNORE", heat="RED",
        win_rate=0.0, profit_factor=0.0, net_pnl_pct=0.0, total_trades=0, sharpe_ratio=0.0,
        entry_price=0.0, stop_loss=0.0, target=0.0,
        above_ema20=False, above_ema50=False, volume_ratio=0.0, rsi=0.0, macd_hist=0.0,
        error=error,
    )


# ── Per-stock scan ────────────────────────────────────────────────────────────

def scan_stock(symbol: str, capital: float = INITIAL_CAPITAL) -> ScanItem:
    """
    Fetch data once, compute indicators once, run every validated strategy
    (LAB_STRATEGY_IDS) on the same data, and select the best one by
    historical performance score. Also evaluates whether that strategy's
    entry condition is true right now (live_signal).
    """
    try:
        df = fetch_candles_df(symbol, interval=SCAN_INTERVAL, period=SCAN_PERIOD)
    except Exception as exc:
        return _empty_scan_item(symbol, f"Data fetch failed: {exc}")

    if df.empty or len(df) < MIN_BARS:
        return _empty_scan_item(symbol, f"Insufficient data: {len(df)} bars (need {MIN_BARS}+)")

    try:
        enriched = compute_indicators_df(df)
    except Exception as exc:
        return _empty_scan_item(symbol, f"Indicator computation failed: {exc}")

    rows = enriched.reset_index(drop=False)
    last_row  = rows.iloc[-1]
    prev_row  = rows.iloc[-2]
    price     = float(last_row.get("close", 0.0) or 0.0)

    if price <= 0:
        return _empty_scan_item(symbol, "No valid closing price")

    best = None  # (perf_score, strategy_id, strategy, metrics, live_signal, reason)

    for sid in LAB_STRATEGY_IDS:
        try:
            strategy = get_strategy(sid)
            metrics  = _run_lab_walk(rows, strategy, capital)
            perf     = _strategy_perf_score(metrics)
            live_ok, reason = strategy.check_entry(last_row, prev_row)
        except Exception:
            continue

        # Prefer strategies currently signalling; break ties by perf score.
        candidate_rank = (1 if live_ok else 0, perf)
        if best is None or candidate_rank > (1 if best[4] else 0, best[0]):
            best = (perf, sid, strategy, metrics, live_ok, reason)

    if best is None:
        return _empty_scan_item(symbol, "No strategy could be evaluated")

    perf_score, sid, strategy, metrics, live_signal, reason = best

    confidence = _confidence_score(perf_score, metrics.get("total_trades", 0), live_signal)

    # Trade levels — computed off the latest bar using the chosen strategy's own rules
    try:
        stop_loss = strategy.compute_stop_loss(last_row, price)
        target    = strategy.compute_target(price, stop_loss)
    except Exception:
        stop_loss, target = 0.0, 0.0

    risk_per_share   = max(0.0, price - stop_loss) if stop_loss > 0 else 0.0
    reward_per_share = max(0.0, target - price) if target > 0 else 0.0
    rr_ratio         = round(reward_per_share / risk_per_share, 2) if risk_per_share > 0 else 0.0

    opp_score = _opportunity_score(perf_score, confidence, rr_ratio, live_signal)
    action    = _final_action(opp_score)
    heat      = _heat_of(action)

    return ScanItem(
        rank=0,
        stock=symbol.upper(),
        sector=_sector_of(symbol),
        price=round(price, 2),
        best_strategy_id=strategy.id,
        best_strategy_name=strategy.name,
        strategy_type=strategy.type,
        best_regime=strategy.best_regime,
        strategies_tested=len(LAB_STRATEGY_IDS),
        live_signal=bool(live_signal),
        signal_reason=reason or "",
        opportunity_score=opp_score,
        trade_quality=perf_score,
        confidence=confidence,
        expected_risk=round(risk_per_share, 2),
        expected_reward=round(reward_per_share, 2),
        rr_ratio=rr_ratio,
        final_action=action,
        heat=heat,
        win_rate=metrics.get("win_rate", 0.0),
        profit_factor=min(metrics.get("profit_factor", 0.0), 999.0),
        net_pnl_pct=metrics.get("net_pnl_pct", 0.0),
        total_trades=metrics.get("total_trades", 0),
        sharpe_ratio=metrics.get("sharpe_ratio", 0.0),
        entry_price=round(price, 2),
        stop_loss=stop_loss,
        target=target,
        above_ema20=bool(price > float(last_row.get("ema20", 0.0) or 0.0) > 0),
        above_ema50=bool(price > float(last_row.get("ema50", 0.0) or 0.0) > 0),
        volume_ratio=round(float(last_row.get("volume_ratio", 0.0) or 0.0), 2),
        rsi=round(float(last_row.get("rsi", 0.0) or 0.0), 1),
        macd_hist=round(float(last_row.get("macd_hist", 0.0) or 0.0), 4),
        error=None,
    )


# ── Sector strength ───────────────────────────────────────────────────────────

def _sector_strength(items: list[ScanItem]) -> list[SectorStrength]:
    by_sector: dict[str, list[ScanItem]] = {}
    for it in items:
        by_sector.setdefault(it["sector"], []).append(it)

    sectors: list[SectorStrength] = []
    for sector, stocks in by_sector.items():
        valid = [s for s in stocks if s["error"] is None]
        avg = round(sum(s["opportunity_score"] for s in valid) / len(valid), 1) if valid else 0.0
        strong = sum(1 for s in valid if s["final_action"] == "STRONG BUY")
        buys   = sum(1 for s in valid if s["final_action"] == "BUY")
        watch  = sum(1 for s in valid if s["final_action"] == "WATCH")
        ignore = sum(1 for s in valid if s["final_action"] == "IGNORE")

        if avg >= ACTION_BUY:
            label = "STRONG"
        elif avg >= ACTION_WATCH:
            label = "NEUTRAL"
        else:
            label = "WEAK"

        sectors.append(SectorStrength(
            rank=0, sector=sector, stock_count=len(stocks),
            avg_opportunity=avg, strong_buys=strong, buys=buys,
            watches=watch, ignores=ignore, strength_label=label,
        ))

    sectors.sort(key=lambda s: s["avg_opportunity"], reverse=True)
    for i, s in enumerate(sectors, start=1):
        s["rank"] = i
    return sectors


# ── Full universe scan ────────────────────────────────────────────────────────

def run_market_scan(
    symbols: list[str] | None = None,
    capital: float = INITIAL_CAPITAL,
) -> MarketScanResult:
    """
    Scan the full NIFTY 50 universe (or a custom symbol list), rank
    opportunities, compute sector strength, build the dynamic watchlist,
    heat map, and dashboard summary.

    Paper trading only — no real orders are placed.
    """
    universe = symbols if symbols else list(NIFTY_50)

    items: list[ScanItem] = []
    for sym in universe:
        items.append(scan_stock(sym, capital=capital))

    # Rank by opportunity score (errors sink to the bottom)
    items.sort(key=lambda it: (it["error"] is None, it["opportunity_score"]), reverse=True)
    for i, it in enumerate(items, start=1):
        it["rank"] = i

    # ── Signal Quality Layer (v1.0): quality score + strict filters ──────
    # Downgrades weak BUY/STRONG BUY calls to WATCH/IGNORE and refreshes
    # the heat map to match the filtered action.
    from signal_quality import get_market_regime_as_of, annotate_items_with_quality
    regime_info = get_market_regime_as_of(None)
    annotate_items_with_quality(items, action_key="final_action", regime_info=regime_info)
    for it in items:
        it["heat"] = _heat_of(it["final_action"])

    valid_items = [it for it in items if it["error"] is None]

    sectors = _sector_strength(items)

    watchlist = [it["stock"] for it in valid_items[:WATCHLIST_SIZE]]

    strong_buy_count = sum(1 for it in valid_items if it["final_action"] == "STRONG BUY")
    buy_count        = sum(1 for it in valid_items if it["final_action"] == "BUY")
    watch_count      = sum(1 for it in valid_items if it["final_action"] == "WATCH")
    ignore_count     = sum(1 for it in valid_items if it["final_action"] == "IGNORE")

    avg_score = (
        round(sum(it["opportunity_score"] for it in valid_items) / len(valid_items), 1)
        if valid_items else 0.0
    )

    best_stock       = valid_items[0]["stock"] if valid_items else ""
    best_stock_score = valid_items[0]["opportunity_score"] if valid_items else 0.0

    strongest_sector = sectors[0]["sector"] if sectors else ""
    weakest_sector   = sectors[-1]["sector"] if sectors else ""

    summary = DashboardSummary(
        total_scanned=len(items),
        strong_buy_count=strong_buy_count,
        buy_count=buy_count,
        watch_count=watch_count,
        ignore_count=ignore_count,
        strongest_sector=strongest_sector,
        weakest_sector=weakest_sector,
        best_stock=best_stock,
        best_stock_score=best_stock_score,
        avg_market_score=avg_score,
        scanned_at=datetime.now().isoformat(),
    )

    return MarketScanResult(
        scanned_at=summary["scanned_at"],
        universe_size=len(universe),
        items=items,
        watchlist=watchlist,
        sectors=sectors,
        summary=summary,
    )
