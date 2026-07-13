"""
balanced_decision_model.py — Phase 3A: Balanced Decision Model (ANALYSIS ONLY).

A shadow decision model evaluated inside the walk-forward harness as model
"G". It NEVER touches the live paper-trading engine, portfolio, trades or
production recommendations — it only re-scores the exact same out-of-sample
decision points and reports what WOULD have happened.

Design (spec Phase 3A):
  A. Eligibility gates are separated from the ranking/confidence score.
     Hard gates reject only for serious issues (missing data, invalid
     levels, impossible sizing, disabled strategy, illiquidity, portfolio
     limits). Minor score weaknesses NEVER hard-reject.
  B. Every score component is normalised to 0-100 and reported with its
     raw value, normalised value, weight and weighted contribution.
  C. Initial balanced weights (configurable, central):
       technical 30, opportunity 20, historical evidence 15, adaptive
       learning 10, regime alignment 10, risk/reward 10, volume 5.
     Data quality acts as a reliability MULTIPLIER (shrinks the score
     toward neutral 50), not an additive component.
  D. Negative overrides are limited: adaptive ±10, similarity ±10,
     combined ±15, with Bayesian shrinkage n/(n+K) for small samples.
     Pre-cap and post-cap values are both reported. The combined cap with
     proportional rescale is the guard against the same historical
     evidence being double-counted through both the pattern and the
     similarity paths.
  E. Cliff thresholds are replaced with smooth ramps (opportunity 40-55,
     volume ratio, regime alignment, weak expectancy).
  F. The final confidence is a CALIBRATED probability produced by the
     existing per-window, no-lookahead calibration process.
  G. Shadow labels: STRONG BUY / BUY / WATCH / AVOID / NO TRADE (+ EXIT
     events reported from the unchanged exit logic).

PAPER TRADING AND RESEARCH ONLY — no real orders, no live changes.
"""

from __future__ import annotations

import math

SAFETY_MESSAGE = ("Phase 3A is an analysis-only shadow model. It never "
                  "changes live recommendations, holdings or paper trades. "
                  "Out-of-sample historical performance does not guarantee "
                  "future results.")

# ── Central configuration (spec §C — all configurable in one place) ──────────

BALANCED_WEIGHTS = {
    "technical": 30.0,
    "opportunity": 20.0,
    "historical_evidence": 15.0,
    "adaptive_learning": 10.0,
    "regime_alignment": 10.0,
    "risk_reward": 10.0,
    "volume_liquidity": 5.0,
}

# Data quality is a reliability multiplier: score is shrunk toward neutral 50
# by up to (1 - DATA_QUALITY_MULT_MIN) when every quality field is missing.
DATA_QUALITY_MULT_MIN = 0.6

# Spec §D — adjustment caps and Bayesian shrinkage
ADJ_CAP_ADAPTIVE = 10.0     # pattern + model adjustment, after shrinkage
ADJ_CAP_SIMILARITY = 10.0   # similarity adjustment, after shrinkage
ADJ_CAP_COMBINED = 15.0     # learning + similarity together
SHRINKAGE_K = 10.0          # shrink factor n / (n + K)

# Spec §G — shadow label thresholds (calibrated probability)
LABEL_THRESHOLDS = {"strong_buy": 0.70, "buy": 0.60, "watch": 0.45}
RELIABILITY_MIN_SAMPLES = 30     # calibrator training samples for STRONG BUY
EXPECTANCY_MIN_TRADES = 10       # pattern-evidence sample to validate expectancy
NEG_EXPECTANCY_PCT = -0.2        # validated-negative expectancy threshold

# Spec §A — hard eligibility gate parameters (serious issues only)
GATE_MIN_PRICE = 1.0             # invalid price data below this
GATE_MIN_RR = 0.8                # absolute minimum risk/reward for an entry
GATE_MIN_VOLUME_RATIO = 0.3      # insufficient liquidity below this

# Spec §E — smooth ramps (no cliffs)
OPP_RAMP_LO, OPP_RAMP_HI = 40.0, 55.0
VOL_RAMP_LO, VOL_RAMP_HI = 0.5, 2.0
RR_FULL_SCORE = 4.0              # rr ratio that maps to 100

# Report/verdict configuration
MIN_TRADES_FOR_VERDICT = 30
MAX_CHANGED_EXAMPLES_PER_WINDOW = 6
MAX_CHANGED_EXAMPLES_TOTAL = 24
MAX_BUY_DECISIONS_KEPT = 400

_REGIME_BASE = {"Bullish": 90.0, "Neutral-Bullish": 70.0,
                "Neutral-Bearish": 40.0, "Bearish": 20.0}

CONFIG_DISPLAY = {
    "weights": BALANCED_WEIGHTS,
    "data_quality_multiplier_range": [DATA_QUALITY_MULT_MIN, 1.0],
    "adjustment_caps": {
        "adaptive_learning": ADJ_CAP_ADAPTIVE,
        "similarity": ADJ_CAP_SIMILARITY,
        "combined": ADJ_CAP_COMBINED,
        "bayesian_shrinkage_k": SHRINKAGE_K,
    },
    "label_thresholds": LABEL_THRESHOLDS,
    "eligibility_gates": {
        "min_price": GATE_MIN_PRICE,
        "min_risk_reward": GATE_MIN_RR,
        "min_volume_ratio": GATE_MIN_VOLUME_RATIO,
        "strategy_policy": "gated ranking (GATES_DEFAULT), no lookahead",
        "portfolio_limits": "20% per stock / 30% per sector (portfolio manager)",
    },
    "smooth_ramps": {
        "opportunity": [OPP_RAMP_LO, OPP_RAMP_HI],
        "volume_ratio": [VOL_RAMP_LO, VOL_RAMP_HI],
        "rr_full_score": RR_FULL_SCORE,
    },
}


# ── Small helpers ─────────────────────────────────────────────────────────────

def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(v)))


