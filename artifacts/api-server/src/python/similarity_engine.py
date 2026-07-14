"""
similarity_engine.py — v2.1 Evidence-Based Research Engine.

For every stock, compare the CURRENT market setup with historically similar
setups from the Historical Knowledge Base (historical_knowledge_trades in
trade_intelligence.db) and turn that evidence into:

  1. a weighted similarity score (0-100) against every eligible historical trade,
  2. evidence statistics from the best matches,
  3. an evidence-reliability classification (with reasons),
  4. a bounded, explainable confidence adjustment (+10 max / -15 max).

Hard rules (paper trading & research only — no real orders):
  - The existing strategy engine is NOT replaced; this is an ADDITIONAL layer.
  - Deterministic, explainable, auditable, reproducible: same inputs always
    produce the same outputs. No randomness anywhere.
  - Never uses synthetic/mock records as evidence — the knowledge base is
    built exclusively from real Yahoo Finance simulations, and rows without
    real prices/returns are excluded defensively.
  - Lookahead prevention: only trades fully EXITED before the as-of date are
    eligible evidence.
  - Similarity evidence can never override hard risk filters and can never
    create a BUY on its own (enforced in decision_service).
  - LOW / VERY_LOW reliability evidence can never increase confidence.

Similarity weights (total = 100):
    strategy match     15      exact match only
    sector match       10      exact match only
    market regime      12      exact = full, related family = half
    volatility regime   8      exact = full, adjacent (LOW~NORMAL, NORMAL~HIGH) = half
    RSI similarity      8      normalized distance, scale 50 points
    ADX similarity      8      normalized distance, scale 40 points
    MACD state          8      BULLISH/BEARISH (line vs signal) exact match
    EMA alignment      10      3 sub-checks (9v20, 20v50, 50v200), 10/3 each
    VWAP state          5      price above/below VWAP match
    Supertrend state    5      price above/below Supertrend match
    ATR%% similarity     4      normalized distance, scale 3.0 percentage points
    Volume-ratio sim.   4      normalized distance, scale 1.5x
    Momentum direction  3      UP/DOWN (MACD histogram sign) match

Missing feature values contribute ZERO points and reduce evidence quality.
"""

from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from datetime import datetime
from statistics import median, pstdev

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "trade_intelligence.db")

# ── Tunables (documented, deterministic) ──────────────────────────────────────
MIN_SIMILARITY        = 65.0   # matches below this are discarded
MAX_MATCHES           = 50     # top-N retained after the similarity filter
PRIMARY_MATCHES       = 20     # top-N used for the evidence statistics
DISPLAY_MATCHES       = 5      # top-N returned for UI display
MIN_MATCHES_FOR_TRUST = 10     # fewer than this => evidence LOW, no boost

# Adjustment gates and caps (spec §7)
POS_MIN_MATCHES   = 20
POS_MIN_AVG_SIM   = 75.0
POS_MIN_EXPECT    = 0.75   # %
POS_MIN_PF        = 1.5
NEG_MIN_MATCHES   = 20
NEG_MIN_AVG_SIM   = 75.0
MAX_POS_ADJ       = 10.0
MAX_NEG_ADJ       = -15.0
MIN_POS_ADJ       = 2.0
MIN_NEG_ADJ       = -3.0
SMALL_NEG_ADJ     = -3.0   # allowed on weak evidence that is consistently poor

# Numerical similarity scales (full weight at distance 0, zero at >= scale)
RSI_SCALE   = 50.0
ADX_SCALE   = 40.0
ATR_SCALE   = 3.0    # ATR as % of price
VOL_SCALE   = 1.5    # volume ratio (x average)

WEIGHTS = {
    "strategy":   15.0,
    "sector":     10.0,
    "regime":     12.0,
    "vol_regime":  8.0,
    "rsi":         8.0,
    "adx":         8.0,
    "macd_state":  8.0,
    "ema_align":  10.0,
    "vwap_state":  5.0,
    "supertrend":  5.0,
    "atr":         4.0,
    "volume":      4.0,
    "momentum":    3.0,
}
assert abs(sum(WEIGHTS.values()) - 100.0) < 1e-9

# Features considered "important": if the CURRENT setup is missing any of
# these, evidence quality is reduced (reliability downgraded).
IMPORTANT_FEATURES = ("rsi", "adx", "macd_state", "ema_align")

# Regime families for partial credit (related regimes get half points).
_REGIME_FAMILIES = [
    {"bullish", "strong bullish", "mildly bullish"},
    {"bearish", "strong bearish", "mildly bearish"},
    {"neutral", "sideways", "range-bound"},
]
_VOL_ADJACENT = {("LOW", "NORMAL"), ("NORMAL", "LOW"),
                 ("NORMAL", "HIGH"), ("HIGH", "NORMAL")}

SAFETY_MESSAGE = ("Historical similarity does not guarantee that the current "
                  "trade will have the same outcome. Paper trading and "
                  "research only.")


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _f(v, default=None):
    try:
        if v is None:
            return default
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except Exception:
        return default


# ── 1. Feature extraction ─────────────────────────────────────────────────────

