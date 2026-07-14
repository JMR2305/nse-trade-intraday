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
import threading
import time
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

def _heartbeat_path(exp_id: str) -> str:
    return os.path.join(_exp_dir(exp_id), "heartbeat.json")

def _exec_log_path(exp_id: str) -> str:
    return os.path.join(_exp_dir(exp_id), "exec_log.json")

def _runner_log_path(exp_id: str) -> str:
    return os.path.join(_exp_dir(exp_id), "runner.log")


HEARTBEAT_INTERVAL_S = 5
HEARTBEAT_STALE_S = 30


def _log_stage(exp_id: str, msg: str) -> None:
    """Append a timestamped stage event to the experiment's execution log."""
    p = _exec_log_path(exp_id)
    log: list = []
    try:
        if os.path.exists(p):
            with open(p) as f:
                log = json.load(f)
    except Exception:
        log = []
    log.append({"ts": datetime.now().isoformat(timespec="seconds"), "msg": msg})
    log = log[-100:]
    tmp = p + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump(log, f, indent=1)
        os.replace(tmp, p)
    except Exception:
        pass


def _read_exec_log(exp_id: str) -> list:
    try:
        with open(_exec_log_path(exp_id)) as f:
            return json.load(f)
    except Exception:
        return []


def _write_heartbeat(exp_id: str) -> None:
    p = _heartbeat_path(exp_id)
    tmp = p + ".tmp"
    try:
        with open(tmp, "w") as f:
            json.dump({"ts": time.time(), "pid": os.getpid(),
                       "at": datetime.now().isoformat(timespec="seconds")}, f)
        os.replace(tmp, p)
    except Exception:
        pass


def _start_heartbeat(exp_id: str) -> threading.Event:
    """Background thread that refreshes heartbeat.json every few seconds."""
    stop = threading.Event()

    def _beat():
        while not stop.is_set():
            _write_heartbeat(exp_id)
            stop.wait(HEARTBEAT_INTERVAL_S)

    t = threading.Thread(target=_beat, daemon=True, name=f"heartbeat-{exp_id}")
    t.start()
    return stop


def _heartbeat_age(exp_id: str) -> float | None:
    """Seconds since last heartbeat, or None if no heartbeat file exists."""
    try:
        with open(_heartbeat_path(exp_id)) as f:
            hb = json.load(f)
        return max(0.0, time.time() - float(hb.get("ts", 0)))
    except Exception:
        return None


def _runner_log_tail(exp_id: str, max_chars: int = 800) -> str:
    try:
        with open(_runner_log_path(exp_id), "r", errors="replace") as f:
            data = f.read()
        return data[-max_chars:].strip()
    except Exception:
        return ""

def _pid_alive(pid) -> bool:
    """True only if the PID exists AND is actually an experiment runner.

    A bare os.kill(pid, 0) check is unsafe: after a crash/restart the PID can
    be reused by an unrelated process, leaving a dead run stuck at 'running'.
    """
    try:
        pid = int(pid)
        if pid <= 0:
            return False
        os.kill(pid, 0)
    except (TypeError, ValueError, ProcessLookupError):
        return False
    except PermissionError:
        pass  # exists; verify identity below
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as f:
            cmdline = f.read().replace(b"\0", b" ").decode("utf-8", "replace")
    except Exception:
        return False
    return ("experiment_run" in cmdline or "main.py" in cmdline) and "python" in cmdline.lower()


