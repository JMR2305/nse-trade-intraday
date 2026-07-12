"""
macd_optimizer.py — Phase 3 MACD Optimization (ANALYSIS ONLY, NO NEW STRATEGIES).

Phase 2B found that only MACD Cross keeps a positive out-of-sample edge after
realistic NSE costs. Phase 3 evaluates controlled improvements to that ONE
strategy — entry filters, exit variations and portfolio risk rules — each
tested INDEPENDENTLY under walk-forward validation.

Ground rules enforced here:
  - MACD Cross only. No new strategies, indicators beyond those already
    computed, or AI models.
  - Entry filters only ever REMOVE baseline entries — never add new ones.
  - Every tunable parameter is selected on TRAINING windows only; all
    reported numbers come from unseen TEST windows.
  - Enhancements that fail to improve genuine out-of-sample performance are
    REJECTED, with the reason preserved.
  - Nothing here changes the live paper-trading pipeline; the final
    recommended configuration is a report, not a deployment.

PAPER TRADING AND RESEARCH ONLY.
"""

from __future__ import annotations

import math

import pandas as pd

from backtesting_engine import WARMUP_BARS
from execution_simulator import (
    CostModel, side_costs, effective_sell_price, simulate_entry,
    evaluate_exit_candle, build_trade_record,
    INTRABAR_CONSERVATIVE, INTRABAR_RULE_LABELS,
    EXIT_STOP, EXIT_TARGET, EXIT_SIGNAL, EXIT_TIME, EXIT_FORCED,
)
from market_scanner import _sector_of
from strategies import STRATEGY_REGISTRY
from strategy_audit import (
    _f, _metrics, _shrunk_mean, _cum_equity, _scaled_cost_model,
    walk_exit, _walk_partial, audit_window_pass, _signal_exit_dates,
    _snapshot, AUDIT_NOTIONAL, MIN_VARIANT_TRAIN_TRADES, MIN_REGIME_SAMPLE,
)

MACD_ID = "macd_cross"

SAFETY_MESSAGE = ("ANALYSIS ONLY — Phase 3 never changes live paper-trading "
                  "decisions. The recommended configuration is a research "
                  "finding; out-of-sample historical performance does not "
                  "guarantee future results.")

MIN_TEST_SAMPLE = 20        # below this a variation cannot be accepted
ACCEPT_MARGIN_PCT = 0.05    # required expectancy improvement (%/trade)

VERDICT_ACCEPTED = "ACCEPTED"
VERDICT_REJECTED = "REJECTED"
VERDICT_INSUFFICIENT = "INSUFFICIENT_SAMPLE"

COMBINED_CAVEAT = (
    "Each individual variation was accepted or rejected on unseen test "
    "windows (a fair out-of-sample test). The COMBINED configuration, "
    "however, is built from the variations that happened to pass on those "
    "same test windows, so its combined results carry selection bias and "
    "should be treated as exploratory — not as an independent out-of-sample "
    "validation. Confirmation requires fresh data the optimizer has never "
    "seen (continued paper trading).")

# ── Entry filters (predicates over the signal-bar snapshot) ──────────────────
# Each candidate parameter is selected on TRAIN data per window.

ENTRY_FILTER_DEFS: list[dict] = [
    {"id": "adx_strength", "name": "ADX trend strength",
     "description": "Take the crossover only when ADX shows a real trend.",
     "candidates": [15.0, 20.0, 25.0],
     "fmt": "ADX ≥ {p:g}",
     "pred": lambda s, p: s["adx"] >= p},
    {"id": "atr_volatility_cap", "name": "ATR volatility cap",
     "description": "Skip entries in excessively volatile stocks.",
     "candidates": [2.5, 3.5, 4.5],
     "fmt": "ATR ≤ {p:g}% of price",
     "pred": lambda s, p: 0.0 < s["atr_pct"] <= p},
    {"id": "volume_confirmation", "name": "Volume confirmation",
     "description": "Require volume at or above its 20-day average.",
     "candidates": [1.0, 1.2, 1.5],
     "fmt": "Volume ≥ {p:g}× average",
     "pred": lambda s, p: s["volume_ratio"] >= p},
    {"id": "crossover_quality", "name": "Crossover quality",
     "description": "Reject weak MACD crossovers (tiny histogram).",
     "candidates": [0.02, 0.05, 0.10],
     "fmt": "MACD histogram ≥ {p:g}% of price",
     "pred": lambda s, p: s["close"] > 0
     and s["macd_hist"] >= p / 100.0 * s["close"]},
    {"id": "trend_alignment", "name": "Long-term trend alignment",
     "description": "Trade only with the higher-timeframe trend "
                    "(price above EMA200 and EMA50 above EMA200).",
     "candidates": [1.0],
     "fmt": "Price > EMA200 and EMA50 > EMA200",
     "pred": lambda s, p: s["ema200"] > 0 and s["close"] > s["ema200"]
     and s["ema50"] > s["ema200"]},
    # regime_gate is handled specially (allowed set learned from TRAIN data)
]

REGIME_GATE_ID = "regime_gate"

# ── Exit variations (re-walked on IDENTICAL baseline entries) ────────────────
# kind: how the candidate parameter maps onto walk_exit arguments.