def _smoothstep(t: float) -> float:
    """Smooth 0→1 interpolation (continuous value and slope)."""
    t = _clamp(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def _f(v, default: float = 0.0) -> float:
    try:
        if v is None:
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


# ── Normalisers (spec §B/§E — all smooth, all 0-100) ─────────────────────────

def normalize_technical(confidence) -> float:
    return round(_clamp(_f(confidence), 0.0, 100.0), 2)


def normalize_opportunity(opp) -> float:
    """Smooth ramp replaces the old 40/55 cliffs: 0→20 below 40, smooth
    20→60 across 40-55, linear 60→100 above 55."""
    o = _clamp(_f(opp), 0.0, 100.0)
    if o <= OPP_RAMP_LO:
        return round(o / OPP_RAMP_LO * 20.0, 2)
    if o <= OPP_RAMP_HI:
        t = _smoothstep((o - OPP_RAMP_LO) / (OPP_RAMP_HI - OPP_RAMP_LO))
        return round(20.0 + t * 40.0, 2)
    return round(_clamp(60.0 + (o - OPP_RAMP_HI) / (100.0 - OPP_RAMP_HI) * 40.0,
                        0.0, 100.0), 2)


def normalize_volume(volume_ratio) -> float:
    vr = _f(volume_ratio)
    return round(_clamp((vr - VOL_RAMP_LO) / (VOL_RAMP_HI - VOL_RAMP_LO), 0.0, 1.0)
                 * 100.0, 2)


def normalize_rr(rr_ratio) -> float:
    return round(_clamp(_f(rr_ratio) / RR_FULL_SCORE, 0.0, 1.0) * 100.0, 2)


def normalize_regime(item: dict, regime: str) -> float:
    """Proportional regime alignment for a long-only system, plus a small
    bonus when the strategy's preferred regime matches the current one."""
    base = _REGIME_BASE.get(str(regime or ""), 50.0)
    best = str(item.get("best_regime") or "").lower()
    if best and str(regime or "").lower().startswith(best[:4]):
        base += 10.0
    return round(_clamp(base, 0.0, 100.0), 2)


def data_quality(item: dict) -> dict:
    """Fraction of decision-critical fields that are present and sane.
    Returns {score 0-100, multiplier DATA_QUALITY_MULT_MIN..1.0, missing[]}."""
    checks = {
        "price": _f(item.get("price")) > 0,
        "rsi": 0.0 < _f(item.get("rsi")) <= 100.0,
        "adx": _f(item.get("adx")) > 0,
        "atr": _f(item.get("atr")) > 0,
        "vwap": _f(item.get("vwap")) > 0,
        "ema20": _f(item.get("ema20")) > 0,
        "ema50": _f(item.get("ema50")) > 0,
        "volume_ratio": _f(item.get("volume_ratio")) > 0,
    }
    missing = [k for k, ok in checks.items() if not ok]
    frac = (len(checks) - len(missing)) / len(checks)
    mult = DATA_QUALITY_MULT_MIN + (1.0 - DATA_QUALITY_MULT_MIN) * frac
    return {"score": round(frac * 100.0, 2), "multiplier": round(mult, 4),
            "missing": missing}


# ── Spec §D — shrink + cap the learning/similarity adjustments ───────────────

def shrink_and_cap_adjustments(pattern_adj, pattern_n, model_adj,
                               sim_adj, sim_n) -> dict:
    """Bayesian shrinkage (n / (n + K)) then hard caps: adaptive ±10,
    similarity ±10, combined ±15 (proportional rescale). Pre-cap and
    post-cap values are both returned (spec §D). The combined cap is the
    double-counting guard: when pattern and similarity paths react to the
    same underlying historical trades, their joint influence is bounded."""
    p_adj, m_adj, s_adj = _f(pattern_adj), _f(model_adj), _f(sim_adj)
    p_n, s_n = max(0.0, _f(pattern_n)), max(0.0, _f(sim_n))

    p_shrink = p_n / (p_n + SHRINKAGE_K) if (p_n + SHRINKAGE_K) > 0 else 0.0
    s_shrink = s_n / (s_n + SHRINKAGE_K) if (s_n + SHRINKAGE_K) > 0 else 0.0

    adaptive_pre = p_adj + m_adj                    # pre-shrink, pre-cap
    adaptive_shrunk = p_adj * p_shrink + m_adj      # model weights are already
    #                                                 validated/versioned — only
    #                                                 the pattern evidence shrinks
    adaptive_post = _clamp(adaptive_shrunk, -ADJ_CAP_ADAPTIVE, ADJ_CAP_ADAPTIVE)

    sim_pre = s_adj
    sim_shrunk = s_adj * s_shrink
    sim_post = _clamp(sim_shrunk, -ADJ_CAP_SIMILARITY, ADJ_CAP_SIMILARITY)

    combined = adaptive_post + sim_post
    scale = 1.0
    if abs(combined) > ADJ_CAP_COMBINED and abs(combined) > 0:
        scale = ADJ_CAP_COMBINED / abs(combined)
    return {
        "adaptive_pre_cap": round(adaptive_pre, 2),
        "adaptive_shrunk": round(adaptive_shrunk, 2),
        "adaptive_post_cap": round(adaptive_post * scale, 2),
        "similarity_pre_cap": round(sim_pre, 2),
        "similarity_shrunk": round(sim_shrunk, 2),
        "similarity_post_cap": round(sim_post * scale, 2),
        "combined_post_cap": round(_clamp(combined, -ADJ_CAP_COMBINED,
                                          ADJ_CAP_COMBINED), 2),
        "combined_cap_applied": scale < 1.0,
        "pattern_shrink_factor": round(p_shrink, 4),
        "similarity_shrink_factor": round(s_shrink, 4),
    }


# ── Spec §B — component table ─────────────────────────────────────────────────

def compute_components(item: dict, regime: str, adjustments: dict) -> dict:
    """All components on 0-100 with raw / normalised / weight / weighted
    contribution. Historical-evidence and adaptive-learning components are
    neutral at 50 and move by the CAPPED adjustments (spec §D)."""
    hist_norm = _clamp(
        50.0 + adjustments["similarity_post_cap"] * (50.0 / ADJ_CAP_SIMILARITY),
        0.0, 100.0)
    adap_norm = _clamp(
        50.0 + adjustments["adaptive_post_cap"] * (50.0 / ADJ_CAP_ADAPTIVE),
        0.0, 100.0)
    rows = {
        "technical": {
            "raw": round(_f(item.get("confidence")), 2),
            "normalized": normalize_technical(item.get("confidence")),
        },
        "opportunity": {
            "raw": round(_f(item.get("opportunity_score")), 2),
            "normalized": normalize_opportunity(item.get("opportunity_score")),
        },
        "historical_evidence": {
            "raw": adjustments["similarity_pre_cap"],
            "normalized": round(hist_norm, 2),
        },
        "adaptive_learning": {
            "raw": adjustments["adaptive_pre_cap"],
            "normalized": round(adap_norm, 2),
        },
        "regime_alignment": {
            "raw": str(regime or "Unknown"),
            "normalized": normalize_regime(item, regime),
        },
        "risk_reward": {
            "raw": round(_f(item.get("rr_ratio")), 2),
            "normalized": normalize_rr(item.get("rr_ratio")),
        },
        "volume_liquidity": {
            "raw": round(_f(item.get("volume_ratio")), 2),
            "normalized": normalize_volume(item.get("volume_ratio")),
        },
    }
    for key, row in rows.items():
        w = BALANCED_WEIGHTS[key]
        row["weight_pct"] = w
        row["weighted_contribution"] = round(row["normalized"] * w / 100.0, 2)
    return rows


def balanced_score(components: dict, dq: dict) -> dict:
    """Weighted sum of components, then the data-quality reliability
    multiplier shrinks the score toward neutral 50 (spec §C)."""
    base = sum(row["weighted_contribution"] for row in components.values())
    base = _clamp(base, 0.0, 100.0)
    final = _clamp(50.0 + (base - 50.0) * dq["multiplier"], 0.0, 100.0)
    return {"base_score": round(base, 2), "final_score": round(final, 2),
            "data_quality_multiplier": dq["multiplier"]}


# ── Spec §A — hard eligibility gates ─────────────────────────────────────────

def evaluate_eligibility(item: dict, *, strategy_eligible: bool = True,
                         strategy_reason: str = "",
                         sizing_budget: float | None = None,
                         portfolio_ok: bool = True,
                         portfolio_reason: str = "") -> dict:
    """Hard gates ONLY (serious issues). Soft weaknesses (low score, weak
    volume, regime mismatch) are handled as smooth penalties in the score,
    never here."""
    price = _f(item.get("price"))
    stop = _f(item.get("stop_loss"))
    target = _f(item.get("target"))
    rr = _f(item.get("rr_ratio"))
    vr = _f(item.get("volume_ratio"))
    dq = data_quality(item)

    gates = [
        {"gate": "market_data_present", "passed": dq["score"] >= 50.0,
         "reason": ("" if dq["score"] >= 50.0 else
                    f"missing/fallback data: {', '.join(dq['missing'])}")},
        {"gate": "valid_price", "passed": price >= GATE_MIN_PRICE,
         "reason": "" if price >= GATE_MIN_PRICE else f"invalid price {price}"},
        {"gate": "valid_levels", "passed": 0 < stop < price and target > price,
         "reason": ("" if (0 < stop < price and target > price) else
                    "stop/target unavailable — position sizing impossible")},
        {"gate": "min_risk_reward", "passed": rr >= GATE_MIN_RR,
         "reason": ("" if rr >= GATE_MIN_RR else
                    f"risk/reward {rr:.2f} below absolute minimum {GATE_MIN_RR}")},
        {"gate": "liquidity", "passed": vr >= GATE_MIN_VOLUME_RATIO,
         "reason": ("" if vr >= GATE_MIN_VOLUME_RATIO else
                    f"volume ratio {vr:.2f} below {GATE_MIN_VOLUME_RATIO}")},
        {"gate": "strategy_policy", "passed": bool(strategy_eligible),
         "reason": "" if strategy_eligible else
                   (strategy_reason or "strategy disabled by validated policy")},
        {"gate": "portfolio_limits", "passed": bool(portfolio_ok),
         "reason": "" if portfolio_ok else
                   (portfolio_reason or "portfolio/sector risk limit exceeded")},
    ]
    if sizing_budget is not None:
        ok = price > 0 and price <= sizing_budget
        gates.append({"gate": "sizing_possible", "passed": ok,
                      "reason": "" if ok else
                      f"price {price:.2f} exceeds max allocation {sizing_budget:.2f}"})
    return {"gates": gates, "all_passed": all(g["passed"] for g in gates),
            "failed": [g["gate"] for g in gates if not g["passed"]]}


# ── Spec §G — shadow labels ──────────────────────────────────────────────────

def expectancy_evidence(pattern_stats: dict) -> str:
    """'positive' | 'negative' | 'neutral' — validated only with enough sample."""
    n = int(_f((pattern_stats or {}).get("trades")))
    exp = _f((pattern_stats or {}).get("expectancy"))
    if n >= EXPECTANCY_MIN_TRADES and exp <= NEG_EXPECTANCY_PCT:
        return "negative"
    if n >= EXPECTANCY_MIN_TRADES and exp > 0:
        return "positive"
    return "neutral"


def shadow_label(calibrated_prob: float, *, gates_passed: bool,
                 live_signal: bool, evidence: str,
                 reliability_ok: bool) -> str:
    p = _clamp(_f(calibrated_prob), 0.0, 1.0)
    if not gates_passed:
        return "NO TRADE"
    if evidence == "negative":
        return "AVOID"
    if p >= LABEL_THRESHOLDS["strong_buy"] and live_signal \
            and evidence == "positive" and reliability_ok:
        return "STRONG BUY"
    if p >= LABEL_THRESHOLDS["buy"] and live_signal:
        return "BUY"
    if p >= LABEL_THRESHOLDS["watch"]:
        return "WATCH"      # includes promising setups missing confirmation
    return "AVOID"


def score_decision(item: dict, regime: str, *, pattern_adj: float,
                   pattern_stats: dict, model_adj: float, sim_adj: float,
                   sim_matches: int, calibrator: dict | None,
                   strategy_eligible: bool = True, strategy_reason: str = "",
                   sizing_budget: float | None = None,
                   portfolio_ok: bool = True,
                   portfolio_reason: str = "") -> dict:
    """Full Phase 3A scoring for ONE decision point. Pure and deterministic."""
    from confidence_calibration import calibrate_prediction

    adj = shrink_and_cap_adjustments(
        pattern_adj, (pattern_stats or {}).get("trades", 0), model_adj,
        sim_adj, sim_matches)
    components = compute_components(item, regime, adj)
    dq = data_quality(item)
    score = balanced_score(components, dq)
    cal = calibrate_prediction(calibrator, score["final_score"])
    elig = evaluate_eligibility(
        item, strategy_eligible=strategy_eligible,
        strategy_reason=strategy_reason, sizing_budget=sizing_budget,
        portfolio_ok=portfolio_ok, portfolio_reason=portfolio_reason)
    evidence = expectancy_evidence(pattern_stats or {})
    reliability_ok = bool(
        calibrator and calibrator.get("method") not in (None, "", "identity")
        and int(_f(calibrator.get("n_samples"))) >= RELIABILITY_MIN_SAMPLES)
    label = shadow_label(
        cal["calibrated_probability"], gates_passed=elig["all_passed"],
        live_signal=bool(item.get("live_signal")), evidence=evidence,
        reliability_ok=reliability_ok)
    return {
        "components": components,
        "adjustments": adj,
        "data_quality": dq,
        "score": score,
        "calibration": cal,
        "eligibility": elig,
        "expectancy_evidence": evidence,
        "reliability_ok": reliability_ok,
        "label": label,
    }


# ── Window simulation (model G — identical execution mechanics) ─────────────

def simulate_window_balanced(window, sym_rows, date_pos, trained, test_days,
                             nifty, ctx, cfg, cost_model, calibrator,
                             intel, gates, lookahead_log: dict | None = None):
    """Replay ONE test window with Phase 3A decisions. Entry/exit mechanics,
    costs, slippage and portfolio caps are identical to the existing
    variants (next-day-open entry; unchanged stop/target/signal/time/forced
    exit logic — spec §G EXIT). Only the DECISION layer differs."""
    import walk_forward_validator as wfv
    import validation_metrics as vm

    cash = cfg.initial_capital
    positions: dict[str, dict] = {}
    pending: list[dict] = []
    trades: list[dict] = []
    equity_curve: list[float] = []
    equity_dates: list[str] = []
    daily_cash_frac: list[float] = []

    knowledge = ctx["knowledge"]
    vectors = ctx["vectors"]
    weights = ctx["model_weights"]

    label_counts = {"STRONG BUY": 0, "BUY": 0, "WATCH": 0, "AVOID": 0,
                    "NO TRADE": 0, "EXIT": 0}
    transitions: dict[str, int] = {}
    changed_examples: list[dict] = []
    buy_decisions: list[dict] = []
    gate_failure_counts: dict[str, int] = {}

    max_open = wfv.MAX_NEW_POSITIONS

    for di, day in enumerate(test_days):
        day_str = day.strftime("%Y-%m-%d")
        is_last_day = di == len(test_days) - 1
        regime = wfv.regime_as_of(nifty, day)
        regime7 = wfv.regime7_as_of(nifty, day) if intel is not None else None

        # ── 1. Exits (UNCHANGED logic — spec §G EXIT preserved) ─────────
        for sym in list(positions.keys()):
            pos = positions[sym]
            rows = sym_rows[sym]
            pos_idx = date_pos[sym].get(day_str)
            if pos_idx is None:
                if is_last_day:
                    last_known = rows[rows["date"] <= day]
                    if len(last_known) == 0:
                        continue
                    lk = last_known.iloc[-1]
                    wfv._close_position(trades, positions, cost_model, sym, pos,
                                        str(lk["date"])[:10], float(lk["close"]),
                                        wfv.EXIT_FORCED, cfg.intrabar_rule)
                    cash += trades[-1]["exit_price"] * trades[-1]["quantity"] - \
                        trades[-1]["sell_costs"]["total"]
                    if intel is not None:
                        intel.add_completed_trade(trades[-1])
                continue
            row = rows.iloc[pos_idx]
            candle = {"open": float(row["open"]), "high": float(row["high"]),
                      "low": float(row["low"]), "close": float(row["close"])}
            if pos["entry_price"] > 0:
                pos["mae_pct"] = min(pos["mae_pct"],
                                     (candle["low"] - pos["entry_price"]) / pos["entry_price"] * 100.0)
                pos["mfe_pct"] = max(pos["mfe_pct"],
                                     (candle["high"] - pos["entry_price"]) / pos["entry_price"] * 100.0)
            pos["holding_days"] += 1

            exited, raw_exit, reason, _both = wfv.evaluate_exit_candle(
                candle, pos["stop_loss"], pos["target"], cfg.intrabar_rule)
            if not exited:
                prev = rows.iloc[pos_idx - 1]
                try:
                    should_exit, _ = pos["strategy"].check_exit(
                        row, prev, pos["entry_price"], pos["stop_loss"], pos["target"])
                except Exception:
                    should_exit = False
                if should_exit:
                    exited, raw_exit, reason = True, candle["close"], wfv.EXIT_SIGNAL
                elif pos["holding_days"] >= cfg.max_holding_days:
                    exited, raw_exit, reason = True, candle["close"], wfv.EXIT_TIME
                elif is_last_day:
                    exited, raw_exit, reason = True, candle["close"], wfv.EXIT_FORCED
            if exited:
                wfv._close_position(trades, positions, cost_model, sym, pos,
                                    day_str, raw_exit, reason, cfg.intrabar_rule)
                cash += trades[-1]["exit_price"] * trades[-1]["quantity"] - \
                    trades[-1]["sell_costs"]["total"]
                if intel is not None:
                    intel.add_completed_trade(trades[-1])
                if reason == wfv.EXIT_SIGNAL:
                    label_counts["EXIT"] += 1

        # ── 2. Entries queued yesterday, filled at TODAY's open ─────────
        if not is_last_day:
            for rec in pending:
                sym = rec["stock"]
                if sym in positions or len(positions) >= max_open:
                    continue
                pos_idx = date_pos[sym].get(day_str)
                if pos_idx is None:
                    continue
                row = sym_rows[sym].iloc[pos_idx]
                candle = {"date": day_str, "open": float(row["open"]),
                          "high": float(row["high"]), "low": float(row["low"]),
                          "close": float(row["close"]), "volume": float(row["volume"])}
                total_equity = cash + sum(
                    p["quantity"] * wfv._mark_price(sym_rows[s], date_pos[s], day)
                    for s, p in positions.items())
                # Portfolio-manager caps: 20% per stock, 30% per sector,
                # sizing scaled by the CALIBRATED confidence (like variant C).
                stock_cap = total_equity * wfv.MAX_STOCK_PCT
                sector = rec.get("sector", "OTHER")
                sector_used = sum(
                    p["quantity"] * wfv._mark_price(sym_rows[s], date_pos[s], day)
                    for s, p in positions.items() if p.get("sector") == sector)
                sector_room = total_equity * wfv.MAX_SECTOR_PCT - sector_used
                conf = _f(rec.get("calibrated_confidence"),
                          _f(rec.get("final_confidence"), 50.0))
                conf_scale = _clamp(conf / 100.0 + 0.25, 0.5, 1.0)
                alloc = max(0.0, min(stock_cap * conf_scale, sector_room))
                if alloc <= 0:
                    continue
                fill = wfv.simulate_entry(cost_model, candle, rec["price"], cash, alloc)
                if not fill.get("filled"):
                    continue
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
                    "confidence": rec["balanced_final_score"],
                    "raw_confidence": rec["balanced_final_score"],
                    "calibrated_probability": rec.get("calibrated_probability"),
                    "calibrated_confidence": rec.get("calibrated_confidence"),
                    "calibration_method": rec.get("calibration_method", ""),
                    "calibration_version": rec.get("calibration_version", 0),
                    "recommendation": rec["balanced_label"],
                    "sector": rec["sector"],
                    "market_regime": rec["market_regime"],
                    "max_data_timestamp": rec["max_data_timestamp"],
                    "holding_days": 0,
                    "mae_pct": 0.0,
                    "mfe_pct": 0.0,
                }
        pending = []

        # ── 3. Phase 3A decisions from TODAY's close ─────────────────────
        candidates = []
        if not is_last_day:
            knowledge_asof = wfv._knowledge_before(knowledge, day_str)
            knowledge_max_ts = max(
                (str(k.get("exit_date") or "")[:10] for k in knowledge_asof
                 if str(k.get("exit_date") or "")[:10]), default="")
            total_equity_now = cash + sum(
                p["quantity"] * wfv._mark_price(sym_rows[s], date_pos[s], day)
                for s, p in positions.items())
            for sym, tr in trained.items():
                pos_idx = date_pos[sym].get(day_str)
                if pos_idx is None:
                    continue
                item = wfv.build_day_item(sym, sym_rows[sym], pos_idx, tr)
                if item is None:
                    continue

                pattern_adj, p_stats = wfv._pattern_adjustment(
                    item, knowledge_asof, regime)
                sim_adj, sim_max_ts = wfv._similarity_adjustment(
                    item, vectors, regime, day_str)
                model_adj = wfv._model_adjustment(
                    item, regime, item["confidence"], weights)

                if lookahead_log is not None:
                    wfv._audit_decision(lookahead_log, day_str,
                                        item["max_data_timestamp"],
                                        knowledge_max_ts, sim_max_ts)

                # Current engine label (variant-C formula) for the
                # transition matrix — computed, never acted on.
                cur_conf = round(_clamp(item["confidence"] + pattern_adj
                                        + model_adj + sim_adj, 5.0, 95.0), 1)
                current_label = wfv._recommendation_for(item, "C", cur_conf)

                # Strategy policy gate (gated ranking, no lookahead)
                strategy_eligible, strategy_reason = True, ""
                if intel is not None and regime7 is not None:
                    sid = str(item.get("best_strategy_id", "")).lower()
                    rank_row = next(
                        (r for r in intel.rank_gated(regime7, gates)
                         if r["strategy_id"] == sid), None)
                    strategy_eligible = bool(rank_row and rank_row["eligible"])
                    strategy_reason = (rank_row["reason"] if rank_row else
                                       "Unknown strategy — no completed-trade history")

                # Portfolio/sector limit check at decision time
                sector = item.get("sector", "OTHER")
                sector_used = sum(
                    p["quantity"] * wfv._mark_price(sym_rows[s], date_pos[s], day)
                    for s, p in positions.items() if p.get("sector") == sector)
                sector_room = total_equity_now * wfv.MAX_SECTOR_PCT - sector_used
                portfolio_ok = sector_room > 0 and len(positions) < max_open
                portfolio_reason = ("" if portfolio_ok else
                                    ("sector risk limit reached" if sector_room <= 0
                                     else "maximum open positions reached"))

                sim_n = 0
                # similarity match count is not returned by the wfv helper;
                # reuse the adjustment magnitude as reliability proxy: the
                # similarity engine only emits non-zero adjustments with
                # >= 20 trusted matches (or >= 5 consistently-poor ones).
                if abs(sim_adj) > 3.0:
                    sim_n = 20
                elif abs(sim_adj) > 0.0:
                    sim_n = 5

                scored = score_decision(
                    item, regime,
                    pattern_adj=pattern_adj, pattern_stats=p_stats,
                    model_adj=model_adj, sim_adj=sim_adj, sim_matches=sim_n,
                    calibrator=calibrator,
                    strategy_eligible=strategy_eligible,
                    strategy_reason=strategy_reason,
                    sizing_budget=total_equity_now * wfv.MAX_STOCK_PCT,
                    portfolio_ok=portfolio_ok,
                    portfolio_reason=portfolio_reason)

                g_label = scored["label"]
                label_counts[g_label] = label_counts.get(g_label, 0) + 1
                key = f"{current_label} → {g_label}"
                transitions[key] = transitions.get(key, 0) + 1
                for gname in scored["eligibility"]["failed"]:
                    gate_failure_counts[gname] = gate_failure_counts.get(gname, 0) + 1

                base_norm = current_label if current_label != "STRONG BUY" else "BUY"
                g_norm = g_label if g_label != "STRONG BUY" else "BUY"
                if base_norm != g_norm and \
                        len(changed_examples) < MAX_CHANGED_EXAMPLES_PER_WINDOW:
                    changed_examples.append({
                        "window": window["label"], "date": day_str,
                        "symbol": sym,
                        "current_label": current_label,
                        "balanced_label": g_label,
                        "current_confidence": cur_conf,
                        "balanced_score": scored["score"]["final_score"],
                        "calibrated_probability":
                            scored["calibration"]["calibrated_probability"],
                        "components": scored["components"],
                        "adjustments": scored["adjustments"],
                        "failed_gates": scored["eligibility"]["failed"],
                        "reason": _change_reason(scored, current_label, g_label),
                    })

                if g_label in ("STRONG BUY", "BUY"):
                    if len(buy_decisions) < MAX_BUY_DECISIONS_KEPT:
                        fe = wfv.forward_eval(sym_rows[sym], pos_idx)
                        fr10 = (fe.get("forward_returns") or {}).get("10")
                        buy_decisions.append({
                            "window": window["label"], "date": day_str,
                            "symbol": sym, "label": g_label,
                            "calibrated_probability":
                                scored["calibration"]["calibrated_probability"],
                            "forward_return_10d": fr10,
                            "false_positive": (fr10 is not None and fr10 < 0),
                        })
                    if sym not in positions:
                        item.update({
                            "balanced_final_score": scored["score"]["final_score"],
                            "balanced_label": g_label,
                            "market_regime": regime,
                            **scored["calibration"],
                        })
                        candidates.append(item)

            candidates.sort(key=lambda it: (-_f(it.get("calibrated_probability")),
                                            -it["opportunity_score"], it["stock"]))
            slots = max(0, max_open - len(positions))
            pending = candidates[:slots]

        # ── 4. Mark to market ────────────────────────────────────────────
        equity = cash
        for sym, pos in positions.items():
            equity += pos["quantity"] * wfv._mark_price(sym_rows[sym], date_pos[sym], day)
        equity_curve.append(round(equity, 2))
        equity_dates.append(day_str)
        daily_cash_frac.append(cash / equity if equity > 0 else 1.0)

    metrics = vm.compute_performance_metrics(
        trades, cfg.initial_capital, equity_curve, trading_days=len(test_days))
    n_days = len(daily_cash_frac)
    return {
        "window": window["label"],
        "test_start": window["test_start"],
        "test_end": window["test_end"],
        "trades": trades,
        "equity_curve": equity_curve,
        "equity_dates": equity_dates,
        "metrics": metrics,
        "cash_time_pct": round(sum(daily_cash_frac) / n_days * 100.0, 1)
                         if n_days else 100.0,
        "full_cash_days_pct": round(
            sum(1 for c in daily_cash_frac if c >= 0.999) / n_days * 100.0, 1)
            if n_days else 100.0,
        "label_counts": label_counts,
        "transitions": transitions,
        "changed_examples": changed_examples,
        "buy_decisions": buy_decisions,
        "gate_failure_counts": gate_failure_counts,
        "trading_days": len(test_days),
    }


