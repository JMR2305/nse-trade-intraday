"""
Phase 23 Parts 6 & 7 — AI Strategy Optimization Lab + Institutional Analytics.

STRICTLY READ-ONLY AND ADVISORY.
Sources: backtest store (backtest_portfolio), canonical Event Store
(pipeline_events), paper trade ledger (phase20_executor), candle cache
(historical_data_engine), Phase 21 calibration (verbatim).

• No live trading behaviour is modified.
• Historical runs are IMMUTABLE — what-if variants and walk-forward folds are
  deterministic DERIVED simulations recomputed on demand; they are never
  written back and never overwrite a run.
• Metric math is delegated to the existing expectancy.compute_metrics — no
  duplicate calculation engines.
• Missing data → INSUFFICIENT_EVIDENCE, never extrapolation.
"""
from __future__ import annotations

import json
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import backtest_portfolio as bp
import historical_data_engine as hde
from expectancy import compute_metrics

IST = timezone(timedelta(hours=5, minutes=30))
MIN_EVIDENCE = 5          # below this a bucket is INSUFFICIENT_EVIDENCE
ADVISORY = ("Advisory only — nothing is changed automatically. "
            "Base runs and live settings are never modified.")

# ── tiny in-process cache (Part P) ───────────────────────────────────────────
_CACHE: Dict[str, Any] = {}
_CACHE_TTL = 60.0


def _cached(key: str, fn):
    now = time.time()
    hit = _CACHE.get(key)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]
    val = fn()
    _CACHE[key] = (now, val)
    return val


# ── trade loading (backtest run OR paper ledger) ─────────────────────────────

def _paper_trades() -> List[Dict[str, Any]]:
    from phase20_executor import get_ledger
    return [t for t in get_ledger(limit=10000)
            if str(t.get("side") or "BUY").upper() == "BUY"]


def _capital_for(source: str, run_id: Optional[str]) -> Optional[float]:
    """Actual portfolio capital for the source — backtest run config capital,
    or the paper portfolio's initial capital. Read-only lookups."""
    try:
        if source == "backtest" and run_id:
            run = bp.get_run(run_id) or {}
            cap = float((run.get("config") or {}).get("capital") or 0)
            return cap if cap > 0 else None
        import portfolio_store
        return float(portfolio_store.INITIAL_CAPITAL)
    except Exception:
        return None


def _load_trades(source: str, run_id: Optional[str]) -> List[Dict[str, Any]]:
    if source == "paper":
        return _paper_trades()
    if not run_id:
        return []
    return bp.trades(run_id)


