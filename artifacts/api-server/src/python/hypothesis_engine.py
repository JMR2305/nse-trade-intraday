"""
Hypothesis Engine — Version 2.1 (upgrade from event logging to hypothesis
generation).

After every learning cycle this module does not just record WHAT happened —
it infers WHY. It compares successful and failed paper trades that share
similar conditions (strategy, sector, market regime, RSI band, ADX / trend
strength band, volatility regime, volume band), automatically detects
recurring patterns (minimum sample size 30 trades), estimates the
statistical confidence of every finding, and turns significant findings
into human-readable hypotheses such as:

    "Reduce confidence for MACD Cross in Banking during Strong Bull
     markets by 10%."

Every hypothesis is stored as a PROPOSED model update that requires
explicit user approval before it becomes a new model version. Approved
hypotheses are tracked after deployment: if the adjustment turns out to be
ineffective, it is automatically rolled back with a written explanation.

Hard safety rules (unchanged from spec v2 §7):
  - Only learn-eligible (verified live data) trades feed hypotheses.
  - Approval applies at most ±3 confidence points per cycle, ±15 total.
  - Approval also requires out-of-sample validation to pass.
  - A hypothesis can NEVER change strategy logic, entry/exit rules or hard
    risk filters, and can NEVER create a BUY on its own.

PAPER TRADING ONLY — research tool, never places orders.
"""

from __future__ import annotations

import json
import math
import sqlite3
from datetime import datetime

import trade_intelligence as _ti

# Tests may monkeypatch this to point at a temp DB.
DB_PATH = _ti.DB_PATH

MIN_SAMPLE = 30           # minimum trades in a segment (spec: 30)
MIN_CONFIDENCE = 90.0     # minimum statistical confidence to publish
MIN_EFFECT_EXPECTANCY = 0.30   # % per trade difference worth acting on
MIN_EFFECT_WIN_RATE = 10.0     # win-rate percentage-point difference
MIN_POST_TRADES = 10      # trades needed before judging effectiveness
MAX_STEP = 3.0            # bounded step per approval (spec §7)

# Canonical dimension order for scope encoding.
DIM_ORDER = ("strategy", "sector", "regime", "rsi_band", "adx_band",
             "volume_band", "volatility_regime")

