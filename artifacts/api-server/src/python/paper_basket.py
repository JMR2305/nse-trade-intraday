"""
paper_basket.py
Paper Basket Testing Layer (v0.9).

Simulates buying an equal-quantity basket of stocks selected from the
*previous* trading day's data, then measures paper P&L in rupees.

PAPER TRADING ONLY — no real orders are ever placed. Reads historical
market data (yfinance) purely for research/testing purposes.

Lookahead-bias safeguard (same discipline as market_replay.py):
  - Stock SELECTION uses only candles with timestamp <= selection_date.
  - The BUY price is the next trading day's OPEN (the first bar strictly
    after selection_date) — never a price available before/at selection.
  - The SELL price is the CLOSE `holding_period` trading days after the
    buy day. Future candles are used exclusively for buy/sell pricing,
    never fed back into the selection step.
"""

from datetime import datetime, timedelta
from typing import TypedDict

import pandas as pd

from config import SECTOR_MAP, NIFTY_50, INITIAL_CAPITAL
from market_replay import _fetch_raw_df, replay_stock
from market_scanner import _sector_of
from signal_quality import (
    get_market_regime_as_of, annotate_items_with_quality,
    STRICT_MIN_SCORE, STRICT_MIN_CONFIDENCE, STRICT_MIN_RR, NO_TRADES_MESSAGE,
)
from signal_learning import learn_from_outcomes, load_weights

# ── Config ──────────────────────────────────────────────────────────────────

VALID_HOLDING_DAYS = {1, 3, 5, 10}
VALID_METHODS = {
    "opportunity_score",   # Top scanner opportunity score
    "gainers",             # Top previous day gainers
    "volume_spike",        # Top previous day volume spike
    "sector_strength",     # Top sector strength stocks
}
METHOD_LABELS = {
    "opportunity_score": "Top Scanner Opportunity Score",
    "gainers":           "Top Previous Day Gainers",
    "volume_spike":      "Top Previous Day Volume Spike",
    "sector_strength":   "Top Sector Strength Stocks",
}
DEFAULT_NUM_STOCKS = 10
DEFAULT_QUANTITY = 10
VOLUME_AVG_WINDOW = 20   # trading days used to compute average volume baseline

WARNING_TEXT = "This is historical paper testing only. No real orders are placed."


# ── TypedDicts ────────────────────────────────────────────────────────────────

class BasketItem(TypedDict):
    stock:              str
    sector:             str
    selection_reason:   str
    rank_metric:        float
    buy_date:           str
    buy_price:          float
    sell_date:          str
    sell_price:         float
    quantity:           int
    investment:         float
    pnl_rupees:         float
    pnl_pct:            float
    outcome:            str
    error:              str | None


class BasketSummary(TypedDict):
    total_investment:    float
    final_value:         float
    net_pnl:             float
    net_return_pct:      float
    winning_stocks:      int
    losing_stocks:       int
    win_rate:            float
    best_stock:          str
    best_stock_return:   float
    worst_stock:         str
    worst_stock_return:  float
    average_return_pct:  float
    max_loss_stock:      str
    max_loss_rupees:     float


class PaperBasketResult(TypedDict):
    selection_date:   str
    buy_date:         str
    holding_period:   int
    method:           str
    method_label:     str
    num_stocks:       int
    quantity:         int
    items:            list   # BasketItem[]
    summary:          BasketSummary
    warning:          str


def classify_basket_outcome(pnl_pct: float | None) -> str:
    """
    Basket-specific 5-tier outcome classification by realized return %:
      > +5%        -> Excellent
      +2% to +5%   -> Good
      0% to +2%    -> Weak Profit
      0% to -2%    -> Small Loss
      < -2%        -> Failed
    """
    if pnl_pct is None:
        return "Pending"
    if pnl_pct > 5.0:
        return "Excellent"
    if pnl_pct >= 2.0:
        return "Good"
    if pnl_pct >= 0.0:
        return "Weak Profit"
    if pnl_pct >= -2.0:
        return "Small Loss"
    return "Failed"


# ── Per-stock as-of profile (cheap — no strategy backtest) ───────────────────

