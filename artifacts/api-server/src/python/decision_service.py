"""
decision_service.py
Decision Service — combines the existing scanner, expectancy, adaptive
learning and paper-portfolio outputs into ONE clear recommendation per stock.

Recommendations: STRONG_BUY | BUY | WATCH | EXIT | AVOID

Rules (deterministic, reproducible — no randomness):
  STRONG_BUY : final confidence >= 85, expectancy > 1%, PF >= 1.5,
               reliable sample (>= RELIABLE_SAMPLE trades), R:R >= 2,
               no hard risk filter failed
  BUY        : final confidence 75-84, expectancy > 0, PF > 1.2, R:R >= 2
  WATCH      : final confidence 55-74, or setup incomplete / weak evidence
  AVOID      : final confidence < 55, negative expectancy, poor pattern,
               or risk filter failed
  EXIT       : ONLY when a paper position is open AND an exit condition
               occurs (stop-loss hit, target hit, bearish exit signal,
               time-based exit)

Data-quality guard: if data for a stock came from the mock fallback (or the
scan errored), the service NEVER issues BUY/STRONG_BUY — the stock is shown
as DATA_UNAVAILABLE (recommendation WATCH, or EXIT checks still apply for
open positions using last known levels).

Paper trading only — no real orders. Long-only swing system (no SHORT SELL).
All heavy calculations stay in the existing engines; this module only
combines their outputs.
"""

import json
import os
from datetime import datetime, timezone
from typing import TypedDict

from config import INITIAL_CAPITAL

# ── Decision summary cache ────────────────────────────────────────────────────
# A tiny JSON file written at the end of every get_trade_decisions() call.
# ops_centre.py reads this to show the confirmed BUY count without triggering
# a fresh market scan. The file is best-effort (write failures are silent).

_SUMMARY_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "decision_summary_cache.json")

# ── Decision thresholds ───────────────────────────────────────────────────────

RELIABLE_SAMPLE    = 20     # min historical trades for a reliable sample
STRONG_BUY_CONF    = 85.0
BUY_CONF           = 75.0
WATCH_CONF         = 55.0
TIME_EXIT_FACTOR   = 2.0    # exit when held > factor × expected holding days
TIME_EXIT_MIN_DAYS = 30.0   # ... but never earlier than this many days

_ORDER = {"STRONG_BUY": 0, "BUY": 1, "EXIT": 2, "WATCH": 3, "AVOID": 4}

# Decision Breakdown display weights — how much of the final confidence is
# attributed to each factor (explanatory only; never changes the decision).
_BREAKDOWN_WEIGHTS = [
    ("Technical Analysis",  0.35),
    ("Historical Pattern",  0.25),
    ("Sector Strength",     0.10),
    ("Market Regime",       0.10),
    ("Risk/Reward",         0.10),
    ("Volume Confirmation", 0.05),
    ("Data Quality",        0.05),
]


class DecisionFactor(TypedDict):
    factor: str
    score: float           # underlying signal strength 0-100
    contribution: float    # points contributed to the final confidence


class TradeDecision(TypedDict):
    stock: str
    sector: str
    recommendation: str          # STRONG_BUY | BUY | WATCH | EXIT | AVOID
    data_status: str             # OK | DATA_UNAVAILABLE
    low_reliability: bool
    low_evidence: bool           # True when scanner total_trades < 5 (insufficient backtest)
    total_trades: int            # 6-month backtest trade count from the scanner
    invalidation_override: bool        # True when fc >= BUY_CONF but a gate (filter/expectancy) forced WATCH/AVOID
    invalidation_override_conditions: list  # human-readable list of the blocking conditions
    # Confidence
    base_confidence: float
    learning_adjustment: float
    final_confidence: float
    # v2.0 Adaptive Self-Evaluation model (bounded, versioned, rollback-able)
    model_version: int
    model_adjustment: float
    # v2.1 Evidence-Based Research (similarity engine — bounded, explainable)
    similarity_adjustment: float
    evidence_reliability: str    # VERY_LOW | LOW | MEDIUM | HIGH
    similarity_evidence: dict | None
    # Historical evidence
    historical_expectancy: float
    historical_profit_factor: float
    historical_win_rate: float
    historical_sharpe: float
    historical_kelly: float
    pattern_match_pct: float
    historical_trades: int
    best_pattern: str
    regime_match: bool
    # Trade levels
    price: float
    entry_price: float
    stop_loss: float
    target: float
    rr_ratio: float
    expected_holding_days: float
    expected_drawdown: float
    # Position (paper)
    position_open: bool
    position_quantity: int
    position_avg_price: float
    position_pnl_pct: float
    exit_reason: str
    # Explanations
    reason: str                  # short one-liner for the table
    explanation: str             # longer text for the expanded row
    explanation_sections: dict   # structured, single-source evidence sections
    failed_conditions: list
    breakdown: list              # list[DecisionFactor] summing to final_confidence
    # v2.3 Analyst Reasoning and Decision Invalidation Layer
    analyst_summary: str
    current_observation: str
    historical_assessment: str
    decision_reasoning: str
    invalidation_conditions: list
    upgrade_conditions: list
    invalidation_met: int
    upgrade_met: int
    decision_state: str          # VALID | WEAKENING | INVALIDATED | IMPROVING | EXPIRED | DATA_LIMITED
    decision_timestamp: str
    valid_until: str | None
    validity_note: str
    conflict_level: str          # NONE | LOW | MEDIUM | HIGH
    conflict_explanation: str
    missing_data_fields: list


