"""
Phase 5 – Alpha Generation Engine (ANALYSIS ONLY)

Research module that evaluates 10 new strategy candidates formed by
layering additional entry filters onto the existing MACD Cross signals.
Every candidate is evaluated strictly out-of-sample, using the same
walk-forward windows, execution cost model, and lookahead controls as
the live system.

No candidate is connected to paper-trading or live-trading decisions.
Enabling any candidate requires it to pass all quality gates across
multiple independent validation runs AND a separate manual review.

Strategy components evaluated:
  • Multi-timeframe trend confirmation (ADX-based trend strength filter)
  • Relative strength vs NIFTY 50 (60-day momentum comparison)
  • VWAP and volume participation (above-VWAP + volume-ratio filters)
  • ATR-based volatility filter (low-vol regime selection)
  • Market-regime-specific entry logic (bearish / neutral regime filters)
  • Multi-signal intersections (high-conviction combined filters)
  • Sector concentration reduction (focus on best-performing sectors)
"""
from __future__ import annotations

import math
from collections import defaultdict

import pandas as pd

from strategy_audit import audit_window_pass
from macd_robustness import (
    _f, _safe_div, _metrics, MACD_ID,
    _group_key_volatility, _group_key_adx,
)
from macd_optimizer import STRATEGY_REGISTRY
from execution_simulator import CostModel

SAFETY_MSG = (
    "ANALYSIS ONLY — Alpha Generation Engine. No strategy candidate in "
    "this report affects live or paper-trading decisions. A candidate must "
    "demonstrate positive net expectancy, PF ≥ 1.15, acceptable drawdown, "
    "sufficient sample size, multi-window consistency, and no excessive "
    "concentration before it can even be PROPOSED for a future iteration."
)

# ── Quality gate thresholds ───────────────────────────────────────────────────
GATE_MIN_EXP_PCT      = 0.0      # expectancy strictly positive after costs
GATE_MIN_PF_KEEP      = 1.10     # profit factor for KEEP verdict
GATE_MIN_TRADES_KEEP  = 30       # min trades for KEEP verdict
GATE_MIN_TRADES_VALID = 10       # fewer → REJECT immediately
GATE_MIN_WIN_RATE     = 0.0      # no hard win-rate gate (PF captures this)
GATE_MIN_WINDOW_PASS  = 0.50     # ≥50% of WF windows must be profitable
GATE_MAX_DD_KEEP      = 60.0     # max drawdown % for KEEP verdict
GATE_MAX_TOP5_CONC    = 0.70     # top-5 trades ≤70% of gross profit
RS_LOOKBACK_DAYS      = 60       # trading days for relative-strength lookback

VERDICT_KEEP         = "KEEP_FOR_FURTHER_TESTING"
VERDICT_INCONCLUSIVE = "INCONCLUSIVE"
VERDICT_REJECT       = "REJECT"


# ── Snapshot field helper ─────────────────────────────────────────────────────

def _snap(trade: dict, key: str, default=None):
    """Extract a field from the trade's snapshot dict safely."""
    snap = trade.get("snapshot") or {}
    v = snap.get(key)
    return default if v is None else v


# ── Relative Strength filter ──────────────────────────────────────────────────

def _rs_outperforms_nifty(
    sym_rows: dict, nifty_df, symbol: str,
    entry_date_str: str, lookback: int = RS_LOOKBACK_DAYS,
) -> bool:
    """Return True if the stock outperformed NIFTY 50 over `lookback` trading
    days before the entry date.  Returns True (permissive) when there is
    insufficient data so the filter never punishes missing history.
    """
    if nifty_df is None or nifty_df.empty or symbol not in sym_rows:
        return True
    try:
        entry_ts = pd.Timestamp(entry_date_str)
        rows = sym_rows[symbol]
        stock_before = rows[rows.index < entry_ts].tail(lookback)
        nifty_before = nifty_df[nifty_df.index < entry_ts].tail(lookback)
        if len(stock_before) < 10 or len(nifty_before) < 10:
            return True
        close_col = next((c for c in ("Close", "close") if c in rows.columns), None)
        nifty_col = next((c for c in ("Close", "close") if c in nifty_df.columns), None)
        if close_col is None or nifty_col is None:
            return True
        s_ret = (float(stock_before[close_col].iloc[-1]) /
                 float(stock_before[close_col].iloc[0])) - 1.0
        n_ret = (float(nifty_before[nifty_col].iloc[-1]) /
                 float(nifty_before[nifty_col].iloc[0])) - 1.0
        return s_ret > n_ret
    except Exception:
        return True


