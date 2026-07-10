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

# ── Tunables (deterministic rule constants, per spec) ─────────────────────────

MIN_TRADES          = 30      # below this: no adjustment, "Low historical confidence"
BOOST_WIN_RATE      = 60.0    # win rate needed for a confidence boost
BOOST_PROFIT_FACTOR = 1.5
CUT_WIN_RATE        = 45.0    # win rate below which confidence is reduced
CUT_PROFIT_FACTOR   = 1.0
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
    """Wins / losses / win rate / avg return / profit factor / expectancy."""
    n = len(trades)
    if n == 0:
        return {"trades": 0, "wins": 0, "losses": 0, "win_rate": 0.0,
                "average_return": 0.0, "profit_factor": 0.0, "expectancy": 0.0}
    rets   = [float(t.get("return_percent") or 0.0) for t in trades]
    wins   = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    gross_win  = sum(wins)
    gross_loss = abs(sum(losses))
    wr = len(wins) / n * 100.0
    pf = round(gross_win / gross_loss, 2) if gross_loss > 0 else (999.0 if gross_win > 0 else 0.0)
    avg_win  = (gross_win / len(wins)) if wins else 0.0
    avg_loss = (sum(losses) / len(losses)) if losses else 0.0
    expectancy = (wr / 100.0) * avg_win + (1 - wr / 100.0) * avg_loss
    return {
        "trades": n,
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(wr, 1),
        "average_return": round(sum(rets) / n, 2),
        "profit_factor": min(pf, 999.0),
        "expectancy": round(expectancy, 2),
    }


# ── Confidence adjustment (spec §2) ──────────────────────────────────────────

def confidence_adjustment(stats: dict) -> tuple[float, str]:
    """
    Returns (adjustment, note). Deterministic per spec:
      >=30 trades, WR>60, PF>1.5  → +5..+15 (scaled by how far above thresholds)
      >=30 trades, WR<45, PF<1    → -5..-20
      <30 trades                  → 0, "Low historical confidence"
    """
    n, wr, pf = stats["trades"], stats["win_rate"], stats["profit_factor"]
    if n < MIN_TRADES:
        return 0.0, "Low historical confidence"
    if wr > BOOST_WIN_RATE and pf > BOOST_PROFIT_FACTOR:
        extra = (wr - BOOST_WIN_RATE) * 0.4 + (min(pf, 4.0) - BOOST_PROFIT_FACTOR) * 2.0
        return round(min(BOOST_MAX, BOOST_MIN + extra), 1), ""
    if wr < CUT_WIN_RATE and pf < CUT_PROFIT_FACTOR:
        extra = (CUT_WIN_RATE - wr) * 0.5 + (CUT_PROFIT_FACTOR - max(pf, 0.0)) * 5.0
        return round(-min(CUT_MAX, CUT_MIN + extra), 1), ""
    return 0.0, "Mixed historical evidence"


def clamp_confidence(v: float) -> float:
    return round(max(CONF_FLOOR, min(CONF_CAP, v)), 1)


# ── Historical success + opportunity blend (spec §3) ─────────────────────────

def historical_success_score(stats: dict) -> float:
    """0-100 from win rate (60%) and profit factor (40%); neutral 50 when thin."""
    if stats["trades"] < MIN_TRADES:
        return 50.0
    pf_score = min(stats["profit_factor"], 3.0) / 3.0 * 100.0
    return round(min(100.0, max(0.0, stats["win_rate"] * 0.6 + pf_score * 0.4)), 1)


def blended_opportunity(technical: float, historical: float,
                        sector_strength: float, regime_strength: float) -> dict:
    """40% technical + 30% historical + 20% sector + 10% regime, with breakdown."""
    contrib_t = technical * 0.40
    contrib_h = historical * 0.30
    contrib_s = sector_strength * 0.20
    contrib_r = regime_strength * 0.10
    score = round(max(0.0, min(100.0, contrib_t + contrib_h + contrib_s + contrib_r)), 1)
    return {
        "score": score,
        "technical_score": round(technical, 1),
        "historical_score": round(historical, 1),
        "sector_strength_score": round(sector_strength, 1),
        "regime_strength_score": round(regime_strength, 1),
        "technical_contribution": round(contrib_t, 1),
        "historical_contribution": round(contrib_h, 1),
        "sector_contribution": round(contrib_s, 1),
        "regime_contribution": round(contrib_r, 1),
    }