def _fetch_profile_df(symbol: str, selection_date: str, holding_period: int) -> pd.DataFrame | None:
    """
    Fetch a window of raw daily candles wide enough to cover:
      - VOLUME_AVG_WINDOW+ trailing days before selection_date (for gainers/
        volume-spike ranking), and
      - `holding_period` trading days after the next trading day (for the
        buy/sell simulation).
    Returns None if the fetch fails or data is insufficient.
    """
    try:
        sel_dt = datetime.strptime(selection_date, "%Y-%m-%d")
    except ValueError:
        return None

    lookback_start = sel_dt - timedelta(days=90)
    future_end = sel_dt + timedelta(days=holding_period * 3 + 12)

    try:
        df = _fetch_raw_df(
            symbol, "1d",
            start=lookback_start.strftime("%Y-%m-%d"),
            end=future_end.strftime("%Y-%m-%d"),
        )
    except Exception:
        return None

    if df is None or df.empty:
        return None
    return df


def _split_as_of_future(df: pd.DataFrame, selection_date: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    sel_dt = datetime.strptime(selection_date, "%Y-%m-%d")
    cutoff = sel_dt + timedelta(hours=23, minutes=59)
    idx_naive = df.index.tz_localize(None) if df.index.tz is not None else df.index
    as_of_mask = idx_naive <= cutoff
    as_of_df = df[as_of_mask]
    future_df = df[~as_of_mask]
    return as_of_df, future_df


def _gainer_metric(as_of_df: pd.DataFrame) -> float | None:
    """% change of selection_date's close vs. the prior trading day's close."""
    if len(as_of_df) < 2:
        return None
    prev_close = float(as_of_df.iloc[-2]["close"])
    last_close = float(as_of_df.iloc[-1]["close"])
    if prev_close <= 0:
        return None
    return round((last_close - prev_close) / prev_close * 100.0, 2)


def _volume_spike_metric(as_of_df: pd.DataFrame) -> float | None:
    """Ratio of selection_date's volume to the trailing average volume (x)."""
    if len(as_of_df) < VOLUME_AVG_WINDOW + 1:
        return None
    trailing = as_of_df.iloc[-(VOLUME_AVG_WINDOW + 1):-1]["volume"]
    avg_vol = float(trailing.mean())
    last_vol = float(as_of_df.iloc[-1]["volume"])
    if avg_vol <= 0:
        return None
    return round(last_vol / avg_vol, 2)


def _buy_sell_from_future(future_df: pd.DataFrame, holding_period: int) -> tuple[str, float, str, float] | None:
    """
    Buy at the next trading day's OPEN (first future bar), sell at the CLOSE
    `holding_period` trading days later (index holding_period - 1 in the
    future series, i.e. holding_period=1 => buy & sell same next trading day).
    Returns (buy_date, buy_price, sell_date, sell_price) or None if the
    future window doesn't have enough settled bars yet.
    """
    future_daily = future_df[future_df["close"] > 0]
    if len(future_daily) < holding_period or len(future_daily) < 1:
        return None

    buy_row = future_daily.iloc[0]
    sell_row = future_daily.iloc[holding_period - 1]

    buy_price = float(buy_row["open"])
    sell_price = float(sell_row["close"])
    if buy_price <= 0 or sell_price <= 0:
        return None

    buy_date = str(future_daily.index[0].date())
    sell_date = str(future_daily.index[holding_period - 1].date())
    return buy_date, round(buy_price, 2), sell_date, round(sell_price, 2)


def _empty_item(symbol: str, reason: str, error: str) -> BasketItem:
    return BasketItem(
        stock=symbol.upper(), sector=_sector_of(symbol), selection_reason=reason,
        rank_metric=0.0, buy_date="", buy_price=0.0, sell_date="", sell_price=0.0,
        quantity=0, investment=0.0, pnl_rupees=0.0, pnl_pct=0.0,
        outcome="Pending", error=error,
    )


def _simulate_item(
    symbol: str, selection_date: str, holding_period: int, quantity: int,
    reason: str, rank_metric: float,
) -> BasketItem:
    df = _fetch_profile_df(symbol, selection_date, holding_period)
    if df is None:
        return _empty_item(symbol, reason, "Data fetch failed or insufficient history")

    as_of_df, future_df = _split_as_of_future(df, selection_date)
    if as_of_df.empty:
        return _empty_item(symbol, reason, f"No data available up to {selection_date}")

    trade = _buy_sell_from_future(future_df, holding_period)
    if trade is None:
        return _empty_item(symbol, reason, "Not enough future trading days settled yet for this holding period")

    buy_date, buy_price, sell_date, sell_price = trade
    investment = round(buy_price * quantity, 2)
    final_value = round(sell_price * quantity, 2)
    pnl_rupees = round(final_value - investment, 2)
    pnl_pct = round((sell_price - buy_price) / buy_price * 100.0, 2)

    return BasketItem(
        stock=symbol.upper(), sector=_sector_of(symbol), selection_reason=reason,
        rank_metric=rank_metric,
        buy_date=buy_date, buy_price=buy_price,
        sell_date=sell_date, sell_price=sell_price,
        quantity=quantity, investment=investment,
        pnl_rupees=pnl_rupees, pnl_pct=pnl_pct,
        outcome=classify_basket_outcome(pnl_pct),
        error=None,
    )


# ── Candidate ranking per method ─────────────────────────────────────────────

def _replay_universe(
    universe: list[str], selection_date: str, capital: float,
) -> dict[str, dict]:
    """
    Compute the lookahead-safe Market Replay signal for every stock ONCE
    (as of selection_date). Shared by the ranking methods, the improved
    filtered model, and comparison mode so the expensive scan runs once.
    holding_period=1 is passed only because replay_stock requires one for
    its own (unused here) outcome comparison — our own buy/sell simulation
    is computed independently in _simulate_item.
    """
    return {
        sym: dict(replay_stock(sym, selection_date, holding_period=1, interval="daily", capital=capital))
        for sym in universe
    }


def _rank_by_opportunity_score(replay_items: dict[str, dict]) -> list[tuple[str, float, str]]:
    ranked: list[tuple[str, float, str]] = []
    for sym, item in replay_items.items():
        if item["error"] is not None:
            continue
        reason = (
            f"Opportunity score {item['opportunity_score']:.1f}/100 "
            f"({item['best_strategy_name']}, {item['historical_action']})"
        )
        ranked.append((sym, item["opportunity_score"], reason))
    ranked.sort(key=lambda t: t[1], reverse=True)
    return ranked


def _rank_by_gainers(universe: list[str], selection_date: str) -> list[tuple[str, float, str]]:
    ranked: list[tuple[str, float, str]] = []
    for sym in universe:
        df = _fetch_profile_df(sym, selection_date, 1)
        if df is None:
            continue
        as_of_df, _ = _split_as_of_future(df, selection_date)
        metric = _gainer_metric(as_of_df)
        if metric is None:
            continue
        reason = f"Previous day gain {metric:+.2f}%"
        ranked.append((sym, metric, reason))
    ranked.sort(key=lambda t: t[1], reverse=True)
    return ranked


def _rank_by_volume_spike(universe: list[str], selection_date: str) -> list[tuple[str, float, str]]:
    ranked: list[tuple[str, float, str]] = []
    for sym in universe:
        df = _fetch_profile_df(sym, selection_date, 1)
        if df is None:
            continue
        as_of_df, _ = _split_as_of_future(df, selection_date)
        metric = _volume_spike_metric(as_of_df)
        if metric is None:
            continue
        reason = f"Volume {metric:.2f}x the {VOLUME_AVG_WINDOW}-day average"
        ranked.append((sym, metric, reason))
    ranked.sort(key=lambda t: t[1], reverse=True)
    return ranked


def _rank_by_sector_strength(
    replay_items: dict[str, dict], num_stocks: int,
) -> list[tuple[str, float, str]]:
    """
    Uses the precomputed per-stock opportunity scores (as-of selection_date,
    lookahead safe), groups by sector, ranks sectors by average score, then
    returns stocks ordered sector-by-sector (strongest sector first, best
    stocks within each sector first) until enough candidates are gathered.
    """
    by_symbol: dict[str, tuple[float, str]] = {}
    for sym, item in replay_items.items():
        if item["error"] is not None:
            continue
        by_symbol[sym] = (item["opportunity_score"], item["best_strategy_name"])

    by_sector: dict[str, list[str]] = {}
    for sym in by_symbol:
        by_sector.setdefault(_sector_of(sym), []).append(sym)

    sector_avg = {
        sector: sum(by_symbol[s][0] for s in syms) / len(syms)
        for sector, syms in by_sector.items() if syms
    }
    sectors_ranked = sorted(sector_avg.keys(), key=lambda s: sector_avg[s], reverse=True)

    ranked: list[tuple[str, float, str]] = []
    for sector in sectors_ranked:
        stocks_in_sector = sorted(by_sector[sector], key=lambda s: by_symbol[s][0], reverse=True)
        for sym in stocks_in_sector:
            score, strat = by_symbol[sym]
            reason = (
                f"{sector} sector strength {sector_avg[sector]:.1f}/100 "
                f"(stock opportunity score {score:.1f}, {strat})"
            )
            ranked.append((sym, score, reason))
        if len(ranked) >= num_stocks * 2:
            break
    return ranked


# ── Full basket run ───────────────────────────────────────────────────────────

def _summarize(valid: list[BasketItem]) -> BasketSummary:
    total_investment = round(sum(it["investment"] for it in valid), 2)
    final_value = round(sum(it["sell_price"] * it["quantity"] for it in valid), 2)
    net_pnl = round(final_value - total_investment, 2)
    net_return_pct = round(net_pnl / total_investment * 100.0, 2) if total_investment > 0 else 0.0

    winning = [it for it in valid if it["pnl_rupees"] > 0]
    losing = [it for it in valid if it["pnl_rupees"] < 0]
    win_rate = round(len(winning) / len(valid) * 100.0, 1) if valid else 0.0

    best_item = max(valid, key=lambda it: it["pnl_pct"]) if valid else None
    worst_item = min(valid, key=lambda it: it["pnl_pct"]) if valid else None
    max_loss_item = min(valid, key=lambda it: it["pnl_rupees"]) if valid else None
    avg_return_pct = round(sum(it["pnl_pct"] for it in valid) / len(valid), 2) if valid else 0.0

    return BasketSummary(
        total_investment=total_investment,
        final_value=final_value,
        net_pnl=net_pnl,
        net_return_pct=net_return_pct,
        winning_stocks=len(winning),
        losing_stocks=len(losing),
        win_rate=win_rate,
        best_stock=best_item["stock"] if best_item else "",
        best_stock_return=best_item["pnl_pct"] if best_item else 0.0,
        worst_stock=worst_item["stock"] if worst_item else "",
        worst_stock_return=worst_item["pnl_pct"] if worst_item else 0.0,
        average_return_pct=avg_return_pct,
        max_loss_stock=max_loss_item["stock"] if max_loss_item else "",
        max_loss_rupees=max_loss_item["pnl_rupees"] if max_loss_item else 0.0,
    )


def _comparison_row(label: str, summary: BasketSummary, trades: int) -> dict:
    return {
        "model": label,
        "total_investment": summary["total_investment"],
        "net_pnl": summary["net_pnl"],
        "net_return_pct": summary["net_return_pct"],
        "win_rate": summary["win_rate"],
        "trades": trades,
        "best_stock": summary["best_stock"],
        "worst_stock": summary["worst_stock"],
    }


def run_paper_basket(
    selection_date: str,
    holding_period: int = 5,
    num_stocks: int = DEFAULT_NUM_STOCKS,
    quantity: int = DEFAULT_QUANTITY,
    method: str = "opportunity_score",
    capital: float = INITIAL_CAPITAL,
    min_score: float = STRICT_MIN_SCORE,
    min_confidence: float = STRICT_MIN_CONFIDENCE,
    min_rr: float = STRICT_MIN_RR,
    include_watch: bool = False,
) -> dict:
    """
    Runs BOTH models and returns a comparison (v1.0):
      - Old model:      the original method ranking, top `num_stocks`.
      - Improved model: strict signal-quality filters (min score/confidence/
        risk-reward, top-3 sector, bullish regime, EMA20/50, volume above
        average, reliable strategy) — trades only BUY/STRONG BUY (WATCH
        optional), ranked by Signal Quality Score. Never forces trades.
    Learning weights are updated from the improved model's resolved outcomes.
    Top-level items/summary remain the OLD model for backward compatibility.
    """
    if holding_period not in VALID_HOLDING_DAYS:
        holding_period = 5
    if method not in VALID_METHODS:
        method = "opportunity_score"
    num_stocks = max(1, min(int(num_stocks or DEFAULT_NUM_STOCKS), 30))
    quantity = max(1, int(quantity or DEFAULT_QUANTITY))
    min_score = max(0.0, min(float(min_score), 100.0))
    min_confidence = max(0.0, min(float(min_confidence), 100.0))
    min_rr = max(0.0, float(min_rr))

    try:
        datetime.strptime(selection_date, "%Y-%m-%d")
    except (ValueError, TypeError):
        sel_dt = datetime.now() - timedelta(days=holding_period * 2 + 5)
        selection_date = sel_dt.strftime("%Y-%m-%d")

    universe = list(NIFTY_50)

    # Expensive per-stock signal computation runs ONCE, shared by both models.
    replay_items = _replay_universe(universe, selection_date, capital)

    # ── OLD MODEL: original ranking, top N ────────────────────────────────
    if method == "opportunity_score":
        ranked = _rank_by_opportunity_score(replay_items)
    elif method == "gainers":
        ranked = _rank_by_gainers(universe, selection_date)
    elif method == "volume_spike":
        ranked = _rank_by_volume_spike(universe, selection_date)
    else:  # sector_strength
        ranked = _rank_by_sector_strength(replay_items, num_stocks)

    items: list[BasketItem] = []
    for sym, metric, reason in ranked:
        if len(items) >= num_stocks:
            break
        result = _simulate_item(sym, selection_date, holding_period, quantity, reason, metric)
        if result["error"] is None:
            items.append(result)
    valid = [it for it in items if it["error"] is None]
    summary = _summarize(valid)
    buy_date = valid[0]["buy_date"] if valid else ""

    # ── IMPROVED MODEL: strict signal-quality filters ─────────────────────
    regime_info = get_market_regime_as_of(selection_date)
    annotated = list(replay_items.values())
    annotate_items_with_quality(
        annotated, action_key="historical_action", regime_info=regime_info,
        min_score=min_score, min_confidence=min_confidence, min_rr=min_rr,
    )

    def _eligible(it: dict) -> bool:
        if it.get("error") is not None:
            return False
        # IGNORE means the signal was either poor quality or downgraded hard.
        if it["historical_action"] == "IGNORE":
            return False
        if it["opportunity_score"] < min_score or it["confidence"] < min_confidence:
            return False
        if it["rr_ratio"] < min_rr:
            return False
        if include_watch:
            # Relaxed mode: WATCH signals allowed as long as the numeric
            # floors above are met.
            return True
        # Strict mode: every strict gate must pass (sector, regime, trend,
        # volume, reliability). The action LABEL (BUY vs WATCH) is just a
        # score binning — a fully-passing setup is tradeable either way.
        return it["filter_passed"]

    candidates = sorted(
        (it for it in annotated if _eligible(it)),
        key=lambda it: it["signal_quality"], reverse=True,
    )

    improved_items: list[BasketItem] = []
    improved_quality: dict[str, dict] = {}
    for it in candidates:
        if len(improved_items) >= num_stocks:
            break
        reason = (
            f"Signal quality {it['signal_quality']:.1f}/100, "
            f"opportunity {it['opportunity_score']:.1f}, confidence {it['confidence']:.1f}, "
            f"R/R {it['rr_ratio']:.2f} ({it['historical_action']})"
        )
        sim = _simulate_item(it["stock"], selection_date, holding_period, quantity,
                             reason, it["signal_quality"])
        if sim["error"] is None:
            improved_items.append(sim)
            improved_quality[it["stock"]] = {
                "signal_quality": it["signal_quality"],
                "quality_components": it["quality_components"],
                "filter_passed": it["filter_passed"],
                "filter_reasons": it["filter_reasons"],
                "action": it["historical_action"],
            }
    improved_valid = [it for it in improved_items if it["error"] is None]
    improved_summary = _summarize(improved_valid)

    no_trades_message = NO_TRADES_MESSAGE if not improved_valid else None

    # ── LEARNING: adjust factor weights from improved-model outcomes ─────
    learn_records = [
        {
            "factors": improved_quality[it["stock"]]["quality_components"],
            "win": it["pnl_rupees"] > 0,
        }
        for it in improved_valid if it["stock"] in improved_quality
    ]
    learning = learn_from_outcomes(learn_records) if learn_records else {
        **load_weights(), "adjustments": {}, "records_used": 0,
    }

    result: dict = dict(PaperBasketResult(
        selection_date=selection_date,
        buy_date=buy_date,
        holding_period=holding_period,
        method=method,
        method_label=METHOD_LABELS[method],
        num_stocks=num_stocks,
        quantity=quantity,
        items=items,
        summary=summary,
        warning=WARNING_TEXT,
    ))
    result["filters"] = {
        "min_score": min_score,
        "min_confidence": min_confidence,
        "min_rr": min_rr,
        "include_watch": include_watch,
    }
    result["regime"] = regime_info
    result["improved"] = {
        "items": improved_items,
        "summary": improved_summary,
        "quality": improved_quality,
        "no_trades_message": no_trades_message,
    }
    result["comparison"] = [
        _comparison_row("Old model", summary, len(valid)),
        _comparison_row("Improved filtered model", improved_summary, len(improved_valid)),
    ]
    result["learning"] = learning
    return result