def _macd_state(line, signal) -> str | None:
    l, s = _f(line), _f(signal)
    if l is None or s is None:
        return None
    return "BULLISH" if l >= s else "BEARISH"


def _ema_align(price, ema9, ema20, ema50, ema200) -> tuple | None:
    """Three boolean sub-relations: ema9>ema20, ema20>ema50, ema50>ema200.
    Requires the EMAs to actually exist (>0)."""
    e9, e20, e50, e200 = _f(ema9), _f(ema20), _f(ema50), _f(ema200)
    if not all(x is not None and x > 0 for x in (e9, e20, e50, e200)):
        return None
    return (e9 > e20, e20 > e50, e50 > e200)


def _above(price, level) -> bool | None:
    p, lv = _f(price), _f(level)
    if p is None or lv is None or p <= 0 or lv <= 0:
        return None
    return p >= lv


def _atr_pct(atr, price) -> float | None:
    a, p = _f(atr), _f(price)
    if a is None or p is None or p <= 0 or a < 0:
        return None
    return a / p * 100.0


def _momentum(macd_hist) -> str | None:
    h = _f(macd_hist)
    if h is None:
        return None
    return "UP" if h >= 0 else "DOWN"


def _trend_strength(adx) -> str:
    a = _f(adx)
    if a is None:
        return "UNKNOWN"
    if a >= 40:
        return "VERY STRONG"
    if a >= 25:
        return "STRONG"
    if a >= 20:
        return "MODERATE"
    return "WEAK"


def _vol_regime_of(atr_pct_val: float | None) -> str | None:
    """Volatility regime from ATR%% of price (matches the knowledge builder's
    LOW/NORMAL/HIGH convention)."""
    if atr_pct_val is None:
        return None
    if atr_pct_val < 1.2:
        return "LOW"
    if atr_pct_val > 2.8:
        return "HIGH"
    return "NORMAL"


def extract_current_features(item: dict, regime_now: str = "Neutral") -> dict:
    """Feature vector for the CURRENT setup of one scanned stock.
    Missing values stay None (zero similarity contribution + quality penalty)."""
    price = _f(item.get("price"))
    atr_pct = _atr_pct(item.get("atr"), price)
    vol_regime = item.get("volatility_regime")
    if not vol_regime:
        vol_regime = _vol_regime_of(atr_pct)
    return {
        # identity & context
        "symbol":      str(item.get("stock", "")).upper(),
        "sector":      str(item.get("sector", "") or "") or None,
        "strategy":    str(item.get("best_strategy_id", "") or "") or None,
        "regime":      str(regime_now or "") or None,
        "vol_regime":  (str(vol_regime).upper() if vol_regime else None),
        "holding_period": _f(item.get("expected_holding_days")),
        # technical
        "rsi":         _f(item.get("rsi")),
        "adx":         _f(item.get("adx")),
        "macd_state":  _macd_state(item.get("macd_line"), item.get("macd_signal")),
        "macd_hist_dir": _momentum(item.get("macd_hist")),
        "ema_align":   _ema_align(price, item.get("ema9"), item.get("ema20"),
                                  item.get("ema50"), item.get("ema200")),
        "vwap_state":  _above(price, item.get("vwap")),
        "supertrend_state": _above(price, item.get("supertrend")),
        "atr_pct":     atr_pct,
        "volume":      _f(item.get("volume_ratio")),
        "momentum":    _momentum(item.get("macd_hist")),
        "trend_strength": _trend_strength(item.get("adx")),
        # decision & risk (context only — not used in the similarity score)
        "base_confidence":   _f(item.get("base_confidence"), _f(item.get("confidence"))),
        "opportunity_score": _f(item.get("opportunity_score")),
        "trade_quality":     _f(item.get("trade_quality")),
        "risk_reward":       _f(item.get("rr_ratio")),
        "entry_price":       _f(item.get("entry_price")),
        "stop_loss":         _f(item.get("stop_loss")),
        "target":            _f(item.get("target")),
    }


def extract_historical_features(row: dict) -> dict:
    """Feature vector for one historical_knowledge_trades row (entry snapshot)."""
    entry = _f(row.get("entry_price"))
    atr_pct = _atr_pct(row.get("atr"), entry)
    return {
        "id":          row.get("id"),
        "symbol":      str(row.get("symbol", "")).upper(),
        "sector":      str(row.get("sector", "") or "") or None,
        "strategy":    str(row.get("strategy", "") or "") or None,
        "regime":      str(row.get("market_regime", "") or "") or None,
        "vol_regime":  (str(row.get("volatility_regime")).upper()
                        if row.get("volatility_regime") else None),
        "holding_days": _f(row.get("holding_days")),
        "rsi":         _f(row.get("rsi")),
        "adx":         _f(row.get("adx")),
        "macd_state":  _macd_state(row.get("macd"), row.get("macd_signal")),
        "ema_align":   _ema_align(entry, row.get("ema9"), row.get("ema20"),
                                  row.get("ema50"), row.get("ema200")),
        "vwap_state":  _above(entry, row.get("vwap")),
        "supertrend_state": _above(entry, row.get("supertrend")),
        "atr_pct":     atr_pct,
        "volume":      _f(row.get("volume_ratio")),
        # momentum direction is not stored; derive from MACD line vs signal
        # (histogram = line - signal, so its sign is line >= signal).
        "momentum":    ("UP" if (_f(row.get("macd")) is not None
                                 and _f(row.get("macd_signal")) is not None
                                 and _f(row.get("macd")) >= _f(row.get("macd_signal")))
                        else "DOWN" if (_f(row.get("macd")) is not None
                                        and _f(row.get("macd_signal")) is not None)
                        else None),
        # outcome
        "entry_date":     str(row.get("entry_date", "") or ""),
        "exit_date":      str(row.get("exit_date", "") or ""),
        "return_percent": _f(row.get("return_percent")),
        "winning":        int(row.get("winning") or 0),
        "exit_reason":    str(row.get("exit_reason", "") or ""),
        "entry_price":    entry,
    }