EXIT_TEST_DEFS: list[dict] = [
    {"id": "atr_stop", "name": "ATR-based stop-loss",
     "description": "Stop at signal close − m×ATR (baseline m=2).",
     "candidates": [1.5, 2.0, 2.5, 3.0], "fmt": "Stop = close − {p:g}×ATR",
     "kind": "atr_stop"},
    {"id": "atr_target", "name": "ATR-based profit target",
     "description": "Target at signal close + m×ATR.",
     "candidates": [1.5, 2.0, 2.5, 3.0], "fmt": "Target = close + {p:g}×ATR",
     "kind": "atr_target"},
    {"id": "trailing_stop", "name": "Trailing stop",
     "description": "2×ATR initial stop trailed at m×ATR below each close; "
                    "no fixed target, no signal exit.",
     "candidates": [1.5, 2.0, 3.0], "fmt": "Trail {p:g}×ATR",
     "kind": "trailing"},
    {"id": "time_exit", "name": "Time-based exit",
     "description": "Existing stops/targets with a tighter holding cap.",
     "candidates": [3, 5, 10, 15], "fmt": "Max hold {p:g} days",
     "kind": "time"},
    {"id": "partial_booking", "name": "Partial profit booking",
     "description": "Sell half at +1.5×ATR, trail the rest at 2×ATR.",
     "candidates": [1.0], "fmt": "Half off at +1.5×ATR, trail 2×ATR",
     "kind": "partial"},
    {"id": "dynamic_rr", "name": "Dynamic risk-reward target",
     "description": "Target = close + m×(close − stop); m tuned on training "
                    "data each window (baseline m=2.5).",
     "candidates": [1.5, 2.0, 2.5, 3.0], "fmt": "Target = {p:g}× risk",
     "kind": "rr"},
]

# ── Risk-management variants (portfolio-level, fixed rules — no tuning) ─────

BASE_RISK: dict = {
    "alloc_pct": 0.20, "max_open": 5,
    "vol_target_atr": None, "risk_per_trade_pct": None,
    "max_exposure_pct": None, "sector_cap": None,
    "daily_loss_limit_pct": None, "dd_protect_pct": None,
}

RISK_VARIANT_DEFS: list[dict] = [
    {"id": "vol_sizing", "name": "Volatility-adjusted position sizing",
     "description": "Scale each position so a 2%-ATR stock gets full size; "
                    "more volatile stocks get proportionally less.",
     "over": {"vol_target_atr": 2.0}},
    {"id": "risk_per_trade", "name": "Risk per trade ≤ 1% of equity",
     "description": "Cap position size so a stop-out loses at most 1% of "
                    "current equity.",
     "over": {"risk_per_trade_pct": 1.0}},
    {"id": "max_exposure", "name": "Maximum portfolio exposure 60%",
     "description": "Never have more than 60% of equity invested at once.",
     "over": {"max_exposure_pct": 60.0}},
    {"id": "sector_cap", "name": "Correlation-aware allocation",
     "description": "At most one open position per sector.",
     "over": {"sector_cap": 1}},
    {"id": "daily_loss_limit", "name": "Daily loss limit 2%",
     "description": "After a day losing more than 2% of equity, take no new "
                    "entries the next day.",
     "over": {"daily_loss_limit_pct": 2.0}},
    {"id": "dd_protection", "name": "Drawdown protection",
     "description": "Halve position size while equity is more than 10% below "
                    "its running peak.",
     "over": {"dd_protect_pct": 10.0}},
]


# ── Exit re-walk on one recorded baseline trade ──────────────────────────────

def _entry_dict(t: dict) -> dict:
    return {"entry_date": t["entry_date"], "raw_open": t["raw_open"],
            "fill_price": t["entry_price"], "quantity": t["quantity"],
            "requested_quantity": t["quantity"], "partial_fill": False,
            "gap_pct": t.get("gap_pct", 0.0), "buy_costs": t["buy_costs"]}


def _fill_dict(t: dict) -> dict:
    return {"entry_date": t["entry_date"], "fill_price": t["entry_price"],
            "raw_open": t["raw_open"],
            "quantity": t["quantity"], "requested_quantity": t["quantity"],
            "partial_fill": False, "gap_pct": t.get("gap_pct", 0.0),
            "buy_costs": t["buy_costs"]}


def rewalk_exit(t: dict, sym_recs: dict[str, list[dict]],
                cost_model: CostModel, cfg, kind: str, p: float) -> dict:
    """Re-simulate ONE baseline trade with an alternative exit rule. The
    entry (date, fill price, quantity, buy costs) is identical; only the
    exit changes. Returns a full trade record."""
    spec = t["_spec"]
    recs = sym_recs[spec["sym"]]
    close = _f(t["snapshot"]["close"])
    atr = _f(spec["entry_atr"])
    sig = spec.get("sig") or set()
    stop, target = spec["stop"], spec["target"]
    kw: dict = dict(use_signal=True, max_holding=cfg.max_holding_days,
                    trail=None)
    if kind == "atr_stop":
        stop = close - p * atr
    elif kind == "atr_target":
        target = close + p * atr
    elif kind == "trailing":
        stop, target = close - 2.0 * atr, 0.0
        kw.update(use_signal=False, trail=p)
    elif kind == "time":
        kw.update(max_holding=int(p))
    elif kind == "rr":
        target = close + p * max(close - stop, 0.0)
    elif kind == "partial":
        return _walk_partial(cost_model, recs, spec["entry_pos"], spec["end"],
                             _fill_dict(t), stop, sig, cfg.intrabar_rule,
                             cfg.max_holding_days, atr, spec["sym"])
    else:
        raise ValueError(f"unknown exit kind {kind!r}")
    ex = walk_exit(cost_model, recs, spec["entry_pos"], spec["end"],
                   _fill_dict(t), stop, target, sig, cfg.intrabar_rule,
                   kw["max_holding"], use_signal=kw["use_signal"],
                   trail_atr_mult=kw["trail"], entry_atr=atr)
    rec = build_trade_record(spec["sym"], _entry_dict(t), ex, {
        "market_regime": t.get("market_regime"), "sector": t.get("sector")})
    return rec


