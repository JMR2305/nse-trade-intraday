"""
Adaptive Learning Layer — Sprint 3 Module 3.

Uses the Historical Knowledge Base (historical_knowledge_trades) to improve
Market Scanner decisions. STRICT SAFETY RULES:

  - NEVER changes strategy logic, entry rules, or exit rules.
  - ONLY adjusts: confidence, opportunity score, ranking, explanation.
  - Every adjustment is deterministic, rule-based and explainable.
  - No black-box AI / ML — plain arithmetic over historical stats.

PAPER TRADING ONLY — research and ranking assistance, never places orders.
"""

from __future__ import annotations

import sqlite3

from trade_intelligence import DB_PATH
from predictive_intelligence import (
    rsi_bucket, adx_bucket, volume_bucket, rr_bucket, ema_alignment,
)
from expectancy import (
    compute_metrics, expectancy_score, profit_factor_score, risk_score,
)

# ── Tunables (deterministic rule constants, per spec) ─────────────────────────

MIN_TRADES          = 30      # below this: no adjustment, "Low historical confidence"
# Sprint 4: expectancy-based learning (replaces win-rate thresholds)
BOOST_EXPECTANCY    = 0.5     # % expectancy per trade needed for a boost
BOOST_PROFIT_FACTOR = 1.3
CUT_EXPECTANCY      = -0.2    # % expectancy per trade below which we cut
BOOST_MIN, BOOST_MAX = 5.0, 15.0
CUT_MIN, CUT_MAX     = 5.0, 20.0
CONF_FLOOR, CONF_CAP = 5.0, 95.0

# Similar-trade search is HIERARCHICAL and deterministic. The strategy must
# always match exactly. Then three tiers, strictest first:
#   Tier 1: sector + regime exact, >=2 of 5 technical bands match
#   Tier 2: regime exact,          >=3 of 5 technical bands match
#   Tier 3: >=4 of all 7 context dimensions match
# The first tier that yields >= MIN_TRADES similar trades is used (so the
# explanation text is always truthful about what was matched). When no tier
# reaches MIN_TRADES the largest set is used (adjustment stays 0).
TECH_DIMS = ("rsi_band", "adx_band", "ema_align", "volume_band", "rr_band")
ALL_DIMS  = ("sector", "regime") + TECH_DIMS
TIER3_MIN = 4

# Regime strength (0-100) for the opportunity blend — same 7-way taxonomy
# as the Historical Knowledge builder.
REGIME_STRENGTH = {
    "Strong Bullish":  90.0,
    "Bullish":         75.0,
    "Low Volatility":  60.0,
    "Neutral":         50.0,
    "High Volatility": 35.0,
    "Bearish":         25.0,
    "Strong Bearish":  10.0,
}


def holding_bucket(days) -> str:
    if days is None:
        return "unknown"
    if days <= 3:
        return "short"
    if days <= 10:
        return "medium"
    return "long"


# ── Knowledge base loading ────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='historical_knowledge_trades'"
    ).fetchone()
    return row is not None


def load_knowledge() -> list[dict]:
    """Load all historical knowledge trades with precomputed match bands."""
    conn = _connect()
    try:
        if not _table_exists(conn):
            return []
        rows = conn.execute(
            """SELECT symbol, sector, strategy, entry_date, exit_date, holding_days,
                      return_percent, winning, market_regime, rsi, adx,
                      ema9, ema20, ema50, volume_ratio, risk_reward
               FROM historical_knowledge_trades"""
        ).fetchall()
    finally:
        conn.close()

    out = []
    for r in rows:
        d = dict(r)
        d["rsi_band"]    = rsi_bucket(d.get("rsi"))
        d["adx_band"]    = adx_bucket(d.get("adx"))
        d["ema_align"]   = ema_alignment(d.get("ema9"), d.get("ema20"), d.get("ema50"))
        d["volume_band"] = volume_bucket(d.get("volume_ratio"))
        d["rr_band"]     = rr_bucket(d.get("risk_reward"))
        d["hold_band"]   = holding_bucket(d.get("holding_days"))
        d["regime"]      = d.get("market_regime") or ""
        d["strategy"]    = str(d.get("strategy") or "").strip().lower()
        d["sector"]      = str(d.get("sector") or "").upper()
        out.append(d)
    return out