def _last_buy_meta(trades: list, symbol: str) -> dict:
    """Most recent BUY record for `symbol` (holds stop/target metadata)."""
    for tr in reversed(trades or []):
        if tr.get("symbol", "").upper() == symbol.upper() and tr.get("action") == "BUY":
            return tr
    return {}


# ── Confidence calibration (Phase 1) ─────────────────────────────────────────

_CALIBRATOR_CACHE: dict = {"cal": None, "loaded_at": 0.0}
_CALIBRATOR_TTL = 300.0  # re-read the persisted calibrator every 5 minutes


def _active_calibrator() -> dict | None:
    """Cached active calibrator (fitted from historical knowledge trades)."""
    import time as _time
    now = _time.time()
    if (_CALIBRATOR_CACHE["cal"] is None
            or now - _CALIBRATOR_CACHE["loaded_at"] > _CALIBRATOR_TTL):
        try:
            from confidence_calibration import get_or_fit_calibrator
            _CALIBRATOR_CACHE["cal"] = get_or_fit_calibrator()
        except Exception:
            _CALIBRATOR_CACHE["cal"] = None
        _CALIBRATOR_CACHE["loaded_at"] = now
    return _CALIBRATOR_CACHE["cal"]


def _calibration_fields(final_confidence: float) -> dict:
    """raw confidence + calibrated probability + method/version for ONE
    prediction. Falls back to identity (raw/100) when no calibrator exists."""
    try:
        from confidence_calibration import calibrate_prediction
        return calibrate_prediction(_active_calibrator(), final_confidence)
    except Exception:
        p = max(0.0, min(1.0, float(final_confidence or 0.0) / 100.0))
        return {
            "raw_confidence": round(float(final_confidence or 0.0), 1),
            "calibrated_probability": round(p, 6),
            "calibrated_confidence": round(p * 100.0, 1),
            "calibration_method": "identity",
            "calibration_version": 0,
        }


def _held_days(buy_meta: dict) -> float:
    ts = buy_meta.get("timestamp", "")
    try:
        opened = datetime.fromisoformat(str(ts).replace("Z", "+00:00")).replace(tzinfo=None)
        return max(0.0, (datetime.now() - opened).total_seconds() / 86400.0)
    except Exception:
        return 0.0


def _check_exit(item: dict, pos: dict, buy_meta: dict) -> str:
    """Return exit reason string, or '' when no exit condition triggered."""
    price = float(item.get("price", 0.0) or 0.0)
    if price <= 0:
        return ""

    stop   = float(buy_meta.get("stop_loss", 0.0) or 0.0)
    target = float(buy_meta.get("target", 0.0) or 0.0)

    if stop > 0 and price <= stop:
        return f"Stop-loss hit — price ₹{price:.2f} is at/below stop ₹{stop:.2f}"
    if target > 0 and price >= target:
        return f"Target hit — price ₹{price:.2f} is at/above target ₹{target:.2f}"

    # Bearish exit signal: the scanner now scores this stock as a clear avoid
    # (confidence collapsed below the WATCH floor with a failed risk filter
    # or negative historical expectancy).
    fc  = float(item.get("final_confidence", item.get("confidence", 0.0)) or 0.0)
    exp = float(item.get("historical_expectancy", 0.0) or 0.0)
    if item.get("error") is None and fc < WATCH_CONF and (
        not item.get("filter_passed", True) or exp < 0
    ):
        return f"Bearish exit signal — confidence fell to {fc:.0f} with weak setup"

    # Time-based exit: held far beyond the pattern's expected holding period.
    held = _held_days(buy_meta)
    expected = float(item.get("expected_holding_days", 0.0) or 0.0)
    limit = max(TIME_EXIT_MIN_DAYS, TIME_EXIT_FACTOR * expected) if expected > 0 else TIME_EXIT_MIN_DAYS
    if held > limit:
        return f"Time-based exit — held {held:.0f} days (limit {limit:.0f} days)"

    return ""


