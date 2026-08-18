"""
phase20_bootstrap_status.py — Bootstrap mode readiness payload builder.

Provides ``build_bootstrap_status_payload()``, a pure-ish function that
assembles the full JSON response for the ``phase20_bootstrap_status`` command.
Extracted from main.py so it can be unit-tested without importing the entire
server entry-point.

Gate priority order mirrors ``run_bootstrap_auto_entry()`` in phase20_executor:
  1. bootstrap_paper_enabled  (feature flag — caller already checked)
  2. auto_paper_entries       (normalised by get_settings to include confirmation)
  3. circuit breaker          (fail-closed: unreadable = tripped)
  4. kite_ltp_session_verified=True (session must be verified; overlay-enabled-only
                               is NOT sufficient because every candidate's per-symbol
                               kite_session_verified_flag=False when session is absent,
                               so the executor's per-candidate filter at line 875 of
                               phase20_executor.py always rejects them)
  5. closed-trade cutoff      (>= _BOOTSTRAP_MAX_CLOSED_TRADES)
  6. bootstrap_eligible_count (0 = scanning, >0 = ready)
"""
from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

# Bootstrap eligibility thresholds (must match live_scan_engine.py constants).
_BS_MIN_CONF = 60.0
_BS_MIN_OPP  = 50.0
_BS_MIN_RR   = 1.5
_BS_LIVE_QUALITIES = {"LIVE", "NEAR_LIVE"}


def _snapshot_ineligibility_reason(r: Dict[str, Any]) -> str:
    """Return a human-readable reason why a snapshot recommendation is NOT
    bootstrap_eligible.  Works on plain dicts from the scan snapshot (not
    Phase7Recommendation objects) so it can be called from the status builder
    without importing live_scan_engine.  Never raises."""
    if r.get("error"):
        return f"scan error: {r['error']}"
    if not r.get("low_evidence"):
        return "sufficient backtest evidence — normal BUY path applies (not bootstrap)"
    action = r.get("final_action", "")
    if action not in ("WATCH", "BUY", "STRONG BUY"):
        return f"action={action}, needs WATCH or better"
    if not r.get("all_gates_passed"):
        # Surface the first failed gate from the gate sub-dicts if present.
        for gate_key in ("gate_price", "gate_data_quality", "gate_rr", "gate_volume"):
            gate = r.get(gate_key) or {}
            if not gate.get("passed"):
                name = gate_key.replace("gate_", "")
                return f"risk gate failed ({name}): {gate.get('reason', name)}"
        return "risk gates not all passed"
    conf = float(r.get("calibrated_confidence") or 0)
    if conf < _BS_MIN_CONF:
        return f"confidence {conf:.1f} < {_BS_MIN_CONF} threshold"
    opp = float(r.get("opportunity_score") or 0)
    if opp < _BS_MIN_OPP:
        return f"opportunity score {opp:.1f} < {_BS_MIN_OPP} threshold"
    rr = float(r.get("rr_ratio") or 0)
    if rr < _BS_MIN_RR:
        return f"RR {rr:.2f} < {_BS_MIN_RR} threshold"
    if not r.get("quote_reliable"):
        return "Kite LTP not reliable — live quote required for bootstrap"
    if not r.get("kite_session_verified_flag"):
        return "Kite session not verified — login required for bootstrap"
    dq = r.get("data_quality", "")
    if dq not in _BS_LIVE_QUALITIES:
        return f"data quality {dq} — LIVE or NEAR_LIVE required"
    return "unknown — check scan logs"


def _extract_cb_detail(reasons: List[Any]) -> str:
    """
    Serialise the first circuit-breaker reason object to a plain string.

    ``evaluate_and_maybe_trip()`` returns ``reasons`` as a list of dicts with
    ``{code, detail, ...}`` shape.  Extracting the ``detail`` string (with a
    safe fallback chain) ensures the value is always JSON-serialisable and
    React-renderable — not a raw dict that would throw
    "Objects are not valid as a React child".
    """
    if not reasons:
        return "circuit breaker tripped"
    r0 = reasons[0]
    if isinstance(r0, dict):
        return str(r0.get("detail") or r0.get("code") or "circuit breaker tripped")
    return str(r0) if r0 else "circuit breaker tripped"