def _change_reason(scored: dict, current_label: str, g_label: str) -> str:
    if g_label == "NO TRADE":
        return ("hard eligibility gate failed: "
                + ", ".join(scored["eligibility"]["failed"]))
    p = scored["calibration"]["calibrated_probability"]
    parts = [f"calibrated probability {p:.0%}"]
    adjc = scored["adjustments"]
    if adjc["combined_cap_applied"]:
        parts.append("learning+similarity influence capped at ±15")
    if abs(adjc["adaptive_pre_cap"] - adjc["adaptive_post_cap"]) > 0.05:
        parts.append(
            f"adaptive adj {adjc['adaptive_pre_cap']:+.1f} capped to "
            f"{adjc['adaptive_post_cap']:+.1f}")
    if abs(adjc["similarity_pre_cap"] - adjc["similarity_post_cap"]) > 0.05:
        parts.append(
            f"similarity adj {adjc['similarity_pre_cap']:+.1f} capped to "
            f"{adjc['similarity_post_cap']:+.1f}")
    if scored["expectancy_evidence"] == "negative":
        parts.append("validated negative expectancy")
    if scored["data_quality"]["multiplier"] < 0.9:
        parts.append("data-quality multiplier "
                     f"{scored['data_quality']['multiplier']:.2f}")
    top = sorted(scored["components"].items(),
                 key=lambda kv: -kv[1]["weighted_contribution"])[:2]
    parts.append("top components: " + ", ".join(
        f"{k} {v['weighted_contribution']:.1f}" for k, v in top))
    return "; ".join(parts)