def _build_breakdown(item: dict, data_ok: bool, regime_strength: float,
                     final_confidence: float) -> list:
    """
    Decompose the final confidence into labeled factor contributions.
    Purely explanatory — built from signals the engines already computed,
    scaled so the contributions sum exactly to the final confidence.
    Deterministic: same inputs always produce the same breakdown.
    """
    ob = item.get("opportunity_breakdown") or {}
    technical = float(item.get("base_confidence", item.get("confidence", 0.0)) or 0.0)
    exp_sc = float(ob.get("expectancy_score", 50.0) or 0.0)
    pf_sc  = float(ob.get("pf_score", 50.0) or 0.0)
    historical = (exp_sc + pf_sc) / 2.0
    sector = float(ob.get("sector_strength_score", 0.0) or 0.0)
    rr = float(item.get("rr_ratio", 0.0) or 0.0)
    rr_score = max(0.0, min(100.0, rr / 3.0 * 100.0))
    vol_ratio = float(item.get("volume_ratio", 0.0) or 0.0)
    vol_score = max(0.0, min(100.0, vol_ratio / 2.0 * 100.0))
    dq_score = 100.0 if data_ok else 0.0

    scores = {
        "Technical Analysis":  max(0.0, min(100.0, technical)),
        "Historical Pattern":  max(0.0, min(100.0, historical)),
        "Sector Strength":     max(0.0, min(100.0, sector)),
        "Market Regime":       max(0.0, min(100.0, regime_strength)),
        "Risk/Reward":         rr_score,
        "Volume Confirmation": vol_score,
        "Data Quality":        dq_score,
    }

    raw = [(name, w * scores[name]) for name, w in _BREAKDOWN_WEIGHTS]
    total_raw = sum(v for _, v in raw)

    breakdown: list[DecisionFactor] = []
    if total_raw <= 0 or final_confidence <= 0:
        for name, _ in _BREAKDOWN_WEIGHTS:
            breakdown.append(DecisionFactor(
                factor=name, score=round(scores[name], 1), contribution=0.0))
        return breakdown

    scale = final_confidence / total_raw
    contributions = [round(v * scale, 1) for _, v in raw]
    # Fix rounding drift so the column sums exactly to the final confidence.
    drift = round(final_confidence - sum(contributions), 1)
    if drift != 0:
        idx = max(range(len(contributions)), key=lambda i: contributions[i])
        corrected = round(contributions[idx] + drift, 1)
        # Defensive: never let drift correction push a contribution negative.
        contributions[idx] = max(0.0, corrected)

    for (name, _), contrib in zip(raw, contributions):
        breakdown.append(DecisionFactor(
            factor=name, score=round(scores[name], 1), contribution=contrib))
    return breakdown


