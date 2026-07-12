"""
strategy_audit.py — Phase 2B Strategy Engine Audit (ANALYSIS ONLY).

Diagnoses WHY each strategy wins or loses out-of-sample and evaluates a
small set of controlled, interpretable improvements — without touching the
ranking engine or the live paper-trading pipeline.

What it does, per walk-forward window:
  §1  Audit pass — for EVERY strategy, take ALL raw entry signals across the
      whole universe (no ranking, no portfolio gating, no confidence filter),
      fill each at the next day's open with a FIXED notional, and simulate
      the trade independently with the strategy's own exit logic. A full
      indicator snapshot is captured at the signal bar.
  §2  Entry-condition diagnostics — with/without splits per condition, with
      sample-size gating so small samples are never over-claimed.
  §3  Exit alternatives A–G re-simulated on IDENTICAL entries.
  §4  Holding-period buckets (selection uses TRAINING data only).
  §5  Regime eligibility matrix per strategy.
  §6  Cost sensitivity: zero / current / +25% / +50%.
  §7  Robustness checks on proposed variants (bootstrap CI, slippage,
      same-candle rule flip, parameter perturbation, sub-period split,
      regime stability, sector concentration).
  §8  Max three controlled variants per strategy (filters on identical
      baseline entries — entries only ever REMOVED, never added).
  §11 Model comparison E (best validated variants only) and F (E + gated
      regime eligibility with cash fallback) — selection on TRAIN data,
      evaluation on unseen TEST data, chained across windows.
  §12 Final plain-language report.

No-lookahead rules enforced here:
  - Signals use only bars up to the signal day; entries fill next day.
  - Variant selection and E/F eligibility come from TRAIN-window trades.
  - Nothing learned inside a test window feeds back into decisions in it.

PAPER TRADING AND RESEARCH ONLY — nothing here changes live decisions.
"""

from __future__ import annotations

import math
import random
import statistics

import pandas as pd

from backtesting_engine import WARMUP_BARS
from execution_simulator import (
    CostModel, side_costs, effective_buy_price, effective_sell_price,
    simulate_entry, evaluate_exit_candle, build_trade_record,
    INTRABAR_CONSERVATIVE, INTRABAR_OPTIMISTIC, INTRABAR_RULE_LABELS,
    EXIT_STOP, EXIT_TARGET, EXIT_SIGNAL, EXIT_TIME, EXIT_FORCED,
)
from market_scanner import _sector_of
from strategies import STRATEGY_REGISTRY, LAB_STRATEGY_IDS

SAFETY_MESSAGE = ("ANALYSIS ONLY — Phase 2B never changes live paper-trading "
                  "decisions. Out-of-sample historical performance does not "
                  "guarantee future results.")

# Fixed audit notional (₹) per simulated trade. Deliberately larger than the
# live ₹5,000 capital so every NIFTY-50 stock is affordable and every strategy
# gets a statistically comparable sample; the audit currency is the per-trade
# RETURN PERCENTAGE, not rupees.
AUDIT_NOTIONAL = 100_000.0

SHRINK_K = 10          # pseudo-count pulling small-sample expectancy to 0
MIN_SPLIT_SAMPLE = 20  # min trades on EACH side of a with/without split
MIN_REGIME_SAMPLE = 10
MIN_VARIANT_TRAIN_TRADES = 5
BOOTSTRAP_ITER = 800
TIME_ONLY_HOLD_DAYS = 10   # horizon for exit alternative E (time exit only)

HOLDING_BUCKETS = [
    (1, "1 day"),
    (3, "2–3 days"),
    (7, "4–7 days"),
    (15, "8–15 days"),
    (20, "16–20 days"),
    (0, "Signal-only (no fixed limit)"),
]

EXIT_ALT_LABELS = {
    "A": "A — Existing exit logic (stop/target/signal/time)",
    "B": "B — ATR stop & target (entry ± 2×ATR)",
    "C": "C — Trailing stop (2×ATR from close, no target)",
    "D": "D — Signal exit only (no stop/target)",
    "E": f"E — Time exit only ({TIME_ONLY_HOLD_DAYS} trading days)",
    "F": "F — Partial profit at +1.5×ATR, trail remainder 2×ATR",
    "G": "G — Break-even stop after +1×ATR favourable move",
}

ST_ELIGIBLE = "ELIGIBLE"
ST_WATCHLIST = "WATCHLIST"
ST_NEG_EDGE = "DISABLED_NEGATIVE_EDGE"
ST_INSUFFICIENT = "DISABLED_INSUFFICIENT_SAMPLE"
ST_UNSTABLE = "DISABLED_UNSTABLE"

MODEL_LABELS_2B = {
    "A": "A — Current base technical engine",
    "B": "B — Current calibrated model (pattern + similarity)",
    "C": "C — Existing adaptive model (full)",
    "D": "D — Corrected gated model (Phase 2A)",
    "E": "E — Best validated strategy variants only (Phase 2B)",
    "F": "F — Best variants + regime eligibility gate + cash fallback (Phase 2B)",
}

MAX_OPEN_EF = 5        # slots for the E/F portfolio simulation
ALLOC_PCT_EF = 0.20    # flat allocation per position (like variant A/B)


# ── Small helpers ────────────────────────────────────────────────────────────

def _f(v, default: float = 0.0) -> float:
    try:
        x = float(v)
        return default if (math.isnan(x) or math.isinf(x)) else x
    except (TypeError, ValueError):
        return default


def _shrunk_mean(values: list[float], k: int = SHRINK_K) -> float:
    n = len(values)
    if n == 0:
        return 0.0
    return (sum(values) / n) * (n / (n + k))


def _metrics(trades: list[dict]) -> dict:
    """Compact metric block used across the audit (returns are the currency)."""
    n = len(trades)
    if n == 0:
        return {"trades": 0, "net_return_pct": 0.0, "expectancy_pct": None,
                "profit_factor": None, "win_rate": None, "max_drawdown_pct": None,
                "avg_win_pct": None, "avg_loss_pct": None, "avg_holding_days": None}
    rets = [_f(t.get("return_pct")) for t in trades]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    gw = sum(wins)
    gl = -sum(losses)
    pf = round(min(gw / gl, 99.0), 2) if gl > 1e-9 else (99.0 if gw > 0 else 0.0)
    cum = peak = dd = 0.0
    for t in sorted(trades, key=lambda x: str(x.get("exit_date") or "")):
        cum += _f(t.get("return_pct"))
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    hold = [int(t.get("holding_days", 0)) for t in trades]
    return {
        "trades": n,
        "net_return_pct": round(sum(rets), 2),
        "expectancy_pct": round(sum(rets) / n, 3),
        "profit_factor": pf,
        "win_rate": round(len(wins) / n * 100.0, 1),
        "max_drawdown_pct": round(dd, 2),
        "avg_win_pct": round(sum(wins) / len(wins), 2) if wins else 0.0,
        "avg_loss_pct": round(sum(losses) / len(losses), 2) if losses else 0.0,
        "avg_holding_days": round(sum(hold) / n, 1),
    }


def _scaled_cost_model(cm: CostModel, mult: float) -> CostModel:
    """Cost model with every friction scaled by `mult` (0 → frictionless)."""
    d = cm.to_dict()
    for k in ("slippage_pct", "spread_pct", "brokerage_pct", "brokerage_flat",
              "stt_pct", "exchange_pct", "sebi_pct", "stamp_pct"):
        d[k] = d[k] * mult
    if mult == 0.0:
        d["gst_pct"] = 0.0
    return CostModel.from_dict(d)


def _reprice_trade(t: dict, cm: CostModel) -> dict:
    """Recompute one trade's economics under a different cost model. The
    exit DAY is unchanged (stops/targets trigger on raw candle prices), only
    fill prices, slippage/spread and statutory costs change."""
    qty = int(t["quantity"])
    raw_open = _f(t["raw_open"])
    raw_exit = _f(t["raw_exit_price"])
    fill = effective_buy_price(cm, raw_open)
    sell = effective_sell_price(cm, raw_exit)
    bc = side_costs(cm, fill * qty, "buy")
    sc = side_costs(cm, sell * qty, "sell")
    invested = fill * qty
    net = (sell - fill) * qty - bc["total"] - sc["total"]
    return {
        "return_pct": round(net / invested * 100.0, 3) if invested > 0 else 0.0,
        "net_pnl": round(net, 2),
        "exit_date": t["exit_date"],
        "holding_days": t["holding_days"],
    }


# ── Exit walker (all alternatives share this one engine) ─────────────────────