# Dimension combinations mined for recurring patterns.
# Single dimensions first (broad patterns), then 2-3 dim combinations.
DIM_COMBOS = (
    ("strategy",),
    ("sector",),
    ("regime",),
    ("rsi_band",),
    ("adx_band",),
    ("volume_band",),
    ("volatility_regime",),
    ("strategy", "sector"),
    ("strategy", "regime"),
    ("sector", "regime"),
    ("strategy", "sector", "regime"),
    ("strategy", "rsi_band"),
    ("strategy", "adx_band"),
    ("strategy", "volume_band"),
    ("regime", "rsi_band"),
    ("regime", "adx_band"),
    ("regime", "volatility_regime"),
    ("sector", "volatility_regime"),
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS hypotheses (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT,
    dims            TEXT,      -- JSON {dim: value}
    scope_type      TEXT,      -- e.g. "strategy+sector+regime"
    scope_key       TEXT,      -- e.g. "macd_cross&BANKING&Strong Bull"
    statement       TEXT,      -- human-readable hypothesis
    rationale       TEXT,      -- the inferred WHY, in plain language
    direction       TEXT,      -- reduce | increase
    magnitude_pct   REAL,      -- suggested total change (confidence points)
    step_points     REAL,      -- bounded step applied per approval (±3)
    confidence_pct  REAL,      -- statistical confidence of the finding
    sample_size     INTEGER,
    evidence        TEXT,      -- JSON segment-vs-baseline metrics
    status          TEXT,      -- PROPOSED | APPLIED | REJECTED | ROLLED_BACK
    validation      TEXT,      -- JSON out-of-sample validation result
    decided_at      TEXT,
    applied_version INTEGER,
    effectiveness   TEXT       -- JSON post-deployment tracking
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


# ── Statistics (no external deps — normal approximations, valid n>=30) ───────

def _norm_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _two_sided_confidence(z: float) -> float:
    """Confidence % that the observed difference is not chance (1 - p)."""
    p = 2.0 * (1.0 - _norm_cdf(abs(z)))
    return round(max(0.0, min(100.0, (1.0 - p) * 100.0)), 1)


def win_rate_confidence(wins_a: int, n_a: int, wins_b: int, n_b: int) -> float:
    """Two-proportion z-test: is segment A's win rate really different from
    segment B's, or just noise?"""
    if n_a == 0 or n_b == 0:
        return 0.0
    p_a, p_b = wins_a / n_a, wins_b / n_b
    pooled = (wins_a + wins_b) / (n_a + n_b)
    denom = pooled * (1.0 - pooled) * (1.0 / n_a + 1.0 / n_b)
    if denom <= 0:
        return 0.0
    z = (p_a - p_b) / math.sqrt(denom)
    return _two_sided_confidence(z)


def returns_confidence(rets_a: list[float], rets_b: list[float]) -> float:
    """Welch test on mean per-trade return (normal approximation, n>=30)."""
    n_a, n_b = len(rets_a), len(rets_b)
    if n_a < 2 or n_b < 2:
        return 0.0
    m_a, m_b = sum(rets_a) / n_a, sum(rets_b) / n_b
    v_a = sum((x - m_a) ** 2 for x in rets_a) / (n_a - 1)
    v_b = sum((x - m_b) ** 2 for x in rets_b) / (n_b - 1)
    denom = v_a / n_a + v_b / n_b
    if denom <= 0:
        # Zero variance in both groups: any mean difference is exact.
        return 100.0 if abs(m_a - m_b) > 1e-12 else 0.0
    z = (m_a - m_b) / math.sqrt(denom)
    return _two_sided_confidence(z)


# ── Feature extraction ────────────────────────────────────────────────────────

def _features(e: dict) -> dict:
    """Segment features for one evaluated trade (frozen entry snapshot)."""
    from adaptive_adjustments import _bands_for
    return _bands_for(e)


def _display_names(evals: list[dict]) -> dict:
    """strategy_id -> most common human strategy name."""
    counts: dict[str, dict[str, int]] = {}
    for e in evals:
        snap = e.get("snapshot") or {}
        sid = str(snap.get("strategy_id") or "").strip().lower()
        name = str(snap.get("strategy_name") or "").strip()
        if sid and name:
            counts.setdefault(sid, {}).setdefault(name, 0)
            counts[sid][name] += 1
    return {sid: max(names, key=names.get) for sid, names in counts.items()}


# ── Human-readable statement builder ─────────────────────────────────────────

_BAND_PHRASES = {
    "rsi_band": {
        "oversold": "when RSI is oversold", "weak": "when RSI is weak",
        "neutral": "when RSI is neutral", "strong": "when RSI is strong",
        "overbought": "when RSI is overbought",
    },
    "adx_band": {
        "no_trend": "when there is no trend (low ADX)",
        "emerging": "when a trend is only emerging (ADX)",
        "trending": "when the trend is established (ADX)",
        "strong_trend": "when the trend is very strong (high ADX)",
    },
    "volume_band": {
        "low": "on low volume", "normal": "on normal volume",
        "elevated": "on elevated volume", "surge": "on a volume surge",
    },
    "volatility_regime": {
        "low": "in low-volatility conditions",
        "normal": "in normal-volatility conditions",
        "high": "in high-volatility conditions",
    },
}


def _title(s: str) -> str:
    return " ".join(w.capitalize() for w in str(s).replace("_", " ").split())


def build_statement(dims: dict, direction: str, magnitude: float,
                    strategy_names: dict) -> str:
    verb = "Reduce" if direction == "reduce" else "Increase"
    parts = []
    if "strategy" in dims:
        parts.append(strategy_names.get(dims["strategy"], _title(dims["strategy"])))
    else:
        parts.append("all strategies")
    if "sector" in dims:
        parts.append(f"in {_title(dims['sector'])}")
    if "regime" in dims:
        parts.append(f"during {dims['regime']} markets")
    for band_dim in ("rsi_band", "adx_band", "volume_band", "volatility_regime"):
        if band_dim in dims:
            phrase = _BAND_PHRASES[band_dim].get(dims[band_dim])
            if phrase:
                parts.append(phrase)
    return (f"{verb} confidence for {' '.join(parts)} "
            f"by {abs(magnitude):.0f}%.")


def _rationale(dims: dict, seg: dict, base: dict, direction: str) -> str:
    where = ", ".join(f"{_title(k)}: {v}" for k, v in dims.items())
    if direction == "reduce":
        return (f"Trades taken under [{where}] underperformed the rest of the "
                f"book: expectancy {seg['expectancy']:+.2f}% vs "
                f"{base['expectancy']:+.2f}% per trade and win rate "
                f"{seg['win_rate']:.0f}% vs {base['win_rate']:.0f}% "
                f"({seg['trades']} trades). The recurring pattern suggests the "
                f"model is systematically overconfident in this situation.")
    return (f"Trades taken under [{where}] outperformed the rest of the book: "
            f"expectancy {seg['expectancy']:+.2f}% vs {base['expectancy']:+.2f}% "
            f"per trade and win rate {seg['win_rate']:.0f}% vs "
            f"{base['win_rate']:.0f}% ({seg['trades']} trades). The recurring "
            f"pattern suggests the model is systematically underconfident in "
            f"this situation.")


# ── Pattern mining ────────────────────────────────────────────────────────────

def _segment_metrics(evals: list[dict]) -> dict:
    from expectancy import compute_metrics
    trades = [{"return_percent": e.get("actual_return"),
               "holding_days": e.get("actual_holding_days"),
               "exit_date": e.get("exit_time")} for e in evals]
    m = compute_metrics(trades)
    return {"trades": m["trades"], "wins": m["wins"], "losses": m["losses"],
            "win_rate": m["win_rate"], "expectancy": m["expectancy"],
            "profit_factor": m["profit_factor"],
            "average_return": m["average_return"]}


def mine_patterns(evals: list[dict]) -> list[dict]:
    """Compare each dimension-combo segment (n>=MIN_SAMPLE) against all
    remaining trades and keep statistically confident, meaningful findings."""
    if len(evals) < MIN_SAMPLE * 2:   # a segment AND a comparison group
        return []
    feats = [(_features(e), e) for e in evals]
    findings: list[dict] = []

    for combo in DIM_COMBOS:
        segments: dict[tuple, list[dict]] = {}
        for f, e in feats:
            key = tuple(f.get(d, "") for d in combo)
            if any(v in ("", "unknown") for v in key):
                continue
            segments.setdefault(key, []).append(e)

        for key, seg_evals in segments.items():
            if len(seg_evals) < MIN_SAMPLE:
                continue
            seg_ids = {id(e) for e in seg_evals}
            rest = [e for e in evals if id(e) not in seg_ids]
            if len(rest) < MIN_SAMPLE:
                continue

            seg_m = _segment_metrics(seg_evals)
            rest_m = _segment_metrics(rest)

            d_exp = seg_m["expectancy"] - rest_m["expectancy"]
            d_wr = seg_m["win_rate"] - rest_m["win_rate"]
            exp_material = abs(d_exp) >= MIN_EFFECT_EXPECTANCY
            wr_material = abs(d_wr) >= MIN_EFFECT_WIN_RATE
            if not exp_material and not wr_material:
                continue
            # Contradictory evidence (better returns but worse win rate, or
            # vice versa, both by a material margin) — not a usable pattern.
            if exp_material and wr_material and d_exp * d_wr < 0:
                continue

            conf_ret = returns_confidence(
                [_f(e.get("actual_return")) for e in seg_evals],
                [_f(e.get("actual_return")) for e in rest])
            conf_wr = win_rate_confidence(
                seg_m["wins"], seg_m["trades"], rest_m["wins"], rest_m["trades"])
            # Every materially different metric must ALSO be statistically
            # significant on its own test — a weak test cannot ride along on
            # a strong one.
            supporting = []
            if exp_material:
                supporting.append(conf_ret)
            if wr_material:
                supporting.append(conf_wr)
            confidence = min(supporting)
            if confidence < MIN_CONFIDENCE:
                continue

            direction = "reduce" if (d_exp < 0 or (abs(d_exp) < 1e-9 and d_wr < 0)) \
                else "increase"
            effect = max(abs(d_exp) / 0.15, abs(d_wr) / 2.0)  # rough scale
            magnitude = 5.0 if effect < 7 else (10.0 if effect < 14 else 15.0)

            dims = {d: k for d, k in zip(combo, key)}
            findings.append({
                "dims": dims,
                "direction": direction,
                "magnitude_pct": magnitude,
                "confidence_pct": round(confidence, 1),
                "sample_size": seg_m["trades"],
                "evidence": {
                    "segment": seg_m, "baseline": rest_m,
                    "expectancy_diff": round(d_exp, 2),
                    "win_rate_diff": round(d_wr, 1),
                    "confidence_returns_test": conf_ret,
                    "confidence_win_rate_test": conf_wr,
                },
            })

    # Strongest findings first; cap per cycle for reviewability. Ties favour
    # risk-REDUCING hypotheses (capital preservation first). To keep the
    # shortlist diverse, the best finding of each scope type is prioritised
    # before a second finding of an already-represented type is admitted.
    findings.sort(key=lambda f: (f["confidence_pct"],
                                 abs(f["evidence"]["expectancy_diff"]),
                                 f["direction"] == "reduce"),
                  reverse=True)
    first_pass, second_pass, seen_types = [], [], set()
    for f in findings:
        stype = "+".join(d for d in DIM_ORDER if d in f["dims"])
        (second_pass if stype in seen_types else first_pass).append(f)
        seen_types.add(stype)
    return (first_pass + second_pass)[:12]


# ── Scope encoding (shared with model_versioning / decision context) ─────────

def scope_of(dims: dict) -> tuple[str, str]:
    ordered = [d for d in DIM_ORDER if d in dims]
    return "+".join(ordered), "&".join(str(dims[d]) for d in ordered)


# ── Hypothesis persistence + lifecycle ────────────────────────────────────────

def generate_hypotheses(evals: list[dict] | None = None) -> list[dict]:
    """Mine patterns and (re)write PROPOSED hypotheses. Applies NOTHING.
    Existing decided hypotheses (applied/rejected/rolled back) are kept for
    the audit trail; an open proposal for the same scope is replaced."""
    if evals is None:
        from adaptive_adjustments import _eligible_evaluations
        evals = _eligible_evaluations()

    findings = mine_patterns(evals)
    names = _display_names(evals)
    stored: list[dict] = []

    conn = _connect()
    try:
        for f in findings:
            scope_type, scope_key = scope_of(f["dims"])
            # Never re-propose a scope that was already decided and is still
            # in force (applied and not rolled back) or explicitly rejected
            # within this dataset size.
            decided = conn.execute(
                "SELECT status FROM hypotheses WHERE scope_type=? AND scope_key=? "
                "AND status IN ('APPLIED','REJECTED') "
                "ORDER BY id DESC LIMIT 1", (scope_type, scope_key)).fetchone()
            if decided:
                continue
            signed = f["magnitude_pct"] if f["direction"] == "increase" \
                else -f["magnitude_pct"]
            step = max(-MAX_STEP, min(MAX_STEP, signed))
            statement = build_statement(f["dims"], f["direction"],
                                        f["magnitude_pct"], names)
            rationale = _rationale(f["dims"], f["evidence"]["segment"],
                                   f["evidence"]["baseline"], f["direction"])
            conn.execute(
                "DELETE FROM hypotheses WHERE scope_type=? AND scope_key=? "
                "AND status='PROPOSED'", (scope_type, scope_key))
            cur = conn.execute(
                "INSERT INTO hypotheses (created_at, dims, scope_type, scope_key, "
                "statement, rationale, direction, magnitude_pct, step_points, "
                "confidence_pct, sample_size, evidence, status) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,'PROPOSED')",
                (datetime.now().isoformat(), json.dumps(f["dims"]), scope_type,
                 scope_key, statement, rationale, f["direction"],
                 signed, round(step, 1), f["confidence_pct"],
                 f["sample_size"], json.dumps(f["evidence"])))
            stored.append({"id": cur.lastrowid, "statement": statement,
                           "confidence_pct": f["confidence_pct"],
                           "sample_size": f["sample_size"]})
        conn.commit()
    finally:
        conn.close()
    return stored


def get_hypotheses(limit: int = 100) -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM hypotheses ORDER BY "
            "CASE status WHEN 'PROPOSED' THEN 0 ELSE 1 END, id DESC LIMIT ?",
            (int(limit),)).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("dims", "evidence", "validation", "effectiveness"):
            try:
                d[k] = json.loads(d.get(k) or "null")
            except Exception:
                d[k] = None
        out.append(d)
    return out


def _get(conn: sqlite3.Connection, hyp_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM hypotheses WHERE id=?",
                       (int(hyp_id),)).fetchone()
    return dict(row) if row else None


def approve_hypothesis(hyp_id: int) -> dict:
    """User approval: out-of-sample validate, then apply ONE bounded step
    (±3 points max) as a new model version. Validation failure auto-rejects."""
    conn = _connect()
    try:
        h = _get(conn, hyp_id)
        if not h:
            return {"success": False, "message": f"Hypothesis {hyp_id} not found."}
        if h["status"] != "PROPOSED":
            return {"success": False,
                    "message": f"Hypothesis {hyp_id} is already {h['status']}."}

        from adaptive_adjustments import validate_proposal
        proposal = {"scope_type": h["scope_type"], "scope_key": h["scope_key"],
                    "points": float(h["step_points"])}
        validation = validate_proposal(proposal)
        now = datetime.now().isoformat()
        if not validation["passed"]:
            conn.execute(
                "UPDATE hypotheses SET status='REJECTED', validation=?, "
                "decided_at=? WHERE id=?",
                (json.dumps(validation), now, int(hyp_id)))
            conn.commit()
            return {"success": False, "status": "REJECTED",
                    "message": validation["reason"], "validation": validation}

        from model_versioning import apply_update
        scope = f"{h['scope_type']}|{h['scope_key']}"
        result = apply_update(
            {scope: float(h["step_points"])},
            reason=f"Hypothesis #{hyp_id}: {h['statement']}",
            sample_size=int(h["sample_size"] or 0),
            expected_impact=(f"{float(h['step_points']):+.1f} confidence points "
                             f"(bounded step toward "
                             f"{float(h['magnitude_pct']):+.0f}) for "
                             f"{h['scope_type']} '{h['scope_key']}'"))
        if not result.get("applied"):
            conn.execute(
                "UPDATE hypotheses SET status='REJECTED', validation=?, "
                "decided_at=? WHERE id=?",
                (json.dumps({"passed": False, "reason": result.get("message")}),
                 now, int(hyp_id)))
            conn.commit()
            return {"success": False, "status": "REJECTED",
                    "message": result.get("message", "Cap reached.")}

        conn.execute(
            "UPDATE hypotheses SET status='APPLIED', validation=?, decided_at=?, "
            "applied_version=? WHERE id=?",
            (json.dumps(validation), now, result["version"], int(hyp_id)))
        conn.commit()
        return {"success": True, "status": "APPLIED",
                "model_version": result["version"],
                "message": (f"Hypothesis approved — model version "
                            f"{result['version']} created with a bounded "
                            f"{float(h['step_points']):+.1f} point step. Its "
                            f"real-world effect is now being tracked and it "
                            f"will be rolled back automatically if it does "
                            f"not help."),
                "validation": validation}
    finally:
        conn.close()


def reject_hypothesis(hyp_id: int) -> dict:
    conn = _connect()
    try:
        h = _get(conn, hyp_id)
        if not h:
            return {"success": False, "message": f"Hypothesis {hyp_id} not found."}
        if h["status"] != "PROPOSED":
            return {"success": False,
                    "message": f"Hypothesis {hyp_id} is already {h['status']}."}
        conn.execute(
            "UPDATE hypotheses SET status='REJECTED', decided_at=? WHERE id=?",
            (datetime.now().isoformat(), int(hyp_id)))
        conn.commit()
        return {"success": True, "status": "REJECTED",
                "message": f"Hypothesis {hyp_id} rejected — nothing was applied."}
    finally:
        conn.close()


# ── Post-deployment effectiveness tracking + automatic rollback ──────────────

def _in_dims(e: dict, dims: dict) -> bool:
    f = _features(e)
    return all(str(f.get(d, "")) == str(v) for d, v in dims.items())


def track_effectiveness() -> list[dict]:
    """For every APPLIED hypothesis: measure in-scope performance recorded
    AFTER the adjustment went live. If the evidence says the adjustment was
    wrong, roll the model version back automatically and explain why."""
    from adaptive_adjustments import _eligible_evaluations
    evals = _eligible_evaluations()

    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM hypotheses WHERE status='APPLIED'").fetchall()
        applied = [dict(r) for r in rows]
    finally:
        conn.close()

    actions: list[dict] = []
    for h in applied:
        try:
            dims = json.loads(h.get("dims") or "{}")
        except Exception:
            continue
        version = int(h.get("applied_version") or 0)
        post = [e for e in evals
                if int(e.get("model_version") or 0) >= version
                and _in_dims(e, dims)]
        if len(post) < MIN_POST_TRADES:
            _store_effectiveness(h["id"], {
                "post_trades": len(post),
                "verdict": "monitoring",
                "note": (f"Only {len(post)} in-scope trades since the change "
                         f"— need {MIN_POST_TRADES} before judging it.")})
            continue

        post_m = _segment_metrics(post)
        try:
            baseline = (json.loads(h.get("evidence") or "{}")
                        .get("segment", {}))
        except Exception:
            baseline = {}
        direction = h.get("direction")

        rollback_reason = None
        if direction == "reduce" and post_m["expectancy"] >= 0.5:
            rollback_reason = (
                f"The penalised segment now shows healthy performance "
                f"(expectancy {post_m['expectancy']:+.2f}% over "
                f"{post_m['trades']} trades) — the reduction is no longer "
                f"justified.")
        elif direction == "increase" and post_m["expectancy"] <= 0.0:
            rollback_reason = (
                f"The boosted segment stopped performing (expectancy "
                f"{post_m['expectancy']:+.2f}% over {post_m['trades']} "
                f"trades) — the increase did not improve results.")

        eff = {"post_trades": post_m["trades"],
               "post_expectancy": post_m["expectancy"],
               "post_win_rate": post_m["win_rate"],
               "baseline_expectancy": baseline.get("expectancy"),
               "baseline_win_rate": baseline.get("win_rate")}

        if rollback_reason:
            from model_versioning import rollback
            rb = rollback(version)
            eff.update({"verdict": "rolled_back", "note": rollback_reason,
                        "rollback": rb})
            conn = _connect()
            try:
                conn.execute(
                    "UPDATE hypotheses SET status='ROLLED_BACK', "
                    "effectiveness=?, decided_at=? WHERE id=?",
                    (json.dumps(eff), datetime.now().isoformat(), h["id"]))
                conn.commit()
            finally:
                conn.close()
            actions.append({"hypothesis_id": h["id"],
                            "action": "auto_rollback",
                            "statement": h.get("statement"),
                            "reason": rollback_reason,
                            "rolled_back_version": version})
        else:
            eff.update({"verdict": "effective",
                        "note": (f"Post-adjustment performance is consistent "
                                 f"with the hypothesis over "
                                 f"{post_m['trades']} trades — keeping it.")})
            _store_effectiveness(h["id"], eff)
            actions.append({"hypothesis_id": h["id"], "action": "kept",
                            "statement": h.get("statement"),
                            "reason": eff["note"]})
    return actions


def _store_effectiveness(hyp_id: int, eff: dict) -> None:
    conn = _connect()
    try:
        conn.execute("UPDATE hypotheses SET effectiveness=? WHERE id=?",
                     (json.dumps(eff), int(hyp_id)))
        conn.commit()
    finally:
        conn.close()
