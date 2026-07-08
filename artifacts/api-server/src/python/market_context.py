"""
market_context.py
Market Context Engine — synthesises NIFTY, BANKNIFTY, VIX, sector
strength, and market breadth into a single market-wide verdict.

Inputs  (all computed from already-fetched data, no extra yfinance calls):
  - RegimeResult from market_regime.get_regime()
  - Signals list from signal_engine.scan_watchlist() (for breadth)

Outputs:
  - MarketContext TypedDict
    - score          : 0–100  overall market health
    - bias           : BULLISH | BEARISH | NEUTRAL
    - confidence_modifier : -20 to +20, applied to all signal confidences
    - sector_strength : dict of sector → score (derived from watchlist stocks)
    - market_breadth  : % of scanned stocks with bullish signal
"""

from datetime import datetime
from typing import TypedDict
from config import (
    MARKET_SCORE_BASE,
    MARKET_SCORE_NIFTY_UP, MARKET_SCORE_NIFTY_DOWN,
    MARKET_SCORE_BANKNIFTY_UP, MARKET_SCORE_BANKNIFTY_DOWN,
    MARKET_SCORE_VIX_LOW, MARKET_SCORE_VIX_NORMAL,
    MARKET_SCORE_VIX_HIGH, MARKET_SCORE_VIX_EXTREME,
    MARKET_SCORE_BREADTH_MAX,
    VIX_LOW_THRESHOLD, VIX_NORMAL_THRESHOLD, VIX_HIGH_THRESHOLD,
    MARKET_CONF_MOD_BULLISH, MARKET_CONF_MOD_BEARISH, MARKET_CONF_MOD_NEUTRAL,
    SECTOR_MAP,
)


# ── TypedDict ─────────────────────────────────────────────────────────────────

class MarketContext(TypedDict):
    score: float                        # 0–100
    bias: str                           # BULLISH | BEARISH | NEUTRAL
    confidence_modifier: float          # applied to every signal confidence
    nifty_price: float
    nifty_trend: str                    # UP | DOWN | SIDEWAYS
    nifty_change_pct: float
    banknifty_price: float
    banknifty_trend: str
    banknifty_change_pct: float
    vix: float
    vix_category: str                   # LOW | NORMAL | HIGH | EXTREME
    market_breadth: float               # 0.0–1.0 (fraction of stocks bullish)
    breadth_label: str                  # VERY_STRONG | STRONG | NEUTRAL | WEAK | VERY_WEAK
    sector_strength: dict               # {sector: 0–100}
    regime: str
    computed_at: str


# ── Helpers ───────────────────────────────────────────────────────────────────

BULLISH_SIGNALS = {"STRONG_BUY", "BUY"}
BEARISH_SIGNALS = {"STRONG_SELL", "SELL"}


def _vix_category(vix: float) -> str:
    if vix < VIX_LOW_THRESHOLD:
        return "LOW"
    elif vix < VIX_NORMAL_THRESHOLD:
        return "NORMAL"
    elif vix < VIX_HIGH_THRESHOLD:
        return "HIGH"
    return "EXTREME"


def _vix_score_adj(vix: float) -> float:
    cat = _vix_category(vix)
    return {
        "LOW":     MARKET_SCORE_VIX_LOW,
        "NORMAL":  MARKET_SCORE_VIX_NORMAL,
        "HIGH":    MARKET_SCORE_VIX_HIGH,
        "EXTREME": MARKET_SCORE_VIX_EXTREME,
    }[cat]


def _breadth_label(breadth: float) -> str:
    if breadth >= 0.70:
        return "VERY_STRONG"
    elif breadth >= 0.55:
        return "STRONG"
    elif breadth >= 0.40:
        return "NEUTRAL"
    elif breadth >= 0.25:
        return "WEAK"
    return "VERY_WEAK"


def _sector_strength_from_signals(signals: list[dict]) -> dict[str, float]:
    """
    Derive sector strength from watchlist signals.
    Maps each signal's stock to its sector and averages confidence scores
    (with directional weighting: BUY signals add, SELL signals subtract).
    """
    sector_scores: dict[str, list[float]] = {}

    # Build reverse map: stock → sector
    stock_sector: dict[str, str] = {}
    for sector, stocks in SECTOR_MAP.items():
        for s in stocks:
            stock_sector[s.upper()] = sector

    for sig in signals:
        stock = sig.get("stock", "").upper()
        sector = stock_sector.get(stock, "OTHER")
        confidence = sig.get("confidence", 50.0)
        signal_type = sig.get("signal", "NO_TRADE")

        # Directional score: bullish → positive, bearish → negative, else neutral
        if signal_type in BULLISH_SIGNALS:
            directional_score = confidence
        elif signal_type in BEARISH_SIGNALS:
            directional_score = 100 - confidence  # inverse
        else:
            directional_score = 50.0

        sector_scores.setdefault(sector, []).append(directional_score)

    return {
        sector: round(sum(scores) / len(scores), 1)
        for sector, scores in sector_scores.items()
        if scores
    }