# ── Aggregation / report (called once after the window loop) ─────────────────

def _breakdown(trades: list[dict], key_fn, label: str) -> list[dict]:
    groups: dict[str, list[dict]] = {}
    for t in trades:
        groups.setdefault(str(key_fn(t) or "unknown"), []).append(t)
    out = []
    for k in sorted(groups):
        g = groups[k]
        wins = sum(1 for t in g if _f(t.get("net_pnl")) > 0)
        out.append({
            label: k, "trades": len(g),
            "win_rate": round(wins / len(g) * 100.0, 1) if g else 0.0,
            "net_pnl": round(sum(_f(t.get("net_pnl")) for t in g), 2),
            "avg_return_pct": round(
                sum(_f(t.get("return_pct")) for t in g) / len(g), 2) if g else 0.0,
        })
    return out


def _conf_band(t: dict) -> str:
    c = _f(t.get("calibrated_confidence"), _f(t.get("confidence")))
    if c < 45:
        return "<45"
    if c < 55:
        return "45-55"
    if c < 65:
        return "55-65"
    if c < 75:
        return "65-75"
    return "75+"


def _model_row(model: str, label: str, metrics: dict, trades: list[dict],
               cash_time_pct) -> dict:
    buys = [t for t in trades
            if str(t.get("recommendation", "")) in ("BUY", "STRONG BUY")]
    fp = sum(1 for t in buys if _f(t.get("net_pnl")) < 0)
    n = len(trades)
    gross = sum(_f(t.get("gross_pnl")) for t in trades)
    hold = (sum(_f(t.get("holding_days")) for t in trades) / n) if n else 0.0
    return {
        "model": model, "label": label,
        "trades": int(metrics.get("total_trades", n) or 0),
        "net_return_pct": metrics.get("total_return_pct", 0.0),
        "gross_pnl": round(gross, 2),
        "profit_factor": metrics.get("profit_factor", 0.0),
        "expectancy": metrics.get("expectancy", 0.0),
        "win_rate": metrics.get("win_rate", 0.0),
        "sharpe_ratio": metrics.get("sharpe_ratio", 0.0),
        "max_drawdown_pct": metrics.get("max_drawdown_pct", 0.0),
        "total_costs": metrics.get("total_costs", 0.0),
        "avg_holding_days": round(hold, 1),
        "cash_time_pct": cash_time_pct,
        "buy_signals": len(buys),
        "strong_buy_signals": sum(
            1 for t in trades if t.get("recommendation") == "STRONG BUY"),
        "false_positive_buys": fp,
        "false_positive_rate_pct": round(fp / len(buys) * 100.0, 1) if buys else 0.0,
        "by_regime": _breakdown(trades, lambda t: t.get("market_regime"), "regime"),
        "by_confidence_band": _breakdown(trades, _conf_band, "band"),
        "by_strategy": _breakdown(trades, lambda t: t.get("strategy_name"), "strategy"),
        "by_sector": _breakdown(trades, lambda t: t.get("sector"), "sector"),
    }


