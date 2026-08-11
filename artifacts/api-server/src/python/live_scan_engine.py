"""
live_scan_engine.py  —  Phase 7: Live Market Intelligence
Canonical scan engine that produces ONE consistent data snapshot per scan.

Architecture
------------
* A single scan_id (UUID) is created at the start of each scan run.
* ALL data is fetched up-front via LiveDataProvider before any analysis.
* Every gate pass/fail is recorded with an explicit reason string.
* Data quality is propagated into every recommendation — STALE/UNAVAILABLE
  data is capped at WATCH/IGNORE regardless of technical score.
* Paper-trading integration: eligible recommendations may create simulated
  positions in paper_trader.py — no real broker API is called.
* Meta-Learning and Strategy Evolution findings NEVER affect decisions here
  unless a future human-approved phase explicitly wires them in.
* Research-only safeguards from previous phases are fully preserved.

Recommendation metadata per item
---------------------------------
  scan_id, snapshot_ts, data_source, data_age_days, data_quality,
  strategy, regime, technical_score, historical_evidence_adjustment,
  calibrated_confidence, rr_ratio, entry, stop, target,
  expected_holding_period, gate_results (all pass/fail with reason),
  final_action, paper_eligible, paper_order_id (or None).

PAPER TRADING / RESEARCH ONLY — live broker APIs are disabled.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd

from config import NIFTY_50, INITIAL_CAPITAL, SECTOR_MAP

try:
    from phase3f_logging import get_logger as _get_logger
    _log = _get_logger("live_scan_engine")
except Exception:
    _log = None  # structured logging optional

from live_data_provider import (
    DataQuality, LiveDataProvider, ProviderHealth, SymbolFetchResult,
)
from market_scanner import (
    _sector_of, _final_action, _heat_of, _strategy_perf_score,
    _confidence_score, _opportunity_score, _rr_normalized,
    _empty_scan_item, _sector_strength, ACTION_STRONG_BUY, ACTION_BUY,
    WATCHLIST_SIZE,
)

# ── Constants ─────────────────────────────────────────────────────────────────

SCAN_CACHE_FILE = os.path.join(os.path.dirname(__file__), "phase7_scan_cache.json")
STALE_GUARD_ACTION  = "WATCH"    # max action for STALE data
UNAVAIL_GUARD_ACTION = "IGNORE"  # max action for UNAVAILABLE data
MIN_RR_FOR_BUY      = 1.5        # RR gate: below this → WATCH minimum

PAPER_ELIGIBLE_ACTIONS  = {"STRONG BUY", "BUY"}
PAPER_ELIGIBLE_QUALITIES = {DataQuality.LIVE, DataQuality.NEAR_LIVE}

HOLDING_PERIOD_BY_STRATEGY = {
    "mean_reversion":  5,
    "macd_crossover": 12,
    "ema_crossover":  10,
    "trend_rider":    15,
    "breakout":        8,
}

# ── Gate definitions ──────────────────────────────────────────────────────────

def _apply_quality_gate(action: str, quality: str) -> Tuple[str, str]:
    """Enforce data-quality safety cap. Returns (capped_action, reason)."""
    if quality == DataQuality.UNAVAILABLE:
        if action in ("STRONG BUY", "BUY", "WATCH"):
            return UNAVAIL_GUARD_ACTION, f"Data UNAVAILABLE — capped to {UNAVAIL_GUARD_ACTION}"
        return action, "Data UNAVAILABLE — action already conservative"
    if quality == DataQuality.STALE:
        if action in ("STRONG BUY", "BUY"):
            return STALE_GUARD_ACTION, f"Data STALE — BUY/STRONG BUY blocked, capped to {STALE_GUARD_ACTION}"
        return action, f"Data STALE — action {action} permitted (already conservative)"
    return action, f"Data quality {quality} — no cap applied"


def _rr_gate(rr_ratio: float, action: str) -> Tuple[bool, str]:
    """Minimum RR gate for BUY / STRONG BUY."""
    if action in ("STRONG BUY", "BUY") and rr_ratio < MIN_RR_FOR_BUY:
        return False, f"RR {rr_ratio:.2f} < {MIN_RR_FOR_BUY} minimum — BUY requires viable risk/reward"
    return True, f"RR {rr_ratio:.2f} passes gate (min {MIN_RR_FOR_BUY})"


def _price_gate(price: float, symbol: str) -> Tuple[bool, str]:
    """Reject zero / negative / implausibly small prices."""
    if price <= 0:
        return False, f"{symbol} price ₹{price} invalid — must be > 0"
    if price < 1.0:
        return False, f"{symbol} price ₹{price} below ₹1 — implausible for NSE stock"
    return True, f"Price ₹{price:.2f} valid"


def _volume_gate(volume_ratio: float, action: str) -> Tuple[bool, str]:
    """Flag very low volume for BUY-class actions."""
    if action in ("STRONG BUY", "BUY") and volume_ratio < 0.3:
        return False, f"Volume ratio {volume_ratio:.2f} very low (<0.3) — liquidity risk"
    return True, f"Volume ratio {volume_ratio:.2f} acceptable"


# ── Recommendation record ─────────────────────────────────────────────────────

@dataclass
class Phase7Recommendation:
    # Identity
    scan_id: str
    snapshot_ts: str
    symbol: str
    sector: str
    # Data provenance
    data_source: str
    data_age_days: Optional[float]
    data_quality: str
    latest_bar_date: Optional[str]
    bars_available: int
    # Strategy
    strategy_id: str
    strategy_name: str
    regime: str
    # Scores
    technical_score: float          # perf_score from 6mo backtest
    historical_evidence_adjustment: float   # learning_adjustment
    calibrated_confidence: float    # final_confidence after adjustment
    opportunity_score: float
    # Trade levels (paper/indicative only)
    entry_price: float
    stop_loss: float
    target_price: float
    rr_ratio: float
    expected_holding_days: int
    # Gates — each records (passed: bool, reason: str)
    gate_price: Dict[str, Any]
    gate_data_quality: Dict[str, Any]
    gate_rr: Dict[str, Any]
    gate_volume: Dict[str, Any]
    # Decision
    final_action: str
    heat: str
    all_gates_passed: bool
    # Paper trading
    paper_eligible: bool
    paper_order_id: Optional[str]
    paper_order_note: str
    # Extras
    win_rate: float
    profit_factor: float
    net_pnl_pct: float
    total_trades: int
    low_evidence: bool          # True when total_trades < 5 (insufficient backtest evidence)
    adx: float
    rsi: float
    volume_ratio: float
    above_ema20: bool
    above_ema50: bool
    error: Optional[str]


# ── Canonical scan ────────────────────────────────────────────────────────────

@dataclass
class Phase7ScanResult:
    scan_id: str
    snapshot_ts: str                      # single consistent timestamp for the whole scan
    universe: List[str]
    universe_size: int
    duration_s: float
    provider_health: Dict[str, Any]       # ProviderHealth as dict
    recommendations: List[Dict[str, Any]] # Phase7Recommendation as dicts
    summary: Dict[str, Any]
    scan_audit: Dict[str, Any]            # proves snapshot consistency
    paper_eligible: bool                  # overall: can paper-trade this scan?
    safety: Dict[str, Any]
    phase: str = "7"
    label: str = "PAPER / LIVE DATA VALIDATION"
    timings: Dict[str, Any] = field(default_factory=dict)  # stage breakdown (s)


def _holding_days(strategy_id: str) -> int:
    for k, v in HOLDING_PERIOD_BY_STRATEGY.items():
        if k in (strategy_id or "").lower():
            return v
    return 10


def _scan_one(
    symbol: str,
    fetch_result: SymbolFetchResult,
    scan_id: str,
    snapshot_ts: str,
    capital: float,
) -> Phase7Recommendation:
    """Analyse one symbol using its pre-fetched data."""

    # True per-stage processing timestamps (ISO-8601, ms precision) captured
    # as work actually completes. Attached to the recommendation as a
    # NON-dataclass attribute (`_stage_ts`) so it never leaks into asdict()
    # snapshots; derive_symbol_events() reads it to timestamp each event
    # individually — otherwise batch emits share one insert time and the
    # operator-analytics stage timings read as 0 ms.
    stage_ts: Dict[str, str] = {}

    def _mark(stage: str) -> None:
        stage_ts[stage] = datetime.now(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"

    # Defaults for failed symbols
    def _fail(reason: str) -> Phase7Recommendation:
        _mark("SCANNER")
        r = Phase7Recommendation(
            scan_id=scan_id, snapshot_ts=snapshot_ts, symbol=symbol.upper(),
            sector=_sector_of(symbol), data_source=fetch_result.data_source,
            data_age_days=fetch_result.data_age_days,
            data_quality=fetch_result.data_quality,
            latest_bar_date=fetch_result.latest_date,
            bars_available=fetch_result.bars,
            strategy_id="", strategy_name="", regime="",
            technical_score=0.0, historical_evidence_adjustment=0.0,
            calibrated_confidence=0.0, opportunity_score=0.0,
            entry_price=0.0, stop_loss=0.0, target_price=0.0, rr_ratio=0.0,
            expected_holding_days=0,
            gate_price={"passed": False, "reason": reason},
            gate_data_quality={"passed": False, "reason": reason},
            gate_rr={"passed": False, "reason": "Symbol failed"},
            gate_volume={"passed": False, "reason": "Symbol failed"},
            final_action="IGNORE", heat="RED", all_gates_passed=False,
            paper_eligible=False, paper_order_id=None,
            paper_order_note=reason,
            win_rate=0.0, profit_factor=0.0, net_pnl_pct=0.0, total_trades=0,
            low_evidence=True,  # zero trades → definitely low evidence
            adx=0.0, rsi=0.0, volume_ratio=0.0,
            above_ema20=False, above_ema50=False, error=reason,
        )
        r._stage_ts = dict(stage_ts)  # type: ignore[attr-defined]
        return r

    if not fetch_result.success or fetch_result.df is None:
        return _fail(f"Data fetch failed: {fetch_result.error}")

    df = fetch_result.df
    quality = fetch_result.data_quality

    # Indicator computation
    try:
        from indicator_engine import compute_indicators_df
        enriched = compute_indicators_df(df)
    except Exception as exc:
        return _fail(f"Indicator computation failed: {exc}")

    rows = enriched.reset_index(drop=False)
    if len(rows) < 30:
        return _fail(f"Insufficient bars after indicators: {len(rows)}")
    _mark("SCANNER")  # data fetch + indicator computation complete

    last_row = rows.iloc[-1]
    price = float(last_row.get("close", 0.0) or 0.0)

    # Gate: price validity
    price_ok, price_reason = _price_gate(price, symbol)
    if not price_ok:
        r = _fail(price_reason)
        r.gate_price = {"passed": False, "reason": price_reason}
        return r

    # Strategy evaluation
    try:
        from strategies import get_strategy, LAB_STRATEGY_IDS
        from backtesting_engine import _run_lab_walk
    except Exception as exc:
        return _fail(f"Strategy import failed: {exc}")

    prev_row = rows.iloc[-2]
    best = None
    for sid in LAB_STRATEGY_IDS:
        try:
            strategy = get_strategy(sid)
            metrics = _run_lab_walk(rows, strategy, capital)
            perf = _strategy_perf_score(metrics)
            live_ok, reason = strategy.check_entry(last_row, prev_row)
        except Exception:
            continue
        rank = (1 if live_ok else 0, perf)
        if best is None or rank > (1 if best[4] else 0, best[0]):
            best = (perf, sid, strategy, metrics, live_ok, reason)

    if best is None:
        return _fail("No strategy could be evaluated")
    _mark("RESEARCH")  # historical strategy walk (bulk of per-symbol work)
    _mark("MARKET_INTELLIGENCE")  # derived from the same computation (≈0ms)
    _mark("MONITORING")           # derived from the same computation (≈0ms)

    perf_score, sid, strategy, metrics, live_signal, sig_reason = best
    confidence = _confidence_score(perf_score, metrics.get("total_trades", 0), live_signal)

    # Trade levels
    try:
        stop_loss = strategy.compute_stop_loss(last_row, price)
        target = strategy.compute_target(price, stop_loss)
    except Exception:
        stop_loss, target = 0.0, 0.0

    risk = max(0.0, price - stop_loss) if stop_loss > 0 else 0.0
    reward = max(0.0, target - price) if target > 0 else 0.0
    rr_ratio = round(reward / risk, 2) if risk > 0 else 0.0

    opp_score = _opportunity_score(perf_score, confidence, rr_ratio, live_signal)
    action = _final_action(opp_score)

    # Learning adjustment (best-effort)
    learning_adj = 0.0
    final_conf = confidence
    try:
        from adaptive_learning import get_item_adjustment
        adj_data = get_item_adjustment(symbol, strategy.id, action)
        learning_adj = float(adj_data.get("adjustment", 0.0))
        final_conf = float(adj_data.get("final_confidence", confidence))
    except Exception:
        pass
    _mark("STRATEGY")  # levels + learning adjustment complete

    # Gate: data quality cap
    capped_action, quality_reason = _apply_quality_gate(action, quality)
    quality_ok = (capped_action == action)
    action = capped_action
    heat = _heat_of(action)

    # Gate: RR
    rr_ok, rr_reason = _rr_gate(rr_ratio, action)
    if not rr_ok and action in ("STRONG BUY", "BUY"):
        action = "WATCH"
        heat = _heat_of(action)

    # Gate: volume
    vol_ratio = float(last_row.get("volume_ratio", 0.0) or 0.0)
    # Intraday backtests may attach a time-of-day normalized volume ratio
    # (session-so-far vs avg session-to-date at the same time). Only the
    # backtest runner sets df.attrs — LIVE and daily scans are unaffected.
    vol_norm = None
    try:
        # Hard guard: honoured ONLY for backtest-cache data. A live provider
        # dataframe can never activate this path, even if attrs leak through.
        if fetch_result.data_source == "backtest_cache":
            vol_norm = (getattr(fetch_result.df, "attrs", None) or {}).get(
                "intraday_vol_norm")
    except Exception:
        vol_norm = None
    if isinstance(vol_norm, dict) and vol_norm.get("ok"):
        vol_ratio = float(vol_norm["ratio"])
    vol_ok, vol_reason = _volume_gate(vol_ratio, action)
    if isinstance(vol_norm, dict):
        vol_reason += (
            " [time-of-day normalized"
            f" over {vol_norm.get('days')} sessions]" if vol_norm.get("ok")
            else f" [volume-curve evidence insufficient — raw full-day ratio;"
                 f" {vol_norm.get('reason')}]")
    if not vol_ok and action in ("STRONG BUY", "BUY"):
        action = "WATCH"
        heat = _heat_of(action)

    all_gates = all([price_ok, quality_ok or quality in (DataQuality.LIVE, DataQuality.NEAR_LIVE),
                     rr_ok, vol_ok])
    # Paper eligibility: BUY-class + fresh data + all gates pass
    paper_eligible = (
        action in PAPER_ELIGIBLE_ACTIONS
        and quality in PAPER_ELIGIBLE_QUALITIES
        and all_gates
    )
    _mark("RISK")  # all gates evaluated

    # Paper order creation (simulated only)
    paper_order_id = None
    paper_note = "Not eligible for paper execution"
    if paper_eligible:
        try:
            from paper_trader import create_paper_order
            order = create_paper_order(
                symbol=symbol.upper(), action=action,
                entry_price=round(price, 2), stop_loss=stop_loss,
                target=target, strategy=strategy.name,
                scan_id=scan_id, confidence=final_conf,
            )
            if order and order.get("order_id"):
                paper_order_id = order["order_id"]
                paper_note = f"Paper order created: {paper_order_id}"
            else:
                paper_note = order.get("reason", "Paper order skipped")
        except Exception as exc:
            paper_note = f"Paper order skipped: {exc}"
    _mark("AI_DECISION")  # final action + paper eligibility decided

    rec = Phase7Recommendation(
        scan_id=scan_id, snapshot_ts=snapshot_ts,
        symbol=symbol.upper(), sector=_sector_of(symbol),
        data_source=fetch_result.data_source,
        data_age_days=fetch_result.data_age_days,
        data_quality=quality,
        latest_bar_date=fetch_result.latest_date,
        bars_available=fetch_result.bars,
        strategy_id=sid, strategy_name=strategy.name,
        regime=strategy.best_regime,
        technical_score=round(perf_score, 1),
        historical_evidence_adjustment=round(learning_adj, 2),
        calibrated_confidence=round(final_conf, 1),
        opportunity_score=round(opp_score, 1),
        entry_price=round(price, 2), stop_loss=round(stop_loss, 2),
        target_price=round(target, 2), rr_ratio=rr_ratio,
        expected_holding_days=_holding_days(sid),
        gate_price={"passed": price_ok, "reason": price_reason},
        gate_data_quality={"passed": quality_ok or quality in PAPER_ELIGIBLE_QUALITIES,
                           "reason": quality_reason},
        gate_rr={"passed": rr_ok, "reason": rr_reason},
        gate_volume={"passed": vol_ok, "reason": vol_reason},
        final_action=action, heat=heat,
        all_gates_passed=all_gates,
        paper_eligible=paper_eligible,
        paper_order_id=paper_order_id,
        paper_order_note=paper_note,
        win_rate=metrics.get("win_rate", 0.0),
        profit_factor=min(metrics.get("profit_factor", 0.0), 999.0),
        net_pnl_pct=metrics.get("net_pnl_pct", 0.0),
        total_trades=metrics.get("total_trades", 0),
        low_evidence=metrics.get("total_trades", 0) < 5,
        adx=round(float(last_row.get("adx", 0.0) or 0.0), 1),
        rsi=round(float(last_row.get("rsi", 0.0) or 0.0), 1),
        volume_ratio=round(vol_ratio, 2),
        above_ema20=bool(price > float(last_row.get("ema20", 0.0) or 0.0) > 0),
        above_ema50=bool(price > float(last_row.get("ema50", 0.0) or 0.0) > 0),
        error=None,
    )
    rec._stage_ts = dict(stage_ts)  # type: ignore[attr-defined]
    return rec


def _set_progress(stage: Optional[str], scan_id: Optional[str] = None,
                  extra: Optional[Dict[str, Any]] = None) -> None:
    """Publish live scan progress to the durable KV so the UI can show the
    active scan (stage + elapsed). stage=None clears it. Never raises."""
    try:
        import phase20_store
        if stage is None:
            phase20_store.kv_set("scan_progress", None)
            return
        rec: Dict[str, Any] = {
            "stage": stage,
            "scan_id": scan_id,
            "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        if extra:
            rec.update(extra)
        prev = phase20_store.kv_get("scan_progress") or {}
        rec["started_at"] = (prev.get("started_at")
                             if isinstance(prev, dict) and prev.get("scan_id") == scan_id
                             else rec["updated_at"])
        phase20_store.kv_set("scan_progress", rec)
    except Exception:
        pass


def derive_symbol_events(recs: List[Phase7Recommendation], scan_id: str,
                         mode: str = "LIVE",
                         run_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """
    Derive per-symbol pipeline events from authoritative recommendations.

    Shared by LIVE scans and the Phase 23 Historical Backtest Engine so both
    modes emit IDENTICAL event shapes from the same code path — counts can
    never diverge from the scan by construction.
    """
    batch: List[Dict[str, Any]] = []
    for r in recs:
        base: Dict[str, Any] = {"scan_id": scan_id, "symbol": r.symbol,
                                "mode": mode}
        if run_id:
            base["run_id"] = run_id
        # True per-stage processing timestamps recorded by _scan_one
        # (non-dataclass attr — absent on synthetic recs; events then fall
        # back to insert time in pipeline_events).
        st: Dict[str, str] = getattr(r, "_stage_ts", None) or {}

        def _ev(event_type: str, stage: str, payload: Dict[str, Any]) -> Dict[str, Any]:
            ev = {**base, "event_type": event_type, "stage": stage,
                  "payload": payload}
            if st.get(stage):
                ev["ts"] = st[stage]
            return ev

        if r.error is not None:
            batch.append(_ev("SYMBOL_REJECTED", "SCANNER",
                             {"error": r.error,
                              "data_quality": r.data_quality}))
            continue
        batch.append(_ev("SYMBOL_SCANNED", "SCANNER",
                         {"data_quality": r.data_quality,
                          "bars": r.bars_available,
                          "rsi": r.rsi, "adx": r.adx,
                          "volume_ratio": r.volume_ratio}))
        batch.append(_ev("RESEARCH_COMPLETED", "RESEARCH",
                         {"win_rate": r.win_rate,
                          "profit_factor": r.profit_factor,
                          "total_trades": r.total_trades,
                          "low_evidence": r.low_evidence}))
        batch.append(_ev("MARKET_INTELLIGENCE_COMPLETED", "MARKET_INTELLIGENCE",
                         {"regime": r.regime, "sector": r.sector}))
        batch.append(_ev("MONITORING_COMPLETED", "MONITORING",
                         {"above_ema20": r.above_ema20,
                          "above_ema50": r.above_ema50}))
        if r.strategy_id:
            batch.append(_ev("STRATEGY_SELECTED", "STRATEGY",
                             {"strategy_id": r.strategy_id,
                              "strategy_name": r.strategy_name,
                              "technical_score": r.technical_score}))
        else:
            batch.append(_ev("STRATEGY_REJECTED", "STRATEGY",
                             {"reason": "No viable strategy"}))
        gates = {"price": r.gate_price, "data_quality": r.gate_data_quality,
                 "rr": r.gate_rr, "volume": r.gate_volume}
        failed = {k: v for k, v in gates.items() if not (v or {}).get("passed")}
        if r.all_gates_passed:
            batch.append(_ev("RISK_APPROVED", "RISK",
                             {"gates": gates, "rr_ratio": r.rr_ratio}))
        else:
            batch.append(_ev("RISK_REJECTED", "RISK",
                             {"failed_gates": failed,
                              "rr_ratio": r.rr_ratio,
                              "confidence": r.calibrated_confidence}))
        act = r.final_action
        et = ("BUY_GENERATED" if act in ("BUY", "STRONG BUY")
              else "WATCH_GENERATED" if act == "WATCH" else "IGNORE_GENERATED")
        batch.append(_ev(et, "AI_DECISION",
                         {"action": act,
                          "confidence": r.calibrated_confidence,
                          "opportunity_score": r.opportunity_score,
                          "paper_eligible": r.paper_eligible}))
    return batch


def run_live_scan(
    symbols: Optional[List[str]] = None,
    capital: float = INITIAL_CAPITAL,
    force: bool = False,
    heartbeat: Optional[Any] = None,
) -> Phase7ScanResult:
    """
    Run a full Phase 7 canonical scan.
    1. Generate scan_id + snapshot_ts once (audit trail).
    2. Fetch ALL symbols up-front (consistent snapshot).
    3. Analyse each symbol using its fetched data.
    4. Apply safety gates, build recommendations.
    5. Compute provider health report.
    6. Return a single Phase7ScanResult (JSON-serialisable).

    This is the ONE authoritative source consumed by all pages:
    Trade Decisions, Market Scanner, AI Decision, Dashboard, Portfolio Manager.
    """
    scan_id = uuid.uuid4().hex[:12]
    snapshot_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    universe = sorted(symbols if symbols else list(NIFTY_50))
    t0 = time.monotonic()

    if _log:
        _log.info("scan_start", scan_id=scan_id,
                  snapshot_ts=snapshot_ts, symbols_total=len(universe))

    # Phase 23: canonical pipeline event stream (fail-safe, never breaks scan)
    try:
        from pipeline_events import emit as _pe_emit, emit_many as _pe_emit_many
    except Exception:
        _pe_emit = lambda *a, **k: None          # type: ignore
        _pe_emit_many = lambda *a, **k: None     # type: ignore
    _pe_emit("SCAN_STARTED", "SUPERVISOR", scan_id=scan_id,
             payload={"snapshot_ts": snapshot_ts, "universe_size": len(universe)})

    # ── Phase 1: Fetch all data up-front (consistent snapshot) ────────────────
    _set_progress("FETCHING", scan_id, {"symbols_total": len(universe),
                                        "symbols_done": 0})
    provider = LiveDataProvider()
    _last_beat = time.monotonic()
    t_fetch0 = time.monotonic()

    def _fetch_progress(done: int, total: int) -> None:
        # Heartbeat: renew the distributed scan lease + progress every ~25s
        # so a slow fetch (provider retries) never loses its lock mid-run.
        nonlocal _last_beat
        if time.monotonic() - _last_beat > 25:
            _last_beat = time.monotonic()
            if heartbeat is not None:
                try:
                    heartbeat()
                except Exception:
                    pass
            _set_progress("FETCHING", scan_id, {"symbols_total": total,
                                                "symbols_done": done})

    # Phase 22: bulk multi-ticker download (one call for the whole universe)
    # with per-symbol retry fallback for stragglers — full coverage, but no
    # longer 50 serial calls × retries (the 900s production scan root cause).
    fetch_results: Dict[str, SymbolFetchResult] = provider.fetch_batch(
        universe, progress_cb=_fetch_progress)
    fetch_s = round(time.monotonic() - t_fetch0, 2)

    fetch_done_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _pe_emit("SCAN_FETCH_COMPLETED", "SCANNER", scan_id=scan_id, payload={
        "fetch_s": fetch_s,
        "symbols_requested": len(universe),
        "symbols_received": sum(1 for r in fetch_results.values() if r.success),
        "symbols_failed": sum(1 for r in fetch_results.values() if not r.success),
    })

    # ── Phase 2: Analyse each symbol ─────────────────────────────────────────
    _set_progress("ANALYZING", scan_id)
    if heartbeat is not None:
        try:
            heartbeat()
        except Exception:
            pass
    t_analysis0 = time.monotonic()
    recs: List[Phase7Recommendation] = []
    for sym in universe:
        fr = fetch_results.get(sym.upper())
        if fr is None:
            # Should never happen but handle defensively
            from live_data_provider import SymbolFetchResult, DataQuality, PROVIDER_ID
            fr = SymbolFetchResult(symbol=sym.upper(), success=False, df=None,
                                   latest_date=None, data_age_days=None,
                                   data_quality=DataQuality.UNAVAILABLE,
                                   data_source=PROVIDER_ID,
                                   fetch_ts=snapshot_ts, fetch_latency_ms=0,
                                   retries_used=0, error="Symbol missing from fetch batch",
                                   bars=0)
        recs.append(_scan_one(sym, fr, scan_id, snapshot_ts, capital))

    analysis_s = round(time.monotonic() - t_analysis0, 2)

    # Phase 23: per-symbol pipeline events derived from each recommendation —
    # one batch insert (never 50 round-trips), emitted from the authoritative
    # scan result itself so counts can never diverge from the scan.
    try:
        _pe_emit_many(derive_symbol_events(recs, scan_id))
    except Exception:
        pass

    # Sort by opportunity_score desc (errors last)
    recs.sort(key=lambda r: (r.error is None, r.opportunity_score), reverse=True)
    for i, r in enumerate(recs, start=1):
        # rank is stored outside the dataclass to avoid mutation; inject into dict later
        pass

    # ── Phase 3: Provider health ──────────────────────────────────────────────
    health: ProviderHealth = provider.build_health_report(
        fetch_results, scan_id, snapshot_ts)

    # ── Phase 4: Summary ──────────────────────────────────────────────────────
    valid = [r for r in recs if r.error is None]
    strong_buy = sum(1 for r in valid if r.final_action == "STRONG BUY")
    buy        = sum(1 for r in valid if r.final_action == "BUY")
    watch      = sum(1 for r in valid if r.final_action == "WATCH")
    ignore     = sum(1 for r in valid if r.final_action == "IGNORE")
    paper_elig = sum(1 for r in valid if r.paper_eligible)
    gates_all  = sum(1 for r in valid if r.all_gates_passed)

    quality_counts: Dict[str, int] = {}
    for r in recs:
        quality_counts[r.data_quality] = quality_counts.get(r.data_quality, 0) + 1

    avg_score = round(sum(r.opportunity_score for r in valid) / len(valid), 1) if valid else 0.0
    best = valid[0] if valid else None

    scan_complete_ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    duration_s = round(time.monotonic() - t0, 2)

    summary = {
        "scan_id": scan_id, "snapshot_ts": snapshot_ts,
        "universe_size": len(universe), "symbols_analysed": len(recs),
        "symbols_with_errors": sum(1 for r in recs if r.error),
        "strong_buy_count": strong_buy, "buy_count": buy,
        "watch_count": watch, "ignore_count": ignore,
        "paper_eligible_count": paper_elig,
        "all_gates_passed_count": gates_all,
        "avg_opportunity_score": avg_score,
        "best_stock": best.symbol if best else None,
        "best_stock_score": best.opportunity_score if best else None,
        "data_quality_breakdown": quality_counts,
        "duration_s": duration_s,
        "label": "PAPER / LIVE DATA VALIDATION",
    }

    # ── Phase 5: Scan audit ───────────────────────────────────────────────────
    # Prove that one consistent snapshot was used throughout.
    all_snapshot_ts = list({r.snapshot_ts for r in recs})
    all_scan_ids = list({r.scan_id for r in recs})
    audit = {
        "scan_id": scan_id, "snapshot_ts": snapshot_ts,
        "fetch_completed_ts": fetch_done_ts,
        "scan_completed_ts": scan_complete_ts,
        "all_items_share_same_snapshot_ts": len(all_snapshot_ts) == 1,
        "all_items_share_same_scan_id": len(all_scan_ids) == 1,
        "distinct_snapshot_ts_count": len(all_snapshot_ts),
        "distinct_scan_id_count": len(all_scan_ids),
        "data_fetched_before_analysis": True,   # enforced by design
        "no_lookahead": "Data is fetched from yfinance using max_data_timestamp patterns; "
                        "all bars available before analysis began.",
        "audit_verdict": "PASS" if (len(all_snapshot_ts) == 1 and len(all_scan_ids) == 1) else "FAIL",
    }

    overall_paper_eligible = health.paper_execution_eligible and paper_elig > 0

    # ── Phase 19: Kite provider label (read-only overlay metadata) ────────────
    t_auth0 = time.monotonic()
    try:
        from kite_quote_provider import kite_session_verified, provider_label as _pl
        # PROVEN session only — an expired token must never mark the scan as
        # Kite-connected (live LTP overlay would let fallback data pass the entry gate).
        _kite_live = kite_session_verified()
        _provider_label = _pl()
    except Exception:
        _kite_live = False
        _provider_label = "Yahoo Finance (History)"
    auth_s = round(time.monotonic() - t_auth0, 2)

    safety = {
        "research_only": True,
        "paper_trading_only": True,
        "no_live_broker_calls": True,
        "no_real_orders": True,
        "no_auto_strategy_promotion": True,
        "meta_learning_affects_decisions": False,
        "kite_connected": _kite_live,
        "data_provider": _provider_label,
        "ohlcv_source": "yfinance (historical)",
        "live_quote_source": "Kite Connect (LTP overlay)" if _kite_live else "Not configured",
        "note": "Phase 7 is paper trading and research only. No real broker API "
                "is called. No real money is at risk. Meta-Learning and Strategy "
                "Evolution findings do not affect live decisions unless a future "
                "human-approved phase explicitly enables them.",
    }

    rec_dicts = []
    for i, r in enumerate(recs, start=1):
        d = asdict(r)
        d["rank"] = i
        rec_dicts.append(d)

    # Stage timing breakdown (seconds). "analysis" covers indicator
    # computation + decision generation per symbol (they run interleaved in
    # _scan_one and cannot be split without double-instrumenting strategies).
    timings: Dict[str, Any] = {
        "fetch_s": fetch_s,
        "analysis_s": analysis_s,
        "provider_auth_s": auth_s,
        "total_scan_s": duration_s,
        "symbols": len(universe),
        "retry_events": int(health.retry_events or 0),
        "symbols_fallback_fetched": sum(
            1 for r in fetch_results.values()
            if getattr(r, "via_fallback", False)),
        "symbols_failed": sum(
            1 for r in fetch_results.values() if not r.success),
    }

    result = Phase7ScanResult(
        scan_id=scan_id, snapshot_ts=snapshot_ts,
        universe=universe, universe_size=len(universe),
        duration_s=duration_s,
        provider_health=asdict(health),
        recommendations=rec_dicts,
        summary=summary, scan_audit=audit,
        paper_eligible=overall_paper_eligible,
        safety=safety,
        timings=timings,
    )

    # ── Persist cache (Phase 19B: durable shared store + local warm cache) ───
    _set_progress("PERSISTING", scan_id)
    if heartbeat is not None:
        try:
            heartbeat()
        except Exception:
            pass
    t_persist0 = time.monotonic()
    try:
        cache_data = asdict(result)
        from scan_state_store import save_successful_scan
        save_successful_scan(cache_data)
    except Exception:
        # Last-resort local write so at least this instance keeps the result.
        try:
            with open(SCAN_CACHE_FILE, "w") as f:
                json.dump(asdict(result), f, default=str)
        except Exception:
            pass
    result.timings["db_write_s"] = round(time.monotonic() - t_persist0, 2)

    _pe_emit("SCAN_COMPLETED", "SUPERVISOR", scan_id=scan_id, payload={
        "duration_s": duration_s, "universe_size": len(universe),
        "buy_count": buy + strong_buy, "watch_count": watch,
        "ignore_count": ignore, "paper_eligible_count": paper_elig,
        "symbols_with_errors": summary["symbols_with_errors"],
        "timings": timings,
    })
    # Retention: keep the event table bounded under continuous operation.
    try:
        from pipeline_events import prune_events
        prune_events()
    except Exception:
        pass

    # ── Phase 15: sync derived caches to this canonical scan ─────────────────
    # AI Decision / Opportunity caches are overlaid with canonical values so
    # every page reads the exact same numbers from the same scan_id.
    try:
        from phase15_sync import sync_derived_caches
        sync_derived_caches()
    except Exception:
        pass

    # ── Phase 18: auto-create/refresh today's research-notebook draft ────────
    # Read-only journaling of what the scan saw. Never affects the scan result
    # or any trading behaviour; failures are swallowed silently.
    try:
        from phase18_notebook import ensure_today_entry
        ensure_today_entry()
    except Exception:
        pass

    # ── Phase 11 price snapshots — persist current_price per open position ────
    # Gives sparklines 6-16 intraday data points instead of 2 (sparse events).
    # Failures are non-fatal and do not affect the scan result.
    try:
        from phase11_autonomous import record_price_snapshots as _rps
        _rps(scan_id=scan_id)
    except Exception:
        pass

    return result


def load_cached_scan() -> Optional[Dict[str, Any]]:
    """
    Load the most recent scan result. Phase 19B: prefers the durable shared
    store (Postgres) so every Autoscale instance sees the same latest scan;
    falls back to the local disk cache.
    """
    try:
        from scan_state_store import load_latest_snapshot
        snap = load_latest_snapshot()
        if snap:
            return snap
    except Exception:
        pass
    try:
        with open(SCAN_CACHE_FILE) as f:
            return json.load(f)
    except Exception:
        return None


def get_or_run_scan(
    max_age_s: float = 600,
    symbols: Optional[List[str]] = None,
    capital: float = INITIAL_CAPITAL,
    force: bool = False,
    wait_for_lock: bool = True,
) -> Dict[str, Any]:
    """
    Return cached scan if fresh enough, otherwise run a new scan.
    All callers (Trade Decisions, Market Scanner, etc.) call this —
    they all receive the SAME canonical result.

    wait_for_lock=False (used by the scheduler): if another instance holds
    the scan lease, return the previous snapshot immediately with
    _scan_lock_busy=True instead of polling — the tick records
    SKIPPED_ACTIVE_SCAN rather than inflating its own duration.
    """
    if not force:
        cached = load_cached_scan()
        if cached:
            try:
                snap_ts = cached.get("snapshot_ts", "")
                snap_dt = datetime.fromisoformat(snap_ts.replace("Z", "+00:00"))
                age = (datetime.now(timezone.utc) - snap_dt).total_seconds()
                if age < max_age_s:
                    cached["_from_cache"] = True
                    cached["_cache_age_s"] = round(age, 1)
                    return cached
            except Exception:
                pass

    # ── Phase 19B: distributed scan lease (Autoscale-safe) ────────────────
    # Only one instance runs the scan; others join the result. An expired
    # lease is reclaimed automatically (stuck-lock recovery).
    try:
        from scan_state_store import (
            acquire_scan_lock, release_scan_lock, record_failed_scan,
            renew_scan_lock,
        )
    except Exception:
        acquire_scan_lock = None  # type: ignore[assignment]

    if acquire_scan_lock is None:
        result = run_live_scan(symbols=symbols, capital=capital, force=force)
        d = asdict(result)
        d["_from_cache"] = False
        d["_cache_age_s"] = 0.0
        return d

    prev = load_cached_scan()
    prev_scan_id = (prev or {}).get("scan_id")

    t_lock0 = time.monotonic()
    acquired, holder = acquire_scan_lock()
    if not acquired:
        if not wait_for_lock:
            # Scheduler path: never poll — report busy immediately.
            if prev:
                prev["_from_cache"] = True
                prev["_scan_lock_busy"] = True
                return prev
            return {"_scan_lock_busy": True, "_from_cache": True,
                    "scan_id": None, "snapshot_ts": None}
        # Another instance is scanning. Poll for its result instead of
        # duplicating work; fall back to the previous snapshot on timeout.
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            time.sleep(3)
            latest = load_cached_scan()
            if latest and latest.get("scan_id") != prev_scan_id:
                latest["_from_cache"] = True
                latest["_joined_inflight_scan"] = True
                latest["_lock_wait_s"] = round(time.monotonic() - t_lock0, 2)
                return latest
        if prev:
            prev["_from_cache"] = True
            prev["_scan_lock_busy"] = True
            prev["_lock_wait_s"] = round(time.monotonic() - t_lock0, 2)
            return prev
        raise RuntimeError("Scan lock busy and no previous snapshot available")
    lock_wait_s = round(time.monotonic() - t_lock0, 2)

    def _beat() -> None:
        try:
            renew_scan_lock(holder)
        except Exception:
            pass

    try:
        result = run_live_scan(symbols=symbols, capital=capital, force=force,
                               heartbeat=_beat)
    except Exception as exc:
        # Failed scan must NEVER overwrite the last successful snapshot —
        # run_live_scan only persists on success, so just record the failure.
        try:
            record_failed_scan(str(exc))
        except Exception:
            pass
        raise
    finally:
        try:
            release_scan_lock(holder)
        except Exception:
            pass
        _set_progress(None)

    d = asdict(result)
    d["_from_cache"] = False
    d["_cache_age_s"] = 0.0
    d.setdefault("timings", {})["lock_wait_s"] = lock_wait_s
    return d
