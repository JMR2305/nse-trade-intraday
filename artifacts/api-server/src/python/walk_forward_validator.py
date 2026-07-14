"""
walk_forward_validator.py — v2.4 Walk-Forward Validation.

Tests the complete Trade Decision Engine on unseen historical periods with
realistic execution assumptions (execution_simulator) and honest metrics
(validation_metrics).

Walk-forward structure: rolling train (1/2/3y) → test (1/3/6mo) → step
(1/3mo) windows until the dataset ends.

Strict data separation:
  - Strategy performance ("Pattern Quality") is computed from TRAINING
    window bars only.
  - Historical Knowledge / similarity / adaptive-learning inputs are
    filtered to trades fully exited BEFORE each decision day.
  - Indicators are causal (EMA/RSI/MACD/ATR/ADX/supertrend) — computing them
    once over the full series and slicing rows <= day is lookahead-free.
  - The maximum data timestamp used is logged for every decision, and any
    violation (timestamp > decision day) is counted and reported.

Three model variants are replayed on the SAME unseen data:
  A — Base technical engine only
  B — A + Historical Pattern adjustment + Similarity adjustment
  C — Full model: B + adaptive model modifier + Portfolio Manager rules

No mock or synthetic data — real candles or fail loudly. Deterministic and
reproducible (seeded RNG for the random benchmark; version-pinned adaptive
model weights for the whole run).

PAPER TRADING AND RESEARCH ONLY — no real orders are ever placed.
"""

from __future__ import annotations

import json
import os
import random
import time
import csv as _csv
from collections import Counter as _Counter
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta

import pandas as pd

from config import (
    NIFTY_50, INITIAL_CAPITAL, MAX_CAPITAL_PER_TRADE_PCT,
)
from market_replay import _fetch_raw_df
from indicator_engine import compute_indicators_df
from strategies import get_strategy, LAB_STRATEGY_IDS
from backtesting_engine import _run_lab_walk, WARMUP_BARS
from market_scanner import (
    _sector_of, _final_action, _strategy_perf_score, _confidence_score,
    _opportunity_score,
)
from execution_simulator import (
    CostModel, side_costs, effective_buy_price, effective_sell_price,
    simulate_entry, evaluate_exit_candle, build_trade_record,
    INTRABAR_CONSERVATIVE, INTRABAR_OPTIMISTIC, INTRABAR_RULE_LABELS,
    EXIT_SIGNAL, EXIT_TIME, EXIT_FORCED,
)
import validation_metrics as vm
from strategy_intelligence import (
    StrategyIntelligence, classify_regime, MAX_STRATEGY_ALLOC,
    GATES_DEFAULT, GATES_STRICT, ST_ENABLED,
    trades_from_knowledge as intel_trades_from_knowledge,
)

SAFETY_MESSAGE = ("Out-of-sample historical performance does not guarantee "
                  "future results. Paper trading and research only.")

VALIDATION_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "validation_runs")
STATUS_PATH = os.path.join(VALIDATION_DIR, "wf_status.json")
RESULT_PATH = os.path.join(VALIDATION_DIR, "wf_result.json")

CSV_FILES = {
    "report": "wf_report.csv",
    "trades": "wf_trades.csv",
    "windows": "wf_windows.csv",
    "calibration": "wf_calibration.csv",
    "costs": "wf_costs.csv",
    "evidence_report": "wf_evidence_report.csv",
    "evidence_trades": "wf_evidence_trades.csv",
}

VARIANT_LABELS = {
    "A": "A — Base technical engine only",
    "B": "B — Technical + Historical Pattern + Similarity",
    "C": "C — Full model (adaptive learning + portfolio manager)",
    "D": "D — Corrected gated ranking + edge-weighted allocation (Phase 2A)",
    "E": "E — Strict gates: cash when no strategy qualifies (Phase 2A)",
}

# Variants that run the FULL model pipeline (calibration, model weights,
# portfolio-manager caps). C uses the legacy strategy-intelligence policy;
# D/E use the corrected gated policy (default / strict gates).
FULL_VARIANTS = ("C", "D", "E")

# Portfolio Manager limits (imported values, applied — never modified here)
try:
    from portfolio_manager import MAX_STOCK_PCT, MAX_SECTOR_PCT, MAX_NEW_POSITIONS
except Exception:  # pragma: no cover — keep validator usable standalone
    MAX_STOCK_PCT, MAX_SECTOR_PCT, MAX_NEW_POSITIONS = 0.20, 0.30, 5

MAX_OPEN_POSITIONS_SIMPLE = 5   # slot rule for variants A and B

_REC_DOWNGRADE_CONF = 55.0      # adjusted confidence below this downgrades BUY→WATCH


# ── Config ───────────────────────────────────────────────────────────────────

@dataclass
class ValidationConfig:
    train_years: int = 1                # 1 | 2 | 3
    test_months: int = 3                # 1 | 3 | 6
    step_months: int = 3                # 1 | 3
    start_date: str = ""                # first TRAIN start (auto if empty)
    end_date: str = ""                  # last TEST end (auto: today)
    initial_capital: float = INITIAL_CAPITAL
    universe: list = field(default_factory=list)        # [] → NIFTY 50
    universe_size: int = 0                              # >0 → first N of universe
    strategy_set: list = field(default_factory=list)    # [] → all lab strategies
    cost_model: dict = field(default_factory=dict)
    intrabar_rule: str = INTRABAR_CONSERVATIVE
    max_holding_days: int = 20
    min_confidence_execute: float = 55.0
    min_calibrated_prob: float = 0.30   # calibrated win-probability floor (variant C)
    verdict_criteria: dict = field(default_factory=dict)
    random_seed: int = 42

    @classmethod
    def from_dict(cls, d: dict | None) -> "ValidationConfig":
        cfg = cls()
        if not d:
            return cfg
        for k, v in d.items():
            if hasattr(cfg, k) and v is not None:
                setattr(cfg, k, v)
        cfg.train_years = int(cfg.train_years) if int(cfg.train_years) in (1, 2, 3) else 1
        cfg.test_months = int(cfg.test_months) if int(cfg.test_months) in (1, 3, 6) else 3
        cfg.step_months = int(cfg.step_months) if int(cfg.step_months) in (1, 3) else 3
        if cfg.intrabar_rule not in (INTRABAR_CONSERVATIVE, INTRABAR_OPTIMISTIC):
            cfg.intrabar_rule = INTRABAR_CONSERVATIVE
        cfg.initial_capital = float(cfg.initial_capital)
        cfg.max_holding_days = max(1, int(cfg.max_holding_days))
        cfg.min_confidence_execute = float(cfg.min_confidence_execute)
        cfg.min_calibrated_prob = max(0.0, min(1.0, float(cfg.min_calibrated_prob)))
        cfg.random_seed = int(cfg.random_seed)
        cfg.universe = [str(s).upper() for s in (cfg.universe or [])]
        cfg.strategy_set = [str(s) for s in (cfg.strategy_set or [])]
        return cfg

    def to_dict(self) -> dict:
        return asdict(self)


# ── Window generation ────────────────────────────────────────────────────────

def _add_months(d: datetime, months: int) -> datetime:
    y = d.year + (d.month - 1 + months) // 12
    m = (d.month - 1 + months) % 12 + 1
    day = min(d.day, [31, 29 if y % 4 == 0 and (y % 100 != 0 or y % 400 == 0) else 28,
                      31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1])
    return datetime(y, m, day)


def generate_windows(start_date: str, end_date: str,
                     train_years: int, test_months: int, step_months: int) -> list[dict]:
    """
    Rolling windows: train [start, start+train_years) then test
    [train_end, train_end+test_months). Slide by step_months until the test
    window would run past end_date.
    """
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    windows = []
    train_start = start
    idx = 1
    while True:
        train_end = _add_months(train_start, train_years * 12) - timedelta(days=1)
        test_start = train_end + timedelta(days=1)
        test_end = _add_months(test_start, test_months) - timedelta(days=1)
        if test_end > end:
            break
        windows.append({
            "window": idx,
            "label": f"W{idx}",
            "train_start": train_start.strftime("%Y-%m-%d"),
            "train_end": train_end.strftime("%Y-%m-%d"),
            "test_start": test_start.strftime("%Y-%m-%d"),
            "test_end": test_end.strftime("%Y-%m-%d"),
        })
        train_start = _add_months(train_start, step_months)
        idx += 1
    return windows


# ── Status file ──────────────────────────────────────────────────────────────

def _write_status(payload: dict) -> None:
    os.makedirs(VALIDATION_DIR, exist_ok=True)
    payload = dict(payload)
    payload["updated_at"] = datetime.now().isoformat(timespec="seconds")
    tmp = STATUS_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f)
    os.replace(tmp, STATUS_PATH)


def read_status() -> dict:
    if not os.path.exists(STATUS_PATH):
        return {"status": "idle"}
    try:
        with open(STATUS_PATH) as f:
            return json.load(f)
    except Exception:
        return {"status": "idle"}


def read_result() -> dict:
    if not os.path.exists(RESULT_PATH):
        return {"available": False}
    try:
        with open(RESULT_PATH) as f:
            data = json.load(f)
        data["available"] = True
        return data
    except Exception as exc:
        return {"available": False, "error": str(exc)}


# ── Data prefetch ────────────────────────────────────────────────────────────