# ── 2. Similarity score (0-100, deterministic) ────────────────────────────────

def _numeric_sim(a, b, scale: float) -> float | None:
    """1.0 at zero distance, linearly down to 0.0 at >= scale. None if missing."""
    if a is None or b is None:
        return None
    return max(0.0, 1.0 - abs(a - b) / scale)


def _regime_sim(a: str | None, b: str | None) -> float | None:
    if not a or not b:
        return None
    al, bl = a.strip().lower(), b.strip().lower()
    if al == bl:
        return 1.0
    for fam in _REGIME_FAMILIES:
        if al in fam and bl in fam:
            return 0.5  # related regime — partial credit
    return 0.0


def _vol_regime_sim(a: str | None, b: str | None) -> float | None:
    if not a or not b:
        return None
    if a == b:
        return 1.0
    if (a, b) in _VOL_ADJACENT:
        return 0.5
    return 0.0


_WEIGHTS_CACHE: dict = {"ts": 0.0, "weights": None}
_WEIGHTS_TTL = 10.0  # seconds — dynamic weights change rarely (gated updates)


def get_active_weights() -> dict[str, float]:
    """Dynamic feature weights (v2.2 Root Cause Intelligence) when available,
    otherwise the static baseline. Dynamic weights are rebalanced gradually
    from historical evidence, gated at >=50 new completed trades per update,
    and always sum to 100 (validated defensively on load). Cached briefly —
    the DB lookup dominated hot loops in walk-forward runs."""
    now = time.time()
    if _WEIGHTS_CACHE["weights"] is not None and now - _WEIGHTS_CACHE["ts"] < _WEIGHTS_TTL:
        return _WEIGHTS_CACHE["weights"]
    weights = WEIGHTS
    try:
        import root_cause_engine
        dyn = root_cause_engine.get_dynamic_weights()
        if dyn is not None:
            weights = dyn
    except Exception:
        pass
    _WEIGHTS_CACHE["ts"] = now
    _WEIGHTS_CACHE["weights"] = weights
    return weights


def similarity_score(cur: dict, hist: dict,
                     weights: dict[str, float] | None = None) -> tuple[float, list[str]]:
    """Weighted similarity 0-100 between the current setup and one historical
    trade. Returns (score, missing_feature_names). Fully deterministic."""
    w = weights if weights is not None else WEIGHTS
    missing: list[str] = []
    total = 0.0

    def add(name: str, sim: float | None):
        nonlocal total
        if sim is None:
            missing.append(name)
            return
        total += w[name] * max(0.0, min(1.0, sim))

    add("strategy", None if not cur["strategy"] or not hist["strategy"]
        else (1.0 if cur["strategy"] == hist["strategy"] else 0.0))
    add("sector", None if not cur["sector"] or not hist["sector"]
        else (1.0 if cur["sector"] == hist["sector"] else 0.0))
    add("regime", _regime_sim(cur["regime"], hist["regime"]))
    add("vol_regime", _vol_regime_sim(cur["vol_regime"], hist["vol_regime"]))
    add("rsi", _numeric_sim(cur["rsi"], hist["rsi"], RSI_SCALE))
    add("adx", _numeric_sim(cur["adx"], hist["adx"], ADX_SCALE))
    add("macd_state", None if not cur["macd_state"] or not hist["macd_state"]
        else (1.0 if cur["macd_state"] == hist["macd_state"] else 0.0))
    # EMA alignment: three sub-relations, each worth 1/3 of the weight.
    if cur["ema_align"] is None or hist["ema_align"] is None:
        add("ema_align", None)
    else:
        matches = sum(1 for c, h in zip(cur["ema_align"], hist["ema_align"]) if c == h)
        add("ema_align", matches / 3.0)
    add("vwap_state", None if cur["vwap_state"] is None or hist["vwap_state"] is None
        else (1.0 if cur["vwap_state"] == hist["vwap_state"] else 0.0))
    add("supertrend", None if cur["supertrend_state"] is None or hist["supertrend_state"] is None
        else (1.0 if cur["supertrend_state"] == hist["supertrend_state"] else 0.0))
    add("atr", _numeric_sim(cur["atr_pct"], hist["atr_pct"], ATR_SCALE))
    add("volume", _numeric_sim(cur["volume"], hist["volume"], VOL_SCALE))
    add("momentum", None if not cur["momentum"] or not hist["momentum"]
        else (1.0 if cur["momentum"] == hist["momentum"] else 0.0))

    return round(total, 2), missing