def _reconcile_stale(exp_id: str, status: dict) -> dict:
    """If a status says 'running' but the runner process is gone, mark it failed.

    A grace period protects the placeholder written just before spawn
    (which may briefly lack a live PID).
    """
    if status.get("status") != "running":
        return status

    hb_age = _heartbeat_age(exp_id)
    pid_ok = _pid_alive(status.get("pid"))

    # Healthy if the heartbeat is fresh, or (no heartbeat file yet) PID is alive
    if hb_age is not None and hb_age <= HEARTBEAT_STALE_S:
        return status
    if hb_age is None and pid_ok:
        return status

    # Startup grace period: only when no heartbeat was ever written (runner
    # may still be booting). Once a heartbeat exists, the 30s stale rule wins.
    if hb_age is None:
        started = status.get("started_at") or status.get("updated_at") or ""
        try:
            started_dt = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
            age = (datetime.now(started_dt.tzinfo) - started_dt).total_seconds()
            if age < 120:
                return status
        except Exception:
            pass

    if hb_age is not None and hb_age > HEARTBEAT_STALE_S:
        reason = (f"Heartbeat stopped {int(hb_age)}s ago (limit {HEARTBEAT_STALE_S}s) — "
                  "the runner process died without reporting an error. Most likely "
                  "killed by the OS (out-of-memory) or a server/workflow restart.")
    else:
        reason = ("Runner process is no longer alive and never wrote a completion "
                  "status — likely killed by a server restart or out-of-memory.")

    log_tail = _runner_log_tail(exp_id)
    if log_tail:
        reason += f"\nLast runner output:\n{log_tail}"

    status["status"] = "failed"
    status["error"] = reason
    status["failed_at"] = datetime.now().isoformat()
    status["updated_at"] = datetime.now().isoformat()
    try:
        _write_status(exp_id, status)
        _log_stage(exp_id, f"failed — {reason.splitlines()[0]}")
    except Exception:
        pass
    return status


def _read_status(exp_id: str) -> dict:
    p = _status_path(exp_id)
    if not os.path.exists(p):
        return {}
    try:
        with open(p) as f:
            status = json.load(f)
    except Exception:
        return {}
    return _reconcile_stale(exp_id, status)

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

        status["exec_log"] = _read_exec_log(exp_id)
        experiments.append(status)

    experiments.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return {"experiments": experiments, "total": len(experiments)}


