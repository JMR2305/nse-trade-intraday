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

from datetime import datetime
from typing import TypedDict

from config import INITIAL_CAPITAL

RELIABLE_SAMPLE   = 20     # min historical trades for a reliable sample
STRONG_BUY_CONF   = 85.0
BUY_CONF          = 75.0
WATCH_CONF        = 55.0
TIME_EXIT_FACTOR  = 2.0    # exit when held > factor × expected holding days
TIME_EXIT_MIN_DAYS = 30.0  # ... but never earlier than this many days

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
    # Confidence
    base_confidence: float
    learning_adjustment: float
    final_confidence: float
    # Historical evidence
    historical_expectancy: float
    historical_profit_factor: float
    historical_win_rate: float
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
    failed_conditions: list
    breakdown: list              # list[DecisionFactor] summing to final_confidence


def _last_buy_meta(trades: list, symbol: str) -> dict:
    """Most recent BUY record for `symbol` (holds stop/target metadata)."""
    for tr in reversed(trades or []):
        if tr.get("symbol", "").upper() == symbol.upper() and tr.get("action") == "BUY":
            return tr
    return {}


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
            regime_strength: float = 50.0) -> TradeDecision:
    sym    = str(item.get("stock", "")).upper()
    err    = item.get("error")
    fc     = float(item.get("final_confidence", item.get("confidence", 0.0)) or 0.0)
    base   = float(item.get("base_confidence", item.get("confidence", 0.0)) or 0.0)
    adj    = float(item.get("learning_adjustment", 0.0) or 0.0)
    exp    = float(item.get("historical_expectancy", 0.0) or 0.0)
    pf     = float(item.get("historical_profit_factor", 0.0) or 0.0)
    wr     = float(item.get("historical_win_rate", 0.0) or 0.0)
    n_hist = int(item.get("historical_trades", 0) or 0)
    rr     = float(item.get("rr_ratio", 0.0) or 0.0)
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

    low_reliability = n_hist < RELIABLE_SAMPLE

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

        if (fc >= STRONG_BUY_CONF and exp > 1.0 and pf >= 1.5
                and not low_reliability and rr >= 2.0 and filter_passed):
            recommendation = "STRONG_BUY"
            reason = f"Confidence {fc:.0f}, expectancy {exp:+.2f}%, PF {pf:.2f}, R:R {rr:.1f}:1"
        elif (BUY_CONF <= fc < STRONG_BUY_CONF and exp > 0 and pf > 1.2 and rr >= 2.0):
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

    # Build the longer explanation for the expanded row
    parts = [
        f"{recommendation.replace('_', ' ')}: {reason}.",
        f"Base technical confidence {base:.0f}, learning adjustment {adj:+.0f} → final {fc:.0f}.",
    ]
    if n_hist > 0:
        parts.append(
            f"Best pattern: {item.get('best_strategy_name', '')} in {item.get('sector', '')} "
            f"({item.get('best_regime', '')} regime) — {n_hist} historical matches, "
            f"{wr:.0f}% win rate, expectancy {exp:+.2f}%, PF {pf:.2f}."
        )
    else:
        parts.append("No historical pattern matches yet — evidence is limited.")
    if low_reliability:
        parts.append(f"LOW RELIABILITY: fewer than {RELIABLE_SAMPLE} historical samples.")
    if not data_ok:
        parts.append("Live NSE data unavailable — no buy recommendations are issued on fallback data.")
    if position_open:
        parts.append(
            f"Open paper position: {pos_qty} shares @ ₹{pos_avg:.2f} ({pos_pnl_pct:+.2f}%)."
        )
    learning_expl = str(item.get("learning_explanation", "") or "")
    if learning_expl:
        parts.append(learning_expl)

    return TradeDecision(
        stock=sym,
        sector=str(item.get("sector", "")),
        recommendation=recommendation,
        data_status="OK" if data_ok else "DATA_UNAVAILABLE",
        low_reliability=low_reliability,
        base_confidence=round(base, 1),
        learning_adjustment=round(adj, 1),
        final_confidence=round(fc, 1),
        historical_expectancy=round(exp, 2),
        historical_profit_factor=round(pf, 2),
        historical_win_rate=round(wr, 1),
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
        failed_conditions=failed,
        breakdown=_build_breakdown(item, data_ok, regime_strength, round(fc, 1)),
    )


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

    decisions = [_decide(it, positions, trades, regime_strength)
                 for it in scan["items"]]

    decisions.sort(key=lambda d: (_ORDER.get(d["recommendation"], 9),
                                  -d["final_confidence"]))

    counts = {k: 0 for k in _ORDER}
    for d in decisions:
        counts[d["recommendation"]] = counts.get(d["recommendation"], 0) + 1

    return {
        "generated_at": datetime.now().isoformat(),
        "market_regime": regime_now,
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
