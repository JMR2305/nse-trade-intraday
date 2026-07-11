"""
analyst_reasoning.py — v2.3 Analyst Reasoning and Decision Invalidation Layer.

Turns one completed TradeDecision (plus the raw scanner item it was built
from) into a disciplined analyst assessment:

  A. current_observation      — what the system sees NOW (live indicators only)
  B. historical_assessment    — what happened in similar historical setups
                                (similarity evidence ONLY — no pattern stats)
  C. decision_reasoning       — why the recommendation was made, with the
                                exact source of every adjustment
  D. invalidation_conditions / upgrade_conditions — specific measurable
                                triggers that would change the decision

Plus decision monitoring: decision_state, valid_until, conflict detection
and a concise analyst summary (<= 120 words).

Rules:
  - PAPER TRADING ONLY. This module never changes a recommendation,
    confidence number, strategy rule or learning safeguard — it only
    explains and monitors decisions that were already made.
  - Every statement is deterministic and derived from fields the engines
    already computed. Nothing is invented.
  - Correlation is never presented as causation: historical factor overlap
    is described as associated evidence, not as a proven cause.
"""

from __future__ import annotations

from datetime import datetime, timedelta

try:
    from zoneinfo import ZoneInfo
    _IST = ZoneInfo("Asia/Kolkata")
except Exception:                                    # pragma: no cover
    _IST = None

# Deterministic thresholds — mirror the values already used by the scanner /
# decision service. Changing behaviour is out of scope: these are used ONLY
# to describe invalidation/upgrade triggers, never to alter a decision.
RSI_WEAK          = 40.0    # RSI below this = momentum breakdown
RSI_TARGET_LOW    = 45.0    # healthy momentum band lower edge
VOLUME_MIN_RATIO  = 0.75    # scanner risk-filter volume floor
MIN_RR            = 2.0     # minimum acceptable risk/reward
OPP_SCORE_MIN     = 50.0    # opportunity-score risk-filter floor
WATCH_CONF        = 55.0    # decision-service WATCH floor
BUY_CONF          = 75.0    # decision-service BUY floor
SECTOR_RANK_MAX   = 3       # scanner "top sector" requirement
MARKET_CLOSE_H    = 15      # NSE daily close 15:30 IST
MARKET_CLOSE_M    = 30

DECISION_STATES = ("VALID", "WEAKENING", "INVALIDATED", "IMPROVING",
                   "EXPIRED", "DATA_LIMITED")
CONFLICT_LEVELS = ("NONE", "LOW", "MEDIUM", "HIGH")


def _f(v, default=0.0) -> float:
    try:
        x = float(v)
        return x if x == x else default
    except (TypeError, ValueError):
        return default


def _now_ist(now: datetime | None) -> datetime:
    if now is not None:
        return now
    if _IST is not None:
        return datetime.now(_IST).replace(tzinfo=None)
    return datetime.now()


def next_daily_close(now: datetime) -> datetime:
    """Next completed NSE daily candle (15:30 IST), skipping weekends.
    Deterministic given `now` (naive IST)."""
    close_today = now.replace(hour=MARKET_CLOSE_H, minute=MARKET_CLOSE_M,
                              second=0, microsecond=0)
    candidate = close_today if now < close_today else close_today + timedelta(days=1)
    while candidate.weekday() >= 5:          # Sat=5, Sun=6
        candidate += timedelta(days=1)
    return candidate


def _cond(metric: str, current, trigger, direction: str, why: str,
          met: bool) -> dict:
    return {
        "metric": metric,
        "current_value": str(current),
        "trigger_value": str(trigger),
        "direction": direction,
        "why": why,
        "met": bool(met),
    }


# ── Section A — what the system sees now ─────────────────────────────────────