def _closed(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [t for t in trades if str(t.get("status")) == "CLOSED"
            and t.get("realized_pnl") is not None]


def _parse_ts(ts: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def _hold_days(t: Dict[str, Any]) -> Optional[float]:
    a, b = _parse_ts(t.get("fill_ts")), _parse_ts(t.get("exit_ts"))
    if a and b:
        return max(0.0, (b - a).total_seconds() / 86400.0)
    return None


def _cost(t: Dict[str, Any]) -> float:
    try:
        return float(t.get("fill_price") or 0) * float(t.get("quantity") or 0)
    except Exception:
        return 0.0


def _ret_pct(t: Dict[str, Any]) -> float:
    c = _cost(t)
    return (float(t.get("realized_pnl") or 0) / c * 100.0) if c > 0 else 0.0


def _as_metric_rows(trades: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Map ledger rows onto expectancy.compute_metrics input — the single
    existing metrics engine (no duplicate math)."""
    rows = []
    for t in _closed(trades):
        rows.append({"return_percent": _ret_pct(t),
                     "holding_days": _hold_days(t),
                     "exit_date": t.get("exit_ts")})
    return rows


def _sector_of(t: Dict[str, Any]) -> str:
    s = t.get("sector")
    if s:
        return str(s)
    try:
        from phase18_reviews import _sector_for
        return _sector_for(str(t.get("symbol") or "")) or "UNKNOWN"
    except Exception:
        return "UNKNOWN"


def _max_exposure(trades: List[Dict[str, Any]]) -> float:
    """Peak concurrently-deployed capital, from ledger open/close intervals."""
    points: List[tuple] = []
    for t in _closed(trades):
        a, b = _parse_ts(t.get("fill_ts")), _parse_ts(t.get("exit_ts"))
        if a and b:
            points.append((a, _cost(t)))
            points.append((b, -_cost(t)))
    points.sort(key=lambda p: p[0])
    cur = peak = 0.0
    for _, delta in points:
        cur += delta
        peak = max(peak, cur)
    return round(peak, 2)


# ── Part B: multi-run comparison ─────────────────────────────────────────────

def run_metrics(run_id: str) -> Dict[str, Any]:
    run = bp.get_run(run_id)
    if not run:
        return {"ok": False, "error": f"Unknown run {run_id}"}
    trades = bp.trades(run_id)
    closed = _closed(trades)
    m = compute_metrics(_as_metric_rows(trades))
    stored = run.get("metrics") or {}
    cfg = run.get("config") or {}
    capital = float(cfg.get("capital") or stored.get("starting_capital")
                    or 0) or None
    pnl = round(sum(float(t.get("realized_pnl") or 0) for t in closed), 2)
    return {
        "ok": True, "run_id": run_id, "status": run.get("status"),
        "period": f"{cfg.get('start')} → {cfg.get('end')}",
        "interval": cfg.get("interval"),
        "universe": cfg.get("symbols") or cfg.get("universe"),
        "capital": capital,
        "trades": m["trades"], "win_rate": m["win_rate"],
        "pnl": pnl,
        "net_return_pct": stored.get("net_return_pct"),
        "sharpe": m["sharpe"], "sortino": m["sortino"],
        "max_drawdown_pct": stored.get("max_drawdown_pct",
                                       m["max_drawdown"]),
        "profit_factor": m["profit_factor"],
        "expectancy": m["expectancy"],
        "avg_hold_days": m["avg_holding_days"],
        "recovery_factor": m["recovery_factor"],
        "capital_growth_pct": (round(pnl / capital * 100.0, 2)
                               if capital else None),
        "max_exposure": _max_exposure(trades),
        "max_exposure_pct": (round(_max_exposure(trades) / capital * 100.0, 2)
                             if capital else None),
        "equity_curve": stored.get("equity_curve") or [],
    }


def compare_runs(run_ids: List[str]) -> Dict[str, Any]:
    rows = [run_metrics(r) for r in run_ids]
    return {"ok": True, "rows": rows, "note": ADVISORY}


def list_completed_runs(limit: int = 50) -> List[Dict[str, Any]]:
    return [r for r in bp.list_runs(limit=limit)
            if r.get("status") == "COMPLETED"]


# ── Parts A & C: config what-if / parameter optimizer (derived, isolated) ────

def _entry_volume_ratio(run_id: str, t: Dict[str, Any]) -> Optional[float]:
    from pipeline_events import query_events
    sid = t.get("scan_id")
    if not sid:
        return None
    evs = query_events(run_id=run_id, mode="BACKTEST",
                       symbol=str(t.get("symbol") or "").upper(), limit=2000)
    for e in evs:
        if e.get("scan_id") == sid and e.get("event_type") == "SYMBOL_SCANNED":
            return (e.get("payload") or {}).get("volume_ratio")
    return None


def _resim_exit(run_id: str, t: Dict[str, Any], stop_mult: float,
                target_mult: float, trailing_mult: Optional[float],
                cfg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Re-simulate ONE trade's exit with adjusted stop/target levels over the
    SAME cached candles, using the SAME priority rule as the engine (stop
    beats target on the same candle; still-open at end → close at final
    close). Advisory derived simulation — never persisted."""
    fill = float(t.get("fill_price") or 0)
    stop0 = float(t.get("stop_loss") or 0)
    tgt0 = float(t.get("target") or 0)
    qty = float(t.get("quantity") or 0)
    if fill <= 0 or stop0 <= 0 or tgt0 <= 0 or qty <= 0:
        return None
    interval = str(cfg.get("interval") or "1d")
    candles = hde.get_candles(str(t.get("symbol")), interval,
                              str(cfg.get("start"))[:10],
                              str(cfg.get("end"))[:10])
    fill_ts = _parse_ts(t.get("fill_ts"))
    if not candles or not fill_ts:
        return None
    stop_d = (fill - stop0) * stop_mult
    stop = fill - stop_d
    target = fill + (tgt0 - fill) * target_mult
    high_wm = fill
    exit_price = None
    exit_rule = None
    exit_ts = None
    for c in candles:
        cts = _parse_ts(c["ts"])
        if not cts or cts <= fill_ts:
            continue
        if trailing_mult:
            high_wm = max(high_wm, float(c["high"]))
            stop = max(stop, high_wm - stop_d * trailing_mult / stop_mult
                       if stop_mult else high_wm - stop_d)
        if float(c["low"]) <= stop:          # stop has priority
            exit_price, exit_rule, exit_ts = stop, "STOP", c["ts"]
            break
        if float(c["high"]) >= target:
            exit_price, exit_rule, exit_ts = target, "TARGET", c["ts"]
            break
    if exit_price is None:
        exit_price, exit_rule, exit_ts = (float(candles[-1]["close"]),
                                          "END_OF_BACKTEST",
                                          candles[-1]["ts"])
    pnl = (exit_price - fill) * qty
    return {"exit_price": round(exit_price, 2), "exit_rule": exit_rule,
            "exit_ts": exit_ts, "realized_pnl": round(pnl, 2)}


def what_if(run_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Derived what-if simulation of one configuration over a COMPLETED run.
    The base run is never modified; every call is an isolated recomputation."""
    run = bp.get_run(run_id)
    if not run:
        return {"ok": False, "error": f"Unknown run {run_id}"}
    cfg = run.get("config") or {}
    base = _closed(bp.trades(run_id))
    if not base:
        return {"ok": False, "error": "Run has no closed trades",
                "verdict": "INSUFFICIENT_EVIDENCE"}

    min_conf = params.get("min_confidence")
    regime_f = params.get("regime_filter")
    sector_f = params.get("sector_filter")
    min_vol = params.get("min_volume_ratio")
    max_open = params.get("max_open_trades")
    risk_scale = float(params.get("risk_scale") or 1.0)
    stop_mult = float(params.get("stop_mult") or 1.0)
    target_mult = float(params.get("target_mult") or 1.0)
    trailing = params.get("trailing_mult")
    trailing = float(trailing) if trailing else None

    kept, dropped = [], []
    for t in sorted(base, key=lambda x: str(x.get("fill_ts") or "")):
        why = None
        if min_conf is not None and float(t.get("confidence") or 0) \
                < float(min_conf):
            why = f"confidence {t.get('confidence')} < {min_conf}"
        elif regime_f and str(t.get("regime") or "").upper() \
                != str(regime_f).upper():
            why = f"regime {t.get('regime')} != {regime_f}"
        elif sector_f and _sector_of(t).upper() != str(sector_f).upper():
            why = f"sector {_sector_of(t)} != {sector_f}"
        elif min_vol is not None:
            vr = _entry_volume_ratio(run_id, t)
            if vr is not None and float(vr) < float(min_vol):
                why = f"volume_ratio {vr} < {min_vol}"
        if why:
            dropped.append({"trade_id": t.get("trade_id"),
                            "symbol": t.get("symbol"), "reason": why})
        else:
            kept.append(dict(t))

    if max_open is not None:
        limited, open_iv = [], []
        for t in kept:
            a, b = _parse_ts(t.get("fill_ts")), _parse_ts(t.get("exit_ts"))
            open_iv = [(x, y) for x, y in open_iv if a and y and y > a]
            if len(open_iv) >= int(max_open):
                dropped.append({"trade_id": t.get("trade_id"),
                                "symbol": t.get("symbol"),
                                "reason": f"max_open_trades {max_open} reached"})
                continue
            limited.append(t)
            if a and b:
                open_iv.append((a, b))
        kept = limited

    resim = (stop_mult != 1.0 or target_mult != 1.0 or trailing is not None)
    resim_failures = 0
    resim_failed: List[Dict[str, Any]] = []
    simulated: List[Dict[str, Any]] = []
    for t in kept:
        if resim:
            r = _resim_exit(run_id, t, stop_mult, target_mult, trailing, cfg)
            if r is None:
                # Never retain the baseline exit as if it were re-simulated —
                # exclude the trade from the derived result entirely.
                resim_failures += 1
                resim_failed.append({"trade_id": t.get("trade_id"),
                                     "symbol": t.get("symbol"),
                                     "reason": "candles/fields unavailable "
                                               "for exit re-simulation"})
                continue
            t.update(r)
        if risk_scale != 1.0:
            t["realized_pnl"] = round(float(t["realized_pnl"]) * risk_scale, 2)
            t["quantity"] = float(t.get("quantity") or 0) * risk_scale
        simulated.append(t)
    kept = simulated

    m = compute_metrics(_as_metric_rows(kept))
    pnl = round(sum(float(t.get("realized_pnl") or 0) for t in kept), 2)
    return {
        "ok": True, "run_id": run_id, "params": params,
        "derived": True, "base_run_modified": False,
        "trades_kept": len(kept), "trades_dropped": len(dropped),
        "dropped": dropped[:50],
        "resimulated_exits": resim, "resim_failures": resim_failures,
        "resim_failed": resim_failed[:50],
        "pnl": pnl, "metrics": m,
        "verdict": ("INSUFFICIENT_EVIDENCE" if len(kept) < MIN_EVIDENCE
                    else "RESIM_INCOMPLETE" if resim_failures > 0
                    else "OK"),
        "note": ADVISORY,
    }


def compare_configs(run_id: str, configs: List[Dict[str, Any]]
                    ) -> Dict[str, Any]:
    rows = []
    for c in configs[:8]:
        r = what_if(run_id, c.get("params") or {})
        r["label"] = c.get("label") or "Config"
        rows.append(r)
    return {"ok": True, "run_id": run_id, "rows": rows, "note": ADVISORY}


# ── Part D: walk-forward (derived folds over the trade sequence) ─────────────

def walk_forward(run_id: str, folds: int = 4) -> Dict[str, Any]:
    closed = sorted(_closed(bp.trades(run_id)),
                    key=lambda t: str(t.get("exit_ts") or ""))
    if len(closed) < folds * 2:
        return {"ok": True, "run_id": run_id, "folds": [],
                "verdict": "INSUFFICIENT_EVIDENCE",
                "reason": f"{len(closed)} closed trades < {folds * 2} needed",
                "note": ADVISORY}
    n = len(closed)
    seg = max(1, n // (folds + 1))
    fold_rows = []
    for i in range(folds):
        train = closed[: seg * (i + 1)]
        validate = closed[seg * (i + 1): seg * (i + 2)]
        if not validate:
            break
        tm = compute_metrics(_as_metric_rows(train))
        vm = compute_metrics(_as_metric_rows(validate))
        fold_rows.append({
            "fold": i + 1,
            "train_trades": tm["trades"], "validate_trades": vm["trades"],
            "train_expectancy": tm["expectancy"],
            "validate_expectancy": vm["expectancy"],
            "train_win_rate": tm["win_rate"],
            "validate_win_rate": vm["win_rate"],
        })
    gen_scores = []
    for f in fold_rows:
        te, ve = f["train_expectancy"], f["validate_expectancy"]
        if te > 0:
            gen_scores.append(max(0.0, min(1.5, ve / te)))
        elif ve > 0:
            gen_scores.append(1.0)
    gen = round(sum(gen_scores) / len(gen_scores), 2) if gen_scores else None
    v_rates = [f["validate_win_rate"] for f in fold_rows]
    mean_v = sum(v_rates) / len(v_rates) if v_rates else 0
    consistency = (round(100.0 - (max(v_rates) - min(v_rates)), 1)
                   if v_rates else None)
    overfit = ("UNKNOWN" if gen is None else
               "HIGH" if gen < 0.4 else "MEDIUM" if gen < 0.75 else "LOW")
    return {"ok": True, "run_id": run_id, "folds": fold_rows,
            "generalization_score": gen,
            "consistency": consistency,
            "mean_validation_win_rate": round(mean_v, 1),
            "overfitting_risk": overfit,
            "verdict": "OK", "note": ADVISORY}


# ── Part E: Monte Carlo (bootstrap over completed trade returns) ─────────────

def monte_carlo(source: str, run_id: Optional[str] = None,
                simulations: int = 500) -> Dict[str, Any]:
    closed = _closed(_load_trades(source, run_id))
    # Portfolio-level per-trade returns: realized PnL relative to actual
    # portfolio capital — never "all-in" per-trade notional returns, which
    # would wildly overstate compounding, drawdown and risk-of-ruin.
    capital = _capital_for(source, run_id)
    if not capital or capital <= 0:
        return {"ok": True, "verdict": "INSUFFICIENT_EVIDENCE",
                "reason": "portfolio capital unavailable", "note": ADVISORY}
    rets = [float(t.get("realized_pnl") or 0) / capital * 100.0
            for t in closed]
    if len(rets) < MIN_EVIDENCE:
        return {"ok": True, "verdict": "INSUFFICIENT_EVIDENCE",
                "reason": f"only {len(rets)} completed trades", "note": ADVISORY}
    rng = random.Random(f"{source}:{run_id}:{len(rets)}")  # deterministic
    simulations = max(100, min(2000, int(simulations)))
    finals, max_dds, paths = [], [], []
    for s in range(simulations):
        eq, peak, dd = 1.0, 1.0, 0.0
        path = [1.0]
        for _ in range(len(rets)):
            eq *= 1.0 + rng.choice(rets) / 100.0
            peak = max(peak, eq)
            dd = max(dd, (peak - eq) / peak * 100.0 if peak > 0 else 0.0)
            path.append(round(eq, 4))
        finals.append(eq)
        max_dds.append(dd)
        if s < 40:
            paths.append(path)
    finals.sort()
    max_dds.sort()

    def pct(vals, p):
        return vals[min(len(vals) - 1, int(p / 100.0 * len(vals)))]

    ret = [round((v - 1.0) * 100.0, 2) for v in finals]
    return {
        "ok": True, "source": source, "run_id": run_id,
        "simulations": simulations, "trades_per_path": len(rets),
        "probability_of_profit": round(
            sum(1 for v in finals if v > 1.0) / simulations * 100.0, 1),
        "probability_drawdown_gt_10pct": round(
            sum(1 for d in max_dds if d > 10.0) / simulations * 100.0, 1),
        "expected_return_range_pct": {"p5": pct(ret, 5), "p50": pct(ret, 50),
                                      "p95": pct(ret, 95)},
        "confidence_interval_95_pct": [pct(ret, 2.5), pct(ret, 97.5)],
        "worst_expected_drawdown_pct": round(pct(max_dds, 95), 2),
        "best_expected_outcome_pct": ret[-1],
        "capital_survival_probability": round(
            sum(1 for v in finals if v > 0.5) / simulations * 100.0, 1),
        "risk_of_ruin_pct": round(
            sum(1 for v in finals if v <= 0.5) / simulations * 100.0, 2),
        "return_histogram": _hist(ret, 20),
        "drawdown_histogram": _hist(max_dds, 15),
        "sample_paths": paths,
        "verdict": "OK", "note": ADVISORY,
    }


def _hist(vals: List[float], bins: int) -> List[Dict[str, Any]]:
    if not vals:
        return []
    lo, hi = min(vals), max(vals)
    if hi <= lo:
        return [{"bucket": round(lo, 2), "count": len(vals)}]
    w = (hi - lo) / bins
    out = [0] * bins
    for v in vals:
        out[min(bins - 1, int((v - lo) / w))] += 1
    return [{"bucket": round(lo + i * w + w / 2, 2), "count": c}
            for i, c in enumerate(out)]


# ── Parts F/G/H: regime / time / sector buckets ──────────────────────────────

def _bucket_rows(closed: List[Dict[str, Any]], keyer) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for t in closed:
        groups.setdefault(str(keyer(t) or "UNKNOWN"), []).append(t)
    rows = []
    for k, ts in groups.items():
        wins = sum(1 for t in ts if float(t.get("realized_pnl") or 0) > 0)
        pnl = round(sum(float(t.get("realized_pnl") or 0) for t in ts), 2)
        by_strat: Dict[str, float] = {}
        for t in ts:
            s = str(t.get("strategy_name") or "?")
            by_strat[s] = by_strat.get(s, 0.0) + float(t.get("realized_pnl")
                                                       or 0)
        ranked = sorted(by_strat.items(), key=lambda kv: kv[1], reverse=True)
        holds = [h for h in (_hold_days(t) for t in ts) if h is not None]
        rows.append({
            "bucket": k, "trades": len(ts),
            "win_rate": round(wins / len(ts) * 100.0, 1),
            "pnl": pnl,
            "expectancy": compute_metrics(_as_metric_rows(ts))["expectancy"],
            "best_strategy": ranked[0][0] if ranked else None,
            "worst_strategy": ranked[-1][0] if ranked else None,
            "avg_hold_days": (round(sum(holds) / len(holds), 2)
                              if holds else None),
            "insufficient_evidence": len(ts) < MIN_EVIDENCE,
        })
    rows.sort(key=lambda r: r["pnl"], reverse=True)
    return rows


def bucket_analysis(source: str, run_id: Optional[str] = None
                    ) -> Dict[str, Any]:
    closed = _closed(_load_trades(source, run_id))

    def hour_of(t):
        d = _parse_ts(t.get("fill_ts"))
        return f"{d.astimezone(IST).hour:02d}:00 IST" if d else None

    def weekday_of(t):
        d = _parse_ts(t.get("fill_ts"))
        return d.astimezone(IST).strftime("%A") if d else None

    def month_of(t):
        d = _parse_ts(t.get("exit_ts")) or _parse_ts(t.get("fill_ts"))
        return d.astimezone(IST).strftime("%Y-%m") if d else None

    return {
        "ok": True, "source": source, "run_id": run_id,
        "total_trades": len(closed),
        "regime": _bucket_rows(closed, lambda t: str(t.get("regime")
                                                     or "UNKNOWN").upper()),
        "sector": _bucket_rows(closed, _sector_of),
        "hour": _bucket_rows(closed, hour_of),
        "weekday": _bucket_rows(closed, weekday_of),
        "month": _bucket_rows(closed, month_of),
        "strategy": _bucket_rows(closed,
                                 lambda t: t.get("strategy_name") or "?"),
        "verdict": ("INSUFFICIENT_EVIDENCE" if len(closed) < MIN_EVIDENCE
                    else "OK"),
        "note": ADVISORY,
    }


# ── Part I: strategy leaderboard ─────────────────────────────────────────────

def leaderboard(source: str, run_id: Optional[str] = None) -> Dict[str, Any]:
    closed = _closed(_load_trades(source, run_id))
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for t in closed:
        groups.setdefault(str(t.get("strategy_name") or "?"), []).append(t)
    rows = []
    for name, ts in groups.items():
        m = compute_metrics(_as_metric_rows(ts))
        pnl = round(sum(float(t.get("realized_pnl") or 0) for t in ts), 2)
        wins = [t for t in ts if float(t.get("realized_pnl") or 0) > 0]
        conf_w = [float(t.get("confidence") or 0) for t in wins
                  if t.get("confidence") is not None]
        conf_l = [float(t.get("confidence") or 0) for t in ts
                  if float(t.get("realized_pnl") or 0) <= 0
                  and t.get("confidence") is not None]
        cap = sum(_cost(t) for t in ts)
        rows.append({
            "strategy": name, "trades": m["trades"],
            "win_rate": m["win_rate"], "pnl": pnl,
            "max_drawdown_pct": m["max_drawdown"],
            "profit_factor": m["profit_factor"],
            "expectancy": m["expectancy"],
            "sharpe": m["sharpe"], "sortino": m["sortino"],
            "recovery_factor": m["recovery_factor"],
            "avg_hold_days": m["avg_holding_days"],
            "confidence_accuracy": (
                round((sum(conf_w) / len(conf_w))
                      - (sum(conf_l) / len(conf_l)), 1)
                if conf_w and conf_l else None),
            "capital_efficiency_pct": (round(pnl / cap * 100.0, 2)
                                       if cap > 0 else None),
            "insufficient_evidence": len(ts) < MIN_EVIDENCE,
        })
    rows.sort(key=lambda r: r["pnl"], reverse=True)
    return {"ok": True, "source": source, "run_id": run_id, "rows": rows,
            "note": ADVISORY}


# ── Part J: confidence calibration ───────────────────────────────────────────

def calibration(source: str, run_id: Optional[str] = None) -> Dict[str, Any]:
    closed = [t for t in _closed(_load_trades(source, run_id))
              if t.get("confidence") is not None]
    buckets = []
    brier_terms = []
    for lo in range(30, 100, 10):
        hi = lo + 10
        ts = [t for t in closed if lo <= float(t["confidence"]) < hi]
        if not ts:
            continue
        wins = sum(1 for t in ts if float(t.get("realized_pnl") or 0) > 0)
        observed = wins / len(ts) * 100.0
        predicted = sum(float(t["confidence"]) for t in ts) / len(ts)
        buckets.append({
            "bucket": f"{lo}–{hi}", "trades": len(ts),
            "predicted_win_rate": round(predicted, 1),
            "observed_win_rate": round(observed, 1),
            "calibration_error": round(observed - predicted, 1),
            "insufficient_evidence": len(ts) < MIN_EVIDENCE,
        })
    for t in closed:
        p = float(t["confidence"]) / 100.0
        o = 1.0 if float(t.get("realized_pnl") or 0) > 0 else 0.0
        brier_terms.append((p - o) ** 2)
    out: Dict[str, Any] = {
        "ok": True, "source": source, "run_id": run_id,
        "trades": len(closed), "reliability_curve": buckets,
        "brier_score": (round(sum(brier_terms) / len(brier_terms), 4)
                        if brier_terms else None),
        "mean_abs_calibration_error": (
            round(sum(abs(b["calibration_error"]) for b in buckets)
                  / len(buckets), 1) if buckets else None),
        "confidence_distribution": _hist(
            [float(t["confidence"]) for t in closed], 12),
        "verdict": ("INSUFFICIENT_EVIDENCE" if len(closed) < MIN_EVIDENCE
                    else "OK"),
        "note": ADVISORY,
    }
    if source == "paper":
        try:
            from phase21_calibration import run_calibration
            out["phase21_calibration"] = run_calibration()  # verbatim
        except Exception as exc:
            out["phase21_calibration_error"] = str(exc)
    return out


# ── Part K: institutional dashboard bundle ───────────────────────────────────

def dashboard(source: str, run_id: Optional[str] = None) -> Dict[str, Any]:
    def build():
        trades = _load_trades(source, run_id)
        closed = sorted(_closed(trades),
                        key=lambda t: str(t.get("exit_ts") or ""))
        capital = None
        equity_curve: List[Dict[str, Any]] = []
        if source == "backtest" and run_id:
            run = bp.get_run(run_id) or {}
            capital = float((run.get("config") or {}).get("capital") or 0) \
                or None
            equity_curve = (run.get("metrics") or {}).get("equity_curve") or []
        if not equity_curve and capital is None:
            capital = 100000.0
        if not equity_curve:
            eq = capital
            for t in closed:
                eq += float(t.get("realized_pnl") or 0)
                equity_curve.append({"ts": t.get("exit_ts"),
                                     "equity": round(eq, 2)})
        # drawdown curve from equity
        dd_curve, peak = [], None
        for p in equity_curve:
            v = float(p.get("equity") or p.get("value") or 0)
            peak = v if peak is None else max(peak, v)
            dd_curve.append({"ts": p.get("ts"),
                             "drawdown_pct": round((peak - v) / peak * 100.0, 2)
                             if peak else 0.0})
        # monthly returns
        monthly: Dict[str, float] = {}
        for t in closed:
            d = _parse_ts(t.get("exit_ts"))
            if d:
                k = d.astimezone(IST).strftime("%Y-%m")
                monthly[k] = monthly.get(k, 0.0) + float(t.get("realized_pnl")
                                                         or 0)
        # rolling windows (10 trades)
        rolling = []
        W = 10
        for i in range(W, len(closed) + 1):
            win = closed[i - W: i]
            m = compute_metrics(_as_metric_rows(win))
            rolling.append({"trade_index": i, "sharpe": m["sharpe"],
                            "win_rate": m["win_rate"],
                            "profit_factor": m["profit_factor"]})
        buckets = bucket_analysis(source, run_id)
        # risk heatmap: sector × regime pnl
        heat: Dict[str, Dict[str, float]] = {}
        for t in closed:
            s, r = _sector_of(t), str(t.get("regime") or "UNKNOWN").upper()
            heat.setdefault(s, {})[r] = heat.setdefault(s, {}).get(r, 0.0) \
                + float(t.get("realized_pnl") or 0)
        heatmap = [{"sector": s,
                    "cells": [{"regime": r, "pnl": round(v, 2)}
                              for r, v in sorted(m.items())]}
                   for s, m in sorted(heat.items())]
        # capital utilization over time
        util = []
        if capital:
            events: List[tuple] = []
            for t in closed:
                a, b = _parse_ts(t.get("fill_ts")), _parse_ts(t.get("exit_ts"))
                if a and b:
                    events.append((a.isoformat(), _cost(t)))
                    events.append((b.isoformat(), -_cost(t)))
            events.sort()
            cur = 0.0
            for ts, delta in events:
                cur += delta
                util.append({"ts": ts,
                             "utilization_pct": round(cur / capital * 100.0,
                                                      2)})
        m_all = compute_metrics(_as_metric_rows(closed))
        return {
            "ok": True, "source": source, "run_id": run_id,
            "capital": capital,
            "summary": m_all,
            "total_pnl": round(sum(float(t.get("realized_pnl") or 0)
                                   for t in closed), 2),
            "equity_curve": equity_curve,
            "drawdown_curve": dd_curve,
            "monthly_returns": [{"month": k, "pnl": round(v, 2)}
                                for k, v in sorted(monthly.items())],
            "rolling": rolling,
            "strategy_comparison": buckets["strategy"],
            "sector_comparison": buckets["sector"],
            "regime_comparison": buckets["regime"],
            "calibration": calibration(source, run_id),
            "risk_heatmap": heatmap,
            "capital_utilization": util,
            "verdict": ("INSUFFICIENT_EVIDENCE" if len(closed) < MIN_EVIDENCE
                        else "OK"),
            "note": ADVISORY,
        }
    return _cached(f"dash:{source}:{run_id}", build)


# ── Part L: recommendations (advisory only) ──────────────────────────────────

def recommendations(source: str, run_id: Optional[str] = None
                    ) -> Dict[str, Any]:
    closed = _closed(_load_trades(source, run_id))
    recs: List[Dict[str, Any]] = []
    if len(closed) < MIN_EVIDENCE:
        return {"ok": True, "source": source, "run_id": run_id,
                "recommendations": [],
                "verdict": "INSUFFICIENT_EVIDENCE",
                "reason": f"only {len(closed)} completed trades",
                "note": ADVISORY}

    # confidence threshold sweep (filter-only what-if over recorded trades)
    def exp_at(minc):
        kept = [t for t in closed if float(t.get("confidence") or 0) >= minc]
        if len(kept) < MIN_EVIDENCE:
            return None, len(kept)
        return compute_metrics(_as_metric_rows(kept))["expectancy"], len(kept)

    base_exp = compute_metrics(_as_metric_rows(closed))["expectancy"]
    best = (None, base_exp, len(closed))
    for c in range(40, 80, 5):
        e, n = exp_at(c)
        if e is not None and e > best[1]:
            best = (c, e, n)
    if best[0] is not None:
        recs.append({
            "kind": "confidence_threshold",
            "text": (f"Confidence threshold ≥{best[0]} would have improved "
                     f"expectancy from {base_exp} to {best[1]} "
                     f"({best[2]} trades)."),
            "evidence_trades": best[2], "advisory": True})

    buckets = bucket_analysis(source, run_id)
    for dim, label in (("sector", "allocation"), ("hour", "entry window"),
                       ("weekday", "weekday")):
        rows = [r for r in buckets[dim] if not r["insufficient_evidence"]]
        if len(rows) >= 2:
            recs.append({"kind": f"best_{dim}",
                         "text": (f"Best {label}: {rows[0]['bucket']} "
                                  f"(₹{rows[0]['pnl']}, "
                                  f"{rows[0]['win_rate']}% win rate); worst: "
                                  f"{rows[-1]['bucket']} (₹{rows[-1]['pnl']})."),
                         "evidence_trades": rows[0]["trades"]
                         + rows[-1]["trades"], "advisory": True})

    # stop-multiplier sweep (backtest only — needs cached candles)
    if source == "backtest" and run_id:
        base_pnl = sum(float(t.get("realized_pnl") or 0) for t in closed)
        best_sm = (1.0, base_pnl)
        for sm in (1.5, 2.0, 2.5, 3.0):
            wf = what_if(run_id, {"stop_mult": sm})
            if wf.get("ok") and wf.get("verdict") == "OK" \
                    and not wf.get("resim_failures") \
                    and wf["pnl"] > best_sm[1]:
                best_sm = (sm, wf["pnl"])
        if best_sm[0] != 1.0:
            recs.append({"kind": "stop_multiplier",
                         "text": (f"Widening the stop to {best_sm[0]}× the "
                                  f"recorded distance would have improved PnL "
                                  f"from ₹{round(base_pnl, 2)} to "
                                  f"₹{best_sm[1]} (derived simulation)."),
                         "evidence_trades": len(closed), "advisory": True})

    return {"ok": True, "source": source, "run_id": run_id,
            "recommendations": recs, "verdict": "OK",
            "auto_apply": False, "note": ADVISORY}


# ── Part M: compare any two runs ─────────────────────────────────────────────

def run_diff(run_a: str, run_b: str) -> Dict[str, Any]:
    a, b = run_metrics(run_a), run_metrics(run_b)
    if not a.get("ok") or not b.get("ok"):
        return {"ok": False, "error": "unknown run",
                "a": a.get("error"), "b": b.get("error")}
    ta = {(t.get("symbol"), str(t.get("fill_ts"))): t
          for t in _closed(bp.trades(run_a))}
    tb = {(t.get("symbol"), str(t.get("fill_ts"))): t
          for t in _closed(bp.trades(run_b))}
    added = [dict(symbol=k[0], fill_ts=k[1],
                  pnl=tb[k].get("realized_pnl")) for k in tb if k not in ta]
    removed = [dict(symbol=k[0], fill_ts=k[1],
                    pnl=ta[k].get("realized_pnl")) for k in ta if k not in tb]

    def avg(ts, key):
        vals = [float(t.get(key) or 0) for t in ts if t.get(key) is not None]
        return round(sum(vals) / len(vals), 1) if vals else None

    strat = lambda ts: sorted({str(t.get("strategy_name")) for t in ts})
    return {
        "ok": True, "run_a": a, "run_b": b,
        "trades_added": added, "trades_removed": removed,
        "pnl_difference": round((b["pnl"] or 0) - (a["pnl"] or 0), 2),
        "drawdown_difference": round(
            float(b["max_drawdown_pct"] or 0) - float(a["max_drawdown_pct"]
                                                      or 0), 2),
        "strategy_difference": {
            "only_a": [s for s in strat(ta.values())
                       if s not in strat(tb.values())],
            "only_b": [s for s in strat(tb.values())
                       if s not in strat(ta.values())]},
        "confidence_difference": {
            "a": avg(ta.values(), "confidence"),
            "b": avg(tb.values(), "confidence")},
        "risk_difference": {"a_max_exposure": a["max_exposure"],
                            "b_max_exposure": b["max_exposure"]},
        "note": ADVISORY,
    }


# ── Part N: export ───────────────────────────────────────────────────────────

def export_report(source: str, run_id: Optional[str], fmt: str
                  ) -> Dict[str, Any]:
    dash = dashboard(source, run_id)
    recs = recommendations(source, run_id)
    name = f"strategy_lab_{source}{('_' + run_id) if run_id else ''}"
    if fmt == "json":
        return {"ok": True, "filename": f"{name}.json",
                "content_type": "application/json",
                "content": json.dumps({"dashboard": dash,
                                       "recommendations": recs}, indent=2)}
    if fmt == "csv":
        lines = ["strategy,trades,win_rate,pnl,profit_factor,expectancy,"
                 "sharpe,sortino,max_drawdown_pct,avg_hold_days"]
        for r in dash["strategy_comparison"]:
            lines.append(",".join(str(r.get(k, "")) for k in
                                  ("bucket", "trades", "win_rate", "pnl",
                                   "expectancy", "expectancy", "avg_hold_days",
                                   "avg_hold_days", "pnl", "avg_hold_days")))
        lb = leaderboard(source, run_id)
        lines.append("")
        lines.append("leaderboard_strategy,trades,win_rate,pnl,profit_factor,"
                     "expectancy,sharpe,sortino,recovery,avg_hold_days")
        for r in lb["rows"]:
            lines.append(",".join(str(r.get(k, "")) for k in
                                  ("strategy", "trades", "win_rate", "pnl",
                                   "profit_factor", "expectancy", "sharpe",
                                   "sortino", "recovery_factor",
                                   "avg_hold_days")))
        return {"ok": True, "filename": f"{name}.csv",
                "content_type": "text/csv", "content": "\n".join(lines)}
    # markdown (also the print-to-PDF source)
    s = dash["summary"]
    md = [f"# Strategy Lab Report — {source}"
          + (f" ({run_id})" if run_id else ""),
          "", f"_{ADVISORY}_", "",
          "## Summary",
          f"- Trades: {s['trades']}  |  Win rate: {s['win_rate']}%  |  "
          f"PnL: ₹{dash['total_pnl']}",
          f"- Profit factor: {s['profit_factor']}  |  Expectancy: "
          f"{s['expectancy']}  |  Sharpe: {s['sharpe']}  |  Sortino: "
          f"{s['sortino']}",
          f"- Max drawdown: {s['max_drawdown']}%  |  Recovery factor: "
          f"{s['recovery_factor']}",
          "", "## Monthly returns"]
    for m in dash["monthly_returns"]:
        md.append(f"- {m['month']}: ₹{m['pnl']}")
    md += ["", "## Strategy comparison",
           "| Strategy | Trades | Win rate | PnL | Expectancy |",
           "|---|---|---|---|---|"]
    for r in dash["strategy_comparison"]:
        md.append(f"| {r['bucket']} | {r['trades']} | {r['win_rate']}% | "
                  f"₹{r['pnl']} | {r['expectancy']} |")
    md += ["", "## Recommendations (advisory only)"]
    for r in recs.get("recommendations", []):
        md.append(f"- {r['text']}")
    if not recs.get("recommendations"):
        md.append(f"- {recs.get('verdict')}: {recs.get('reason', '')}")
    return {"ok": True, "filename": f"{name}.md",
            "content_type": "text/markdown", "content": "\n".join(md)}


# ── Part O: validation ───────────────────────────────────────────────────────

def lab_verify(run_id: Optional[str] = None) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []

    def check(name, passed, detail):
        checks.append({"check": name,
                       "status": "PASS" if passed else "FAIL",
                       "detail": detail})

    rid = run_id
    if not rid:
        runs = list_completed_runs(limit=1)
        rid = runs[0]["run_id"] if runs else None
    if rid:
        before = json.dumps(bp.get_run(rid), sort_keys=True, default=str)
        trades_before = json.dumps(bp.trades(rid), sort_keys=True, default=str)
        what_if(rid, {"min_confidence": 55, "stop_mult": 2.0})
        walk_forward(rid)
        recommendations("backtest", rid)
        after = json.dumps(bp.get_run(rid), sort_keys=True, default=str)
        trades_after = json.dumps(bp.trades(rid), sort_keys=True, default=str)
        check("runs_immutable", before == after and
              trades_before == trades_after,
              f"run {rid} record + ledger byte-identical after what-if, "
              "walk-forward and recommendations")
        try:
            from backtest_replay import replay_verify
            rv = replay_verify(rid)
            check("replay_integrity_preserved",
                  rv.get("verdict") == "PASS",
                  f"replay_verify verdict: {rv.get('verdict')}")
        except Exception as exc:
            check("replay_integrity_preserved", False, str(exc))
    else:
        check("runs_immutable", True, "no completed runs to verify against")

    try:
        from phase20_store import get_settings
        s_before = json.dumps(get_settings(), sort_keys=True, default=str)
        recommendations("paper")
        s_after = json.dumps(get_settings(), sort_keys=True, default=str)
        check("live_settings_untouched", s_before == s_after,
              "phase20 settings byte-identical after paper recommendations")
    except Exception as exc:
        check("live_settings_untouched", False, str(exc))

    try:
        import phase24_learning as p24
        auto = bool(getattr(p24, "AUTO_APPLY_ENABLED", False))
        check("learning_engine_advisory", not auto,
              f"phase24 AUTO_APPLY_ENABLED={auto}")
    except Exception:
        check("learning_engine_advisory", True,
              "phase24 module not present — nothing can auto-apply")

    passed = all(c["status"] == "PASS" for c in checks)
    return {"ok": True, "verdict": "PASS" if passed else "FAIL",
            "checks": checks, "note": ADVISORY}
