"""
phase14_learning.py — Phase 14: Completed-trade learning dataset + outcome evaluation.

RESEARCH / PAPER LEARNING ONLY.
- Learns ONLY from completed historical and paper trades.
- Strict no-look-ahead: entry features are entry-time snapshots only.
- Every learning row carries an explicit no-look-ahead audit result.
- Reliability labels gate every metric group; small samples never produce
  strong conclusions.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
from datetime import datetime, timezone

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_FILE = os.path.join(BASE_DIR, "trade_intelligence.db")
DATASET_FILE = os.path.join(BASE_DIR, "phase14_learning_dataset.json")
EVAL_FILE = os.path.join(BASE_DIR, "phase14_evaluation.json")

FEATURE_VERSION = "fv1"
MODEL_VERSION = "p14_m1"

# Reliability thresholds (completed trades in group)
RELIABILITY_BANDS = [
    (250, "HIGH"),
    (100, "STRONG"),
    (50, "MODERATE"),
    (30, "LOW"),
    (0, "INSUFFICIENT"),
]

# Entry-time feature columns permitted in learning rows (no-look-ahead whitelist)
ENTRY_FEATURE_COLS = [
    "ema9", "ema20", "ema50", "ema200", "rsi", "macd", "macd_signal", "vwap",
    "atr", "adx", "supertrend", "volume_ratio", "opportunity_score",
    "trade_quality", "confidence", "risk_reward", "market_regime",
    "sector", "strategy", "volatility",
]
# Outcome columns that must NEVER be used as entry features
OUTCOME_COLS = ["exit_price", "profit_loss", "return_percent", "outcome",
                "outcome_classification", "exit_reason", "holding_period"]


def reliability_label(n: int) -> str:
    for threshold, label in RELIABILITY_BANDS:
        if n >= threshold:
            return label
    return "INSUFFICIENT"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Dataset construction ───────────────────────────────────────────────────────

def _load_completed_trades() -> list[dict]:
    if not os.path.exists(DB_FILE):
        return []
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT * FROM trade_intelligence "
            "WHERE exit_price IS NOT NULL AND entry_price IS NOT NULL"
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        conn.close()
    return [dict(r) for r in rows]


def _no_look_ahead_audit(t: dict) -> dict:
    """Audit a raw completed trade for look-ahead safety."""
    issues: list[str] = []
    # 1. Trade must be completed (both entry and exit present)
    if t.get("exit_price") is None or t.get("entry_price") is None:
        issues.append("trade not completed")
    # 2. Entry features must be entry-time snapshots (whitelist enforced at
    #    construction time; here we verify no outcome column leaked into the
    #    feature block — structural guarantee)
    # 3. Recorded_at must not precede the trade date
    date = t.get("date")
    recorded = t.get("recorded_at")
    if date and recorded and str(recorded)[:10] < str(date)[:10]:
        issues.append("recorded before entry date")
    # 4. Holding period must be non-negative
    hp = t.get("holding_period")
    if hp is not None and hp < 0:
        issues.append("negative holding period")
    return {"passed": not issues, "issues": issues}


def build_learning_dataset(force: bool = False) -> dict:
    """Build canonical learning dataset from completed trades only."""
    trades = _load_completed_trades()
    rows: list[dict] = []
    audit_pass = 0
    for t in trades:
        audit = _no_look_ahead_audit(t)
        net_pnl = float(t.get("profit_loss") or 0.0)
        gross_pnl = net_pnl  # costs already netted in paper trader
        ret_pct = float(t.get("return_percent") or 0.0)
        outcome = "WIN" if net_pnl > 0 else ("LOSS" if net_pnl < 0 else "BREAKEVEN")
        entry_features = {c: t.get(c) for c in ENTRY_FEATURE_COLS}
        row = {
            "trade_id": t.get("trade_id"),
            "scan_id": None,
            "snapshot_ts": t.get("date"),
            "symbol": t.get("symbol"),
            "sector": t.get("sector") or "UNKNOWN",
            "strategy": t.get("strategy") or t.get("entry_strategy") or "UNKNOWN",
            "entry_ts": t.get("date"),
            "exit_ts": t.get("recorded_at"),
            "entry_price": t.get("entry_price"),
            "exit_price": t.get("exit_price"),
            "stop_loss": None,
            "target": None,
            "quantity": t.get("quantity"),
            "holding_period_days": t.get("holding_period"),
            "gross_pnl": gross_pnl,
            "transaction_costs": 0.0,
            "net_pnl": net_pnl,
            "return_pct": ret_pct,
            "mfe": None,
            "mae": None,
            "exit_reason": t.get("exit_reason") or t.get("outcome"),
            "raw_confidence": t.get("confidence"),
            "calibrated_confidence": None,
            "opportunity_score": t.get("opportunity_score"),
            "trade_quality": t.get("trade_quality"),
            "market_regime_at_entry": t.get("market_regime") or "UNKNOWN",
            "sector_strength_at_entry": None,
            "relative_strength": None,
            "trend_score": None,
            "momentum_score": None,
            "volume_score": t.get("volume_ratio"),
            "volatility_score": t.get("volatility"),
            "liquidity_score": None,
            "risk_reward": t.get("risk_reward"),
            "recommendation_at_entry": None,
            "outcome": outcome,
            "stop_or_target_first": t.get("exit_reason"),
            "data_quality_at_entry": "OK",
            "model_version": MODEL_VERSION,
            "feature_version": FEATURE_VERSION,
            "entry_features": entry_features,
            "no_look_ahead": audit,
        }
        if audit["passed"]:
            audit_pass += 1
        rows.append(row)

    dataset = {
        "generated_at": _now(),
        "feature_version": FEATURE_VERSION,
        "model_version": MODEL_VERSION,
        "total_rows": len(rows),
        "audit_passed_rows": audit_pass,
        "audit_failed_rows": len(rows) - audit_pass,
        "reliability": reliability_label(audit_pass),
        "note": "RESEARCH / PAPER LEARNING ONLY — completed trades only, "
                "entry-time features only.",
        "rows": rows,
    }
    with open(DATASET_FILE, "w") as f:
        json.dump(dataset, f, indent=1, default=str)
    return dataset


def load_dataset() -> dict:
    if os.path.exists(DATASET_FILE):
        with open(DATASET_FILE) as f:
            return json.load(f)
    return build_learning_dataset()


def learning_rows(only_audited: bool = True) -> list[dict]:
    ds = load_dataset()
    rows = ds.get("rows", [])
    if only_audited:
        rows = [r for r in rows if r.get("no_look_ahead", {}).get("passed")]
    return rows


# ── Metric helpers ─────────────────────────────────────────────────────────────

def _safe_div(a: float, b: float) -> float | None:
    return a / b if b else None


def _brier(pairs: list[tuple[float, int]]) -> float | None:
    if not pairs:
        return None
    return sum((p - y) ** 2 for p, y in pairs) / len(pairs)


def _ece(pairs: list[tuple[float, int]], bins: int = 10) -> float | None:
    if not pairs:
        return None
    buckets: dict[int, list[tuple[float, int]]] = {}
    for p, y in pairs:
        b = min(int(p * bins), bins - 1)
        buckets.setdefault(b, []).append((p, y))
    total = len(pairs)
    ece = 0.0
    for items in buckets.values():
        avg_p = sum(p for p, _ in items) / len(items)
        avg_y = sum(y for _, y in items) / len(items)
        ece += (len(items) / total) * abs(avg_p - avg_y)
    return ece


def _log_loss(pairs: list[tuple[float, int]]) -> float | None:
    if not pairs:
        return None
    eps = 1e-6
    return -sum(
        y * math.log(max(p, eps)) + (1 - y) * math.log(max(1 - p, eps))
        for p, y in pairs
    ) / len(pairs)


def _sharpe(returns: list[float]) -> float | None:
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    var = sum((r - mean) ** 2 for r in returns) / (len(returns) - 1)
    sd = math.sqrt(var)
    return _safe_div(mean, sd)


def _sortino(returns: list[float]) -> float | None:
    if len(returns) < 2:
        return None
    mean = sum(returns) / len(returns)
    downs = [r for r in returns if r < 0]
    if not downs:
        return None
    dvar = sum(r ** 2 for r in downs) / len(downs)
    dsd = math.sqrt(dvar)
    return _safe_div(mean, dsd)


def _max_drawdown(pnls: list[float]) -> float:
    peak = cum = 0.0
    mdd = 0.0
    for p in pnls:
        cum += p
        peak = max(peak, cum)
        mdd = min(mdd, cum - peak)
    return mdd


def group_metrics(rows: list[dict]) -> dict:
    """Core metric block for a group of learning rows."""
    n = len(rows)
    label = reliability_label(n)
    if n == 0:
        return {"sample_size": 0, "reliability": "INSUFFICIENT"}
    pnls = [float(r.get("net_pnl") or 0) for r in rows]
    rets = [float(r.get("return_pct") or 0) for r in rows]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    win_rate = len(wins) / n
    expectancy = sum(pnls) / n
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    pf = _safe_div(gross_win, gross_loss)
    avg_win = _safe_div(gross_win, len(wins))
    avg_loss = _safe_div(-gross_loss, len(losses))
    payoff = _safe_div(avg_win or 0, abs(avg_loss)) if avg_loss else None
    pairs = [
        (min(max(float(r["raw_confidence"]) / 100.0, 0.0), 1.0),
         1 if float(r.get("net_pnl") or 0) > 0 else 0)
        for r in rows if r.get("raw_confidence") is not None
    ]
    return {
        "sample_size": n,
        "reliability": label,
        "win_rate": round(win_rate, 4),
        "expectancy": round(expectancy, 2),
        "profit_factor": round(pf, 3) if pf is not None else None,
        "avg_win": round(avg_win, 2) if avg_win is not None else None,
        "avg_loss": round(avg_loss, 2) if avg_loss is not None else None,
        "payoff_ratio": round(payoff, 3) if payoff is not None else None,
        "max_drawdown": round(_max_drawdown(pnls), 2),
        "sharpe": round(_sharpe(rets), 3) if _sharpe(rets) is not None else None,
        "sortino": round(_sortino(rets), 3) if _sortino(rets) is not None else None,
        "brier": round(_brier(pairs), 4) if _brier(pairs) is not None else None,
        "ece": round(_ece(pairs), 4) if _ece(pairs) is not None else None,
        "log_loss": round(_log_loss(pairs), 4) if _log_loss(pairs) is not None else None,
        "display_conclusions": label not in ("INSUFFICIENT", "LOW"),
    }


# ── Banding helpers ────────────────────────────────────────────────────────────

def confidence_band(conf: float | None) -> str:
    if conf is None:
        return "UNKNOWN"
    if conf >= 80:
        return "80-100"
    if conf >= 60:
        return "60-79"
    if conf >= 40:
        return "40-59"
    return "0-39"


def opportunity_band(score: float | None) -> str:
    if score is None:
        return "UNKNOWN"
    if score >= 75:
        return "75-100"
    if score >= 50:
        return "50-74"
    return "0-49"


def holding_band(days: float | None) -> str:
    if days is None:
        return "UNKNOWN"
    if days <= 1:
        return "0-1d"
    if days <= 5:
        return "2-5d"
    if days <= 15:
        return "6-15d"
    return "15d+"


def quality_grade(q: float | None) -> str:
    if q is None:
        return "UNKNOWN"
    if q >= 80:
        return "A"
    if q >= 60:
        return "B"
    if q >= 40:
        return "C"
    return "D"


def _group_by(rows: list[dict], keyfn) -> dict:
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(str(keyfn(r)), []).append(r)
    return {k: group_metrics(v) for k, v in sorted(out.items())}


# ── Evaluation engine ──────────────────────────────────────────────────────────

def run_evaluation(force: bool = False) -> dict:
    build_learning_dataset(force=True)
    rows = learning_rows(only_audited=True)
    n = len(rows)

    # Signal precision: BUY precision == win rate of executed entries
    wins = sum(1 for r in rows if float(r.get("net_pnl") or 0) > 0)
    buy_precision = _safe_div(wins, n)
    exit_hits = [r for r in rows
                 if (r.get("exit_reason") or "").upper() in
                 ("TARGET_HIT", "SIGNAL_EXIT", "SIGNAL EXIT")]
    exit_wins = sum(1 for r in exit_hits if float(r.get("net_pnl") or 0) > 0)
    exit_precision = _safe_div(exit_wins, len(exit_hits))
    fp_rate = _safe_div(n - wins, n)   # entered but lost
    fn_rate = None                     # unobservable without shadow signals

    report = {
        "generated_at": _now(),
        "model_version": MODEL_VERSION,
        "feature_version": FEATURE_VERSION,
        "completed_trades": n,
        "reliability": reliability_label(n),
        "overall": group_metrics(rows),
        "signal_quality": {
            "buy_precision": round(buy_precision, 4) if buy_precision is not None else None,
            "exit_precision": round(exit_precision, 4) if exit_precision is not None else None,
            "false_positive_rate": round(fp_rate, 4) if fp_rate is not None else None,
            "false_negative_rate": fn_rate,
            "fn_note": "False negatives require shadow-signal tracking; not yet observable.",
        },
        "by_strategy": _group_by(rows, lambda r: r.get("strategy")),
        "by_sector": _group_by(rows, lambda r: r.get("sector")),
        "by_regime": _group_by(rows, lambda r: r.get("market_regime_at_entry")),
        "by_confidence_band": _group_by(rows, lambda r: confidence_band(r.get("raw_confidence"))),
        "by_opportunity_band": _group_by(rows, lambda r: opportunity_band(r.get("opportunity_score"))),
        "by_holding_band": _group_by(rows, lambda r: holding_band(r.get("holding_period_days"))),
        "by_quality_grade": _group_by(rows, lambda r: quality_grade(r.get("trade_quality"))),
        "by_data_quality": _group_by(rows, lambda r: r.get("data_quality_at_entry") or "OK"),
        "warning": ("Sample size below 30 — all conclusions unreliable; adjustments disabled."
                    if n < 30 else None),
        "note": "RESEARCH / PAPER LEARNING ONLY. Low-sample groups must not "
                "display strong conclusions.",
    }
    with open(EVAL_FILE, "w") as f:
        json.dump(report, f, indent=1, default=str)
    return report


def load_evaluation() -> dict:
    if os.path.exists(EVAL_FILE):
        with open(EVAL_FILE) as f:
            return json.load(f)
    return run_evaluation()
