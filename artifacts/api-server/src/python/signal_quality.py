"""
signal_quality.py
Signal Quality Improvement Layer (v1.0).

Adds on top of the Market Scanner / Market Replay signals:

  1. Component scores      — trend, momentum, volume, sector, market regime,
                             risk/reward, historical strategy reliability
                             (each 0-100).
  2. Signal Quality Score  — weighted composite of the components (0-100),
                             using transparent, bounded learning weights
                             from signal_learning.py.
  3. Strict trade filters  — BUY/STRONG BUY is only kept when EVERY strict
                             condition passes; otherwise the action is
                             downgraded to WATCH or IGNORE.

PAPER TRADING ONLY — no real orders are ever placed.
"""

from datetime import datetime, timedelta

from signal_learning import load_weights, FACTORS

# ── Strict filter thresholds ─────────────────────────────────────────────────

STRICT_MIN_SCORE       = 50.0   # opportunity score (composite rarely exceeds ~65 in practice)
STRICT_MIN_CONFIDENCE  = 50.0
STRICT_MIN_RR          = 2.0
MIN_CALIBRATED_PROB    = 0.30   # calibrated win probability floor (Phase 1 calibration)
MIN_VOLUME_RATIO       = 0.75   # vs 20-day average — reject only unusually quiet stocks
TOP_SECTORS            = 3
ALLOWED_REGIMES        = {"Bullish", "Neutral-Bullish"}

# Adaptive strategy reliability gate — "no reliable strategy" rule
MIN_RELIABLE_TRADES    = 3
MIN_RELIABLE_PERF      = 35.0

NO_TRADES_MESSAGE = (
    "No high-quality trades found. This is a valid outcome. "
    "Avoiding trades is better than taking weak trades."
)


# ── Market regime (as-of a date, lookahead safe) ─────────────────────────────

_REGIME_SCORES = {
    "Bullish":         100.0,
    "Neutral-Bullish":  75.0,
    "Neutral-Bearish":  40.0,
    "Bearish":          15.0,
    "Unknown":          50.0,
}


def get_market_regime_as_of(as_of_date: str | None = None) -> dict:
    """
    Classify the market regime from NIFTY 50 index data using ONLY candles
    up to `as_of_date` (or the latest data when None):
      - EMA20 vs EMA50 of the index
      - 5-day return
    Returns {'regime', 'regime_score', 'detail'}.
    """
    try:
        import yfinance as yf
        import pandas as pd

        if as_of_date:
            end_dt = datetime.strptime(as_of_date, "%Y-%m-%d") + timedelta(days=1)
        else:
            end_dt = datetime.now() + timedelta(days=1)
        start_dt = end_dt - timedelta(days=180)

        df = yf.Ticker("^NSEI").history(
            start=start_dt.strftime("%Y-%m-%d"),
            end=end_dt.strftime("%Y-%m-%d"),
            interval="1d",
        )
        if df is None or df.empty or len(df) < 55:
            return {"regime": "Unknown", "regime_score": _REGIME_SCORES["Unknown"],
                    "detail": "Insufficient NIFTY index data"}

        close = df["Close"]
        ema20 = close.ewm(span=20, adjust=False).mean().iloc[-1]
        ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
        last = float(close.iloc[-1])
        ret5 = (last - float(close.iloc[-6])) / float(close.iloc[-6]) * 100.0

        if ema20 > ema50 and ret5 > 0.5:
            regime = "Bullish"
        elif ema20 > ema50:
            regime = "Neutral-Bullish"
        elif ret5 > 0:
            regime = "Neutral-Bearish"
        else:
            regime = "Bearish"

        detail = (
            f"NIFTY EMA20 {'above' if ema20 > ema50 else 'below'} EMA50, "
            f"5-day return {ret5:+.2f}%"
        )
        return {"regime": regime, "regime_score": _REGIME_SCORES[regime], "detail": detail}
    except Exception as exc:
        return {"regime": "Unknown", "regime_score": _REGIME_SCORES["Unknown"],
                "detail": f"Regime check failed: {exc}"}


# ── Component scores (0-100 each) ────────────────────────────────────────────

def trend_score(price: float, ema20: float, ema50: float) -> float:
    """Price vs EMA20/EMA50 alignment."""
    if price <= 0 or ema20 <= 0 or ema50 <= 0:
        return 0.0
    score = 0.0
    if price > ema20:
        score += 40.0
    if price > ema50:
        score += 30.0
    if ema20 > ema50:
        score += 30.0
    return round(score, 1)


def momentum_score(rsi: float, macd_hist: float) -> float:
    """RSI sweet spot (50-70) plus positive MACD histogram."""
    score = 0.0
    if rsi > 0:
        if 50.0 <= rsi <= 70.0:
            score += 60.0
        elif 40.0 <= rsi < 50.0 or 70.0 < rsi <= 80.0:
            score += 35.0
        else:
            score += 10.0
    if macd_hist > 0:
        score += 40.0
    return round(min(100.0, score), 1)


