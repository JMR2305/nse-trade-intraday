"""
portfolio_manager.py — Portfolio Manager (v3.0)

Upgrades the AI from a per-stock recommendation engine into a PORTFOLIO
manager. Instead of 50 independent stock decisions, every refresh produces
ONE portfolio decision:

  1. Every NSE-50 stock is ranked by an expected risk-adjusted return score
     built from confidence, expectancy, Sharpe ratio, Kelly fraction,
     historical reliability and current market-regime fit.
  2. Only the TOP opportunities are selected — never every acceptable trade.
  3. Position size is allocated dynamically (half-Kelly, confidence-scaled)
     under hard portfolio rules:
        - max 20% of capital in any single stock
        - max 30% of capital in any single sector
        - max 5 simultaneous NEW positions (up to 7 only when the extra
          candidates have exceptionally high confidence >= 90)
        - keep cash when no high-quality opportunity exists
  4. Portfolio-level metrics are computed: expected monthly return,
     expected max drawdown, portfolio confidence, diversification score,
     sector exposure, cash allocation and a 0-100 risk score.
  5. Actions per stock: BUY | HOLD | REDUCE | INCREASE | EXIT | HOLD_CASH.
  6. Every allocation is explained with historical evidence, current
     technical signals and learned adjustments — including WHY capital
     went to one stock instead of another.
  7. Portfolio-level learning: every persisted portfolio decision is later
     evaluated against an EQUAL-WEIGHT allocation of the same candidate
     set, so the system tracks whether its allocation choices add value.
     Evaluation only uses verified live (yfinance) data — mock data is
     NEVER learned from.

PAPER TRADING ONLY — no orders are placed automatically. This module only
recommends; the user decides.
"""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime, timedelta

import trade_intelligence as _ti

# Tests may monkeypatch this to point at a temp DB.
DB_PATH = _ti.DB_PATH

# ── Portfolio rules (hard caps) ───────────────────────────────────────────────
MAX_STOCK_PCT      = 0.20   # max 20% of total capital in one stock
MAX_SECTOR_PCT     = 0.30   # max 30% of total capital in one sector
MAX_NEW_POSITIONS  = 5      # max simultaneous new positions per decision
MAX_NEW_EXCEPTIONAL = 7     # absolute cap when confidence is exceptional
EXCEPTIONAL_CONF   = 90.0   # RAW confidence needed to unlock slots 6-7 (legacy)
EXCEPTIONAL_CAL_PROB = 0.60  # calibrated win probability to unlock slots 6-7
MIN_QUALITY_SCORE  = 55.0   # risk-adjusted score below this -> keep cash
MIN_ALLOC_FRACTION = 0.05   # positions smaller than 5% are not worth opening
REDUCE_TOLERANCE   = 0.02   # allow 2pp drift above caps before REDUCE

EVAL_HORIZON_DAYS  = 7      # calendar days (~5 trading) before evaluation