# ── Metric row shared by every comparison-table entry ────────────────────────

def _row_metrics(trades: list[dict], total_test_days: int, vm) -> dict:
    m = _metrics(trades)
    costs = round(sum(_f(t.get("total_costs")) for t in trades), 2)
    sharpe = None
    if trades:
        vmm = vm.compute_performance_metrics(
            sorted(trades, key=lambda t: (str(t.get("exit_date") or ""),
                                          t.get("symbol", ""))),
            AUDIT_NOTIONAL, _cum_equity(trades),
            trading_days=max(total_test_days, 1))
        sharpe = vmm.get("sharpe_ratio")
    return {
        "trades": m["trades"],
        "net_return_pct": m["net_return_pct"],
        "expectancy_pct": m["expectancy_pct"],
        "profit_factor": m["profit_factor"],
        "win_rate": m["win_rate"],
        "sharpe_ratio": sharpe,
        "max_drawdown_pct": m["max_drawdown_pct"],
        "total_costs": costs,
        "avg_holding_days": m["avg_holding_days"],
    }


def _trade_level_verdict(row: dict, base: dict) -> tuple[str, str]:
    """ACCEPT only when the unseen-test expectancy improves by a real margin
    without destroying the profit factor. Everything else is preserved as a
    rejection with the exact reason."""
    n = row["trades"]
    if n < MIN_TEST_SAMPLE:
        return VERDICT_INSUFFICIENT, (
            f"Only {n} out-of-sample trades (need ≥{MIN_TEST_SAMPLE}) — too "
            f"few to accept without overfitting risk.")
    exp, bexp = row["expectancy_pct"] or 0.0, base["expectancy_pct"] or 0.0
    pf, bpf = row["profit_factor"] or 0.0, base["profit_factor"] or 0.0
    if exp <= 0:
        return VERDICT_REJECTED, (
            f"Out-of-sample expectancy is not positive ({exp:+.3f}%/trade).")
    if exp - bexp < ACCEPT_MARGIN_PCT:
        return VERDICT_REJECTED, (
            f"Expectancy {exp:+.3f}%/trade does not beat baseline "
            f"{bexp:+.3f}% by the required +{ACCEPT_MARGIN_PCT}%/trade margin.")
    if pf < bpf - 0.05:
        return VERDICT_REJECTED, (
            f"Profit factor {pf} is worse than baseline {bpf}.")
    return VERDICT_ACCEPTED, (
        f"Expectancy improves {bexp:+.3f}% → {exp:+.3f}%/trade over {n} "
        f"unseen test trades with profit factor {pf} (baseline {bpf}).")


# ── Portfolio replay with risk-management hooks (MACD only) ──────────────────

