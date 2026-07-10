"""
Model Versioning — Version 2.0 Adaptive Self-Evaluation (Module 4).

Every APPLIED learning update creates a new model version storing the
previous weights, the new weights, the reason, supporting sample size and
expected impact. Rollback restores the prior version. All weights are
bounded confidence-point modifiers — they can NEVER change strategy logic,
entry/exit rules, or hard risk filters.

Weight format: { "<scope_type>|<scope_key>": points }
  e.g. { "strategy|ema_cross": -3.0, "sector|IT": 2.0 }

Hard limits (spec §7):
  MAX_STEP  = 3  points per learning cycle per scope
  MAX_TOTAL = 15 points total per scope (±)

PAPER TRADING ONLY — research tool, never places orders.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

import trade_intelligence as _ti

# Tests may monkeypatch this to point at a temp DB.
DB_PATH = _ti.DB_PATH

MAX_STEP = 3.0
MAX_TOTAL = 15.0

_SCHEMA = """
CREATE TABLE IF NOT EXISTS model_versions (
    version          INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at       TEXT,
    previous_weights TEXT,
    new_weights      TEXT,
    reason           TEXT,
    sample_size      INTEGER,
    expected_impact  TEXT,
    status           TEXT,      -- ACTIVE | ROLLED_BACK
    post_performance TEXT
);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(_SCHEMA)
    conn.commit()
    return conn


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


# ── Active version + weights ─────────────────────────────────────────────────

def get_active_version() -> dict:
    """Highest non-rolled-back version. Version 0 = baseline (no weights)."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT * FROM model_versions WHERE status = 'ACTIVE' "
            "ORDER BY version DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    if not row:
        return {"version": 0, "weights": {}, "created_at": None, "reason": "baseline"}
    d = dict(row)
    try:
        weights = json.loads(d.get("new_weights") or "{}")
    except Exception:
        weights = {}
    return {"version": d["version"], "weights": weights,
            "created_at": d.get("created_at"), "reason": d.get("reason")}


def get_versions() -> list[dict]:
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM model_versions ORDER BY version DESC").fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        d = dict(r)
        for k in ("previous_weights", "new_weights", "post_performance"):
            try:
                d[k] = json.loads(d.get(k) or ("{}" if k != "post_performance" else "null"))
            except Exception:
                d[k] = {}
        out.append(d)
    return out


# ── Apply a learning update (creates a version) ──────────────────────────────

def apply_update(delta: dict[str, float], reason: str, sample_size: int,
                 expected_impact: str) -> dict:
    """Apply a bounded weight delta on top of the active weights and create
    a new ACTIVE model version. Per-scope step is clamped to ±MAX_STEP and
    the resulting total per scope to ±MAX_TOTAL."""
    active = get_active_version()
    prev = dict(active["weights"])
    new = dict(prev)

    applied_delta: dict[str, float] = {}
    for scope, points in (delta or {}).items():
        step = _clamp(float(points), -MAX_STEP, MAX_STEP)
        total = _clamp(prev.get(scope, 0.0) + step, -MAX_TOTAL, MAX_TOTAL)
        actual_step = round(total - prev.get(scope, 0.0), 1)
        if actual_step == 0.0:
            continue
        new[scope] = round(total, 1)
        applied_delta[scope] = actual_step

    if not applied_delta:
        return {"applied": False, "version": active["version"],
                "message": "No change — every scope already at its ±15 point cap."}

    conn = _connect()
    try:
        cur = conn.execute(
            "INSERT INTO model_versions (created_at, previous_weights, "
            "new_weights, reason, sample_size, expected_impact, status) "
            "VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE')",
            (datetime.now().isoformat(), json.dumps(prev), json.dumps(new),
             reason, int(sample_size), expected_impact))
        conn.commit()
        version = cur.lastrowid
    finally:
        conn.close()
    return {"applied": True, "version": version, "weights": new,
            "applied_delta": applied_delta}


# ── Rollback ──────────────────────────────────────────────────────────────────

def rollback(version: int) -> dict:
    """Roll back a model version (and any later ones, so the weight history
    stays consistent). The previous surviving version becomes active."""
    conn = _connect()
    try:
        exists = conn.execute(
            "SELECT version FROM model_versions WHERE version = ?",
            (int(version),)).fetchone()
        if not exists:
            return {"success": False, "message": f"Version {version} not found."}
        conn.execute(
            "UPDATE model_versions SET status = 'ROLLED_BACK' "
            "WHERE version >= ? AND status = 'ACTIVE'", (int(version),))
        conn.commit()
    finally:
        conn.close()
    active = get_active_version()
    return {"success": True,
            "message": f"Rolled back to model version {active['version']}.",
            "active_version": active["version"], "weights": active["weights"]}


# ── Modifier lookup used by the Decision Service ─────────────────────────────

def modifier_for(context: dict, weights: dict | None = None) -> tuple[float, list[str]]:
    """Total learning modifier for a decision context, clamped to ±MAX_TOTAL.
    Context keys: strategy_id, symbol, sector, regime, pattern,
    confidence_band. Returns (points, list of applied scope strings)."""
    if weights is None:
        weights = get_active_version()["weights"]
    if not weights:
        return 0.0, []

    keys = []
    if context.get("strategy_id"):
        keys.append(f"strategy|{str(context['strategy_id']).strip().lower()}")
    if context.get("symbol"):
        keys.append(f"symbol|{str(context['symbol']).upper()}")
    if context.get("sector"):
        keys.append(f"sector|{str(context['sector']).upper()}")
    if context.get("regime"):
        keys.append(f"regime|{context['regime']}")
    if context.get("pattern"):
        keys.append(f"pattern|{context['pattern']}")
    if context.get("confidence_band"):
        keys.append(f"confidence_band|{context['confidence_band']}")

    total, applied = 0.0, []
    for k in keys:
        if k in weights and weights[k] != 0:
            total += float(weights[k])
            applied.append(f"{k}: {weights[k]:+.1f}")
    return round(_clamp(total, -MAX_TOTAL, MAX_TOTAL), 1), applied


def confidence_band(conf) -> str:
    try:
        c = float(conf)
    except (TypeError, ValueError):
        return ""
    if c < 50:
        return "below-50"
    if c < 60:
        return "50-59"
    if c < 70:
        return "60-69"
    if c < 80:
        return "70-79"
    if c < 90:
        return "80-89"
    return "90-95"


# ── Post-deployment performance tracking ─────────────────────────────────────

def compute_post_performance(version: int) -> dict:
    """Actual paper-trade performance recorded while `version` was the model
    at entry (learn-eligible trades only)."""
    conn = _connect()
    try:
        try:
            rows = conn.execute(
                "SELECT actual_return, actual_holding_days, exit_time FROM "
                "trade_evaluations WHERE model_version = ? AND learn_eligible = 1",
                (int(version),)).fetchall()
        except sqlite3.OperationalError:
            return {"trades": 0}
    finally:
        conn.close()
    if not rows:
        return {"trades": 0}
    from expectancy import compute_metrics
    trades = [{"return_percent": r["actual_return"],
               "holding_days": r["actual_holding_days"],
               "exit_date": r["exit_time"]} for r in rows]
    m = compute_metrics(trades)
    return {"trades": m["trades"], "win_rate": m["win_rate"],
            "expectancy": m["expectancy"], "profit_factor": m["profit_factor"],
            "average_return": m["average_return"], "max_drawdown": m["max_drawdown"]}