def walk_exit(cost_model: CostModel, recs: list[dict], entry_pos: int,
              end_pos: int, fill: dict, stop: float, target: float,
              sig_exit_dates: set[str], intrabar_rule: str,
              max_holding: int, *,
              use_signal: bool = True,
              trail_atr_mult: float | None = None,
              breakeven_after_atr: float | None = None,
              entry_atr: float = 0.0) -> dict:
    """Walk candles from the entry bar to `end_pos` and find the first exit.
    Supports fixed stop/target, trailing stops, break-even stops, signal
    exits and time exits. Returns an exit_info dict compatible with
    build_trade_record."""
    entry_price = _f(fill["fill_price"])
    raw_open = _f(fill["raw_open"])
    qty = int(fill["quantity"])
    stop_cur = stop
    mae = mfe = 0.0
    exit_date = raw_exit = reason = None
    holding = 0

    for i in range(entry_pos, end_pos + 1):
        c = recs[i]
        d = str(c["date"])[:10]
        holding = i - entry_pos
        low, high, close, opn = _f(c["low"]), _f(c["high"]), _f(c["close"]), _f(c["open"])
        if entry_price > 0:
            mae = min(mae, (low - entry_price) / entry_price * 100.0)
            mfe = max(mfe, (high - entry_price) / entry_price * 100.0)

        if i == entry_pos and stop_cur > 0 and opn <= stop_cur:
            exit_date, raw_exit, reason = d, opn, EXIT_STOP
            break

        exited, raw, why, _both = evaluate_exit_candle(
            {"open": opn, "high": high, "low": low, "close": close},
            stop_cur, target, intrabar_rule)
        if exited:
            exit_date, raw_exit, reason = d, raw, why
            break
        if use_signal and d in sig_exit_dates:
            exit_date, raw_exit, reason = d, close, EXIT_SIGNAL
            break
        if max_holding > 0 and holding >= max_holding:
            exit_date, raw_exit, reason = d, close, EXIT_TIME
            break

        # Stop management AFTER the bar completes (no lookahead within bar)
        if trail_atr_mult is not None:
            atr_now = _f(c.get("atr")) or entry_atr
            if atr_now > 0:
                stop_cur = max(stop_cur, close - trail_atr_mult * atr_now)
        if breakeven_after_atr is not None and entry_atr > 0 \
                and close >= entry_price + breakeven_after_atr * entry_atr:
            stop_cur = max(stop_cur, raw_open)

    if exit_date is None:
        last = recs[end_pos]
        exit_date, raw_exit, reason = str(last["date"])[:10], _f(last["close"]), EXIT_FORCED
        holding = end_pos - entry_pos

    sell_price = effective_sell_price(cost_model, float(raw_exit))
    turnover = sell_price * qty
    return {
        "exit_date": exit_date,
        "raw_exit_price": round(float(raw_exit), 4),
        "sell_price": round(sell_price, 4),
        "exit_reason": reason,
        "holding_days": holding,
        "mae_pct": round(mae, 2),
        "mfe_pct": round(mfe, 2),
        "intrabar_rule": intrabar_rule,
        "intrabar_rule_label": INTRABAR_RULE_LABELS[intrabar_rule],
        "sell_turnover": round(turnover, 2),
        "sell_costs": side_costs(cost_model, turnover, "sell"),
    }


def _walk_partial(cost_model: CostModel, recs: list[dict], entry_pos: int,
                  end_pos: int, fill: dict, stop: float,
                  sig_exit_dates: set[str], intrabar_rule: str,
                  max_holding: int, entry_atr: float, symbol: str) -> dict:
    """Alternative F: sell HALF at entry + 1.5×ATR, trail the remainder with
    a 2×ATR stop. Returns one combined trade record."""
    qty = int(fill["quantity"])
    half = qty // 2
    rest = qty - half
    entry_price = _f(fill["fill_price"])
    target1 = entry_price + 1.5 * entry_atr if entry_atr > 0 else 0.0

    def _leg(leg_qty: int, target: float, trail: float | None) -> dict:
        leg_fill = dict(fill)
        leg_fill["quantity"] = leg_qty
        leg_fill["requested_quantity"] = leg_qty
        turnover = _f(fill["fill_price"]) * leg_qty
        leg_fill["buy_costs"] = side_costs(cost_model, turnover, "buy")
        ex = walk_exit(cost_model, recs, entry_pos, end_pos, leg_fill,
                       stop, target, sig_exit_dates, intrabar_rule,
                       max_holding, use_signal=False,
                       trail_atr_mult=trail, entry_atr=entry_atr)
        return build_trade_record(symbol, leg_fill, ex, {})

    if half <= 0 or target1 <= 0:
        # Too small to split — fall back to plain trailing behaviour.
        full_fill = dict(fill)
        ex = walk_exit(cost_model, recs, entry_pos, end_pos, full_fill,
                       stop, 0.0, sig_exit_dates, intrabar_rule, max_holding,
                       use_signal=False, trail_atr_mult=2.0, entry_atr=entry_atr)
        return build_trade_record(symbol, full_fill, ex, {})

    leg1 = _leg(half, target1, None)
    leg2 = _leg(rest, 0.0, 2.0)
    invested = leg1["invested"] + leg2["invested"]
    net = leg1["net_pnl"] + leg2["net_pnl"]
    combined = dict(leg2)
    combined.update({
        "quantity": qty,
        "invested": round(invested, 2),
        "gross_pnl": round(leg1["gross_pnl"] + leg2["gross_pnl"], 2),
        "net_pnl": round(net, 2),
        "return_pct": round(net / invested * 100.0, 2) if invested > 0 else 0.0,
        "total_costs": round(leg1["total_costs"] + leg2["total_costs"], 2),
        "exit_reason": f"Partial ({leg1['exit_reason']}) + Trail ({leg2['exit_reason']})",
        "holding_days": max(leg1["holding_days"], leg2["holding_days"]),
        "win": net > 0,
    })
    return combined


# ── Signal collection ────────────────────────────────────────────────────────

def _signal_exit_dates(strategy, recs: list[dict], start: int, end: int) -> set[str]:
    """All dates in [start, end] where the strategy's indicator-based exit
    fires. Every registered strategy's check_exit is stateless w.r.t. the
    position, so the set can be precomputed once per (strategy, symbol)."""
    out: set[str] = set()
    for i in range(max(1, start), end + 1):
        try:
            fired, _ = strategy.check_exit(recs[i], recs[i - 1], 0.0, 0.0, 0.0)
        except Exception:
            fired = False
        if fired:
            out.add(str(recs[i]["date"])[:10])
    return out


def _snapshot(recs: list[dict], i: int, regime: str, sector: str) -> dict:
    """Entry-condition snapshot at the SIGNAL bar (bar i)."""
    row = recs[i]
    close = _f(row.get("close"))
    atr = _f(row.get("atr"))
    ema20 = _f(row.get("ema20"))
    ema50 = _f(row.get("ema50"))
    ema200 = _f(row.get("ema200"))
    vwap = _f(row.get("vwap"))
    atr5 = _f(recs[i - 5].get("atr")) if i >= 5 else 0.0
    return {
        "close": close,
        "ema9": _f(row.get("ema9")), "ema20": ema20,
        "ema50": ema50, "ema200": ema200,
        "dist_ema20_pct": round((close - ema20) / ema20 * 100.0, 2) if ema20 > 0 else None,
        "dist_ema50_pct": round((close - ema50) / ema50 * 100.0, 2) if ema50 > 0 else None,
        "dist_ema200_pct": round((close - ema200) / ema200 * 100.0, 2) if ema200 > 0 else None,
        "rsi": _f(row.get("rsi"), 50.0),
        "adx": _f(row.get("adx")),
        "macd_hist": _f(row.get("macd_hist")),
        "supertrend_dir": str(row.get("supertrend_dir", "")),
        "volume_ratio": _f(row.get("volume_ratio")),
        "vwap": vwap,
        "above_vwap": bool(vwap > 0 and close > vwap),
        "atr_pct": round(atr / close * 100.0, 2) if close > 0 else 0.0,
        "atr": atr, "atr5": atr5,
        "regime": regime, "sector": sector,
    }


# ── §8 controlled variants (filters on identical baseline entries) ───────────
# Each filter is a predicate over the entry snapshot; `k` scales the main
# numeric threshold for parameter-perturbation robustness (§7).

def _above_ema200(s, k=1.0):
    return s["ema200"] > 0 and s["close"] > s["ema200"] * (0.98 + 0.02 * k)


VARIANT_DEFS: dict[str, list[tuple[str, str]]] = {
    "ema_cross": [
        ("trend_filtered", "Golden cross only when price is above EMA200"),
        ("trend_plus_volume", "Trend filter + volume ≥ 1.2× 20-day average"),
    ],
    "macd_cross": [
        ("histogram_strength", "MACD histogram positive and ≥ 0.05% of price"),
        ("histogram_plus_adx", "Histogram strength + ADX ≥ 20"),
    ],
    "mean_reversion": [
        ("trend_guard", "Oversold bounce only when price is above EMA200"),
        ("volatility_guard", "Oversold bounce only when ATR ≤ 3% of price"),
    ],
    "trend_rider": [
        ("strong_adx", "Entries require ADX ≥ 28"),
        ("strong_adx_pullback", "ADX ≥ 28 + close within 1% of EMA20 (pullback)"),
    ],
    "supertrend_follow": [
        ("volume_confirmed", "Flip-to-UP with volume ≥ 1.2× average"),
        ("htf_aligned", "Flip-to-UP only when price is above EMA200"),
    ],
    "breakout_hunter": [
        ("volume_expansion", "Breakout with volume ≥ 2.0× average"),
        ("volume_plus_atr_expansion", "Volume ≥ 2.0× + ATR rising vs 5 bars ago"),
    ],
}

VARIANT_FILTERS = {
    ("ema_cross", "trend_filtered"): _above_ema200,
    ("ema_cross", "trend_plus_volume"):
        lambda s, k=1.0: _above_ema200(s) and s["volume_ratio"] >= 1.2 * k,
    ("macd_cross", "histogram_strength"):
        lambda s, k=1.0: s["macd_hist"] > 0 and s["close"] > 0
        and s["macd_hist"] >= 0.0005 * k * s["close"],
    ("macd_cross", "histogram_plus_adx"):
        lambda s, k=1.0: s["macd_hist"] > 0 and s["close"] > 0
        and s["macd_hist"] >= 0.0005 * s["close"] and s["adx"] >= 20 * k,
    ("mean_reversion", "trend_guard"): _above_ema200,
    ("mean_reversion", "volatility_guard"):
        lambda s, k=1.0: s["atr_pct"] <= 3.0 * k,
    ("trend_rider", "strong_adx"):
        lambda s, k=1.0: s["adx"] >= 28 * k,
    ("trend_rider", "strong_adx_pullback"):
        lambda s, k=1.0: s["adx"] >= 28 and s["ema20"] > 0
        and s["close"] <= s["ema20"] * (1.0 + 0.01 * k),
    ("supertrend_follow", "volume_confirmed"):
        lambda s, k=1.0: s["volume_ratio"] >= 1.2 * k,
    ("supertrend_follow", "htf_aligned"): _above_ema200,
    ("breakout_hunter", "volume_expansion"):
        lambda s, k=1.0: s["volume_ratio"] >= 2.0 * k,
    ("breakout_hunter", "volume_plus_atr_expansion"):
        lambda s, k=1.0: s["volume_ratio"] >= 2.0 and s["atr5"] > 0
        and s["atr"] >= s["atr5"] * k,
}