def build_current_observation(decision: dict, item: dict,
                              regime_now: str) -> str:
    sym = str(decision.get("stock", ""))
    tech = (decision.get("explanation_sections") or {}).get("technical") or {}
    trend = tech.get("trend", "")
    momentum = tech.get("momentum", "")
    volume = tech.get("volume", "")
    vol_pct = item.get("volatility")
    sector = str(decision.get("sector", "") or "")
    sector_rank = item.get("sector_rank")
    rr = _f(decision.get("rr_ratio"))
    data_ok = str(decision.get("data_status", "")) == "OK"
    pos_open = bool(decision.get("position_open"))

    bits = [f"{sym}: {trend}.", f"Momentum: {momentum}.", f"Volume: {volume}."]
    if vol_pct is not None:
        bits.append(f"Volatility: {_f(vol_pct):.1f}% annualised.")
    bits.append(f"Market regime: {regime_now}.")
    if sector:
        if sector_rank is not None:
            bits.append(f"Sector: {sector} (rank {int(sector_rank)} of the "
                        f"scanned sectors).")
        else:
            bits.append(f"Sector: {sector}.")
    bits.append(f"Risk/reward: {rr:.1f}:1." if rr > 0
                else "Risk/reward: not available.")
    bits.append("Data quality: verified live NSE data." if data_ok
                else "Data quality: live data unavailable — this assessment "
                     "is provisional.")
    if pos_open:
        qty = int(decision.get("position_quantity", 0) or 0)
        avg = _f(decision.get("position_avg_price"))
        pnl = _f(decision.get("position_pnl_pct"))
        bits.append(f"Open paper position: {qty} shares @ ₹{avg:.2f} "
                    f"({pnl:+.2f}%).")
    else:
        bits.append("No open position.")
    return " ".join(bits)


# ── Section B — what happened in similar historical setups ───────────────────

def build_historical_assessment(decision: dict) -> str:
    ev = decision.get("similarity_evidence")
    if not isinstance(ev, dict) or int(ev.get("match_count", 0) or 0) == 0:
        return ("No sufficiently similar historical setups were found, so no "
                "similarity evidence is available for this decision.")
    stats = ev.get("stats") or {}
    n = int(ev.get("match_count", 0) or 0)
    avg_sim = _f(ev.get("avg_similarity"))
    wr = _f(stats.get("win_rate"))
    exp = _f(stats.get("expectancy"))
    pf = _f(stats.get("profit_factor"))
    avg_ret = _f(stats.get("avg_return"))
    mae = _f(stats.get("max_adverse_excursion"))
    hold = _f(stats.get("avg_holding_days"))
    reliability = str(decision.get("evidence_reliability", "") or "VERY_LOW")
    txt = (f"Among {n} similar historical setups with {avg_sim:.0f}% average "
           f"similarity, {wr:.0f}% were profitable. Expectancy was "
           f"{exp:+.2f}% and profit factor was {pf:.2f}. Average return was "
           f"{avg_ret:+.2f}% per trade")
    if hold > 0:
        txt += f" over an average holding period of {hold:.0f} days"
    txt += "."
    if mae != 0:
        txt += (f" The worst adverse move among these trades was "
                f"{mae:.2f}%.")
    txt += f" Evidence reliability: {reliability.replace('_', ' ')}."
    return txt


# ── Section C — why this recommendation was made ─────────────────────────────

def build_decision_reasoning(decision: dict) -> str:
    rec = str(decision.get("recommendation", ""))
    reason = str(decision.get("reason", "") or "")
    summary = ((decision.get("explanation_sections") or {}).get("summary")
               or {})
    base = _f(summary.get("technical_confidence"))
    adj_learn = _f(summary.get("learning_adjustment"))
    adj_model = _f(summary.get("model_adjustment"))
    adj_sim = _f(summary.get("similarity_adjustment"))
    fc = _f(summary.get("final_confidence"))

    adjustments = [
        ("adaptive learning", adj_learn),
        ("self-evaluation model", adj_model),
        ("historical similarity evidence", adj_sim),
    ]
    named = [(name, a) for name, a in adjustments if a != 0]
    biggest = max(named, key=lambda t: abs(t[1]), default=None)

    parts = []
    # Greatest impact
    if biggest is None or base >= max(abs(a) for _, a in adjustments) * 4 + 1:
        parts.append(f"The largest input to this decision was the current "
                     f"technical assessment itself (technical confidence "
                     f"{base:.0f}).")
    else:
        name, a = biggest
        parts.append(f"Beyond the technical confidence of {base:.0f}, the "
                     f"largest single adjustment came from {name} "
                     f"({a:+.1f} points).")
    # Supporting vs contradicting evidence
    supporting = [f"{name} ({a:+.1f})" for name, a in named if a > 0]
    contradicting = [f"{name} ({a:+.1f})" for name, a in named if a < 0]
    tech = ((decision.get("explanation_sections") or {}).get("technical")
            or {})
    if not tech.get("risk_filters_passed", True):
        contradicting.append("failed risk filters")
    if supporting:
        parts.append("Supporting evidence: " + ", ".join(supporting) + ".")
    if contradicting:
        parts.append("Contradicting evidence: " + ", ".join(contradicting) + ".")
    if not supporting and not contradicting:
        parts.append("No adjustment moved the confidence — the decision "
                     "rests on the technical assessment alone.")
    # Pattern knowledge disclaimer (single fixed source statement)
    pattern = (decision.get("explanation_sections") or {}).get("pattern")
    if pattern:
        parts.append(f"Descriptive Pattern Knowledge (expectancy "
                     f"{_f(pattern.get('expectancy')):+.2f}%, PF "
                     f"{_f(pattern.get('profit_factor')):.2f} over "
                     f"{int(pattern.get('sample_size', 0) or 0)} trades) did "
                     f"not affect the confidence.")
    # Final recommendation
    parts.append(f"Final confidence {fc:.0f} → "
                 f"{rec.replace('_', ' ')}: {reason}.")
    return " ".join(parts)