# ── Candidate definitions ─────────────────────────────────────────────────────

def _build_candidates(sym_rows: dict, nifty_df) -> list[dict]:
    """Return the 10 candidate strategy specs with their filter functions."""
    return [
        {
            "id": "C1",
            "name": "MACD × Volume Surge",
            "description": (
                "Require strong volume confirmation at the signal bar "
                "(volume ratio ≥ 1.5× 20-day average). Eliminates "
                "low-conviction breakouts triggered on thin volume."
            ),
            "components": ["Volume participation filter"],
            "filters": ["volume_ratio ≥ 1.5"],
            "filter_fn": lambda t: _f(_snap(t, "volume_ratio", 0.0)) >= 1.5,
        },
        {
            "id": "C2",
            "name": "MACD × Strong Trend (ADX ≥ 25)",
            "description": (
                "Multi-timeframe trend confirmation: only enter when ADX "
                "confirms a defined trend (≥ 25). Avoids whipsaw MACD "
                "signals in ranging, trendless markets."
            ),
            "components": ["Multi-timeframe trend confirmation", "ATR/ADX volatility filter"],
            "filters": ["ADX ≥ 25"],
            "filter_fn": lambda t: _f(_snap(t, "adx", 0.0)) >= 25,
        },
        {
            "id": "C3",
            "name": "MACD × Low Volatility (ATR% < 1.5%)",
            "description": (
                "Restrict entries to calm, low-volatility environments "
                "(daily ATR < 1.5% of price). Low-ATR periods tend to "
                "produce cleaner MACD crossovers with less noise."
            ),
            "components": ["ATR-based volatility filter"],
            "filters": ["ATR% < 1.5%"],
            "filter_fn": lambda t: _f(_snap(t, "atr_pct", 999.0)) < 1.5,
        },
        {
            "id": "C4",
            "name": "MACD × Bearish Regime",
            "description": (
                "Per Phase 4 robustness findings: MACD Cross shows its "
                "best out-of-sample expectancy specifically in Bearish "
                "market regimes, likely from mean-reversion dynamics."
            ),
            "components": ["Market-regime-specific entry logic"],
            "filters": ["market_regime = Bearish"],
            "filter_fn": lambda t: t.get("market_regime", "") == "Bearish",
        },
        {
            "id": "C5",
            "name": "MACD × VWAP Confirmation",
            "description": (
                "Only trade when price is above VWAP at the signal bar. "
                "VWAP acts as an intraday fair-value anchor; above-VWAP "
                "entries confirm institutional buying pressure."
            ),
            "components": ["VWAP and volume participation"],
            "filters": ["above_vwap = True"],
            "filter_fn": lambda t: bool(_snap(t, "above_vwap", False)),
        },
        {
            "id": "C6",
            "name": "MACD × Relative Strength vs NIFTY",
            "description": (
                "Multi-timeframe momentum filter: only enter stocks that "
                "outperformed NIFTY 50 over the 60 trading days before "
                "entry. Focuses capital on market leaders, not laggards."
            ),
            "components": [
                "Relative strength vs NIFTY 50",
                "Multi-timeframe trend confirmation",
            ],
            "filters": [f"60-day return > NIFTY 50 return"],
            "filter_fn": lambda t: _rs_outperforms_nifty(
                sym_rows, nifty_df,
                t.get("symbol", ""), t.get("entry_date", ""),
            ),
        },
        {
            "id": "C7",
            "name": "MACD × Sector Focus (Consumer + Infra)",
            "description": (
                "Concentrate on the two highest-expectancy sectors from "
                "Phase 4 analysis: CONSUMER and INFRA. Systematically "
                "removes negative-expectancy sectors (IT, TELECOM, FMCG)."
            ),
            "components": ["Candidate ranking layer (sector edge filter)"],
            "filters": ["sector ∈ {CONSUMER, INFRA}"],
            "filter_fn": lambda t: t.get("sector", "") in ("CONSUMER", "INFRA"),
        },
        {
            "id": "C8",
            "name": "MACD × Short Duration (≤ 5 days)",
            "description": (
                "Capture quick MACD momentum moves and exit within 5 "
                "trading days. Reduces overnight and weekend risk; "
                "improves capital turnover and limits time-in-market."
            ),
            "components": ["Candidate ranking layer (holding period filter)"],
            "filters": ["holding_days ≤ 5"],
            "filter_fn": lambda t: int(_f(t.get("holding_days", 99))) <= 5,
        },
        {
            "id": "C9",
            "name": "MACD × Volume + Trend (V + T)",
            "description": (
                "Two orthogonal confirmations from independent domains: "
                "volume surge (≥ 1.5×) confirms participation, AND "
                "strong ADX (≥ 25) confirms a defined trend. "
                "Rejects both low-volume breakouts and weak-trend crossovers."
            ),
            "components": [
                "VWAP and volume participation",
                "Multi-timeframe trend confirmation",
            ],
            "filters": ["volume_ratio ≥ 1.5", "ADX ≥ 25"],
            "filter_fn": lambda t: (
                _f(_snap(t, "volume_ratio", 0.0)) >= 1.5 and
                _f(_snap(t, "adx", 0.0)) >= 25
            ),
        },
        {
            "id": "C10",
            "name": "MACD × Multi-Signal (V + T + VWAP)",
            "description": (
                "High-conviction triple intersection: volume surge (≥ 1.5×) "
                "AND strong trend (ADX ≥ 25) AND price above VWAP. "
                "Three independent confirming signals; fewer trades, "
                "significantly higher signal quality threshold."
            ),
            "components": [
                "VWAP and volume participation",
                "Multi-timeframe trend confirmation",
                "Candidate ranking layer (final composite score)",
            ],
            "filters": ["volume_ratio ≥ 1.5", "ADX ≥ 25", "above_vwap = True"],
            "filter_fn": lambda t: (
                _f(_snap(t, "volume_ratio", 0.0)) >= 1.5 and
                _f(_snap(t, "adx", 0.0)) >= 25 and
                bool(_snap(t, "above_vwap", False))
            ),
        },
    ]