def build_bootstrap_status_payload(
    *,
    settings: Dict[str, Any],
    snapshot: Optional[Dict[str, Any]],
    evaluate_circuit_breaker: Callable[[Dict[str, Any]], Dict[str, Any]],
    get_closed_trades: Callable[[], int],
    bootstrap_max_closed_trades: int = 20,
) -> Dict[str, Any]:
    """
    Build the ``phase20_bootstrap_status`` response payload.

    Parameters
    ----------
    settings:
        Already-normalised settings from ``phase20_store.get_settings()``.
        ``auto_paper_entries`` is ``False`` when the operator confirmation is
        absent (normalised by the store — no separate field needed here).
    snapshot:
        Latest scan snapshot from ``scan_state_store.load_latest_snapshot()``,
        or ``None`` when no scan has been run yet.
    evaluate_circuit_breaker:
        Callable that accepts the settings dict and returns the circuit-breaker
        result dict ``{tripped, reasons, ...}``.  Must not raise; caller is
        responsible for wrapping in try/except and converting errors to
        ``{tripped: True, reasons: [...]}`` before calling.
    get_closed_trades:
        Zero-argument callable that returns the count of CLOSED paper trades
        from the DB.
    bootstrap_max_closed_trades:
        Threshold above which bootstrap auto-disables (mirrors
        ``_BOOTSTRAP_MAX_CLOSED_TRADES`` in phase20_executor).

    Returns
    -------
    dict  Full payload ready to be JSON-serialised and returned by the route.
    """
    snap = snapshot or {}
    safety  = snap.get("safety") or {}
    summary = snap.get("summary") or {}
    recs    = snap.get("recommendations") or []

    # ── Gate 1: auto_paper_entries ──────────────────────────────────────────
    auto_entries = bool(settings.get("auto_paper_entries"))

    # ── Gate 2: circuit breaker (fail-closed) ───────────────────────────────
    cb_result  = evaluate_circuit_breaker(settings)
    cb_tripped = bool(cb_result.get("tripped"))
    cb_detail  = _extract_cb_detail(cb_result.get("reasons") or []) if cb_tripped else ""

    # ── Gate 3: Kite session verified ────────────────────────────────────────
    # The executor's snapshot-level gate (line 811-812) accepts
    # "session_verified OR overlay_enabled", but the per-candidate filter at
    # line 875 requires kite_session_verified_flag=True on every candidate —
    # and kite_ltp_overlay.py sets that flag to bool(session_ok), meaning it
    # is False whenever the Kite session is unverified (even with the overlay
    # feature flag on).  Consequently, overlay-only (session absent) means no
    # candidates can ever pass the executor's per-candidate filter, and no
    # bootstrap entry will fire.
    #
    # The status card must reflect the stricter, end-to-end-accurate predicate:
    # kite_verified ↔ kite_ltp_session_verified.
    # The overlay flag is surfaced as an informational field only, so the UI
    # can show "overlay enabled — Kite login still required" rather than "Live".
    kite_session  = bool(safety.get("kite_ltp_session_verified"))
    kite_overlay  = bool(safety.get("kite_ltp_overlay_enabled"))
    kite_verified = kite_session  # session must be verified; overlay-only is not enough

    # ── Gate 4: closed-trade cutoff ─────────────────────────────────────────
    closed_trades   = get_closed_trades()
    cutoff_reached  = closed_trades >= bootstrap_max_closed_trades

    # ── Candidate summary ───────────────────────────────────────────────────
    boot_cands  = [r for r in recs if r.get("bootstrap_eligible")]
    watch_cands = [r for r in recs if r.get("final_action") == "WATCH"
                   and not r.get("paper_eligible")]
    show_cands  = sorted(
        boot_cands or watch_cands,
        key=lambda r: r.get("calibrated_confidence", 0),
        reverse=True,
    )[:5]

    # ── Top WATCH candidate when no bootstrap-eligible symbols exist ─────────
    # Operators see "top candidate: HDFCBANK (WATCH, not BUY)" so they know
    # the scanner ran and found candidates that just didn't clear eligibility.
    top_watch: Optional[Dict[str, Any]] = None
    if not boot_cands and watch_cands:
        _tw = sorted(watch_cands,
                     key=lambda r: r.get("calibrated_confidence", 0),
                     reverse=True)[0]
        top_watch = {
            "symbol":            _tw.get("symbol"),
            "confidence":        _tw.get("calibrated_confidence", 0),
            "opportunity_score": _tw.get("opportunity_score", 0),
            "rr_ratio":          _tw.get("rr_ratio", 0),
            "action":            _tw.get("final_action", "WATCH"),
            "ineligibility_reason": _snapshot_ineligibility_reason(_tw),
        }

    return {
        "success": True,
        "bootstrap_paper_enabled": True,
        # Gate 1
        "auto_paper_entries": auto_entries,
        "auto_paper_entries_confirmed_at": settings.get("auto_paper_entries_confirmed_at"),
        # Gate 2
        "circuit_breaker_tripped": cb_tripped,
        "circuit_breaker_detail": cb_detail,
        # Gate 3
        "kite_verified":         kite_verified,
        "kite_session_verified": kite_session,
        "kite_overlay_enabled":  kite_overlay,
        # Gate 4
        "closed_bootstrap_trades":     closed_trades,
        "bootstrap_max_closed_trades": bootstrap_max_closed_trades,
        "bootstrap_cutoff_reached":    cutoff_reached,
        # Candidate summary
        "bootstrap_eligible_count": int(summary.get("bootstrap_eligible_count") or 0),
        "watch_count":              int(summary.get("watch_count") or 0),
        "snapshot_ts": snap.get("snapshot_ts"),
        "scan_id":     snap.get("scan_id"),
        # Top watch candidate surfaced when no bootstrap-eligible symbols exist so
        # operators understand "the scanner found HDFCBANK at 78% but it's WATCH, not BUY".
        "top_watch_candidate": top_watch,
        "top_candidates": [
            {
                "symbol":            r.get("symbol"),
                "confidence":        r.get("calibrated_confidence", 0),
                "opportunity_score": r.get("opportunity_score", 0),
                "rr_ratio":          r.get("rr_ratio", 0),
                "bootstrap_eligible": bool(r.get("bootstrap_eligible")),
                "entry_price":       r.get("entry_price", 0),
                "action":            r.get("final_action", "WATCH"),
                "ineligibility_reason": (
                    None if r.get("bootstrap_eligible")
                    else _snapshot_ineligibility_reason(r)
                ),
            }
            for r in show_cands
        ],
    }
