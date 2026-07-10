"""
Failure / Success Analyzer — Version 2.0 Adaptive Self-Evaluation (Module 2).

Assigns probable causes to losing / underperforming trades and contributing
factors to profitable trades. STRICT RULES:

  - Every cause needs supporting data — no cause is assigned without
    evidence. Missing data simply means the cause is skipped.
  - Every cause carries: name, evidence (with numbers), severity,
    and a confidence-in-diagnosis score (0-100).
  - Pure deterministic arithmetic — no ML, no randomness.

PAPER TRADING ONLY — research tool, never places orders.
"""

from __future__ import annotations

import json

# Underperforming = profitable but far below what was predicted.
UNDERPERFORM_GAP = 3.0     # % below expected return counts as underperforming

_HIGH, _MED, _LOW = "High", "Medium", "Low"


def _f(v, default=None):
    try:
        x = float(v)
        return x if x == x else default
    except (TypeError, ValueError):
        return default


def _cause(name: str, evidence: str, severity: str, confidence: float) -> dict:
    return {
        "cause": name,
        "evidence": evidence,
        "severity": severity,
        "diagnosis_confidence": round(max(0.0, min(100.0, confidence)), 0),
    }


def _factor(name: str, evidence: str, weight: float) -> dict:
    return {
        "factor": name,
        "evidence": evidence,
        "weight": round(max(0.0, min(100.0, weight)), 0),
    }


def _kb_strategy_stats(strategy_id: str, dim: str, dim_value: str) -> dict | None:
    """Historical KB expectancy for strategy × sector or strategy × regime.
    Returns None when the KB is missing or the sample is too thin (<30)."""
    try:
        from adaptive_learning import load_knowledge, pattern_stats
        strat = str(strategy_id or "").strip().lower()
        key = "sector" if dim == "sector" else "regime"
        val = str(dim_value or "").upper() if dim == "sector" else str(dim_value or "")
        subset = [t for t in load_knowledge()
                  if t["strategy"] == strat and str(t.get(key, "")) == val]
        if len(subset) < 30:
            return None
        return pattern_stats(subset)
    except Exception:
        return None


def _regime_at(date_iso: str) -> str:
    try:
        from trade_intelligence import classify_regime
        return classify_regime(str(date_iso)[:10]).get("regime", "")
    except Exception:
        return ""


# ── Failure analysis (spec §4) ────────────────────────────────────────────────