# ── Section D — invalidation / upgrade conditions ────────────────────────────

def build_conditions(decision: dict, item: dict,
                     regime_now: str) -> tuple[list[dict], list[dict]]:
    """Return (invalidation_conditions, upgrade_conditions). Both lists are
    always built so the UI can show the relevant one; `met` flags are
    evaluated deterministically against CURRENT values."""
    rec = str(decision.get("recommendation", ""))
    price = _f(decision.get("price"))
    stop = _f(decision.get("stop_loss"))
    target = _f(decision.get("target"))
    rr = _f(decision.get("rr_ratio"))
    rsi = _f(item.get("rsi"))
    macd_h = _f(item.get("macd_hist"))
    vol_ratio = _f(item.get("volume_ratio"))
    opp = _f(item.get("opportunity_score"))
    ema20 = _f(item.get("ema20"))
    ema50 = _f(item.get("ema50"))
    above20 = bool(item.get("above_ema20"))
    above50 = bool(item.get("above_ema50"))
    sector_rank = item.get("sector_rank")
    fc = _f(decision.get("final_confidence"))
    sim = ((decision.get("explanation_sections") or {}).get("similarity")
           or {})
    sim_exp = _f(sim.get("expectancy"))
    sim_n = int(sim.get("match_count", 0) or 0)
    regime_bearish = "bear" in str(regime_now).lower()

    invalidation: list[dict] = []
    upgrade: list[dict] = []

    # Downside triggers (relevant when the stance is constructive)
    if stop > 0:
        invalidation.append(_cond(
            "Price vs stop-loss", f"₹{price:.2f}", f"₹{stop:.2f}", "below",
            "A close at or below the stop-loss ends the trade plan — the "
            "planned risk has been realised.", price > 0 and price <= stop))
    if ema50 > 0:
        invalidation.append(_cond(
            "Price vs EMA50", f"₹{price:.2f}", f"₹{ema50:.2f}", "below",
            "A close below EMA50 turns the medium-term trend bearish.",
            not above50))
    invalidation.append(_cond(
        "RSI", f"{rsi:.0f}", f"{RSI_WEAK:.0f}", "below",
        "RSI below this level signals a momentum breakdown.",
        rsi > 0 and rsi < RSI_WEAK))
    invalidation.append(_cond(
        "MACD histogram", f"{macd_h:+.2f}", "0", "below",
        "A negative MACD histogram means short-term momentum has turned "
        "bearish.", macd_h < 0))
    invalidation.append(_cond(
        "Volume ratio", f"{vol_ratio:.2f}×", f"{VOLUME_MIN_RATIO:.2f}×",
        "below",
        "Without volume confirmation the move loses institutional support.",
        vol_ratio > 0 and vol_ratio < VOLUME_MIN_RATIO))
    if sector_rank is not None:
        invalidation.append(_cond(
            "Sector rank", str(int(sector_rank)), str(SECTOR_RANK_MAX),
            "above",
            "Falling out of the top sectors removes the relative-strength "
            "tailwind.", int(sector_rank) > SECTOR_RANK_MAX))
    invalidation.append(_cond(
        "Market regime", regime_now, "Bearish", "equals",
        "A bearish market regime historically weakens long swing setups.",
        regime_bearish))
    invalidation.append(_cond(
        "Risk/reward", f"{rr:.1f}:1", f"{MIN_RR:.0f}:1", "below",
        "Below the minimum risk/reward the trade no longer pays for its "
        "risk.", rr > 0 and rr < MIN_RR))

    # Upgrade triggers (relevant when the stance is WATCH / AVOID / EXIT)
    if ema20 > 0:
        upgrade.append(_cond(
            "Price vs EMA20", f"₹{price:.2f}", f"₹{ema20:.2f}", "above",
            "Reclaiming EMA20 is the first sign the short-term trend is "
            "turning up.", above20))
    if ema50 > 0:
        upgrade.append(_cond(
            "Price vs EMA50", f"₹{price:.2f}", f"₹{ema50:.2f}", "above",
            "A close above EMA50 restores the medium-term uptrend.",
            above50))
    upgrade.append(_cond(
        "RSI", f"{rsi:.0f}", f"{RSI_TARGET_LOW:.0f}", "above",
        "RSI back in the healthy band shows momentum recovering without "
        "being overbought.", rsi >= RSI_TARGET_LOW))
    upgrade.append(_cond(
        "MACD histogram", f"{macd_h:+.2f}", "0", "above",
        "A positive MACD histogram confirms short-term momentum has turned "
        "up.", macd_h > 0))
    upgrade.append(_cond(
        "Volume ratio", f"{vol_ratio:.2f}×", f"{VOLUME_MIN_RATIO:.2f}×",
        "above",
        "Volume at or above this floor confirms participation in the move.",
        vol_ratio >= VOLUME_MIN_RATIO))
    upgrade.append(_cond(
        "Opportunity score", f"{opp:.0f}", f"{OPP_SCORE_MIN:.0f}", "above",
        "The scanner requires this minimum before a setup qualifies.",
        opp >= OPP_SCORE_MIN))
    if sim_n > 0:
        upgrade.append(_cond(
            "Similarity expectancy", f"{sim_exp:+.2f}%", "0%", "above",
            "Positive expectancy among similar past trades is required "
            "before evidence supports a buy.", sim_exp > 0))
    upgrade.append(_cond(
        "Final confidence", f"{fc:.0f}",
        f"{BUY_CONF:.0f}" if rec in ("WATCH",) else f"{WATCH_CONF:.0f}",
        "above",
        "Confidence must clear the decision threshold before the "
        "recommendation can upgrade.",
        fc >= (BUY_CONF if rec in ("WATCH",) else WATCH_CONF)))
    upgrade.append(_cond(
        "Market regime", regime_now, "Bullish", "equals",
        "A bullish regime historically improves long swing outcomes.",
        "bull" in str(regime_now).lower()))

    if rec == "EXIT":
        # Reversal conditions — what would cancel the exit stance.
        reversal = [
            _cond("Final confidence", f"{fc:.0f}", f"{WATCH_CONF:.0f}",
                  "above",
                  "The bearish exit signal is cancelled if confidence "
                  "recovers above the WATCH floor with filters passing.",
                  fc >= WATCH_CONF),
        ]
        if ema20 > 0:
            reversal.append(_cond(
                "Price vs EMA20", f"₹{price:.2f}", f"₹{ema20:.2f}", "above",
                "Reclaiming the short-term trend level would argue against "
                "exiting.", above20))
        reversal.append(_cond(
            "MACD histogram", f"{macd_h:+.2f}", "0", "above",
            "Recovering momentum weakens the case for the exit.",
            macd_h > 0))
        if target > 0:
            reversal.append(_cond(
                "Price vs target", f"₹{price:.2f}", f"₹{target:.2f}",
                "above",
                "Reaching the target resolves the position by plan rather "
                "than by invalidation.", price >= target))
        upgrade = reversal

    return invalidation, upgrade