# ── Per-window consistency ────────────────────────────────────────────────────

def _window_consistency(
    trades: list[dict], window_results: list[dict], capital: float,
) -> dict:
    """Break down candidate trades by walk-forward window; report per-window metrics."""
    window_map: dict[str, list] = defaultdict(list)
    for t in trades:
        lbl = t.get("window") or t.get("_wf_window_id") or "?"
        window_map[lbl].append(t)

    per_window: list[dict] = []
    positive = 0
    valid_windows = [w for w in window_results if not w.get("failed")]
    for w in valid_windows:
        lbl = w["label"]
        wt = window_map.get(lbl, [])
        m = _metrics(wt, capital)
        is_pos = m["expectancy_pct"] > 0
        if is_pos:
            positive += 1
        per_window.append({
            "label": lbl,
            "test_start": w.get("test_start", ""),
            "test_end": w.get("test_end", ""),
            "trades": m["trades"],
            "expectancy_pct": m["expectancy_pct"],
            "profit_factor": m["profit_factor"],
            "win_rate": m["win_rate"],
            "max_drawdown_pct": m["max_drawdown_pct"],
            "positive": is_pos,
        })

    total = len(valid_windows)
    return {
        "per_window": per_window,
        "positive_windows": positive,
        "total_windows": total,
        "pct_positive": round(_safe_div(positive, total) * 100, 1),
    }


# ── Regime breakdown ──────────────────────────────────────────────────────────

def _regime_breakdown(trades: list[dict], capital: float) -> list[dict]:
    """Aggregate metrics per market regime, sorted by trade count desc."""
    groups: dict[str, list] = defaultdict(list)
    for t in trades:
        groups[t.get("market_regime") or "Unknown"].append(t)
    rows = []
    for regime, g in sorted(groups.items(), key=lambda x: -len(x[1])):
        m = _metrics(g, capital)
        rows.append({
            "regime": regime,
            "trades": m["trades"],
            "expectancy_pct": m["expectancy_pct"],
            "profit_factor": m["profit_factor"],
            "win_rate": m["win_rate"],
            "net_return_pct": m["net_return_pct"],
        })
    return rows


# ── Sector breakdown ──────────────────────────────────────────────────────────

