"""
root_cause_engine.py — v2.2 Root Cause Intelligence.

Goes beyond "similar trades did badly": discovers WHY winning trades won and
WHY losing trades lost, and turns that into:

  1. Winner/loser factor prevalence over the similar-trade match set
     (which named market conditions were common among winners vs losers).
  2. A ranked factor table (predictive lift, shrunk by sample size).
  3. A Root Cause Analysis narrative for each stock, e.g.
       "82% of similar losing trades shared Weak volume and Weak ADX.
        The current setup has both characteristics.
        This reduced confidence by 6 points."
     The narrative EXPLAINS the existing bounded similarity adjustment —
     it never introduces a second adjustment (no double counting).
  4. Rolling global feature-importance statistics stored over time
     (feature_importance_snapshots) showing which indicators consistently
     predict success.
  5. Dynamic similarity weights (feature_weights) rebalanced gradually from
     evidence.

Safety rules (paper trading & research only):
  - Weights update ONLY after at least WEIGHT_UPDATE_MIN_NEW_TRADES (50) new
    completed trades since the last update.
  - Changes are gradual: new = 0.8*previous + 0.2*evidence target, and each
    feature's change is additionally capped at ±15% relative per update.
  - Weights always renormalize to exactly 100 — no single trade can
    significantly alter the model.
  - Deterministic and explainable: same inputs always produce the same
    outputs. No randomness, no mock data (rides the same eligibility rules
    as similarity_engine.load_historical_vectors).
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
from datetime import datetime

import similarity_engine as se

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trade_intelligence.db")

# ── Tunables (documented, deterministic) ──────────────────────────────────────
SHRINK_K                    = 20      # sample-size shrinkage constant for lift
LOSER_SHARED_MIN_PREVALENCE = 60.0    # % of losers sharing a factor to call it a root cause
LOSER_SHARED_MAX_LIFT       = -10.0   # factor must also be net-harmful (lift <= this)
WINNER_SHARED_MIN_PREVALENCE = 60.0
WINNER_SHARED_MIN_LIFT      = 10.0
MIN_SIDE_SAMPLES            = 5       # need >=5 winners AND >=5 losers for root cause
WEIGHT_UPDATE_MIN_NEW_TRADES = 50     # spec §9: >=50 new completed trades per update
WEIGHT_BLEND_PREV           = 0.8     # gradual: 80% previous weights
WEIGHT_BLEND_TARGET         = 0.2     # 20% evidence target
WEIGHT_MAX_REL_CHANGE       = 0.15    # extra per-feature cap: ±15% relative per update
IMPORTANCE_CONF_K           = 200.0   # confidence = n / (n + K)

SAFETY_MESSAGE = ("Feature importance is statistical evidence from paper "
                  "trades only. It adapts gradually, never from a single "
                  "trade, and never guarantees future results. Paper trading "
                  "and research only.")

FEATURE_LABELS = {
    "strategy":   "Strategy",
    "sector":     "Sector",
    "regime":     "Market regime",
    "vol_regime": "Volatility regime",
    "rsi":        "RSI",
    "adx":        "ADX trend strength",
    "macd_state": "MACD state",
    "ema_align":  "EMA alignment",
    "vwap_state": "VWAP position",
    "supertrend": "Supertrend position",
    "atr":        "ATR volatility",
    "volume":     "Volume confirmation",
    "momentum":   "Momentum direction",
}


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ── 1. Factor bucketing (deterministic, human-readable) ──────────────────────

def _rsi_factor(rsi) -> str | None:
    if rsi is None:
        return None
    if rsi < 40:
        return "Weak RSI (<40)"
    if rsi <= 60:
        return "Neutral RSI (40-60)"
    if rsi <= 70:
        return "Strong RSI (60-70)"
    return "Overbought RSI (>70)"


def _adx_factor(adx) -> str | None:
    if adx is None:
        return None
    if adx < 20:
        return "Weak ADX (<20)"
    if adx < 25:
        return "Moderate ADX (20-25)"
    if adx < 40:
        return "Strong ADX (25-40)"
    return "Very strong ADX (40+)"


def _volume_factor(vol_ratio) -> str | None:
    if vol_ratio is None:
        return None
    if vol_ratio < 0.8:
        return "Weak volume (<0.8x avg)"
    if vol_ratio <= 1.5:
        return "Normal volume (0.8-1.5x)"
    return "Volume confirmation (>1.5x)"


def _vol_factor(vol_regime) -> str | None:
    if not vol_regime:
        return None
    return {"LOW": "Low volatility", "NORMAL": "Normal volatility",
            "HIGH": "High volatility"}.get(str(vol_regime).upper())


def _ema_factor(ema_align) -> str | None:
    if ema_align is None:
        return None
    n = sum(1 for x in ema_align if x)
    if n == 3:
        return "Bullish EMA stack"
    if n == 0:
        return "Bearish EMA stack"
    return "Mixed EMA alignment"


def _regime_factor(regime) -> str | None:
    if not regime:
        return None
    r = str(regime).strip().lower()
    for fam, label in ((("bullish",), "Bullish market"),
                       (("bearish",), "Bearish market"),
                       (("neutral", "sideways", "range"), "Neutral market")):
        if any(k in r for k in fam):
            return label
    return f"{str(regime).strip().title()} market"


def _holding_factor(days) -> str | None:
    if days is None or days <= 0:
        return None
    if days <= 5:
        return "Short hold (<=5 days)"
    if days <= 15:
        return "Medium hold (6-15 days)"
    return "Long hold (>15 days)"


def _rr_factor(rr) -> str | None:
    if rr is None or rr <= 0:
        return None
    if rr < 1.5:
        return "Poor reward/risk (<1.5)"
    if rr <= 2.5:
        return "Fair reward/risk (1.5-2.5)"
    return "Good reward/risk (>2.5)"


def factors_of(vec: dict) -> dict[str, str]:
    """Map a feature vector (from similarity_engine extractors) to named,
    human-readable factor labels keyed by feature. Missing values are omitted.
    Works for both current setups and historical trades."""
    holding = vec.get("holding_days")
    if holding is None:
        holding = vec.get("holding_period")
    out: dict[str, str | None] = {
        "rsi":        _rsi_factor(vec.get("rsi")),
        "adx":        _adx_factor(vec.get("adx")),
        "volume":     _volume_factor(vec.get("volume")),
        "vol_regime": _vol_factor(vec.get("vol_regime")),
        "atr":        _vol_factor(se._vol_regime_of(vec.get("atr_pct"))),
        "ema_align":  _ema_factor(vec.get("ema_align")),
        "macd_state": (f"{vec['macd_state'].title()} MACD"
                       if vec.get("macd_state") else None),
        "vwap_state": (None if vec.get("vwap_state") is None
                       else ("Above VWAP" if vec["vwap_state"] else "Below VWAP")),
        "supertrend": (None if vec.get("supertrend_state") is None
                       else ("Above Supertrend" if vec["supertrend_state"]
                             else "Below Supertrend")),
        "momentum":   (f"Momentum {vec['momentum'].lower()}"
                       if vec.get("momentum") else None),
        "regime":     _regime_factor(vec.get("regime")),
        "sector":     (f"Sector: {vec['sector']}" if vec.get("sector") else None),
        "strategy":   (f"Strategy: {vec['strategy']}" if vec.get("strategy") else None),
        "holding":    _holding_factor(holding),
        "risk_reward": _rr_factor(vec.get("risk_reward")),
    }
    return {k: v for k, v in out.items() if v is not None}


# ── 2. Winner/loser prevalence + ranked lift ──────────────────────────────────

def factor_prevalence(matches: list[dict]) -> dict:
    """Split similar historical trades into winners (return > 0) and losers,
    then compute, for every named factor, its prevalence in each group and
    the sample-size-shrunk predictive lift (winner% - loser%)."""
    winners = [m for m in matches if (m.get("return_percent") or 0) > 0]
    losers = [m for m in matches if (m.get("return_percent") or 0) <= 0
              and m.get("return_percent") is not None]
    nw, nl = len(winners), len(losers)

    def _count(group: list[dict]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for m in group:
            for feat, label in factors_of(m).items():
                counts[label] = counts.get(label, 0) + 1
        return counts

    wc, lc = _count(winners), _count(losers)
    shrink = min(nw, nl) / (min(nw, nl) + SHRINK_K) if (nw and nl) else 0.0
    table = []
    for label in sorted(set(wc) | set(lc)):
        wp = (wc.get(label, 0) / nw * 100.0) if nw else 0.0
        lp = (lc.get(label, 0) / nl * 100.0) if nl else 0.0
        lift = round((wp - lp) * shrink, 1)
        table.append({
            "factor": label,
            "winner_prevalence": round(wp, 1),
            "loser_prevalence": round(lp, 1),
            "lift": lift,
            "winner_count": wc.get(label, 0),
            "loser_count": lc.get(label, 0),
        })
    table.sort(key=lambda t: (-t["lift"], t["factor"]))
    return {"winners": nw, "losers": nl, "factors": table}


# ── 3. Root Cause Analysis for one stock ──────────────────────────────────────

def _join_names(names: list[str]) -> str:
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + " and " + names[-1]


def root_cause_for_item(cur: dict, matches: list[dict],
                        adjustment: float) -> dict:
    """Explain WHY the similarity evidence points the way it does, in terms of
    named factors shared with winners/losers. `adjustment` is the bounded
    similarity adjustment already applied (this function never adds one)."""
    prev = factor_prevalence(matches)
    cur_factors = set(factors_of(cur).values())
    nw, nl = prev["winners"], prev["losers"]

    shared_with_losers = [
        t for t in prev["factors"]
        if t["loser_prevalence"] >= LOSER_SHARED_MIN_PREVALENCE
        and t["lift"] <= LOSER_SHARED_MAX_LIFT
        and t["factor"] in cur_factors
    ]
    shared_with_winners = [
        t for t in prev["factors"]
        if t["winner_prevalence"] >= WINNER_SHARED_MIN_PREVALENCE
        and t["lift"] >= WINNER_SHARED_MIN_LIFT
        and t["factor"] in cur_factors
    ]
    shared_with_losers.sort(key=lambda t: (t["lift"], t["factor"]))
    shared_with_winners.sort(key=lambda t: (-t["lift"], t["factor"]))

    narrative = ""
    if nw < MIN_SIDE_SAMPLES or nl < MIN_SIDE_SAMPLES:
        narrative = (f"Not enough evidence for a root-cause analysis: only "
                     f"{nw} similar winning and {nl} similar losing trades "
                     f"(need at least {MIN_SIDE_SAMPLES} of each).")
    elif adjustment < 0 and shared_with_losers:
        top = shared_with_losers[:3]
        pct = round(sum(t["loser_prevalence"] for t in top) / len(top))
        names = _join_names([t["factor"] for t in top])
        both = ("this characteristic" if len(top) == 1
                else ("both characteristics" if len(top) == 2
                      else "all of these characteristics"))
        narrative = (f"{pct}% of similar losing trades shared {names}. "
                     f"The current setup has {both}. "
                     f"This reduced confidence by {abs(adjustment):.0f} points.")
    elif adjustment > 0 and shared_with_winners:
        top = shared_with_winners[:3]
        pct = round(sum(t["winner_prevalence"] for t in top) / len(top))
        names = _join_names([t["factor"] for t in top])
        both = ("this characteristic" if len(top) == 1
                else ("both characteristics" if len(top) == 2
                      else "all of these characteristics"))
        narrative = (f"{pct}% of similar winning trades shared {names}. "
                     f"The current setup has {both}. "
                     f"This increased confidence by {adjustment:.0f} points.")
    elif shared_with_losers:
        names = _join_names([t["factor"] for t in shared_with_losers[:3]])
        narrative = (f"Similar losing trades commonly shared {names}, which "
                     f"the current setup also has, but the overall evidence "
                     f"did not meet the threshold for a confidence change.")
    elif shared_with_winners:
        names = _join_names([t["factor"] for t in shared_with_winners[:3]])
        narrative = (f"Similar winning trades commonly shared {names}, which "
                     f"the current setup also has, but the overall evidence "
                     f"did not meet the threshold for a confidence change.")
    else:
        narrative = ("No single factor clearly separated similar winning "
                     "trades from losing ones for this setup.")

    def _slim(t: dict) -> dict:
        return {"factor": t["factor"], "lift": t["lift"],
                "winner_prevalence": t["winner_prevalence"],
                "loser_prevalence": t["loser_prevalence"]}

    return {
        "winners": nw,
        "losers": nl,
        "narrative": narrative,
        "factor_table": [_slim(t) for t in prev["factors"][:12]],
        "shared_with_losers": [_slim(t) for t in shared_with_losers[:5]],
        "shared_with_winners": [_slim(t) for t in shared_with_winners[:5]],
        "current_factors": sorted(cur_factors),
    }


# ── 4. Global feature importance (rolling) ────────────────────────────────────

def _feature_value(vec: dict, feature: str):
    """Categorical value (bucketed label) used for the separation index."""
    return factors_of(vec).get("atr" if feature == "atr" else feature)


_FI_FEATURE_KEYS = list(se.WEIGHTS.keys())


def compute_feature_importance(vectors: list[dict]) -> dict:
    """Separation-based importance of every similarity feature over ALL
    eligible completed trades. For each feature, importance is how differently
    its (bucketed) values are distributed among winners vs losers:
        importance = sum_v |P(v|winner) - P(v|loser)| / 2   in [0, 1]
    Direction: +1 if the feature's most winner-typical value has positive
    lift (helpful), else harmful. Deterministic."""
    winners = [v for v in vectors if (v.get("return_percent") or 0) > 0]
    losers = [v for v in vectors if v.get("return_percent") is not None
              and v["return_percent"] <= 0]
    nw, nl = len(winners), len(losers)
    features = []
    for feat in _FI_FEATURE_KEYS:
        wc: dict[str, int] = {}
        lc: dict[str, int] = {}
        w_seen = l_seen = 0
        for v in winners:
            val = _feature_value(v, feat)
            if val is not None:
                wc[val] = wc.get(val, 0) + 1
                w_seen += 1
        for v in losers:
            val = _feature_value(v, feat)
            if val is not None:
                lc[val] = lc.get(val, 0) + 1
                l_seen += 1
        n = w_seen + l_seen
        if w_seen == 0 or l_seen == 0:
            sep, best_val, best_lift = 0.0, None, 0.0
            worst_val, worst_lift = None, 0.0
        else:
            sep = 0.0
            best_val, best_lift = None, 0.0
            worst_val, worst_lift = None, 0.0
            for val in sorted(set(wc) | set(lc)):
                pw = wc.get(val, 0) / w_seen
                pl = lc.get(val, 0) / l_seen
                sep += abs(pw - pl)
                if (pw - pl) > best_lift:
                    best_val, best_lift = val, pw - pl
                if (pw - pl) < worst_lift:
                    worst_val, worst_lift = val, pw - pl
            sep /= 2.0
        confidence = round(n / (n + IMPORTANCE_CONF_K), 3)
        features.append({
            "feature": feat,
            "label": FEATURE_LABELS[feat],
            "importance": round(sep * confidence, 4),
            "raw_separation": round(sep, 4),
            "sample_size": n,
            "confidence": confidence,
            "best_value": best_val,
            "best_value_lift": round(best_lift * 100.0, 1),
            "worst_value": worst_val,
            "worst_value_lift": round(worst_lift * 100.0, 1),
            "static_weight": se.WEIGHTS[feat],
        })
    total_imp = sum(f["importance"] for f in features) or 1.0
    for f in features:
        f["contribution_pct"] = round(f["importance"] / total_imp * 100.0, 1)
        f["target_weight"] = round(f["importance"] / total_imp * 100.0, 2)
    return {"computed_at": _now(), "winners": nw, "losers": nl,
            "total_trades": nw + nl, "features": features}


# ── 5. Persistence: snapshots + dynamic weights (gated, gradual) ─────────────

def ensure_tables() -> None:
    with _connect() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS feature_importance_snapshots (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                computed_at   TEXT NOT NULL,
                trade_count   INTEGER NOT NULL,
                new_trades    INTEGER NOT NULL,
                weights_updated INTEGER NOT NULL DEFAULT 0,
                features_json TEXT NOT NULL
            )""")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS feature_weights (
                feature       TEXT PRIMARY KEY,
                weight        REAL NOT NULL,
                static_weight REAL NOT NULL,
                updated_at    TEXT NOT NULL
            )""")
        conn.commit()


def get_dynamic_weights() -> dict[str, float] | None:
    """Current dynamic weights, or None if never updated (static in force)."""
    ensure_tables()
    with _connect() as conn:
        rows = conn.execute("SELECT feature, weight FROM feature_weights").fetchall()
    if not rows:
        return None
    w = {r["feature"]: float(r["weight"]) for r in rows}
    if set(w) != set(se.WEIGHTS) or abs(sum(w.values()) - 100.0) > 0.5:
        return None  # defensive: malformed weights never used
    return w


def _last_snapshot(conn) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM feature_importance_snapshots"
        " ORDER BY id DESC LIMIT 1").fetchone()


def _blend_weights(prev: dict[str, float],
                   target: dict[str, float]) -> dict[str, float]:
    """Gradual, capped, renormalized weight update (safety §9)."""
    blended = {}
    for feat in se.WEIGHTS:
        p, t = prev[feat], target.get(feat, prev[feat])
        raw = WEIGHT_BLEND_PREV * p + WEIGHT_BLEND_TARGET * t
        lo, hi = p * (1 - WEIGHT_MAX_REL_CHANGE), p * (1 + WEIGHT_MAX_REL_CHANGE)
        blended[feat] = max(lo, min(hi, raw))
    total = sum(blended.values())
    return {f: round(w / total * 100.0, 3) for f, w in blended.items()}


def maybe_update_feature_importance(force_snapshot: bool = False) -> dict:
    """Recompute importance and (only when gated criteria are met) rebalance
    the dynamic weights. Called opportunistically from the decision pipeline;
    cheap when nothing changed. Returns a status dict (logged/API)."""
    ensure_tables()
    vectors = se.load_historical_vectors()
    trade_count = len(vectors)
    with _connect() as conn:
        last = _last_snapshot(conn)
        last_count = int(last["trade_count"]) if last else 0
        new_trades = trade_count - last_count
        if last is not None and new_trades < WEIGHT_UPDATE_MIN_NEW_TRADES \
                and not force_snapshot:
            return {"updated": False, "trade_count": trade_count,
                    "new_trades": new_trades,
                    "needed": WEIGHT_UPDATE_MIN_NEW_TRADES,
                    "reason": (f"Only {new_trades} new completed trades since "
                               f"the last update — {WEIGHT_UPDATE_MIN_NEW_TRADES} "
                               f"required before importance can change.")}

        fi = compute_feature_importance(vectors)
        weights_updated = False
        if last is None:
            # Baseline snapshot: record importance, keep static weights.
            now = _now()
            for feat, w in se.WEIGHTS.items():
                conn.execute(
                    "INSERT OR REPLACE INTO feature_weights"
                    " (feature, weight, static_weight, updated_at)"
                    " VALUES (?,?,?,?)", (feat, w, w, now))
        elif new_trades >= WEIGHT_UPDATE_MIN_NEW_TRADES:
            prev = get_dynamic_weights() or dict(se.WEIGHTS)
            target = {f["feature"]: f["target_weight"] for f in fi["features"]}
            new_w = _blend_weights(prev, target)
            now = _now()
            for feat, w in new_w.items():
                conn.execute(
                    "INSERT OR REPLACE INTO feature_weights"
                    " (feature, weight, static_weight, updated_at)"
                    " VALUES (?,?,?,?)", (feat, w, se.WEIGHTS[feat], now))
            weights_updated = True
        conn.execute(
            "INSERT INTO feature_importance_snapshots"
            " (computed_at, trade_count, new_trades, weights_updated,"
            "  features_json) VALUES (?,?,?,?,?)",
            (fi["computed_at"], trade_count, max(0, new_trades),
             1 if weights_updated else 0, json.dumps(fi["features"])))
        conn.commit()
    return {"updated": weights_updated, "trade_count": trade_count,
            "new_trades": new_trades, "snapshot": True}


# ── 6. Feature Importance report (API) ────────────────────────────────────────

def _trend_of(latest: float, previous: float | None) -> str:
    if previous is None:
        return "STABLE"
    if latest > previous * 1.05 + 1e-9:
        return "GAINING"
    if latest < previous * 0.95 - 1e-9:
        return "LOSING"
    return "STABLE"


def get_feature_importance_report() -> dict:
    """Everything the Feature Importance page needs. Always reflects the most
    recent snapshot (creating a baseline one if none exists)."""
    ensure_tables()
    maybe_update_feature_importance()   # gated internally; baseline on first run
    with _connect() as conn:
        snaps = conn.execute(
            "SELECT * FROM feature_importance_snapshots"
            " ORDER BY id DESC LIMIT 12").fetchall()
        weights = get_dynamic_weights()
        ever_rebalanced = conn.execute(
            "SELECT EXISTS(SELECT 1 FROM feature_importance_snapshots"
            " WHERE weights_updated = 1)").fetchone()[0]
    if not snaps:
        return {"features": [], "history": [], "updated_at": None,
                "total_trades": 0, "weights_dynamic": False,
                "trades_until_next_update": WEIGHT_UPDATE_MIN_NEW_TRADES,
                "safety": SAFETY_MESSAGE}
    latest = snaps[0]
    latest_features = json.loads(latest["features_json"])
    prev_by_feature: dict[str, float] = {}
    if len(snaps) > 1:
        for f in json.loads(snaps[1]["features_json"]):
            prev_by_feature[f["feature"]] = f["importance"]

    features = []
    for f in latest_features:
        # Backwards compatibility: older snapshots lack the worst_value fields.
        f.setdefault("worst_value", None)
        f.setdefault("worst_value_lift", 0.0)
        w_now = (weights or se.WEIGHTS).get(f["feature"], se.WEIGHTS[f["feature"]])
        features.append({
            **f,
            "current_weight": round(float(w_now), 2),
            "trend": _trend_of(f["importance"],
                               prev_by_feature.get(f["feature"])),
            "direction": ("HELPFUL"
                          if f["best_value_lift"] >= abs(f["worst_value_lift"])
                          else "HARMFUL"),
        })
    features.sort(key=lambda f: -f["importance"])

    history = [{
        "computed_at": s["computed_at"],
        "trade_count": s["trade_count"],
        "weights_updated": bool(s["weights_updated"]),
        "importance": {f["feature"]: f["importance"]
                       for f in json.loads(s["features_json"])},
    } for s in reversed(snaps)]

    trade_count = int(latest["trade_count"])
    current_total = len(se.load_historical_vectors())
    remaining = max(0, WEIGHT_UPDATE_MIN_NEW_TRADES - (current_total - trade_count))
    return {
        "features": features,
        "history": history,
        "updated_at": latest["computed_at"],
        "total_trades": current_total,
        "weights_dynamic": weights is not None and bool(ever_rebalanced),
        "trades_until_next_update": remaining,
        "min_new_trades_per_update": WEIGHT_UPDATE_MIN_NEW_TRADES,
        "safety": SAFETY_MESSAGE,
    }