# ── Similar pattern search ────────────────────────────────────────────────────

def candidate_features(strategy_id: str, sector: str, regime: str,
                       rsi, adx, ema_align: str, volume_ratio, rr) -> dict:
    return {
        "strategy":    str(strategy_id or "").strip().lower(),
        "sector":      str(sector or "").upper(),
        "regime":      regime or "",
        "rsi_band":    rsi_bucket(rsi),
        "adx_band":    adx_bucket(adx),
        "ema_align":   ema_align or "unknown",
        "volume_band": volume_bucket(volume_ratio),
        "rr_band":     rr_bucket(rr),
    }


def _dim_matches(cand: dict, h: dict, dims: tuple[str, ...]) -> int:
    matches = 0
    for dim in dims:
        c, hv = cand.get(dim), h.get(dim)
        if c and hv and c not in ("", "unknown") and c == hv:
            matches += 1
    return matches


def _dims_equal(cand: dict, h: dict, dims: tuple[str, ...]) -> bool:
    for dim in dims:
        c, hv = cand.get(dim), h.get(dim)
        if not c or not hv or c in ("", "unknown") or c != hv:
            return False
    return True


def find_similar(cand: dict, knowledge: list[dict]) -> tuple[list[dict], str]:
    """
    Hierarchical deterministic similar-trade search (see tier docs above).
    Returns (similar_trades, match_context) where match_context describes
    what was matched — used verbatim in the explanation string.
    """
    if not cand["strategy"]:
        return [], "no strategy"
    pool = [h for h in knowledge if h["strategy"] == cand["strategy"]]

    tier1 = [h for h in pool
             if _dims_equal(cand, h, ("sector", "regime"))
             and _dim_matches(cand, h, TECH_DIMS) >= 2]
    ctx1 = f"in {cand['sector']} during {cand['regime']} markets"
    if len(tier1) >= MIN_TRADES:
        return tier1, ctx1

    tier2 = [h for h in pool
             if _dims_equal(cand, h, ("regime",))
             and _dim_matches(cand, h, TECH_DIMS) >= 3]
    ctx2 = f"during {cand['regime']} markets (all sectors)"
    if len(tier2) >= MIN_TRADES:
        return tier2, ctx2

    tier3 = [h for h in pool if _dim_matches(cand, h, ALL_DIMS) >= TIER3_MIN]
    ctx3 = "across all market conditions"
    if len(tier3) >= MIN_TRADES:
        return tier3, ctx3

    # No tier reached MIN_TRADES: use the largest set (stricter tier wins ties)
    best = max(((tier1, ctx1), (tier2, ctx2), (tier3, ctx3)), key=lambda t: len(t[0]))
    return best


def pattern_stats(trades: list[dict]) -> dict:
    """Full expectancy-engine metrics for a group of trades (Sprint 4)."""
    return compute_metrics(trades)


# ── Confidence adjustment (spec §2) ──────────────────────────────────────────

def confidence_adjustment(stats: dict) -> tuple[float, str]:
    """
    Returns (adjustment, note). Deterministic, EXPECTANCY-based (Sprint 4):
      >=30 trades, expectancy >= +0.5%, PF > 1.3 → +5..+15 (scaled by expectancy)
      >=30 trades, expectancy <= -0.2%           → -5..-20 (scaled by expectancy)
      <30 trades                                 → 0, "Low historical confidence"
      otherwise                                  → 0, "Mixed historical evidence"
    """
    n, exp, pf = stats["trades"], stats["expectancy"], stats["profit_factor"]
    if n < MIN_TRADES:
        return 0.0, "Low historical confidence"
    if exp >= BOOST_EXPECTANCY and pf > BOOST_PROFIT_FACTOR:
        extra = (exp - BOOST_EXPECTANCY) * 5.0 + (min(pf, 4.0) - BOOST_PROFIT_FACTOR) * 2.0
        return round(min(BOOST_MAX, BOOST_MIN + extra), 1), ""
    if exp <= CUT_EXPECTANCY:
        extra = (CUT_EXPECTANCY - exp) * 7.0 + (1.0 - min(pf, 1.0)) * 5.0
        return round(-min(CUT_MAX, CUT_MIN + extra), 1), ""
    return 0.0, "Mixed historical evidence"


