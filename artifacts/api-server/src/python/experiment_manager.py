"""
experiment_manager.py — Phase 4 Research Factory: Experiment Manager.
v1.0

Manages a queue of walk-forward validation experiments with different
configs, date ranges, and strategy variants.  Builds a ranked leaderboard
scored by objective metrics (profit factor, expectancy, Sharpe, drawdown,
calibration quality, evidence quality).  Auto-rejects experiments whose
metrics indicate overfitting.

Design:
  - Each experiment is a walk-forward validation run stored in its own
    experiments/<id>/ directory (isolated from validation_runs/).
  - Output redirection is done via module-level patching of
    walk_forward_validator.VALIDATION_DIR (and related paths) so the
    existing validator writes to the experiment directory without
    modification.  Globals are always restored in a finally block.
  - Experiments run one at a time (concurrency enforced by the Node.js
    route layer and a running-experiment check here).
  - No look-ahead bias: every experiment uses the same strict train/test
    split logic as the main walk-forward validator.

READ-ONLY operations: list_experiments, get_experiment, get_leaderboard.
WRITE operations: submit_experiment, run_experiment, delete_experiment.
Paper trading and research only — no real orders are placed.
"""
from __future__ import annotations

import json
import os
import shutil
import uuid
from datetime import datetime

PYTHON_DIR = os.path.dirname(os.path.abspath(__file__))
EXPERIMENTS_DIR = os.path.join(PYTHON_DIR, "experiments")

SAFETY_NOTE = (
    "Out-of-sample historical performance does not guarantee future results. "
    "Paper trading and research only. No real orders are placed."
)

# ── Leaderboard scoring ────────────────────────────────────────────────────────

def _score_pf(pf) -> float:
    """Profit factor → 0–25 pts."""
    try:
        pf = float(pf)
    except (TypeError, ValueError):
        return 0.0
    if pf <= 1.00: return 0.0
    if pf <= 1.15: return 5.0
    if pf <= 1.30: return 10.0
    if pf <= 1.50: return 15.0
    if pf <= 2.00: return 20.0
    return min(25.0, 20.0 + (pf - 2.0) * 5.0)

def _score_expectancy(exp_val) -> float:
    """Expectancy (₹/trade) → 0–20 pts."""
    try:
        v = float(exp_val)
    except (TypeError, ValueError):
        return 0.0
    if v <= 0:   return 0.0
    if v <= 50:  return 5.0
    if v <= 100: return 10.0
    if v <= 200: return 15.0
    return 20.0

def _score_sharpe(sharpe) -> float:
    """Sharpe ratio → 0–20 pts."""
    try:
        v = float(sharpe)
    except (TypeError, ValueError):
        return 0.0
    if v <= 0.0:  return 0.0
    if v <= 0.5:  return 5.0
    if v <= 1.0:  return 10.0
    if v <= 1.5:  return 15.0
    return min(20.0, 15.0 + (v - 1.5) * 10.0)

def _score_drawdown(dd) -> float:
    """Max drawdown % → 0–15 pts (lower drawdown = higher score)."""
    try:
        v = abs(float(dd))
    except (TypeError, ValueError):
        return 0.0
    if v >= 30.0: return 0.0
    if v >= 20.0: return 5.0
    if v >= 15.0: return 8.0
    if v >= 10.0: return 11.0
    return 15.0

def _score_ece(ece) -> float:
    """Calibration ECE → 0–10 pts (lower ECE = better)."""
    try:
        v = float(ece)
    except (TypeError, ValueError):
        return 0.0
    if v >= 0.15: return 0.0
    if v >= 0.10: return 3.0
    if v >= 0.05: return 6.0
    return 10.0

def _score_evidence(ev_verdict) -> float:
    """Evidence expansion verdict → 0–10 pts."""
    return {"PASS": 10.0, "INCONCLUSIVE": 5.0,
            "INSUFFICIENT_EVIDENCE": 2.0, "FAIL": 0.0}.get(str(ev_verdict), 0.0)

def _compute_score(result: dict) -> dict:
    overall  = result.get("overall") or {}
    full     = overall.get("full_metrics") or {}
    calib    = result.get("calibration_report") or {}
    ev       = result.get("evidence_expansion") or {}
    ev_verd  = (ev.get("verdict") or {}).get("verdict")

    breakdown = {
        "profit_factor": round(_score_pf(full.get("profit_factor")), 1),
        "expectancy":    round(_score_expectancy(full.get("expectancy")), 1),
        "sharpe":        round(_score_sharpe(full.get("sharpe_ratio")), 1),
        "drawdown":      round(_score_drawdown(full.get("max_drawdown_pct")), 1),
        "calibration":   round(_score_ece(calib.get("ece")), 1),
        "evidence":      round(_score_evidence(ev_verd), 1),
    }
    total = round(sum(breakdown.values()), 1)
    return {"total": total, "max_possible": 100, "breakdown": breakdown}