def _normalize_dates(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    idx = pd.to_datetime(df.index)
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_localize(None)
    df.index = idx.normalize()
    return df


def prefetch_symbol(symbol: str, start: str, end: str) -> pd.DataFrame:
    """
    One fetch per symbol for the whole run (real data or raise), indicators
    computed once (causal), rows returned with a tz-naive 'date' column.
    """
    raw = _fetch_raw_df(symbol, "1d", start=start, end=end)
    raw = _normalize_dates(raw)
    enriched = compute_indicators_df(raw)
    rows = enriched.reset_index()
    rows = rows.rename(columns={rows.columns[0]: "date"})
    return rows


def prefetch_index(start: str, end: str) -> pd.DataFrame:
    import yfinance as yf
    df = yf.Ticker("^NSEI").history(start=start, end=end, interval="1d")
    if df is None or df.empty:
        raise ValueError("No NIFTY 50 index data returned — cannot run validation")
    df = _normalize_dates(df)
    df = df[["Open", "High", "Low", "Close"]].rename(
        columns={"Open": "open", "High": "high", "Low": "low", "Close": "close"})
    return df[df["close"] > 0].sort_index()


def regime_as_of(nifty: pd.DataFrame, day: pd.Timestamp) -> str:
    """Same classification as signal_quality.get_market_regime_as_of, but on
    prefetched index candles (no per-day network call)."""
    close = nifty.loc[nifty.index <= day, "close"]
    if len(close) < 55:
        return "Unknown"
    ema20 = close.ewm(span=20, adjust=False).mean().iloc[-1]
    ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
    last = float(close.iloc[-1])
    ret5 = (last - float(close.iloc[-6])) / float(close.iloc[-6]) * 100.0
    if ema20 > ema50 and ret5 > 0.5:
        return "Bullish"
    if ema20 > ema50:
        return "Neutral-Bullish"
    if ret5 > 0:
        return "Neutral-Bearish"
    return "Bearish"


def regime7_as_of(nifty: pd.DataFrame, day: pd.Timestamp) -> str:
    """Phase 2: classify into the 7 canonical regimes using ONLY index
    candles up to and including `day` (no lookahead)."""
    span = nifty.loc[nifty.index <= day]
    if len(span) < 55:
        return "Sideways"
    span = span.tail(80)
    return classify_regime(
        [float(c) for c in span["close"]],
        [float(h) for h in span["high"]] if "high" in span.columns else None,
        [float(l) for l in span["low"]] if "low" in span.columns else None,
    )


# ── Forward evaluation (outcome analysis only — never used for decisions) ────

def forward_eval(rows: pd.DataFrame, day_pos: int) -> dict:
    """Forward returns 1/3/5/10/15/20/30 trading days after row `day_pos`,
    plus MAE/MFE over the 20-day forward window (vs that day's close)."""
    base_close = float(rows.iloc[day_pos]["close"])
    out = {"forward_returns": {}, "mae_pct": None, "mfe_pct": None}
    if base_close <= 0:
        return out
    for h in (1, 3, 5, 10, 15, 20, 30):
        p = day_pos + h
        out["forward_returns"][str(h)] = (
            round((float(rows.iloc[p]["close"]) - base_close) / base_close * 100.0, 2)
            if p < len(rows) else None
        )
    fwd = rows.iloc[day_pos + 1: day_pos + 21]
    if len(fwd) > 0:
        out["mae_pct"] = round((float(fwd["low"].min()) - base_close) / base_close * 100.0, 2)
        out["mfe_pct"] = round((float(fwd["high"].max()) - base_close) / base_close * 100.0, 2)
    return out


# ── Learning-layer helpers (read-only; never mutate engine state) ────────────

def _load_learning_context() -> dict:
    """Load knowledge/vectors/model weights ONCE per run (version-pinned)."""
    ctx = {"knowledge": [], "vectors": [], "model_weights": None, "model_version": 0}
    try:
        from adaptive_learning import load_knowledge
        ctx["knowledge"] = load_knowledge()
    except Exception:
        pass
    try:
        from similarity_engine import load_historical_vectors
        ctx["vectors"] = load_historical_vectors()
    except Exception:
        pass
    try:
        from model_versioning import get_active_version
        active = get_active_version()
        ctx["model_weights"] = active.get("weights") or None
        ctx["model_version"] = int(active.get("version", 0) or 0)
    except Exception:
        pass
    return ctx


def _knowledge_before(knowledge: list[dict], day_str: str) -> list[dict]:
    """Only trades fully exited BEFORE the decision day (no lookahead)."""
    return [
        k for k in knowledge
        if str(k.get("exit_date") or "")[:10] and str(k.get("exit_date"))[:10] < day_str
    ]


def _pattern_adjustment(item: dict, knowledge_asof: list[dict], regime: str) -> tuple[float, dict]:
    """Historical Pattern adjustment (adaptive_learning), from as-of knowledge."""
    try:
        from adaptive_learning import (candidate_features, find_similar,
                                       pattern_stats, confidence_adjustment)
        ema_al = ("bullish" if (item.get("above_ema20") and item.get("above_ema50"))
                  else "bearish" if (not item.get("above_ema20") and not item.get("above_ema50"))
                  else "mixed")
        cand = candidate_features(
            item.get("best_strategy_id", ""), item.get("sector", ""), regime,
            item.get("rsi"), item.get("adx"), ema_al,
            item.get("volume_ratio"), item.get("rr_ratio"),
        )
        similar, _ctx = find_similar(cand, knowledge_asof)
        stats = pattern_stats(similar)
        adj, _note = confidence_adjustment(stats)
        return float(adj), stats
    except Exception:
        return 0.0, {}


def _similarity_adjustment(
    item: dict, vectors: list[dict], regime: str, day_str: str,
) -> tuple[float, str]:
    """Similarity adjustment with as_of filtering (no current/future trades).
    Returns (adjustment, newest exit_date among the matches actually used) so
    the lookahead audit can verify the similarity path independently."""
    try:
        from similarity_engine import (
            extract_current_features, find_matches, evidence_stats,
            classify_reliability, confidence_adjustment,
        )
        cur = extract_current_features(item, regime_now=regime)
        matches, missing = find_matches(cur, vectors, as_of=day_str)
        stats = evidence_stats(matches)
        reliability, _reasons = classify_reliability(stats, matches, missing)
        adj, _expl = confidence_adjustment(stats, reliability)
        used_max = max(
            (str(m.get("exit_date") or "")[:10] for m in matches
             if str(m.get("exit_date") or "")[:10]),
            default="",
        )
        return float(adj or 0.0), used_max
    except Exception:
        return 0.0, ""


def _audit_decision(lookahead_log: dict, day_str: str, bar_ts: str,
                    knowledge_max_ts: str, sim_max_ts: str) -> bool:
    """Record one decision in the lookahead audit and flag violations.

    Rules (spec §no-lookahead):
      • the newest candle used may be AT MOST the decision day (same-day close);
      • knowledge trades (pattern path) must have fully exited BEFORE the day;
      • similarity matches used must have fully exited BEFORE the day.
    Returns True when the decision violated any rule."""
    lookahead_log["decisions"] = lookahead_log.get("decisions", 0) + 1
    violated = (
        bar_ts > day_str
        or (knowledge_max_ts != "" and knowledge_max_ts >= day_str)
        or (sim_max_ts != "" and sim_max_ts >= day_str)
    )
    lookahead_log["violations"] = (
        lookahead_log.get("violations", 0) + (1 if violated else 0))
    lookahead_log["max_timestamp"] = max(
        lookahead_log.get("max_timestamp", ""), bar_ts)
    lookahead_log["max_knowledge_timestamp"] = max(
        lookahead_log.get("max_knowledge_timestamp", ""), knowledge_max_ts)
    lookahead_log["max_similarity_timestamp"] = max(
        lookahead_log.get("max_similarity_timestamp", ""), sim_max_ts)
    return violated


def _model_adjustment(item: dict, regime: str, fc: float, weights: dict | None) -> float:
    if not weights:
        return 0.0
    try:
        from model_versioning import modifier_for, confidence_band
        from predictive_intelligence import rsi_bucket, adx_bucket, volume_bucket
        adj, _scopes = modifier_for({
            "strategy_id": item.get("best_strategy_id", ""),
            "symbol": item.get("stock", ""),
            "sector": item.get("sector", ""),
            "regime": regime,
            "pattern": (f"{item.get('best_strategy_name', '')} · "
                        f"{item.get('sector', '')} · {item.get('best_regime', '')}"),
            "confidence_band": confidence_band(fc),
            "rsi_band": rsi_bucket(item.get("rsi")),
            "adx_band": adx_bucket(item.get("adx")),
            "volume_band": volume_bucket(item.get("volume_ratio")),
            "volatility_regime": "",
        }, weights)
        return float(adj)
    except Exception:
        return 0.0


# ── Per-window strategy training ─────────────────────────────────────────────

def train_strategies(
    sym_rows: dict, window: dict, strategy_set: list[str], capital: float,
) -> dict:
    """
    Pick the best strategy per symbol using ONLY training-window bars
    (Pattern Quality from training data — spec §3). Returns
    {sym: {strategy_id, strategy, perf, metrics}}.
    """
    t_start = pd.Timestamp(window["train_start"])
    t_end = pd.Timestamp(window["train_end"])
    out = {}
    for sym, rows in sym_rows.items():
        train = rows[(rows["date"] >= t_start) & (rows["date"] <= t_end)]
        if len(train) < WARMUP_BARS + 10:
            continue
        train = train.reset_index(drop=True)
        best = None
        for sid in strategy_set:
            try:
                strategy = get_strategy(sid)
                metrics = _run_lab_walk(train, strategy, capital)
                perf = _strategy_perf_score(metrics)
            except Exception:
                continue
            if best is None or perf > best["perf"]:
                best = {"strategy_id": sid, "strategy": strategy,
                        "perf": perf, "metrics": metrics}
        if best is not None:
            out[sym] = best
    return out


# ── Daily signal generation ──────────────────────────────────────────────────

def build_day_item(
    sym: str, rows: pd.DataFrame, day_pos: int, trained: dict,
) -> dict | None:
    """Technical (variant A) signal for one symbol on one test day, using
    ONLY rows up to day_pos. Returns None when the symbol didn't trade."""
    if day_pos < WARMUP_BARS + 5:
        return None
    last = rows.iloc[day_pos]
    prev = rows.iloc[day_pos - 1]
    price = float(last.get("close", 0.0) or 0.0)
    if price <= 0:
        return None
    strategy = trained["strategy"]
    metrics = trained["metrics"]
    perf = trained["perf"]
    try:
        live_ok, reason = strategy.check_entry(last, prev)
    except Exception:
        live_ok, reason = False, ""
    confidence = _confidence_score(perf, metrics.get("total_trades", 0), live_ok)
    try:
        stop_loss = float(strategy.compute_stop_loss(last, price))
        target = float(strategy.compute_target(price, stop_loss))
    except Exception:
        stop_loss, target = 0.0, 0.0
    risk = max(0.0, price - stop_loss) if stop_loss > 0 else 0.0
    reward = max(0.0, target - price) if target > 0 else 0.0
    rr = round(reward / risk, 2) if risk > 0 else 0.0
    opp = _opportunity_score(perf, confidence, rr, live_ok)
    action = _final_action(opp)

    max_ts = str(last["date"])[:10]
    return {
        "stock": sym,
        "sector": _sector_of(sym),
        "price": price,
        "best_strategy_id": trained["strategy_id"],
        "best_strategy_name": strategy.name,
        "best_regime": getattr(strategy, "best_regime", ""),
        "live_signal": bool(live_ok),
        "entry_reason": reason or "",
        "confidence": confidence,
        "base_confidence": confidence,
        "trade_quality": perf,
        "opportunity_score": opp,
        "technical_action": action,
        "stop_loss": round(stop_loss, 2),
        "target": round(target, 2),
        "rr_ratio": rr,
        "entry_price": price,
        "expected_holding_days": 0.0,
        # indicator snapshot (as-of)
        "rsi": float(last.get("rsi", 0.0) or 0.0),
        "adx": float(last.get("adx", 0.0) or 0.0),
        "macd_line": float(last.get("macd_line", 0.0) or 0.0),
        "macd_signal": float(last.get("macd_signal", 0.0) or 0.0),
        "macd_hist": float(last.get("macd_hist", 0.0) or 0.0),
        "ema9": float(last.get("ema9", 0.0) or 0.0),
        "ema20": float(last.get("ema20", 0.0) or 0.0),
        "ema50": float(last.get("ema50", 0.0) or 0.0),
        "ema200": float(last.get("ema200", 0.0) or 0.0),
        "vwap": float(last.get("vwap", 0.0) or 0.0),
        "supertrend": float(last.get("supertrend", 0.0) or 0.0),
        "atr": float(last.get("atr", 0.0) or 0.0),
        "volume_ratio": float(last.get("volume_ratio", 0.0) or 0.0),
        "above_ema20": bool(price > float(last.get("ema20", 0.0) or 0.0) > 0),
        "above_ema50": bool(price > float(last.get("ema50", 0.0) or 0.0) > 0),
        "max_data_timestamp": max_ts,
        "day_pos": day_pos,
        "error": None,
    }


def _recommendation_for(item: dict, variant: str, final_conf: float) -> str:
    """Map technical action + adjusted confidence to a recommendation.
    Adjustments can only DOWNGRADE a buy (mirrors the live guard that
    learning can never create a BUY on its own). IGNORE → AVOID."""
    action = item["technical_action"]
    if action in ("STRONG BUY", "BUY"):
        if variant != "A" and final_conf < _REC_DOWNGRADE_CONF:
            return "WATCH"
        return action
    if action == "WATCH":
        return "WATCH"
    return "AVOID"


# ── Portfolio simulation for one window / one variant ────────────────────────

def _passes_entry_gate(variant: str, final_conf: float,
                       cal_p: float | None, cfg) -> bool:
    """Entry gate for a BUY candidate. Variant A (base) has no confidence
    gate. Variants B/C require the raw-confidence floor; when a calibrated
    probability is present (variant C only), the calibrated floor must ALSO
    be met."""
    if variant == "A":
        return True
    if final_conf < cfg.min_confidence_execute:
        return False
    if cal_p is not None and cal_p < cfg.min_calibrated_prob:
        return False
    return True


def _would_be_outcome(item: dict, fe: dict) -> str:
    """Analysis-only estimate of what a REJECTED trade would have done,
    from forward MAE/MFE vs the proposed stop/target distances. Computed
    after the fact for diagnostics — never fed back into decisions."""
    price = float(item.get("price") or 0.0)
    stop = float(item.get("stop_loss") or 0.0)
    target = float(item.get("target") or 0.0)
    mae, mfe = fe.get("mae_pct"), fe.get("mfe_pct")
    if price <= 0 or mae is None:
        return "no forward data"
    stop_pct = (stop - price) / price * 100.0 if stop > 0 else None
    target_pct = (target - price) / price * 100.0 if target > 0 else None
    if stop_pct is not None and mae <= stop_pct:
        return f"would likely have hit stop ({stop_pct:.1f}%)"
    if target_pct is not None and mfe is not None and mfe >= target_pct:
        return f"would likely have hit target (+{target_pct:.1f}%)"
    fr = fe.get("forward_returns") or {}
    for h in ("20", "10", "5", "3", "1"):
        if fr.get(h) is not None:
            return f"held {h}d: {fr[h]:+.2f}% (no stop/target hit)"
    return "no forward data"


# Per-window cache for (pattern_adj, sim_adj, sim_max_ts) keyed by (day, symbol):
# identical inputs across variants B–E. Cleared at the start of every window.
_ADJ_CACHE: dict = {}


def simulate_window_variant(
    variant: str,
    window: dict,
    sym_rows: dict,
    date_pos: dict,           # {sym: {date_str: row position}}
    trained: dict,
    test_days: list[pd.Timestamp],
    nifty: pd.DataFrame,
    ctx: dict,
    cfg: ValidationConfig,
    cost_model: CostModel,
    record_recommendations: list | None = None,
    lookahead_log: dict | None = None,
    calibrator: dict | None = None,
    strategy_intel: StrategyIntelligence | None = None,
    intel_gates: dict | None = None,
    rejected_log: list | None = None,
    research_ledger: list | None = None,
) -> dict:
    """
    Day-by-day replay: exits first (stop/target intrabar, signal, time,
    forced close), then queued entries at today's open, then new
    recommendations from today's close (executed tomorrow — next-day-open
    entry, spec §5). Returns trades, daily equity curve, window metrics.
    """
    cash = cfg.initial_capital
    positions: dict[str, dict] = {}
    pending: list[dict] = []
    trades: list[dict] = []
    equity_curve: list[float] = []
    equity_dates: list[str] = []

    knowledge = ctx["knowledge"]
    vectors = ctx["vectors"]
    weights = ctx["model_weights"] if variant in FULL_VARIANTS else None

    max_open = (MAX_NEW_POSITIONS if variant in FULL_VARIANTS
                else MAX_OPEN_POSITIONS_SIMPLE)
    intel_regime_days: dict[str, int] = {}
    daily_cash_frac: list[float] = []   # cash / equity, per trading day

    for di, day in enumerate(test_days):
        day_str = day.strftime("%Y-%m-%d")
        is_last_day = di == len(test_days) - 1
        regime = regime_as_of(nifty, day)
        regime7 = None
        if strategy_intel is not None:
            regime7 = regime7_as_of(nifty, day)
            intel_regime_days[regime7] = intel_regime_days.get(regime7, 0) + 1

        # ── 1. Exits ────────────────────────────────────────────────────
        for sym in list(positions.keys()):
            pos = positions[sym]
            rows = sym_rows[sym]
            pos_idx = date_pos[sym].get(day_str)
            if pos_idx is None:
                if is_last_day:
                    # symbol didn't trade on final day — close at last known close
                    last_known = rows[rows["date"] <= day]
                    if len(last_known) == 0:
                        continue
                    lk = last_known.iloc[-1]
                    _close_position(trades, positions, cost_model, sym, pos,
                                    str(lk["date"])[:10], float(lk["close"]),
                                    EXIT_FORCED, cfg.intrabar_rule)
                    cash += trades[-1]["exit_price"] * trades[-1]["quantity"] - \
                        trades[-1]["sell_costs"]["total"]
                    if strategy_intel is not None:
                        # Adaptive learning: feed the COMPLETED out-of-sample
                        # trade back into the strategy intelligence.
                        strategy_intel.add_completed_trade(trades[-1])
                continue
            row = rows.iloc[pos_idx]
            candle = {"open": float(row["open"]), "high": float(row["high"]),
                      "low": float(row["low"]), "close": float(row["close"])}
            # excursions
            if pos["entry_price"] > 0:
                pos["mae_pct"] = min(pos["mae_pct"],
                                     (candle["low"] - pos["entry_price"]) / pos["entry_price"] * 100.0)
                pos["mfe_pct"] = max(pos["mfe_pct"],
                                     (candle["high"] - pos["entry_price"]) / pos["entry_price"] * 100.0)
            pos["holding_days"] += 1

            exited, raw_exit, reason, _both = evaluate_exit_candle(
                candle, pos["stop_loss"], pos["target"], cfg.intrabar_rule)
            if not exited:
                prev = rows.iloc[pos_idx - 1]
                try:
                    should_exit, _ = pos["strategy"].check_exit(
                        row, prev, pos["entry_price"], pos["stop_loss"], pos["target"])
                except Exception:
                    should_exit = False
                if should_exit:
                    exited, raw_exit, reason = True, candle["close"], EXIT_SIGNAL
                elif pos["holding_days"] >= cfg.max_holding_days:
                    exited, raw_exit, reason = True, candle["close"], EXIT_TIME
                elif is_last_day:
                    exited, raw_exit, reason = True, candle["close"], EXIT_FORCED
            if exited:
                _close_position(trades, positions, cost_model, sym, pos,
                                day_str, raw_exit, reason, cfg.intrabar_rule)
                cash += trades[-1]["exit_price"] * trades[-1]["quantity"] - \
                    trades[-1]["sell_costs"]["total"]
                if strategy_intel is not None:
                    # Adaptive learning from completed out-of-sample trades only
                    strategy_intel.add_completed_trade(trades[-1])
                # Record an EXIT recommendation for outcome analysis
                if record_recommendations is not None and reason == EXIT_SIGNAL:
                    fe = forward_eval(sym_rows[sym], date_pos[sym][day_str])
                    record_recommendations.append({
                        "recommendation": "EXIT", "symbol": sym, "date": day_str,
                        "forward_returns": fe["forward_returns"],
                        "mae_pct": fe["mae_pct"], "mfe_pct": fe["mfe_pct"],
                    })

        # ── 2. Entries queued yesterday, filled at TODAY's open ─────────
        if not is_last_day:  # entering on the forced-close day is pointless
            for rec in pending:
                sym = rec["stock"]
                _lr = rec.get("_ledger_row")  # research ledger (analysis only)
                if sym in positions or len(positions) >= max_open:
                    if _lr is not None:
                        _lr["stage"] = "rejected_position_limit"
                    continue
                pos_idx = date_pos[sym].get(day_str)
                if pos_idx is None:
                    if _lr is not None:
                        _lr["stage"] = "rejected_no_trading_day"
                    continue
                row = sym_rows[sym].iloc[pos_idx]
                candle = {"date": day_str, "open": float(row["open"]),
                          "high": float(row["high"]), "low": float(row["low"]),
                          "close": float(row["close"]), "volume": float(row["volume"])}
                total_equity = cash + sum(
                    p["quantity"] * _mark_price(sym_rows[s], date_pos[s], day)
                    for s, p in positions.items())
                alloc = _allocation_for(variant, rec, total_equity, positions,
                                        sym_rows, date_pos, day)
                if alloc <= 0:
                    if _lr is not None:
                        _lr["stage"] = "rejected_allocation_caps"
                    continue
                fill = simulate_entry(cost_model, candle, rec["price"], cash, alloc)
                if not fill.get("filled"):
                    if _lr is not None:
                        _lr["stage"] = "rejected_fill"
                    continue
                if _lr is not None:
                    _lr["stage"] = "entered"
                    _lr["entry_date"] = day_str
                    _lr["fill_price"] = fill["fill_price"]
                cash -= fill["cash_used"]
                positions[sym] = {
                    "entry_date": day_str,
                    "entry_price": fill["fill_price"],
                    "raw_open": fill["raw_open"],
                    "quantity": fill["quantity"],
                    "requested_quantity": fill["requested_quantity"],
                    "partial_fill": fill["partial_fill"],
                    "gap_pct": fill["gap_pct"],
                    "buy_costs": fill["buy_costs"],
                    "stop_loss": rec["stop_loss"],
                    "target": rec["target"],
                    "strategy": trained[sym]["strategy"],
                    "strategy_id": rec["best_strategy_id"],
                    "strategy_name": rec["best_strategy_name"],
                    "confidence": rec["final_confidence"],
                    "raw_confidence": rec.get("raw_confidence", rec["final_confidence"]),
                    "calibrated_probability": rec.get("calibrated_probability"),
                    "calibrated_confidence": rec.get("calibrated_confidence"),
                    "calibration_method": rec.get("calibration_method", ""),
                    "calibration_version": rec.get("calibration_version", 0),
                    "recommendation": rec["recommendation"],
                    "sector": rec["sector"],
                    "market_regime": rec["market_regime"],
                    "max_data_timestamp": rec["max_data_timestamp"],
                    "intel_regime": rec.get("intel_regime"),
                    "strategy_rank": rec.get("strategy_rank"),
                    "strategy_reason": rec.get("strategy_reason", ""),
                    "strategy_sizing_factor": rec.get("strategy_sizing_factor"),
                    "strategy_status": rec.get("strategy_status"),
                    "strategy_weight": rec.get("strategy_weight"),
                    "holding_days": 0,
                    "mae_pct": 0.0,
                    "mfe_pct": 0.0,
                }
        pending = []

        # ── 3. New recommendations from TODAY's close ────────────────────
        candidates = []
        if not is_last_day:
            knowledge_asof = _knowledge_before(knowledge, day_str) if variant != "A" else []
            # Newest exit_date in the knowledge actually handed to the
            # pattern-adjustment path (audited independently below).
            knowledge_max_ts = max(
                (str(k.get("exit_date") or "")[:10] for k in knowledge_asof
                 if str(k.get("exit_date") or "")[:10]),
                default="",
            )
            for sym, tr in trained.items():
                pos_idx = date_pos[sym].get(day_str)
                if pos_idx is None:
                    continue
                item = build_day_item(sym, sym_rows[sym], pos_idx, tr)
                if item is None:
                    continue

                fc = item["confidence"]
                pattern_adj = sim_adj = model_adj = 0.0
                sim_max_ts = ""
                if variant != "A":
                    # The pattern/similarity adjustments depend only on the
                    # (day, symbol) setup — identical across variants B–E, so
                    # cache them per window (major speedup on long runs).
                    _ck = (day_str, sym)
                    _hit = _ADJ_CACHE.get(_ck)
                    if _hit is None:
                        pattern_adj, _stats = _pattern_adjustment(item, knowledge_asof, regime)
                        sim_adj, sim_max_ts = _similarity_adjustment(item, vectors, regime, day_str)
                        _ADJ_CACHE[_ck] = (pattern_adj, sim_adj, sim_max_ts)
                    else:
                        pattern_adj, sim_adj, sim_max_ts = _hit
                if variant in FULL_VARIANTS:
                    model_adj = _model_adjustment(item, regime, fc, weights)

                # Lookahead audit — covers EVERY data source in the decision:
                #   • technical bars: newest candle must be <= decision day
                #   • knowledge (pattern path): trades must have exited BEFORE day
                #   • similarity matches used: must have exited BEFORE day
                if lookahead_log is not None:
                    _audit_decision(lookahead_log, day_str,
                                    item["max_data_timestamp"],
                                    knowledge_max_ts, sim_max_ts)
                final_conf = round(max(5.0, min(95.0, fc + pattern_adj + model_adj + sim_adj)), 1)

                recommendation = _recommendation_for(item, variant, final_conf)
                item.update({
                    "pattern_adjustment": round(pattern_adj, 1),
                    "similarity_adjustment": round(sim_adj, 1),
                    "model_adjustment": round(model_adj, 1),
                    "final_confidence": final_conf,
                    "recommendation": recommendation,
                    "market_regime": regime,
                })

                # Confidence calibration (Phase 1) — the calibrator was fitted
                # ONLY from knowledge trades that exited before this window's
                # test start (no lookahead). Variant C filters and sizes on it.
                cal_p = None
                if calibrator is not None:
                    from confidence_calibration import calibrate_prediction
                    _cal = calibrate_prediction(calibrator, final_conf)
                    cal_p = _cal["calibrated_probability"]
                    item.update(_cal)

                if record_recommendations is not None:
                    fe = forward_eval(sym_rows[sym], pos_idx)
                    record_recommendations.append({
                        "recommendation": recommendation, "symbol": sym,
                        "date": day_str, "confidence": final_conf,
                        "forward_returns": fe["forward_returns"],
                        "mae_pct": fe["mae_pct"], "mfe_pct": fe["mfe_pct"],
                    })

                # ── Research ledger (ANALYSIS ONLY — never affects decisions).
                # One row per evaluated candidate with features, the gate
                # outcome and forward returns, consumed by strategy_analyzer.
                led = None
                if research_ledger is not None:
                    _fe = forward_eval(sym_rows[sym], pos_idx)
                    _price = float(item.get("price") or 0.0)
                    _atr = float(item.get("atr") or 0.0)
                    led = {
                        "window": window.get("label", ""),
                        "date": day_str, "symbol": sym,
                        "sector": item.get("sector", "OTHER"),
                        "strategy_id": item.get("best_strategy_id", ""),
                        "regime": regime,
                        "live_signal": bool(item.get("live_signal")),
                        "technical_action": item.get("technical_action", ""),
                        "recommendation": recommendation,
                        "base_confidence": item.get("base_confidence"),
                        "pattern_adjustment": item.get("pattern_adjustment", 0.0),
                        "similarity_adjustment": item.get("similarity_adjustment", 0.0),
                        "model_adjustment": item.get("model_adjustment", 0.0),
                        "final_confidence": final_conf,
                        "calibrated_probability": cal_p,
                        "opportunity_score": item.get("opportunity_score"),
                        "rr_ratio": item.get("rr_ratio"),
                        "rsi": item.get("rsi"), "adx": item.get("adx"),
                        "volume_ratio": item.get("volume_ratio"),
                        "atr_pct": round(_atr / _price * 100.0, 3) if _price > 0 and _atr > 0 else None,
                        "macd_state": ("BULLISH" if float(item.get("macd_line") or 0) >= float(item.get("macd_signal") or 0) else "BEARISH"),
                        "above_ema20": item.get("above_ema20"),
                        "above_ema50": item.get("above_ema50"),
                        "price": _price,
                        "stop_loss": item.get("stop_loss"),
                        "target": item.get("target"),
                        "stage": "not_buy_signal",
                        "entry_date": None, "fill_price": None,
                        "fwd_1": _fe["forward_returns"].get("1"),
                        "fwd_3": _fe["forward_returns"].get("3"),
                        "fwd_5": _fe["forward_returns"].get("5"),
                        "fwd_10": _fe["forward_returns"].get("10"),
                        "fwd_15": _fe["forward_returns"].get("15"),
                        "fwd_20": _fe["forward_returns"].get("20"),
                        "fwd_30": _fe["forward_returns"].get("30"),
                        "mae_pct": _fe["mae_pct"], "mfe_pct": _fe["mfe_pct"],
                    }
                    research_ledger.append(led)

                if recommendation in ("STRONG BUY", "BUY") and sym not in positions:
                    if not _passes_entry_gate(variant, final_conf, cal_p, cfg):
                        if led is not None:
                            if cal_p is not None and cal_p < cfg.min_calibrated_prob \
                                    and final_conf >= cfg.min_confidence_execute:
                                led["stage"] = "rejected_calibrated_prob"
                            elif (final_conf - float(item.get("similarity_adjustment") or 0.0)
                                  >= cfg.min_confidence_execute > final_conf):
                                # counterfactual: would have passed WITHOUT the
                                # (negative) similarity adjustment
                                led["stage"] = "rejected_confidence_similarity"
                            else:
                                led["stage"] = "rejected_confidence"
                        continue
                    # Phase 2: adaptive strategy selection — gate the entry on
                    # whether this strategy is enabled for the CURRENT regime,
                    # judged only from trades completed before this decision.
                    if strategy_intel is not None and regime7 is not None \
                            and intel_gates is None:
                        # Legacy policy (variant C — previous behavior).
                        sid = str(item.get("best_strategy_id", "")).lower()
                        rank_row = next(
                            (r for r in strategy_intel.rank_for_regime(regime7)
                             if r["strategy_id"] == sid), None)
                        item["intel_regime"] = regime7
                        item["strategy_rank"] = rank_row["rank"] if rank_row else None
                        item["strategy_enabled"] = rank_row["enabled"] if rank_row else True
                        item["strategy_reason"] = rank_row["reason"] if rank_row else ""
                        item["strategy_sizing_factor"] = (
                            strategy_intel.sizing_factor(sid, regime7))
                        if not item["strategy_enabled"]:
                            if led is not None:
                                led["stage"] = "rejected_strategy_gate"
                            continue  # strategy disabled in this regime
                    elif strategy_intel is not None and regime7 is not None:
                        # Phase 2A corrected policy (variants D/E): hard
                        # eligibility gates, no diversification floor. If the
                        # strategy is not ENABLED the trade is rejected and
                        # logged for diagnostics (analysis-only).
                        sid = str(item.get("best_strategy_id", "")).lower()
                        rank_row = next(
                            (r for r in strategy_intel.rank_gated(regime7, intel_gates)
                             if r["strategy_id"] == sid), None)
                        alloc_g = strategy_intel.gated_allocation(regime7, intel_gates)
                        item["intel_regime"] = regime7
                        item["strategy_rank"] = rank_row["rank"] if rank_row else None
                        item["strategy_status"] = rank_row["status"] if rank_row else "UNKNOWN"
                        item["strategy_enabled"] = bool(rank_row and rank_row["eligible"])
                        item["strategy_reason"] = rank_row["reason"] if rank_row else \
                            "Unknown strategy — no completed-trade history"
                        item["strategy_weight"] = alloc_g["weights"].get(sid, 0.0)
                        if not item["strategy_enabled"]:
                            if rejected_log is not None:
                                fe = forward_eval(sym_rows[sym], pos_idx)
                                rejected_log.append({
                                    "symbol": sym,
                                    "sector": item.get("sector", "OTHER"),
                                    "strategy_id": sid,
                                    "regime": regime7,
                                    "proposed_date": day_str,
                                    "status": item["strategy_status"],
                                    "rejection_reason": item["strategy_reason"],
                                    "raw_profit_factor": rank_row["raw_profit_factor"] if rank_row else None,
                                    "adjusted_profit_factor": rank_row["adjusted_profit_factor"] if rank_row else None,
                                    "raw_expectancy_pct": rank_row["raw_expectancy_pct"] if rank_row else None,
                                    "adjusted_expectancy_pct": rank_row["adjusted_expectancy_pct"] if rank_row else None,
                                    "sample": rank_row["sample"] if rank_row else 0,
                                    "confidence": final_conf,
                                    "would_be_outcome": _would_be_outcome(item, fe),
                                    "forward_returns": fe["forward_returns"],
                                })
                            if led is not None:
                                led["stage"] = "rejected_strategy_gate"
                            continue  # not eligible → hold cash instead
                    if led is not None:
                        led["stage"] = "candidate_pool"
                        item["_ledger_row"] = led
                    candidates.append(item)
                elif led is not None and recommendation in ("STRONG BUY", "BUY") \
                        and sym in positions:
                    led["stage"] = "already_in_position"

            candidates.sort(key=lambda it: (-it["final_confidence"],
                                            -it["opportunity_score"], it["stock"]))
            slots = max(0, max_open - len(positions))
            pending = candidates[:slots]
            if research_ledger is not None:
                for _pos_i, it in enumerate(candidates):
                    _lr = it.get("_ledger_row")
                    if _lr is not None:
                        _lr["stage"] = ("queued" if _pos_i < slots
                                        else "rejected_no_slot")

        # ── 4. Mark to market ────────────────────────────────────────────
        equity = cash
        for sym, pos in positions.items():
            equity += pos["quantity"] * _mark_price(sym_rows[sym], date_pos[sym], day)
        equity_curve.append(round(equity, 2))
        equity_dates.append(day_str)
        daily_cash_frac.append(cash / equity if equity > 0 else 1.0)

    metrics = vm.compute_performance_metrics(
        trades, cfg.initial_capital, equity_curve, trading_days=len(test_days))
    n_days = len(daily_cash_frac)
    cash_time_pct = round(sum(daily_cash_frac) / n_days * 100.0, 1) if n_days else 100.0
    full_cash_days_pct = round(
        sum(1 for c in daily_cash_frac if c >= 0.999) / n_days * 100.0, 1) if n_days else 100.0
    return {
        "variant": variant,
        "trades": trades,
        "equity_curve": equity_curve,
        "equity_dates": equity_dates,
        "metrics": metrics,
        "intel_regime_days": intel_regime_days,
        "cash_time_pct": cash_time_pct,        # avg fraction of equity in cash
        "full_cash_days_pct": full_cash_days_pct,  # % of days 100% in cash
    }


def _mark_price(rows: pd.DataFrame, dpos: dict, day: pd.Timestamp) -> float:
    idx = dpos.get(day.strftime("%Y-%m-%d"))
    if idx is not None:
        return float(rows.iloc[idx]["close"])
    older = rows[rows["date"] <= day]
    return float(older.iloc[-1]["close"]) if len(older) else 0.0


def _allocation_for(variant: str, rec: dict, total_equity: float,
                    positions: dict, sym_rows: dict, date_pos: dict,
                    day: pd.Timestamp) -> float:
    """A/B: flat 20% of equity. C/D/E: Portfolio Manager caps — 20% per
    stock, 30% per sector, confidence-scaled sizing. C tilts by the legacy
    sizing factor; D/E cap by the gated per-strategy capital budget
    (edge-weighted, max 40% per strategy — remainder stays in cash)."""
    if variant not in FULL_VARIANTS:
        return total_equity * MAX_CAPITAL_PER_TRADE_PCT
    stock_cap = total_equity * MAX_STOCK_PCT
    sector = rec.get("sector", "OTHER")
    sector_used = sum(
        p["quantity"] * _mark_price(sym_rows[s], date_pos[s], day)
        for s, p in positions.items() if p.get("sector") == sector
    )
    sector_room = total_equity * MAX_SECTOR_PCT - sector_used
    # Sizing uses the CALIBRATED confidence when available (Phase 1 calibration)
    conf = float(rec.get("calibrated_confidence")
                 if rec.get("calibrated_confidence") is not None
                 else rec.get("final_confidence", 50.0))
    conf_scale = max(0.5, min(1.0, conf / 100.0 + 0.25))
    alloc = max(0.0, min(stock_cap * conf_scale, sector_room))
    if variant == "C":
        # Phase 2 (legacy): dynamic allocation — tilt position size toward
        # strategies ranked higher for the current regime (factor bounded
        # [0.5, 1.5]). Re-clamp afterwards so the tilt can never break the
        # per-stock cap or the remaining sector room.
        sf = rec.get("strategy_sizing_factor")
        if sf is not None:
            alloc *= float(sf)
        return max(0.0, min(alloc, stock_cap, sector_room))
    # Phase 2A (D/E): the strategy's gated weight is a hard capital budget.
    # Capital already deployed to this strategy counts against the budget;
    # what the budget doesn't cover stays in cash.
    w = float(rec.get("strategy_weight") or 0.0)
    if w <= 0.0:
        return 0.0
    sid = str(rec.get("best_strategy_id", "")).lower()
    strategy_used = sum(
        p["quantity"] * _mark_price(sym_rows[s], date_pos[s], day)
        for s, p in positions.items()
        if str(p.get("strategy_id", "")).lower() == sid
    )
    strategy_room = total_equity * w - strategy_used
    return max(0.0, min(alloc, stock_cap, sector_room, strategy_room))


def _close_position(trades: list, positions: dict, cost_model: CostModel,
                    sym: str, pos: dict, day_str: str, raw_exit: float,
                    reason: str, intrabar_rule: str) -> None:
    sell_price = effective_sell_price(cost_model, raw_exit)
    sell_turnover = sell_price * pos["quantity"]
    sell_c = side_costs(cost_model, sell_turnover, "sell")
    entry = {
        "entry_date": pos["entry_date"], "raw_open": pos["raw_open"],
        "fill_price": pos["entry_price"], "quantity": pos["quantity"],
        "requested_quantity": pos["requested_quantity"],
        "partial_fill": pos["partial_fill"], "gap_pct": pos["gap_pct"],
        "buy_costs": pos["buy_costs"],
    }
    exit_info = {
        "exit_date": day_str, "raw_exit_price": round(raw_exit, 4),
        "sell_price": round(sell_price, 4), "exit_reason": reason,
        "holding_days": pos["holding_days"],
        "mae_pct": round(pos["mae_pct"], 2), "mfe_pct": round(pos["mfe_pct"], 2),
        "intrabar_rule": intrabar_rule,
        "intrabar_rule_label": INTRABAR_RULE_LABELS[intrabar_rule],
        "sell_turnover": round(sell_turnover, 2), "sell_costs": sell_c,
    }
    meta = {
        "confidence": pos["confidence"], "recommendation": pos["recommendation"],
        "raw_confidence": pos.get("raw_confidence", pos["confidence"]),
        "calibrated_probability": pos.get("calibrated_probability"),
        "calibrated_confidence": pos.get("calibrated_confidence"),
        "calibration_method": pos.get("calibration_method", ""),
        "calibration_version": pos.get("calibration_version", 0),
        "strategy_id": pos["strategy_id"], "strategy_name": pos["strategy_name"],
        "sector": pos["sector"], "market_regime": pos["market_regime"],
        "max_data_timestamp": pos["max_data_timestamp"],
        "intel_regime": pos.get("intel_regime"),
        "strategy_rank": pos.get("strategy_rank"),
        "strategy_sizing_factor": pos.get("strategy_sizing_factor"),
        "strategy_status": pos.get("strategy_status"),
        "strategy_weight": pos.get("strategy_weight"),
    }
    trades.append(build_trade_record(sym, entry, exit_info, meta))
    del positions[sym]


# ── Benchmarks ───────────────────────────────────────────────────────────────

def _index_return(nifty: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> float:
    span = nifty[(nifty.index >= start) & (nifty.index <= end)]
    if len(span) < 2:
        return 0.0
    return round((float(span["close"].iloc[-1]) - float(span["close"].iloc[0]))
                 / float(span["close"].iloc[0]) * 100.0, 2)


def _equal_weight_return(sym_rows: dict, start: pd.Timestamp, end: pd.Timestamp) -> float:
    rets = []
    for rows in sym_rows.values():
        span = rows[(rows["date"] >= start) & (rows["date"] <= end)]
        if len(span) < 2:
            continue
        first, last = float(span.iloc[0]["close"]), float(span.iloc[-1]["close"])
        if first > 0:
            rets.append((last - first) / first * 100.0)
    return round(sum(rets) / len(rets), 2) if rets else 0.0


def _rule_engine_return(sym_rows: dict, date_pos: dict, trained: dict,
                        test_days: list, cfg: ValidationConfig,
                        cost_model: CostModel) -> float:
    """Every technical BUY taken equal-weight (capital/5), no ranking, no
    learning, no portfolio caps — the raw rule engine."""
    capital = cfg.initial_capital
    pnl = 0.0
    alloc = capital / 5.0
    for sym, tr in trained.items():
        rows = sym_rows[sym]
        for di, day in enumerate(test_days[:-1]):
            day_str = day.strftime("%Y-%m-%d")
            pos_idx = date_pos[sym].get(day_str)
            if pos_idx is None or pos_idx + 1 >= len(rows):
                continue
            item = build_day_item(sym, rows, pos_idx, tr)
            if item is None or item["technical_action"] not in ("STRONG BUY", "BUY"):
                continue
            entry_candle = rows.iloc[pos_idx + 1]
            fill = simulate_entry(
                cost_model,
                {"date": str(entry_candle["date"])[:10],
                 "open": float(entry_candle["open"]), "high": float(entry_candle["high"]),
                 "low": float(entry_candle["low"]), "close": float(entry_candle["close"]),
                 "volume": float(entry_candle["volume"])},
                item["price"], alloc, alloc)
            if not fill.get("filled"):
                continue
            # walk to exit
            from execution_simulator import simulate_exit
            future = rows.iloc[pos_idx + 1:].copy()
            future = future.rename(columns={"date": "date"})
            future["date"] = future["date"].astype(str).str[:10]
            ex = simulate_exit(cost_model, future, fill["fill_price"],
                               item["stop_loss"], item["target"], fill["quantity"],
                               max_holding_days=cfg.max_holding_days,
                               intrabar_rule=cfg.intrabar_rule)
            tr_rec = build_trade_record(sym, fill, ex, {})
            pnl += tr_rec["net_pnl"]
            break  # one trade per symbol per window keeps this benchmark bounded
    return round(pnl / capital * 100.0, 2)


def _random_benchmark_return(model_trades: list[dict], sym_rows: dict,
                             date_pos: dict, cfg: ValidationConfig,
                             cost_model: CostModel, rng: random.Random) -> float:
    """Stock-selection skill control: for each full-model trade, buy a RANDOM
    other symbol on the same entry day, hold the same number of days."""
    if not model_trades:
        return 0.0
    symbols = sorted(sym_rows.keys())
    capital = cfg.initial_capital
    pnl = 0.0
    for t in model_trades:
        sym = rng.choice(symbols)
        rows = sym_rows[sym]
        pos_idx = date_pos[sym].get(str(t["entry_date"])[:10])
        if pos_idx is None:
            continue
        buy_px = effective_buy_price(cost_model, float(rows.iloc[pos_idx]["open"]))
        qty = int(float(t["invested"]) // buy_px)
        if qty <= 0:
            continue
        exit_pos = min(pos_idx + max(1, int(t["holding_days"])), len(rows) - 1)
        sell_px = effective_sell_price(cost_model, float(rows.iloc[exit_pos]["close"]))
        bc = side_costs(cost_model, buy_px * qty, "buy")
        sc = side_costs(cost_model, sell_px * qty, "sell")
        pnl += (sell_px - buy_px) * qty - bc["total"] - sc["total"]
    return round(pnl / capital * 100.0, 2)


# ── Cost breakdown aggregation ───────────────────────────────────────────────

def aggregate_costs(trades: list[dict]) -> dict:
    agg = {"brokerage": 0.0, "stt": 0.0, "exchange": 0.0, "sebi": 0.0,
           "stamp_duty": 0.0, "gst": 0.0, "slippage_and_spread": 0.0}
    gross = net = 0.0
    for t in trades:
        for side in ("buy_costs", "sell_costs"):
            c = t.get(side, {})
            for k in ("brokerage", "stt", "exchange", "sebi", "stamp_duty", "gst"):
                agg[k] += float(c.get(k, 0.0))
        slip = (float(t.get("entry_price", 0.0)) - float(t.get("raw_open", 0.0))) * t.get("quantity", 0)
        slip += (float(t.get("raw_exit_price", 0.0)) - float(t.get("exit_price", 0.0))) * t.get("quantity", 0)
        agg["slippage_and_spread"] += slip
        gross += float(t.get("gross_pnl", 0.0))
        net += float(t.get("net_pnl", 0.0))
    agg = {k: round(v, 2) for k, v in agg.items()}
    agg["total"] = round(sum(agg.values()), 2)
    agg["gross_pnl"] = round(gross, 2)
    agg["net_pnl"] = round(net, 2)
    agg["cost_drag"] = round(gross - net, 2)
    return agg


def _phase2a_report(overall: dict, layer_comparison: list,
                    rejected_trades: list) -> dict:
    """Phase 2A analysis report (§11): compares the legacy ranking policy
    (variant C) against the corrected gated policy (D) and strict gates (E),
    summarizes rejected-trade diagnostics, and gives a deployment
    recommendation. ANALYSIS ONLY — nothing here changes the live pipeline."""
    rows = {r["variant"]: r for r in layer_comparison}
    c, d, e = rows.get("C", {}), rows.get("D", {}), rows.get("E", {})

    # Rejected-trades diagnostic: how often the gate was RIGHT to reject.
    rej = rejected_trades
    n_rej = len(rej)
    saved = hurt = unknown = 0
    for rt in rej:
        out = rt.get("would_be_outcome", "")
        if out.startswith("would likely have hit stop"):
            saved += 1
        elif out.startswith("would likely have hit target"):
            hurt += 1
        elif out.startswith("held"):
            try:
                val = float(out.split(":")[1].split("%")[0])
                if val < 0:
                    saved += 1
                elif val > 0:
                    hurt += 1
                else:
                    unknown += 1
            except (ValueError, IndexError):
                unknown += 1
        else:
            unknown += 1
    by_status: dict[str, int] = {}
    by_strategy: dict[str, int] = {}
    for rt in rej:
        by_status[rt.get("status", "UNKNOWN")] = by_status.get(rt.get("status", "UNKNOWN"), 0) + 1
        sid = rt.get("strategy_id", "?")
        by_strategy[sid] = by_strategy.get(sid, 0) + 1

    def _num(row, key, default=0.0):
        v = row.get(key)
        return float(v) if v is not None else default

    d_beats_c = (_num(d, "net_return_pct") > _num(c, "net_return_pct")
                 and _num(d, "max_drawdown_pct") <= _num(c, "max_drawdown_pct") + 1e-9)
    d_better_risk = _num(d, "max_drawdown_pct") < _num(c, "max_drawdown_pct")

    if d_beats_c:
        recommendation = (
            "Variant D (gated policy) beat the legacy policy on return "
            "without added drawdown in this run. Consider promoting D after "
            "reviewing per-window stability — promotion is a manual decision, "
            "nothing is auto-deployed.")
    elif d_better_risk:
        recommendation = (
            "Variant D reduced drawdown versus the legacy policy but did not "
            "improve net return. Keep the legacy policy live; re-evaluate D "
            "after more completed trades accumulate.")
    else:
        recommendation = (
            "Variant D did not improve on the legacy policy in this run. "
            "Keep the legacy policy live. The gates may be starving the "
            "system of trades at the current sample size — re-run after more "
            "trade history accumulates.")

    return {
        "description": ("Phase 2A analysis: corrected ranking/allocation "
                        "policy (hard eligibility gates, Bayesian shrinkage, "
                        "evidence hierarchy, edge-proportional allocation "
                        "with cash remainder) evaluated as walk-forward "
                        "variants D (default gates) and E (strict gates) "
                        "against the preserved legacy policy (variant C)."),
        "comparison": {
            "legacy_C": {k: c.get(k) for k in (
                "net_return_pct", "profit_factor", "expectancy", "win_rate",
                "max_drawdown_pct", "sharpe_ratio", "total_trades",
                "exposure_pct", "turnover", "cash_time_pct", "full_cash_days_pct")},
            "gated_D": {k: d.get(k) for k in (
                "net_return_pct", "profit_factor", "expectancy", "win_rate",
                "max_drawdown_pct", "sharpe_ratio", "total_trades",
                "exposure_pct", "turnover", "cash_time_pct", "full_cash_days_pct")},
            "strict_E": {k: e.get(k) for k in (
                "net_return_pct", "profit_factor", "expectancy", "win_rate",
                "max_drawdown_pct", "sharpe_ratio", "total_trades",
                "exposure_pct", "turnover", "cash_time_pct", "full_cash_days_pct")},
        },
        "rejected_trades_summary": {
            "total_rejected": n_rej,
            "rejections_that_saved_money": saved,
            "rejections_that_cost_money": hurt,
            "rejections_unknown_outcome": unknown,
            "gate_precision_pct": round(saved / (saved + hurt) * 100.0, 1)
                                  if (saved + hurt) else None,
            "by_status": by_status,
            "by_strategy": by_strategy,
        },
        "rejected_trades": rej[:200],
        "recommendation": recommendation,
        "deployment_note": ("ANALYSIS ONLY. The live decision pipeline still "
                            "uses the legacy policy (variant C). Deploying the "
                            "gated policy requires an explicit, separate "
                            "change."),
    }


# ── Main entry point ─────────────────────────────────────────────────────────

def run_validation(config: dict | None = None, on_stage=None) -> dict:
    t0 = time.time()

    def _stage(msg: str) -> None:
        if on_stage is not None:
            try:
                on_stage(msg)
            except Exception:
                pass
    cfg = ValidationConfig.from_dict(config)
    cost_model = CostModel.from_dict(cfg.cost_model)
    cfg.cost_model = cost_model.to_dict()

    universe = cfg.universe or list(NIFTY_50)
    if int(cfg.universe_size or 0) > 0:
        universe = universe[: int(cfg.universe_size)]
    strategy_set = cfg.strategy_set or list(LAB_STRATEGY_IDS)

    end_date = cfg.end_date or (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    if cfg.start_date:
        start_date = cfg.start_date
    else:
        # default: enough for 2 windows
        back_months = cfg.train_years * 12 + cfg.test_months + cfg.step_months
        start_date = _add_months(datetime.strptime(end_date, "%Y-%m-%d"),
                                 -back_months).strftime("%Y-%m-%d")

    windows = generate_windows(start_date, end_date, cfg.train_years,
                               cfg.test_months, cfg.step_months)
    status = {
        "status": "running", "phase": "fetching data",
        "pid": os.getpid(),
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "windows_total": len(windows), "windows_done": 0,
        "progress_pct": 0, "logs": [f"{len(windows)} walk-forward window(s) planned"],
        "config": cfg.to_dict(),
    }
    _write_status(status)

    if not windows:
        err = ("No walk-forward windows fit between "
               f"{start_date} and {end_date} with train={cfg.train_years}y, "
               f"test={cfg.test_months}mo — extend the date range.")
        status.update({"status": "failed", "error": err})
        _write_status(status)
        return {"error": err}

    # ── Prefetch (one fetch per symbol, warmup padding before first train) ──
    fetch_start = (datetime.strptime(windows[0]["train_start"], "%Y-%m-%d")
                   - timedelta(days=150)).strftime("%Y-%m-%d")
    fetch_end = (datetime.strptime(end_date, "%Y-%m-%d")
                 + timedelta(days=1)).strftime("%Y-%m-%d")

    _stage(f"loading data — prefetching {len(universe)} symbols "
           f"({fetch_start} → {fetch_end})")
    sym_rows: dict[str, pd.DataFrame] = {}
    skipped: list[str] = []
    for i, sym in enumerate(universe):
        try:
            sym_rows[sym] = prefetch_symbol(sym, fetch_start, fetch_end)
        except Exception as exc:
            skipped.append(f"{sym}: {exc}")
        status["progress_pct"] = round((i + 1) / len(universe) * 20.0)
        status["logs"] = status["logs"][-8:] + [f"Fetched {sym} ({i + 1}/{len(universe)})"]
        _write_status(status)

    if not sym_rows:
        err = "No historical data could be fetched for any symbol in the universe."
        status.update({"status": "failed", "error": err})
        _write_status(status)
        return {"error": err}

    try:
        nifty = prefetch_index(fetch_start, fetch_end)
    except Exception as exc:
        err = f"NIFTY index data unavailable: {exc}"
        status.update({"status": "failed", "error": err})
        _write_status(status)
        return {"error": err}

    # Position lookups: {sym: {date_str: row position}}
    date_pos = {
        sym: {str(d)[:10]: i for i, d in enumerate(rows["date"])}
        for sym, rows in sym_rows.items()
    }

    ctx = _load_learning_context()
    rng = random.Random(cfg.random_seed)

    # ── Window loop ─────────────────────────────────────────────────────────
    VARIANTS = ("A", "B", "C", "D", "E")
    window_results = []
    all_trades = {v: [] for v in VARIANTS}
    recommendations: list[dict] = []
    lookahead_log = {"decisions": 0, "violations": 0, "max_timestamp": "",
                     "max_knowledge_timestamp": "", "max_similarity_timestamp": ""}
    chained = {**{v: [] for v in VARIANTS}, "nifty": [], "dates": []}
    chain_factor = {v: 1.0 for v in VARIANTS}
    calibration_windows: list[dict] = []
    intelligence_windows: list[dict] = []
    last_intel: StrategyIntelligence | None = None
    last_intel_gated: StrategyIntelligence | None = None
    rejected_trades: list[dict] = []
    research_ledger: list[dict] = []   # Phase 4.2 — analysis only (variant C)
    cash_days = {v: {"cash_weighted": 0.0, "full_cash": 0.0, "days": 0}
                 for v in VARIANTS}
    # Phase 3A (ANALYSIS ONLY): shadow Balanced Decision Model windows.
    balanced_windows: list[dict] = []
    balanced_errors: list[str] = []
    balanced_lookahead = {"decisions": 0, "violations": 0, "max_timestamp": "",
                          "max_knowledge_timestamp": "",
                          "max_similarity_timestamp": ""}

    for wi, window in enumerate(windows):
        status.update({
            "phase": f"window {wi + 1}/{len(windows)} "
                     f"({window['test_start']} → {window['test_end']})",
            "progress_pct": round(20 + wi / len(windows) * 75.0),
            "windows_done": wi,
        })
        _write_status(status)
        _stage(f"walk-forward — training + simulating window {wi + 1}/{len(windows)} "
               f"({window['test_start']} → {window['test_end']})")
        _ADJ_CACHE.clear()

        t_start = pd.Timestamp(window["test_start"])
        t_end = pd.Timestamp(window["test_end"])
        test_days = [d for d in nifty.index if t_start <= d <= t_end]
        if len(test_days) < 5:
            window_results.append({**window, "failed": True,
                                   "failure_reason": "Fewer than 5 trading days in the test window"})
            continue

        trained = train_strategies(sym_rows, window, strategy_set, cfg.initial_capital)
        if not trained:
            window_results.append({**window, "failed": True,
                                   "failure_reason": "No symbol had enough training data"})
            continue

        # Confidence calibration (Phase 1): fit a calibrator PER WINDOW from
        # knowledge trades that fully exited before the test window starts —
        # the same no-lookahead rule as the pattern/similarity paths.
        window_calibrator = None
        try:
            from confidence_calibration import (fit_calibrator,
                                                training_samples_from_knowledge)
            _cal_samples = training_samples_from_knowledge(as_of=window["test_start"])
            window_calibrator = fit_calibrator(_cal_samples)
            window_calibrator["version"] = wi + 1
        except Exception:
            window_calibrator = None
        calibration_windows.append({
            "window": window["label"],
            "test_start": window["test_start"],
            "method": (window_calibrator or {}).get("method", "unavailable"),
            "training_samples": int((window_calibrator or {}).get("n_samples", 0) or 0),
            "version": int((window_calibrator or {}).get("version", 0) or 0),
        })

        # Phase 2 strategy intelligence: built PER WINDOW from knowledge
        # trades that fully exited before the test window starts (no
        # lookahead); the simulation then feeds its own completed
        # out-of-sample trades back in as they close (adaptive learning).
        # C, D and E each get their OWN instance (they learn from their own
        # out-of-sample trades) built from the identical starting data.
        def _fresh_intel():
            try:
                return StrategyIntelligence(
                    intel_trades_from_knowledge(as_of=window["test_start"]))
            except Exception:
                return None

        window_intel = _fresh_intel()          # C — legacy policy
        window_intel_d = _fresh_intel()        # D — gated policy
        window_intel_e = _fresh_intel()        # E — strict gates

        variant_intel = {"C": window_intel, "D": window_intel_d, "E": window_intel_e}
        variant_gates = {"D": GATES_DEFAULT, "E": GATES_STRICT}

        variant_out = {}
        for variant in VARIANTS:
            variant_out[variant] = simulate_window_variant(
                variant, window, sym_rows, date_pos, trained, test_days, nifty,
                ctx, cfg, cost_model,
                record_recommendations=recommendations if variant == "C" else None,
                lookahead_log=lookahead_log if variant == "C" else None,
                calibrator=window_calibrator if variant in FULL_VARIANTS else None,
                strategy_intel=variant_intel.get(variant),
                intel_gates=variant_gates.get(variant),
                rejected_log=rejected_trades if variant == "D" else None,
                research_ledger=research_ledger if variant == "C" else None,
            )
            for t in variant_out[variant]["trades"]:
                t["window"] = window["label"]
                t["variant"] = variant
            all_trades[variant].extend(variant_out[variant]["trades"])
            nd = len(test_days)
            cash_days[variant]["cash_weighted"] += \
                variant_out[variant]["cash_time_pct"] / 100.0 * nd
            cash_days[variant]["full_cash"] += \
                variant_out[variant]["full_cash_days_pct"] / 100.0 * nd
            cash_days[variant]["days"] += nd
        for rt in rejected_trades:
            rt.setdefault("window", window["label"])

        # Phase 3A (ANALYSIS ONLY): replay the SAME window with the shadow
        # Balanced Decision Model (model G). Identical execution mechanics
        # and no-lookahead rules; failures are recorded, never silent.
        try:
            from balanced_decision_model import simulate_window_balanced

            balanced_windows.append(simulate_window_balanced(
                window, sym_rows, date_pos, trained, test_days, nifty,
                ctx, cfg, cost_model, window_calibrator,
                _fresh_intel(), GATES_DEFAULT,
                lookahead_log=balanced_lookahead))
        except Exception as exc:
            balanced_errors.append(
                f"{window['label']}: {type(exc).__name__}: {exc}")

        # Per-window strategy-intelligence snapshot (for the UI)
        if window_intel is not None:
            last_intel = window_intel
            regime_days = variant_out["C"].get("intel_regime_days", {})
            dominant = max(regime_days, key=regime_days.get) if regime_days else "Sideways"
            intelligence_windows.append({
                "window": window["label"],
                "test_start": window["test_start"],
                "dominant_regime": dominant,
                "regime_days": regime_days,
                "oos_trades_learned": len(variant_out["C"]["trades"]),
                "ranking": [{
                    "rank": r["rank"], "strategy_id": r["strategy_id"],
                    "score": r["score"], "enabled": r["enabled"],
                    "reason": r["reason"],
                } for r in window_intel.rank_for_regime(dominant)],
                # Phase 2A: corrected-policy view of the SAME window (variant
                # D's intelligence — gates, statuses, eligibility).
                "gated_ranking": ([{
                    "rank": r["rank"], "strategy_id": r["strategy_id"],
                    "status": r["status"], "eligible": r["eligible"],
                    "score": r["score"], "reason": r["reason"],
                    "raw_profit_factor": r["raw_profit_factor"],
                    "adjusted_profit_factor": r["adjusted_profit_factor"],
                    "sample": r["sample"],
                } for r in window_intel_d.rank_gated(dominant, GATES_DEFAULT)]
                    if window_intel_d is not None else []),
                "gated_cash_only": (window_intel_d.gated_allocation(
                    dominant, GATES_DEFAULT)["cash_only"]
                    if window_intel_d is not None else True),
            })
        if window_intel_d is not None:
            last_intel_gated = window_intel_d

        # chained equity curves (compounded across windows)
        n_days = len(variant_out["C"]["equity_dates"])
        nifty_span = nifty[(nifty.index >= t_start) & (nifty.index <= t_end)]
        nifty_base = float(nifty_span["close"].iloc[0]) if len(nifty_span) else 0.0
        nifty_curve = {str(d)[:10]: float(c) / nifty_base if nifty_base > 0 else 1.0
                       for d, c in zip(nifty_span.index, nifty_span["close"])}
        nifty_chain_base = chained["nifty"][-1] if chained["nifty"] else cfg.initial_capital
        for i in range(n_days):
            d = variant_out["C"]["equity_dates"][i]
            chained["dates"].append(d)
            for v in VARIANTS:
                val = variant_out[v]["equity_curve"][i] / cfg.initial_capital
                chained[v].append(round(chain_factor[v] * val * cfg.initial_capital, 2))
            chained["nifty"].append(round(nifty_chain_base * nifty_curve.get(d, 1.0), 2))
        for v in VARIANTS:
            chain_factor[v] *= variant_out[v]["equity_curve"][-1] / cfg.initial_capital

        bench = {
            "nifty_buy_hold_pct": _index_return(nifty, t_start, t_end),
            "equal_weight_pct": _equal_weight_return(sym_rows, t_start, t_end),
            "rule_engine_pct": _rule_engine_return(sym_rows, date_pos, trained,
                                                   test_days, cfg, cost_model),
            "technical_confidence_only_pct": variant_out["A"]["metrics"]["total_return_pct"],
            "random_selection_pct": _random_benchmark_return(
                variant_out["C"]["trades"], sym_rows, date_pos, cfg, cost_model, rng),
            "cash_pct": 0.0,
        }

        window_results.append({
            **window,
            # A window with zero trades is a VALID outcome (the model chose not
            # to trade) — benchmarks still apply. "failed" is reserved for data
            # failures (no candles / insufficient history), handled above.
            "failed": False,
            "failure_reason": ("No trades executed in this test window"
                               if variant_out["C"]["metrics"]["total_trades"] == 0 else ""),
            "trading_days": len(test_days),
            "base_metrics": variant_out["A"]["metrics"],
            "layered_metrics": variant_out["B"]["metrics"],
            "full_metrics": variant_out["C"]["metrics"],
            "gated_metrics": variant_out["D"]["metrics"],
            "strict_metrics": variant_out["E"]["metrics"],
            "cash_time_pct": {v: variant_out[v]["cash_time_pct"] for v in VARIANTS},
            "benchmarks": bench,
        })

        # Persist per-window progress and release per-window memory: long runs
        # were dying from memory exhaustion accumulated across windows.
        status["windows_done"] = wi + 1
        _write_status(status)
        _stage(f"walk-forward — window {wi + 1}/{len(windows)} done")
        del trained, variant_out
        import gc
        gc.collect()

    # ── Aggregation ─────────────────────────────────────────────────────────
    status.update({"phase": "aggregating results", "progress_pct": 96})
    _write_status(status)
    _stage("scoring — aggregating results across windows")

    total_test_days = sum(int(w.get("trading_days", 0)) for w in window_results)
    overall = {}
    for v in VARIANTS:
        trades_sorted = sorted(all_trades[v], key=lambda t: (t["exit_date"], t["symbol"]))
        overall[v] = vm.compute_performance_metrics(
            trades_sorted, cfg.initial_capital, chained[v], trading_days=total_test_days)

    layer_comparison = []
    for v in VARIANTS:
        m = overall[v]
        cd = cash_days[v]
        layer_comparison.append({
            "variant": v, "label": VARIANT_LABELS[v],
            "net_return_pct": m["total_return_pct"],
            "net_profit": m["net_profit"],
            "expectancy": m["expectancy"],
            "profit_factor": m["profit_factor"],
            "max_drawdown_pct": m["max_drawdown_pct"],
            "sharpe_ratio": m["sharpe_ratio"],
            "total_trades": m["total_trades"],
            "total_costs": m["total_costs"],
            "win_rate": m["win_rate"],
            "exposure_pct": m["exposure_pct"],
            "turnover": m["turnover"],
            "cash_time_pct": round(cd["cash_weighted"] / cd["days"] * 100.0, 1)
                             if cd["days"] else 100.0,
            "full_cash_days_pct": round(cd["full_cash"] / cd["days"] * 100.0, 1)
                                  if cd["days"] else 100.0,
        })
    for i, row in enumerate(layer_comparison):
        if i == 0:
            row["vs_previous"] = "baseline"
        else:
            diff = row["net_return_pct"] - layer_comparison[i - 1]["net_return_pct"]
            row["vs_previous"] = (f"improved (+{diff:.2f}%)" if diff > 0
                                  else f"worsened ({diff:.2f}%)" if diff < 0
                                  else "no change")

    ok_windows = [w for w in window_results if not w.get("failed")]
    benchmarks_overall = {
        "nifty_buy_hold_pct": round(sum(w["benchmarks"]["nifty_buy_hold_pct"] for w in ok_windows), 2) if ok_windows else 0.0,
        "equal_weight_pct": round(sum(w["benchmarks"]["equal_weight_pct"] for w in ok_windows), 2) if ok_windows else 0.0,
        "rule_engine_pct": round(sum(w["benchmarks"]["rule_engine_pct"] for w in ok_windows), 2) if ok_windows else 0.0,
        "technical_confidence_only_pct": overall["A"]["total_return_pct"],
        "random_selection_pct": round(sum(w["benchmarks"]["random_selection_pct"] for w in ok_windows), 2) if ok_windows else 0.0,
        "cash_pct": 0.0,
        "full_model_pct": overall["C"]["total_return_pct"],
        "note": "Window returns summed across test windows (each window restarts at the configured capital); the full model line is the compounded overall return.",
    }

    calibration = vm.compute_calibration(all_trades["C"])

    # Phase 1 calibration report: before (raw/100) vs after (per-window
    # calibrated probability recorded on each trade) quality metrics.
    calibration_report = None
    try:
        from confidence_calibration import calibration_report_from_pairs
        _ct = [t for t in all_trades["C"]
               if t.get("calibrated_probability") is not None]
        if _ct:
            _methods = [t.get("calibration_method") or "identity" for t in _ct]
            _method = max(set(_methods), key=_methods.count)
            calibration_report = calibration_report_from_pairs(
                [float(t.get("raw_confidence", t.get("confidence", 0.0)) or 0.0)
                 for t in _ct],
                [float(t["calibrated_probability"]) for t in _ct],
                [1 if float(t.get("net_pnl", 0.0)) > 0 else 0 for t in _ct],
                method=_method,
                version=max(int(t.get("calibration_version", 0) or 0) for t in _ct),
            )
            calibration_report["windows"] = calibration_windows
            calibration_report["min_calibrated_prob"] = cfg.min_calibrated_prob
    except Exception:
        calibration_report = None
    if calibration_report is None:
        calibration_report = {
            "samples": 0, "calibration_method": "unavailable",
            "calibration_version": 0, "before": None, "after": None,
            "reliability_raw": [], "reliability_calibrated": [],
            "windows": calibration_windows,
            "min_calibrated_prob": cfg.min_calibrated_prob,
            "safety": SAFETY_MESSAGE,
        }

    # Phase 2: Strategy Intelligence report — the LAST window's intelligence
    # (knowledge as-of its test start + every completed out-of-sample trade
    # learned during the run), evaluated at the most recent market regime.
    strategy_intelligence_report = None
    try:
        if last_intel is not None:
            current_regime = regime7_as_of(nifty, nifty.index[-1])
            _rep = last_intel.report(current_regime)
            strategy_intelligence_report = {
                "current_regime": current_regime,
                "total_completed_trades": _rep["total_completed_trades"],
                "ranking": _rep["ranking"],
                "matrix": _rep["matrix"],
                "windows": intelligence_windows,
                "note": ("Strategies are ranked per market regime from "
                         "completed trades only (knowledge trades that exited "
                         "before each test window plus out-of-sample trades "
                         "closed during the run — no lookahead). Disabled "
                         "strategies are skipped at entry; allocation tilts "
                         "toward higher-ranked strategies, capped at "
                         f"{int(MAX_STRATEGY_ALLOC * 100)}% per strategy."),
            }
            # Phase 2A: corrected-policy report (variant D intelligence,
            # analysis-only — the live pipeline is unchanged).
            if last_intel_gated is not None:
                strategy_intelligence_report["gated"] = \
                    last_intel_gated.gated_report(current_regime, GATES_DEFAULT)
    except Exception:
        strategy_intelligence_report = None

    rec_outcomes = vm.compute_recommendation_outcomes(recommendations)
    stability = vm.compute_stability(all_trades["C"])
    verdict = vm.evaluate_verdict(overall["C"], overall["A"], stability,
                                  [w for w in window_results if not w.get("failed")],
                                  cfg.verdict_criteria)
    cost_breakdown = aggregate_costs(all_trades["C"])

    # ── Phase 2B: Strategy Audit (ANALYSIS ONLY — never changes decisions) ──
    status.update({"phase": "Phase 2B strategy audit", "progress_pct": 97})
    _write_status(status)

    # Shared, lookahead-safe inputs for the Phase 2B audit and the Phase 3
    # MACD optimization (both are analysis-only add-ons).
    _audit_first = pd.Timestamp(windows[0]["train_start"])
    _audit_last = pd.Timestamp(end_date)
    regime_by_date = {
        str(d)[:10]: regime7_as_of(nifty, d)
        for d in nifty.index if _audit_first <= d <= _audit_last
    }
    test_dates_by_window = {}
    for w in window_results:
        if w.get("failed"):
            continue
        _ts, _te = pd.Timestamp(w["test_start"]), pd.Timestamp(w["test_end"])
        test_dates_by_window[w["label"]] = [
            str(d)[:10] for d in nifty.index if _ts <= d <= _te]

    def _audit_progress(msg: str) -> None:
        status["logs"] = status["logs"][-8:] + [msg]
        _write_status(status)

    try:
        from strategy_audit import run_strategy_audit

        strategy_audit_report = run_strategy_audit(
            sym_rows, window_results, regime_by_date, test_dates_by_window,
            cfg, cost_model,
            existing_overall={v: overall[v] for v in ("A", "B", "C", "D")},
            existing_cash={
                v: (round(cash_days[v]["cash_weighted"] / cash_days[v]["days"]
                          * 100.0, 1) if cash_days[v]["days"] else 100.0)
                for v in ("A", "B", "C", "D")
            },
            random_seed=cfg.random_seed,
            progress_cb=_audit_progress,
        )
    except Exception as exc:  # explicit failure — never silently dropped
        strategy_audit_report = {
            "error": f"Strategy audit failed: {type(exc).__name__}: {exc}",
            "safety": SAFETY_MESSAGE,
        }

    # ── Phase 3: MACD optimization (ANALYSIS ONLY — never changes decisions) ─
    status.update({"phase": "Phase 3 MACD optimization", "progress_pct": 97})
    _write_status(status)
    try:
        from macd_optimizer import run_macd_optimization

        macd_optimization_report = run_macd_optimization(
            sym_rows, window_results, regime_by_date, test_dates_by_window,
            cfg, cost_model, progress_cb=_audit_progress)
    except Exception as exc:  # explicit failure — never silently dropped
        macd_optimization_report = {
            "error": f"MACD optimization failed: {type(exc).__name__}: {exc}",
            "safety": SAFETY_MESSAGE,
        }

    # ── Phase 4: MACD robustness (ANALYSIS ONLY — never changes decisions) ──
    status.update({"phase": "Phase 4 MACD robustness analysis", "progress_pct": 98})
    _write_status(status)
    try:
        from macd_robustness import run_macd_robustness

        macd_robustness_report = run_macd_robustness(
            sym_rows, window_results, regime_by_date, test_dates_by_window,
            cfg, cost_model, progress_cb=_audit_progress)
    except Exception as exc:  # explicit failure — never silently dropped
        macd_robustness_report = {
            "error": f"MACD robustness analysis failed: {type(exc).__name__}: {exc}",
            "safety": SAFETY_MESSAGE,
        }

    # ── Phase 5: Alpha Generation Engine (ANALYSIS ONLY — never changes decisions) ──
    status.update({"phase": "Phase 5 Alpha Generation Engine", "progress_pct": 99})
    _write_status(status)
    try:
        from alpha_generator import run_alpha_generation

        alpha_generation_report = run_alpha_generation(
            sym_rows, window_results, regime_by_date, test_dates_by_window,
            cfg, cost_model, nifty_df=nifty, progress_cb=_audit_progress)
    except Exception as exc:  # explicit failure — never silently dropped
        alpha_generation_report = {
            "error": f"Alpha generation failed: {type(exc).__name__}: {exc}",
            "safety": SAFETY_MESSAGE,
        }

    # ── Phase 3A: Balanced Decision Model (ANALYSIS ONLY — shadow model) ─
    status.update({"phase": "Phase 3A Balanced Decision Model", "progress_pct": 99})
    _write_status(status)
    try:
        from balanced_decision_model import build_balanced_report

        balanced_decision_report = build_balanced_report(
            balanced_windows, overall, layer_comparison, all_trades, cfg,
            calibration_report, balanced_lookahead, balanced_errors,
            progress_cb=_audit_progress)
    except Exception as exc:  # explicit failure — never silently dropped
        balanced_decision_report = {
            "error": f"Balanced decision model failed: {type(exc).__name__}: {exc}",
            "safety": SAFETY_MESSAGE,
        }

    # ── Phase 3A.5: Evidence Expansion (ANALYSIS ONLY) ───────────────────────
    status.update({"phase": "Phase 3A.5 Evidence Expansion", "progress_pct": 99})
    _write_status(status)
    try:
        from evidence_expansion import build_evidence_report as _build_evidence

        evidence_expansion_report = _build_evidence(
            all_trades["C"], window_results, calibration_report, cfg,
            progress_cb=_audit_progress)
    except Exception as exc:  # explicit failure — never silently dropped
        evidence_expansion_report = {
            "error": f"Evidence expansion failed: {type(exc).__name__}: {exc}",
            "safety": SAFETY_MESSAGE,
        }

    equity_curve = [
        {"date": chained["dates"][i], "full_model": chained["C"][i],
         "base_model": chained["A"][i], "layered_model": chained["B"][i],
         "gated_model": chained["D"][i], "strict_model": chained["E"][i],
         "nifty": chained["nifty"][i]}
        for i in range(len(chained["dates"]))
    ]
    dd_series = vm.drawdown_series(chained["C"])
    drawdown_curve = [
        {"date": chained["dates"][i], "drawdown_pct": dd_series[i]}
        for i in range(len(chained["dates"]))
    ]

    result = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "run_seconds": round(time.time() - t0, 1),
        "config": cfg.to_dict(),
        "intrabar_rule_label": INTRABAR_RULE_LABELS[cfg.intrabar_rule],
        "universe_size": len(sym_rows),
        "skipped_symbols": skipped,
        "adaptive_model_version": ctx["model_version"],
        "knowledge_trades_available": len(ctx["knowledge"]),
        "similarity_vectors_available": len(ctx["vectors"]),
        "windows": [
            {k: v for k, v in w.items()} for w in window_results
        ],
        "overall": {
            "base_metrics": overall["A"],
            "layered_metrics": overall["B"],
            "full_metrics": overall["C"],
            "gated_metrics": overall["D"],
            "strict_metrics": overall["E"],
        },
        "layer_comparison": layer_comparison,
        "phase2a": _phase2a_report(overall, layer_comparison, rejected_trades),
        # Phase 4.2 — Strategy Improvement Framework (analysis only): the
        # full per-candidate ledger is written to research_ledger.csv (too
        # large for JSON); only stage counts are embedded here.
        "research_ledger_summary": {
            "rows": len(research_ledger),
            "stages": dict(sorted(_Counter(
                r["stage"] for r in research_ledger).items())),
        },
        "strategy_audit": strategy_audit_report,
        "macd_optimization": macd_optimization_report,
        "macd_robustness": macd_robustness_report,
        "alpha_generation": alpha_generation_report,
        "balanced_decision": balanced_decision_report,
        "evidence_expansion": evidence_expansion_report,
        "benchmarks": benchmarks_overall,
        "calibration": calibration,
        "calibration_report": calibration_report,
        "strategy_intelligence": strategy_intelligence_report,
        "recommendation_outcomes": rec_outcomes,
        "recommendations_issued": len(recommendations),
        "stability": stability,
        "verdict": verdict,
        "cost_breakdown": cost_breakdown,
        "equity_curve": equity_curve,
        "drawdown_curve": drawdown_curve,
        "lookahead_audit": {
            "decisions_logged": lookahead_log["decisions"],
            "violations": lookahead_log["violations"],
            "max_data_timestamp_seen": lookahead_log["max_timestamp"],
            "max_knowledge_timestamp_seen": lookahead_log["max_knowledge_timestamp"],
            "max_similarity_timestamp_seen": lookahead_log["max_similarity_timestamp"],
            "note": ("Every decision logs the newest timestamp from each data "
                     "source it used — candle bars, historical-knowledge trades "
                     "(pattern path) and similarity matches. A violation means a "
                     "decision saw a candle newer than its own day, or knowledge/"
                     "similarity trades that had not fully exited before the "
                     "decision day. This must always be 0."),
        },
        "safety": SAFETY_MESSAGE,
    }

    os.makedirs(VALIDATION_DIR, exist_ok=True)
    with open(RESULT_PATH, "w") as f:
        json.dump(result, f)

    _export_csvs(result, all_trades["C"])
    _export_research_ledger(research_ledger)

    status.update({"status": "completed", "phase": "done", "progress_pct": 100,
                   "windows_done": len(window_results)})
    _write_status(status)
    return result


# ── CSV exports ──────────────────────────────────────────────────────────────

def _export_research_ledger(ledger: list[dict]) -> None:
    """Phase 4.2 (analysis only): every variant-C candidate evaluated during
    the walk-forward, with features, gate outcome and forward returns."""
    if not ledger:
        return
    os.makedirs(VALIDATION_DIR, exist_ok=True)
    cols = list(ledger[0].keys())
    with open(os.path.join(VALIDATION_DIR, "research_ledger.csv"),
              "w", newline="") as f:
        w = _csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(ledger)


def _export_csvs(result: dict, full_trades: list[dict]) -> None:
    os.makedirs(VALIDATION_DIR, exist_ok=True)

    # 1. Complete validation report
    with open(os.path.join(VALIDATION_DIR, CSV_FILES["report"]), "w", newline="") as f:
        w = _csv.writer(f)
        w.writerow(["section", "metric", "value"])
        w.writerow(["meta", "generated_at", result["generated_at"]])
        w.writerow(["meta", "verdict", result["verdict"]["verdict"]])
        w.writerow(["meta", "verdict_summary", result["verdict"]["summary"]])
        for v_key, label in (("base_metrics", "base model"),
                             ("layered_metrics", "pattern+similarity"),
                             ("full_metrics", "full model")):
            for k, val in result["overall"][v_key].items():
                w.writerow([label, k, val])
        for k, val in result["benchmarks"].items():
            w.writerow(["benchmarks", k, val])
        for c in result["verdict"]["checks"]:
            w.writerow(["verdict_check", c["name"],
                        f"observed={c['observed']} threshold={c['direction']}{c['threshold']} passed={c['passed']}"])
        for flag in result["stability"]["concentration_flags"]:
            w.writerow(["stability_flag", "concentration", flag])
        w.writerow(["safety", "message", result["safety"]])

    # 2. All simulated trades (full model)
    trade_cols = ["window", "variant", "symbol", "sector", "recommendation",
                  "confidence", "raw_confidence", "calibrated_probability",
                  "calibrated_confidence", "calibration_method",
                  "calibration_version", "strategy_name", "entry_date", "entry_price",
                  "quantity", "requested_quantity", "partial_fill", "gap_pct",
                  "invested", "exit_date", "exit_price", "exit_reason",
                  "holding_days", "gross_pnl", "net_pnl", "return_pct",
                  "total_costs", "mae_pct", "mfe_pct", "intrabar_rule",
                  "market_regime", "max_data_timestamp"]
    with open(os.path.join(VALIDATION_DIR, CSV_FILES["trades"]), "w", newline="") as f:
        w = _csv.writer(f)
        w.writerow(trade_cols)
        for t in full_trades:
            w.writerow([t.get(c, "") for c in trade_cols])

    # 3. Window-level metrics
    with open(os.path.join(VALIDATION_DIR, CSV_FILES["windows"]), "w", newline="") as f:
        w = _csv.writer(f)
        header = ["window", "train_start", "train_end", "test_start", "test_end",
                  "failed", "failure_reason"]
        metric_keys = ["total_trades", "win_rate", "net_profit", "total_return_pct",
                       "expectancy", "profit_factor", "max_drawdown_pct",
                       "sharpe_ratio", "total_costs"]
        header += [f"base_{k}" for k in metric_keys]
        header += [f"full_{k}" for k in metric_keys]
        header += ["nifty_buy_hold_pct", "equal_weight_pct", "rule_engine_pct",
                   "random_selection_pct"]
        w.writerow(header)
        for win in result["windows"]:
            row = [win.get("label"), win.get("train_start"), win.get("train_end"),
                   win.get("test_start"), win.get("test_end"),
                   win.get("failed"), win.get("failure_reason", "")]
            bm = win.get("base_metrics", {})
            fm = win.get("full_metrics", {})
            row += [bm.get(k, "") for k in metric_keys]
            row += [fm.get(k, "") for k in metric_keys]
            b = win.get("benchmarks", {})
            row += [b.get("nifty_buy_hold_pct", ""), b.get("equal_weight_pct", ""),
                    b.get("rule_engine_pct", ""), b.get("random_selection_pct", "")]
            w.writerow(row)

    # 4. Confidence calibration
    with open(os.path.join(VALIDATION_DIR, CSV_FILES["calibration"]), "w", newline="") as f:
        w = _csv.writer(f)
        cols = ["band", "trades", "predicted_success_rate", "actual_success_rate",
                "calibration_gap", "avg_return_pct", "profit_factor", "flag"]
        w.writerow(cols)
        for row in result["calibration"]:
            w.writerow([row.get(c, "") for c in cols])

    # 5. Cost breakdown
    with open(os.path.join(VALIDATION_DIR, CSV_FILES["costs"]), "w", newline="") as f:
        w = _csv.writer(f)
        w.writerow(["component", "amount_inr"])
        for k, v in result["cost_breakdown"].items():
            w.writerow([k, v])


def export_csv_path(kind: str) -> str | None:
    fn = CSV_FILES.get(kind)
    if not fn:
        return None
    p = os.path.join(VALIDATION_DIR, fn)
    return p if os.path.exists(p) else None