def clamp_confidence(v: float) -> float:
    return round(max(CONF_FLOOR, min(CONF_CAP, v)), 1)


# ── Historical scores + opportunity blend (Sprint 4: 40/30/15/10/5) ──────────

def historical_component_scores(stats: dict) -> tuple[float, float, float]:
    """(expectancy_score, pf_score, risk_score), all 0-100. Neutral 50 when thin."""
    if stats["trades"] < MIN_TRADES:
        return 50.0, 50.0, 50.0
    return (
        expectancy_score(stats["expectancy"]),
        profit_factor_score(stats["profit_factor"]),
        risk_score(stats["max_drawdown"]),
    )


def blended_opportunity(technical: float, exp_score: float, pf_score: float,
                        rsk_score: float, sector_strength: float) -> dict:
    """
    Sprint 4 scanner ranking blend:
      40% Technical + 30% Historical Expectancy + 15% Profit Factor
      + 10% Risk + 5% Sector Strength — with a visible breakdown.
    """
    contrib_t  = technical * 0.40
    contrib_e  = exp_score * 0.30
    contrib_pf = pf_score * 0.15
    contrib_rk = rsk_score * 0.10
    contrib_s  = sector_strength * 0.05
    score = round(max(0.0, min(100.0,
        contrib_t + contrib_e + contrib_pf + contrib_rk + contrib_s)), 1)
    return {
        "score": score,
        "technical_score": round(technical, 1),
        "expectancy_score": round(exp_score, 1),
        "pf_score": round(pf_score, 1),
        "risk_score": round(rsk_score, 1),
        "sector_strength_score": round(sector_strength, 1),
        "technical_contribution": round(contrib_t, 1),
        "expectancy_contribution": round(contrib_e, 1),
        "pf_contribution": round(contrib_pf, 1),
        "risk_contribution": round(contrib_rk, 1),
        "sector_contribution": round(contrib_s, 1),
    }


# ── Explainability (spec §6) ──────────────────────────────────────────────────

def build_explanation(strategy_name: str, match_context: str,
                      stats: dict, adjustment: float, note: str) -> str:
    n, exp = stats["trades"], stats["expectancy"]
    rating = stats.get("expectancy_rating", "Neutral")
    where = f"{strategy_name} setups {match_context}"
    if note == "Low historical confidence":
        return (f"No adjustment — only {n} similar historical trades found for "
                f"{where} (need {MIN_TRADES}+). Low historical confidence.")
    if adjustment > 0:
        return (f"Confidence increased because similar {where} earned "
                f"{exp:+.2f}% expectancy per trade over {n} historical trades "
                f"({rating}; profit factor {stats['profit_factor']:.2f}, "
                f"win rate {stats['win_rate']:.0f}%).")
    if adjustment < 0:
        return (f"Confidence reduced because similar {where} had "
                f"{exp:+.2f}% expectancy per trade over {n} historical trades "
                f"({rating}; profit factor {stats['profit_factor']:.2f}, "
                f"average loser -{stats['avg_loss']:.2f}%).")
    return (f"No adjustment — similar {where} showed {exp:+.2f}% expectancy "
            f"per trade over {n} trades ({rating}). Mixed historical evidence.")


# ── Current market regime (same taxonomy as the knowledge base) ──────────────