def failure_causes(snapshot: dict, ev: dict) -> list[dict]:
    """Evidence-based probable causes for a losing/underperforming trade."""
    causes: list[dict] = []

    ind = snapshot.get("indicators") or {}
    if isinstance(ind, str):
        try:
            ind = json.loads(ind)
        except Exception:
            ind = {}

    ret = _f(ev.get("actual_return"), 0.0)
    expected = _f(ev.get("expected_return"))
    mfe, mae = _f(ev.get("mfe")), _f(ev.get("mae"))
    entry = _f(ev.get("entry_price"), 0.0) or 0.0
    stop = _f(snapshot.get("stop_loss"), 0.0) or 0.0
    target = _f(snapshot.get("target"), 0.0) or 0.0
    atr = _f(ind.get("atr"))
    rsi = _f(ind.get("rsi"))
    ema9, ema20, ema50 = _f(ind.get("ema9")), _f(ind.get("ema20")), _f(ind.get("ema50"))
    ema200 = _f(ind.get("ema200"))
    macd, macd_sig = _f(ind.get("macd")), _f(ind.get("macd_signal"))
    vol_ratio = _f(ind.get("volume_ratio"))
    volatility = _f(snapshot.get("volatility"))
    holding = _f(ev.get("actual_holding_days"), 0.0) or 0.0
    expected_hold = _f(snapshot.get("expected_holding_days"))
    exit_type = str(ev.get("exit_type", ""))

    atr_pct = (atr / entry * 100.0) if (atr and entry > 0) else None
    stop_dist = ((entry - stop) / entry * 100.0) if (entry > 0 and 0 < stop < entry) else None
    target_dist = ((target - entry) / entry * 100.0) if (entry > 0 and target > entry) else None

    # 1. Entered against broader trend
    if None not in (ema9, ema20, ema50) and ema9 < ema20 < ema50:
        causes.append(_cause(
            "Entered against broader trend",
            f"EMAs bearish-aligned at entry (EMA9 {ema9:.1f} < EMA20 {ema20:.1f} "
            f"< EMA50 {ema50:.1f}) in a long-only trade.",
            _HIGH, 85))
    elif ema200 is not None and entry > 0 and entry < ema200:
        causes.append(_cause(
            "Entered against broader trend",
            f"Entry ₹{entry:.2f} below the 200-day EMA ₹{ema200:.2f}.",
            _MED, 65))

    # 2. Market regime changed after entry
    regime_entry = str(snapshot.get("market_regime", "") or "")
    regime_exit = _regime_at(ev.get("exit_time", ""))
    if regime_entry and regime_exit and regime_entry != regime_exit:
        bearish_shift = regime_exit in ("Bearish", "Strong Bearish", "High Volatility")
        causes.append(_cause(
            "Market regime changed after entry",
            f"Regime moved from {regime_entry} at entry to {regime_exit} at exit.",
            _HIGH if bearish_shift else _MED, 75 if bearish_shift else 55))

    # 3. Sector weakened — needs sector strength captured at entry
    sector_str = _f(snapshot.get("sector_strength"))
    if sector_str is not None and sector_str < 40:
        causes.append(_cause(
            "Sector weakened",
            f"Sector strength was already weak at entry ({sector_str:.0f}/100).",
            _MED, 55))

    # 4. Volume confirmation was weak
    if vol_ratio is not None and vol_ratio < 0.8:
        causes.append(_cause(
            "Volume confirmation was weak",
            f"Volume at entry ran {vol_ratio:.2f}× its 20-day average (< 0.8×).",
            _MED, 70))

    # 5. Momentum reversed
    if mfe is not None and mfe < 1.0 and ret < 0:
        causes.append(_cause(
            "Momentum reversed",
            f"Price never moved more than {mfe:+.2f}% in favour before the "
            f"{ret:+.2f}% loss.",
            _HIGH, 75))

    # 6. Entry too early (deep adverse move first, favourable move existed)
    if mae is not None and mfe is not None and mae <= -3.0 and mfe >= 1.5:
        causes.append(_cause(
            "Entry was too early",
            f"Price first fell {mae:+.2f}% against the trade before reaching "
            f"{mfe:+.2f}% in favour.",
            _MED, 60))

    # 7. Entry too late (bought overbought)
    if rsi is not None and rsi > 70 and ret < 0:
        causes.append(_cause(
            "Entry was too late",
            f"RSI was overbought at entry ({rsi:.0f} > 70) and the move had "
            f"little room left.",
            _MED, 65))

    # 8. Stop-loss too tight
    if ev.get("stop_hit") and stop_dist is not None and atr_pct is not None \
            and stop_dist < atr_pct:
        causes.append(_cause(
            "Stop-loss too tight",
            f"Stop distance {stop_dist:.2f}% was inside one day's typical range "
            f"(ATR {atr_pct:.2f}%) — normal noise could hit it.",
            _HIGH, 80))
    elif ev.get("stop_hit") and mfe is not None and target_dist is not None \
            and mfe >= 0.6 * target_dist:
        causes.append(_cause(
            "Stop-loss too tight",
            f"Price reached {mfe:+.2f}% in favour ({mfe / target_dist * 100:.0f}% "
            f"of the way to target) before the stop was hit.",
            _MED, 60))

    # 9. Stop-loss too wide
    if stop_dist is not None and atr_pct is not None and stop_dist > 3.0 * atr_pct \
            and ret < 0 and not ev.get("stop_hit"):
        causes.append(_cause(
            "Stop-loss too wide",
            f"Stop distance {stop_dist:.2f}% exceeded 3× daily range "
            f"(ATR {atr_pct:.2f}%), allowing a large drawdown.",
            _LOW, 50))

    # 10. Target unrealistic
    if target_dist is not None and mfe is not None and not ev.get("target_hit") \
            and atr_pct is not None and target_dist > 4.0 * atr_pct and mfe < 0.5 * target_dist:
        causes.append(_cause(
            "Target unrealistic",
            f"Target required {target_dist:.2f}% but the price only reached "
            f"{mfe:+.2f}% ({(mfe / target_dist * 100):.0f}% of the way) — "
            f"target was {target_dist / atr_pct:.1f}× the daily range.",
            _MED, 65))

    # 11. Risk/reward estimate inaccurate
    pred_err = _f(ev.get("prediction_error"))
    if pred_err is not None and expected is not None and pred_err < -5.0:
        causes.append(_cause(
            "Risk/reward estimate inaccurate",
            f"Expected {expected:+.2f}% but realized {ret:+.2f}% "
            f"(error {pred_err:+.2f} points).",
            _MED, 70))

    # 12. Historical sample unreliable
    n_hist = int(snapshot.get("historical_matches") or 0)
    if 0 < n_hist < 30:
        causes.append(_cause(
            "Historical sample unreliable",
            f"Only {n_hist} similar historical trades supported this decision "
            f"(30+ needed for reliability).",
            _MED, 70))
    elif n_hist == 0:
        causes.append(_cause(
            "Pattern match too weak",
            "No similar historical trades were found — the decision relied on "
            "technical signals alone.",
            _MED, 65))

    # 13. Pattern match too weak (weak historical edge)
    hist_exp = _f(snapshot.get("historical_expectancy"))
    if n_hist >= 30 and hist_exp is not None and hist_exp < 0.2:
        causes.append(_cause(
            "Pattern match too weak",
            f"The matched pattern's historical expectancy was only "
            f"{hist_exp:+.2f}% per trade across {n_hist} trades.",
            _MED, 60))

    # 14. High volatility
    if (volatility is not None and volatility >= 22.0) or \
            regime_entry == "High Volatility":
        vol_txt = f"{volatility:.1f}% annualised" if volatility is not None else "High Volatility regime"
        causes.append(_cause(
            "High volatility",
            f"Market volatility at entry: {vol_txt}.",
            _MED, 60))

    # 15. Overnight gap
    max_gap = _f(ev.get("max_gap_pct"))
    if max_gap is not None and max_gap > 2.0:
        causes.append(_cause(
            "Overnight gap",
            f"Largest overnight gap during the hold was {max_gap:.2f}% "
            f"(> 2% cannot be protected by a daily stop).",
            _MED, 70))

    # 16. Data quality problem
    if snapshot.get("data_source") not in (None, "", "yfinance"):
        causes.append(_cause(
            "Data quality problem",
            f"Entry decision used fallback data (source: "
            f"{snapshot.get('data_source')}). Not eligible for learning.",
            _HIGH, 90))

    # 17. Strategy unsuitable for sector (needs >=30 KB trades)
    strat = snapshot.get("strategy_id", "")
    sector = snapshot.get("sector", "")
    st = _kb_strategy_stats(strat, "sector", sector)
    if st and st["expectancy"] < -0.2:
        causes.append(_cause(
            "Strategy unsuitable for sector",
            f"{snapshot.get('strategy_name', strat)} in {sector} has "
            f"{st['expectancy']:+.2f}% expectancy over {st['trades']} historical trades.",
            _HIGH, 75))

    # 18. Strategy unsuitable for market regime (needs >=30 KB trades)
    if regime_entry:
        sr = _kb_strategy_stats(strat, "regime", regime_entry)
        if sr and sr["expectancy"] < -0.2:
            causes.append(_cause(
                "Strategy unsuitable for market regime",
                f"{snapshot.get('strategy_name', strat)} during {regime_entry} has "
                f"{sr['expectancy']:+.2f}% expectancy over {sr['trades']} historical trades.",
                _HIGH, 75))

    # 19/20. Time exit too short / too long
    if exit_type in ("TIME_EXIT", "TIME"):
        if mfe is not None and ret is not None and mfe - ret > 2.0:
            causes.append(_cause(
                "Time exit too long",
                f"Price peaked at {mfe:+.2f}% but only {ret:+.2f}% remained at "
                f"the timed exit — gains decayed while waiting.",
                _MED, 60))
        elif expected_hold and holding < expected_hold:
            causes.append(_cause(
                "Time exit too short",
                f"Closed after {holding:.0f} days but similar patterns needed "
                f"{expected_hold:.0f} days on average.",
                _MED, 60))

    return causes