def submit_experiment(config: dict) -> dict:
    """Submit a new experiment to the queue."""
    import hashlib as _hashlib

    exp_id = uuid.uuid4().hex[:12]
    os.makedirs(_exp_dir(exp_id), exist_ok=True)

    # Store config (strip any result data the caller may have injected)
    safe_config = {k: v for k, v in config.items()
                   if k not in ("result", "score", "metrics", "overfitting_flags")}
    with open(_config_path(exp_id), "w") as f:
        json.dump(safe_config, f, indent=2)

    # Canonical config for duplicate detection (stored in status.json)
    canonical = {
        "train_years":             int(safe_config.get("train_years") or 1),
        "test_months":             int(safe_config.get("test_months") or 3),
        "step_months":             int(safe_config.get("step_months") or 3),
        "start_date":              str(safe_config.get("start_date") or ""),
        "end_date":                str(safe_config.get("end_date") or ""),
        "universe_size":           int(safe_config.get("universe_size") or 0),
        "intrabar_rule":           str(safe_config.get("intrabar_rule") or "conservative"),
        "max_holding_days":        int(safe_config.get("max_holding_days") or 20),
        "min_confidence_execute":  float(safe_config.get("min_confidence_execute") or 55),
    }
    config_hash = _hashlib.md5(
        json.dumps(canonical, sort_keys=True).encode()
    ).hexdigest()[:12]

    now = datetime.now().isoformat()
    payload = {
        "id":             exp_id,
        "status":         "queued",
        "created_at":     now,
        "updated_at":     now,
        "name":           safe_config.get("name", "Unnamed Experiment"),
        "description":    safe_config.get("description", ""),
        "tags":           safe_config.get("tags", []),
        "config_hash":    config_hash,
        "canonical_config": canonical,
        # Batch / template provenance
        "batch_id":       safe_config.get("batch_id", ""),
        "batch_name":     safe_config.get("batch_name", ""),
        "batch_index":    int(safe_config.get("batch_index") or 0),
        "template_id":    safe_config.get("template_id", ""),
        "template_family": safe_config.get("template_family", ""),
        "config_summary": {
            "train_years":  canonical["train_years"],
            "test_months":  canonical["test_months"],
            "step_months":  canonical["step_months"],
            "start_date":   canonical["start_date"],
            "end_date":     canonical["end_date"],
            "universe_size": canonical["universe_size"],
            "intrabar_rule": canonical["intrabar_rule"],
            "max_holding_days": canonical["max_holding_days"],
            "min_confidence_execute": canonical["min_confidence_execute"],
        },
    }
    _write_status(exp_id, payload)
    _log_stage(exp_id, f"queued — experiment \"{payload.get('name')}\" created")
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

    # Dump native tracebacks (segfault/fatal signal) to stderr → runner.log
    try:
        import faulthandler
        faulthandler.enable()
    except Exception:
        pass

    # Fresh execution log for this attempt (keep prior attempts' history)
    _log_stage(exp_id, "starting — runner process launched "
                       f"(pid {os.getpid()}, attempt at {datetime.now().isoformat(timespec='seconds')})")

    now = datetime.now().isoformat()
    _write_status(exp_id, {
        **status,
        "status":     "running",
        "pid":        os.getpid(),
        "started_at": now,
        "updated_at": now,
        "error":      None,
        "trace":      None,
    })

    _write_heartbeat(exp_id)
    hb_stop = _start_heartbeat(exp_id)

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
        EXPERIMENT_KEYS = {
            "name", "description", "tags",
            "batch_id", "batch_name", "batch_index",
            "template_id", "template_family",
        }
        wf_config = {k: v for k, v in config.items() if k not in EXPERIMENT_KEYS}

        _log_stage(exp_id, "loading data — fetching historical prices for the universe")
        result = wfv.run_validation(wf_config, on_stage=lambda m: _log_stage(exp_id, m))

        if isinstance(result, dict) and result.get("error"):
            raise RuntimeError(str(result["error"]))

        _log_stage(exp_id, "scoring — computing leaderboard score and overfitting checks")
        score_info = _compute_score(result)
        auto_rejected, flags = _check_overfitting(result)
        final_status = "rejected" if auto_rejected else "completed"
        _log_stage(exp_id, "report generation — extracting headline metrics")
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
        _log_stage(exp_id, f"completed — verdict: {headline.get('verdict')}, "
                           f"score {score_info['total']}/100"
                           + (" (auto-rejected: overfitting flags)" if auto_rejected else ""))

        return {
            "ok":           True,
            "id":           exp_id,
            "status":       final_status,
            "score":        score_info["total"],
            "auto_rejected": auto_rejected,
        }

    except BaseException as exc:
        import traceback
        trace = traceback.format_exc()
        now = datetime.now().isoformat()
        _write_status(exp_id, {
            **_read_status(exp_id),
            "status":     "failed",
            "failed_at":  now,
            "updated_at": now,
            "error":      str(exc) or type(exc).__name__,
            "trace":      trace[:4000],
        })
        _log_stage(exp_id, f"failed — {type(exc).__name__}: {str(exc)[:200]}")
        try:
            import sys
            print(trace, file=sys.stderr, flush=True)  # → runner.log
        except Exception:
            pass
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        return {"error": str(exc), "id": exp_id, "status": "failed"}

    finally:
        try:
            hb_stop.set()
        except Exception:
            pass
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

    status["exec_log"] = _read_exec_log(exp_id)
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
            "canonical_config": st.get("canonical_config", {}),
            "config_hash":      st.get("config_hash", ""),
            "batch_id":         st.get("batch_id", ""),
            "batch_name":       st.get("batch_name", ""),
            "batch_index":      st.get("batch_index", 0),
            "template_id":      st.get("template_id", ""),
            "template_family":  st.get("template_family", ""),
            "completed_at":     st.get("completed_at", ""),
            "created_at":       st.get("created_at", ""),
        })

    # Non-rejected sorted by score desc; rejected at bottom sorted by score desc
    entries.sort(
        key=lambda x: (1 if x.get("auto_rejected") else 0, -(x.get("score") or 0))
    )

    return {"entries": entries, "total": len(entries), "total_all": total_all}


# ── Phase 4.1: Batch management, duplicate detection, and export ───────────

import hashlib as _hashlib