def current_market_regime() -> str:
    """Classify today's regime with the SAME 7-way labels as the KB builder."""
    try:
        from historical_knowledge_builder import MarketContext
        from datetime import datetime
        ctx = MarketContext("6mo")
        return ctx.context_for(datetime.now().isoformat())["market_regime"]
    except Exception:
        return "Neutral"


def regime_strength_of(regime: str) -> float:
    return REGIME_STRENGTH.get(regime, 50.0)


# ── Scanner annotation (called by market_scanner) ─────────────────────────────

def annotate_scan_items(items: list[dict], strategy_names: dict[str, str] | None = None) -> dict:
    """
    Enrich scanner items IN PLACE with learning fields and return meta info.
    Only touches confidence / opportunity / ranking / explanation fields —
    never actions, entries, exits, or strategy choices.
    """
    knowledge = load_knowledge()
    regime = current_market_regime()
    regime_strength = regime_strength_of(regime)

    # Sector strength (0-100) from the PRE-learning technical opportunity scores.
    by_sector: dict[str, list[float]] = {}
    for it in items:
        if it.get("error") is None:
            by_sector.setdefault(it.get("sector", "OTHER"), []).append(
                float(it.get("opportunity_score", 0.0)))
    sector_strength = {
        s: round(sum(v) / len(v), 1) for s, v in by_sector.items() if v
    }

    for it in items:
        base_conf = float(it.get("confidence", 0.0))
        it["base_confidence"] = round(base_conf, 1)

        if it.get("error") is not None or not it.get("best_strategy_id"):
            it.update({
                "historical_trades": 0, "historical_win_rate": 0.0,
                "historical_profit_factor": 0.0, "historical_avg_return": 0.0,
                "historical_expectancy": 0.0, "historical_expectancy_rating": "Neutral",
                "historical_kelly": 0.0, "historical_avg_win": 0.0,
                "historical_avg_loss": 0.0, "expected_drawdown": 0.0,
                "expected_holding_days": 0.0, "historical_sharpe": 0.0,
                "learning_adjustment": 0.0,
                "final_confidence": clamp_confidence(base_conf),
                "learning_note": "Low historical confidence",
                "learning_explanation": "No learning applied — stock could not be scanned.",
                "opportunity_breakdown": blended_opportunity(
                    float(it.get("opportunity_score", 0.0)), 50.0, 50.0, 50.0,
                    sector_strength.get(it.get("sector", ""), 0.0)),
            })
            continue

        ema_al = ("bullish" if (it.get("above_ema20") and it.get("above_ema50"))
                  else "bearish" if (not it.get("above_ema20") and not it.get("above_ema50"))
                  else "mixed")
        cand = candidate_features(
            it.get("best_strategy_id", ""), it.get("sector", ""), regime,
            it.get("rsi"), it.get("adx"), ema_al,
            it.get("volume_ratio"), it.get("rr_ratio"),
        )
        similar, match_context = find_similar(cand, knowledge)
        stats = pattern_stats(similar)
        adj, note = confidence_adjustment(stats)
        final_conf = clamp_confidence(base_conf + adj)

        technical = float(it.get("opportunity_score", 0.0))
        exp_sc, pf_sc, rsk_sc = historical_component_scores(stats)
        breakdown = blended_opportunity(
            technical, exp_sc, pf_sc, rsk_sc,
            sector_strength.get(it.get("sector", ""), 0.0),
        )

        strategy_name = it.get("best_strategy_name") or it.get("best_strategy_id", "")
        it.update({
            "historical_trades": stats["trades"],
            "historical_win_rate": stats["win_rate"],
            "historical_profit_factor": stats["profit_factor"],
            "historical_avg_return": stats["average_return"],
            "historical_expectancy": stats["expectancy"],
            "historical_expectancy_rating": stats["expectancy_rating"],
            "historical_kelly": stats["kelly_percent"],
            "historical_avg_win": stats["avg_win"],
            "historical_avg_loss": stats["avg_loss"],
            "expected_drawdown": stats["max_drawdown"],
            "expected_holding_days": stats["avg_holding_days"],
            "historical_sharpe": stats["sharpe"],
            "learning_adjustment": adj,
            "final_confidence": final_conf,
            "learning_note": note,
            "learning_explanation": build_explanation(
                strategy_name, match_context, stats, adj, note),
            "opportunity_breakdown": breakdown,
        })
        # Opportunity Score upgrade: replace with the Sprint 4 blended score.
        it["opportunity_score"] = breakdown["score"]

    return {
        "market_regime": regime,
        "regime_strength": regime_strength,
        "knowledge_trades": len(knowledge),
        "sector_strength": sector_strength,
    }