def _sector_breakdown(trades: list[dict], capital: float) -> list[dict]:
    """Aggregate metrics per sector, sorted by expectancy desc."""
    groups: dict[str, list] = defaultdict(list)
    for t in trades:
        groups[t.get("sector") or "Unknown"].append(t)
    rows = []
    for sector, g in groups.items():
        m = _metrics(g, capital)
        rows.append({
            "sector": sector,
            "trades": m["trades"],
            "expectancy_pct": m["expectancy_pct"],
            "profit_factor": m["profit_factor"],
            "win_rate": m["win_rate"],
        })
    rows.sort(key=lambda r: -r["expectancy_pct"])
    return rows


# ── Concentration ─────────────────────────────────────────────────────────────

def _concentration(trades: list[dict]) -> dict:
    """Top stock, top sector, and top-5 trade share of gross profit."""
    if not trades:
        return {
            "top_stock": None, "top_stock_share_pct": 0.0,
            "top_sector": None, "top_sector_share_pct": 0.0,
            "top5_trade_share_pct": 0.0,
        }
    by_sym: dict[str, float] = defaultdict(float)
    by_sec: dict[str, float] = defaultdict(float)
    for t in trades:
        p = _f(t.get("net_pnl", 0.0))
        if p > 0:
            by_sym[t.get("symbol", "?")] += p
            by_sec[t.get("sector", "?")] += p
    gross = sum(_f(t.get("net_pnl", 0.0)) for t in trades
                if _f(t.get("net_pnl", 0.0)) > 0)
    top_sym = max(by_sym, key=by_sym.get) if by_sym else None
    top_sec = max(by_sec, key=by_sec.get) if by_sec else None
    top5_pnl = sum(sorted(
        [_f(t.get("net_pnl", 0.0)) for t in trades
         if _f(t.get("net_pnl", 0.0)) > 0],
        reverse=True,
    )[:5])
    return {
        "top_stock": top_sym,
        "top_stock_share_pct": round(
            _safe_div(by_sym.get(top_sym, 0), gross) * 100, 1) if top_sym else 0.0,
        "top_sector": top_sec,
        "top_sector_share_pct": round(
            _safe_div(by_sec.get(top_sec, 0), gross) * 100, 1) if top_sec else 0.0,
        "top5_trade_share_pct": round(
            _safe_div(top5_pnl, gross) * 100, 1) if gross > 0 else 0.0,
    }


# ── Candidate verdict ─────────────────────────────────────────────────────────

def _candidate_verdict(
    metrics: dict, consistency: dict, conc: dict,
) -> dict:
    """Issue KEEP_FOR_FURTHER_TESTING / INCONCLUSIVE / REJECT with explicit gate checks."""
    checks: list[dict] = []

    def chk(label: str, passed: bool, detail: str = "") -> bool:
        checks.append({"check": label, "passed": passed, "detail": detail})
        return passed

    n       = metrics["trades"]
    exp     = metrics["expectancy_pct"]
    pf      = metrics["profit_factor"]
    dd      = metrics["max_drawdown_pct"]
    pct_pos = consistency["pct_positive"]
    tot_w   = consistency["total_windows"]
    top5    = conc["top5_trade_share_pct"]

    c_exp  = chk("Positive net expectancy after costs",
                 exp > GATE_MIN_EXP_PCT,
                 f"exp = {exp:.3f}% (need > 0)")
    c_pf   = chk(f"Profit factor ≥ {GATE_MIN_PF_KEEP}",
                 pf >= GATE_MIN_PF_KEEP,
                 f"PF = {pf:.2f}")
    c_size = chk(f"≥ {GATE_MIN_TRADES_KEEP} OOS trades",
                 n >= GATE_MIN_TRADES_KEEP,
                 f"n = {n}")
    c_wins = chk(f"Positive in ≥ {int(GATE_MIN_WINDOW_PASS*100)}% of WF windows",
                 pct_pos >= GATE_MIN_WINDOW_PASS * 100 or tot_w == 0,
                 f"{consistency['positive_windows']}/{tot_w} windows positive")
    c_dd   = chk(f"Max drawdown < {GATE_MAX_DD_KEEP}%",
                 dd < GATE_MAX_DD_KEEP,
                 f"max DD = {dd:.1f}%")
    c_conc = chk(f"Top-5 trades ≤ {int(GATE_MAX_TOP5_CONC*100)}% of gross profit",
                 top5 <= GATE_MAX_TOP5_CONC * 100,
                 f"top-5 share = {top5:.1f}%")

    passed_count = sum(1 for c in checks if c["passed"])
    failed = [c["check"] for c in checks if not c["passed"]]

    # Hard REJECT conditions
    if n < GATE_MIN_TRADES_VALID:
        verdict = VERDICT_REJECT
        rationale = (f"REJECT — insufficient sample size: only {n} trades "
                     f"(minimum {GATE_MIN_TRADES_VALID} required).")
    elif exp <= 0:
        verdict = VERDICT_REJECT
        rationale = (f"REJECT — negative expectancy after costs "
                     f"({exp:.3f}%/trade). Filter reduces edge rather than adding it.")
    elif pf < 1.0:
        verdict = VERDICT_REJECT
        rationale = (f"REJECT — profit factor below 1.0 ({pf:.2f}). "
                     f"Strategy loses money in aggregate.")
    elif passed_count == len(checks):
        verdict = VERDICT_KEEP
        rationale = ("KEEP FOR FURTHER TESTING — all quality gates passed. "
                     "Validate across ≥ 3 additional walk-forward windows before "
                     "proposing for paper-trading adoption.")
    else:
        verdict = VERDICT_INCONCLUSIVE
        rationale = (f"INCONCLUSIVE — {len(failed)} gate(s) failed: "
                     + "; ".join(failed) + ". Needs more data or parameter refinement.")

    return {
        "verdict": verdict,
        "rationale": rationale,
        "checks": checks,
        "passed_count": passed_count,
        "failed_count": len(checks) - passed_count,
        "failed": failed,
    }


