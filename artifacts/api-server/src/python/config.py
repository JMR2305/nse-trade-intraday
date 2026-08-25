"""
config.py
Single source of truth for all configurable parameters.
No values are hardcoded inside components — change here, affects everything.

Designed for future Zerodha integration:
  - CAPITAL / MAX_RISK_PCT control position sizing
  - SECTOR_MAP controls sector strength computation
  - Thresholds control signal/quality/opportunity gates
"""

# ── Capital & Risk ─────────────────────────────────────────────────────────────

INITIAL_CAPITAL: float = 100_000.0   # ₹100,000 — canonical paper-trading capital baseline
MAX_RISK_PCT: float = 0.01          # 1% max risk per trade
MAX_CAPITAL_PER_TRADE_PCT: float = 0.20  # never use more than 20% of cash in one trade

# ── Signal thresholds ──────────────────────────────────────────────────────────

SIGNAL_STRONG_THRESHOLD: float = 90.0   # STRONG_BUY / STRONG_SELL
SIGNAL_BUY_THRESHOLD: float = 75.0      # BUY / SELL
SIGNAL_WATCH_THRESHOLD: float = 60.0    # WATCH
SIGNAL_MIN_THRESHOLD: float = 60.0      # below this = NO_TRADE

# ── Trade Quality weights (must sum to 1.0) ────────────────────────────────────

TRADE_QUALITY_WEIGHTS: dict[str, float] = {
    "trend":    0.25,
    "momentum": 0.20,
    "volume":   0.15,
    "breakout": 0.20,
    "risk":     0.10,
    "market":   0.10,
}

TRADE_QUALITY_GRADES: list[tuple[float, str]] = [
    (85.0, "A+"),
    (75.0, "A"),
    (65.0, "B"),
    (55.0, "C"),
    (45.0, "D"),
    (0.0,  "F"),
]

# ── Opportunity scanner thresholds ─────────────────────────────────────────────

OPP_HOT_BUY_THRESHOLD: float = 85.0
OPP_BUY_THRESHOLD: float = 70.0
OPP_WATCH_THRESHOLD: float = 50.0

# Opportunity score weights
OPP_WEIGHTS: dict[str, float] = {
    "trade_quality":    0.40,
    "ai_confidence":    0.30,
    "rr_score":         0.20,
    "market_alignment": 0.10,
}

# ── AI Decision Engine rules ───────────────────────────────────────────────────

AI_MIN_RR_RATIO: float = 2.0         # minimum reward:risk ratio
AI_MIN_TF_ALIGNMENT: int = 3         # minimum timeframes agreeing (out of 4)
AI_HIGH_VOL_CONF_THRESHOLD: float = 70.0   # confidence below this in HIGH_VOLATILITY → downgrade
AI_SIDEWAYS_CONF_THRESHOLD: float = 72.0   # confidence below this in SIDEWAYS → downgrade
AI_MIN_STOP_DISTANCE_PCT: float = 0.5      # stop < 0.5% of price → whipsaw risk

# ── Market Context thresholds ──────────────────────────────────────────────────

VIX_LOW_THRESHOLD: float = 15.0
VIX_NORMAL_THRESHOLD: float = 20.0
VIX_HIGH_THRESHOLD: float = 25.0

# Market score adjustments
MARKET_SCORE_BASE: float = 50.0
MARKET_SCORE_NIFTY_UP: float = 15.0
MARKET_SCORE_NIFTY_DOWN: float = -15.0
MARKET_SCORE_BANKNIFTY_UP: float = 10.0
MARKET_SCORE_BANKNIFTY_DOWN: float = -10.0
MARKET_SCORE_VIX_LOW: float = 15.0       # VIX < 15
MARKET_SCORE_VIX_NORMAL: float = 0.0     # VIX 15-20
MARKET_SCORE_VIX_HIGH: float = -10.0     # VIX 20-25
MARKET_SCORE_VIX_EXTREME: float = -20.0  # VIX > 25
MARKET_SCORE_BREADTH_MAX: float = 20.0   # max adjustment from breadth

# Confidence modifier range: [-20, +20] applied to signal confidence
MARKET_CONF_MOD_BULLISH: float = 10.0
MARKET_CONF_MOD_BEARISH: float = -15.0
MARKET_CONF_MOD_NEUTRAL: float = 0.0

# ── Sector mapping (for sector strength computation) ──────────────────────────
# Approximates the NIFTY 50 universe, grouped into 11 sectors for
# the Market Scanner's Sector Strength module (Sprint 1.5).

SECTOR_MAP: dict[str, list[str]] = {
    "IT":        ["TCS", "INFY", "WIPRO", "HCLTECH", "TECHM"],
    "BANKING":   ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK", "INDUSINDBK"],
    "FINANCE":   ["BAJFINANCE", "BAJAJFINSV", "HDFCLIFE", "SBILIFE", "SHRIRAMFIN"],
    "ENERGY":    ["RELIANCE", "ONGC", "POWERGRID", "NTPC", "COALINDIA"],
    "INFRA":     ["LT", "ULTRACEMCO", "GRASIM", "ADANIPORTS"],
    # TATAMOTORS was removed 2026-08-12 after the Tata Motors demerger.
    # NSE no longer has a tradeable TATAMOTORS equity; the two successor
    # instruments are TMPV (Tata Motors Passenger Vehicles Ltd, ~₹343) and
    # TMCV (Tata Motors Commercial Vehicles Ltd, ~₹457).  Both are live on
    # NSE and yfinance responds to TMPV.NS and TMCV.NS correctly.
    "AUTO":      ["MARUTI", "TMPV", "TMCV", "BAJAJ-AUTO", "EICHERMOT", "M&M", "HEROMOTOCO"],
    "FMCG":      ["HINDUNILVR", "NESTLEIND", "BRITANNIA", "ITC", "TATACONSUM"],
    "PHARMA":    ["SUNPHARMA", "CIPLA", "DRREDDY", "DIVISLAB", "APOLLOHOSP"],
    "METALS":    ["TATASTEEL", "HINDALCO", "JSWSTEEL", "ADANIENT"],
    "CONSUMER":  ["TITAN", "ASIANPAINT", "TRENT"],
    "TELECOM":   ["BHARTIARTL"],
}