def volume_score(volume_ratio: float) -> float:
    """Volume vs 20-day average; 1.0x = 50, >=2.0x = 100."""
    if volume_ratio <= 0:
        return 0.0
    return round(min(100.0, volume_ratio / 2.0 * 100.0), 1)


def rr_score(rr_ratio: float) -> float:
    return round(min(100.0, max(0.0, rr_ratio / 4.0 * 100.0)), 1)


def sector_score(sector_rank: int, total_sectors: int) -> float:
    """Top sector = 100, decaying with rank."""
    if sector_rank <= 0 or total_sectors <= 0:
        return 50.0
    if total_sectors == 1:
        return 100.0
    frac = (sector_rank - 1) / (total_sectors - 1)
    return round(100.0 - frac * 80.0, 1)


def reliability_score(perf_score: float, total_trades: int) -> float:
    """Historical strategy reliability — perf score dampened by sample size."""
    sample = min(1.0, total_trades / 8.0)
    return round(max(0.0, min(100.0, perf_score * (0.5 + 0.5 * sample))), 1)


def compute_components(
    price: float, ema20: float, ema50: float,
    rsi: float, macd_hist: float, volume_ratio: float,
    rr_ratio: float, perf_score: float, total_trades: int,
    sector_rank: int, total_sectors: int, regime_score: float,
) -> dict[str, float]:
    return {
        "trend":                trend_score(price, ema20, ema50),
        "momentum":             momentum_score(rsi, macd_hist),
        "volume":               volume_score(volume_ratio),
        "sector":               sector_score(sector_rank, total_sectors),
        "regime":               round(regime_score, 1),
        "risk_reward":          rr_score(rr_ratio),
        "strategy_reliability": reliability_score(perf_score, total_trades),
    }


def components_from_item(
    item: dict, sector_rank: int, total_sectors: int, regime_score: float,
) -> dict[str, float]:
    """
    Build the component scores from a ReplayItem/ScanItem-style dict that
    carries above_ema20/above_ema50 booleans instead of raw EMA values.
    """
    t = 0.0
    if item.get("above_ema20"):
        t += 50.0
    if item.get("above_ema50"):
        t += 50.0
    return {
        "trend":                round(t, 1),
        "momentum":             momentum_score(float(item.get("rsi", 0.0) or 0.0),
                                               float(item.get("macd_hist", 0.0) or 0.0)),
        "volume":               volume_score(float(item.get("volume_ratio", 0.0) or 0.0)),
        "sector":               sector_score(sector_rank, total_sectors),
        "regime":               round(regime_score, 1),
        "risk_reward":          rr_score(float(item.get("rr_ratio", 0.0) or 0.0)),
        "strategy_reliability": reliability_score(float(item.get("trade_quality", 0.0) or 0.0),
                                                  int(item.get("total_trades", 0) or 0)),
    }


def annotate_items_with_quality(
    items: list, action_key: str, regime_info: dict,
    min_score: float = STRICT_MIN_SCORE,
    min_confidence: float = STRICT_MIN_CONFIDENCE,
    min_rr: float = STRICT_MIN_RR,
) -> None:
    """
    Mutates a list of ReplayItem/ScanItem dicts in place, adding:
      sector_rank, quality_components, signal_quality, filter_passed,
      filter_reasons — and downgrading BUY/STRONG BUY actions (stored under
      `action_key`) that fail the strict filters. Errored items get zeros.
    """
    weights = load_weights()["weights"]
    regime = regime_info.get("regime", "Unknown")
    regime_score = float(regime_info.get("regime_score", 50.0))

    # Confidence calibration (Phase 1): map each item's raw confidence to a
    # calibrated win probability used as an additional strict filter.
    try:
        from confidence_calibration import get_or_fit_calibrator, apply_calibration
        _calibrator = get_or_fit_calibrator()
    except Exception:
        _calibrator, apply_calibration = None, None

    valid = [it for it in items if it.get("error") is None]

    # Sector ranking by average opportunity score (as-of data only)
    by_sector: dict[str, list] = {}
    for it in valid:
        by_sector.setdefault(it["sector"], []).append(it)
    sector_avg = {
        s: sum(x["opportunity_score"] for x in xs) / len(xs)
        for s, xs in by_sector.items()
    }
    ranked_sectors = sorted(sector_avg, key=lambda s: sector_avg[s], reverse=True)
    sector_rank_of = {s: i + 1 for i, s in enumerate(ranked_sectors)}
    total_sectors = len(ranked_sectors)

    for it in items:
        if it.get("error") is not None:
            it["sector_rank"] = 0
            it["quality_components"] = {f: 0.0 for f in FACTORS}
            it["signal_quality"] = 0.0
            it["filter_passed"] = False
            it["filter_reasons"] = [it.get("error") or "error"]
            continue

        srank = sector_rank_of.get(it["sector"], 0)
        comps = components_from_item(it, srank, total_sectors, regime_score)
        quality = quality_score(comps, weights)
        _conf = float(it.get("confidence", 0.0))
        if apply_calibration is not None:
            cal_p = apply_calibration(_calibrator, _conf)
            it["raw_confidence"] = round(_conf, 1)
            it["calibrated_probability"] = cal_p
            it["calibrated_confidence"] = round(cal_p * 100.0, 1)
            it["calibration_method"] = (_calibrator or {}).get("method", "identity")
            it["calibration_version"] = int((_calibrator or {}).get("version", 0) or 0)
        else:
            cal_p = None
        passes, reasons = strict_filter_check(
            opportunity_score=float(it.get("opportunity_score", 0.0)),
            confidence=_conf,
            calibrated_probability=cal_p,
            rr_ratio=float(it.get("rr_ratio", 0.0)),
            sector_rank=srank,
            regime=regime,
            above_ema20=bool(it.get("above_ema20")),
            above_ema50=bool(it.get("above_ema50")),
            volume_ratio=float(it.get("volume_ratio", 0.0) or 0.0),
            perf_score=float(it.get("trade_quality", 0.0)),
            total_trades=int(it.get("total_trades", 0) or 0),
            min_score=min_score, min_confidence=min_confidence, min_rr=min_rr,
        )
        it["sector_rank"] = srank
        it["quality_components"] = comps
        it["signal_quality"] = quality
        it["filter_passed"] = passes
        it["filter_reasons"] = reasons
        it[action_key] = apply_strict_filter(it.get(action_key, "IGNORE"), passes, quality)