# ── 3. Historical vector cache (performance §14) ──────────────────────────────

_HIST_CACHE: dict = {"key": None, "vectors": []}


def _cache_key(conn: sqlite3.Connection) -> tuple:
    row = conn.execute(
        "SELECT COUNT(*) AS n, COALESCE(MAX(id), 0) AS m"
        " FROM historical_knowledge_trades").fetchone()
    return (int(row["n"]), int(row["m"]))


def load_historical_vectors(force: bool = False) -> list[dict]:
    """Load + feature-extract all eligible historical trades once, cached in
    memory keyed on (row count, max id). Eligibility (data-error prevention):
      - real prices and a real return (no synthetic/mock rows),
      - fully exited (exit_date present) — enforced again vs as_of at query
        time for lookahead prevention,
      - duplicates removed (symbol, strategy, entry_date, exit_date)."""
    try:
        from historical_knowledge_builder import ensure_table
        ensure_table()
    except Exception:
        pass
    with _connect() as conn:
        key = _cache_key(conn)
        if not force and _HIST_CACHE["key"] == key:
            return _HIST_CACHE["vectors"]
        rows = conn.execute(
            "SELECT * FROM historical_knowledge_trades"
            " WHERE entry_price > 0 AND return_percent IS NOT NULL"
            " AND exit_date IS NOT NULL AND exit_date != ''"
            " ORDER BY id").fetchall()
    seen: set = set()
    vectors: list[dict] = []
    for r in rows:
        d = dict(r)
        dedupe = (d.get("symbol"), d.get("strategy"),
                  d.get("entry_date"), d.get("exit_date"))
        if dedupe in seen:
            continue
        seen.add(dedupe)
        vectors.append(extract_historical_features(d))
    _HIST_CACHE["key"] = key
    _HIST_CACHE["vectors"] = vectors
    return vectors


# ── 4. Match retrieval ────────────────────────────────────────────────────────

# Vectorized scoring (performance): walk-forward runs call find_matches once
# per candidate per day — a pure-Python scan over every historical vector made
# long runs ~100x slower. The numpy path computes identical scores in bulk.
try:
    import numpy as _np
except Exception:  # pragma: no cover
    _np = None

_PREP_CACHE: dict = {"key": None, "prep": None}

_VOL_ADJ_MAP = {"LOW": ("NORMAL",), "NORMAL": ("LOW", "HIGH"), "HIGH": ("NORMAL",)}


def _codes(values: list, extra_missing=("",)) -> tuple:
    """Encode a categorical column as int codes (-1 = missing) + value→code map."""
    mapping: dict = {}
    codes = _np.empty(len(values), dtype=_np.int64)
    for i, v in enumerate(values):
        if v is None or v in extra_missing:
            codes[i] = -1
            continue
        c = mapping.get(v)
        if c is None:
            c = len(mapping)
            mapping[v] = c
        codes[i] = c
    return codes, mapping


def _prep_vectors(vectors: list[dict]) -> dict:
    """Precompute numpy columns for a vectors list (cached on identity+len).
    Categorical features are int-encoded so all comparisons stay in numpy."""
    # Keyed on list identity + length + the DB-content key of the hist cache,
    # so a rebuilt vectors list can never collide with a stale prep cache.
    key = (id(vectors), len(vectors), _HIST_CACHE["key"])
    if _PREP_CACHE["key"] == key:
        return _PREP_CACHE["prep"]
    n = len(vectors)

    def num(field):
        return _np.array([v.get(field) if v.get(field) is not None else _np.nan
                          for v in vectors], dtype=float)

    ema = _np.full((n, 3), _np.nan)
    for i, v in enumerate(vectors):
        ea = v.get("ema_align")
        if ea is not None:
            ema[i] = [1.0 if b else 0.0 for b in ea]

    prep = {"n": n, "cat": {}, "rsi": num("rsi"), "adx": num("adx"),
            "atr_pct": num("atr_pct"), "volume": num("volume"), "ema": ema,
            "exit_date": _np.array([str(v.get("exit_date") or "")[:10]
                                    for v in vectors]),
            "id": _np.array([v.get("id") or 0 for v in vectors], dtype=_np.int64)}
    for name, field in (("strategy", "strategy"), ("sector", "sector"),
                        ("macd_state", "macd_state"), ("vwap", "vwap_state"),
                        ("supertrend", "supertrend_state"), ("momentum", "momentum"),
                        ("vol_regime", "vol_regime")):
        prep["cat"][name] = _codes([v.get(field) for v in vectors])

    regimes_l = [(str(v.get("regime")).strip().lower() if v.get("regime") else None)
                 for v in vectors]
    prep["cat"]["regime"] = _codes(regimes_l)
    # Family id per historical row (-1 = no family) for partial regime credit.
    fam_of = {r: fi for fi, fam in enumerate(_REGIME_FAMILIES) for r in fam}
    prep["regime_fam"] = _np.array([fam_of.get(r, -1) if r else -1
                                    for r in regimes_l], dtype=_np.int64)
    _PREP_CACHE["key"] = key
    _PREP_CACHE["prep"] = prep
    return prep