def simulate_macd_portfolio(sym_recs: dict[str, list[dict]],
                            span_pos: dict[str, tuple[int, int]],
                            test_dates: list[str],
                            regime_by_date: dict[str, str],
                            cost_model: CostModel, cfg, risk: dict,
                            entry_pred=None, exit_over: dict | None = None) -> dict:
    """Sequential portfolio replay of MACD Cross over one test window.
    Signals fire at the close and fill at the next day's open — identical
    timing to the main validator. `risk` toggles the Phase 3 risk rules;
    `entry_pred(snapshot) -> bool` optionally filters entries; `exit_over`
    may override stop/target/max-holding at entry time
    ({"kind": ..., "p": ...} restricted to atr_stop/atr_target/rr/time)."""
    strat = STRATEGY_REGISTRY[MACD_ID]
    date_idx: dict[str, dict[str, int]] = {}
    sig_cache: dict[str, set[str]] = {}
    for sym, recs in sym_recs.items():
        if sym not in span_pos:
            continue
        start, end = span_pos[sym]
        date_idx[sym] = {str(recs[i]["date"])[:10]: i
                         for i in range(start, end + 1)}
        sig_cache[sym] = _signal_exit_dates(strat, recs, start, end)

    cash = cfg.initial_capital
    positions: dict[str, dict] = {}
    pending: list[dict] = []
    trades: list[dict] = []
    equity_curve: list[float] = []
    peak_equity = cfg.initial_capital
    prev_equity = cfg.initial_capital
    halt_entries_today = False
    blocked_by_risk = 0

    def _mark(sym: str, d: str) -> float:
        i = date_idx.get(sym, {}).get(d)
        if i is not None:
            return _f(sym_recs[sym][i]["close"])
        pos = positions.get(sym)
        return _f(pos["last_close"]) if pos else 0.0

    def _equity(d: str) -> float:
        return cash + sum(p["quantity"] * _mark(s, d)
                          for s, p in positions.items())

    def _close(sym: str, pos: dict, day: str, raw_exit: float, reason: str):
        nonlocal cash
        sell_price = effective_sell_price(cost_model, raw_exit)
        turnover = sell_price * pos["quantity"]
        exit_info = {
            "exit_date": day, "raw_exit_price": round(raw_exit, 4),
            "sell_price": round(sell_price, 4), "exit_reason": reason,
            "holding_days": pos["holding_days"],
            "mae_pct": round(pos["mae_pct"], 2),
            "mfe_pct": round(pos["mfe_pct"], 2),
            "intrabar_rule": cfg.intrabar_rule,
            "intrabar_rule_label": INTRABAR_RULE_LABELS[cfg.intrabar_rule],
            "sell_turnover": round(turnover, 2),
            "sell_costs": side_costs(cost_model, turnover, "sell"),
        }
        entry = {"entry_date": pos["entry_date"], "raw_open": pos["raw_open"],
                 "fill_price": pos["entry_price"], "quantity": pos["quantity"],
                 "requested_quantity": pos["requested_quantity"],
                 "partial_fill": pos["partial_fill"], "gap_pct": pos["gap_pct"],
                 "buy_costs": pos["buy_costs"]}
        meta = {"strategy_id": MACD_ID, "sector": pos["sector"],
                "market_regime": pos["market_regime"]}
        trades.append(build_trade_record(sym, entry, exit_info, meta))
        cash += sell_price * pos["quantity"] - exit_info["sell_costs"]["total"]
        del positions[sym]

    for di, day in enumerate(test_dates):
        is_last = di == len(test_dates) - 1

        # 1. exits
        for sym in list(positions):
            pos = positions[sym]
            i = date_idx.get(sym, {}).get(day)
            if i is None:
                if is_last:
                    _close(sym, pos, day, pos["last_close"], EXIT_FORCED)
                continue
            c = sym_recs[sym][i]
            candle = {"open": _f(c["open"]), "high": _f(c["high"]),
                      "low": _f(c["low"]), "close": _f(c["close"])}
            pos["last_close"] = candle["close"]
            if pos["entry_price"] > 0:
                pos["mae_pct"] = min(
                    pos["mae_pct"],
                    (candle["low"] - pos["entry_price"]) / pos["entry_price"] * 100.0)
                pos["mfe_pct"] = max(
                    pos["mfe_pct"],
                    (candle["high"] - pos["entry_price"]) / pos["entry_price"] * 100.0)
            pos["holding_days"] += 1
            exited, raw_exit, reason, _b = evaluate_exit_candle(
                candle, pos["stop_loss"], pos["target"], cfg.intrabar_rule)
            if not exited:
                if day in sig_cache.get(sym, set()):
                    exited, raw_exit, reason = True, candle["close"], EXIT_SIGNAL
                elif pos["holding_days"] >= pos["max_holding"]:
                    exited, raw_exit, reason = True, candle["close"], EXIT_TIME
                elif is_last:
                    exited, raw_exit, reason = True, candle["close"], EXIT_FORCED
            if exited:
                _close(sym, pos, day, raw_exit, reason)

        # 2. queued entries fill at today's open
        if not is_last:
            for rec in pending:
                sym = rec["sym"]
                if sym in positions or len(positions) >= risk["max_open"]:
                    continue
                if risk["sector_cap"] is not None and sum(
                        1 for p in positions.values()
                        if p["sector"] == rec["sector"]) >= risk["sector_cap"]:
                    blocked_by_risk += 1
                    continue
                i = date_idx.get(sym, {}).get(day)
                if i is None:
                    continue
                c = sym_recs[sym][i]
                candle = {"date": day, "open": _f(c["open"]),
                          "high": _f(c["high"]), "low": _f(c["low"]),
                          "close": _f(c["close"]), "volume": _f(c["volume"])}
                equity = _equity(day)
                alloc = equity * risk["alloc_pct"]
                if risk["dd_protect_pct"] is not None and \
                        equity < peak_equity * (1 - risk["dd_protect_pct"] / 100.0):
                    alloc *= 0.5
                if risk["vol_target_atr"] is not None and rec["atr_pct"] > 0:
                    scale = risk["vol_target_atr"] / rec["atr_pct"]
                    alloc *= min(max(scale, 0.5), 1.5)
                if risk["risk_per_trade_pct"] is not None:
                    dist = rec["price"] - rec["stop_loss"]
                    if dist > 0:
                        alloc = min(alloc, equity * risk["risk_per_trade_pct"]
                                    / 100.0 * rec["price"] / dist)
                if risk["max_exposure_pct"] is not None:
                    invested = equity - cash
                    room = equity * risk["max_exposure_pct"] / 100.0 - invested
                    if room < alloc:
                        blocked_by_risk += 1
                        continue
                fill = simulate_entry(cost_model, candle, rec["price"],
                                      cash, alloc)
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
                    "max_holding": rec["max_holding"],
                    "sector": rec["sector"], "market_regime": rec["regime"],
                    "holding_days": 0, "mae_pct": 0.0, "mfe_pct": 0.0,
                    "last_close": candle["close"],
                }
        pending = []

        # 3. new signals at today's close (fill tomorrow)
        if not is_last and not halt_entries_today:
            regime = regime_by_date.get(day, "Sideways")
            candidates = []
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
                if entry_pred is not None and not entry_pred(snap):
                    continue
                try:
                    stop = float(strat.compute_stop_loss(recs[i], price))
                    target = float(strat.compute_target(price, stop))
                except Exception:
                    continue
                atr = snap["atr"] or price * 0.02
                max_holding = cfg.max_holding_days
                if exit_over is not None:
                    kind, p = exit_over["kind"], exit_over["p"]
                    if kind == "atr_stop":
                        stop = price - p * atr
                    elif kind == "atr_target":
                        target = price + p * atr
                    elif kind == "rr":
                        target = price + p * max(price - stop, 0.0)
                    elif kind == "time":
                        max_holding = int(p)
                candidates.append({
                    "sym": sym, "price": price, "stop_loss": stop,
                    "target": target, "max_holding": max_holding,
                    "sector": snap["sector"], "regime": regime,
                    "adx": snap["adx"], "atr_pct": snap["atr_pct"],
                })
            candidates.sort(key=lambda c: (-c["adx"], c["sym"]))
            slots = max(0, risk["max_open"] - len(positions))
            pending = candidates[:slots]

        # 4. mark to market + daily-loss / drawdown bookkeeping
        equity = _equity(day)
        equity_curve.append(round(equity, 2))
        peak_equity = max(peak_equity, equity)
        halt_entries_today = False
        if risk["daily_loss_limit_pct"] is not None and prev_equity > 0 and \
                equity < prev_equity * (1 - risk["daily_loss_limit_pct"] / 100.0):
            halt_entries_today = True   # applies to the NEXT trading day
        prev_equity = equity

    return {"trades": trades, "equity_curve": equity_curve,
            "blocked_by_risk": blocked_by_risk}