def get_config_hash(config: dict) -> str:
    """Canonical MD5 hash of walk-forward config (for duplicate detection)."""
    canonical = {
        "train_years":            int(config.get("train_years") or 1),
        "test_months":            int(config.get("test_months") or 3),
        "step_months":            int(config.get("step_months") or 3),
        "start_date":             str(config.get("start_date") or ""),
        "end_date":               str(config.get("end_date") or ""),
        "universe_size":          int(config.get("universe_size") or 0),
        "intrabar_rule":          str(config.get("intrabar_rule") or "conservative"),
        "max_holding_days":       int(config.get("max_holding_days") or 20),
        "min_confidence_execute": float(config.get("min_confidence_execute") or 55),
    }
    return _hashlib.md5(json.dumps(canonical, sort_keys=True).encode()).hexdigest()[:12]


def check_duplicate(config: dict) -> dict:
    """
    Return any existing experiments with the same canonical config.
    Checks stored config_hash first; falls back to recomputing from config.json
    for experiments created before the hash field was added.
    """
    new_hash = get_config_hash(config)
    matches: list[dict] = []
    if not os.path.exists(EXPERIMENTS_DIR):
        return {"duplicate": False, "matches": [], "hash": new_hash}

    for exp_id in os.listdir(EXPERIMENTS_DIR):
        d = _exp_dir(exp_id)
        if not os.path.isdir(d):
            continue
        st = _read_status(exp_id)
        if not st:
            continue
        existing_hash = st.get("config_hash")
        if not existing_hash:
            cfg = _read_config(exp_id)
            existing_hash = get_config_hash(cfg) if cfg else ""
        if existing_hash == new_hash:
            matches.append({
                "id":         exp_id,
                "name":       st.get("name"),
                "status":     st.get("status"),
                "created_at": st.get("created_at"),
                "score":      st.get("score"),
            })

    return {"duplicate": len(matches) > 0, "matches": matches, "hash": new_hash}


def list_batches() -> dict:
    """
    Group experiments by batch_id.  Returns a list of batch objects each
    containing their experiments sorted by batch_index with aggregate counts.
    Only experiments with a non-empty batch_id are included.
    """
    if not os.path.exists(EXPERIMENTS_DIR):
        return {"batches": [], "total": 0}

    batches: dict[str, dict] = {}
    for exp_id in os.listdir(EXPERIMENTS_DIR):
        if not os.path.isdir(_exp_dir(exp_id)):
            continue
        st = _read_status(exp_id)
        if not st:
            continue
        batch_id = st.get("batch_id", "")
        if not batch_id:
            continue

        if batch_id not in batches:
            batches[batch_id] = {
                "id":             batch_id,
                "name":           st.get("batch_name") or f"Batch {batch_id[:6]}",
                "template_family": st.get("template_family", ""),
                "template_id":    st.get("template_id", ""),
                "experiments":    [],
            }

        batches[batch_id]["experiments"].append({
            "id":               exp_id,
            "name":             st.get("name"),
            "status":           st.get("status"),
            "batch_index":      int(st.get("batch_index") or 0),
            "score":            st.get("score"),
            "verdict":          st.get("verdict"),
            "overfitting_flags": st.get("overfitting_flags", []),
            "auto_rejected":    st.get("auto_rejected", False),
            "metrics":          st.get("metrics"),
            "created_at":       st.get("created_at", ""),
            "completed_at":     st.get("completed_at", ""),
            "started_at":       st.get("started_at", ""),
            "error":            st.get("error", ""),
            "wf_progress":      None,  # populated below for running exp
        })

    result = []
    for batch in batches.values():
        exps = sorted(batch["experiments"], key=lambda x: x.get("batch_index", 0))
        # Attach wf_progress for running experiments
        for exp in exps:
            if exp["status"] == "running":
                wsp = os.path.join(_exp_dir(exp["id"]), "wf_status.json")
                if os.path.exists(wsp):
                    try:
                        with open(wsp) as f:
                            exp["wf_progress"] = json.load(f)
                    except Exception:
                        pass

        total     = len(exps)
        completed = sum(1 for e in exps if e["status"] in ("completed", "rejected"))
        failed    = sum(1 for e in exps if e["status"] == "failed")
        running   = sum(1 for e in exps if e["status"] == "running")
        queued    = sum(1 for e in exps if e["status"] == "queued")

        if running:
            b_status = "running"
        elif queued:
            b_status = "queued"
        elif failed and completed + failed == total:
            b_status = "failed"
        elif completed + failed == total:
            b_status = "completed"
        else:
            b_status = "partial"

        dates = [e["created_at"] for e in exps if e.get("created_at")]
        batch["experiments"] = exps
        batch["total"]       = total
        batch["completed"]   = completed
        batch["failed"]      = failed
        batch["running"]     = running
        batch["queued"]      = queued
        batch["status"]      = b_status
        batch["created_at"]  = min(dates) if dates else ""
        result.append(batch)

    result.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return {"batches": result, "total": len(result)}