_SCHEMA = """
CREATE TABLE IF NOT EXISTS portfolio_decisions (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at     TEXT,
    regime         TEXT,
    total_capital  REAL,
    cash_before    REAL,
    cash_after     REAL,
    stance         TEXT,
    new_buys       TEXT,   -- JSON [{symbol, price, shares, weight_pct, score}]
    candidates     TEXT,   -- JSON [{symbol, price, score}] equal-weight benchmark set
    metrics        TEXT,   -- JSON portfolio metrics snapshot
    evaluated      INTEGER DEFAULT 0,
    evaluation     TEXT    -- JSON {ai_return_pct, equal_weight_return_pct, alpha_pct, ...}
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    conn.commit()
    return conn


def _f(v, default=0.0):
    try:
        x = float(v)
        return x if x == x else default
    except (TypeError, ValueError):
        return default


# ── 1. Risk-adjusted return score ─────────────────────────────────────────────

def _effective_confidence(d: dict) -> float:
    """Confidence used for ranking/sizing decisions (0-100).

    Prefers the CALIBRATED confidence (calibrated win probability × 100,
    Phase 1 confidence calibration) and falls back to the raw final
    confidence when no calibration fields are present."""
    cal = d.get("calibrated_confidence")
    if cal is not None:
        return max(0.0, min(100.0, _f(cal)))
    return max(0.0, min(100.0, _f(d.get("final_confidence"))))


def risk_adjusted_score(d: dict) -> float:
    """
    0-100 expected risk-adjusted return score for one stock decision.
    Deterministic blend of the evidence the engines already computed:
      30% final confidence (incl. learned adjustments)
      25% historical expectancy  (mapped -2%..+3% -> 0..100)
      15% Sharpe ratio           (mapped -1..+3   -> 0..100)
      10% Kelly fraction         (mapped  0..25%  -> 0..100)
      10% historical reliability (trades/30, capped)
      10% market-regime fit      (100 match / 40 mismatch)
    """
    conf   = _effective_confidence(d)
    exp    = _f(d.get("historical_expectancy"))
    sharpe = _f(d.get("historical_sharpe"))
    kelly  = _f(d.get("historical_kelly"))
    n      = int(d.get("historical_trades", 0) or 0)

    exp_score    = max(0.0, min(100.0, (exp + 2.0) / 5.0 * 100.0))
    sharpe_score = max(0.0, min(100.0, (sharpe + 1.0) / 4.0 * 100.0))
    kelly_score  = max(0.0, min(100.0, kelly / 25.0 * 100.0))
    reliability  = min(1.0, n / 30.0) * 100.0
    regime_score = 100.0 if d.get("regime_match") else 40.0

    score = (conf * 0.30 + exp_score * 0.25 + sharpe_score * 0.15 +
             kelly_score * 0.10 + reliability * 0.10 + regime_score * 0.10)
    return round(max(0.0, min(100.0, score)), 1)


def _score_parts(d: dict) -> str:
    return (f"expectancy {_f(d.get('historical_expectancy')):+.2f}%/trade, "
            f"Sharpe {_f(d.get('historical_sharpe')):.2f}, "
            f"Kelly {_f(d.get('historical_kelly')):.1f}%, "
            f"win rate {_f(d.get('historical_win_rate')):.0f}% over "
            f"{int(d.get('historical_trades', 0) or 0)} historical trades, "
            f"confidence {_f(d.get('final_confidence')):.0f}"
            + (" (regime match)" if d.get("regime_match") else " (regime mismatch)"))


# ── 2. Dynamic position sizing ────────────────────────────────────────────────

def target_fraction(d: dict) -> float:
    """
    Target fraction of TOTAL capital for one new position.
    Base: half-Kelly (Kelly fraction / 2, floored at a 6% base when Kelly
    is unavailable), scaled by confidence, clamped to [5%, 20%].
    """
    kelly = max(0.0, _f(d.get("historical_kelly")))          # percent
    conf  = _effective_confidence(d)
    base  = max(kelly / 2.0 / 100.0, 0.06)                   # fraction
    scaled = base * (0.6 + 0.4 * conf / 100.0)
    return max(MIN_ALLOC_FRACTION, min(MAX_STOCK_PCT, scaled))


# ── 3. Build the portfolio plan (pure — no I/O, fully testable) ──────────────

def build_portfolio_plan(decisions: list[dict], state: dict,
                         regime: str = "Neutral",
                         regime_strength: float = 50.0) -> dict:
    """
    Turn per-stock decisions + current paper-portfolio state into ONE
    portfolio decision. Pure function: no network, no DB, no clock other
    than timestamps in the payload.
    """
    by_symbol = {str(d.get("stock", "")).upper(): d for d in decisions}
    positions: dict = state.get("positions", {}) or {}
    cash = _f(state.get("cash"), 0.0)

    # ── Mark-to-market holdings ──────────────────────────────────────────
    holdings: list[dict] = []
    invested = 0.0
    sector_value: dict[str, float] = {}
    for sym, pos in positions.items():
        sym = str(sym).upper()
        d = by_symbol.get(sym, {})
        qty = int(pos.get("quantity", 0) or 0)
        avg = _f(pos.get("avg_price"))
        price = _f(d.get("price")) or avg
        value = qty * price
        invested += value
        sector = str(d.get("sector", "") or "OTHER")
        sector_value[sector] = sector_value.get(sector, 0.0) + value
        holdings.append({
            "symbol": sym, "sector": sector, "quantity": qty,
            "avg_price": round(avg, 2), "current_price": round(price, 2),
            "value": round(value, 2),
            "pnl_pct": round((price - avg) / avg * 100.0, 2) if avg > 0 else 0.0,
            "decision": d,
        })

    total_capital = cash + invested
    if total_capital <= 0:
        total_capital = 1.0  # defensive: avoid div-by-zero on empty state

    # ── Holding actions: EXIT / REDUCE / INCREASE / HOLD ─────────────────
    exits: list[dict] = []
    for h in holdings:
        d = h.pop("decision")
        weight = h["value"] / total_capital
        h["weight_pct"] = round(weight * 100.0, 1)
        h["confidence"] = round(_f(d.get("final_confidence")), 1)
        h["expectancy"] = round(_f(d.get("historical_expectancy")), 2)
        h["score"] = risk_adjusted_score(d) if d else 0.0
        rec = str(d.get("recommendation", "") or "")
        sector_weight = sector_value.get(h["sector"], 0.0) / total_capital

        if rec == "EXIT":
            h["action"] = "EXIT"
            h["action_reason"] = str(d.get("exit_reason") or d.get("reason") or
                                     "Exit condition triggered")
            exits.append({"symbol": h["symbol"], "reason": h["action_reason"]})
        elif weight > MAX_STOCK_PCT + REDUCE_TOLERANCE:
            h["action"] = "REDUCE"
            h["action_reason"] = (
                f"Position is {weight * 100.0:.0f}% of capital — above the "
                f"{MAX_STOCK_PCT * 100.0:.0f}% single-stock limit. Trim back "
                f"to restore diversification.")
        elif sector_weight > MAX_SECTOR_PCT + REDUCE_TOLERANCE:
            h["action"] = "REDUCE"
            h["action_reason"] = (
                f"{h['sector']} holdings are {sector_weight * 100.0:.0f}% of "
                f"capital — above the {MAX_SECTOR_PCT * 100.0:.0f}% sector "
                f"limit. Trim the weakest position in this sector.")
        elif rec == "AVOID" and _f(d.get("historical_expectancy")) < 0:
            h["action"] = "REDUCE"
            h["action_reason"] = (
                f"Evidence turned negative (expectancy "
                f"{_f(d.get('historical_expectancy')):+.2f}%/trade, confidence "
                f"{_f(d.get('final_confidence')):.0f}). Reduce exposure while "
                f"the setup is weak.")
        elif (rec == "STRONG_BUY" and weight < 0.10
              and str(d.get("data_status", "")) == "OK"):
            h["action"] = "INCREASE"
            h["action_reason"] = (
                f"Still a top-ranked opportunity ({_score_parts(d)}) and only "
                f"{weight * 100.0:.0f}% of capital — room to add within the "
                f"{MAX_STOCK_PCT * 100.0:.0f}% cap.")
        else:
            h["action"] = "HOLD"
            h["action_reason"] = (str(d.get("reason") or "").strip()
                                  or "No exit condition; evidence unchanged.")

    # ── Rank BUY candidates by risk-adjusted score ───────────────────────
    candidates: list[dict] = []
    for d in decisions:
        sym = str(d.get("stock", "")).upper()
        if sym in {h["symbol"] for h in holdings}:
            continue  # already held — handled via holding actions
        if str(d.get("recommendation", "")) not in ("STRONG_BUY", "BUY"):
            continue
        if str(d.get("data_status", "")) != "OK":
            continue  # NEVER allocate on mock/unavailable data
        if _f(d.get("price")) <= 0:
            continue
        candidates.append({"decision": d, "score": risk_adjusted_score(d)})
    candidates.sort(key=lambda c: (c["score"],
                                   _f(c["decision"].get("final_confidence"))),
                    reverse=True)

    # ── Allocate under portfolio rules ───────────────────────────────────
    new_buys: list[dict] = []
    skipped: list[dict] = []
    cash_remaining = cash
    sector_running = dict(sector_value)

    def _skip(d: dict, score: float, reason: str) -> None:
        skipped.append({
            "symbol": str(d.get("stock", "")).upper(),
            "sector": str(d.get("sector", "") or "OTHER"),
            "score": score,
            "confidence": round(_f(d.get("final_confidence")), 1),
            "expectancy": round(_f(d.get("historical_expectancy")), 2),
            "reason": reason,
        })

    for c in candidates:
        d, score = c["decision"], c["score"]
        sym = str(d.get("stock", "")).upper()
        sector = str(d.get("sector", "") or "OTHER")
        price = _f(d.get("price"))
        conf = _effective_confidence(d)

        if score < MIN_QUALITY_SCORE:
            _skip(d, score, f"Risk-adjusted score {score:.0f} is below the "
                            f"quality bar ({MIN_QUALITY_SCORE:.0f}) — capital "
                            f"stays in cash rather than in a mediocre setup.")
            continue

        n_open = len(new_buys)
        if n_open >= MAX_NEW_EXCEPTIONAL:
            _skip(d, score, f"Already at the absolute limit of "
                            f"{MAX_NEW_EXCEPTIONAL} new positions.")
            continue
        if n_open >= MAX_NEW_POSITIONS:
            cal_p = d.get("calibrated_probability")
            if cal_p is not None:
                exceptional = _f(cal_p) >= EXCEPTIONAL_CAL_PROB
                bar_txt = (f"calibrated win probability >= "
                           f"{EXCEPTIONAL_CAL_PROB * 100.0:.0f}%, this has "
                           f"{_f(cal_p) * 100.0:.0f}%")
            else:
                exceptional = conf >= EXCEPTIONAL_CONF
                bar_txt = (f">= {EXCEPTIONAL_CONF:.0f} confidence, "
                           f"this has {conf:.0f}")
            if not exceptional:
                _skip(d, score, f"Already opening {MAX_NEW_POSITIONS} new "
                                f"positions — slots 6-7 need exceptional "
                                f"conviction ({bar_txt}).")
                continue

        frac = target_fraction(d)
        sector_room = MAX_SECTOR_PCT * total_capital - sector_running.get(sector, 0.0)
        if sector_room <= 0:
            _skip(d, score, f"{sector} is already at the "
                            f"{MAX_SECTOR_PCT * 100.0:.0f}% sector limit.")
            continue

        budget = min(frac * total_capital, sector_room, cash_remaining)
        shares = int(budget // price) if price > 0 else 0
        if shares < 1:
            if cash_remaining < price:
                why = (f"1 share costs ₹{price:,.0f} but only "
                       f"₹{cash_remaining:,.0f} cash remains.")
            else:
                why = (f"1 share costs ₹{price:,.0f} — more than the "
                       f"₹{budget:,.0f} this stock may receive under the "
                       f"{MAX_STOCK_PCT * 100.0:.0f}% single-stock / "
                       f"{MAX_SECTOR_PCT * 100.0:.0f}% sector caps.")
            _skip(d, score, "Cannot size a position: " + why)
            continue

        alloc = shares * price
        weight_pct = alloc / total_capital * 100.0
        cash_remaining -= alloc
        sector_running[sector] = sector_running.get(sector, 0.0) + alloc

        new_buys.append({
            "symbol": sym, "sector": sector,
            "price": round(price, 2), "shares": shares,
            "allocation": round(alloc, 2),
            "weight_pct": round(weight_pct, 1),
            "score": score,
            "confidence": round(conf, 1),
            "expectancy": round(_f(d.get("historical_expectancy")), 2),
            "sharpe": round(_f(d.get("historical_sharpe")), 2),
            "kelly": round(_f(d.get("historical_kelly")), 1),
            "stop_loss": round(_f(d.get("stop_loss")), 2),
            "target": round(_f(d.get("target")), 2),
            "rr_ratio": round(_f(d.get("rr_ratio")), 2),
            "model_adjustment": round(_f(d.get("model_adjustment")), 1),
            "rationale": (
                f"Ranked #{len(new_buys) + 1} of {len(candidates)} qualifying "
                f"opportunities (risk-adjusted score {score:.0f}). "
                f"{_score_parts(d)}. Sized at {weight_pct:.0f}% of capital via "
                f"half-Kelly scaled by confidence, within the "
                f"{MAX_STOCK_PCT * 100.0:.0f}% stock / "
                f"{MAX_SECTOR_PCT * 100.0:.0f}% sector caps."
                + (f" Learned model adjustment {_f(d.get('model_adjustment')):+.1f} "
                   f"points is already included." if _f(d.get("model_adjustment")) else "")),
            "invalidation_note": (
                (f"This allocation is invalidated if the price closes at or "
                 f"below the stop-loss ₹{_f(d.get('stop_loss')):,.2f}, "
                 if _f(d.get("stop_loss")) > 0 else
                 "This allocation is invalidated ")
                + f"if {sym}'s recommendation drops below BUY on a later "
                  f"scan, or if live data becomes unavailable."),
        })

    # ── Why X over Y (comparisons vs best skipped candidates) ────────────
    comparisons: list[str] = []
    if new_buys:
        top_skipped = [s for s in skipped][:5]
        worst_pick = new_buys[-1]
        for s in top_skipped:
            d_sel = by_symbol.get(worst_pick["symbol"], {})
            d_skp = by_symbol.get(s["symbol"], {})
            comparisons.append(
                f"{worst_pick['symbol']} (score {worst_pick['score']:.0f}) was "
                f"funded ahead of {s['symbol']} (score {s['score']:.0f}): "
                f"{worst_pick['symbol']} shows {_score_parts(d_sel)}; "
                f"{s['symbol']} was skipped because {s['reason']}"
                + (f" Its evidence: {_score_parts(d_skp)}." if d_skp else ""))

    # ── Stance ───────────────────────────────────────────────────────────
    if new_buys:
        stance = "DEPLOY"
    elif holdings:
        stance = "HOLD"
    else:
        stance = "HOLD_CASH"

    # ── Portfolio-level metrics (holdings + planned buys) ────────────────
    lines: list[dict] = []
    for h in holdings:
        d = by_symbol.get(h["symbol"], {})
        lines.append({"symbol": h["symbol"], "sector": h["sector"],
                      "value": h["value"], "conf": _f(d.get("final_confidence")),
                      "exp": _f(d.get("historical_expectancy")),
                      "dd": _f(d.get("expected_drawdown")),
                      "hold": _f(d.get("expected_holding_days"), 5.0)})
    for b in new_buys:
        d = by_symbol.get(b["symbol"], {})
        lines.append({"symbol": b["symbol"], "sector": b["sector"],
                      "value": b["allocation"], "conf": b["confidence"],
                      "exp": b["expectancy"],
                      "dd": _f(d.get("expected_drawdown")),
                      "hold": _f(d.get("expected_holding_days"), 5.0)})

    invested_after = sum(x["value"] for x in lines)
    cash_after = max(0.0, total_capital - invested_after)
    inv_weights = [x["value"] / total_capital for x in lines]

    portfolio_confidence = (
        round(sum(x["conf"] * x["value"] for x in lines) / invested_after, 1)
        if invested_after > 0 else 0.0)

    exp_monthly = 0.0
    exp_dd = 0.0
    for x in lines:
        w = x["value"] / total_capital
        cycles_per_month = 21.0 / max(x["hold"], 5.0)
        exp_monthly += w * x["exp"] * min(cycles_per_month, 4.0)
        exp_dd += w * abs(x["dd"])
    exp_monthly = round(max(-20.0, min(20.0, exp_monthly)), 2)
    exp_dd = round(exp_dd, 2)

    # Diversification: position + sector concentration (HHI-based)
    if inv_weights and invested_after > 0:
        pw = [x["value"] / invested_after for x in lines]
        hhi_pos = sum(w * w for w in pw)
        sec_totals: dict[str, float] = {}
        for x in lines:
            sec_totals[x["sector"]] = sec_totals.get(x["sector"], 0.0) + x["value"]
        sw = [v / invested_after for v in sec_totals.values()]
        hhi_sec = sum(w * w for w in sw)
        diversification = round((1.0 - hhi_pos) * 70.0 + (1.0 - hhi_sec) * 30.0, 1)
        concentration = hhi_pos
    else:
        diversification = 0.0
        concentration = 0.0

    invested_frac = invested_after / total_capital
    risk_score = round(max(0.0, min(100.0,
        (min(exp_dd, 15.0) / 15.0) * 40.0 +
        concentration * invested_frac * 30.0 +
        (100.0 - max(0.0, min(100.0, regime_strength))) / 100.0 * 30.0)), 1)

    # Sector exposure (after planned buys)
    sec_after: dict[str, float] = {}
    for x in lines:
        sec_after[x["sector"]] = sec_after.get(x["sector"], 0.0) + x["value"]
    sector_exposure = [
        {"sector": s, "value": round(v, 2),
         "pct": round(v / total_capital * 100.0, 1),
         "cap_pct": MAX_SECTOR_PCT * 100.0}
        for s, v in sorted(sec_after.items(), key=lambda kv: -kv[1])]

    # ── v2.3 portfolio-level reasoning (deterministic, explanatory only) ─
    cash_pct_after = cash_after / total_capital * 100.0
    if stance == "HOLD_CASH":
        cash_reason = (
            f"100% cash: none of the {len(decisions)} scanned stocks "
            f"currently clears the quality bar (risk-adjusted score >= "
            f"{MIN_QUALITY_SCORE:.0f} with verified live data). Holding "
            f"cash is the deliberate decision when edge is absent.")
    elif not candidates:
        cash_reason = (
            f"₹{cash_after:,.0f} ({cash_pct_after:.0f}%) stays in cash: no "
            f"new stock qualified as a BUY candidate this refresh.")
    elif skipped and cash_after > 0:
        cash_reason = (
            f"₹{cash_after:,.0f} ({cash_pct_after:.0f}%) stays in cash after "
            f"funding the top {len(new_buys)} of {len(candidates)} "
            f"candidates — the rest were skipped for the specific reasons "
            f"listed, not for lack of capital alone.")
    else:
        cash_reason = (
            f"₹{cash_after:,.0f} ({cash_pct_after:.0f}%) remains as an "
            f"unallocated buffer after position sizing under the "
            f"{MAX_STOCK_PCT * 100.0:.0f}% stock and "
            f"{MAX_SECTOR_PCT * 100.0:.0f}% sector caps.")

    concentration_conflicts: list[str] = []
    for s in sector_exposure:
        if s["pct"] > MAX_SECTOR_PCT * 100.0 + REDUCE_TOLERANCE * 100.0:
            concentration_conflicts.append(
                f"{s['sector']} is {s['pct']:.0f}% of capital — above the "
                f"{MAX_SECTOR_PCT * 100.0:.0f}% sector cap. New buys in this "
                f"sector are blocked and a REDUCE is flagged.")
        elif s["pct"] > MAX_SECTOR_PCT * 100.0 * 0.8:
            concentration_conflicts.append(
                f"{s['sector']} is {s['pct']:.0f}% of capital — within 20% "
                f"of the {MAX_SECTOR_PCT * 100.0:.0f}% sector cap; further "
                f"buys in this sector will be limited.")
    for x in lines:
        w_pct = x["value"] / total_capital * 100.0
        if w_pct > MAX_STOCK_PCT * 100.0 + REDUCE_TOLERANCE * 100.0:
            concentration_conflicts.append(
                f"{x['symbol']} is {w_pct:.0f}% of capital — above the "
                f"{MAX_STOCK_PCT * 100.0:.0f}% single-stock cap.")

    rebalance_triggers: list[str] = [
        f"Any position closing above {MAX_STOCK_PCT * 100.0:.0f}% of capital "
        f"triggers a REDUCE recommendation.",
        f"Any sector exceeding {MAX_SECTOR_PCT * 100.0:.0f}% of capital "
        f"triggers a REDUCE of the weakest position in that sector.",
        "A holding whose recommendation turns EXIT (stop-loss, target, "
        "bearish signal or time limit) is flagged for exit at the next "
        "refresh.",
        "A holding whose evidence turns negative (AVOID with negative "
        "expectancy) is flagged for REDUCE.",
    ]

    # ── One-paragraph summary ────────────────────────────────────────────
    n_exits = sum(1 for h in holdings if h["action"] == "EXIT")
    if stance == "DEPLOY":
        summary = (
            f"Market regime: {regime}. Out of {len(decisions)} stocks scanned, "
            f"{len(candidates)} qualified as buy candidates and capital goes to "
            f"the top {len(new_buys)} (₹{sum(b['allocation'] for b in new_buys):,.0f}, "
            f"{sum(b['weight_pct'] for b in new_buys):.0f}% of capital). "
            f"₹{cash_after:,.0f} ({cash_after / total_capital * 100.0:.0f}%) stays "
            f"in cash as a buffer.")
    elif stance == "HOLD":
        summary = (
            f"Market regime: {regime}. No new opportunity beat the quality bar "
            f"this refresh — holding {len(holdings)} existing position(s)"
            + (f", {n_exits} flagged for exit" if n_exits else "")
            + f", and keeping ₹{cash_after:,.0f} in cash. Cash is a position: "
              f"deploying into mediocre setups destroys expectancy.")
    else:
        summary = (
            f"Market regime: {regime}. None of the {len(decisions)} scanned "
            f"stocks currently offers a high-quality, affordable opportunity — "
            f"the whole ₹{total_capital:,.0f} stays in cash. "
            f"Holding cash IS the decision when edge is absent.")

    return {
        "generated_at": datetime.now().isoformat(),
        "market_regime": regime,
        "stance": stance,
        "summary": summary,
        "total_capital": round(total_capital, 2),
        "invested_value": round(invested, 2),
        "planned_invested_value": round(invested_after, 2),
        "cash": round(cash, 2),
        "cash_after": round(cash_after, 2),
        "cash_pct": round(cash_after / total_capital * 100.0, 1),
        "holdings": holdings,
        "new_buys": new_buys,
        "exits": exits,
        "skipped": skipped[:12],
        "skipped_total": len(skipped),
        # Full candidate set for benchmark persistence (untruncated) — stripped
        # from the API payload by get_portfolio_manager().
        "_bench_candidates": (
            [{"symbol": b["symbol"], "price": b["price"], "score": b["score"]}
             for b in new_buys] +
            [{"symbol": s["symbol"], "price": 0.0, "score": s["score"]}
             for s in skipped]),
        "comparisons": comparisons,
        "sector_exposure": sector_exposure,
        "candidate_count": len(candidates),
        "cash_reason": cash_reason,
        "concentration_conflicts": concentration_conflicts,
        "rebalance_triggers": rebalance_triggers,
        "metrics": {
            "portfolio_confidence": portfolio_confidence,
            "expected_monthly_return_pct": exp_monthly,
            "expected_max_drawdown_pct": exp_dd,
            "diversification_score": diversification,
            "risk_score": risk_score,
            "positions_count": len(holdings),
            "new_positions_count": len(new_buys),
            "max_stock_pct": MAX_STOCK_PCT * 100.0,
            "max_sector_pct": MAX_SECTOR_PCT * 100.0,
            "max_new_positions": MAX_NEW_POSITIONS,
        },
        "warning": ("Paper trading only — recommendations, never automatic "
                    "execution. Research tool, not investment advice."),
    }


# ── 4. Persistence + portfolio-level learning ────────────────────────────────

def persist_decision(plan: dict) -> int:
    """Store the decision snapshot so it can be judged later. Only decisions
    with at least one qualifying candidate are stored (otherwise there is
    nothing to benchmark against)."""
    if plan.get("candidate_count", 0) < 1:
        return 0
    # Benchmark set = every qualifying candidate (selected + skipped),
    # equal-weighted. The AI's edge = selective sizing vs naive spreading.
    # Use the UNTRUNCATED candidate list so the benchmark is fair even when
    # the UI-facing "skipped" list is capped for display.
    cand: list[dict] = plan.get("_bench_candidates") or []
    if not cand:
        for b in plan.get("new_buys", []):
            cand.append({"symbol": b["symbol"], "price": b["price"], "score": b["score"]})
        for s in plan.get("skipped", []):
            # skipped rows carry no price; the evaluator refetches history anyway
            cand.append({"symbol": s["symbol"], "price": 0.0, "score": s["score"]})
    with _connect() as conn:
        cur = conn.execute(
            "INSERT INTO portfolio_decisions (created_at, regime, total_capital,"
            " cash_before, cash_after, stance, new_buys, candidates, metrics)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (plan["generated_at"], plan["market_regime"], plan["total_capital"],
             plan["cash"], plan["cash_after"], plan["stance"],
             json.dumps(plan.get("new_buys", [])), json.dumps(cand),
             json.dumps(plan.get("metrics", {}))))
        conn.commit()
        return int(cur.lastrowid or 0)


def _symbol_return(symbol: str, start_iso: str,
                   horizon_days: int = EVAL_HORIZON_DAYS) -> float | None:
    """% return from the first close ON/AFTER start_iso to the first close
    ON/AFTER start + horizon_days (deterministic horizon — late evaluation
    runs do not stretch the measurement window). Returns None unless the
    data source is verified live (yfinance) and the horizon close exists."""
    try:
        from market_data_engine import fetch_candles_df, get_last_source
        df = fetch_candles_df(symbol, interval="1d", period="3mo")
        if get_last_source(symbol) != "yfinance":
            return None  # never learn from mock data
        if df.empty:
            return None
        start = datetime.fromisoformat(start_iso.replace("Z", "+00:00")).replace(tzinfo=None)
        horizon_end = start + timedelta(days=horizon_days)
        rows = df.reset_index()
        date_col = rows.columns[0]
        closes = []
        for _, r in rows.iterrows():
            ts = r[date_col]
            dt = ts.to_pydatetime().replace(tzinfo=None) if hasattr(ts, "to_pydatetime") else ts
            closes.append((dt, float(r["close"])))
        entry = next((c for dt, c in closes if dt >= start), None)
        if entry is None or entry <= 0:
            return None
        exit_close = next((c for dt, c in closes if dt >= horizon_end), None)
        if exit_close is None:
            return None  # horizon close not available yet — defer evaluation
        return (exit_close - entry) / entry * 100.0
    except Exception:
        return None


def evaluate_matured_decisions() -> list[dict]:
    """
    Portfolio-level learning: for every stored decision older than the
    horizon, compare the AI's actual allocation against an equal-weight
    allocation of the SAME candidate set. Only verified live data is used;
    symbols on mock data are excluded, and the evaluation is deferred if
    fewer than 70% of candidates have live data.
    """
    cutoff = (datetime.now() - timedelta(days=EVAL_HORIZON_DAYS)).isoformat()
    actions: list[dict] = []
    with _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM portfolio_decisions WHERE evaluated = 0"
            " AND created_at <= ? ORDER BY created_at LIMIT 5", (cutoff,)).fetchall()
        for row in rows:
            try:
                buys = json.loads(row["new_buys"] or "[]")
                cands = json.loads(row["candidates"] or "[]")
            except Exception:
                buys, cands = [], []
            symbols = sorted({c["symbol"] for c in cands} | {b["symbol"] for b in buys})
            if not symbols:
                conn.execute("UPDATE portfolio_decisions SET evaluated = 1,"
                             " evaluation = ? WHERE id = ?",
                             (json.dumps({"skipped": "no candidates"}), row["id"]))
                continue
            returns = {s: _symbol_return(s, row["created_at"]) for s in symbols}
            live = {s: r for s, r in returns.items() if r is not None}
            if len(live) < max(1, math.ceil(0.7 * len(symbols))):
                continue  # defer — not enough verified live data yet

            total = _f(row["total_capital"], 1.0) or 1.0
            ai_ret = sum((_f(b.get("allocation")) / total) * live.get(b["symbol"], 0.0)
                         for b in buys if b["symbol"] in live)
            ew_symbols = [s for s in {c["symbol"] for c in cands} if s in live]
            ew_ret = (sum(live[s] for s in ew_symbols) / len(ew_symbols)
                      if ew_symbols else 0.0)
            evaluation = {
                "evaluated_at": datetime.now().isoformat(),
                "horizon_days": EVAL_HORIZON_DAYS,
                "ai_return_pct": round(ai_ret, 3),
                "equal_weight_return_pct": round(ew_ret, 3),
                "alpha_pct": round(ai_ret - ew_ret, 3),
                "symbols_evaluated": len(live),
                "symbols_total": len(symbols),
                "data_source": "yfinance",
            }
            conn.execute("UPDATE portfolio_decisions SET evaluated = 1,"
                         " evaluation = ? WHERE id = ?",
                         (json.dumps(evaluation), row["id"]))
            actions.append({"decision_id": row["id"], **evaluation})
        conn.commit()
    return actions


def allocation_performance() -> dict:
    """Aggregate: is selective allocation beating equal weight?"""
    with _connect() as conn:
        rows = conn.execute(
            "SELECT evaluation FROM portfolio_decisions WHERE evaluated = 1"
            " AND evaluation IS NOT NULL").fetchall()
    evals = []
    for r in rows:
        try:
            e = json.loads(r["evaluation"])
            if "ai_return_pct" in e:
                evals.append(e)
        except Exception:
            continue
    if not evals:
        return {"evaluated_count": 0, "avg_ai_return_pct": 0.0,
                "avg_equal_weight_return_pct": 0.0, "avg_alpha_pct": 0.0,
                "outperform_rate_pct": 0.0,
                "verdict": ("Not enough evaluated portfolio decisions yet — "
                            "each decision is judged against an equal-weight "
                            f"benchmark {EVAL_HORIZON_DAYS} days after it is made.")}
    n = len(evals)
    ai = sum(e["ai_return_pct"] for e in evals) / n
    ew = sum(e["equal_weight_return_pct"] for e in evals) / n
    alpha = ai - ew
    outperform = sum(1 for e in evals if e["alpha_pct"] > 0) / n * 100.0
    if alpha > 0.05:
        verdict = (f"Allocation is ADDING value: {alpha:+.2f}% average alpha vs "
                   f"equal weight across {n} decisions ({outperform:.0f}% outperformed).")
    elif alpha < -0.05:
        verdict = (f"Allocation is LAGGING equal weight by {abs(alpha):.2f}% on "
                   f"average across {n} decisions — selection/sizing needs review.")
    else:
        verdict = (f"Allocation is roughly MATCHING equal weight across {n} "
                   f"decisions — no clear edge either way yet.")
    return {"evaluated_count": n,
            "avg_ai_return_pct": round(ai, 3),
            "avg_equal_weight_return_pct": round(ew, 3),
            "avg_alpha_pct": round(alpha, 3),
            "outperform_rate_pct": round(outperform, 1),
            "verdict": verdict}


def recent_decisions(limit: int = 10) -> list[dict]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT id, created_at, regime, stance, total_capital, cash_after,"
            " new_buys, evaluated, evaluation FROM portfolio_decisions"
            " ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        try:
            buys = json.loads(r["new_buys"] or "[]")
        except Exception:
            buys = []
        item = {
            "id": r["id"], "created_at": r["created_at"], "regime": r["regime"],
            "stance": r["stance"],
            "new_buys_count": len(buys),
            "invested_pct": round((1.0 - _f(r["cash_after"]) /
                                   max(_f(r["total_capital"]), 1.0)) * 100.0, 1),
            "evaluated": bool(r["evaluated"]),
        }
        if r["evaluation"]:
            try:
                item["evaluation"] = json.loads(r["evaluation"])
            except Exception:
                pass
        out.append(item)
    return out


# ── 5. Entry point (I/O wrapper) ──────────────────────────────────────────────

def get_portfolio_manager(persist: bool = True) -> dict:
    """
    ONE portfolio decision per refresh:
      evaluate matured past decisions (learning) -> full universe scan ->
      per-stock decisions -> single portfolio allocation plan -> persist.
    """
    effectiveness = []
    try:
        effectiveness = evaluate_matured_decisions()
    except Exception:
        effectiveness = []

    from decision_service import get_trade_decisions
    from paper_trader import _load_state

    payload = get_trade_decisions()
    state = _load_state()

    regime = str(payload.get("market_regime", "Neutral"))
    try:
        from adaptive_learning import regime_strength_of
        regime_strength = regime_strength_of(regime)
    except Exception:
        regime_strength = 50.0

    plan = build_portfolio_plan(payload.get("decisions", []), state,
                                regime=regime, regime_strength=regime_strength)
    plan["model_version"] = int(payload.get("model_version", 0) or 0)

    decision_id = 0
    if persist:
        try:
            decision_id = persist_decision(plan)
        except Exception:
            decision_id = 0
    plan.pop("_bench_candidates", None)
    plan["decision_id"] = decision_id
    plan["benchmark_evaluations"] = effectiveness
    try:
        plan["allocation_performance"] = allocation_performance()
    except Exception:
        plan["allocation_performance"] = {"evaluated_count": 0, "verdict": ""}
    try:
        plan["recent_decisions"] = recent_decisions()
    except Exception:
        plan["recent_decisions"] = []
    return plan