# ── §2 entry-condition definitions ───────────────────────────────────────────

ENTRY_CONDITIONS: list[tuple[str, callable]] = [
    ("EMA aligned (9>20>50)",
     lambda s: s["ema9"] > s["ema20"] > s["ema50"] > 0),
    ("Price above EMA200",
     lambda s: s["ema200"] > 0 and s["close"] > s["ema200"]),
    ("Extended >2% above EMA20",
     lambda s: s["dist_ema20_pct"] is not None and s["dist_ema20_pct"] > 2.0),
    ("RSI 40–60", lambda s: 40 <= s["rsi"] <= 60),
    ("RSI > 60", lambda s: s["rsi"] > 60),
    ("MACD histogram positive", lambda s: s["macd_hist"] > 0),
    ("ADX ≥ 25 (strong trend)", lambda s: s["adx"] >= 25),
    ("Supertrend UP", lambda s: s["supertrend_dir"] == "UP"),
    ("Volume ratio ≥ 1.5×", lambda s: s["volume_ratio"] >= 1.5),
    ("Price above VWAP", lambda s: s["above_vwap"]),
    ("ATR ≥ 2.5% of price (high volatility)", lambda s: s["atr_pct"] >= 2.5),
    ("Gap-up entry ≥ 1%", lambda s: _f(s.get("gap_pct")) >= 1.0),
    ("Bullish/Neutral-Bullish regime",
     lambda s: s["regime"] in ("Bullish", "Neutral Bullish")),
    ("High-volatility regime", lambda s: s["regime"] == "High Volatility"),
]


def _vol_band(s: dict) -> str:
    a = s["atr_pct"]
    return "<1.5% ATR" if a < 1.5 else "1.5–3% ATR" if a <= 3.0 else ">3% ATR"


def _trend_band(s: dict) -> str:
    a = s["adx"]
    return "ADX <20" if a < 20 else "ADX 20–25" if a < 25 else \
        "ADX 25–35" if a < 35 else "ADX >35"


def _volume_band(s: dict) -> str:
    v = s["volume_ratio"]
    return "Vol <0.8×" if v < 0.8 else "Vol 0.8–1.2×" if v < 1.2 else \
        "Vol 1.2–2×" if v < 2.0 else "Vol >2×"


def _holding_bucket_label(days: int) -> str:
    if days <= 1:
        return "1 day"
    if days <= 3:
        return "2–3 days"
    if days <= 7:
        return "4–7 days"
    if days <= 15:
        return "8–15 days"
    return "16+ days"


def _entry_subtype(s: dict) -> str:
    trend = "with long-term trend" if (s["ema200"] > 0 and s["close"] > s["ema200"]) \
        else "against long-term trend"
    vol = "volume-backed" if s["volume_ratio"] >= 1.2 else "quiet volume"
    return f"{trend}, {vol}"


# ── Core per-window audit pass ───────────────────────────────────────────────

def audit_window_pass(strategy, sym_recs: dict[str, list[dict]],
                      span_pos: dict[str, tuple[int, int]],
                      regime_by_date: dict[str, str],
                      cost_model: CostModel, cfg, window_label: str,
                      collect_alternatives: bool) -> dict:
    """Run the raw-signal audit for ONE strategy over one period (train or
    test). Returns baseline trades (with snapshots and re-simulation specs)
    plus, when requested, exit-alternative and holding-bucket trades on the
    identical entries."""
    baseline: list[dict] = []
    alt_trades: dict[str, list[dict]] = {k: [] for k in EXIT_ALT_LABELS}
    bucket_trades: dict[int, list[dict]] = {b: [] for b, _ in HOLDING_BUCKETS}
    skipped_entries = 0

    for sym, recs in sym_recs.items():
        if sym not in span_pos:
            continue
        start, end = span_pos[sym]
        if end - start < 2:
            continue
        sector = _sector_of(sym)
        sig_exits = _signal_exit_dates(strategy, recs, start, end)

        for i in range(max(start, WARMUP_BARS + 5), end):  # signal bar
            row, prev = recs[i], recs[i - 1]
            try:
                ok, _reason = strategy.check_entry(row, prev)
            except Exception:
                ok = False
            if not ok:
                continue
            price = _f(row.get("close"))
            if price <= 0:
                continue
            try:
                stop = float(strategy.compute_stop_loss(row, price))
                target = float(strategy.compute_target(price, stop))
            except Exception:
                continue
            entry_pos = i + 1
            entry_candle = {
                "date": str(recs[entry_pos]["date"])[:10],
                "open": _f(recs[entry_pos]["open"]),
                "high": _f(recs[entry_pos]["high"]),
                "low": _f(recs[entry_pos]["low"]),
                "close": _f(recs[entry_pos]["close"]),
                "volume": _f(recs[entry_pos]["volume"]),
            }
            fill = simulate_entry(cost_model, entry_candle, price,
                                  AUDIT_NOTIONAL * 10, AUDIT_NOTIONAL)
            if not fill.get("filled"):
                skipped_entries += 1
                continue

            day_str = str(row["date"])[:10]
            regime = regime_by_date.get(day_str, "Sideways")
            snap = _snapshot(recs, i, regime, sector)
            snap["gap_pct"] = _f(fill.get("gap_pct"))
            entry_atr = snap["atr"] or price * 0.02

            ex = walk_exit(cost_model, recs, entry_pos, end, fill, stop, target,
                           sig_exits, cfg.intrabar_rule, cfg.max_holding_days)
            trade = build_trade_record(sym, fill, ex, {
                "strategy_id": strategy.id, "window": window_label,
                "signal_date": day_str, "market_regime": regime,
                "sector": sector, "entry_subtype": _entry_subtype(snap),
                "snapshot": snap,
                "_spec": {"sym": sym, "entry_pos": entry_pos, "end": end,
                          "stop": stop, "target": target,
                          "entry_atr": entry_atr, "sig": sig_exits},
            })
            baseline.append(trade)

            if not collect_alternatives:
                continue

            # §3 exit alternatives B–G on the IDENTICAL entry (A = baseline)
            alts = {
                "B": dict(stop=price - 2 * entry_atr, target=price + 2 * entry_atr,
                          use_signal=False, max_holding=cfg.max_holding_days),
                "C": dict(stop=price - 2 * entry_atr, target=0.0, use_signal=False,
                          max_holding=cfg.max_holding_days, trail_atr_mult=2.0),
                "D": dict(stop=0.0, target=0.0, use_signal=True, max_holding=0),
                "E": dict(stop=0.0, target=0.0, use_signal=False,
                          max_holding=TIME_ONLY_HOLD_DAYS),
                "G": dict(stop=stop, target=target, use_signal=True,
                          max_holding=cfg.max_holding_days,
                          breakeven_after_atr=1.0),
            }
            for key, kw in alts.items():
                exa = walk_exit(cost_model, recs, entry_pos, end, fill,
                                kw.pop("stop"), kw.pop("target"), sig_exits,
                                cfg.intrabar_rule, kw.pop("max_holding"),
                                entry_atr=entry_atr, **kw)
                alt_trades[key].append(build_trade_record(sym, fill, exa, {}))
            alt_trades["F"].append(_walk_partial(
                cost_model, recs, entry_pos, end, fill, stop, sig_exits,
                cfg.intrabar_rule, cfg.max_holding_days, entry_atr, sym))

            # §4 holding buckets: existing exit logic, different time caps
            for bucket, _label in HOLDING_BUCKETS:
                exb = walk_exit(cost_model, recs, entry_pos, end, fill, stop,
                                target, sig_exits, cfg.intrabar_rule, bucket)
                bucket_trades[bucket].append(build_trade_record(sym, fill, exb, {}))

    alt_trades["A"] = [dict(t) for t in baseline]
    return {"baseline": baseline, "alternatives": alt_trades,
            "buckets": bucket_trades, "skipped_entries": skipped_entries}


# ── §2 with/without splits ───────────────────────────────────────────────────

def condition_diagnostics(trades: list[dict]) -> list[dict]:
    out = []
    for name, pred in ENTRY_CONDITIONS:
        with_t, without_t = [], []
        for t in trades:
            (with_t if pred(t["snapshot"]) else without_t).append(t)
        mw, mo = _metrics(with_t), _metrics(without_t)
        n1, n2 = mw["trades"], mo["trades"]
        row = {"condition": name,
               "with": mw, "without": mo,
               "win_rate_diff": None, "expectancy_diff_pct": None,
               "profit_factor_diff": None, "drawdown_diff_pct": None,
               "z_score": None, "reliable": False, "verdict": "INCONCLUSIVE",
               "note": ""}
        if n1 == 0 or n2 == 0:
            row["note"] = "Condition never varies in this sample."
            out.append(row)
            continue
        row["win_rate_diff"] = round(mw["win_rate"] - mo["win_rate"], 1)
        row["expectancy_diff_pct"] = round(
            mw["expectancy_pct"] - mo["expectancy_pct"], 3)
        row["profit_factor_diff"] = round(
            (mw["profit_factor"] or 0) - (mo["profit_factor"] or 0), 2)
        row["drawdown_diff_pct"] = round(
            (mw["max_drawdown_pct"] or 0) - (mo["max_drawdown_pct"] or 0), 2)
        # Two-proportion z on win rates
        p1, p2 = mw["win_rate"] / 100.0, mo["win_rate"] / 100.0
        p = (p1 * n1 + p2 * n2) / (n1 + n2)
        se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2)) if 0 < p < 1 else 0.0
        z = (p1 - p2) / se if se > 0 else 0.0
        row["z_score"] = round(z, 2)
        if n1 < MIN_SPLIT_SAMPLE or n2 < MIN_SPLIT_SAMPLE:
            row["note"] = (f"Sample too small to judge "
                           f"(with={n1}, without={n2}, need ≥{MIN_SPLIT_SAMPLE} each).")
        else:
            row["reliable"] = True
            if row["expectancy_diff_pct"] > 0 and z >= 1.6:
                row["verdict"] = "USEFUL"
            elif row["expectancy_diff_pct"] < 0 and z <= -1.6:
                row["verdict"] = "HARMFUL"
            else:
                row["verdict"] = "INCONCLUSIVE"
                row["note"] = "Difference not statistically distinguishable from noise."
        out.append(row)
    return out