def quality_score(components: dict[str, float], weights: dict[str, float] | None = None) -> float:
    """Weighted composite Signal Quality Score out of 100."""
    if weights is None:
        weights = load_weights()["weights"]
    total_w = sum(weights.get(f, 0.0) for f in FACTORS)
    if total_w <= 0:
        return 0.0
    raw = sum(components.get(f, 0.0) * weights.get(f, 0.0) for f in FACTORS) / total_w
    return round(max(0.0, min(100.0, raw)), 1)


# ── Strict filters ───────────────────────────────────────────────────────────

def strict_filter_check(
    opportunity_score: float,
    confidence: float,
    rr_ratio: float,
    sector_rank: int,
    regime: str,
    above_ema20: bool,
    above_ema50: bool,
    volume_ratio: float,
    perf_score: float,
    total_trades: int,
    min_score: float = STRICT_MIN_SCORE,
    min_confidence: float = STRICT_MIN_CONFIDENCE,
    min_rr: float = STRICT_MIN_RR,
    calibrated_probability: float | None = None,
    min_calibrated_prob: float = MIN_CALIBRATED_PROB,
) -> tuple[bool, list[str]]:
    """Returns (passes_all, list of failed-condition reasons)."""
    failures: list[str] = []
    if opportunity_score < min_score:
        failures.append(f"Opportunity score {opportunity_score:.1f} < {min_score:g}")
    if confidence < min_confidence:
        failures.append(f"Confidence {confidence:.1f} < {min_confidence:g}")
    if calibrated_probability is not None and calibrated_probability < min_calibrated_prob:
        failures.append(
            f"Calibrated win probability {calibrated_probability * 100.0:.0f}% "
            f"< {min_calibrated_prob * 100.0:.0f}% floor"
        )
    if rr_ratio < min_rr:
        failures.append(f"Risk/reward {rr_ratio:.2f} < {min_rr:g}")
    if sector_rank <= 0 or sector_rank > TOP_SECTORS:
        failures.append(f"Sector rank {sector_rank} not in top {TOP_SECTORS}")
    if regime not in ALLOWED_REGIMES:
        failures.append(f"Market regime is {regime} (need Bullish or Neutral-Bullish)")
    if not above_ema20:
        failures.append("Price below EMA20")
    if not above_ema50:
        failures.append("Price below EMA50")
    if volume_ratio < MIN_VOLUME_RATIO:
        failures.append(
            f"Volume unusually quiet ({volume_ratio:.2f}x vs 20-day avg, need >= {MIN_VOLUME_RATIO:g}x)"
        )
    if total_trades < MIN_RELIABLE_TRADES or perf_score < MIN_RELIABLE_PERF:
        failures.append(
            f"No reliable strategy (perf {perf_score:.1f}, {total_trades} trades — "
            f"need perf >= {MIN_RELIABLE_PERF:g} and >= {MIN_RELIABLE_TRADES} trades)"
        )
    return (len(failures) == 0, failures)


def apply_strict_filter(action: str, passes: bool, quality: float) -> str:
    """
    Only keep BUY/STRONG BUY when all strict conditions pass; otherwise
    downgrade to WATCH (decent quality) or IGNORE (poor quality).
    """
    if action not in ("STRONG BUY", "BUY"):
        return action
    if passes:
        return action
    return "WATCH" if quality >= 45.0 else "IGNORE"
