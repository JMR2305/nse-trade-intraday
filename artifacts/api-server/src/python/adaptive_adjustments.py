"""
Adaptive Adjustments — Version 2.0 Adaptive Self-Evaluation (Module 3).

Aggregates evaluated paper-trade outcomes, builds confidence-calibration
bands, and PROPOSES bounded learning adjustments. Two modes (spec §9):

  A. Analysis Mode (default) — calculates proposed changes, applies nothing.
  B. Approved Learning Mode  — only explicitly approved proposals are
     applied, and only after out-of-sample validation passes. Every applied
     change creates a model version (model_versioning) and can be rolled back.

Hard safety rules (spec §7):
  - >=30 completed learn-eligible trades for group-level proposals,
    >=15 for symbol-specific proposals.
  - Max ±3 confidence points per learning cycle, ±15 total per scope.
  - Trades from synthetic/mock data are NEVER learned from
    (learn_eligible = 0 at evaluation time).
  - Never overrides hard risk filters; never creates a BUY on its own
    (enforced in decision_service).

PAPER TRADING ONLY — research tool, never places orders.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

import trade_intelligence as _ti
from expectancy import compute_metrics

# Tests may monkeypatch this to point at a temp DB.
DB_PATH = _ti.DB_PATH

MIN_GROUP_TRADES = 30
MIN_SYMBOL_TRADES = 15
MAX_STEP = 3.0
MIN_OOS_TRADES = 10     # out-of-sample scope trades needed to validate

BOOST_EXPECTANCY = 0.5
BOOST_PF = 1.3
CUT_EXPECTANCY = -0.2

CAL_BANDS = [(50, 59), (60, 69), (70, 79), (80, 89), (90, 95)]

WARN_LEARNING = ("Adaptive learning is based on historical and paper-trading "
                 "outcomes. It does not guarantee future profitability.")
WARN_SAMPLE = ("No learning change was applied because the sample size was "
               "insufficient.")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS proposed_adjustments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT,
    scope_type      TEXT,
    scope_key       TEXT,
    points          REAL,
    size_multiplier REAL,
    reason          TEXT,
    evidence        TEXT,
    sample_size     INTEGER,
    status          TEXT,      -- PROPOSED | APPROVED | REJECTED | APPLIED
    validation      TEXT,
    decided_at      TEXT,
    applied_version INTEGER
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


# ── Evaluation loading (learn-eligible only — never mock data) ───────────────

def _eligible_evaluations() -> list[dict]:
    import trade_evaluator
    evals = trade_evaluator.get_evaluation_with_snapshot(limit=100000)
    return [e for e in evals if int(e.get("learn_eligible") or 0) == 1]


def _bands_for(e: dict) -> dict:
    """Grouping bands for one evaluation (uses the frozen entry snapshot)."""
    from predictive_intelligence import rsi_bucket, adx_bucket, volume_bucket
    from model_versioning import confidence_band
    snap = e.get("snapshot") or {}
    ind = snap.get("indicators") or {}
    if isinstance(ind, str):
        try:
            ind = json.loads(ind)
        except Exception:
            ind = {}
    hold = _f(e.get("actual_holding_days"))
    return {
        "strategy": str(snap.get("strategy_id") or "").strip().lower(),
        "symbol": str(e.get("symbol") or "").upper(),
        "sector": str(e.get("sector") or "").upper(),
        "regime": str(snap.get("market_regime") or ""),
        "volatility_regime": str(snap.get("volatility_regime") or ""),
        "rsi_band": rsi_bucket(ind.get("rsi")),
        "adx_band": adx_bucket(ind.get("adx")),
        "volume_band": volume_bucket(ind.get("volume_ratio")),
        "confidence_band": confidence_band(e.get("predicted_confidence")),
        "pattern": str(snap.get("pattern_matched") or ""),
        "holding_band": ("short" if hold <= 3 else "medium" if hold <= 10 else "long"),
    }


def _metrics_of(evals: list[dict]) -> dict:
    trades = [{"return_percent": e.get("actual_return"),
               "holding_days": e.get("actual_holding_days"),
               "exit_date": e.get("exit_time")} for e in evals]
    m = compute_metrics(trades)
    pred_errs = [_f(e.get("prediction_error")) for e in evals
                 if e.get("prediction_error") is not None]
    m["avg_prediction_error"] = round(sum(pred_errs) / len(pred_errs), 2) \
        if pred_errs else None
    correct = sum(1 for e in evals if e.get("direction_correct"))
    m["calibration_accuracy"] = round(correct / len(evals) * 100.0, 1) if evals else 0.0
    return m


# ── Learning aggregation (spec §6) ────────────────────────────────────────────

def aggregate_outcomes(evals: list[dict] | None = None) -> dict:
    if evals is None:
        evals = _eligible_evaluations()
    dims = ("strategy", "symbol", "sector", "regime", "volatility_regime",
            "rsi_band", "adx_band", "volume_band", "confidence_band",
            "pattern", "holding_band")
    out: dict[str, list[dict]] = {}
    for dim in dims:
        groups: dict[str, list[dict]] = {}
        for e in evals:
            key = _bands_for(e).get(dim, "")
            if key in ("", "unknown"):
                continue
            groups.setdefault(key, []).append(e)
        rows = []
        for key, group in groups.items():
            rows.append({dim: key, **_metrics_of(group)})
        out[dim] = sorted(rows, key=lambda r: r["trades"], reverse=True)

    # By failure cause
    cause_groups: dict[str, list[dict]] = {}
    for e in evals:
        for c in (e.get("failure_causes") or []):
            cause_groups.setdefault(c.get("cause", "Unknown"), []).append(e)
    out["failure_cause"] = sorted(
        [{"failure_cause": k, **_metrics_of(v)} for k, v in cause_groups.items()],
        key=lambda r: r["trades"], reverse=True)
    return out


# ── Confidence calibration (spec §8) ─────────────────────────────────────────

def calibration_bands(evals: list[dict] | None = None) -> list[dict]:
    if evals is None:
        evals = _eligible_evaluations()
    rows = []
    for lo, hi in CAL_BANDS:
        band = [e for e in evals
                if e.get("predicted_confidence") is not None
                and lo <= _f(e.get("predicted_confidence")) <= hi]
        n = len(band)
        predicted_mid = (lo + hi) / 2.0
        if n == 0:
            rows.append({"band": f"{lo}-{hi}", "trades": 0,
                         "predicted_success_rate": predicted_mid,
                         "actual_success_rate": None, "gap": None,
                         "conclusion": "No data", "recommended_correction": 0.0})
            continue
        actual = sum(1 for e in band if e.get("direction_correct")) / n * 100.0
        gap = round(predicted_mid - actual, 1)
        if abs(gap) <= 5:
            conclusion, corr = "Well calibrated", 0.0
        elif gap > 0:
            conclusion = "Model is overconfident"
            corr = -min(4.0, round(gap * 0.15, 1))
        else:
            conclusion = "Model is underconfident"
            corr = min(4.0, round(abs(gap) * 0.15, 1))
        rows.append({"band": f"{lo}-{hi}", "trades": n,
                     "predicted_success_rate": predicted_mid,
                     "actual_success_rate": round(actual, 1), "gap": gap,
                     "conclusion": conclusion,
                     "recommended_correction": corr})
    return rows


def calibration_score(bands: list[dict]) -> float | None:
    """0-100: 100 = perfectly calibrated. Weighted by band sample size."""
    total_n, weighted_gap = 0, 0.0
    for b in bands:
        if b["gap"] is None or b["trades"] == 0:
            continue
        total_n += b["trades"]
        weighted_gap += abs(b["gap"]) * b["trades"]
    if total_n == 0:
        return None
    return round(max(0.0, 100.0 - weighted_gap / total_n), 1)


# ── Learning cycle: Analysis Mode (spec §9A) ─────────────────────────────────

def run_learning_cycle() -> dict:
    """Analysis Mode — evaluates pending trades, aggregates, and (re)writes
    PROPOSED adjustments. Applies NOTHING."""
    import trade_evaluator
    backfill = trade_evaluator.backfill_evaluations()

    evals = _eligible_evaluations()
    notes: list[str] = []
    proposals: list[dict] = []

    from model_versioning import get_active_version
    active_weights = get_active_version()["weights"]

    group_dims = ("strategy", "sector", "regime", "pattern")
    for dim in group_dims + ("symbol",):
        min_n = MIN_SYMBOL_TRADES if dim == "symbol" else MIN_GROUP_TRADES
        groups: dict[str, list[dict]] = {}
        for e in evals:
            key = _bands_for(e).get(dim, "")
            if key in ("", "unknown"):
                continue
            groups.setdefault(key, []).append(e)
        for key, group in groups.items():
            if len(group) < min_n:
                continue
            m = _metrics_of(group)
            points = 0.0
            if m["expectancy"] <= CUT_EXPECTANCY:
                points = -min(MAX_STEP, 1.0 + abs(m["expectancy"]))
                reason = (f"Negative expectancy {m['expectancy']:+.2f}% per trade "
                          f"over {m['trades']} completed paper trades "
                          f"(PF {m['profit_factor']:.2f}, win rate {m['win_rate']:.0f}%).")
            elif m["expectancy"] >= BOOST_EXPECTANCY and m["profit_factor"] > BOOST_PF:
                points = min(MAX_STEP, 0.5 + m["expectancy"])
                reason = (f"Positive expectancy {m['expectancy']:+.2f}% per trade "
                          f"over {m['trades']} completed paper trades "
                          f"(PF {m['profit_factor']:.2f}, win rate {m['win_rate']:.0f}%).")
            else:
                continue
            scope = f"{dim}|{key}"
            current = float(active_weights.get(scope, 0.0))
            capped = max(-15.0, min(15.0, current + points))
            if round(capped - current, 1) == 0.0:
                notes.append(f"{scope}: already at the ±15 point cap — skipped.")
                continue
            size_mult = 0.75 if points < 0 else (1.1 if points > 0 else 1.0)
            proposals.append({
                "scope_type": dim, "scope_key": key,
                "points": round(points, 1), "size_multiplier": size_mult,
                "reason": reason, "sample_size": m["trades"],
                "evidence": {k: m[k] for k in
                             ("trades", "wins", "losses", "win_rate", "expectancy",
                              "profit_factor", "average_return", "max_drawdown",
                              "avg_prediction_error", "calibration_accuracy")},
            })

    # Calibration-band corrections (spec §8)
    bands = calibration_bands(evals)
    for b in bands:
        if b["trades"] >= MIN_GROUP_TRADES and b["recommended_correction"] != 0.0:
            proposals.append({
                "scope_type": "confidence_band", "scope_key": b["band"],
                "points": max(-MAX_STEP, min(MAX_STEP, b["recommended_correction"])),
                "size_multiplier": 1.0,
                "reason": (f"{b['conclusion']}: predicted ~{b['predicted_success_rate']:.0f}% "
                           f"success in the {b['band']} band but actual was "
                           f"{b['actual_success_rate']:.0f}% over {b['trades']} trades."),
                "sample_size": b["trades"],
                "evidence": b,
            })

    # Persist proposals (replace prior open proposals for the same scope)
    conn = _connect()
    try:
        stored = 0
        for p in proposals:
            conn.execute(
                "DELETE FROM proposed_adjustments WHERE scope_type = ? AND "
                "scope_key = ? AND status = 'PROPOSED'",
                (p["scope_type"], p["scope_key"]))
            conn.execute(
                "INSERT INTO proposed_adjustments (created_at, scope_type, "
                "scope_key, points, size_multiplier, reason, evidence, "
                "sample_size, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PROPOSED')",
                (datetime.now().isoformat(), p["scope_type"], p["scope_key"],
                 p["points"], p["size_multiplier"], p["reason"],
                 json.dumps(p["evidence"]), p["sample_size"]))
            stored += 1
        conn.commit()
    finally:
        conn.close()

    if not proposals:
        notes.append(WARN_SAMPLE)

    # ── v2.1 Hypothesis generation + effectiveness tracking ─────────────────
    # After logging WHAT happened, infer WHY: mine recurring patterns across
    # comparable trades, publish statistically confident hypotheses (as
    # approval-gated proposals), and auto-rollback applied hypotheses that
    # turned out to be ineffective.
    hypotheses_created: list[dict] = []
    effectiveness_actions: list[dict] = []
    try:
        import hypothesis_engine
        effectiveness_actions = hypothesis_engine.track_effectiveness()
        hypotheses_created = hypothesis_engine.generate_hypotheses(evals)
        for a in effectiveness_actions:
            if a.get("action") == "auto_rollback":
                notes.append(f"Auto-rollback: {a.get('reason')}")
    except Exception as exc:
        notes.append(f"Hypothesis generation skipped: {exc}")

    return {
        "mode": "analysis",
        "evaluated_new": backfill.get("evaluated", 0),
        "eligible_trades": len(evals),
        "proposals_created": len(proposals),
        "proposals": proposals,
        "hypotheses_created": len(hypotheses_created),
        "hypotheses": hypotheses_created,
        "effectiveness_actions": effectiveness_actions,
        "calibration": bands,
        "notes": notes,
        "warning": WARN_LEARNING,
    }


# ── Out-of-sample validation (spec §11) ──────────────────────────────────────

def _kb_trades() -> list[dict]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND "
            "name='historical_knowledge_trades'").fetchone()
        if not row:
            return []
        wanted = ["symbol", "sector", "strategy", "market_regime", "exit_date",
                  "holding_days", "return_percent", "confidence", "rsi", "adx",
                  "volume_ratio", "volatility_regime"]
        have = {r[1] for r in conn.execute(
            "PRAGMA table_info(historical_knowledge_trades)")}
        cols = [c for c in wanted if c in have]
        rows = conn.execute(
            f"SELECT {', '.join(cols)} FROM historical_knowledge_trades "
            f"ORDER BY exit_date").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def _kb_dim_value(t: dict, dim: str) -> str:
    """Value of one hypothesis dimension for a knowledge-base trade
    (used for out-of-sample validation of combo scopes)."""
    from predictive_intelligence import rsi_bucket, adx_bucket, volume_bucket
    if dim == "strategy":
        return str(t.get("strategy") or "").strip().lower()
    if dim == "sector":
        return str(t.get("sector") or "").upper()
    if dim == "regime":
        return str(t.get("market_regime") or "")
    if dim == "rsi_band":
        return rsi_bucket(t.get("rsi"))
    if dim == "adx_band":
        return adx_bucket(t.get("adx"))
    if dim == "volume_band":
        return volume_bucket(t.get("volume_ratio"))
    if dim == "volatility_regime":
        return str(t.get("volatility_regime") or "").strip().lower()
    return ""


def _in_scope(t: dict, scope_type: str, scope_key: str) -> bool:
    # Hypothesis combo scopes, e.g. "strategy+sector+regime|x&Y&Z".
    if "+" in scope_type:
        dims = scope_type.split("+")
        keys = scope_key.split("&")
        if len(dims) != len(keys):
            return False
        return all(_kb_dim_value(t, d).lower() == str(k).strip().lower()
                   for d, k in zip(dims, keys))
    if scope_type == "strategy":
        return str(t.get("strategy") or "").strip().lower() == scope_key
    if scope_type == "symbol":
        return str(t.get("symbol") or "").upper() == scope_key
    if scope_type == "sector":
        return str(t.get("sector") or "").upper() == scope_key
    if scope_type == "regime":
        return str(t.get("market_regime") or "") == scope_key
    if scope_type == "pattern":
        parts = [p.strip() for p in scope_key.split("·")]
        if len(parts) != 3:
            return False
        return (str(t.get("strategy") or "").strip().lower() == parts[0].strip().lower()
                and str(t.get("sector") or "").upper() == parts[1].upper()
                and str(t.get("market_regime") or "") == parts[2])
    if scope_type == "confidence_band":
        from model_versioning import confidence_band
        return confidence_band(t.get("confidence")) == scope_key
    return False


def _weighted_metrics(trades: list[dict], weights: list[float]) -> dict:
    """Deterministic weighted portfolio metrics for old-vs-proposed model
    comparison. Weight = relative position size under that model."""
    import math
    pairs = [(w, _f(t.get("return_percent"))) for w, t in zip(weights, trades)]
    total_w = sum(w for w, _ in pairs)
    if total_w <= 0:
        return {"expectancy": 0.0, "profit_factor": 0.0, "max_drawdown": 0.0,
                "sharpe": 0.0}
    rets = [w * r for w, r in pairs]
    mean = sum(w * r for w, r in pairs) / total_w
    gross_win = sum(x for x in rets if x > 0)
    gross_loss = abs(sum(x for x in rets if x <= 0))
    pf = (gross_win / gross_loss) if gross_loss > 0 else (999.0 if gross_win > 0 else 0.0)
    equity, peak, max_dd = 1.0, 1.0, 0.0
    for x in rets:
        equity *= (1.0 + x / 100.0)
        peak = max(peak, equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - equity) / peak * 100.0)
    n = len(rets)
    var = sum((x - (sum(rets) / n)) ** 2 for x in rets) / n if n else 0.0
    std = math.sqrt(var)
    sharpe = ((sum(rets) / n) / std) if std > 0 else (99.0 if sum(rets) > 0 else 0.0)
    return {"expectancy": round(mean, 3), "profit_factor": round(min(pf, 999.0), 3),
            "max_drawdown": round(max_dd, 3), "sharpe": round(min(sharpe, 99.0), 3)}


def validate_proposal(proposal: dict) -> dict:
    """Out-of-sample check: compare old model vs proposed model on the most
    recent 30% of historical knowledge trades (never seen by the proposal's
    supporting sample). Rejects when the proposed model worsens expectancy,
    profit factor, max drawdown, or risk-adjusted return (sharpe).
    Win rate alone is NEVER used for approval (spec §11)."""
    kb = _kb_trades()
    if len(kb) < 50:
        return {"passed": False,
                "reason": ("Insufficient historical data for out-of-sample "
                           "validation (need 50+ knowledge-base trades).")}

    split = int(len(kb) * 0.7)
    oos = kb[split:]
    scope_type, scope_key = proposal["scope_type"], proposal["scope_key"]
    points = float(proposal["points"])

    in_scope_flags = [_in_scope(t, scope_type, scope_key) for t in oos]
    n_scope = sum(in_scope_flags)
    if n_scope < MIN_OOS_TRADES:
        return {"passed": False,
                "reason": (f"Only {n_scope} out-of-sample trades match this "
                           f"scope (need {MIN_OOS_TRADES}+) — not enough "
                           f"unseen evidence to validate the change.")}

    # Old model: every trade at weight 1.0.
    # Proposed model: scope trades re-weighted by the confidence shift
    # (bounded — a -15pt penalty halves the position, +15pt adds 50%).
    old_w = [1.0] * len(oos)
    prop_w = [1.0 + (points / 15.0) * 0.5 if flag else 1.0
              for flag in in_scope_flags]
    prop_w = [max(0.25, min(1.5, w)) for w in prop_w]

    old_m = _weighted_metrics(oos, old_w)
    new_m = _weighted_metrics(oos, prop_w)

    worsened = []
    if new_m["expectancy"] < old_m["expectancy"]:
        worsened.append("expectancy")
    if new_m["profit_factor"] < old_m["profit_factor"]:
        worsened.append("profit factor")
    if new_m["max_drawdown"] > old_m["max_drawdown"]:
        worsened.append("max drawdown")
    if new_m["sharpe"] < old_m["sharpe"]:
        worsened.append("risk-adjusted return")

    passed = not worsened
    return {
        "passed": passed,
        "reason": ("Out-of-sample check passed — the proposed model does not "
                   "worsen any protected metric."
                   if passed else
                   f"Rejected — the proposed model worsens: {', '.join(worsened)} "
                   f"on out-of-sample data."),
        "oos_trades": len(oos), "oos_scope_trades": n_scope,
        "old_model": old_m, "proposed_model": new_m,
    }


# ── Approve / reject (spec §9B) ──────────────────────────────────────────────

def _get_proposal(conn: sqlite3.Connection, adj_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM proposed_adjustments WHERE id = ?",
                       (int(adj_id),)).fetchone()
    return dict(row) if row else None


def approve_adjustment(adj_id: int) -> dict:
    """Approved Learning Mode: validate out-of-sample, then apply via a new
    model version. Validation failure auto-rejects."""
    conn = _connect()
    try:
        p = _get_proposal(conn, adj_id)
        if not p:
            return {"success": False, "message": f"Adjustment {adj_id} not found."}
        if p["status"] != "PROPOSED":
            return {"success": False,
                    "message": f"Adjustment {adj_id} is already {p['status']}."}

        validation = validate_proposal(p)
        now = datetime.now().isoformat()
        if not validation["passed"]:
            conn.execute(
                "UPDATE proposed_adjustments SET status = 'REJECTED', "
                "validation = ?, decided_at = ? WHERE id = ?",
                (json.dumps(validation), now, int(adj_id)))
            conn.commit()
            return {"success": False, "status": "REJECTED",
                    "message": validation["reason"], "validation": validation}

        from model_versioning import apply_update
        scope = f"{p['scope_type']}|{p['scope_key']}"
        result = apply_update(
            {scope: float(p["points"])},
            reason=p["reason"],
            sample_size=int(p["sample_size"] or 0),
            expected_impact=(f"{p['points']:+.1f} confidence points for "
                             f"{p['scope_type']} '{p['scope_key']}'"))
        if not result.get("applied"):
            conn.execute(
                "UPDATE proposed_adjustments SET status = 'REJECTED', "
                "validation = ?, decided_at = ? WHERE id = ?",
                (json.dumps({"passed": False, "reason": result.get("message")}),
                 now, int(adj_id)))
            conn.commit()
            return {"success": False, "status": "REJECTED",
                    "message": result.get("message", "Cap reached.")}

        conn.execute(
            "UPDATE proposed_adjustments SET status = 'APPLIED', validation = ?, "
            "decided_at = ?, applied_version = ? WHERE id = ?",
            (json.dumps(validation), now, result["version"], int(adj_id)))
        conn.commit()
        return {"success": True, "status": "APPLIED",
                "model_version": result["version"],
                "message": (f"Applied {p['points']:+.1f} points to "
                            f"{p['scope_type']} '{p['scope_key']}' — model "
                            f"version {result['version']} created."),
                "validation": validation}
    finally:
        conn.close()


def reject_adjustment(adj_id: int) -> dict:
    conn = _connect()
    try:
        p = _get_proposal(conn, adj_id)
        if not p:
            return {"success": False, "message": f"Adjustment {adj_id} not found."}
        if p["status"] != "PROPOSED":
            return {"success": False,
                    "message": f"Adjustment {adj_id} is already {p['status']}."}
        conn.execute(
            "UPDATE proposed_adjustments SET status = 'REJECTED', decided_at = ? "
            "WHERE id = ?", (datetime.now().isoformat(), int(adj_id)))
        conn.commit()
        return {"success": True, "status": "REJECTED",
                "message": f"Adjustment {adj_id} rejected — nothing was applied."}
    finally:
        conn.close()


def get_adjustments(include_decided: bool = True) -> list[dict]:
    conn = _connect()
    try:
        q = "SELECT * FROM proposed_adjustments ORDER BY id DESC LIMIT 100"
        rows = conn.execute(q).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("evidence", "validation"):
            try:
                d[k] = json.loads(d.get(k) or "null")
            except Exception:
                d[k] = None
        if include_decided or d["status"] == "PROPOSED":
            out.append(d)
    return out


# ── Learning Review payload (spec §12) ───────────────────────────────────────

def _hypotheses_safe() -> list[dict]:
    try:
        import hypothesis_engine
        return hypothesis_engine.get_hypotheses()
    except Exception:
        return []


def learning_review() -> dict:
    import trade_evaluator
    trade_evaluator.backfill_evaluations()

    all_evals = trade_evaluator.get_evaluation_with_snapshot(limit=500)
    eligible = [e for e in all_evals if int(e.get("learn_eligible") or 0) == 1]

    successful = sum(1 for e in all_evals if e.get("direction_correct"))
    failed = len(all_evals) - successful
    pred_errs = [_f(e.get("prediction_error")) for e in all_evals
                 if e.get("prediction_error") is not None]
    avg_pred_err = round(sum(pred_errs) / len(pred_errs), 2) if pred_errs else None

    bands = calibration_bands(eligible)
    cal_score = calibration_score(bands)

    # Most common failure causes / strongest success factors
    cause_counts: dict[str, dict] = {}
    factor_counts: dict[str, dict] = {}
    for e in all_evals:
        for c in (e.get("failure_causes") or []):
            k = c.get("cause", "Unknown")
            cc = cause_counts.setdefault(k, {"cause": k, "count": 0, "example": c.get("evidence", "")})
            cc["count"] += 1
        for f in (e.get("success_factors") or []):
            k = f.get("factor", "Unknown")
            fc = factor_counts.setdefault(k, {"factor": k, "count": 0, "example": f.get("evidence", "")})
            fc["count"] += 1

    from model_versioning import get_versions, get_active_version, compute_post_performance
    versions = get_versions()
    for v in versions:
        v["post_performance"] = compute_post_performance(v["version"])
    active = get_active_version()

    # Trim evaluation payload for the review table
    trades_out = []
    for e in all_evals:
        snap = e.get("snapshot") or {}
        trades_out.append({
            "trade_id": e.get("trade_id"), "symbol": e.get("symbol"),
            "sector": e.get("sector"), "entry_time": e.get("entry_time"),
            "exit_time": e.get("exit_time"),
            "entry_price": e.get("entry_price"), "exit_price": e.get("exit_price"),
            "exit_type": e.get("exit_type"),
            "predicted_confidence": e.get("predicted_confidence"),
            "expected_return": e.get("expected_return"),
            "actual_return": e.get("actual_return"),
            "prediction_error": e.get("prediction_error"),
            "actual_holding_days": e.get("actual_holding_days"),
            "expected_holding_days": snap.get("expected_holding_days"),
            "mfe": e.get("mfe"), "mae": e.get("mae"),
            "stop_hit": bool(e.get("stop_hit")), "target_hit": bool(e.get("target_hit")),
            "direction_correct": bool(e.get("direction_correct")),
            "outcome_class": e.get("outcome_class"),
            "failure_causes": e.get("failure_causes") or [],
            "success_factors": e.get("success_factors") or [],
            "lesson": e.get("lesson") or "",
            "learn_eligible": bool(e.get("learn_eligible")),
            "data_source": e.get("data_source"),
            "model_version": e.get("model_version"),
            "strategy_name": snap.get("strategy_name"),
            "recommendation": snap.get("recommendation"),
            "pattern_matched": snap.get("pattern_matched"),
            "reliability_level": snap.get("reliability_level"),
        })

    notes = []
    if len(eligible) < MIN_SYMBOL_TRADES:
        notes.append(WARN_SAMPLE)

    return {
        "generated_at": datetime.now().isoformat(),
        "mode": "analysis",
        "active_model_version": active["version"],
        "active_weights": active["weights"],
        "trades_evaluated": len(all_evals),
        "learn_eligible_trades": len(eligible),
        "successful_predictions": successful,
        "failed_predictions": failed,
        "avg_prediction_error": avg_pred_err,
        "calibration_score": cal_score,
        "calibration_bands": bands,
        "common_failure_causes": sorted(cause_counts.values(),
                                        key=lambda c: c["count"], reverse=True)[:10],
        "strongest_success_factors": sorted(factor_counts.values(),
                                            key=lambda f: f["count"], reverse=True)[:10],
        "proposed_adjustments": get_adjustments(),
        "hypotheses": _hypotheses_safe(),
        "model_versions": versions,
        "trades": trades_out,
        "warnings": [WARN_LEARNING] + notes,
    }