# ── §5 regime eligibility ────────────────────────────────────────────────────

def classify_strategy_regime(trades: list[dict]) -> tuple[str, str]:
    """(status, reason) for one strategy-regime cell from its audit trades."""
    n = len(trades)
    rets = [_f(t.get("return_pct")) for t in trades]
    if n < MIN_REGIME_SAMPLE:
        return ST_INSUFFICIENT, (
            f"Only {n} trades in this regime (need ≥{MIN_REGIME_SAMPLE}).")
    shrunk = _shrunk_mean(rets)
    m = _metrics(trades)
    halves = [rets[: n // 2], rets[n // 2:]]
    half_means = [sum(h) / len(h) for h in halves if h]
    if len(half_means) == 2 and min(half_means) < -0.5 and \
            (half_means[0] > 0) != (half_means[1] > 0):
        return ST_UNSTABLE, (
            f"Edge flips sign between sub-periods "
            f"({half_means[0]:+.2f}% vs {half_means[1]:+.2f}% per trade).")
    if shrunk <= -0.05 or (m["profit_factor"] or 0) < 0.9:
        return ST_NEG_EDGE, (
            f"Shrunk expectancy {shrunk:+.2f}%/trade, PF {m['profit_factor']}"
            f" over {n} trades — negative edge after costs.")
    if shrunk > 0.05 and (m["profit_factor"] or 0) >= 1.1:
        return ST_ELIGIBLE, (
            f"Shrunk expectancy {shrunk:+.2f}%/trade, PF {m['profit_factor']}"
            f" over {n} trades.")
    return ST_WATCHLIST, (
        f"Edge near zero (shrunk {shrunk:+.2f}%/trade, PF {m['profit_factor']},"
        f" {n} trades) — monitor, do not deploy.")


# ── §7 robustness checks for a variant ───────────────────────────────────────

def robustness_checks(trades: list[dict], sym_recs: dict[str, list[dict]],
                      cost_model: CostModel, cfg, rng: random.Random,
                      strategy_id: str, variant_name: str) -> dict:
    """All §7 checks on one variant's TEST trades. Every check is reported
    (pass or fail) — failures are preserved, never hidden."""
    rets = [_f(t.get("return_pct")) for t in trades]
    n = len(rets)
    checks: list[dict] = []

    def _add(name: str, observed: str, passed: bool):
        checks.append({"check": name, "observed": observed, "passed": bool(passed)})

    if n < MIN_VARIANT_TRAIN_TRADES:
        _add("Minimum sample", f"{n} trades", False)
        return {"checks": checks, "passed": False,
                "note": "Too few out-of-sample trades to evaluate robustness."}
    _add("Minimum sample", f"{n} trades", n >= 20)

    # Bootstrap CI on mean return per trade
    means = []
    for _ in range(BOOTSTRAP_ITER):
        sample = [rets[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    lo = means[int(0.025 * len(means))]
    hi = means[int(0.975 * len(means))]
    _add("Bootstrap 95% CI on expectancy",
         f"[{lo:+.2f}%, {hi:+.2f}%] per trade", lo > 0)

    # Higher slippage (2× and 4× current) — exact re-pricing
    for mult, label in ((2.0, "2× slippage/spread"), (4.0, "4× slippage/spread")):
        cm2 = cost_model.to_dict()
        cm2["slippage_pct"] *= mult
        cm2["spread_pct"] *= mult
        cm2 = CostModel.from_dict(cm2)
        rp = [_reprice_trade(t, cm2)["return_pct"] for t in trades]
        exp2 = sum(rp) / len(rp)
        _add(f"Expectancy under {label}", f"{exp2:+.3f}%/trade", exp2 > 0)

    # Same-candle rule flip (conservative → optimistic): re-walk exits
    flipped = []
    for t in trades:
        spec = t.get("_spec")
        if not spec or spec["sym"] not in sym_recs:
            continue
        recs = sym_recs[spec["sym"]]
        fill = {"fill_price": t["entry_price"], "raw_open": t["raw_open"],
                "quantity": t["quantity"]}
        ex = walk_exit(cost_model, recs, spec["entry_pos"], spec["end"], fill,
                       spec["stop"], spec["target"], spec.get("sig") or set(),
                       INTRABAR_OPTIMISTIC, cfg.max_holding_days,
                       entry_atr=spec["entry_atr"])
        entry = {"entry_date": t["entry_date"], "raw_open": t["raw_open"],
                 "fill_price": t["entry_price"], "quantity": t["quantity"],
                 "requested_quantity": t["quantity"], "partial_fill": False,
                 "gap_pct": t.get("gap_pct", 0.0), "buy_costs": t["buy_costs"]}
        flipped.append(_f(build_trade_record(spec["sym"], entry, ex, {})["return_pct"]))
    if flipped:
        expf = sum(flipped) / len(flipped)
        base_exp = sum(rets) / n
        _add("Same-candle rule flip (optimistic)",
             f"{expf:+.3f}%/trade vs {base_exp:+.3f}% conservative",
             min(expf, base_exp) > 0)

    # Sub-period split (by entry date)
    ordered = sorted(trades, key=lambda t: str(t.get("entry_date") or ""))
    half = len(ordered) // 2
    e1 = [_f(t["return_pct"]) for t in ordered[:half]]
    e2 = [_f(t["return_pct"]) for t in ordered[half:]]
    if e1 and e2:
        m1, m2 = sum(e1) / len(e1), sum(e2) / len(e2)
        _add("Sub-period stability",
             f"first half {m1:+.2f}%, second half {m2:+.2f}%",
             m1 > 0 and m2 > 0)

    # Regime stability: expectancy per regime with n ≥ 5
    by_regime: dict[str, list[float]] = {}
    for t in trades:
        by_regime.setdefault(t.get("market_regime", "Sideways"), []).append(
            _f(t["return_pct"]))
    judged = {r: sum(v) / len(v) for r, v in by_regime.items() if len(v) >= 5}
    pos = sum(1 for v in judged.values() if v > 0)
    _add("Regime stability",
         f"positive in {pos}/{len(judged)} regimes with ≥5 trades" if judged
         else "no regime with ≥5 trades",
         bool(judged) and pos >= max(1, len(judged) // 2))

    # Sector concentration of net profit
    by_sector: dict[str, float] = {}
    total_pnl = 0.0
    for t in trades:
        pnl = _f(t.get("net_pnl"))
        by_sector[t.get("sector", "OTHER")] = by_sector.get(t.get("sector", "OTHER"), 0.0) + pnl
        total_pnl += pnl
    if total_pnl > 0 and by_sector:
        top_sector, top_pnl = max(by_sector.items(), key=lambda kv: kv[1])
        share = top_pnl / total_pnl * 100.0
        _add("Sector concentration",
             f"{share:.0f}% of net profit from {top_sector}", share <= 60.0)
    else:
        _add("Sector concentration", "net profit not positive", False)

    # Parameter perturbation (±20% on the variant's main threshold)
    filt = VARIANT_FILTERS.get((strategy_id, variant_name))
    if filt is not None:
        for k in (0.8, 1.2):
            sub = [t for t in trades if filt(t["snapshot"], k)]
            if len(sub) >= MIN_VARIANT_TRAIN_TRADES:
                expk = sum(_f(t["return_pct"]) for t in sub) / len(sub)
                _add(f"Parameter perturbation ×{k}",
                     f"{expk:+.3f}%/trade over {len(sub)} trades", expk > 0)
            else:
                _add(f"Parameter perturbation ×{k}",
                     f"only {len(sub)} trades survive", False)

    passed = all(c["passed"] for c in checks)
    return {"checks": checks, "passed": passed,
            "note": "" if passed else
            "Failed checks are preserved above — this variant is NOT validated."}


# ── §11 E/F portfolio simulation ─────────────────────────────────────────────

def simulate_ef_window(selected: dict[str, tuple[str, callable | None]],
                       eligibility: dict[tuple[str, str], str] | None,
                       sym_recs: dict[str, list[dict]],
                       span_pos: dict[str, tuple[int, int]],
                       test_dates: list[str],
                       regime_by_date: dict[str, str],
                       cost_model: CostModel, cfg) -> dict:
    """Portfolio replay for model E (eligibility=None) or F (regime
    eligibility gate + cash fallback). `selected` maps strategy_id →
    (variant_name, filter_fn|None); strategies absent from the map are not
    traded at all. Entries queue at the signal close and fill next day."""
    strategies = {sid: STRATEGY_REGISTRY[sid] for sid in selected}
    date_idx: dict[str, dict[str, int]] = {}
    sig_exit_cache: dict[tuple[str, str], set[str]] = {}
    for sym, recs in sym_recs.items():
        if sym not in span_pos:
            continue
        start, end = span_pos[sym]
        date_idx[sym] = {str(recs[i]["date"])[:10]: i for i in range(start, end + 1)}
        for sid, strat in strategies.items():
            sig_exit_cache[(sid, sym)] = _signal_exit_dates(strat, recs, start, end)

    cash = cfg.initial_capital
    positions: dict[str, dict] = {}
    pending: list[dict] = []
    trades: list[dict] = []
    equity_curve: list[float] = []
    daily_cash_frac: list[float] = []

    def _mark(sym: str, d: str) -> float:
        i = date_idx.get(sym, {}).get(d)
        if i is not None:
            return _f(sym_recs[sym][i]["close"])
        pos = positions.get(sym)
        return _f(pos["last_close"]) if pos else 0.0

    for di, day in enumerate(test_dates):
        is_last = di == len(test_dates) - 1

        # 1. exits
        for sym in list(positions):
            pos = positions[sym]
            i = date_idx.get(sym, {}).get(day)
            if i is None:
                if is_last:
                    _close_ef(trades, positions, cost_model, sym, pos, day,
                              pos["last_close"], EXIT_FORCED)
                    cash += trades[-1]["exit_price"] * trades[-1]["quantity"] \
                        - trades[-1]["sell_costs"]["total"]
                continue
            recs = sym_recs[sym]
            c = recs[i]
            candle = {"open": _f(c["open"]), "high": _f(c["high"]),
                      "low": _f(c["low"]), "close": _f(c["close"])}
            pos["last_close"] = candle["close"]
            if pos["entry_price"] > 0:
                pos["mae_pct"] = min(pos["mae_pct"],
                                     (candle["low"] - pos["entry_price"]) / pos["entry_price"] * 100.0)
                pos["mfe_pct"] = max(pos["mfe_pct"],
                                     (candle["high"] - pos["entry_price"]) / pos["entry_price"] * 100.0)
            pos["holding_days"] += 1
            exited, raw_exit, reason, _b = evaluate_exit_candle(
                candle, pos["stop_loss"], pos["target"], cfg.intrabar_rule)
            if not exited:
                if day in sig_exit_cache.get((pos["strategy_id"], sym), set()):
                    exited, raw_exit, reason = True, candle["close"], EXIT_SIGNAL
                elif pos["holding_days"] >= cfg.max_holding_days:
                    exited, raw_exit, reason = True, candle["close"], EXIT_TIME
                elif is_last:
                    exited, raw_exit, reason = True, candle["close"], EXIT_FORCED
            if exited:
                _close_ef(trades, positions, cost_model, sym, pos, day,
                          raw_exit, reason)
                cash += trades[-1]["exit_price"] * trades[-1]["quantity"] \
                    - trades[-1]["sell_costs"]["total"]

        # 2. queued entries fill at today's open
        if not is_last:
            for rec in pending:
                sym = rec["sym"]
                if sym in positions or len(positions) >= MAX_OPEN_EF:
                    continue
                i = date_idx.get(sym, {}).get(day)
                if i is None:
                    continue
                c = sym_recs[sym][i]
                candle = {"date": day, "open": _f(c["open"]), "high": _f(c["high"]),
                          "low": _f(c["low"]), "close": _f(c["close"]),
                          "volume": _f(c["volume"])}
                equity = cash + sum(p["quantity"] * _mark(s, day)
                                    for s, p in positions.items())
                alloc = equity * ALLOC_PCT_EF
                fill = simulate_entry(cost_model, candle, rec["price"], cash, alloc)
                if not fill.get("filled"):
                    continue
                cash -= fill["cash_used"]
                positions[sym] = {
                    "entry_date": day, "entry_price": fill["fill_price"],
                    "raw_open": fill["raw_open"], "quantity": fill["quantity"],
                    "requested_quantity": fill["requested_quantity"],
                    "partial_fill": fill["partial_fill"],
                    "gap_pct": fill["gap_pct"], "buy_costs": fill["buy_costs"],
                    "stop_loss": rec["stop_loss"], "target": rec["target"],
                    "strategy_id": rec["strategy_id"],
                    "variant": rec["variant"],
                    "sector": rec["sector"], "market_regime": rec["regime"],
                    "holding_days": 0, "mae_pct": 0.0, "mfe_pct": 0.0,
                    "last_close": candle["close"],
                }
        pending = []

        # 3. new signals at today's close (fill tomorrow)
        if not is_last:
            regime = regime_by_date.get(day, "Sideways")
            candidates = []
            for sid, (variant_name, filt) in selected.items():
                if eligibility is not None and \
                        eligibility.get((sid, regime), ST_INSUFFICIENT) != ST_ELIGIBLE:
                    continue  # cash fallback — strategy not eligible in regime
                strat = strategies[sid]
                for sym, recs in sym_recs.items():
                    if sym in positions or sym not in date_idx:
                        continue
                    i = date_idx[sym].get(day)
                    if i is None or i < WARMUP_BARS + 5:
                        continue
                    try:
                        ok, _r = strat.check_entry(recs[i], recs[i - 1])
                    except Exception:
                        ok = False
                    if not ok:
                        continue
                    price = _f(recs[i]["close"])
                    if price <= 0:
                        continue
                    snap = _snapshot(recs, i, regime, _sector_of(sym))
                    snap["gap_pct"] = 0.0
                    if filt is not None and not filt(snap):
                        continue
                    try:
                        stop = float(strat.compute_stop_loss(recs[i], price))
                        target = float(strat.compute_target(price, stop))
                    except Exception:
                        continue
                    candidates.append({
                        "sym": sym, "price": price, "stop_loss": stop,
                        "target": target, "strategy_id": sid,
                        "variant": variant_name, "sector": snap["sector"],
                        "regime": regime, "adx": snap["adx"],
                    })
            # Deterministic ordering: strongest trend first, then symbol
            candidates.sort(key=lambda cnd: (-cnd["adx"], cnd["sym"]))
            slots = max(0, MAX_OPEN_EF - len(positions))
            pending = candidates[:slots]

        # 4. mark to market
        equity = cash + sum(p["quantity"] * _mark(s, day)
                            for s, p in positions.items())
        equity_curve.append(round(equity, 2))
        daily_cash_frac.append(cash / equity if equity > 0 else 1.0)

    nd = len(daily_cash_frac)
    return {
        "trades": trades,
        "equity_curve": equity_curve,
        "cash_time_pct": round(sum(daily_cash_frac) / nd * 100.0, 1) if nd else 100.0,
    }


def _close_ef(trades: list, positions: dict, cost_model: CostModel, sym: str,
              pos: dict, day: str, raw_exit: float, reason: str) -> None:
    sell_price = effective_sell_price(cost_model, raw_exit)
    turnover = sell_price * pos["quantity"]
    entry = {"entry_date": pos["entry_date"], "raw_open": pos["raw_open"],
             "fill_price": pos["entry_price"], "quantity": pos["quantity"],
             "requested_quantity": pos["requested_quantity"],
             "partial_fill": pos["partial_fill"], "gap_pct": pos["gap_pct"],
             "buy_costs": pos["buy_costs"]}
    exit_info = {"exit_date": day, "raw_exit_price": round(raw_exit, 4),
                 "sell_price": round(sell_price, 4), "exit_reason": reason,
                 "holding_days": pos["holding_days"],
                 "mae_pct": round(pos["mae_pct"], 2),
                 "mfe_pct": round(pos["mfe_pct"], 2),
                 "intrabar_rule": INTRABAR_CONSERVATIVE,
                 "intrabar_rule_label": INTRABAR_RULE_LABELS[INTRABAR_CONSERVATIVE],
                 "sell_turnover": round(turnover, 2),
                 "sell_costs": side_costs(cost_model, turnover, "sell")}
    meta = {"strategy_id": pos["strategy_id"], "variant": pos["variant"],
            "sector": pos["sector"], "market_regime": pos["market_regime"]}
    trades.append(build_trade_record(sym, entry, exit_info, meta))
    del positions[sym]


# ── Loss attribution (§3 narrative, derived from the comparison table) ───────

def _loss_attribution(strategy_id: str, baseline: list[dict],
                      alt_metrics: dict[str, dict]) -> list[str]:
    findings: list[str] = []
    n = len(baseline)
    if n == 0:
        return ["No baseline trades — nothing to attribute."]
    reasons: dict[str, int] = {}
    gap_exits = both = 0
    for t in baseline:
        reasons[t.get("exit_reason", "?")] = reasons.get(t.get("exit_reason", "?"), 0) + 1
        raw = _f(t.get("raw_exit_price"))
        stop_lvl = _f(t.get("_spec", {}).get("stop"))
        if t.get("exit_reason") == EXIT_STOP and stop_lvl > 0 and raw < stop_lvl * 0.995:
            gap_exits += 1
    stop_rate = reasons.get(EXIT_STOP, 0) / n * 100.0
    target_rate = reasons.get(EXIT_TARGET, 0) / n * 100.0
    time_rate = reasons.get(EXIT_TIME, 0) / n * 100.0

    base_exp = alt_metrics["A"]["expectancy_pct"] or 0.0

    def _better(key: str) -> bool:
        m = alt_metrics.get(key) or {}
        return m.get("expectancy_pct") is not None and m["expectancy_pct"] > base_exp + 0.05

    if stop_rate > 40 and (_better("C") or _better("B")):
        findings.append(
            f"Stop-loss appears TOO TIGHT: {stop_rate:.0f}% of trades stop out, and "
            f"wider/trailing stops (alternatives B/C) improve expectancy.")
    if stop_rate > 40 and not (_better("B") or _better("C")):
        findings.append(
            f"{stop_rate:.0f}% of trades hit the stop, but wider stops do NOT help — "
            f"losses come from entry selection, not stop placement.")
    if target_rate < 15 and _better("D"):
        findings.append(
            f"Target appears TOO AMBITIOUS: only {target_rate:.0f}% of trades reach it, "
            f"and removing the target (signal-only exit D) improves expectancy.")
    if time_rate > 30:
        m_e = alt_metrics.get("E") or {}
        if (m_e.get("expectancy_pct") or -9) > base_exp:
            findings.append(
                f"Time exits dominate ({time_rate:.0f}%) and a shorter fixed "
                f"{TIME_ONLY_HOLD_DAYS}-day horizon (E) does better — signal exits fire too late.")
        else:
            findings.append(
                f"Time exits dominate ({time_rate:.0f}%) — the exit signal rarely "
                f"fires before the holding cap.")
    if _better("G"):
        findings.append(
            "A break-even stop after +1×ATR (G) improves expectancy — winners are "
            "being allowed to turn back into losers.")
    if gap_exits > 0:
        findings.append(
            f"Gap risk: {gap_exits} stop exits filled BELOW the stop level via an "
            f"opening gap ({gap_exits / n * 100.0:.0f}% of trades).")
    if not findings:
        findings.append(
            "No single exit mechanism explains the results — differences between "
            "exit alternatives are small relative to entry-selection effects.")
    return findings


# ── Recommendation per strategy (§10/§12) ────────────────────────────────────

def _recommend(strategy_id: str, name: str, test_baseline: list[dict],
               variant_rows: list[dict], windows_positive: int,
               windows_total: int) -> dict:
    n = len(test_baseline)
    m = _metrics(test_baseline)
    validated = [v for v in variant_rows
                 if v.get("robustness", {}).get("passed") and v.get("selected_any_window")]
    if n < 10:
        return {"strategy_id": strategy_id, "name": name,
                "recommendation": "INCONCLUSIVE",
                "reason": (f"Only {n} out-of-sample audit trades — below the "
                           f"minimum of 10 needed to judge an edge either way.")}
    exp = m["expectancy_pct"] or 0.0
    pf = m["profit_factor"] or 0.0
    if exp > 0.05 and pf >= 1.1 and windows_positive * 2 >= windows_total:
        return {"strategy_id": strategy_id, "name": name,
                "recommendation": "KEEP",
                "reason": (f"Positive net edge out-of-sample: {exp:+.2f}%/trade, "
                           f"PF {pf}, positive in {windows_positive}/{windows_total} "
                           f"windows over {n} trades.")}
    if validated:
        best = max(validated, key=lambda v: v["test"]["expectancy_pct"] or -99)
        return {"strategy_id": strategy_id, "name": name,
                "recommendation": "MODIFY",
                "reason": (f"Baseline edge is {exp:+.2f}%/trade (PF {pf}) but variant "
                           f"'{best['name']}' passed all robustness checks with "
                           f"{(best['test']['expectancy_pct'] or 0):+.2f}%/trade over "
                           f"{best['test']['trades']} out-of-sample trades. "
                           f"Adopting it requires an explicit, separate decision.")}
    if exp <= -0.05 and n >= 20:
        return {"strategy_id": strategy_id, "name": name,
                "recommendation": "DISABLE",
                "reason": (f"Negative net edge out-of-sample: {exp:+.2f}%/trade, "
                           f"PF {pf} over {n} trades, and no controlled variant "
                           f"survived robustness checks.")}
    return {"strategy_id": strategy_id, "name": name,
            "recommendation": "INCONCLUSIVE",
            "reason": (f"Edge is statistically indistinguishable from zero "
                       f"({exp:+.2f}%/trade, PF {pf}, {n} trades) and no variant "
                       f"passed every robustness check.")}


# ── Main entry point ─────────────────────────────────────────────────────────

def run_strategy_audit(sym_rows: dict[str, pd.DataFrame],
                       windows: list[dict],
                       regime_by_date: dict[str, str],
                       test_dates_by_window: dict[str, list[str]],
                       cfg, cost_model: CostModel,
                       existing_overall: dict | None = None,
                       existing_cash: dict | None = None,
                       random_seed: int = 42,
                       progress_cb=None) -> dict:
    """Run the complete Phase 2B audit across all walk-forward windows.

    sym_rows           — {sym: enriched DataFrame with 'date' column}
    windows            — the validator's window dicts (train/test bounds)
    regime_by_date     — {date_str: 7-way regime} (as-of, no lookahead)
    test_dates_by_window — {window label: [test day date_str, ...]}
    existing_overall   — validator's overall metrics for variants A–D (§11)
    existing_cash      — {variant: cash_time_pct} for A–D
    """
    import validation_metrics as vm

    rng = random.Random(random_seed)
    sym_recs = {sym: rows.to_dict("records") for sym, rows in sym_rows.items()}
    strategy_ids = [sid for sid in LAB_STRATEGY_IDS if sid in STRATEGY_REGISTRY]

    # Accumulators across windows
    test_trades: dict[str, list[dict]] = {sid: [] for sid in strategy_ids}
    alt_all: dict[str, dict[str, list[dict]]] = {
        sid: {k: [] for k in EXIT_ALT_LABELS} for sid in strategy_ids}
    bucket_all: dict[str, dict[int, list[dict]]] = {
        sid: {b: [] for b, _ in HOLDING_BUCKETS} for sid in strategy_ids}
    train_bucket_sel: dict[str, list[int]] = {sid: [] for sid in strategy_ids}
    variant_test: dict[tuple[str, str], list[dict]] = {}
    variant_train_stats: dict[tuple[str, str], list[dict]] = {}
    variant_selected_windows: dict[tuple[str, str], int] = {}
    window_exp: dict[str, list[float]] = {sid: [] for sid in strategy_ids}
    skipped_entries = 0

    ef_trades: dict[str, list[dict]] = {"E": [], "F": []}
    ef_chain: dict[str, list[float]] = {"E": [], "F": []}
    ef_factor = {"E": 1.0, "F": 1.0}
    ef_cash_days = {"E": [0.0, 0], "F": [0.0, 0]}
    ef_selections: list[dict] = []
    total_test_days = 0

    def _span_pos(t0: pd.Timestamp, t1: pd.Timestamp) -> dict[str, tuple[int, int]]:
        out = {}
        for sym, rows in sym_rows.items():
            dates = rows["date"]
            idx = [i for i, d in enumerate(dates) if t0 <= d <= t1]
            if len(idx) >= 5:
                out[sym] = (idx[0], idx[-1])
        return out

    valid_windows = [w for w in windows if not w.get("failed")]
    for wi, window in enumerate(valid_windows):
        label = window.get("label", f"W{wi + 1}")
        if progress_cb:
            progress_cb(f"Phase 2B audit — window {label}")
        train_span = _span_pos(pd.Timestamp(window["train_start"]),
                               pd.Timestamp(window["train_end"]))
        test_span = _span_pos(pd.Timestamp(window["test_start"]),
                              pd.Timestamp(window["test_end"]))
        test_dates = test_dates_by_window.get(label, [])
        total_test_days += len(test_dates)

        selections: dict[str, tuple[str, callable | None]] = {}
        window_eligibility: dict[tuple[str, str], str] = {}

        for sid in strategy_ids:
            strategy = STRATEGY_REGISTRY[sid]
            # TRAIN pass — selection data only (no alternatives needed)
            train_out = audit_window_pass(
                strategy, sym_recs, train_span, regime_by_date, cost_model,
                cfg, label, collect_alternatives=False)
            # TEST pass — full evaluation
            test_out = audit_window_pass(
                strategy, sym_recs, test_span, regime_by_date, cost_model,
                cfg, label, collect_alternatives=True)
            skipped_entries += train_out["skipped_entries"] + test_out["skipped_entries"]

            test_trades[sid].extend(test_out["baseline"])
            for k in EXIT_ALT_LABELS:
                alt_all[sid][k].extend(test_out["alternatives"][k])
            for b, _l in HOLDING_BUCKETS:
                bucket_all[sid][b].extend(test_out["buckets"][b])
            if test_out["baseline"]:
                window_exp[sid].append(
                    sum(_f(t["return_pct"]) for t in test_out["baseline"])
                    / len(test_out["baseline"]))

            # §4 train-only holding selection: re-simulate train entries under
            # each bucket and pick the best shrunk expectancy.
            train_trades = train_out["baseline"]
            best_bucket, best_val = None, None
            for b, _l in HOLDING_BUCKETS:
                resim = []
                for t in train_trades:
                    spec = t["_spec"]
                    fill = {"fill_price": t["entry_price"], "raw_open": t["raw_open"],
                            "quantity": t["quantity"]}
                    ex = walk_exit(cost_model, sym_recs[spec["sym"]],
                                   spec["entry_pos"], spec["end"], fill,
                                   spec["stop"], spec["target"], set(),
                                   cfg.intrabar_rule, b,
                                   entry_atr=spec["entry_atr"])
                    sell = ex["sell_price"] * t["quantity"]
                    net = (sell - t["entry_price"] * t["quantity"]
                           - t["buy_costs"]["total"] - ex["sell_costs"]["total"])
                    inv = t["entry_price"] * t["quantity"]
                    resim.append(net / inv * 100.0 if inv > 0 else 0.0)
                if len(resim) >= MIN_VARIANT_TRAIN_TRADES:
                    val = _shrunk_mean(resim)
                    if best_val is None or val > best_val:
                        best_bucket, best_val = b, val
            if best_bucket is not None:
                train_bucket_sel[sid].append(best_bucket)

            # §8 variants: filter TRAIN trades for selection, TEST for evaluation
            candidates: list[tuple[str, callable | None, float, int]] = []
            train_rets_base = [_f(t["return_pct"]) for t in train_trades]
            if len(train_rets_base) >= MIN_VARIANT_TRAIN_TRADES:
                candidates.append(("baseline", None,
                                   _shrunk_mean(train_rets_base),
                                   len(train_rets_base)))
            for vname, vdesc in VARIANT_DEFS.get(sid, []):
                filt = VARIANT_FILTERS[(sid, vname)]
                tr_sub = [t for t in train_trades if filt(t["snapshot"])]
                te_sub = [t for t in test_out["baseline"] if filt(t["snapshot"])]
                variant_test.setdefault((sid, vname), []).extend(te_sub)
                rets = [_f(t["return_pct"]) for t in tr_sub]
                variant_train_stats.setdefault((sid, vname), []).append(
                    {"window": label, "trades": len(tr_sub),
                     "shrunk_expectancy_pct": round(_shrunk_mean(rets), 3)})
                if len(rets) >= MIN_VARIANT_TRAIN_TRADES:
                    candidates.append((vname, filt, _shrunk_mean(rets), len(rets)))

            # §11 selection: best positive shrunk TRAIN expectancy
            picked = None
            for cname, cfilt, cval, cn in sorted(candidates, key=lambda x: -x[2]):
                if cval > 0:
                    picked = (cname, cfilt)
                    break
            if picked is not None:
                selections[sid] = picked
                if picked[0] != "baseline":
                    variant_selected_windows[(sid, picked[0])] = \
                        variant_selected_windows.get((sid, picked[0]), 0) + 1

            # §5/§11-F eligibility from TRAIN trades per regime
            by_regime: dict[str, list[dict]] = {}
            for t in train_trades:
                by_regime.setdefault(t.get("market_regime", "Sideways"), []).append(t)
            for regime, tl in by_regime.items():
                status, _reason = classify_strategy_regime(tl)
                window_eligibility[(sid, regime)] = status

        ef_selections.append({
            "window": label,
            "selected": {sid: sel[0] for sid, sel in selections.items()},
            "excluded": [sid for sid in strategy_ids if sid not in selections],
        })

        # §11 E and F portfolio replays on the unseen test window
        for model, elig in (("E", None), ("F", window_eligibility)):
            out = simulate_ef_window(selections, elig, sym_recs, test_span,
                                     test_dates, regime_by_date, cost_model, cfg)
            for t in out["trades"]:
                t["window"] = label
            ef_trades[model].extend(out["trades"])
            base = cfg.initial_capital
            for v in out["equity_curve"]:
                ef_chain[model].append(round(ef_factor[model] * v / base * base, 2))
            if out["equity_curve"]:
                ef_factor[model] *= out["equity_curve"][-1] / base
            ef_cash_days[model][0] += out["cash_time_pct"] / 100.0 * len(test_dates)
            ef_cash_days[model][1] += len(test_dates)

    # ── Aggregation ─────────────────────────────────────────────────────────
    n_windows = len(valid_windows)
    scorecards = []
    entry_conditions = []
    exit_comparison = []
    loss_attribution = []
    holding_comparison = []
    regime_eligibility = []
    cost_sensitivity = []
    variants_out = []
    recommendations = []

    for sid in strategy_ids:
        strategy = STRATEGY_REGISTRY[sid]
        trades = test_trades[sid]
        m = vm.compute_performance_metrics(
            sorted(trades, key=lambda t: (str(t["exit_date"]), t["symbol"])),
            AUDIT_NOTIONAL,
            _cum_equity(trades), trading_days=total_test_days)
        reasons: dict[str, int] = {}
        for t in trades:
            reasons[t.get("exit_reason", "?")] = reasons.get(t.get("exit_reason", "?"), 0) + 1
        n = len(trades)
        hold = sorted(int(t.get("holding_days", 0)) for t in trades)
        gross_rets = [_reprice_trade(t, _scaled_cost_model(cost_model, 0.0))["return_pct"]
                      for t in trades]
        scorecards.append({
            "strategy_id": sid, "name": strategy.name,
            "metrics": m,
            "gross_return_pct": round(sum(gross_rets), 2),
            "net_return_pct_sum": round(sum(_f(t["return_pct"]) for t in trades), 2),
            "reward_risk_realised": _reward_risk(trades),
            "median_holding_days": hold[n // 2] if n else None,
            "avg_mae_pct": round(sum(_f(t["mae_pct"]) for t in trades) / n, 2) if n else None,
            "avg_mfe_pct": round(sum(_f(t["mfe_pct"]) for t in trades) / n, 2) if n else None,
            "stop_hit_rate": round(reasons.get(EXIT_STOP, 0) / n * 100.0, 1) if n else None,
            "target_hit_rate": round(reasons.get(EXIT_TARGET, 0) / n * 100.0, 1) if n else None,
            "signal_exit_rate": round(reasons.get(EXIT_SIGNAL, 0) / n * 100.0, 1) if n else None,
            "time_exit_rate": round(reasons.get(EXIT_TIME, 0) / n * 100.0, 1) if n else None,
            "forced_exit_rate": round(reasons.get(EXIT_FORCED, 0) / n * 100.0, 1) if n else None,
            "breakdowns": {
                "by_regime": _breakdown(trades, lambda t: t.get("market_regime", "?")),
                "by_sector": _breakdown(trades, lambda t: t.get("sector", "?")),
                "by_holding_bucket": _breakdown(
                    trades, lambda t: _holding_bucket_label(int(t.get("holding_days", 0)))),
                "by_entry_subtype": _breakdown(trades, lambda t: t.get("entry_subtype", "?")),
                "by_exit_reason": _breakdown(trades, lambda t: t.get("exit_reason", "?")),
                "by_volatility_band": _breakdown(trades, lambda t: _vol_band(t["snapshot"])),
                "by_trend_band": _breakdown(trades, lambda t: _trend_band(t["snapshot"])),
                "by_volume_band": _breakdown(trades, lambda t: _volume_band(t["snapshot"])),
            },
        })

        entry_conditions.append({
            "strategy_id": sid, "name": strategy.name,
            "conditions": condition_diagnostics(trades),
        })

        alt_metrics = {k: _metrics(v) for k, v in alt_all[sid].items()}
        exit_comparison.append({
            "strategy_id": sid, "name": strategy.name,
            "alternatives": [
                {"key": k, "label": EXIT_ALT_LABELS[k], **alt_metrics[k]}
                for k in "ABCDEFG"
            ],
        })
        loss_attribution.append({
            "strategy_id": sid, "name": strategy.name,
            "findings": _loss_attribution(sid, trades, alt_metrics),
        })

        sel_counts: dict[int, int] = {}
        for b in train_bucket_sel[sid]:
            sel_counts[b] = sel_counts.get(b, 0) + 1
        holding_comparison.append({
            "strategy_id": sid, "name": strategy.name,
            "buckets": [
                {"max_holding_days": b, "label": lbl, **_metrics(bucket_all[sid][b])}
                for b, lbl in HOLDING_BUCKETS
            ],
            "train_selected": [
                {"max_holding_days": b, "windows_selected": c}
                for b, c in sorted(sel_counts.items())
            ],
            "note": ("Bucket selection used TRAINING data only; the table above "
                     "shows how each bucket then performed on unseen test data."),
        })

        by_regime: dict[str, list[dict]] = {}
        for t in trades:
            by_regime.setdefault(t.get("market_regime", "Sideways"), []).append(t)
        regime_rows = []
        for regime in sorted(by_regime):
            tl = by_regime[regime]
            status, reason = classify_strategy_regime(tl)
            mm = _metrics(tl)
            regime_rows.append({"regime": regime, **mm,
                                "shrunk_expectancy_pct": round(
                                    _shrunk_mean([_f(t["return_pct"]) for t in tl]), 3),
                                "status": status, "reason": reason})
        regime_eligibility.append({"strategy_id": sid, "name": strategy.name,
                                   "regimes": regime_rows})

        scen_rows = []
        for mult, lbl in ((0.0, "Zero costs"), (1.0, "Current realistic costs"),
                          (1.25, "Current +25%"), (1.5, "Current +50%")):
            cm2 = _scaled_cost_model(cost_model, mult)
            rp = [_reprice_trade(t, cm2)["return_pct"] for t in trades]
            nn = len(rp)
            wins = sum(1 for r in rp if r > 0)
            gw = sum(r for r in rp if r > 0)
            gl = -sum(r for r in rp if r <= 0)
            scen_rows.append({
                "label": lbl, "multiplier": mult,
                "net_return_pct": round(sum(rp), 2),
                "expectancy_pct": round(sum(rp) / nn, 3) if nn else None,
                "profit_factor": round(min(gw / gl, 99.0), 2) if gl > 1e-9
                                 else (99.0 if gw > 0 else 0.0),
                "win_rate": round(wins / nn * 100.0, 1) if nn else None,
            })
        gross_pos = (scen_rows[0]["expectancy_pct"] or 0) > 0
        net_pos = (scen_rows[1]["expectancy_pct"] or 0) > 0
        flags = []
        if gross_pos and not net_pos:
            flags.append("Gross edge is positive but costs erase it — execution "
                         "costs are the primary problem; lower trade frequency or "
                         "longer holds could help.")
        if not gross_pos:
            flags.append("Edge is negative even with ZERO costs — the entry/exit "
                         "logic itself has no edge; cost reduction cannot fix it.")
        if gross_pos and net_pos and (scen_rows[3]["expectancy_pct"] or 0) <= 0:
            flags.append("Edge survives current costs but dies at +50% — thin margin.")
        cost_sensitivity.append({"strategy_id": sid, "name": strategy.name,
                                 "scenarios": scen_rows,
                                 "gross_edge_positive": gross_pos,
                                 "net_edge_positive": net_pos,
                                 "flags": flags})

        # §8 variant evaluation + §7 robustness
        variant_rows = []
        for vname, vdesc in VARIANT_DEFS.get(sid, []):
            te = variant_test.get((sid, vname), [])
            te_m = _metrics(te)
            rob = robustness_checks(te, sym_recs, cost_model, cfg, rng, sid, vname)
            variant_rows.append({
                "name": vname, "description": vdesc,
                "test": te_m,
                "train_windows": variant_train_stats.get((sid, vname), []),
                "selected_any_window": variant_selected_windows.get((sid, vname), 0) > 0,
                "windows_selected": variant_selected_windows.get((sid, vname), 0),
                "vs_baseline_expectancy_diff": (
                    round((te_m["expectancy_pct"] or 0)
                          - (_metrics(trades)["expectancy_pct"] or 0), 3)
                    if te_m["trades"] and trades else None),
                "robustness": rob,
            })
        variants_out.append({
            "strategy_id": sid, "name": strategy.name,
            "baseline": _metrics(trades),
            "variants": variant_rows,
            "note": ("Variants only FILTER the identical baseline entries — no new "
                     "entries are created, max 3 configurations per strategy, no "
                     "parameter search."),
        })

        wpos = sum(1 for e in window_exp[sid] if e > 0)
        recommendations.append(_recommend(sid, strategy.name, trades,
                                          variant_rows, wpos,
                                          max(1, len(window_exp[sid]))))

    # §11 model comparison table
    model_comparison = _model_comparison(
        existing_overall or {}, existing_cash or {}, ef_trades, ef_chain,
        ef_cash_days, cfg, total_test_days, vm)

    final_report = _final_report(recommendations, scorecards, entry_conditions,
                                 exit_comparison, holding_comparison,
                                 cost_sensitivity, variants_out,
                                 model_comparison)

    # Strip internal fields from anything that reaches the payload
    for sc in scorecards:
        pass  # scorecards only carry aggregates already

    return {
        "notional_per_trade": AUDIT_NOTIONAL,
        "methodology": (
            "Every strategy was audited on ALL of its raw entry signals across "
            "the full universe (no ranking, no portfolio caps, no confidence "
            "filter), each filled at the next day's open with a fixed "
            f"₹{AUDIT_NOTIONAL:,.0f} notional and realistic costs. Exit "
            "alternatives and holding buckets were re-simulated on IDENTICAL "
            "entries. Variant and holding selection used TRAINING windows only; "
            "all tables below show unseen TEST-window results. Failed variants "
            "and negative results are preserved."),
        "windows_evaluated": n_windows,
        "skipped_entries": skipped_entries,
        "scorecards": scorecards,
        "entry_conditions": entry_conditions,
        "exit_comparison": exit_comparison,
        "loss_attribution": loss_attribution,
        "holding_comparison": holding_comparison,
        "regime_eligibility": regime_eligibility,
        "cost_sensitivity": cost_sensitivity,
        "variants": variants_out,
        "ef_selections": ef_selections,
        "model_comparison": model_comparison,
        "recommendations": recommendations,
        "final_report": final_report,
        "safety": SAFETY_MESSAGE,
    }


def _cum_equity(trades: list[dict]) -> list[float]:
    """Equity curve for compute_performance_metrics: audit notional plus
    cumulative net P&L in exit order."""
    eq = [AUDIT_NOTIONAL]
    for t in sorted(trades, key=lambda x: str(x.get("exit_date") or "")):
        eq.append(eq[-1] + _f(t.get("net_pnl")))
    return eq


def _reward_risk(trades: list[dict]) -> float | None:
    wins = [_f(t["return_pct"]) for t in trades if _f(t["return_pct"]) > 0]
    losses = [-_f(t["return_pct"]) for t in trades if _f(t["return_pct"]) <= 0]
    if not wins or not losses:
        return None
    al = sum(losses) / len(losses)
    return round((sum(wins) / len(wins)) / al, 2) if al > 0 else None


def _breakdown(trades: list[dict], key_fn) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for t in trades:
        groups.setdefault(str(key_fn(t)), []).append(t)
    return [{"group": k, **_metrics(v)} for k, v in sorted(groups.items())]


def _model_comparison(existing_overall: dict, existing_cash: dict,
                      ef_trades: dict, ef_chain: dict, ef_cash_days: dict,
                      cfg, total_test_days: int, vm) -> list[dict]:
    rows = []
    for key in ("A", "B", "C", "D"):
        m = existing_overall.get(key) or {}
        rows.append({
            "model": key, "label": MODEL_LABELS_2B[key],
            "net_return_pct": m.get("total_return_pct"),
            "net_profit": m.get("net_profit"),
            "profit_factor": m.get("profit_factor"),
            "expectancy": m.get("expectancy"),
            "total_trades": m.get("total_trades"),
            "win_rate": m.get("win_rate"),
            "sharpe_ratio": m.get("sharpe_ratio"),
            "sortino_ratio": m.get("sortino_ratio"),
            "max_drawdown_pct": m.get("max_drawdown_pct"),
            "exposure_pct": m.get("exposure_pct"),
            "turnover": m.get("turnover"),
            "total_costs": m.get("total_costs"),
            "cash_time_pct": existing_cash.get(key),
        })
    for key in ("E", "F"):
        trades = sorted(ef_trades[key], key=lambda t: (str(t["exit_date"]), t["symbol"]))
        m = vm.compute_performance_metrics(
            trades, cfg.initial_capital, ef_chain[key] or [cfg.initial_capital],
            trading_days=total_test_days)
        cw, cd = ef_cash_days[key]
        rows.append({
            "model": key, "label": MODEL_LABELS_2B[key],
            "net_return_pct": m["total_return_pct"],
            "net_profit": m["net_profit"],
            "profit_factor": m["profit_factor"],
            "expectancy": m["expectancy"],
            "total_trades": m["total_trades"],
            "win_rate": m["win_rate"],
            "sharpe_ratio": m["sharpe_ratio"],
            "sortino_ratio": m["sortino_ratio"],
            "max_drawdown_pct": m["max_drawdown_pct"],
            "exposure_pct": m["exposure_pct"],
            "turnover": m["turnover"],
            "total_costs": m["total_costs"],
            "cash_time_pct": round(cw / cd * 100.0, 1) if cd else 100.0,
        })
    return rows


def _final_report(recommendations, scorecards, entry_conditions,
                  exit_comparison, holding_comparison, cost_sensitivity,
                  variants_out, model_comparison) -> dict:
    """§12 — plain answers to the ten completion questions."""
    keep = [r for r in recommendations if r["recommendation"] == "KEEP"]
    disable = [r for r in recommendations if r["recommendation"] == "DISABLE"]
    modify = [r for r in recommendations if r["recommendation"] == "MODIFY"]

    useful_filters = []
    for ec in entry_conditions:
        for c in ec["conditions"]:
            if c["verdict"] == "USEFUL":
                useful_filters.append(f"{ec['name']}: {c['condition']} "
                                      f"({c['expectancy_diff_pct']:+.2f}%/trade)")
    helpful_exits = []
    for xc in exit_comparison:
        base = next((a for a in xc["alternatives"] if a["key"] == "A"), {})
        for a in xc["alternatives"]:
            if a["key"] == "A" or a["expectancy_pct"] is None or \
                    base.get("expectancy_pct") is None:
                continue
            if a["expectancy_pct"] > base["expectancy_pct"] + 0.05 and a["trades"] >= 10:
                helpful_exits.append(f"{xc['name']}: {a['label']} "
                                     f"({a['expectancy_pct']:+.2f}% vs "
                                     f"{base['expectancy_pct']:+.2f}%/trade)")
    best_holdings = []
    for hc in holding_comparison:
        judged = [b for b in hc["buckets"] if b["trades"] >= 10
                  and b["expectancy_pct"] is not None]
        if judged:
            top = max(judged, key=lambda b: b["expectancy_pct"])
            best_holdings.append(f"{hc['name']}: {top['label']} "
                                 f"({top['expectancy_pct']:+.2f}%/trade)")
    costs_main = [cs["name"] for cs in cost_sensitivity
                  if cs["gross_edge_positive"] and not cs["net_edge_positive"]]
    no_gross = [cs["name"] for cs in cost_sensitivity if not cs["gross_edge_positive"]]

    passed_variants = []
    for vo in variants_out:
        for v in vo["variants"]:
            if v["robustness"].get("passed"):
                passed_variants.append(f"{vo['name']} — {v['name']}")

    rows = {r["model"]: r for r in model_comparison}
    a_ret = rows.get("A", {}).get("net_return_pct")
    e_ret = rows.get("E", {}).get("net_return_pct")
    f_ret = rows.get("F", {}).get("net_return_pct")
    ef_verdict = []
    if a_ret is not None and e_ret is not None:
        ef_verdict.append(
            f"Model E returned {e_ret:+.2f}% vs base engine {a_ret:+.2f}% — "
            + ("an improvement." if e_ret > a_ret else "NOT an improvement."))
    if a_ret is not None and f_ret is not None:
        ef_verdict.append(
            f"Model F returned {f_ret:+.2f}% vs base engine {a_ret:+.2f}% — "
            + ("an improvement." if f_ret > a_ret else "NOT an improvement."))

    safe = [r["name"] for r in keep]
    if safe:
        deploy_answer = ("Candidates with a demonstrated net positive edge: "
                         + ", ".join(safe) + ". Deployment still requires an "
                         "explicit manual decision — nothing is auto-promoted.")
        none_reason = ""
    else:
        deploy_answer = "NO strategy is currently safe to approve for paper deployment."
        none_reason = ("No strategy showed a positive net edge that survived "
                       "sample-size requirements, robustness checks and "
                       "multi-window confirmation. A valid outcome of this audit "
                       "is that no current strategy has a reliable edge — the "
                       "corrected gated model already responds correctly by "
                       "holding cash.")

    return {
        "q1_net_positive_edge": ([r["name"] + ": " + r["reason"] for r in keep]
                                 or ["None — no strategy showed a genuine net positive edge out-of-sample."]),
        "q2_should_disable": ([r["name"] + ": " + r["reason"] for r in disable]
                              or ["None met the evidence bar for outright disabling."]),
        "q3_entry_filters_helped": useful_filters or
            ["No entry filter cleared the statistical reliability bar."],
        "q4_exit_rules_helped": helpful_exits or
            ["No alternative exit consistently beat the existing logic."],
        "q5_best_holding_periods": best_holdings or
            ["No holding bucket had enough trades to judge."],
        "q6_costs_main_cause": (
            (f"Costs erase an otherwise-positive gross edge for: {', '.join(costs_main)}. "
             if costs_main else "Costs are NOT the primary cause of failure. ")
            + (f"No gross edge even at zero cost for: {', '.join(no_gross)}."
               if no_gross else "")),
        "q7_variants_passed": passed_variants or
            ["No proposed variant passed every walk-forward robustness check."],
        "q8_e_f_vs_base": ef_verdict or ["Model comparison unavailable."],
        "q9_safe_to_deploy": deploy_answer,
        "q10_reasons_if_none": none_reason,
        "modify_candidates": [r["name"] + ": " + r["reason"] for r in modify],
        "summary": (
            f"{len(keep)} strategy(ies) KEEP, {len(modify)} MODIFY, "
            f"{len(disable)} DISABLE, "
            f"{len(recommendations) - len(keep) - len(modify) - len(disable)} "
            f"INCONCLUSIVE. " + deploy_answer),
    }