def _decide(item: dict, positions: dict, trades: list,
            regime_strength: float = 50.0,
            model_weights: dict | None = None,
            model_version: int = 0,
            regime_now_hint: str = "") -> TradeDecision:
    sym    = str(item.get("stock", "")).upper()
    err    = item.get("error")
    fc     = float(item.get("final_confidence", item.get("confidence", 0.0)) or 0.0)
    base   = float(item.get("base_confidence", item.get("confidence", 0.0)) or 0.0)
    adj    = float(item.get("learning_adjustment", 0.0) or 0.0)
    exp    = float(item.get("historical_expectancy", 0.0) or 0.0)
    pf     = float(item.get("historical_profit_factor", 0.0) or 0.0)
    wr     = float(item.get("historical_win_rate", 0.0) or 0.0)
    n_hist       = int(item.get("historical_trades", 0) or 0)
    n_scan_trades = int(item.get("total_trades", 0) or 0)
    rr           = float(item.get("rr_ratio", 0.0) or 0.0)
    price  = float(item.get("price", 0.0) or 0.0)
    filter_passed = bool(item.get("filter_passed", False))
    filter_reasons = list(item.get("filter_reasons", []) or [])

    # Data quality: scan error OR mock fallback data => never BUY/STRONG_BUY.
    try:
        from market_data_engine import get_last_source
        source = get_last_source(sym)
    except Exception:
        source = "unknown"
    # Only trust explicitly-tracked live data; "mock" or "unknown" both block buys.
    data_ok = err is None and source == "yfinance"

    # Current regime compatibility
    try:
        from adaptive_learning import current_market_regime
        regime_now = current_market_regime()
    except Exception:
        regime_now = "Neutral"
    regime_match = str(item.get("best_regime", "")).lower() in str(regime_now).lower() \
        or str(regime_now).lower() in str(item.get("best_regime", "")).lower()

    # ── v2.0 Adaptive Self-Evaluation model modifier ─────────────────────────
    # Bounded (±15 total), versioned and rollback-able. Applied ONLY to the
    # confidence number. It can NEVER override hard risk filters (the
    # data-quality and filter_passed gates below run regardless) and can
    # NEVER create a BUY on its own (guarded in the recommendation logic).
    model_adj = 0.0
    if model_weights:
        try:
            from model_versioning import modifier_for, confidence_band
            from predictive_intelligence import (rsi_bucket, adx_bucket,
                                                 volume_bucket)
            _vol = item.get("volatility")
            _vol_regime = ("high" if float(_vol) >= 22.0
                           else "low" if float(_vol) <= 8.0
                           else "normal") if _vol is not None else ""
            model_adj, _scopes = modifier_for({
                "strategy_id": item.get("best_strategy_id", ""),
                "symbol": sym,
                "sector": item.get("sector", ""),
                "regime": regime_now,
                "pattern": (f"{item.get('best_strategy_name', '')} · "
                            f"{item.get('sector', '')} · {item.get('best_regime', '')}"),
                "confidence_band": confidence_band(fc),
                # v2.1 hypothesis combo scopes (band dimensions)
                "rsi_band": rsi_bucket(item.get("rsi")),
                "adx_band": adx_bucket(item.get("adx")),
                "volume_band": volume_bucket(item.get("volume_ratio")),
                "volatility_regime": _vol_regime,
            }, model_weights)
        except Exception:
            model_adj = 0.0
    fc_raw = fc                       # confidence BEFORE the v2 model modifier
    fc = round(max(0.0, min(100.0, fc + model_adj)), 1)

    # ── v2.1 Evidence-Based Research (similarity engine) modifier ────────────
    # Bounded (+10 max / -15 max), deterministic and fully explainable.
    # Applied AFTER the v2 model modifier, ONLY to the confidence number.
    # It can NEVER override hard risk filters (data-quality and filter gates
    # run regardless) and can NEVER create a BUY on its own — the fc_raw
    # guard below requires the confidence BEFORE both modifiers to also
    # clear the recommendation bar. Final confidence stays within 5-95.
    sim_adj = float(item.get("similarity_adjustment", 0.0) or 0.0)
    evidence_reliability = str(item.get("evidence_reliability", "") or "VERY_LOW")
    similarity_evidence = item.get("similarity_evidence")
    if sim_adj != 0.0:
        fc = round(max(5.0, min(95.0, fc + sim_adj)), 1)

    low_reliability = n_hist < RELIABLE_SAMPLE
    low_evidence    = n_scan_trades < 5   # scanner backtest has too few trades for reliable scoring

    pos = positions.get(sym) or {}
    position_open = bool(pos)
    buy_meta = _last_buy_meta(trades, sym) if position_open else {}
    pos_qty = int(pos.get("quantity", 0) or 0)
    pos_avg = float(pos.get("avg_price", 0.0) or 0.0)
    pos_pnl_pct = round((price - pos_avg) / pos_avg * 100.0, 2) if (pos_avg > 0 and price > 0) else 0.0

    failed: list[str] = []
    exit_reason = ""

    # ── 1. EXIT — only for open paper positions with a triggered condition ──
    if position_open:
        exit_reason = _check_exit(item, pos, buy_meta)

    if exit_reason:
        recommendation = "EXIT"
        reason = exit_reason.split("—")[0].strip()
    # ── 2. Data-quality guard ────────────────────────────────────────────────
    elif not data_ok:
        recommendation = "WATCH"
        reason = "Data unavailable — live NSE data could not be fetched" if err is None \
            else f"Data unavailable — {err}"
    # ── 3. AVOID ─────────────────────────────────────────────────────────────
    elif fc < WATCH_CONF or exp < 0 or not filter_passed:
        recommendation = "AVOID"
        if not filter_passed:
            reason = "Risk filter failed" + (f": {filter_reasons[0]}" if filter_reasons else "")
        elif exp < 0:
            reason = f"Negative historical expectancy ({exp:+.2f}%)"
        else:
            reason = f"Low confidence ({fc:.0f} < {WATCH_CONF:.0f})"
    else:
        # ── 4. STRONG_BUY / BUY / WATCH ──────────────────────────────────────
        if fc < STRONG_BUY_CONF:
            failed.append(f"Confidence {fc:.0f} < {STRONG_BUY_CONF:.0f} needed for STRONG BUY")
        if exp <= 1.0:
            failed.append(f"Expectancy {exp:+.2f}% ≤ +1% needed for STRONG BUY")
        if pf < 1.5:
            failed.append(f"Profit factor {pf:.2f} < 1.5 needed for STRONG BUY")
        if low_reliability:
            failed.append(f"Only {n_hist} historical trades (< {RELIABLE_SAMPLE} for a reliable sample)")
        if rr < 2.0:
            failed.append(f"Risk/reward {rr:.1f}:1 < 2:1")

        # SAFETY: a positive v2 model adjustment can never create a buy on
        # its own — the UNADJUSTED confidence must also clear the bar.
        if (fc >= STRONG_BUY_CONF and fc_raw >= STRONG_BUY_CONF
                and exp > 1.0 and pf >= 1.5
                and not low_reliability and rr >= 2.0 and filter_passed):
            recommendation = "STRONG_BUY"
            reason = f"Confidence {fc:.0f}, expectancy {exp:+.2f}%, PF {pf:.2f}, R:R {rr:.1f}:1"
        elif (BUY_CONF <= fc < STRONG_BUY_CONF and fc_raw >= BUY_CONF
                and exp > 0 and pf > 1.2 and rr >= 2.0):
            recommendation = "BUY"
            reason = f"Confidence {fc:.0f}, expectancy {exp:+.2f}%, PF {pf:.2f}, R:R {rr:.1f}:1"
        elif fc >= WATCH_CONF:
            recommendation = "WATCH"
            if fc >= BUY_CONF:
                reason = "Confidence high but historical evidence or R:R below BUY thresholds"
            elif not item.get("live_signal", False):
                reason = "Setup incomplete — no live entry signal yet"
            elif low_reliability:
                reason = f"Weak historical evidence ({n_hist} trades)"
            else:
                reason = f"Moderate confidence ({fc:.0f})"
        else:
            recommendation = "AVOID"
            reason = f"Low confidence ({fc:.0f})"

    # ── Invalidation override detection ──────────────────────────────────────
    # Flag when high confidence (≥ BUY_CONF) is silently blocked to WATCH/AVOID
    # by a gate other than confidence itself, so operators are never in the dark.
    invalidation_override = False
    invalidation_override_conditions: list[str] = []
    if data_ok and fc >= BUY_CONF and recommendation not in ("EXIT", "STRONG_BUY", "BUY"):
        if recommendation == "AVOID":
            invalidation_override = True
            if not filter_passed:
                invalidation_override_conditions.extend(
                    filter_reasons if filter_reasons else ["risk filter failed"])
            if exp < 0:
                invalidation_override_conditions.append(
                    f"negative expectancy ({exp:+.2f}%)")
        elif recommendation == "WATCH":
            invalidation_override = True
            if fc >= STRONG_BUY_CONF:
                # fc >= 85 but STRONG_BUY conditions failed — report STRONG_BUY gates.
                # Note: BUY is not reachable when fc >= STRONG_BUY_CONF, so only
                # STRONG_BUY conditions matter here.
                if not (exp > 1.0):
                    invalidation_override_conditions.append(
                        f"expectancy {exp:+.2f}% (must be > 1% for STRONG BUY)")
                if not (pf >= 1.5):
                    invalidation_override_conditions.append(
                        f"profit factor {pf:.2f} (must be ≥ 1.5 for STRONG BUY)")
                if low_reliability:
                    invalidation_override_conditions.append(
                        f"thin historical sample ({n_hist} trades < {RELIABLE_SAMPLE} "
                        f"required for STRONG BUY)")
                if not (rr >= 2.0):
                    invalidation_override_conditions.append(
                        f"R:R {rr:.1f}:1 (must be ≥ 2:1 for STRONG BUY)")
                if not filter_passed:
                    invalidation_override_conditions.extend(
                        filter_reasons if filter_reasons else ["risk filter failed"])
                if fc_raw < STRONG_BUY_CONF:
                    invalidation_override_conditions.append(
                        f"unadjusted confidence {fc_raw:.0f} < {STRONG_BUY_CONF:.0f} "
                        f"(model/similarity adjustment cannot create STRONG BUY on its own)")
            else:
                # fc in [BUY_CONF, STRONG_BUY_CONF) but BUY sub-conditions failed
                if not (exp > 0):
                    invalidation_override_conditions.append(
                        f"expectancy {exp:+.2f}% (must be > 0 for BUY)")
                if not (pf > 1.2):
                    invalidation_override_conditions.append(
                        f"profit factor {pf:.2f} (must be > 1.2 for BUY)")
                if not (rr >= 2.0):
                    invalidation_override_conditions.append(
                        f"R:R {rr:.1f}:1 (must be ≥ 2:1 for BUY)")
                if fc_raw < BUY_CONF:
                    invalidation_override_conditions.append(
                        f"unadjusted confidence {fc_raw:.0f} < {BUY_CONF:.0f} "
                        f"(model/similarity adjustment cannot create a BUY on its own)")
        if invalidation_override and not invalidation_override_conditions:
            invalidation_override_conditions = ["blocking condition met"]

    # ── Structured explanation: every statement references exactly ONE
    #    evidence source. Three labelled sections + a final summary.
    sim_expl = str(item.get("similarity_explanation", "") or "")
    learning_expl = str(item.get("learning_explanation", "") or "")

    # Section 1 — Current Technical Analysis (scanner indicators only)
    above20 = bool(item.get("above_ema20", False))
    above50 = bool(item.get("above_ema50", False))
    st_dir = str(item.get("supertrend_dir", "") or "").upper()
    rsi_v = float(item.get("rsi", 0.0) or 0.0)
    macd_h = float(item.get("macd_hist", 0.0) or 0.0)
    vol_ratio = float(item.get("volume_ratio", 0.0) or 0.0)
    opp_score = float(item.get("opportunity_score", 0.0) or 0.0)
    trend_txt = (
        f"{'Above' if above20 else 'Below'} EMA20, "
        f"{'above' if above50 else 'below'} EMA50"
        + (f", supertrend {st_dir}" if st_dir else "")
    )
    momentum_txt = f"RSI {rsi_v:.0f}, MACD histogram {macd_h:+.2f}"
    volume_txt = (f"{vol_ratio:.1f}× 20-day average volume"
                  if vol_ratio > 0 else "No volume data")
    filters_txt = ("All risk filters passed" if filter_passed
                   else "Risk filter failed"
                   + (f": {'; '.join(filter_reasons)}" if filter_reasons else ""))
    technical_section = {
        "technical_score": round(base, 1),
        "opportunity_score": round(opp_score, 1),
        "risk_filters_passed": filter_passed,
        "risk_filter_notes": filter_reasons,
        "trend": trend_txt,
        "momentum": momentum_txt,
        "volume": volume_txt,
    }

    # Section 2 — Historical Similarity Evidence (similar past trades ONLY)
    sim_stats = (similarity_evidence or {}).get("stats") or {} \
        if isinstance(similarity_evidence, dict) else {}
    sim_matches = int((similarity_evidence or {}).get("match_count", 0) or 0) \
        if isinstance(similarity_evidence, dict) else 0
    sim_avg = float((similarity_evidence or {}).get("avg_similarity", 0.0) or 0.0) \
        if isinstance(similarity_evidence, dict) else 0.0
    similarity_section = {
        "match_count": sim_matches,
        "avg_similarity": round(sim_avg, 1),
        "win_rate": round(float(sim_stats.get("win_rate", 0.0) or 0.0), 1),
        "expectancy": round(float(sim_stats.get("expectancy", 0.0) or 0.0), 2),
        "profit_factor": round(float(sim_stats.get("profit_factor", 0.0) or 0.0), 2),
        "adjustment": round(sim_adj, 1),
        "reliability": evidence_reliability,
        "text": sim_expl,
    }

    # Section 3 — Pattern Knowledge (strongest historical pattern; descriptive)
    PATTERN_NOTE = ("This information is descriptive only and did not affect "
                    "the confidence adjustment.")
    pattern_section = None
    if n_hist > 0:
        pattern_section = {
            "strategy": str(item.get("best_strategy_name", "") or ""),
            "sector": str(item.get("sector", "") or ""),
            "regime": str(item.get("best_regime", "") or ""),
            "expectancy": round(exp, 2),
            "profit_factor": round(pf, 2),
            "sample_size": n_hist,
            "note": PATTERN_NOTE,
        }

    # Final Decision Summary — one line per adjustment, one source each.
    summary_section = {
        "technical_confidence": round(base, 1),
        "learning_adjustment": round(adj, 1),
        "model_adjustment": round(model_adj, 1),
        "similarity_adjustment": round(sim_adj, 1),
        "pattern_adjustment": 0.0,
        "final_confidence": round(fc, 1),
        "recommendation": recommendation,
        "learning_note": learning_expl or None,
    }

    parts = [f"{recommendation.replace('_', ' ')}: {reason}."]
    parts.append(
        f"[Current Technical Analysis] Technical score {base:.0f}, "
        f"opportunity score {opp_score:.0f}. {filters_txt}. "
        f"Trend: {trend_txt}. Momentum: {momentum_txt}. Volume: {volume_txt}."
    )
    if sim_matches > 0:
        parts.append(
            f"[Historical Similarity Evidence] {sim_matches} similar past trades "
            f"(avg similarity {sim_avg:.0f}%, {evidence_reliability.replace('_', ' ')} "
            f"reliability): win rate {similarity_section['win_rate']:.0f}%, "
            f"expectancy {similarity_section['expectancy']:+.2f}%, "
            f"PF {similarity_section['profit_factor']:.2f}. "
            f"Confidence adjustment from this evidence alone: {sim_adj:+.1f} points."
        )
    else:
        parts.append(
            "[Historical Similarity Evidence] No sufficiently similar past "
            "trades found — no similarity adjustment was applied."
        )
    if pattern_section:
        parts.append(
            f"[Pattern Knowledge] Strongest historical pattern: "
            f"{pattern_section['strategy']} in {pattern_section['sector']} "
            f"({pattern_section['regime']} regime) — expectancy {exp:+.2f}%, "
            f"PF {pf:.2f}, sample size {n_hist}. {PATTERN_NOTE}"
        )
    else:
        parts.append(
            f"[Pattern Knowledge] No historical pattern data yet. {PATTERN_NOTE}"
        )
    parts.append(
        f"[Final Decision Summary] Technical confidence {base:.0f}; "
        f"learning adjustment {adj:+.0f} (adaptive learning); "
        f"model adjustment {model_adj:+.1f} (self-evaluation model v{model_version}); "
        f"similarity adjustment {sim_adj:+.1f} (similar historical trades); "
        f"pattern adjustment +0 (descriptive only) → final confidence {fc:.0f} "
        f"(bounded 5-95). Recommendation: {recommendation.replace('_', ' ')}."
    )
    if low_reliability:
        parts.append(f"LOW RELIABILITY: fewer than {RELIABLE_SAMPLE} historical samples.")
    if not data_ok:
        parts.append("Live NSE data unavailable — no buy recommendations are issued on fallback data.")
    if position_open:
        parts.append(
            f"Open paper position: {pos_qty} shares @ ₹{pos_avg:.2f} ({pos_pnl_pct:+.2f}%)."
        )
    if learning_expl:
        parts.append(learning_expl)

    explanation_sections = {
        "technical": technical_section,
        "similarity": similarity_section,
        "pattern": pattern_section,
        "summary": summary_section,
    }

    decision = dict(
        stock=sym,
        sector=str(item.get("sector", "")),
        recommendation=recommendation,
        data_status="OK" if data_ok else "DATA_UNAVAILABLE",
        low_reliability=low_reliability,
        low_evidence=low_evidence,
        total_trades=n_scan_trades,
        invalidation_override=invalidation_override,
        invalidation_override_conditions=invalidation_override_conditions,
        base_confidence=round(base, 1),
        learning_adjustment=round(adj, 1),
        final_confidence=round(fc, 1),
        model_version=int(model_version),
        model_adjustment=round(model_adj, 1),
        similarity_adjustment=round(sim_adj, 1),
        evidence_reliability=evidence_reliability,
        similarity_evidence=similarity_evidence if isinstance(similarity_evidence, dict) else None,
        historical_expectancy=round(exp, 2),
        historical_profit_factor=round(pf, 2),
        historical_win_rate=round(wr, 1),
        historical_sharpe=round(float(item.get("historical_sharpe", 0.0) or 0.0), 2),
        historical_kelly=round(float(item.get("historical_kelly", 0.0) or 0.0), 2),
        pattern_match_pct=round(wr, 1),
        historical_trades=n_hist,
        best_pattern=(
            f"{item.get('best_strategy_name', '')} · {item.get('sector', '')} · "
            f"{item.get('best_regime', '')}"
        ),
        regime_match=bool(regime_match),
        price=round(price, 2),
        entry_price=round(float(item.get("entry_price", 0.0) or 0.0), 2),
        stop_loss=round(float(item.get("stop_loss", 0.0) or 0.0), 2),
        target=round(float(item.get("target", 0.0) or 0.0), 2),
        rr_ratio=round(rr, 2),
        expected_holding_days=round(float(item.get("expected_holding_days", 0.0) or 0.0), 1),
        expected_drawdown=round(float(item.get("expected_drawdown", 0.0) or 0.0), 2),
        position_open=position_open,
        position_quantity=pos_qty,
        position_avg_price=round(pos_avg, 2),
        position_pnl_pct=pos_pnl_pct,
        exit_reason=exit_reason,
        reason=reason,
        explanation=" ".join(parts),
        explanation_sections=explanation_sections,
        failed_conditions=failed,
        breakdown=_build_breakdown(item, data_ok, regime_strength, round(fc, 1)),
    )

    # ── Confidence calibration (Phase 1) ─────────────────────────────────────
    # Attach raw confidence, calibrated win probability and the method used.
    # Never changes the recommendation logic above; downstream consumers
    # (portfolio manager sizing, ranking) prefer calibrated_confidence.
    decision.update(_calibration_fields(fc))

    # ── Phase 2: Adaptive strategy selection ────────────────────────────────
    # Rank this decision's strategy for the CURRENT regime from completed
    # trades only. The portfolio manager skips disabled strategies and tilts
    # sizing by strategy_sizing_factor. Failure here never breaks a decision.
    try:
        from strategy_intelligence import get_live_intelligence, normalize_regime
        _sid = str(item.get("best_strategy_id", "") or "").lower()
        _reg7 = normalize_regime(regime_now)
        _intel = get_live_intelligence()
        _row = next((r for r in _intel.rank_for_regime(_reg7)
                     if r["strategy_id"] == _sid), None)
        decision.update({
            "strategy_id": _sid,
            "strategy_regime": _reg7,
            "strategy_rank": _row["rank"] if _row else None,
            "strategy_enabled": bool(_row["enabled"]) if _row else True,
            "strategy_reason": _row["reason"] if _row else "",
            "strategy_sizing_factor": (_intel.sizing_factor(_sid, _reg7)
                                       if _sid else 1.0),
        })
    except Exception:
        decision.update({
            "strategy_id": str(item.get("best_strategy_id", "") or "").lower(),
            "strategy_regime": "", "strategy_rank": None,
            "strategy_enabled": True, "strategy_reason": "",
            "strategy_sizing_factor": 1.0,
        })

    # ── v2.3 Analyst Reasoning and Decision Invalidation Layer ──────────────
    # Purely explanatory + monitoring: never changes the recommendation or
    # confidence above. Failure here must never break the decision itself.
    try:
        from analyst_reasoning import build_analyst_view
        decision.update(build_analyst_view(decision, item, regime_now))
    except Exception as exc:
        decision.update({
            "analyst_summary": f"Analyst reasoning unavailable: {exc}",
            "current_observation": "",
            "historical_assessment": "",
            "decision_reasoning": "",
            "invalidation_conditions": [],
            "upgrade_conditions": [],
            "invalidation_met": 0,
            "upgrade_met": 0,
            "decision_state": "DATA_LIMITED" if not data_ok else "VALID",
            "decision_timestamp": datetime.now().isoformat(timespec="seconds"),
            "valid_until": None,
            "validity_note": "Re-evaluation required",
            "conflict_level": "NONE",
            "conflict_explanation": "",
            "missing_data_fields": [],
        })

    return decision  # type: ignore[return-value]


