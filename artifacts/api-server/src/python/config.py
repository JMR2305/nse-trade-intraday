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

INITIAL_CAPITAL: float = 5000.0
MAX_RISK_PCT: float = 0.01          # 1% max risk per trade (₹50 on ₹5000)
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
    "IT":        ["TCS", "INFY", "WIPRO", "HCLTECH", "TECHM", "LTIM"],
    "BANKING":   ["HDFCBANK", "ICICIBANK", "SBIN", "AXISBANK", "KOTAKBANK", "INDUSINDBK"],
    "FINANCE":   ["BAJFINANCE", "BAJAJFINSV", "HDFCLIFE", "SBILIFE", "SHRIRAMFIN"],
    "ENERGY":    ["RELIANCE", "ONGC", "POWERGRID", "NTPC", "COALINDIA"],
    "INFRA":     ["LT", "ULTRACEMCO", "GRASIM", "ADANIPORTS"],
    "AUTO":      ["MARUTI", "TATAMOTORS", "BAJAJ-AUTO", "EICHERMOT", "M&M", "HEROMOTOCO"],
    "FMCG":      ["HINDUNILVR", "NESTLEIND", "BRITANNIA", "ITC", "TATACONSUM"],
    "PHARMA":    ["SUNPHARMA", "CIPLA", "DRREDDY", "DIVISLAB", "APOLLOHOSP"],
    "METALS":    ["TATASTEEL", "HINDALCO", "JSWSTEEL", "ADANIENT"],
    "CONSUMER":  ["TITAN", "ASIANPAINT", "TRENT"],
    "TELECOM":   ["BHARTIARTL"],
}

# Flattened NIFTY 50 universe (derived from SECTOR_MAP) — used by the
# Market Scanner (Sprint 1.5) to scan the full index.
NIFTY_50: list[str] = [sym for syms in SECTOR_MAP.values() for sym in syms]

# ── Default watchlist ─────────────────────────────────────────────────────────

DEFAULT_WATCHLIST: list[str] = [
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK",
    "SBIN", "WIPRO", "LT", "BAJFINANCE", "MARUTI",
]

# ── Zerodha integration (future) ──────────────────────────────────────────────

ZERODHA_ENABLED: bool = False
ZERODHA_API_KEY: str = ""
ZERODHA_API_SECRET: str = ""
PAPER_TRADING_MODE: bool = True     # always True until Zerodha is wired