def _concentration(trades: list[dict]) -> dict:
    total = sum(_f(t.get("net_pnl")) for t in trades)
    flags = []
    shares = {}
    if trades and total > 0:
        for name, key_fn in (("symbol", lambda t: t.get("symbol")),
                             ("sector", lambda t: t.get("sector")),
                             ("month", lambda t: str(t.get("exit_date", ""))[:7])):
            sums: dict[str, float] = {}
            for t in trades:
                k = str(key_fn(t) or "?")
                sums[k] = sums.get(k, 0.0) + _f(t.get("net_pnl"))
            top_k = max(sums, key=sums.get)
            share = sums[top_k] / total * 100.0
            shares[f"top_{name}_profit_share_pct"] = round(share, 1)
            shares[f"top_{name}"] = top_k
            if share > 60.0:
                flags.append(f"{share:.0f}% of net profit comes from one "
                             f"{name} ({top_k})")
        best = max((_f(t.get("net_pnl")) for t in trades), default=0.0)
        share = best / total * 100.0
        shares["top_trade_profit_share_pct"] = round(share, 1)
        if share > 50.0:
            flags.append(f"one trade contributes {share:.0f}% of net profit")
    return {"shares": shares, "flags": flags}


def build_balanced_report(g_windows: list[dict], overall: dict,
                          layer_comparison: list[dict], all_trades: dict,
                          cfg, current_calibration_report: dict | None,
                          lookahead_log: dict | None,
                          errors: list[str], progress_cb=None) -> dict:
    """Aggregate every simulated window into the Phase 3A report."""
    import validation_metrics as vm
    from confidence_calibration import (brier_score, log_loss,
                                        expected_calibration_error,
                                        reliability_diagram)

    if progress_cb:
        progress_cb("Phase 3A: aggregating Balanced Decision Model results")

    g_trades: list[dict] = []
    chained: list[float] = []
    factor = 1.0
    label_totals: dict[str, int] = {}
    transitions: dict[str, int] = {}
    changed_examples: list[dict] = []
    buy_decisions: list[dict] = []
    gate_failures: dict[str, int] = {}
    cash_weighted = full_cash = day_total = 0
    window_summaries = []
    for w in g_windows:
        for t in w["trades"]:
            t.setdefault("window", w["window"])
            t["variant"] = "G"
        g_trades.extend(w["trades"])
        for v in w["equity_curve"]:
            chained.append(round(factor * v / cfg.initial_capital
                                 * cfg.initial_capital, 2))
        if w["equity_curve"]:
            factor *= w["equity_curve"][-1] / cfg.initial_capital
        for k, v in w["label_counts"].items():
            label_totals[k] = label_totals.get(k, 0) + v
        for k, v in w["transitions"].items():
            transitions[k] = transitions.get(k, 0) + v
        for k, v in w["gate_failure_counts"].items():
            gate_failures[k] = gate_failures.get(k, 0) + v
        changed_examples.extend(w["changed_examples"])
        buy_decisions.extend(w["buy_decisions"])
        nd = w.get("trading_days", 0)
        cash_weighted += w["cash_time_pct"] / 100.0 * nd
        full_cash += w["full_cash_days_pct"] / 100.0 * nd
        day_total += nd
        window_summaries.append({
            "window": w["window"], "test_start": w["test_start"],
            "test_end": w["test_end"],
            "trades": w["metrics"]["total_trades"],
            "net_return_pct": w["metrics"]["total_return_pct"],
            "profit_factor": w["metrics"]["profit_factor"],
            "win_rate": w["metrics"]["win_rate"],
            "max_drawdown_pct": w["metrics"]["max_drawdown_pct"],
            "cash_time_pct": w["cash_time_pct"],
        })
    changed_examples = changed_examples[:MAX_CHANGED_EXAMPLES_TOTAL]

    total_days = sum(w.get("trading_days", 0) for w in g_windows)
    g_sorted = sorted(g_trades, key=lambda t: (t.get("exit_date", ""),
                                               t.get("symbol", "")))
    g_metrics = vm.compute_performance_metrics(
        g_sorted, cfg.initial_capital, chained or [cfg.initial_capital],
        trading_days=total_days)
    g_cash_pct = round(cash_weighted / day_total * 100.0, 1) if day_total else 100.0

    # ── Model comparison A–G (spec §H). Models A-E exist in this system;
    # spec letter F ("current regime-gated") corresponds to variant E here.
    comparison = []
    for row in layer_comparison:
        v = row["variant"]
        comparison.append(_model_row(
            v, row["label"], overall.get(v, {}), all_trades.get(v, []),
            row.get("cash_time_pct")))
    comparison.append(_model_row(
        "G", "G — Phase 3A Balanced Decision Model (shadow)",
        g_metrics, g_sorted, g_cash_pct))

    # ── Calibration comparison (spec §F) ─────────────────────────────────
    pairs = [(t["calibrated_probability"], 1 if _f(t.get("net_pnl")) > 0 else 0)
             for t in g_sorted if t.get("calibrated_probability") is not None]
    g_cal = None
    if pairs:
        probs = [p for p, _ in pairs]
        outs = [o for _, o in pairs]
        wins = sum(outs)
        g_cal = {
            "samples": len(pairs),
            "avg_calibrated_probability": round(sum(probs) / len(probs), 4),
            "actual_win_rate": round(wins / len(pairs), 4),
            "brier_score": brier_score(probs, outs),
            "ece": expected_calibration_error(probs, outs),
            "log_loss": log_loss(probs, outs),
            "reliability": reliability_diagram(probs, outs),
        }
    current_after = ((current_calibration_report or {}).get("after") or {})
    calibration_comparison = {
        "balanced_model": g_cal,
        "current_model": {
            "brier_score": current_after.get("brier_score"),
            "ece": current_after.get("ece"),
            "log_loss": current_after.get("log_loss"),
            "samples": (current_calibration_report or {}).get("samples", 0),
        },
        "note": ("Both models use the identical per-window calibrators "
                 "fitted ONLY from knowledge trades that exited before each "
                 "test window (no lookahead). The balanced model calibrates "
                 "its 0-100 balanced score through the same process."),
    }

    # ── Decision transitions (spec §I) ───────────────────────────────────
    changed = sum(v for k, v in transitions.items()
                  if k.split(" → ")[0] != k.split(" → ")[1])
    unchanged = sum(v for k, v in transitions.items()
                    if k.split(" → ")[0] == k.split(" → ")[1])
    transition_matrix = {
        "cells": [{"from_label": k.split(" → ")[0],
                   "to_label": k.split(" → ")[1], "count": v}
                  for k, v in sorted(transitions.items(),
                                     key=lambda kv: -kv[1])],
        "changed": changed,
        "unchanged": unchanged,
        "changed_pct": round(changed / (changed + unchanged) * 100.0, 1)
                       if (changed + unchanged) else 0.0,
    }

    # ── False-positive BUY analysis (decision level, forward-looking
    # DIAGNOSTIC only — never fed back into any decision) ─────────────────
    fp_evaluable = [b for b in buy_decisions
                    if b.get("forward_return_10d") is not None]
    fp_count = sum(1 for b in fp_evaluable if b["false_positive"])
    decision_fp = {
        "buy_decisions": len(buy_decisions),
        "evaluable": len(fp_evaluable),
        "false_positives": fp_count,
        "false_positive_rate_pct": round(
            fp_count / len(fp_evaluable) * 100.0, 1) if fp_evaluable else 0.0,
        "note": ("A BUY decision counts as a false positive when the "
                 "10-trading-day forward return was negative. Executed-trade "
                 "false positives (losing BUY trades) are reported per model "
                 "in the comparison table."),
    }

    concentration = _concentration(g_sorted)

    # ── Safety & lookahead audit (spec §J) ───────────────────────────────
    safety_audit = {
        "analysis_only": True,
        "live_recommendations_changed": False,
        "portfolio_modified": False,
        "paper_trades_created_or_closed": False,
        "thresholds_or_enablement_changed": False,
        "lookahead_decisions_checked": int((lookahead_log or {}).get("decisions", 0)),
        "lookahead_violations": int((lookahead_log or {}).get("violations", 0)),
        "window_errors": errors,
        "exit_logic": "unchanged — identical stop/target/signal/time/forced exits",
    }

    verdict = _final_recommendation(
        g_metrics, window_summaries, calibration_comparison, comparison,
        concentration, decision_fp, safety_audit, cfg)

    return {
        "phase": "3A",
        "title": "Phase 3A — Balanced Decision Model (Analysis Only)",
        "config": CONFIG_DISPLAY,
        "model_comparison": comparison,
        "model_mapping_note": (
            "Spec models A-F map to this system's variants: A base technical, "
            "B calibrated pattern+similarity, C adaptive full model, D "
            "corrected gated, E strict regime-gated (spec letters E/F both "
            "correspond to the strategy-variant and regime-gated models here). "
            "G is the new Phase 3A Balanced Decision Model."),
        "overall_metrics": g_metrics,
        "cash_time_pct": g_cash_pct,
        "windows": window_summaries,
        "recommendation_distribution": label_totals,
        "transition_matrix": transition_matrix,
        "changed_decision_examples": changed_examples,
        "calibration_comparison": calibration_comparison,
        "false_positive_analysis": decision_fp,
        "gate_failure_counts": gate_failures,
        "concentration": concentration,
        "safety_audit": safety_audit,
        "final_recommendation": verdict,
        "safety": SAFETY_MESSAGE,
    }