# ── Overfitting detection ─────────────────────────────────────────────────────

def _check_overfitting(result: dict) -> tuple[bool, list[str]]:
    """
    Returns (auto_rejected: bool, flags: list[str]).

    Hard flags (any single one triggers rejection):
      - win_rate > 82%
      - profit_factor > 5.0
      - total_trades < 25
      - sharpe > 4.5
      - windows < 2

    Soft flags (3 or more trigger rejection, shown as warnings otherwise):
      - win_rate > 70%
      - profit_factor > 3.0
      - trades < 50
      - return_dispersion > 25%
    """
    overall = result.get("overall") or {}
    full    = overall.get("full_metrics") or {}
    stab    = result.get("stability") or {}

    def _f(v): 
        try: return float(v or 0)
        except (TypeError, ValueError): return 0.0

    pf          = _f(full.get("profit_factor"))
    win_rate    = _f(full.get("win_rate"))
    trades      = int(_f(full.get("total_trades")))
    sharpe      = _f(full.get("sharpe_ratio"))
    windows     = len([w for w in (result.get("windows") or []) if not w.get("failed")])
    dispersion  = _f(stab.get("return_dispersion"))

    hard_flags: list[str] = []
    if win_rate > 82:
        hard_flags.append(f"win_rate_anomaly ({win_rate:.1f}% > 82% hard limit)")
    if pf > 5.0:
        hard_flags.append(f"profit_factor_anomaly ({pf:.2f} > 5.0 hard limit)")
    if trades < 25:
        hard_flags.append(f"insufficient_oos_trades ({trades} < 25 hard limit)")
    if sharpe > 4.5:
        hard_flags.append(f"sharpe_anomaly ({sharpe:.2f} > 4.5 hard limit)")
    if windows < 2:
        hard_flags.append(f"insufficient_windows ({windows} < 2 hard limit)")
    if hard_flags:
        return True, hard_flags

    soft_flags: list[str] = []
    if win_rate > 70:
        soft_flags.append(f"win_rate_elevated ({win_rate:.1f}% > 70%)")
    if pf > 3.0:
        soft_flags.append(f"profit_factor_elevated ({pf:.2f} > 3.0)")
    if trades < 50:
        soft_flags.append(f"trades_low ({trades} < 50)")
    if dispersion > 25.0:
        soft_flags.append(f"return_dispersion_high ({dispersion:.1f}% > 25%)")
    if len(soft_flags) >= 3:
        return True, soft_flags

    return False, soft_flags


# ── Headline metrics extraction ───────────────────────────────────────────────

def _extract_headline(result: dict) -> dict:
    overall = result.get("overall") or {}
    full    = overall.get("full_metrics") or {}
    calib   = result.get("calibration_report") or {}
    ev      = result.get("evidence_expansion") or {}

    def _f(v):
        try: return round(float(v), 4)
        except (TypeError, ValueError): return None

    return {
        "total_trades":    full.get("total_trades"),
        "total_return_pct": _f(full.get("total_return_pct")),
        "net_pnl":         _f(full.get("net_profit")),
        "win_rate":        _f(full.get("win_rate")),
        "profit_factor":   _f(full.get("profit_factor")),
        "expectancy":      _f(full.get("expectancy")),
        "sharpe":          _f(full.get("sharpe_ratio")),
        "max_drawdown_pct": _f(full.get("max_drawdown_pct")),
        "brier_score":     _f(calib.get("brier_score")),
        "ece":             _f(calib.get("ece")),
        "ev_verdict":      (ev.get("verdict") or {}).get("verdict"),
        "ev_trades":       ev.get("n_trades"),
        "windows":         len([w for w in (result.get("windows") or []) if not w.get("failed")]),
        "generated_at":    result.get("generated_at"),
        "run_seconds":     result.get("run_seconds"),
        "verdict":         (result.get("verdict") or {}).get("verdict"),
        "universe_size":   result.get("universe_size"),
    }


# ── Path helpers ──────────────────────────────────────────────────────────────

def _exp_dir(exp_id: str) -> str:
    return os.path.join(EXPERIMENTS_DIR, exp_id)

def _status_path(exp_id: str) -> str:
    return os.path.join(_exp_dir(exp_id), "status.json")

def _config_path(exp_id: str) -> str:
    return os.path.join(_exp_dir(exp_id), "config.json")

def _result_path(exp_id: str) -> str:
    return os.path.join(_exp_dir(exp_id), "wf_result.json")

def _read_status(exp_id: str) -> dict:
    p = _status_path(exp_id)
    if not os.path.exists(p):
        return {}
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return {}