# ── Learning Insights dashboard (spec §7) ─────────────────────────────────────

_MIN_PATTERN_TRADES = 10      # patterns need this many trades to be listed
_MIN_RELIABLE_TRADES = 30     # "reliable" claims need >=30 trades


def _pattern_rows(knowledge: list[dict], keys: tuple[str, ...]) -> list[dict]:
    groups: dict[tuple, list[dict]] = {}
    for t in knowledge:
        k = tuple(t.get(key) or "" for key in keys)
        if any(v in ("", "unknown") for v in k):
            continue
        groups.setdefault(k, []).append(t)
    rows = []
    for k, trades in groups.items():
        s = pattern_stats(trades)
        if s["trades"] < _MIN_PATTERN_TRADES:
            continue
        rows.append({**{key: k[i] for i, key in enumerate(keys)}, **s})
    return rows


def _heatmap(knowledge: list[dict], row_key: str, col_key: str) -> dict:
    groups: dict[tuple, list[dict]] = {}
    row_vals, col_vals = set(), set()
    for t in knowledge:
        r, c = t.get(row_key) or "", t.get(col_key) or ""
        if r in ("", "unknown") or c in ("", "unknown"):
            continue
        row_vals.add(r)
        col_vals.add(c)
        groups.setdefault((r, c), []).append(t)
    cells = []
    for (r, c), trades in groups.items():
        s = pattern_stats(trades)
        cells.append({"row": r, "col": c, "trades": s["trades"],
                      "win_rate": s["win_rate"], "average_return": s["average_return"]})
    return {
        "rows": sorted(row_vals),
        "cols": sorted(col_vals),
        "cells": cells,
    }