def get_trade_decisions() -> dict:
    """
    Run the full market scan, combine every layer's output with the paper
    portfolio, and return one clear recommendation per stock.
    """
    from market_scanner import run_market_scan
    from paper_trader import _load_state  # read-only use of portfolio state

    state = _load_state()
    cash = float(state.get("cash", INITIAL_CAPITAL) or INITIAL_CAPITAL)
    positions: dict = state.get("positions", {}) or {}
    trades: list = state.get("trades", []) or []

    scan = run_market_scan(capital=cash)

    try:
        from adaptive_learning import current_market_regime
        regime_now = current_market_regime()
    except Exception:
        regime_now = "Neutral"

    learning_meta = scan.get("learning") or {}
    regime_strength = float(learning_meta.get("regime_strength", 50.0) or 50.0)

    # v2.1 Evidence-Based Research: batch similarity evidence for all stocks.
    # Failure here is non-fatal — decisions fall back to a zero adjustment.
    try:
        from similarity_engine import annotate_items_with_evidence
        try:
            from root_cause_engine import (root_cause_for_item,
                                           maybe_update_feature_importance)
            # v2.2: opportunistic, gated (>=50 new completed trades) rolling
            # feature-importance update. Cheap no-op when nothing changed.
            try:
                maybe_update_feature_importance()
            except Exception:
                pass
        except Exception:
            root_cause_for_item = None
        annotate_items_with_evidence(scan["items"], regime_now=regime_now,
                                     root_cause_fn=root_cause_for_item)
    except Exception as exc:
        for it in scan["items"]:
            it.setdefault("similarity_adjustment", 0.0)
            it.setdefault("evidence_reliability", "VERY_LOW")
            it.setdefault("similarity_explanation",
                          f"Similarity evidence unavailable: {exc}")
            it.setdefault("similarity_evidence", None)

    # v2.0 Adaptive Self-Evaluation: active model version + bounded weights
    try:
        from model_versioning import get_active_version
        active_model = get_active_version()
        model_version = int(active_model.get("version", 0))
        model_weights = dict(active_model.get("weights", {}))
    except Exception:
        model_version, model_weights = 0, {}

    decisions = [_decide(it, positions, trades, regime_strength,
                         model_weights=model_weights,
                         model_version=model_version)
                 for it in scan["items"]]

    decisions.sort(key=lambda d: (_ORDER.get(d["recommendation"], 9),
                                  -d["final_confidence"]))

    counts = {k: 0 for k in _ORDER}
    for d in decisions:
        counts[d["recommendation"]] = counts.get(d["recommendation"], 0) + 1

    result = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "market_regime": regime_now,
        "model_version": model_version,
        "universe_size": len(decisions),
        "strong_buy_count": counts["STRONG_BUY"],
        "buy_count": counts["BUY"],
        "watch_count": counts["WATCH"],
        "exit_count": counts["EXIT"],
        "avoid_count": counts["AVOID"],
        "data_unavailable_count": sum(1 for d in decisions if d["data_status"] != "OK"),
        "decisions": decisions,
        "warning": "Paper trading only — research tool, not investment advice.",
    }
    # Persist a lightweight summary so ops_centre can show the confirmed BUY
    # count without triggering a new market scan.
    _write_decision_summary(result)
    return result