def _scores_vectorized(cur: dict, prep: dict, w: dict[str, float]):
    """Similarity scores (0-100) for every historical vector — identical
    semantics to similarity_score(): missing features contribute zero."""
    total = _np.zeros(prep["n"])

    def add_eq(wname: str, curval, cat_name: str):
        nonlocal total
        if curval is None or curval == "":
            return
        codes, mapping = prep["cat"][cat_name]
        c = mapping.get(curval, -2)
        total += w[wname] * (codes == c)

    add_eq("strategy", cur.get("strategy"), "strategy")
    add_eq("sector", cur.get("sector"), "sector")
    add_eq("macd_state", cur.get("macd_state"), "macd_state")
    add_eq("vwap_state", cur.get("vwap_state"), "vwap")
    add_eq("supertrend", cur.get("supertrend_state"), "supertrend")
    add_eq("momentum", cur.get("momentum"), "momentum")

    # regime: exact = 1.0, same family = 0.5
    creg = (str(cur.get("regime")).strip().lower() if cur.get("regime") else "")
    if creg:
        codes, mapping = prep["cat"]["regime"]
        eq = codes == mapping.get(creg, -2)
        total += w["regime"] * eq
        cfam = next((fi for fi, fam in enumerate(_REGIME_FAMILIES) if creg in fam), -2)
        rel = (prep["regime_fam"] == cfam) & ~eq
        total += 0.5 * w["regime"] * rel

    # vol_regime: exact = 1.0, adjacent = 0.5
    cvol = cur.get("vol_regime")
    if cvol:
        codes, mapping = prep["cat"]["vol_regime"]
        eq = codes == mapping.get(cvol, -2)
        total += w["vol_regime"] * eq
        adj_codes = [mapping[a] for a in _VOL_ADJ_MAP.get(cvol, ()) if a in mapping]
        if adj_codes:
            adj = _np.isin(codes, adj_codes) & ~eq
            total += 0.5 * w["vol_regime"] * adj

    # numeric features: 1 - |a-b|/scale clipped to [0, 1]; NaN contributes 0
    for wname, field, scale in (("rsi", "rsi", RSI_SCALE), ("adx", "adx", ADX_SCALE),
                                ("atr", "atr_pct", ATR_SCALE), ("volume", "volume", VOL_SCALE)):
        cv = cur.get(field)
        if cv is None:
            continue
        sim = _np.clip(1.0 - _np.abs(prep[field] - cv) / scale, 0.0, 1.0)
        total += w[wname] * _np.nan_to_num(sim)

    # EMA alignment: 3 sub-relations, each worth 1/3 of the weight
    cea = cur.get("ema_align")
    if cea is not None:
        cvec = _np.array([1.0 if b else 0.0 for b in cea])
        valid = ~_np.isnan(prep["ema"][:, 0])
        matches = (prep["ema"][valid] == cvec).sum(axis=1) / 3.0
        total[valid] += w["ema_align"] * matches

    return _np.round(total, 2)


def find_matches(cur: dict, vectors: list[dict],
                 as_of: str | None = None) -> tuple[list[dict], list[str]]:
    """Return up to MAX_MATCHES historical matches with similarity >=
    MIN_SIMILARITY, sorted by similarity desc (ties broken deterministically
    by exit_date desc then id). Excludes any trade not fully exited before
    `as_of` (lookahead prevention)."""
    as_of = as_of or datetime.now().strftime("%Y-%m-%d")
    missing_current = [f for f in WEIGHTS if _is_current_missing(cur, f)]
    weights = get_active_weights()
    scored: list[dict] = []
    if _np is not None and len(vectors) >= 50:
        prep = _prep_vectors(vectors)
        sims = _scores_vectorized(cur, prep, weights)
        eligible = ((prep["exit_date"] != "") & (prep["exit_date"] < as_of)
                    & (sims >= MIN_SIMILARITY))
        idx = _np.nonzero(eligible)[0]
        if idx.size:
            # Same deterministic order as the sort below: sim desc, then
            # exit_date asc, then id asc — done in numpy before building dicts.
            order = _np.lexsort((prep["id"][idx], prep["exit_date"][idx], -sims[idx]))
            idx = idx[order[:MAX_MATCHES]]
        for i in idx:
            h = vectors[i]
            scored.append({**h, "similarity": float(sims[i]),
                           "partial_match": _holding_mismatch(cur, h)})
    else:
        for h in vectors:
            # Lookahead prevention: evidence must be fully realized in the past.
            if not h["exit_date"] or h["exit_date"][:10] >= as_of:
                continue
            sim, _missing = similarity_score(cur, h, weights)
            if sim >= MIN_SIMILARITY:
                scored.append({**h, "similarity": sim,
                               "partial_match": _holding_mismatch(cur, h)})
    scored.sort(key=lambda m: (-m["similarity"], m["exit_date"], m["id"] or 0),
                reverse=False)
    return scored[:MAX_MATCHES], missing_current