# ── Decision state + expiry ───────────────────────────────────────────────────

def decision_state(decision: dict, invalidation: list[dict],
                   upgrade: list[dict], now: datetime,
                   valid_until: datetime | None) -> tuple[str, int, int]:
    """Deterministic monitoring state. Returns (state, inv_met, up_met)."""
    rec = str(decision.get("recommendation", ""))
    inv_met = sum(1 for c in invalidation if c["met"])
    up_met = sum(1 for c in upgrade if c["met"])

    if str(decision.get("data_status", "")) != "OK":
        return "DATA_LIMITED", inv_met, up_met
    if valid_until is not None and now >= valid_until:
        return "EXPIRED", inv_met, up_met

    if rec in ("STRONG_BUY", "BUY"):
        stop_hit = any(c["metric"] == "Price vs stop-loss" and c["met"]
                       for c in invalidation)
        if stop_hit or inv_met >= 3:
            return "INVALIDATED", inv_met, up_met
        if inv_met >= 1:
            return "WEAKENING", inv_met, up_met
        return "VALID", inv_met, up_met

    if rec in ("WATCH", "AVOID"):
        # Majority of upgrade triggers already met => setup is improving.
        if upgrade and up_met >= max(3, (len(upgrade) + 1) // 2):
            return "IMPROVING", inv_met, up_met
        return "VALID", inv_met, up_met

    if rec == "EXIT":
        # Reversal conditions mostly met => the exit case is weakening.
        if upgrade and up_met >= max(2, (len(upgrade) + 1) // 2):
            return "IMPROVING", inv_met, up_met
        return "VALID", inv_met, up_met

    return "VALID", inv_met, up_met


# ── Conflict detection ────────────────────────────────────────────────────────

_SEV_ORDER = {"NONE": 0, "LOW": 1, "MEDIUM": 2, "HIGH": 3}


def detect_conflicts(decision: dict, item: dict) -> tuple[str, str]:
    """Deterministic conflict rules. Returns (level, explanation)."""
    tech = ((decision.get("explanation_sections") or {}).get("technical")
            or {})
    sim = ((decision.get("explanation_sections") or {}).get("similarity")
           or {})
    pattern = (decision.get("explanation_sections") or {}).get("pattern")
    base = _f(tech.get("technical_score"))
    filters_ok = bool(tech.get("risk_filters_passed"))
    sim_n = int(sim.get("match_count", 0) or 0)
    sim_exp = _f(sim.get("expectancy"))
    reliability = str(decision.get("evidence_reliability", "") or "VERY_LOW")
    fc = _f(decision.get("final_confidence"))
    rr = _f(decision.get("rr_ratio"))
    low_rel = bool(decision.get("low_reliability"))
    data_ok = str(decision.get("data_status", "")) == "OK"
    sector_rank = item.get("sector_rank")

    conflicts: list[tuple[str, str]] = []

    # 1. Technical positive but similarity evidence negative
    if base >= WATCH_CONF and filters_ok and sim_n >= 10 and sim_exp < 0:
        sev = "HIGH" if reliability in ("HIGH", "MEDIUM") else "MEDIUM"
        conflicts.append((sev,
            f"Technical conditions are constructive (technical confidence "
            f"{base:.0f}, filters passed), but {sim_n} similar historical "
            f"setups had negative expectancy ({sim_exp:+.2f}%)."))

    # 2. Pattern knowledge positive but live technicals weak
    if pattern and _f(pattern.get("expectancy")) > 0 and (
            base < 45.0 or not filters_ok):
        sev = ("MEDIUM" if (_f(pattern.get("profit_factor")) >= 1.2 and
                            int(pattern.get("sample_size", 0) or 0) >= 20)
               else "LOW")
        conflicts.append((sev,
            f"Descriptive Pattern Knowledge is positive (expectancy "
            f"{_f(pattern.get('expectancy')):+.2f}%), but live technical "
            f"conditions are weak (technical confidence {base:.0f}"
            + ("" if filters_ok else ", risk filters failed") + ")."))

    # 3. Strong confidence but low data quality / thin history
    if fc >= BUY_CONF and (not data_ok or low_rel):
        conflicts.append(("HIGH" if not data_ok else "MEDIUM",
            f"Confidence is high ({fc:.0f}) but "
            + ("live data is unavailable"
               if not data_ok else "the historical sample is thin")
            + ", so the confidence rests on limited evidence."))

    # 4. High expectancy but poor risk/reward
    if sim_n >= 10 and sim_exp > 1.0 and 0 < rr < MIN_RR:
        conflicts.append(("MEDIUM",
            f"Similar trades show strong expectancy ({sim_exp:+.2f}%) but "
            f"the current risk/reward is only {rr:.1f}:1 — below the "
            f"{MIN_RR:.0f}:1 minimum."))

    # 5. Good individual setup but weak sector
    if base >= WATCH_CONF and filters_ok and sector_rank is not None \
            and int(sector_rank) > SECTOR_RANK_MAX:
        conflicts.append(("LOW",
            f"The individual setup is constructive, but its sector ranks "
            f"{int(sector_rank)} — outside the top {SECTOR_RANK_MAX}."))

    if not conflicts:
        return "NONE", ""
    conflicts.sort(key=lambda c: -_SEV_ORDER[c[0]])
    level = conflicts[0][0]
    explanation = " ".join(
        f"{sev} conflict: {txt}" for sev, txt in conflicts)
    return level, explanation


# ── Analyst summary (<= 120 words, fixed format) ─────────────────────────────

def _first_sentence(text: str) -> str:
    text = text.strip()
    idx = text.find(". ")
    return (text[:idx + 1] if idx > 0 else text).strip()


def build_analyst_summary(decision: dict, historical_assessment: str,
                          conflict_level: str, conflict_explanation: str,
                          invalidation: list[dict], upgrade: list[dict]) -> str:
    rec = str(decision.get("recommendation", "")).replace("_", " ")
    fc = _f(decision.get("final_confidence"))
    reason = str(decision.get("reason", "") or "").rstrip(".")

    hist = _first_sentence(historical_assessment)

    if conflict_level not in ("NONE", ""):
        risk = _first_sentence(conflict_explanation.split("conflict: ", 1)[-1])
    elif str(decision.get("data_status", "")) != "OK":
        risk = "Live NSE data is unavailable, so this assessment is provisional."
    else:
        # Most relevant unmet-to-met downside trigger: first invalidation
        # condition not yet met (the next thing that could go wrong).
        pending = next((c for c in invalidation if not c["met"]), None)
        risk = (f"{pending['metric']} moving {pending['direction']} "
                f"{pending['trigger_value']} (now {pending['current_value']})."
                if pending else "No single dominant risk trigger identified.")

    rec_is_buy = decision.get("recommendation") in ("STRONG_BUY", "BUY")
    change_list = invalidation if rec_is_buy else upgrade
    pending_change = [c for c in change_list if not c["met"]][:2]
    if pending_change:
        change = "; ".join(
            f"{c['metric']} {c['direction']} {c['trigger_value']}"
            for c in pending_change)
        change = ("Invalidated if " if rec_is_buy else "Upgraded if ") + change + "."
    else:
        change = ("Multiple change conditions are already met — "
                  "re-evaluation at the next daily close.")

    summary = (f"Recommendation: {rec}. "
               f"Confidence: {fc:.0f}%. "
               f"Primary reason: {reason}. "
               f"Historical evidence: {hist} "
               f"Main risk: {risk} "
               f"What would change the decision: {change}")
    # Hard cap at 120 words (deterministic truncation on word boundary).
    words = summary.split()
    if len(words) > 120:
        summary = " ".join(words[:120]).rstrip(",;") + "."
    return summary


# ── Missing data fields (DATA_LIMITED transparency) ──────────────────────────

def missing_data_fields(decision: dict, item: dict) -> list[str]:
    if str(decision.get("data_status", "")) == "OK":
        return []
    missing = ["live price", "live volume", "live technical indicators"]
    err = item.get("error")
    if err:
        missing.append(f"fetch error: {err}")
    return missing


# ── Top-level builder ─────────────────────────────────────────────────────────

def build_analyst_view(decision: dict, item: dict, regime_now: str,
                       now: datetime | None = None) -> dict:
    """Assemble the complete v2.3 analyst layer for one decision.
    Pure and deterministic given its inputs (uses `now` if provided)."""
    now_ist = _now_ist(now)
    data_ok = str(decision.get("data_status", "")) == "OK"
    rec = str(decision.get("recommendation", ""))

    invalidation, upgrade = build_conditions(decision, item, regime_now)

    # Validity window
    if rec == "EXIT":
        valid_until_dt = None
        validity_note = "Valid until the position is closed or superseded"
    elif not data_ok:
        valid_until_dt = None
        validity_note = "Re-evaluation required"
    else:
        valid_until_dt = next_daily_close(now_ist)
        validity_note = "Valid until next daily close"

    state, inv_met, up_met = decision_state(
        decision, invalidation, upgrade, now_ist, valid_until_dt)

    conflict_level, conflict_explanation = detect_conflicts(decision, item)

    current_observation = build_current_observation(decision, item, regime_now)
    historical_assessment = build_historical_assessment(decision)
    decision_reasoning = build_decision_reasoning(decision)
    analyst_summary = build_analyst_summary(
        decision, historical_assessment, conflict_level,
        conflict_explanation, invalidation, upgrade)

    return {
        "analyst_summary": analyst_summary,
        "current_observation": current_observation,
        "historical_assessment": historical_assessment,
        "decision_reasoning": decision_reasoning,
        "invalidation_conditions": invalidation,
        "upgrade_conditions": upgrade,
        "invalidation_met": inv_met,
        "upgrade_met": up_met,
        "decision_state": state,
        "decision_timestamp": now_ist.isoformat(timespec="seconds"),
        "valid_until": (valid_until_dt.isoformat(timespec="seconds")
                        if valid_until_dt else None),
        "validity_note": validity_note,
        "conflict_level": conflict_level,
        "conflict_explanation": conflict_explanation,
        "missing_data_fields": missing_data_fields(decision, item),
    }