def _portfolio_verdict(row: dict, base: dict) -> tuple[str, str]:
    """Risk rules protect capital — accept when risk-adjusted results improve
    (better Sharpe, or materially lower drawdown without giving up most of
    the return)."""
    n = row["trades"] or 0
    if n < MIN_TEST_SAMPLE:
        return VERDICT_INSUFFICIENT, (
            f"Only {n} out-of-sample portfolio trades (need ≥{MIN_TEST_SAMPLE}).")
    sh, bsh = row["sharpe_ratio"] or 0.0, base["sharpe_ratio"] or 0.0
    dd, bdd = row["max_drawdown_pct"] or 0.0, base["max_drawdown_pct"] or 0.0
    ret, bret = row["net_return_pct"] or 0.0, base["net_return_pct"] or 0.0
    if sh > bsh + 0.05 and ret > min(bret, 0.0):
        return VERDICT_ACCEPTED, (
            f"Sharpe improves {bsh:.2f} → {sh:.2f} with net return "
            f"{ret:+.2f}% (baseline {bret:+.2f}%).")
    if bdd > 0 and dd <= bdd * 0.8 and ret >= bret - abs(bret) * 0.2 - 0.5:
        return VERDICT_ACCEPTED, (
            f"Max drawdown falls {bdd:.2f}% → {dd:.2f}% while net return "
            f"stays {ret:+.2f}% vs baseline {bret:+.2f}%.")
    return VERDICT_REJECTED, (
        f"No genuine out-of-sample improvement: Sharpe {sh:.2f} vs {bsh:.2f}, "
        f"drawdown {dd:.2f}% vs {bdd:.2f}%, net return {ret:+.2f}% vs "
        f"{bret:+.2f}%.")


# ── Main entry point ─────────────────────────────────────────────────────────