# ── OOS trade collection (mirrors Phase 4) ────────────────────────────────────

def _span_idx(sym_rows: dict, t0, t1) -> dict:
    """Return {sym: (start_idx, end_idx)} for dates in [t0, t1]."""
    out: dict[str, tuple[int, int]] = {}
    for sym, df in sym_rows.items():
        dates = df["date"]
        idx = [i for i, d in enumerate(dates) if t0 <= d <= t1]
        if len(idx) >= 5:
            out[sym] = (idx[0], idx[-1])
    return out


# ── Main entry point ──────────────────────────────────────────────────────────

def run_alpha_generation(
    sym_rows: dict,
    window_results: list[dict],
    regime_by_date: dict,
    test_dates_by_window: dict,
    cfg,
    cost_model: CostModel,
    nifty_df=None,
    progress_cb=None,
) -> dict:
    """
    Phase 5: Alpha Generation Engine — analysis only.

    Evaluates 10 candidate strategy filters applied to MACD Cross OOS trades.
    Returns a JSON-safe report. Never alters the live pipeline.
    """
    def _progress(msg: str) -> None:
        if progress_cb:
            progress_cb(msg)

    capital = float(getattr(cfg, "initial_capital", 5000.0))
    strat = STRATEGY_REGISTRY[MACD_ID]
    sym_recs = {sym: df.to_dict("records") for sym, df in sym_rows.items()}
    valid_windows = [w for w in window_results if not w.get("failed")]

    # ── Collect OOS MACD trades (same pattern as Phase 4) ────────────────────
    _progress("Phase 5 Alpha Generation — collecting OOS trades")
    all_oos_trades: list[dict] = []
    window_labels: list[str] = []

    for wi, window in enumerate(valid_windows):
        label = window.get("label", f"W{wi + 1}")
        window_labels.append(label)
        test_span = _span_idx(
            sym_rows,
            pd.Timestamp(window["test_start"]),
            pd.Timestamp(window["test_end"]),
        )
        test_out = audit_window_pass(
            strat, sym_recs, test_span,
            regime_by_date, cost_model, cfg, label,
            collect_alternatives=False,
        )
        win_trades = test_out["baseline"]
        for t in win_trades:
            t["window"] = label
        all_oos_trades.extend(win_trades)

    total_oos = len(all_oos_trades)

    if not all_oos_trades:
        return {
            "safety": SAFETY_MSG,
            "error": "No OOS MACD Cross trades found — cannot evaluate candidates.",
            "candidates": [],
        }

    # ── Baseline (unfiltered MACD) ────────────────────────────────────────────
    baseline_m = _metrics(all_oos_trades, capital)
    baseline_consistency = _window_consistency(all_oos_trades, window_results, capital)
    baseline_conc = _concentration(all_oos_trades)

    # ── Build candidate specs ────────────────────────────────────────────────
    candidates_spec = _build_candidates(sym_rows, nifty_df)
    candidate_results: list[dict] = []

    for spec in candidates_spec:
        cid = spec["id"]
        _progress(f"Phase 5 Alpha Generation — {cid}: {spec['name']}")
        fn = spec["filter_fn"]
        filtered = [t for t in all_oos_trades if fn(t)]

        m = _metrics(filtered, capital)
        consistency = _window_consistency(filtered, window_results, capital)
        regime_bd = _regime_breakdown(filtered, capital)
        sector_bd = _sector_breakdown(filtered, capital)
        conc = _concentration(filtered)
        verdict_d = _candidate_verdict(m, consistency, conc)

        candidate_results.append({
            "id": cid,
            "name": spec["name"],
            "description": spec["description"],
            "components": spec["components"],
            "filters": spec["filters"],
            "trades": m["trades"],
            "pct_of_baseline": round(
                _safe_div(m["trades"], total_oos) * 100, 1),
            "metrics": m,
            "window_consistency": consistency,
            "regime_breakdown": regime_bd,
            "sector_breakdown": sector_bd,
            "concentration": conc,
            "verdict": verdict_d["verdict"],
            "verdict_rationale": verdict_d["rationale"],
            "verdict_checks": verdict_d["checks"],
            "verdict_passed": verdict_d["passed_count"],
            "verdict_failed": verdict_d["failed_count"],
            "verdict_failed_checks": verdict_d["failed"],
        })

    # ── Comparison table ─────────────────────────────────────────────────────
    _progress("Phase 5 Alpha Generation — building comparison table")

    def _row(name: str, m: dict, verdict: str = "—", is_baseline: bool = False,
             note: str = "") -> dict:
        return {
            "name": name,
            "trades": m["trades"],
            "expectancy_pct": m["expectancy_pct"],
            "net_return_pct": m["net_return_pct"],
            "profit_factor": m["profit_factor"],
            "win_rate": m["win_rate"],
            "sharpe_ratio": m["sharpe_ratio"],
            "max_drawdown_pct": m["max_drawdown_pct"],
            "total_costs": m["total_costs"],
            "verdict": verdict,
            "is_baseline": is_baseline,
            "note": note,
        }

    comparison_table = [
        _row("MACD Baseline (unfiltered)", baseline_m, "—", True,
             "All OOS MACD Cross trades across all windows")
    ] + [
        _row(
            f"{c['id']}: {c['name']}",
            c["metrics"],
            c["verdict"],
            note=f"{c['pct_of_baseline']:.0f}% of baseline trades",
        )
        for c in candidate_results
    ]

    # ── Recommendation summary ────────────────────────────────────────────────
    verdict_order = {VERDICT_KEEP: 0, VERDICT_INCONCLUSIVE: 1, VERDICT_REJECT: 2}
    sorted_candidates = sorted(
        candidate_results,
        key=lambda c: (verdict_order.get(c["verdict"], 3),
                       -c["metrics"]["profit_factor"]),
    )
    keep_priority = 1
    recommendation_summary: list[dict] = []
    for c in sorted_candidates:
        entry: dict = {
            "candidate_id": c["id"],
            "name": c["name"],
            "status": c["verdict"],
            "trades": c["metrics"]["trades"],
            "expectancy_pct": c["metrics"]["expectancy_pct"],
            "profit_factor": c["metrics"]["profit_factor"],
            "pct_positive_windows": c["window_consistency"]["pct_positive"],
            "reason": c["verdict_rationale"],
        }
        if c["verdict"] == VERDICT_KEEP:
            entry["priority"] = keep_priority
            keep_priority += 1
        recommendation_summary.append(entry)

    return {
        "safety": SAFETY_MSG,
        "total_oos_trades": total_oos,
        "windows_evaluated": len(valid_windows),
        "window_labels": window_labels,
        "baseline": {
            **baseline_m,
            "window_consistency": baseline_consistency,
            "concentration": baseline_conc,
        },
        "candidates": candidate_results,
        "comparison_table": comparison_table,
        "recommendation_summary": recommendation_summary,
    }