def _is_current_missing(cur: dict, feature: str) -> bool:
    mapping = {"rsi": "rsi", "adx": "adx", "macd_state": "macd_state",
               "ema_align": "ema_align", "vwap_state": "vwap_state",
               "supertrend": "supertrend_state", "atr": "atr_pct",
               "volume": "volume", "momentum": "momentum",
               "strategy": "strategy", "sector": "sector",
               "regime": "regime", "vol_regime": "vol_regime"}
    return cur.get(mapping.get(feature, feature)) is None


def _holding_mismatch(cur: dict, hist: dict) -> bool:
    """Label incompatible holding periods as partial matches (spec §12)."""
    exp = cur.get("holding_period")
    hd = hist.get("holding_days")
    if not exp or not hd or exp <= 0 or hd <= 0:
        return False
    ratio = hd / exp
    return ratio > 4.0 or ratio < 0.25


# ── 5. Evidence statistics ────────────────────────────────────────────────────

def evidence_stats(matches: list[dict]) -> dict:
    """Deterministic statistics over the PRIMARY match set."""
    primary = matches[:PRIMARY_MATCHES]
    rets = [m["return_percent"] for m in primary if m["return_percent"] is not None]
    n = len(rets)
    if n == 0:
        return {"matches": 0, "avg_similarity": 0.0, "wins": 0, "losses": 0,
                "win_rate": 0.0, "avg_return": 0.0, "median_return": 0.0,
                "avg_win_return": 0.0, "avg_loss_return": 0.0,
                "profit_factor": 0.0, "expectancy": 0.0,
                "max_adverse_excursion": 0.0, "max_favourable_excursion": 0.0,
                "avg_holding_days": 0.0, "return_std": 0.0,
                "historical_drawdown": 0.0, "best_outcome": 0.0,
                "worst_outcome": 0.0}
    wins   = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    win_rate = len(wins) / n * 100.0
    avg_win  = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    gross_win  = sum(wins)
    gross_loss = abs(sum(losses))
    pf = (gross_win / gross_loss) if gross_loss > 0 else (999.0 if gross_win > 0 else 0.0)
    expectancy = (win_rate / 100.0) * avg_win + (1 - win_rate / 100.0) * avg_loss

    # Historical drawdown: worst peak-to-trough of the equal-weight equity
    # curve over the matched returns ordered by entry_date (deterministic).
    ordered = sorted(primary, key=lambda m: (m["entry_date"], m["id"] or 0))
    equity, peak, max_dd = 1.0, 1.0, 0.0
    for m in ordered:
        r = m["return_percent"]
        if r is None:
            continue
        equity *= (1.0 + r / 100.0)
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak * 100.0)

    holding = [m["holding_days"] for m in primary if m["holding_days"]]
    return {
        "matches": n,
        "avg_similarity": round(sum(m["similarity"] for m in primary) / len(primary), 1),
        "wins": len(wins),
        "losses": len(losses),
        "win_rate": round(win_rate, 1),
        "avg_return": round(sum(rets) / n, 3),
        "median_return": round(median(rets), 3),
        "avg_win_return": round(avg_win, 3),
        "avg_loss_return": round(avg_loss, 3),
        "profit_factor": round(min(pf, 999.0), 2),
        "expectancy": round(expectancy, 3),
        # The knowledge base stores per-trade final returns (no intrabar
        # excursion series), so MAE/MFE are the worst/best realized outcomes.
        "max_adverse_excursion": round(min(rets), 2),
        "max_favourable_excursion": round(max(rets), 2),
        "avg_holding_days": round(sum(holding) / len(holding), 1) if holding else 0.0,
        "return_std": round(pstdev(rets), 3) if n > 1 else 0.0,
        "historical_drawdown": round(max_dd, 2),
        "best_outcome": round(max(rets), 2),
        "worst_outcome": round(min(rets), 2),
    }


# ── 6. Evidence reliability ───────────────────────────────────────────────────

_RELIABILITY_ORDER = ["VERY_LOW", "LOW", "MEDIUM", "HIGH"]


def classify_reliability(stats: dict, matches: list[dict],
                         missing_current: list[str]) -> tuple[str, list[str]]:
    # Tiering uses the FULL eligible match set (top-50 >=65%), while the
    # performance stats are computed over the top-20 primary sample.
    n = len(matches)
    if n < 10:
        level = "VERY_LOW"
        reasons = [f"Only {n} historical matches (fewer than 10)."]
    elif n < 20:
        level, reasons = "LOW", [f"{n} historical matches (10-19)."]
    elif n < 50:
        level, reasons = "MEDIUM", [f"{n} historical matches (20-49)."]
    else:
        level, reasons = "HIGH", [f"{n} historical matches (50+)."]

    downgrades = 0
    if n > 0 and stats["avg_similarity"] < 70.0:
        downgrades += 1
        reasons.append(f"Average similarity {stats['avg_similarity']:.0f}% is below 70%.")
    important_missing = [m for m in missing_current if m in IMPORTANT_FEATURES]
    if important_missing:
        downgrades += 1
        reasons.append("Important current features missing: "
                       + ", ".join(important_missing) + ".")
    primary = matches[:PRIMARY_MATCHES]
    if primary:
        by_symbol: dict[str, int] = {}
        for m in primary:
            by_symbol[m["symbol"]] = by_symbol.get(m["symbol"], 0) + 1
        top_share = max(by_symbol.values()) / len(primary)
        if top_share > 0.6:
            downgrades += 1
            dom = max(by_symbol, key=lambda s: by_symbol[s])
            reasons.append(f"Matches concentrated in one stock ({dom}: "
                           f"{top_share * 100:.0f}% of the evidence).")
        dates = sorted(m["entry_date"][:10] for m in primary if m["entry_date"])
        if len(dates) >= 2:
            try:
                span = (datetime.fromisoformat(dates[-1])
                        - datetime.fromisoformat(dates[0])).days
                if span < 90:
                    downgrades += 1
                    reasons.append(f"Evidence spans only {span} days "
                                   "(very narrow time period).")
            except Exception:
                pass

    idx = max(0, _RELIABILITY_ORDER.index(level) - downgrades)
    final = _RELIABILITY_ORDER[idx]
    if final != level:
        reasons.append(f"Reliability downgraded from {level} to {final}.")
    return final, reasons