def _final_recommendation(g_metrics: dict, windows: list[dict],
                          cal_cmp: dict, comparison: list[dict],
                          concentration: dict, decision_fp: dict,
                          safety_audit: dict, cfg) -> dict:
    """Evidence-based verdict (spec §L). NEVER activates the model."""
    checks = []

    def _chk(name, observed, threshold, passed):
        checks.append({"name": name, "observed": observed,
                       "threshold": threshold, "passed": bool(passed)})

    n = int(g_metrics.get("total_trades", 0) or 0)
    exp = _f(g_metrics.get("expectancy"))
    pf = _f(g_metrics.get("profit_factor"))
    dd = _f(g_metrics.get("max_drawdown_pct"))
    dd_limit = _f((cfg.verdict_criteria or {}).get("max_drawdown_pct", 20.0), 20.0)

    sample_ok = n >= MIN_TRADES_FOR_VERDICT
    _chk("sufficient out-of-sample trades", n, f">= {MIN_TRADES_FOR_VERDICT}",
         sample_ok)
    _chk("positive net expectancy after costs", exp, "> 0", exp > 0)
    _chk("profit factor", pf, "> 1.10", pf > 1.10)
    _chk("max drawdown within limit", dd, f"<= {dd_limit}", dd <= dd_limit)

    g_brier = ((cal_cmp.get("balanced_model") or {}).get("brier_score"))
    c_brier = ((cal_cmp.get("current_model") or {}).get("brier_score"))
    cal_ok = (g_brier is not None and c_brier is not None and g_brier <= c_brier)
    _chk("calibration (Brier) better than current model",
         g_brier if g_brier is not None else "n/a",
         f"<= {c_brier}" if c_brier is not None else "current unavailable",
         cal_ok)

    conc_ok = not concentration.get("flags")
    _chk("results not concentrated in one stock/sector/month/trade",
         "; ".join(concentration.get("flags") or []) or "no flags",
         "no concentration flags", conc_ok)

    ok_windows = [w for w in windows if _f(w.get("net_return_pct")) >= 0]
    win_ok = len(windows) >= 2 and len(ok_windows) * 2 >= len(windows)
    _chk("acceptable performance across windows",
         f"{len(ok_windows)}/{len(windows)} windows non-negative",
         ">= half of >= 2 windows", win_ok)

    viol = int(safety_audit.get("lookahead_violations", 0))
    _chk("no lookahead leakage", viol, "== 0", viol == 0)

    cur_fp = next((r["false_positive_rate_pct"] for r in comparison
                   if r["model"] == "C"), 0.0)
    g_fp = next((r["false_positive_rate_pct"] for r in comparison
                 if r["model"] == "G"), 0.0)
    fp_ok = g_fp <= cur_fp + 10.0
    _chk("no material increase in false-positive BUYs (executed)",
         f"G {g_fp}% vs current {cur_fp}%", "G <= current + 10pp", fp_ok)

    if viol > 0:
        rec, why = "REJECT", "Lookahead violations were detected — results invalid."
    elif sample_ok and (exp <= 0 or pf <= 1.0):
        rec, why = "REJECT", ("With a sufficient out-of-sample sample the "
                              "model shows non-positive expectancy or a "
                              "profit factor at/below 1.0 after costs.")
    elif all(c["passed"] for c in checks):
        rec, why = ("ELIGIBLE FOR LIMITED SHADOW PAPER TEST",
                    "All out-of-sample success criteria passed. This does NOT "
                    "activate the model — a limited shadow paper test must be "
                    "started manually and evaluated separately.")
    else:
        failed = [c["name"] for c in checks if not c["passed"]]
        rec, why = "CONTINUE ANALYSIS", (
            "Not all success criteria are met yet: " + "; ".join(failed) + ". "
            "Collect more out-of-sample evidence before any shadow paper test.")

    return {"recommendation": rec, "summary": why, "checks": checks,
            "auto_activation": False}
