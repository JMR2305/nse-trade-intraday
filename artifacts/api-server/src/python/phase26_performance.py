"""
phase26_performance.py — Phase 26C: performance validation.

Aggregates latency/duration metrics that the platform ALREADY records —
scan-run history durations, pipeline-event stage timestamps, a timed replay
build, a timed DB health query, and process resource counters — into one
graded report. No new profiling infrastructure and no duplicate profiling:
everything is read from existing timestamps or measured as a single cheap
probe per cycle.

Metrics (each graded PASS / WARN / FAIL against explicit thresholds, or
INSUFFICIENT when the source has no data — never extrapolated):

* scan_duration_s        — latest successful scheduled/manual scan duration.
* decision_latency_s     — SCANNER→AI_DECISION last-event gap for the
                           latest scan (pipeline_events stage summary).
* execution_latency_s    — AI_DECISION→EXECUTION last-event gap.
* replay_latency_ms      — measured build_replay("latest") wall time.
* db_query_ms            — timed canonical-store read (scan meta).
* memory_mb              — process peak RSS (resource.getrusage).
* cpu_load_1m            — 1-minute load average.

Fold: any FAIL → FAIL, else any WARN → WARN, else PASS (INSUFFICIENT
metrics degrade the verdict to WARN at worst, never FAIL).

Results persist append-only via phase26c_store; FAIL metrics feed the
Phase 26 issue store (category PERFORMANCE).

READ-ONLY / ADVISORY-ONLY. PAPER TRADING / RESEARCH ONLY.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# name: (warn_threshold, fail_threshold, unit) — value <= warn → PASS,
# <= fail → WARN, else FAIL.
THRESHOLDS: Dict[str, tuple] = {
    "scan_duration_s":    (120.0,  300.0, "s"),
    "decision_latency_s": (60.0,   180.0, "s"),
    "execution_latency_s": (30.0,  120.0, "s"),
    "replay_latency_ms":  (2000.0, 8000.0, "ms"),
    "db_query_ms":        (500.0,  2000.0, "ms"),
    "memory_mb":          (1500.0, 2500.0, "MB"),
    "cpu_load_1m":        (4.0,    8.0,   ""),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(value: Any) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _f(v, default=None):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


# ── Input collection (live) ─────────────────────────────────────────────────

def collect_performance_inputs() -> Dict[str, Any]:
    """Read existing timestamps + run two cheap timed probes. Unavailable
    sources are None → INSUFFICIENT, never fabricated."""
    out: Dict[str, Any] = {}

    def _try(name, fn):
        try:
            out[name] = fn()
        except Exception as exc:
            out[name] = None
            out.setdefault("_errors", {})[name] = str(exc)[:200]

    def _scan_runs():
        import phase20_store as store
        return store.list_scan_runs(limit=20)

    def _stage_summary():
        import scan_state_store
        meta = scan_state_store.load_latest_meta() or {}
        scan_id = meta.get("scan_id")
        if not scan_id:
            return None
        from pipeline_events import stage_summary
        return stage_summary(scan_id=scan_id)

    def _replay_ms():
        from replay_engine import build_replay
        t0 = time.monotonic()
        r = build_replay("latest") or {}
        ms = (time.monotonic() - t0) * 1000
        return None if r.get("error") else round(ms, 1)

    def _db_ms():
        import scan_state_store
        t0 = time.monotonic()
        scan_state_store.load_latest_meta()
        return round((time.monotonic() - t0) * 1000, 1)

    def _memory_mb():
        import resource
        kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        return round(kb / 1024.0, 1)          # Linux reports KB

    def _load1():
        import os
        return round(os.getloadavg()[0], 2)

    _try("scan_runs", _scan_runs)
    _try("stage_summary", _stage_summary)
    _try("replay_latency_ms", _replay_ms)
    _try("db_query_ms", _db_ms)
    _try("memory_mb", _memory_mb)
    _try("cpu_load_1m", _load1)
    return out


# ── Metric derivation (pure, injectable) ─────────────────────────────────────

def _latest_success_duration(scan_runs) -> Optional[float]:
    for r in scan_runs or []:
        if str(r.get("status") or "").upper() == "SUCCESS":
            return _f(r.get("duration_s"))
    return None


def _stage_gap_s(stage_summary: Optional[Dict[str, Any]],
                 from_stage: str, to_stage: str) -> Optional[float]:
    """Gap between the last event of two stages for the scan. None when
    either stage has no events (e.g. no trades that scan — not a failure)."""
    if not stage_summary:
        return None
    by_id = {s.get("stage"): s for s in stage_summary.get("stages") or []}
    a = _parse_ts((by_id.get(from_stage) or {}).get("last_ts"))
    b = _parse_ts((by_id.get(to_stage) or {}).get("last_ts"))
    if a is None or b is None:
        return None
    return round((b - a).total_seconds(), 2)


def _grade(name: str, value: Optional[float]) -> Dict[str, Any]:
    warn, fail, unit = THRESHOLDS[name]
    m = {"metric": name, "value": value, "unit": unit,
         "warn_threshold": warn, "fail_threshold": fail}
    if value is None:
        m["grade"] = "INSUFFICIENT"
        m["detail"] = "No data recorded for this metric this cycle"
        return m
    if value <= warn:
        m["grade"] = "PASS"
    elif value <= fail:
        m["grade"] = "WARN"
    else:
        m["grade"] = "FAIL"
    m["detail"] = f"{value}{unit} (warn>{warn}{unit}, fail>{fail}{unit})"
    return m


def build_performance_report(inputs: Dict[str, Any]) -> Dict[str, Any]:
    summary = inputs.get("stage_summary")
    metrics = [
        _grade("scan_duration_s",
               _latest_success_duration(inputs.get("scan_runs"))),
        _grade("decision_latency_s",
               _stage_gap_s(summary, "SCANNER", "AI_DECISION")),
        _grade("execution_latency_s",
               _stage_gap_s(summary, "AI_DECISION", "EXECUTION")),
        _grade("replay_latency_ms", _f(inputs.get("replay_latency_ms"))),
        _grade("db_query_ms", _f(inputs.get("db_query_ms"))),
        _grade("memory_mb", _f(inputs.get("memory_mb"))),
        _grade("cpu_load_1m", _f(inputs.get("cpu_load_1m"))),
    ]
    grades = [m["grade"] for m in metrics]
    if "FAIL" in grades:
        verdict = "FAIL"
    elif "WARN" in grades or "INSUFFICIENT" in grades:
        verdict = "WARN"
    else:
        verdict = "PASS"
    return {
        "area": "PERFORMANCE",
        "generated_at": _now_iso(),
        "verdict": verdict,
        "fully_evaluated": "INSUFFICIENT" not in grades,
        "metrics": metrics,
        "grade_counts": {g: grades.count(g)
                         for g in ("PASS", "WARN", "FAIL", "INSUFFICIENT")},
        "advisory_only": True,
    }


def run_performance_validation(persist: bool = True,
                               inputs: Optional[Dict[str, Any]] = None
                               ) -> Dict[str, Any]:
    if inputs is None:
        inputs = collect_performance_inputs()
    report = build_performance_report(inputs)
    try:
        from phase26_recovery import _feed_issues
        _feed_issues(report, category="PERFORMANCE",
                     items=[(m["metric"], m["detail"]) for m in
                            report["metrics"] if m["grade"] == "FAIL"])
    except Exception as exc:
        report["issue_reconcile"] = {"error": str(exc)[:200]}
    if persist:
        try:
            import phase26c_store as store
            stored = store.append_result(report["area"], report)
            report["result_id"] = stored.get("result_id")
        except Exception as exc:
            report["persist_error"] = str(exc)[:200]
    return report