def get_batch(batch_id: str) -> dict:
    """Get a single batch by ID (thin wrapper around list_batches)."""
    result = list_batches()
    for batch in result["batches"]:
        if batch["id"] == batch_id:
            return batch
    return {"error": f"Batch {batch_id} not found"}


def export_experiments_csv(exp_ids_json: str | None = None) -> dict:
    """
    Generate a CSV report for the given experiment IDs (or all experiments).
    Returns {"ok": True, "csv": "<csv string>", "row_count": N}.
    """
    import csv
    import io

    exp_ids = json.loads(exp_ids_json) if exp_ids_json else None
    all_exps = list_experiments()["experiments"]
    if exp_ids:
        id_set = set(exp_ids)
        all_exps = [e for e in all_exps if e.get("id") in id_set]

    # Sort: completed/rejected by score first, others appended
    completed = [e for e in all_exps if e.get("status") in ("completed", "rejected")]
    completed.sort(key=lambda x: (1 if x.get("auto_rejected") else 0, -(x.get("score") or 0)))
    others    = [e for e in all_exps if e.get("status") not in ("completed", "rejected")]
    sorted_exps = completed + others

    headers = [
        "rank", "id", "name", "tags", "template_family", "template_id",
        "batch_id", "batch_name", "batch_index",
        "status", "verdict", "score",
        "profit_factor", "expectancy_inr", "sharpe_ratio", "max_drawdown_pct",
        "win_rate_pct", "total_trades", "total_return_pct", "net_pnl_inr",
        "calibration_ece", "brier_score",
        "evidence_verdict", "evidence_trades", "windows",
        "overfitting_flags", "auto_rejected",
        "train_years", "test_months", "step_months",
        "start_date", "end_date", "intrabar_rule",
        "max_holding_days", "min_confidence_execute",
        "created_at", "started_at", "completed_at",
        "safety_note",
    ]

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(headers)

    for rank_idx, exp in enumerate(sorted_exps):
        m  = exp.get("metrics") or {}
        cs = exp.get("config_summary") or {}
        rank = rank_idx + 1 if exp.get("status") in ("completed", "rejected") else ""
        flags = " | ".join(exp.get("overfitting_flags") or [])
        tags  = ", ".join(exp.get("tags") or [])
        w.writerow([
            rank, exp.get("id"), exp.get("name"), tags,
            exp.get("template_family", ""), exp.get("template_id", ""),
            exp.get("batch_id", ""), exp.get("batch_name", ""), exp.get("batch_index", ""),
            exp.get("status"), m.get("verdict") or exp.get("verdict"), exp.get("score", ""),
            m.get("profit_factor", ""), m.get("expectancy", ""),
            m.get("sharpe", ""), m.get("max_drawdown_pct", ""),
            m.get("win_rate", ""), m.get("total_trades", ""),
            m.get("total_return_pct", ""), m.get("net_pnl", ""),
            m.get("ece", ""), m.get("brier_score", ""),
            m.get("ev_verdict", ""), m.get("ev_trades", ""), m.get("windows", ""),
            flags, exp.get("auto_rejected", ""),
            cs.get("train_years", ""), cs.get("test_months", ""), cs.get("step_months", ""),
            cs.get("start_date", ""), cs.get("end_date", ""),
            cs.get("intrabar_rule", ""), cs.get("max_holding_days", ""),
            cs.get("min_confidence_execute", ""),
            exp.get("created_at", ""), exp.get("started_at", ""), exp.get("completed_at", ""),
            SAFETY_NOTE,
        ])

    return {"ok": True, "csv": buf.getvalue(), "row_count": len(sorted_exps)}


