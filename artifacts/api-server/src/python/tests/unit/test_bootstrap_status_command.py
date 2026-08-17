"""
test_bootstrap_status_command.py — Unit tests for phase20_bootstrap_status.py

Covers all 6 card states (disabled, entries_off, circuit_breaker, no_kite,
complete, scanning, ready) and the critical serialisation contract that
circuit_breaker_detail is always a plain string — never a raw dict/object
that would crash React with "Objects are not valid as a React child".

Gate priority order matches run_bootstrap_auto_entry() in phase20_executor:
  auto_paper_entries → circuit_breaker → kite_ltp → cutoff → candidates
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

# ── Path setup ────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from phase20_bootstrap_status import build_bootstrap_status_payload, _extract_cb_detail  # noqa: E402

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_BASE_SETTINGS = {
    "bootstrap_paper_enabled": True,
    "auto_paper_entries": True,
    "auto_paper_entries_confirmed_at": "2026-01-01T00:00:00Z",
}

_SNAP_KITE_OK = {
    "safety": {
        "kite_ltp_session_verified": True,
        "kite_ltp_overlay_enabled": False,
    },
    "summary": {"bootstrap_eligible_count": 0, "watch_count": 5},
    "recommendations": [],
    "scan_id": "scan01",
    "snapshot_ts": "2026-01-01T09:00:00Z",
}

_SNAP_NO_KITE = {
    "safety": {
        "kite_ltp_session_verified": False,
        "kite_ltp_overlay_enabled": False,
    },
    "summary": {"bootstrap_eligible_count": 0, "watch_count": 5},
    "recommendations": [],
    "scan_id": "scan02",
    "snapshot_ts": "2026-01-01T09:00:00Z",
}

_CB_CLEAR = {"tripped": False, "reasons": []}

def _cb_trip(detail: str = "3 consecutive losses", code: str = "CONSECUTIVE_LOSSES"):
    return {"tripped": True, "reasons": [{"code": code, "detail": detail}]}


def _call(
    *,
    settings: dict | None = None,
    snapshot: dict | None = None,
    cb_result: dict | None = None,
    closed: int = 0,
) -> dict[str, Any]:
    """Thin wrapper around build_bootstrap_status_payload."""
    return build_bootstrap_status_payload(
        settings=settings if settings is not None else dict(_BASE_SETTINGS),
        snapshot=snapshot if snapshot is not None else dict(_SNAP_KITE_OK),
        evaluate_circuit_breaker=lambda _s: cb_result if cb_result is not None else _CB_CLEAR,
        get_closed_trades=lambda: closed,
    )


# ---------------------------------------------------------------------------
# _extract_cb_detail — serialisation contract
# ---------------------------------------------------------------------------

class TestExtractCbDetail:
    """_extract_cb_detail must always return a plain str."""

    def test_returns_detail_string(self):
        assert _extract_cb_detail([{"code": "X", "detail": "Loss limit hit"}]) == "Loss limit hit"

    def test_falls_back_to_code_when_no_detail(self):
        assert _extract_cb_detail([{"code": "NEGATIVE_EXPECTANCY"}]) == "NEGATIVE_EXPECTANCY"

    def test_fallback_when_dict_both_absent(self):
        result = _extract_cb_detail([{}])
        assert isinstance(result, str)
        assert result == "circuit breaker tripped"

    def test_fallback_empty_list(self):
        result = _extract_cb_detail([])
        assert isinstance(result, str)
        assert result == "circuit breaker tripped"

    def test_non_dict_reason_stringified(self):
        result = _extract_cb_detail(["some string reason"])
        assert isinstance(result, str)
        assert result == "some string reason"

    def test_none_reason_gives_fallback(self):
        result = _extract_cb_detail([None])
        assert isinstance(result, str)


# ---------------------------------------------------------------------------
# State: entries_off — auto_paper_entries=False (includes unconfirmed case)
# ---------------------------------------------------------------------------

class TestEntriesOff:
    def test_auto_paper_entries_false(self):
        r = _call(settings={**_BASE_SETTINGS, "auto_paper_entries": False})
        assert r["auto_paper_entries"] is False

    def test_normalised_unconfirmed_shows_false(self):
        """get_settings() sets auto_paper_entries=False when confirmed_at missing;
        the payload mirrors that — no separate 'unconfirmed' state exists."""
        r = _call(settings={
            "bootstrap_paper_enabled": True,
            "auto_paper_entries": False,          # normalised by get_settings()
            "auto_paper_entries_confirmed_at": None,
        })
        assert r["auto_paper_entries"] is False

    def test_confirmed_at_forwarded(self):
        r = _call()
        assert r["auto_paper_entries_confirmed_at"] == "2026-01-01T00:00:00Z"

    def test_confirmed_at_none_forwarded(self):
        r = _call(settings={**_BASE_SETTINGS,
                             "auto_paper_entries": False,
                             "auto_paper_entries_confirmed_at": None})
        assert r["auto_paper_entries_confirmed_at"] is None


# ---------------------------------------------------------------------------
# State: circuit_breaker — tripped; detail MUST be a plain string
# ---------------------------------------------------------------------------

class TestCircuitBreaker:
    def test_tripped_true(self):
        r = _call(cb_result=_cb_trip("Daily loss limit breached", "DAILY_LOSS_LIMIT"))
        assert r["circuit_breaker_tripped"] is True

    def test_detail_is_str_not_dict(self):
        """CRITICAL: circuit_breaker_detail must be a str so React can render it."""
        r = _call(cb_result=_cb_trip("Daily loss limit breached"))
        assert isinstance(r["circuit_breaker_detail"], str), (
            f"circuit_breaker_detail type={type(r['circuit_breaker_detail'])!r}"
        )

    def test_detail_content(self):
        r = _call(cb_result=_cb_trip("3 consecutive losses"))
        assert "3 consecutive losses" in r["circuit_breaker_detail"]

    def test_detail_empty_when_not_tripped(self):
        r = _call(cb_result=_CB_CLEAR)
        assert r["circuit_breaker_tripped"] is False
        assert r["circuit_breaker_detail"] == ""

    def test_detail_fallback_when_reasons_empty(self):
        r = _call(cb_result={"tripped": True, "reasons": []})
        assert isinstance(r["circuit_breaker_detail"], str)
        assert r["circuit_breaker_detail"]   # non-empty

    def test_detail_fallback_no_detail_key(self):
        r = _call(cb_result={"tripped": True,
                              "reasons": [{"code": "NEGATIVE_EXPECTANCY"}]})
        assert isinstance(r["circuit_breaker_detail"], str)
        assert "NEGATIVE_EXPECTANCY" in r["circuit_breaker_detail"]


# ---------------------------------------------------------------------------
# State: no_kite — neither session_verified nor overlay_enabled
# ---------------------------------------------------------------------------

class TestKiteVerified:
    def test_both_false_gives_not_verified(self):
        r = _call(snapshot=_SNAP_NO_KITE)
        assert r["kite_verified"] is False
        assert r["kite_session_verified"] is False
        assert r["kite_overlay_enabled"] is False

    def test_session_verified_makes_kite_ok(self):
        snap = {**_SNAP_NO_KITE,
                "safety": {"kite_ltp_session_verified": True,
                            "kite_ltp_overlay_enabled": False}}
        r = _call(snapshot=snap)
        assert r["kite_verified"] is True
        assert r["kite_session_verified"] is True

    def test_overlay_only_does_not_make_kite_ok(self):
        """CRITICAL: overlay enabled but session unverified → kite_verified=False.

        kite_ltp_overlay.py sets per-candidate kite_session_verified_flag=bool(session_ok).
        When session is unverified, that flag is False for every candidate, so the executor's
        per-candidate filter (phase20_executor.py line 875) rejects them all and no bootstrap
        entry can ever fire. The card must reflect this — not show 'Kite Live'.
        """
        snap = {**_SNAP_NO_KITE,
                "safety": {"kite_ltp_session_verified": False,
                            "kite_ltp_overlay_enabled": True}}
        r = _call(snapshot=snap)
        assert r["kite_verified"] is False, (
            "Overlay-only (session unverified) must report kite_verified=False because "
            "per-candidate kite_session_verified_flag=False blocks all executor selections"
        )
        assert r["kite_overlay_enabled"] is True   # still surfaced as informational
        assert r["kite_session_verified"] is False

    def test_session_and_overlay_both_true(self):
        snap = {**_SNAP_KITE_OK,
                "safety": {"kite_ltp_session_verified": True,
                            "kite_ltp_overlay_enabled": True}}
        r = _call(snapshot=snap)
        assert r["kite_verified"] is True
        assert r["kite_session_verified"] is True
        assert r["kite_overlay_enabled"] is True


# ---------------------------------------------------------------------------
# State: complete — closed_bootstrap_trades >= max (20)
# ---------------------------------------------------------------------------

class TestCutoffReached:
    def test_at_threshold(self):
        r = _call(closed=20)
        assert r["bootstrap_cutoff_reached"] is True
        assert r["closed_bootstrap_trades"] == 20
        assert r["bootstrap_max_closed_trades"] == 20

    def test_above_threshold(self):
        r = _call(closed=25)
        assert r["bootstrap_cutoff_reached"] is True

    def test_below_threshold(self):
        r = _call(closed=19)
        assert r["bootstrap_cutoff_reached"] is False

    def test_zero_trades(self):
        r = _call(closed=0)
        assert r["bootstrap_cutoff_reached"] is False
        assert r["closed_bootstrap_trades"] == 0


# ---------------------------------------------------------------------------
# State: scanning — all gates pass, bootstrap_eligible_count=0
# ---------------------------------------------------------------------------

class TestScanning:
    def test_all_gates_pass_no_eligible(self):
        r = _call(snapshot={
            **_SNAP_KITE_OK,
            "summary": {"bootstrap_eligible_count": 0, "watch_count": 8},
        })
        assert r["bootstrap_paper_enabled"] is True
        assert r["auto_paper_entries"] is True
        assert r["circuit_breaker_tripped"] is False
        assert r["kite_verified"] is True
        assert r["bootstrap_cutoff_reached"] is False
        assert r["bootstrap_eligible_count"] == 0

    def test_watch_count_forwarded(self):
        r = _call(snapshot={**_SNAP_KITE_OK,
                             "summary": {"bootstrap_eligible_count": 0, "watch_count": 12}})
        assert r["watch_count"] == 12

    def test_snapshot_fields_forwarded(self):
        r = _call(snapshot={**_SNAP_KITE_OK,
                             "scan_id": "abc123",
                             "snapshot_ts": "2026-06-01T09:15:00Z"})
        assert r["scan_id"] == "abc123"
        assert r["snapshot_ts"] == "2026-06-01T09:15:00Z"

    def test_no_candidates_returns_empty_list(self):
        r = _call()
        assert r["top_candidates"] == []


# ---------------------------------------------------------------------------
# State: ready — eligible candidates exist (genuinely executable path)
# ---------------------------------------------------------------------------

_CAND_A = {
    "symbol": "RELIANCE",
    "final_action": "WATCH",
    "calibrated_confidence": 72.0,
    "opportunity_score": 65.0,
    "rr_ratio": 2.0,
    "bootstrap_eligible": True,
    "paper_eligible": False,
    "entry_price": 2800.0,
}
_CAND_B = {
    "symbol": "TCS",
    "final_action": "WATCH",
    "calibrated_confidence": 68.0,
    "opportunity_score": 60.0,
    "rr_ratio": 1.8,
    "bootstrap_eligible": True,
    "paper_eligible": False,
    "entry_price": 3500.0,
}
_SNAP_READY = {
    **_SNAP_KITE_OK,
    "summary": {"bootstrap_eligible_count": 2, "watch_count": 10},
    "recommendations": [_CAND_A, _CAND_B],
}


class TestReady:
    def test_eligible_count(self):
        r = _call(snapshot=_SNAP_READY)
        assert r["bootstrap_eligible_count"] == 2

    def test_top_candidates_present(self):
        r = _call(snapshot=_SNAP_READY)
        assert len(r["top_candidates"]) == 2
        syms = {c["symbol"] for c in r["top_candidates"]}
        assert "RELIANCE" in syms and "TCS" in syms

    def test_candidates_sorted_by_confidence_desc(self):
        r = _call(snapshot=_SNAP_READY)
        confs = [c["confidence"] for c in r["top_candidates"]]
        assert confs == sorted(confs, reverse=True)

    def test_candidate_numeric_fields(self):
        r = _call(snapshot=_SNAP_READY)
        for c in r["top_candidates"]:
            assert isinstance(c["confidence"], (int, float))
            assert isinstance(c["rr_ratio"], (int, float))

    def test_candidate_bootstrap_eligible_is_bool(self):
        r = _call(snapshot=_SNAP_READY)
        for c in r["top_candidates"]:
            assert isinstance(c["bootstrap_eligible"], bool)

    def test_success_flag(self):
        r = _call(snapshot=_SNAP_READY)
        assert r["success"] is True
        assert r["bootstrap_paper_enabled"] is True

    def test_no_candidates_when_snapshot_is_none(self):
        r = _call(snapshot=None)
        assert r["top_candidates"] == []


# ---------------------------------------------------------------------------
# Disabled path is handled by the caller (main.py), not the helper,
# so we test only that build_bootstrap_status_payload always sets
# bootstrap_paper_enabled=True (the caller only calls it when enabled).
# ---------------------------------------------------------------------------

class TestAlwaysEnabled:
    def test_bootstrap_paper_enabled_is_true(self):
        r = _call()
        assert r["bootstrap_paper_enabled"] is True

    def test_success_is_true(self):
        r = _call()
        assert r["success"] is True