# ── Explainability (spec §6) ──────────────────────────────────────────────────

def build_explanation(strategy_name: str, match_context: str,
                      stats: dict, adjustment: float, note: str) -> str:
    n, wr = stats["trades"], stats["win_rate"]
    where = f"{strategy_name} setups {match_context}"
    if note == "Low historical confidence":
        return (f"No adjustment — only {n} similar historical trades found for "
                f"{where} (need {MIN_TRADES}+). Low historical confidence.")
    if adjustment > 0:
        return (f"Confidence increased because similar {where} achieved a "
                f"{wr:.0f}% win rate over {n} historical trades "
                f"(profit factor {stats['profit_factor']:.2f}).")
    if adjustment < 0:
        return (f"Confidence reduced because similar {where} lost money in "
                f"{100 - wr:.0f}% of {n} historical trades "
                f"(profit factor {stats['profit_factor']:.2f}).")
    return (f"No adjustment — similar {where} showed mixed results "
            f"({wr:.0f}% win rate over {n} trades). Mixed historical evidence.")


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
                "historical_expectancy": 0.0, "learning_adjustment": 0.0,
                "final_confidence": clamp_confidence(base_conf),
                "learning_note": "Low historical confidence",
                "learning_explanation": "No learning applied — stock could not be scanned.",
                "opportunity_breakdown": blended_opportunity(
                    float(it.get("opportunity_score", 0.0)), 50.0,
                    sector_strength.get(it.get("sector", ""), 0.0), regime_strength),
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
        breakdown = blended_opportunity(
            technical,
            historical_success_score(stats),
            sector_strength.get(it.get("sector", ""), 0.0),
            regime_strength,
        )

        strategy_name = it.get("best_strategy_name") or it.get("best_strategy_id", "")
        it.update({
            "historical_trades": stats["trades"],
            "historical_win_rate": stats["win_rate"],
            "historical_profit_factor": stats["profit_factor"],
            "historical_avg_return": stats["average_return"],
            "historical_expectancy": stats["expectancy"],
            "learning_adjustment": adj,
            "final_confidence": final_conf,
            "learning_note": note,
            "learning_explanation": build_explanation(
                strategy_name, match_context, stats, adj, note),
            "opportunity_breakdown": breakdown,
        })
        # Opportunity Score upgrade (spec §3): replace with the blended score.
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

    # Patterns: strategy × sector × regime
    patterns = _pattern_rows(knowledge, ("strategy", "sector", "regime"))
    by_score = sorted(patterns, key=lambda p: (p["win_rate"], p["profit_factor"], p["trades"]),
                      reverse=True)
    top_patterns = by_score[:10]
    worst_patterns = list(reversed(by_score[-10:])) if len(by_score) > 10 else \
        sorted(patterns, key=lambda p: (p["win_rate"], p["profit_factor"]))[:10]

    # Best strategy per sector / per regime
    def best_per(dim: str) -> list[dict]:
        rows = _pattern_rows(knowledge, (dim, "strategy"))
        best: dict[str, dict] = {}
        for r in rows:
            key = r[dim]
            cur = best.get(key)
            if cur is None or (r["win_rate"], r["profit_factor"]) > (cur["win_rate"], cur["profit_factor"]):
                best[key] = r
        return sorted(best.values(), key=lambda r: r["win_rate"], reverse=True)

    # Reliable setups: strategy × rsi_band × adx_band, >=30 trades
    setups = [s for s in _pattern_rows(knowledge, ("strategy", "rsi_band", "adx_band"))
              if s["trades"] >= _MIN_RELIABLE_TRADES]
    setups_sorted = sorted(setups, key=lambda s: (s["win_rate"], s["profit_factor"]), reverse=True)

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
        "heatmaps": {
            "sector_strategy": _heatmap(knowledge, "sector", "strategy"),
            "regime_strategy": _heatmap(knowledge, "regime", "strategy"),
            "rsi_strategy":    _heatmap(knowledge, "rsi_band", "strategy"),
            "adx_strategy":    _heatmap(knowledge, "adx_band", "strategy"),
        },
    }