# ── Core function ─────────────────────────────────────────────────────────────

def compute_market_context(
    regime_result: dict,
    signals: list[dict] | None = None,
) -> MarketContext:
    """
    Build a MarketContext from regime data + optional signal scan breadth.

    Args:
        regime_result : output of market_regime.get_regime()
        signals       : optional list of Signal dicts for breadth computation.
                        If None, breadth is inferred from regime alone.

    Returns:
        MarketContext with score, bias, confidence_modifier, sector data.
    """
    signals = signals or []

    # ── Unpack regime ─────────────────────────────────────────────────────────
    nifty_price      = regime_result.get("nifty_price", 0.0)
    nifty_trend      = regime_result.get("nifty_trend", "SIDEWAYS")
    nifty_change_pct = regime_result.get("nifty_change_pct", 0.0)
    bnifty_price     = regime_result.get("banknifty_price", 0.0)
    bnifty_trend     = regime_result.get("banknifty_trend", "SIDEWAYS")
    bnifty_change_pct= regime_result.get("banknifty_change_pct", 0.0)
    vix              = regime_result.get("vix", 18.0)
    regime           = regime_result.get("regime", "SIDEWAYS")

    # ── Score components ──────────────────────────────────────────────────────
    score = MARKET_SCORE_BASE

    # NIFTY direction
    if nifty_trend == "UP":
        score += MARKET_SCORE_NIFTY_UP
    elif nifty_trend == "DOWN":
        score += MARKET_SCORE_NIFTY_DOWN

    # BANKNIFTY direction
    if bnifty_trend == "UP":
        score += MARKET_SCORE_BANKNIFTY_UP
    elif bnifty_trend == "DOWN":
        score += MARKET_SCORE_BANKNIFTY_DOWN

    # VIX
    score += _vix_score_adj(vix)

    # Market breadth from signals
    bullish_count = sum(1 for s in signals if s.get("signal", "") in BULLISH_SIGNALS)
    total_count   = len(signals) if signals else 1
    breadth = bullish_count / total_count

    # Breadth contribution: -20 (all bearish) to +20 (all bullish)
    breadth_adj = (breadth - 0.5) * 2 * MARKET_SCORE_BREADTH_MAX
    score += breadth_adj

    # Regime fine-tuning
    if regime == "BULLISH":
        score += 5
    elif regime == "BEARISH":
        score -= 5

    score = round(max(0.0, min(100.0, score)), 1)

    # ── Bias ──────────────────────────────────────────────────────────────────
    if score >= 62:
        bias = "BULLISH"
    elif score <= 40:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    # ── Confidence modifier ───────────────────────────────────────────────────
    if bias == "BULLISH":
        conf_mod = MARKET_CONF_MOD_BULLISH
    elif bias == "BEARISH":
        conf_mod = MARKET_CONF_MOD_BEARISH
    else:
        conf_mod = MARKET_CONF_MOD_NEUTRAL

    # Extra: very high VIX → reduce confidence modifier
    if vix > VIX_HIGH_THRESHOLD:
        conf_mod -= 5

    conf_mod = round(max(-20.0, min(20.0, conf_mod)), 1)

    # ── Sector strength ───────────────────────────────────────────────────────
    sector_strength = _sector_strength_from_signals(signals)

    return MarketContext(
        score=score,
        bias=bias,
        confidence_modifier=conf_mod,
        nifty_price=round(nifty_price, 2),
        nifty_trend=nifty_trend,
        nifty_change_pct=round(nifty_change_pct, 2),
        banknifty_price=round(bnifty_price, 2),
        banknifty_trend=bnifty_trend,
        banknifty_change_pct=round(bnifty_change_pct, 2),
        vix=round(vix, 2),
        vix_category=_vix_category(vix),
        market_breadth=round(breadth, 3),
        breadth_label=_breadth_label(breadth),
        sector_strength=sector_strength,
        regime=regime,
        computed_at=datetime.now().isoformat(),
    )