def _write_status(exp_id: str, payload: dict) -> None:
    p   = _status_path(exp_id)
    tmp = p + ".tmp"
    with open(tmp, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    os.replace(tmp, p)

def _read_config(exp_id: str) -> dict:
    p = _config_path(exp_id)
    if not os.path.exists(p):
        return {}
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return {}


# ── Experiment CRUD ───────────────────────────────────────────────────────────

def list_experiments() -> dict:
    """List all experiments sorted by created_at descending."""
    if not os.path.exists(EXPERIMENTS_DIR):
        return {"experiments": [], "total": 0}

    experiments = []
    for exp_id in os.listdir(EXPERIMENTS_DIR):
        d = _exp_dir(exp_id)
        if not os.path.isdir(d):
            continue
        status = _read_status(exp_id)
        if not status:
            continue

        # If running, attach wf_progress from the experiment's own status file
        if status.get("status") == "running":
            wf_sp = os.path.join(d, "wf_status.json")
            if os.path.exists(wf_sp):
                try:
                    with open(wf_sp) as f:
                        status["wf_progress"] = json.load(f)
                except Exception:
                    pass

        experiments.append(status)

    experiments.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return {"experiments": experiments, "total": len(experiments)}


def submit_experiment(config: dict) -> dict:
    """Submit a new experiment to the queue."""
    exp_id = uuid.uuid4().hex[:12]
    os.makedirs(_exp_dir(exp_id), exist_ok=True)

    # Store config (strip any result data the caller may have injected)
    safe_config = {k: v for k, v in config.items()
                   if k not in ("result", "score", "metrics", "overfitting_flags")}
    with open(_config_path(exp_id), "w") as f:
        json.dump(safe_config, f, indent=2)

    now = datetime.now().isoformat()
    payload = {
        "id":          exp_id,
        "status":      "queued",
        "created_at":  now,
        "updated_at":  now,
        "name":        safe_config.get("name", "Unnamed Experiment"),
        "description": safe_config.get("description", ""),
        "tags":        safe_config.get("tags", []),
        "config_summary": {
            "train_years":  safe_config.get("train_years", 1),
            "test_months":  safe_config.get("test_months", 3),
            "step_months":  safe_config.get("step_months", 3),
            "start_date":   safe_config.get("start_date", ""),
            "end_date":     safe_config.get("end_date", ""),
            "universe_size": safe_config.get("universe_size", 0),
            "intrabar_rule": safe_config.get("intrabar_rule", "conservative"),
            "max_holding_days": safe_config.get("max_holding_days", 20),
        },
    }
    _write_status(exp_id, payload)
    return {"ok": True, "id": exp_id, "status": "queued"}


def run_experiment(exp_id: str) -> dict:
    """
    Execute a queued experiment (call from a detached background process).

    Patches walk_forward_validator (and evidence_expansion) module globals to
    redirect all output files to the experiment's own directory, then restores
    them unconditionally in a finally block.  The experiment remains isolated
    from validation_runs/ so the main Walk-Forward result is never overwritten.
    """
    status = _read_status(exp_id)
    if not status:
        return {"error": f"Experiment {exp_id} not found"}
    # "running" is allowed because the Node.js layer writes a placeholder
    # "running" status immediately before spawning this process.
    if status.get("status") not in ("queued", "failed", "running"):
        return {"error": f"Experiment {exp_id} is not runnable "
                         f"(current status: {status.get('status')})"}

    config = _read_config(exp_id)
    if not config:
        return {"error": f"Config not found for experiment {exp_id}"}

    exp_out = _exp_dir(exp_id)
    os.makedirs(exp_out, exist_ok=True)

    now = datetime.now().isoformat()
    _write_status(exp_id, {
        **status,
        "status":     "running",
        "pid":        os.getpid(),
        "started_at": now,
        "updated_at": now,
    })

    import walk_forward_validator as wfv
    try:
        import evidence_expansion as ee
        _has_ee = True
    except ImportError:
        _has_ee = False
        ee = None  # type: ignore[assignment]

    # ── Patch output globals ───────────────────────────────────────────────
    orig_vdir  = wfv.VALIDATION_DIR
    orig_sp    = wfv.STATUS_PATH
    orig_rp    = wfv.RESULT_PATH
    orig_ee    = getattr(ee, "VALIDATION_DIR", None) if _has_ee else None

    wfv.VALIDATION_DIR = exp_out
    wfv.STATUS_PATH    = os.path.join(exp_out, "wf_status.json")
    wfv.RESULT_PATH    = os.path.join(exp_out, "wf_result.json")
    if _has_ee:
        ee.VALIDATION_DIR = exp_out  # type: ignore[union-attr]

    try:
        # Strip experiment-only keys before passing to ValidationConfig
        EXPERIMENT_KEYS = {"name", "description", "tags"}
        wf_config = {k: v for k, v in config.items() if k not in EXPERIMENT_KEYS}

        result = wfv.run_validation(wf_config)

        score_info = _compute_score(result)
        auto_rejected, flags = _check_overfitting(result)
        final_status = "rejected" if auto_rejected else "completed"
        headline = _extract_headline(result)

        now = datetime.now().isoformat()
        _write_status(exp_id, {
            **_read_status(exp_id),
            "status":           final_status,
            "completed_at":     now,
            "updated_at":       now,
            "verdict":          headline.get("verdict"),
            "score":            score_info["total"],
            "score_breakdown":  score_info["breakdown"],
            "overfitting_flags": flags,
            "auto_rejected":    auto_rejected,
            "metrics":          headline,
        })

        return {
            "ok":           True,
            "id":           exp_id,
            "status":       final_status,
            "score":        score_info["total"],
            "auto_rejected": auto_rejected,
        }

    except Exception as exc:
        import traceback
        now = datetime.now().isoformat()
        _write_status(exp_id, {
            **_read_status(exp_id),
            "status":     "failed",
            "failed_at":  now,
            "updated_at": now,
            "error":      str(exc),
            "trace":      traceback.format_exc()[:2000],
        })
        return {"error": str(exc), "id": exp_id, "status": "failed"}

    finally:
        # ── Always restore module globals ──────────────────────────────────
        wfv.VALIDATION_DIR = orig_vdir
        wfv.STATUS_PATH    = orig_sp
        wfv.RESULT_PATH    = orig_rp
        if _has_ee and orig_ee is not None:
            ee.VALIDATION_DIR = orig_ee  # type: ignore[union-attr]


def get_experiment(exp_id: str) -> dict:
    """Get the full status (and result if complete) for one experiment."""
    status = _read_status(exp_id)
    if not status:
        return {"error": f"Experiment {exp_id} not found"}

    if status.get("status") == "running":
        wf_sp = os.path.join(_exp_dir(exp_id), "wf_status.json")
        if os.path.exists(wf_sp):
            try:
                with open(wf_sp) as f:
                    status["wf_progress"] = json.load(f)
            except Exception:
                pass

    if status.get("status") in ("completed", "rejected"):
        rp = _result_path(exp_id)
        if os.path.exists(rp):
            try:
                with open(rp) as f:
                    status["result"] = json.load(f)
            except Exception:
                pass

    return status


def get_leaderboard() -> dict:
    """
    Return all completed/rejected experiments ranked by composite score.
    Rejected experiments appear at the bottom regardless of score.
    """
    if not os.path.exists(EXPERIMENTS_DIR):
        return {"entries": [], "total": 0, "total_all": 0}

    entries = []
    total_all = 0
    for exp_id in os.listdir(EXPERIMENTS_DIR):
        if not os.path.isdir(_exp_dir(exp_id)):
            continue
        total_all += 1
        st = _read_status(exp_id)
        if st.get("status") not in ("completed", "rejected"):
            continue
        entries.append({
            "id":               exp_id,
            "name":             st.get("name", exp_id[:8]),
            "description":      st.get("description", ""),
            "tags":             st.get("tags", []),
            "status":           st.get("status"),
            "verdict":          st.get("verdict"),
            "score":            st.get("score", 0.0),
            "score_breakdown":  st.get("score_breakdown", {}),
            "overfitting_flags": st.get("overfitting_flags", []),
            "auto_rejected":    st.get("auto_rejected", False),
            "metrics":          st.get("metrics", {}),
            "config_summary":   st.get("config_summary", {}),
            "completed_at":     st.get("completed_at", ""),
            "created_at":       st.get("created_at", ""),
        })

    # Non-rejected sorted by score desc; rejected at bottom sorted by score desc
    entries.sort(
        key=lambda x: (1 if x.get("auto_rejected") else 0, -(x.get("score") or 0))
    )

    return {"entries": entries, "total": len(entries), "total_all": total_all}


def delete_experiment(exp_id: str) -> dict:
    """Delete an experiment and all its data (irreversible)."""
    d = _exp_dir(exp_id)
    if not os.path.exists(d):
        return {"error": f"Experiment {exp_id} not found"}
    st = _read_status(exp_id)
    if st.get("status") == "running":
        return {"error": "Cannot delete a running experiment"}
    shutil.rmtree(d)
    return {"ok": True, "id": exp_id}


def check_any_running() -> dict:
    """
    Check whether any experiment is currently marked 'running'.
    Used by the Node.js layer for concurrency checks.
    """
    if not os.path.exists(EXPERIMENTS_DIR):
        return {"running": False}
    for exp_id in os.listdir(EXPERIMENTS_DIR):
        if not os.path.isdir(_exp_dir(exp_id)):
            continue
        st = _read_status(exp_id)
        if st.get("status") == "running":
            return {"running": True, "id": exp_id}
    return {"running": False}
