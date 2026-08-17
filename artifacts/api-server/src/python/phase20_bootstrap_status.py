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
        "top_candidates": [
            {
                "symbol":            r.get("symbol"),
                "confidence":        r.get("calibrated_confidence", 0),
                "opportunity_score": r.get("opportunity_score", 0),
                "rr_ratio":          r.get("rr_ratio", 0),
                "bootstrap_eligible": bool(r.get("bootstrap_eligible")),
                "entry_price":       r.get("entry_price", 0),
            }
            for r in show_cands
        ],
    }