# Flattened NIFTY 50 universe (derived from SECTOR_MAP) — used by the
# Market Scanner (Sprint 1.5) to scan the full index.
NIFTY_50: list[str] = [sym for syms in SECTOR_MAP.values() for sym in syms]

# Minimum scanner coverage expected during market hours. Weekend data gaps
# (e.g. Yahoo returning 48/50) are expected to self-resolve at Monday open —
# coverage below this DURING a live session is an operator-visible problem.
MIN_SYMBOLS_EXPECTED: int = len(NIFTY_50)

# ── Default watchlist ─────────────────────────────────────────────────────────

DEFAULT_WATCHLIST: list[str] = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
    "SBIN", "WIPRO", "LT", "BAJFINANCE", "MARUTI",
]

# ── Intraday universe selection ───────────────────────────────────────────────
from enum import Enum
import os as _os
import json as _json


class UniverseMode(str, Enum):
    """Scanner universe choices. Both modes remain paper-trading only."""

    NIFTY_50 = "NIFTY_50"
    CUSTOM_LOW_PRICE_SECTOR = "CUSTOM_LOW_PRICE_SECTOR"


_active_universe_raw = _os.getenv(
    "ACTIVE_INTRADAY_UNIVERSE", UniverseMode.NIFTY_50.value
).upper().strip()
try:
    ACTIVE_INTRADAY_UNIVERSE = UniverseMode(_active_universe_raw)
except ValueError:
    # Fail safe to the long-standing NIFTY universe when deployment
    # configuration is mistyped. The custom universe is always opt-in.
    ACTIVE_INTRADAY_UNIVERSE = UniverseMode.NIFTY_50


def get_active_intraday_universe() -> UniverseMode:
    """Return the operator-selected universe, falling back to deploy config."""
    try:
        from phase20_store import get_settings
        persisted = str(get_settings().get("active_intraday_universe") or "").upper()
        return UniverseMode(persisted)
    except Exception:
        return ACTIVE_INTRADAY_UNIVERSE


def get_active_intraday_universe_strict() -> UniverseMode:
    """Read the durable universe mode without masking storage failures.

    Phase 5A collection is allowed to use environment/default compatibility
    only when its durable settings record is readable. A read failure must not
    silently substitute the legacy watchlist for a custom operator universe.
    """
    from phase20_store import DEFAULT_SETTINGS, _connect, _ensure_schema, db_available

    if not db_available():
        raise RuntimeError("Durable Phase 20 settings are unavailable")

    conn = None
    try:
        conn = _connect()
        _ensure_schema(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT data FROM phase20_settings WHERE id = 1")
            row = cur.fetchone()
        stored = row[0] if row and row[0] else {}
        if isinstance(stored, str):
            stored = _json.loads(stored)
        if not isinstance(stored, dict):
            raise RuntimeError("Durable Phase 20 settings are malformed")
        raw = stored.get(
            "active_intraday_universe",
            DEFAULT_SETTINGS["active_intraday_universe"],
        )
        return UniverseMode(str(raw).upper().strip())
    except Exception as exc:
        raise RuntimeError(f"Durable active universe is unavailable: {exc}") from exc
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass

# Human/provider sector names are intentionally normalised before custom
# universe filtering. Keep this mapping close to configuration rather than
# scattering synonym handling throughout refresh and scan code.
LOW_PRICE_SECTOR_ALIASES: dict[str, str] = {
    "IT": "IT",
    "INFORMATION TECHNOLOGY": "IT",
    "SOFTWARE": "IT",
    "TECHNOLOGY": "IT",
    "INFRASTRUCTURE": "INFRA",
    "CONSTRUCTION": "INFRA",
    "POWER": "INFRA",
    "TELECOM": "INFRA",
    "RAILWAYS": "INFRA",
    "PORTS": "INFRA",
    "ROADS": "INFRA",
    "UTILITIES": "INFRA",
    "BANK": "BANK",
    "BANKS": "BANK",
    "BANKING": "BANK",
    "PSU BANK": "BANK",
    "PRIVATE BANK": "BANK",
}


def normalize_low_price_sector(value: str | None) -> str | None:
    """Map provider sector variants to IT, INFRA, or BANK."""
    cleaned = " ".join(str(value or "").upper().replace("&", " ").split())
    return LOW_PRICE_SECTOR_ALIASES.get(cleaned)

# ── Zerodha integration ───────────────────────────────────────────────────────

ZERODHA_ENABLED: bool = False
ZERODHA_API_KEY: str = ""
ZERODHA_API_SECRET: str = ""
PAPER_TRADING_MODE: bool = True     # always True — no live orders ever

# ── Kite LTP overlay (Option A) ───────────────────────────────────────────────
# When true: daily yfinance OHLCV drives all indicators; Kite live LTP overlays
# current_price / execution_price only, during market hours with a verified
# Kite session.  Falls back to yfinance daily close if Kite is unavailable.
# Default false so existing behaviour is unchanged unless explicitly enabled.
KITE_LTP_OVERLAY_ENABLED: bool = (
    _os.getenv("KITE_LTP_OVERLAY_ENABLED", "false").lower() == "true"
)