# ── Success analysis (spec §5) ────────────────────────────────────────────────

def success_factors(snapshot: dict, ev: dict) -> list[dict]:
    """Contributing factors for a profitable trade — evidence-based."""
    factors: list[dict] = []

    ind = snapshot.get("indicators") or {}
    if isinstance(ind, str):
        try:
            ind = json.loads(ind)
        except Exception:
            ind = {}

    ema9, ema20, ema50 = _f(ind.get("ema9")), _f(ind.get("ema20")), _f(ind.get("ema50"))
    adx = _f(ind.get("adx"))
    rsi = _f(ind.get("rsi"))
    macd, macd_sig = _f(ind.get("macd")), _f(ind.get("macd_signal"))
    vol_ratio = _f(ind.get("volume_ratio"))
    rr = _f(snapshot.get("expected_rr"))
    n_hist = int(snapshot.get("historical_matches") or 0)
    hist_exp = _f(snapshot.get("historical_expectancy"))
    sector_str = _f(snapshot.get("sector_strength"))
    regime = str(snapshot.get("market_regime", "") or "")
    holding = _f(ev.get("actual_holding_days"), 0.0) or 0.0
    expected_hold = _f(snapshot.get("expected_holding_days"))

    if None not in (ema9, ema20, ema50) and ema9 > ema20 > ema50:
        w = 80 if (adx or 0) > 25 else 65
        factors.append(_factor(
            "Strong trend alignment",
            f"EMAs bullish-aligned at entry (EMA9 > EMA20 > EMA50)"
            + (f", ADX {adx:.0f} trending." if adx else "."), w))

    if n_hist >= 30 and hist_exp is not None and hist_exp >= 0.5:
        factors.append(_factor(
            "High-quality historical pattern",
            f"{n_hist} similar trades with {hist_exp:+.2f}% expectancy per trade.",
            85))

    if sector_str is not None and sector_str >= 60:
        factors.append(_factor(
            "Sector strength",
            f"Sector strength {sector_str:.0f}/100 at entry.", 60))

    if regime in ("Strong Bullish", "Bullish"):
        factors.append(_factor(
            "Market regime match",
            f"Entered during a {regime} market — favourable for long trades.",
            70))

    if vol_ratio is not None and vol_ratio >= 1.2:
        factors.append(_factor(
            "Volume confirmation",
            f"Volume ran {vol_ratio:.2f}× its 20-day average at entry.", 65))

    if macd is not None and macd_sig is not None and macd > macd_sig \
            and rsi is not None and 50 <= rsi <= 70:
        factors.append(_factor(
            "Momentum confirmation",
            f"MACD above signal with RSI {rsi:.0f} in the healthy 50-70 band.",
            65))

    if rr is not None and rr >= 2.0:
        factors.append(_factor(
            "Good risk/reward",
            f"Planned risk/reward was {rr:.1f}:1 at entry.", 60))

    if expected_hold and expected_hold > 0 and \
            0.5 * expected_hold <= holding <= 1.5 * expected_hold:
        factors.append(_factor(
            "Suitable holding period",
            f"Held {holding:.0f} days vs {expected_hold:.0f} expected — "
            f"within the pattern's normal window.", 55))

    if ev.get("target_hit"):
        factors.append(_factor(
            "Accurate stop and target",
            f"Price reached the planned target "
            f"(exit ₹{_f(ev.get('exit_price'), 0.0):.2f}).", 75))

    return factors