# ── 7. Evidence-based confidence adjustment ───────────────────────────────────

def confidence_adjustment(stats: dict, reliability: str) -> tuple[float, str]:
    """Bounded, gradual, explainable adjustment.
      Positive: +2..+10 requires >=20 matches, avg sim >=75%, expectancy
                > +0.75%, PF >= 1.5 AND reliability MEDIUM or HIGH.
      Negative: -3..-15 requires >=20 matches, avg sim >=75%, expectancy < 0,
                PF < 1.0. On weaker evidence that is consistently poor, only
                a small -3 is allowed.
    Deterministic linear scaling — documented and unit-tested."""
    n, sim = stats["matches"], stats["avg_similarity"]
    exp, pf = stats["expectancy"], stats["profit_factor"]

    if n < MIN_MATCHES_FOR_TRUST:
        # Insufficient evidence: never increase; allow a small negative nudge
        # only when the little evidence available is consistently poor.
        if n >= 5 and exp < 0 and pf < 1.0 and stats["win_rate"] < 40.0:
            return (SMALL_NEG_ADJ,
                    f"Confidence decreased by {abs(SMALL_NEG_ADJ):.0f} points "
                    f"because the only {n} historical matches found were "
                    f"consistently poor ({exp:+.2f}% expectancy, "
                    f"{pf:.2f} profit factor).")
        return (0.0, f"No confidence increase was applied because only {n} "
                     "reliable historical matches were found.")

    # Negative path (does NOT require high reliability — bad evidence warns).
    if n >= NEG_MIN_MATCHES and sim >= NEG_MIN_AVG_SIM and exp < 0 and pf < 1.0:
        # Scale by how bad: expectancy 0..-2% and PF 1.0..0.5 both push
        # towards the -15 cap. 60% weight on expectancy, 40% on PF.
        sev = min(1.0, (abs(exp) / 2.0) * 0.6 + max(0.0, (1.0 - pf) / 0.5) * 0.4)
        adj = round(MIN_NEG_ADJ + (MAX_NEG_ADJ - MIN_NEG_ADJ) * sev, 1)
        adj = max(MAX_NEG_ADJ, min(MIN_NEG_ADJ, adj))
        return (adj,
                f"Confidence decreased by {abs(adj):.0f} points because {n} "
                f"highly similar historical setups (avg {sim:.0f}% similarity) "
                f"produced {exp:+.2f}% expectancy and a {pf:.2f} profit factor.")

    # Positive path — blocked entirely for LOW / VERY_LOW reliability.
    if reliability in ("LOW", "VERY_LOW"):
        return (0.0, f"No confidence increase was applied because evidence "
                     f"reliability is {reliability} ({n} matches).")
    if n >= POS_MIN_MATCHES and sim >= POS_MIN_AVG_SIM \
            and exp > POS_MIN_EXPECT and pf >= POS_MIN_PF:
        # Scale by how good: expectancy +0.75..+2.75% (50%), PF 1.5..3.0
        # (30%), similarity 75..100% (20%).
        qual = min(1.0, ((exp - POS_MIN_EXPECT) / 2.0) * 0.5
                   + min(1.0, (pf - POS_MIN_PF) / 1.5) * 0.3
                   + min(1.0, (sim - POS_MIN_AVG_SIM) / 25.0) * 0.2)
        adj = round(MIN_POS_ADJ + (MAX_POS_ADJ - MIN_POS_ADJ) * qual, 1)
        adj = min(MAX_POS_ADJ, max(MIN_POS_ADJ, adj))
        return (adj,
                f"Confidence increased by {adj:.0f} points because {n} highly "
                f"similar historical setups averaged {sim:.0f}% similarity, "
                f"produced {exp:+.2f}% expectancy, and had a {pf:.2f} profit "
                f"factor.")

    return (0.0, f"No similarity adjustment: {n} matches at {sim:.0f}% average "
                 f"similarity with {exp:+.2f}% expectancy and {pf:.2f} profit "
                 f"factor did not meet the increase or decrease thresholds.")


# ── 8. Per-stock evidence + batch annotation ──────────────────────────────────