def export_experiments_json(exp_ids_json: str | None = None) -> dict:
    """
    Generate a machine-readable JSON report (all experiments or specified IDs).
    The report is self-contained and suitable for sharing without screenshots.
    """
    exp_ids = json.loads(exp_ids_json) if exp_ids_json else None
    all_exps = list_experiments()["experiments"]
    if exp_ids:
        id_set = set(exp_ids)
        all_exps = [e for e in all_exps if e.get("id") in id_set]

    leaderboard = get_leaderboard()

    report: dict = {
        "generated_at":      datetime.now().isoformat(),
        "safety_note":       SAFETY_NOTE,
        "research_only":     True,
        "paper_trading_only": True,
        "auto_promotion":    False,
        "live_orders_affected": False,
        "system": {
            "universe":  "NIFTY 50",
            "capital":   "₹5,000 (paper)",
            "execution": "strict no-lookahead walk-forward train/test splits",
        },
        "summary": {
            "total_experiments": len(all_exps),
            "completed": sum(1 for e in all_exps if e.get("status") == "completed"),
            "rejected":  sum(1 for e in all_exps if e.get("status") == "rejected"),
            "failed":    sum(1 for e in all_exps if e.get("status") == "failed"),
            "queued":    sum(1 for e in all_exps if e.get("status") == "queued"),
        },
        "leaderboard_top3": leaderboard["entries"][:3] if leaderboard.get("entries") else [],
        "experiments": [],
    }

    for exp in all_exps:
        m  = exp.get("metrics") or {}
        cs = exp.get("config_summary") or {}
        report["experiments"].append({
            "id":           exp.get("id"),
            "name":         exp.get("name"),
            "description":  exp.get("description"),
            "tags":         exp.get("tags"),
            "template_id":  exp.get("template_id"),
            "template_family": exp.get("template_family"),
            "batch_id":     exp.get("batch_id"),
            "batch_name":   exp.get("batch_name"),
            "batch_index":  exp.get("batch_index"),
            "status":       exp.get("status"),
            "auto_rejected": exp.get("auto_rejected"),
            "overfitting_flags": exp.get("overfitting_flags"),
            "rejection_reason": " | ".join(exp.get("overfitting_flags") or []) or None,
            "score":            exp.get("score"),
            "score_breakdown":  exp.get("score_breakdown"),
            "verdict":          m.get("verdict") or exp.get("verdict"),
            "evidence_verdict": m.get("ev_verdict"),
            "evidence_label":   "RESEARCH_ONLY",
            "metrics": {
                "profit_factor":      m.get("profit_factor"),
                "expectancy_inr":     m.get("expectancy"),
                "sharpe_ratio":       m.get("sharpe"),
                "max_drawdown_pct":   m.get("max_drawdown_pct"),
                "win_rate_pct":       m.get("win_rate"),
                "total_trades":       m.get("total_trades"),
                "total_return_pct":   m.get("total_return_pct"),
                "net_pnl_inr":        m.get("net_pnl"),
                "calibration_ece":    m.get("ece"),
                "brier_score":        m.get("brier_score"),
                "evidence_trades":    m.get("ev_trades"),
                "windows":            m.get("windows"),
            },
            "config": {
                "train_years":            cs.get("train_years"),
                "test_months":            cs.get("test_months"),
                "step_months":            cs.get("step_months"),
                "start_date":             cs.get("start_date"),
                "end_date":               cs.get("end_date"),
                "intrabar_rule":          cs.get("intrabar_rule"),
                "max_holding_days":       cs.get("max_holding_days"),
                "min_confidence_execute": cs.get("min_confidence_execute"),
                "universe_size":          cs.get("universe_size"),
            },
            "timestamps": {
                "created":   exp.get("created_at"),
                "started":   exp.get("started_at"),
                "completed": exp.get("completed_at"),
            },
        })

    return {"ok": True, "report": report}

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