# ── Combined entry point + lesson extraction ─────────────────────────────────

def analyze_trade(snapshot: dict, evaluation: dict) -> tuple[list, list, str]:
    """Returns (failure_causes, success_factors, lesson). Losing or
    underperforming trades get causes; profitable trades get factors."""
    ret = _f(evaluation.get("actual_return"), 0.0) or 0.0
    expected = _f(evaluation.get("expected_return"))

    losing = ret <= 0
    underperforming = (not losing and expected is not None
                       and (expected - ret) > UNDERPERFORM_GAP)

    causes = failure_causes(snapshot, evaluation) if (losing or underperforming) else []
    factors = success_factors(snapshot, evaluation) if ret > 0 else []

    lesson = _extract_lesson(ret, causes, factors, underperforming)
    return causes, factors, lesson


def _extract_lesson(ret: float, causes: list, factors: list,
                    underperforming: bool) -> str:
    if ret > 0 and not underperforming:
        if factors:
            top = max(factors, key=lambda f: f["weight"])
            return (f"Winner (+{ret:.2f}%). Biggest contributor: "
                    f"{top['factor'].lower()} — {top['evidence']}")
        return f"Winner (+{ret:.2f}%), but no standout factor was identified."
    if not causes:
        return (f"Outcome {ret:+.2f}%. No evidence-backed cause found — "
                f"possibly normal market noise.")
    sev_rank = {"High": 0, "Medium": 1, "Low": 2}
    top = sorted(causes, key=lambda c: (sev_rank.get(c["severity"], 3),
                                        -c["diagnosis_confidence"]))[0]
    label = "Underperformed" if underperforming else f"Loss ({ret:+.2f}%)"
    return f"{label}. Most likely cause: {top['cause'].lower()} — {top['evidence']}"