def _display_match(m: dict) -> dict:
    return {
        "symbol": m["symbol"],
        "entry_date": m["entry_date"][:10],
        "strategy": m["strategy"] or "",
        "sector": m["sector"] or "",
        "regime": m["regime"] or "",
        "similarity": round(m["similarity"], 1),
        "return_percent": round(m["return_percent"], 2) if m["return_percent"] is not None else 0.0,
        "holding_days": int(m["holding_days"] or 0),
        "exit_reason": m["exit_reason"],
        "partial_match": bool(m.get("partial_match")),
    }


def evidence_for_item(item: dict, vectors: list[dict],
                      regime_now: str = "Neutral",
                      as_of: str | None = None,
                      root_cause_fn=None) -> dict:
    """Full evidence record for ONE stock (deterministic). `root_cause_fn`
    (v2.2) receives (current_features, matches, adjustment) and returns a
    root-cause analysis dict — injected to avoid a circular import."""
    cur = extract_current_features(item, regime_now=regime_now)
    matches, missing_current = find_matches(cur, vectors, as_of=as_of)
    stats = evidence_stats(matches)
    reliability, reliability_reasons = classify_reliability(
        stats, matches, missing_current)
    adjustment, explanation = confidence_adjustment(stats, reliability)
    root_cause = None
    if root_cause_fn is not None:
        try:
            root_cause = root_cause_fn(cur, matches, adjustment)
        except Exception:
            root_cause = None
    return {
        "root_cause": root_cause,
        "match_count": len(matches),
        "avg_similarity": stats["avg_similarity"],
        "reliability": reliability,
        "reliability_reasons": reliability_reasons,
        "stats": stats,
        "adjustment": adjustment,
        "explanation": explanation,
        "top_matches": [_display_match(m) for m in matches[:DISPLAY_MATCHES]],
        "missing_features": missing_current,
        "safety": SAFETY_MESSAGE,
    }


def annotate_items_with_evidence(items: list[dict],
                                 regime_now: str = "Neutral",
                                 root_cause_fn=None) -> dict:
    """Batch-process all scanned stocks IN PLACE (performance §14).
    Adds to each item: similarity_adjustment, evidence_reliability,
    similarity_explanation, similarity_evidence (incl. root_cause when a
    root_cause_fn is provided). Items with scan errors or no data get a zero
    adjustment. Returns processing metadata (logged)."""
    t0 = time.time()
    vectors = load_historical_vectors()
    total_matches = 0
    for it in items:
        if it.get("error") is not None:
            it["similarity_adjustment"] = 0.0
            it["evidence_reliability"] = "VERY_LOW"
            it["similarity_explanation"] = ("No similarity evidence — stock "
                                            "could not be scanned.")
            it["similarity_evidence"] = None
            continue
        ev = evidence_for_item(it, vectors, regime_now=regime_now,
                               root_cause_fn=root_cause_fn)
        it["similarity_adjustment"] = ev["adjustment"]
        it["evidence_reliability"] = ev["reliability"]
        it["similarity_explanation"] = ev["explanation"]
        it["similarity_evidence"] = ev
        total_matches += ev["match_count"]
    meta = {
        "historical_vectors": len(vectors),
        "stocks_processed": len(items),
        "total_matches": total_matches,
        "processing_ms": round((time.time() - t0) * 1000.0, 1),
    }
    try:
        print(f"[similarity_engine] processed {meta['stocks_processed']} stocks "
              f"against {meta['historical_vectors']} historical vectors in "
              f"{meta['processing_ms']}ms ({meta['total_matches']} matches)",
              flush=True)
    except Exception:
        pass
    return meta


# ── 9. API payload (GET /api/evidence-research) ───────────────────────────────

def get_evidence_research() -> dict:
    """One evidence record per stock, riding on the full decision pipeline
    (so recommendations/final confidence match the Trade Decisions page)."""
    from decision_service import get_trade_decisions
    payload = get_trade_decisions()
    records = []
    for d in payload.get("decisions", []):
        ev = d.get("similarity_evidence") or {}
        stats = ev.get("stats") or {}
        records.append({
            "symbol": d["stock"],
            "sector": d.get("sector", ""),
            "recommendation": d["recommendation"],
            "final_confidence": d["final_confidence"],
            "similarity_adjustment": d.get("similarity_adjustment", 0.0),
            "match_count": ev.get("match_count", 0),
            "avg_similarity": ev.get("avg_similarity", 0.0),
            "evidence_reliability": d.get("evidence_reliability", "VERY_LOW"),
            "reliability_reasons": ev.get("reliability_reasons", []),
            "win_rate": stats.get("win_rate", 0.0),
            "expectancy": stats.get("expectancy", 0.0),
            "profit_factor": stats.get("profit_factor", 0.0),
            "expected_return": stats.get("avg_return", 0.0),
            "expected_drawdown": stats.get("historical_drawdown", 0.0),
            "expected_holding_days": stats.get("avg_holding_days", 0.0),
            "top_matches": ev.get("top_matches", []),
            "explanation": ev.get("explanation", ""),
        })
    return {
        "generated_at": payload.get("generated_at"),
        "market_regime": payload.get("market_regime"),
        "universe_size": len(records),
        "records": records,
        "safety": SAFETY_MESSAGE,
    }