def run_macd_optimization(sym_rows: dict[str, pd.DataFrame],
                          windows: list[dict],
                          regime_by_date: dict[str, str],
                          test_dates_by_window: dict[str, list[str]],
                          cfg, cost_model: CostModel,
                          progress_cb=None) -> dict:
    """Phase 3: independently walk-forward-test entry filters, exit
    variations and risk rules for MACD Cross, then assemble the final
    recommended configuration. Pure analysis — returns a JSON-safe report."""
    import validation_metrics as vm

    strat = STRATEGY_REGISTRY[MACD_ID]
    sym_recs = {sym: rows.to_dict("records") for sym, rows in sym_rows.items()}

    def _span_pos(t0: pd.Timestamp, t1: pd.Timestamp) -> dict[str, tuple[int, int]]:
        out = {}
        for sym, rows in sym_rows.items():
            dates = rows["date"]
            idx = [i for i, d in enumerate(dates) if t0 <= d <= t1]
            if len(idx) >= 5:
                out[sym] = (idx[0], idx[-1])
        return out

    valid_windows = [w for w in windows if not w.get("failed")]
    per_window: list[dict] = []
    total_test_days = 0

    # ── Pass 1: per-window train selection + test application ──────────────
    for wi, window in enumerate(valid_windows):
        label = window.get("label", f"W{wi + 1}")
        if progress_cb:
            progress_cb(f"Phase 3 MACD optimization — window {label}")
        train_span = _span_pos(pd.Timestamp(window["train_start"]),
                               pd.Timestamp(window["train_end"]))
        test_span = _span_pos(pd.Timestamp(window["test_start"]),
                              pd.Timestamp(window["test_end"]))
        test_dates = test_dates_by_window.get(label, [])
        total_test_days += len(test_dates)

        train_out = audit_window_pass(strat, sym_recs, train_span,
                                      regime_by_date, cost_model, cfg, label,
                                      collect_alternatives=False)
        test_out = audit_window_pass(strat, sym_recs, test_span,
                                     regime_by_date, cost_model, cfg, label,
                                     collect_alternatives=False)
        train_trades = train_out["baseline"]
        test_trades = test_out["baseline"]

        w = {"label": label, "test_span": test_span, "test_dates": test_dates,
             "test_trades": test_trades, "filter_sel": {}, "exit_sel": {},
             "regime_allowed": None}

        # Entry filters — pick the TRAIN-best candidate per filter
        for fd in ENTRY_FILTER_DEFS:
            best_p, best_val = None, None
            for p in fd["candidates"]:
                sub = [_f(t["return_pct"]) for t in train_trades
                       if fd["pred"](t["snapshot"], p)]
                if len(sub) < MIN_VARIANT_TRAIN_TRADES:
                    continue
                val = _shrunk_mean(sub)
                if best_val is None or val > best_val:
                    best_p, best_val = p, val
            w["filter_sel"][fd["id"]] = {
                "param": best_p,
                "train_shrunk_expectancy_pct":
                    round(best_val, 3) if best_val is not None else None}

        # Regime gate — allowed regimes from TRAIN trades only
        by_regime: dict[str, list[float]] = {}
        for t in train_trades:
            by_regime.setdefault(t.get("market_regime", "Sideways"), []).append(
                _f(t["return_pct"]))
        allowed = sorted(r for r, v in by_regime.items()
                         if len(v) >= MIN_REGIME_SAMPLE and _shrunk_mean(v) > 0)
        w["regime_allowed"] = allowed

        # Exit variations — pick the TRAIN-best candidate per variation
        for xd in EXIT_TEST_DEFS:
            best_p, best_val = None, None
            for p in xd["candidates"]:
                rets = []
                for t in train_trades:
                    if t["_spec"]["sym"] not in sym_recs:
                        continue
                    rets.append(_f(rewalk_exit(t, sym_recs, cost_model, cfg,
                                               xd["kind"], p)["return_pct"]))
                if len(rets) < MIN_VARIANT_TRAIN_TRADES:
                    continue
                val = _shrunk_mean(rets)
                if best_val is None or val > best_val:
                    best_p, best_val = p, val
            w["exit_sel"][xd["id"]] = {
                "param": best_p,
                "train_shrunk_expectancy_pct":
                    round(best_val, 3) if best_val is not None else None}

        per_window.append(w)

    baseline_trades = [t for w in per_window for t in w["test_trades"]]
    base_row = _row_metrics(baseline_trades, total_test_days, vm)

    # ── Pass 2: aggregate each enhancement across unseen test windows ──────
    comparison: list[dict] = []

    def _params_by_window(sel_key: str, enh_id: str) -> list[dict]:
        return [{"window": w["label"],
                 "param": w[sel_key][enh_id]["param"],
                 "train_shrunk_expectancy_pct":
                     w[sel_key][enh_id]["train_shrunk_expectancy_pct"]}
                for w in per_window]

    filter_trades: dict[str, list[dict]] = {}
    for fd in ENTRY_FILTER_DEFS:
        agg: list[dict] = []
        for w in per_window:
            sel = w["filter_sel"][fd["id"]]["param"]
            if sel is None:      # no reliable train selection — pass through
                agg.extend(w["test_trades"])
            else:
                agg.extend(t for t in w["test_trades"]
                           if fd["pred"](t["snapshot"], sel))
        filter_trades[fd["id"]] = agg
        row = _row_metrics(agg, total_test_days, vm)
        verdict, reason = _trade_level_verdict(row, base_row)
        comparison.append({
            "id": fd["id"], "category": "entry_filter", "name": fd["name"],
            "description": fd["description"],
            "params_by_window": _params_by_window("filter_sel", fd["id"]),
            "param_format": fd["fmt"],
            **row,
            "vs_baseline_expectancy_diff": round(
                (row["expectancy_pct"] or 0) - (base_row["expectancy_pct"] or 0), 3),
            "verdict": verdict, "reason": reason,
        })

    # Regime gate
    agg = []
    for w in per_window:
        allowed = w["regime_allowed"]
        if not allowed:          # nothing eligible on train — pass through
            agg.extend(w["test_trades"])
        else:
            agg.extend(t for t in w["test_trades"]
                       if t.get("market_regime") in allowed)
    filter_trades[REGIME_GATE_ID] = agg
    row = _row_metrics(agg, total_test_days, vm)
    verdict, reason = _trade_level_verdict(row, base_row)
    comparison.append({
        "id": REGIME_GATE_ID, "category": "entry_filter",
        "name": "Market regime filter",
        "description": "Trade only in regimes where MACD Cross showed a "
                       "positive training-window edge (re-learned each window).",
        "params_by_window": [
            {"window": w["label"],
             "param": ", ".join(w["regime_allowed"]) or "none eligible",
             "train_shrunk_expectancy_pct": None} for w in per_window],
        "param_format": "Allowed regimes: {p}",
        **row,
        "vs_baseline_expectancy_diff": round(
            (row["expectancy_pct"] or 0) - (base_row["expectancy_pct"] or 0), 3),
        "verdict": verdict, "reason": reason,
    })

    # Exit variations
    exit_trades: dict[str, list[dict]] = {}
    for xd in EXIT_TEST_DEFS:
        agg = []
        for w in per_window:
            sel = w["exit_sel"][xd["id"]]["param"]
            if sel is None:
                agg.extend(w["test_trades"])
                continue
            for t in w["test_trades"]:
                if t["_spec"]["sym"] not in sym_recs:
                    continue
                agg.append(rewalk_exit(t, sym_recs, cost_model, cfg,
                                       xd["kind"], sel))
        exit_trades[xd["id"]] = agg
        row = _row_metrics(agg, total_test_days, vm)
        verdict, reason = _trade_level_verdict(row, base_row)
        comparison.append({
            "id": xd["id"], "category": "exit", "name": xd["name"],
            "description": xd["description"],
            "params_by_window": _params_by_window("exit_sel", xd["id"]),
            "param_format": xd["fmt"],
            **row,
            "vs_baseline_expectancy_diff": round(
                (row["expectancy_pct"] or 0) - (base_row["expectancy_pct"] or 0), 3),
            "verdict": verdict, "reason": reason,
        })

    # ── Pass 3: portfolio-level risk-management variants ────────────────────
    if progress_cb:
        progress_cb("Phase 3 MACD optimization — risk-management replays")

    def _run_portfolio(risk: dict, entry_preds=None, exit_over=None) -> dict:
        trades_all: list[dict] = []
        chain: list[float] = []
        factor = 1.0
        blocked = 0
        for w in per_window:
            pred = entry_preds.get(w["label"]) if entry_preds else None
            out = simulate_macd_portfolio(
                sym_recs, w["test_span"], w["test_dates"], regime_by_date,
                cost_model, cfg, risk, entry_pred=pred,
                exit_over=(exit_over or {}).get(w["label"])
                if isinstance(exit_over, dict) else exit_over)
            for t in out["trades"]:
                t["window"] = w["label"]
            trades_all.extend(out["trades"])
            base = cfg.initial_capital
            for v in out["equity_curve"]:
                chain.append(round(factor * v, 2))
            if out["equity_curve"]:
                factor *= out["equity_curve"][-1] / base
            blocked += out["blocked_by_risk"]
        m = vm.compute_performance_metrics(
            sorted(trades_all, key=lambda t: (str(t["exit_date"]), t["symbol"])),
            cfg.initial_capital, chain or [cfg.initial_capital],
            trading_days=max(total_test_days, 1))
        return {"trades": m["total_trades"],
                "net_return_pct": m["total_return_pct"],
                "expectancy_pct": round(
                    sum(_f(t["return_pct"]) for t in trades_all)
                    / len(trades_all), 3) if trades_all else None,
                "profit_factor": m["profit_factor"],
                "win_rate": m["win_rate"],
                "sharpe_ratio": m["sharpe_ratio"],
                "max_drawdown_pct": m["max_drawdown_pct"],
                "total_costs": m["total_costs"],
                "avg_holding_days": None,
                "blocked_by_risk": blocked}

    portfolio_base = _run_portfolio(dict(BASE_RISK))
    risk_rows: list[dict] = []
    for rd in RISK_VARIANT_DEFS:
        risk = dict(BASE_RISK)
        risk.update(rd["over"])
        row = _run_portfolio(risk)
        verdict, reason = _portfolio_verdict(row, portfolio_base)
        risk_rows.append({
            "id": rd["id"], "category": "risk_management",
            "name": rd["name"], "description": rd["description"],
            "params_by_window": [], "param_format": "",
            **row,
            "vs_baseline_expectancy_diff": None,
            "verdict": verdict, "reason": reason,
        })
    comparison.extend(risk_rows)

    # ── Pass 4: final recommended configuration ─────────────────────────────
    accepted = [r for r in comparison if r["verdict"] == VERDICT_ACCEPTED]
    accepted_filters = [r for r in accepted if r["category"] == "entry_filter"]
    accepted_exits = [r for r in accepted if r["category"] == "exit"]
    accepted_risk = [r for r in accepted if r["category"] == "risk_management"]
    best_exit = max(accepted_exits,
                    key=lambda r: r["expectancy_pct"] or -99.0) \
        if accepted_exits else None

    fd_by_id = {fd["id"]: fd for fd in ENTRY_FILTER_DEFS}
    xd_by_id = {xd["id"]: xd for xd in EXIT_TEST_DEFS}

    def _stacked_pred(w: dict):
        """AND of every accepted entry filter, using THIS window's
        train-selected parameters. Filters without a selection this window
        are skipped (no data to justify them)."""
        parts = []
        for r in accepted_filters:
            if r["id"] == REGIME_GATE_ID:
                allowed = w["regime_allowed"]
                if allowed:
                    parts.append(lambda s, a=set(allowed): s["regime"] in a)
                continue
            sel = w["filter_sel"][r["id"]]["param"]
            if sel is not None:
                parts.append(lambda s, fd=fd_by_id[r["id"]], p=sel: fd["pred"](s, p))
        if not parts:
            return None
        return lambda s: all(fn(s) for fn in parts)

    combined_trades: list[dict] = []
    for w in per_window:
        pred = _stacked_pred(w)
        subset = [t for t in w["test_trades"]
                  if pred is None or pred(t["snapshot"])]
        if best_exit is not None:
            sel = w["exit_sel"][best_exit["id"]]["param"]
            if sel is not None:
                subset = [rewalk_exit(t, sym_recs, cost_model, cfg,
                                      xd_by_id[best_exit["id"]]["kind"], sel)
                          for t in subset if t["_spec"]["sym"] in sym_recs]
        combined_trades.extend(subset)
    combined_row = _row_metrics(combined_trades, total_test_days, vm)

    # Combined portfolio: accepted risk rules + stacked filters (+ exit
    # override when it is representable as entry-time stop/target/holding).
    combined_risk = dict(BASE_RISK)
    for r in accepted_risk:
        rd = next(d for d in RISK_VARIANT_DEFS if d["id"] == r["id"])
        combined_risk.update(rd["over"])
    entry_preds = {w["label"]: _stacked_pred(w) for w in per_window}
    exit_over_by_window = None
    exit_note = ""
    if best_exit is not None:
        kind = xd_by_id[best_exit["id"]]["kind"]
        if kind in ("atr_stop", "atr_target", "rr", "time"):
            exit_over_by_window = {
                w["label"]: ({"kind": kind,
                              "p": w["exit_sel"][best_exit["id"]]["param"]}
                             if w["exit_sel"][best_exit["id"]]["param"]
                             is not None else None)
                for w in per_window}
        else:
            exit_note = (f"The accepted exit '{best_exit['name']}' needs "
                         "bar-by-bar management and is evaluated at trade "
                         "level only; the portfolio replay keeps the "
                         "standard exits.")
    combined_portfolio = _run_portfolio(combined_risk, entry_preds,
                                        exit_over_by_window)

    combined_improves = (
        (combined_row["trades"] or 0) >= MIN_TEST_SAMPLE
        and (combined_row["expectancy_pct"] or 0)
        > (base_row["expectancy_pct"] or 0) + ACCEPT_MARGIN_PCT
        and (combined_portfolio["net_return_pct"] or 0)
        >= (portfolio_base["net_return_pct"] or 0))

    def _mode_param(sel_key: str, enh_id: str):
        vals = [w[sel_key][enh_id]["param"] for w in per_window
                if w[sel_key][enh_id]["param"] is not None]
        if not vals:
            return None
        return max(set(vals), key=vals.count)

    def _rule_text(fmt: str, param) -> str:
        """Render a '{p:g}'-style rule template with the typical parameter;
        leave templates without a numeric param untouched."""
        if isinstance(param, (int, float)):
            try:
                return fmt.format(p=param)
            except (KeyError, ValueError, IndexError):
                return fmt
        return fmt

    recommended_config = {
        "strategy": "MACD Cross (unchanged entry signal: MACD crosses above "
                    "signal line, RSI < 65)",
        "entry_filters": [
            {"id": r["id"], "name": r["name"],
             "typical_param": ("per-window regimes"
                               if r["id"] == REGIME_GATE_ID
                               else _mode_param("filter_sel", r["id"])),
             "rule": _rule_text(
                 r["param_format"],
                 None if r["id"] == REGIME_GATE_ID
                 else _mode_param("filter_sel", r["id"]))}
            for r in accepted_filters],
        "exit": ({"id": best_exit["id"], "name": best_exit["name"],
                  "typical_param": _mode_param("exit_sel", best_exit["id"]),
                  "rule": _rule_text(best_exit["param_format"],
                                     _mode_param("exit_sel", best_exit["id"]))}
                 if best_exit else
                 {"id": "baseline", "name": "Existing exit logic",
                  "typical_param": None,
                  "rule": "Stop entry−2×ATR, target 2.5× risk, MACD bearish "
                          "cross signal exit, 20-day time cap"}),
        "risk_rules": [{"id": r["id"], "name": r["name"],
                        "rule": r["description"]} for r in accepted_risk],
        "parameters_note": ("Parameters are re-selected on each window's "
                            "TRAINING data; 'typical_param' shows the most "
                            "frequently selected value across windows."),
        "status": ("PROVISIONALLY RECOMMENDED for continued paper validation "
                   "— the combined configuration beat the baseline on the "
                   "unseen test windows, but those are the same windows used "
                   "to accept its components, so treat this as exploratory "
                   "until it is confirmed on fresh paper-trading data."
                   if combined_improves else
                   "NOT RECOMMENDED YET — keep the unmodified baseline MACD "
                   "Cross (requirement: never adopt a change that does not "
                   "consistently beat the baseline out-of-sample)."),
        "adopted": bool(combined_improves),
        "validation_caveat": COMBINED_CAVEAT,
    }

    rejected = [{"id": r["id"], "name": r["name"], "category": r["category"],
                 "verdict": r["verdict"], "reason": r["reason"]}
                for r in comparison if r["verdict"] != VERDICT_ACCEPTED]

    report = {
        "baseline_summary": (
            f"Baseline MACD Cross took {base_row['trades']} out-of-sample "
            f"trades: expectancy {base_row['expectancy_pct'] or 0:+.3f}%/trade, "
            f"profit factor {base_row['profit_factor']}, win rate "
            f"{base_row['win_rate']}%, max drawdown "
            f"{base_row['max_drawdown_pct']}% (per-trade basis) and "
            f"₹{base_row['total_costs']:,.0f} transaction costs at a fixed "
            f"₹{AUDIT_NOTIONAL:,.0f} notional."),
        "tested": len(comparison),
        "accepted": [{"id": r["id"], "name": r["name"],
                      "category": r["category"], "reason": r["reason"]}
                     for r in accepted],
        "rejected": rejected,
        "combined_vs_baseline": (
            f"Combined configuration: expectancy "
            f"{combined_row['expectancy_pct'] or 0:+.3f}%/trade over "
            f"{combined_row['trades']} trades vs baseline "
            f"{base_row['expectancy_pct'] or 0:+.3f}%; portfolio net return "
            f"{combined_portfolio['net_return_pct'] or 0:+.2f}% vs baseline "
            f"{portfolio_base['net_return_pct'] or 0:+.2f}%."),
        "final_recommendation": recommended_config["status"],
        "exit_note": exit_note,
    }

    return {
        "strategy_id": MACD_ID,
        "strategy_name": strat.name,
        "safety": SAFETY_MESSAGE,
        "methodology": (
            "Every enhancement was tested INDEPENDENTLY on MACD Cross only. "
            "Entry filters and exit parameters were selected on each window's "
            "TRAINING data and then applied unchanged to the unseen TEST "
            "window; risk rules are fixed (untuned) portfolio-level policies "
            "replayed over the test windows. Entry filters only remove "
            f"baseline entries. Trade-level tables use a fixed "
            f"₹{AUDIT_NOTIONAL:,.0f} notional per trade; portfolio tables "
            f"start each window at ₹{cfg.initial_capital:,.0f} and chain "
            "across windows. Rejected enhancements are preserved with "
            "reasons."),
        "windows_evaluated": len(valid_windows),
        "notional_per_trade": AUDIT_NOTIONAL,
        "baseline": {"trade_level": base_row, "portfolio": portfolio_base},
        "comparison_table": comparison,
        "combined": {"trade_level": combined_row,
                     "portfolio": combined_portfolio,
                     "improves_baseline": bool(combined_improves),
                     "validation_caveat": COMBINED_CAVEAT},
        "recommended_config": recommended_config,
        "report": report,
    }