import tempfile as _tempfile

# Required keys + expected integer-typed count fields for schema validation.
_REQUIRED_SUMMARY_KEYS: frozenset[str] = frozenset({
    "generated_at", "confirmed_buy_count", "strong_buy_count",
    "buy_count", "universe_size",
})
_SUMMARY_INT_KEYS: tuple[str, ...] = (
    "confirmed_buy_count", "strong_buy_count", "buy_count", "universe_size",
)


def _write_decision_summary(result: dict) -> None:
    """
    Atomically persist a lightweight summary of the last get_trade_decisions()
    result. Uses write-to-temp + os.replace() so a concurrent reader never sees
    a partial file. Write failures are silent — never crash a scan.
    """
    try:
        summary = {
            "generated_at":      result.get("generated_at"),
            "strong_buy_count":  int(result.get("strong_buy_count", 0)),
            "buy_count":         int(result.get("buy_count", 0)),
            "confirmed_buy_count": (int(result.get("strong_buy_count", 0))
                                    + int(result.get("buy_count", 0))),
            "watch_count":       int(result.get("watch_count", 0)),
            "avoid_count":       int(result.get("avoid_count", 0)),
            "universe_size":     int(result.get("universe_size", 0)),
            "market_regime":     result.get("market_regime", ""),
        }
        _dir = os.path.dirname(_SUMMARY_FILE)
        # Write to a sibling temp file, then atomically replace the target.
        fd, tmp_path = _tempfile.mkstemp(
            dir=_dir, suffix=".json.tmp", prefix=".dec_sum_")
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(summary, fh)
            os.replace(tmp_path, _SUMMARY_FILE)   # atomic on POSIX
        except Exception:
            try:
                os.unlink(tmp_path)               # clean up orphan on failure
            except OSError:
                pass
            raise
    except Exception:
        pass  # best-effort — never crash a scan


def load_decision_summary() -> dict | None:
    """
    Return the summary written by the last get_trade_decisions() call, or None
    when:
      - the file does not exist (Trade Decisions page never loaded), or
      - the file is corrupt / unreadable, or
      - the schema is incomplete or contains wrong types.

    Callers MUST treat None as "not yet available" and must NOT substitute a
    proxy value (e.g. scanner_candidates) in its place — doing so recreates the
    original bug where scanner-level counts masquerade as confirmed BUY counts.

    Keys guaranteed present when not None:
        generated_at (str), confirmed_buy_count (int), strong_buy_count (int),
        buy_count (int), universe_size (int)
    """
    try:
        if not os.path.exists(_SUMMARY_FILE):
            return None
        with open(_SUMMARY_FILE) as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return None
        if not _REQUIRED_SUMMARY_KEYS.issubset(data.keys()):
            return None
        for key in _SUMMARY_INT_KEYS:
            if not isinstance(data[key], (int, float)):
                return None
        return data
    except Exception:
        return None