def learning_insights() -> dict:
    """Deterministic aggregations over the Historical Knowledge Base."""
    knowledge = load_knowledge()
    if not knowledge:
        return {
            "knowledge_trades": 0,
            "warning": "Historical Knowledge Base is empty — build it first.",
            "top_patterns": [], "worst_patterns": [],
            "best_strategy_by_sector": [], "best_strategy_by_regime": [],
            "most_reliable_setups": [], "least_reliable_setups": [],
            "heatmaps": {},
        }

    # Patterns: strategy × sector × regime — RANKED BY EXPECTANCY (Sprint 4)
    patterns = _pattern_rows(knowledge, ("strategy", "sector", "regime"))
    by_exp = sorted(patterns,
                    key=lambda p: (p["expectancy"], p["profit_factor"], p["trades"]),
                    reverse=True)
    top_patterns = by_exp[:10]
    worst_patterns = sorted(patterns,
                            key=lambda p: (p["expectancy"], p["profit_factor"]))[:10]

    # Best strategy per sector / per regime — by expectancy
    def best_per(dim: str) -> list[dict]:
        rows = _pattern_rows(knowledge, (dim, "strategy"))
        best: dict[str, dict] = {}
        for r in rows:
            key = r[dim]
            cur = best.get(key)
            if cur is None or (r["expectancy"], r["profit_factor"]) > (cur["expectancy"], cur["profit_factor"]):
                best[key] = r
        return sorted(best.values(), key=lambda r: r["expectancy"], reverse=True)

    # Reliable setups: strategy × rsi_band × adx_band, >=30 trades — by expectancy
    setups = [s for s in _pattern_rows(knowledge, ("strategy", "rsi_band", "adx_band"))
              if s["trades"] >= _MIN_RELIABLE_TRADES]
    setups_sorted = sorted(setups, key=lambda s: (s["expectancy"], s["profit_factor"]),
                           reverse=True)

    # ── Sprint 4 expectancy sections ──────────────────────────────────────────
    top_expectancy = by_exp[:20]
    lowest_expectancy = sorted(patterns,
                               key=lambda p: (p["expectancy"], p["profit_factor"]))[:20]
    highest_sharpe = sorted(patterns, key=lambda p: (p["sharpe"], p["trades"]),
                            reverse=True)[:10]
    highest_kelly = sorted(patterns, key=lambda p: (p["kelly_percent"], p["trades"]),
                           reverse=True)[:10]
    largest_drawdown = sorted(patterns, key=lambda p: (p["max_drawdown"], p["trades"]),
                              reverse=True)[:10]

    # Per-strategy aggregate metrics (all trades of a strategy)
    strat_rows = _pattern_rows(knowledge, ("strategy",))
    best_risk_adjusted = sorted(strat_rows, key=lambda s: (s["sharpe"], s["expectancy"]),
                                reverse=True)

    # Long-term (>10 day holds) vs swing (4-10 day holds) strategy leaders
    def strat_rows_for_band(band: str) -> list[dict]:
        subset = [t for t in knowledge if t.get("hold_band") == band]
        rows = _pattern_rows(subset, ("strategy",))
        return sorted(rows, key=lambda s: (s["expectancy"], s["profit_factor"]),
                      reverse=True)

    best_long_term = strat_rows_for_band("long")
    best_swing = strat_rows_for_band("medium")

    return {
        "knowledge_trades": len(knowledge),
        "warning": ("Deterministic aggregation of simulated historical trades. "
                    "Research only — not investment advice."),
        "top_patterns": top_patterns,
        "worst_patterns": worst_patterns,
        "best_strategy_by_sector": best_per("sector"),
        "best_strategy_by_regime": best_per("regime"),
        "most_reliable_setups": setups_sorted[:10],
        "least_reliable_setups": list(reversed(setups_sorted[-10:])) if setups_sorted else [],
        "top_expectancy_patterns": top_expectancy,
        "lowest_expectancy_patterns": lowest_expectancy,
        "highest_sharpe_patterns": highest_sharpe,
        "highest_kelly_patterns": highest_kelly,
        "largest_drawdown_patterns": largest_drawdown,
        "best_risk_adjusted_strategies": best_risk_adjusted,
        "best_long_term_strategies": best_long_term,
        "best_swing_strategies": best_swing,
        "heatmaps": {
            "sector_strategy": _heatmap(knowledge, "sector", "strategy"),
            "regime_strategy": _heatmap(knowledge, "regime", "strategy"),
            "rsi_strategy":    _heatmap(knowledge, "rsi_band", "strategy"),
            "adx_strategy":    _heatmap(knowledge, "adx_band", "strategy"),
        },
    }


# ── Pattern Quality dashboard (Sprint 4) ─────────────────────────────────────

def pattern_quality() -> dict:
    """
    All strategy × sector × regime patterns with the full expectancy metric
    set, ranked by expectancy (rank 1 = highest expectancy).
    """
    knowledge = load_knowledge()
    if not knowledge:
        return {"knowledge_trades": 0, "patterns": [],
                "warning": "Historical Knowledge Base is empty — build it first."}
    rows = _pattern_rows(knowledge, ("strategy", "sector", "regime"))
    rows.sort(key=lambda p: (p["expectancy"], p["profit_factor"], p["trades"]),
              reverse=True)
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    return {
        "knowledge_trades": len(knowledge),
        "patterns": rows,
        "warning": ("Deterministic aggregation of simulated historical trades. "
                    "Research only — not investment advice."),
    }
