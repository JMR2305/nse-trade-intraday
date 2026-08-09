"""Task: automatic low-coverage operator alert (phase20_scheduler).

Hermetic: coverage_probe, market_hours, and the KV/notification store are
all monkeypatched — no DB, no network, no real clock.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, time as dtime
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")))

import phase20_scheduler as sched  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")


class FakeStore:
    def __init__(self):
        self.kv = {}
        self.notifications = []

    def kv_get(self, key):
        return self.kv.get(key)

    def kv_set(self, key, value):
        self.kv[key] = value

    def kv_claim_once(self, key):
        if key in self.kv:
            return False
        self.kv[key] = True
        return True

    def add_notification(self, **kw):
        self.notifications.append(kw)


class FakeMarketHours:
    MARKET_OPEN = dtime(9, 15)

    def __init__(self, now):
        self._now = now

    def now_ist(self):
        return self._now


def probe(ok, coverage=48, missing=("LTIM", "TATAMOTORS"), fresh=True,
          in_session=True, warning="coverage low"):
    return {"ok": ok, "in_session": in_session, "coverage": coverage,
            "min_symbols_expected": 50, "missing_symbols": list(missing),
            "scan_id": "scan-x", "scan_fresh_for_session": fresh,
            "warning": None if ok else warning}


@pytest.fixture
def env(monkeypatch):
    """Patch store + market_hours + coverage_probe; default 10:00 IST."""
    fake = FakeStore()
    monkeypatch.setattr(sched, "store", fake)
    state = {"now": datetime(2026, 8, 10, 10, 0, tzinfo=IST),
             "probe": probe(ok=False)}
    mh = FakeMarketHours(state["now"])

    import scanner_coverage
    monkeypatch.setitem(sys.modules, "market_hours", mh)
    monkeypatch.setattr(scanner_coverage, "coverage_probe",
                        lambda: state["probe"])

    def set_now(dt):
        mh._now = dt
    state["set_now"] = set_now
    state["store"] = fake
    return state


def test_no_alert_within_grace(env):
    env["set_now"](datetime(2026, 8, 10, 9, 20, tzinfo=IST))  # < 09:30
    out = sched._maybe_alert_low_coverage("OPEN")
    assert out["checked"] is False and "grace" in out["reason"]
    assert env["store"].notifications == []


def test_no_alert_when_market_not_open(env):
    assert sched._maybe_alert_low_coverage("CLOSED") is None
    assert sched._maybe_alert_low_coverage("WEEKEND") is None
    assert env["store"].notifications == []


def test_alert_fires_once_per_session_per_shortfall(env):
    out1 = sched._maybe_alert_low_coverage("OPEN")
    assert out1["alerted"] is True
    out2 = sched._maybe_alert_low_coverage("OPEN")
    assert out2["alerted"] is False
    assert len(env["store"].notifications) == 1
    n = env["store"].notifications[0]
    assert n["kind"] == "DATA_QUALITY_CRITICAL"       # email-eligible kind
    assert n["severity"] == "CRITICAL"
    assert "48/50" in n["title"]
    assert n["context"]["missing_symbols"] == ["LTIM", "TATAMOTORS"]


def test_new_shortfall_same_session_alerts_again(env):
    sched._maybe_alert_low_coverage("OPEN")
    env["probe"] = probe(ok=False, coverage=47,
                         missing=("LTIM", "TATAMOTORS", "WIPRO"))
    out = sched._maybe_alert_low_coverage("OPEN")
    assert out["alerted"] is True
    assert len(env["store"].notifications) == 2


def test_stale_scan_uses_no_fresh_scan_signature(env):
    env["probe"] = probe(ok=False, fresh=False, missing=())
    out = sched._maybe_alert_low_coverage("OPEN")
    assert out["alerted"] is True and out["signature"] == "no-fresh-scan"


def test_recovery_resolves_once(env):
    sched._maybe_alert_low_coverage("OPEN")            # raise alert
    env["probe"] = probe(ok=True, coverage=50, missing=())
    out = sched._maybe_alert_low_coverage("OPEN")
    assert out.get("resolved") is True
    out2 = sched._maybe_alert_low_coverage("OPEN")     # no duplicate resolve
    assert out2.get("resolved") is None
    kinds = [n["kind"] for n in env["store"].notifications]
    assert kinds == ["DATA_QUALITY_CRITICAL", "DATA_QUALITY_RECOVERED"]
    assert env["store"].notifications[1]["severity"] == "INFO"


def test_ok_without_prior_alert_stays_silent(env):
    env["probe"] = probe(ok=True, coverage=50, missing=())
    out = sched._maybe_alert_low_coverage("OPEN")
    assert out == {"checked": True, "ok": True}
    assert env["store"].notifications == []


def test_next_session_can_alert_again(env):
    sched._maybe_alert_low_coverage("OPEN")
    env["set_now"](datetime(2026, 8, 11, 10, 0, tzinfo=IST))  # next day
    out = sched._maybe_alert_low_coverage("OPEN")
    assert out["alerted"] is True
    assert len(env["store"].notifications) == 2


def test_shortfall_a_b_a_never_realerts_a(env):
    """A → B → A within one session: A alerts once, B alerts once, the
    recurrence of A is suppressed (per-signature claims, not last-writer)."""
    a = probe(ok=False, missing=("LTIM",))
    b = probe(ok=False, missing=("LTIM", "WIPRO"))
    env["probe"] = a
    assert sched._maybe_alert_low_coverage("OPEN")["alerted"] is True
    env["probe"] = b
    assert sched._maybe_alert_low_coverage("OPEN")["alerted"] is True
    env["probe"] = a
    assert sched._maybe_alert_low_coverage("OPEN")["alerted"] is False
    assert len(env["store"].notifications) == 2


def test_recovery_rearms_after_new_alert(env):
    """alert → recover → NEW shortfall → recover again: two recovery
    notifications, one per alert episode."""
    sched._maybe_alert_low_coverage("OPEN")
    env["probe"] = probe(ok=True, coverage=50, missing=())
    assert sched._maybe_alert_low_coverage("OPEN").get("resolved") is True
    env["probe"] = probe(ok=False, coverage=47, missing=("WIPRO",))
    assert sched._maybe_alert_low_coverage("OPEN")["alerted"] is True
    env["probe"] = probe(ok=True, coverage=50, missing=())
    assert sched._maybe_alert_low_coverage("OPEN").get("resolved") is True
    kinds = [n["kind"] for n in env["store"].notifications]
    assert kinds == ["DATA_QUALITY_CRITICAL", "DATA_QUALITY_RECOVERED",
                     "DATA_QUALITY_CRITICAL", "DATA_QUALITY_RECOVERED"]


def test_probe_out_of_session_skips(env):
    env["probe"] = probe(ok=False, in_session=False)
    out = sched._maybe_alert_low_coverage("OPEN")
    assert out["checked"] is False
    assert env["store"].notifications == []


def test_kv_claim_once_file_fallback_is_atomic(tmp_path, monkeypatch):
    """Interleaved contenders on the JSON fallback: exactly one wins."""
    import threading
    import phase20_store as p20s
    monkeypatch.setattr(p20s, "_DIR", str(tmp_path))
    monkeypatch.setattr(p20s, "_with_db",
                        lambda db_fn, file_fn: file_fn())
    wins = []

    def contender():
        if p20s.kv_claim_once("coverage_alert:2026-08-10:missing:LTIM"):
            wins.append(1)

    threads = [threading.Thread(target=contender) for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(wins) == 1
    # and a different key can still be claimed
    assert p20s.kv_claim_once("coverage_alert:2026-08-10:other") is True


def test_concurrent_watchdog_ticks_never_duplicate(tmp_path, monkeypatch):
    """End-to-end: many concurrent watchdog invocations with interleaved
    signatures against the REAL file-backed KV store — every claim stays
    durable (kv_set cannot erase concurrent claims) and each signature
    alerts exactly once."""
    import threading
    import phase20_store as p20s

    monkeypatch.setattr(p20s, "_DIR", str(tmp_path))
    monkeypatch.setattr(p20s, "_with_db", lambda db_fn, file_fn: file_fn())
    notifications = []
    notif_lock = threading.Lock()

    def add_notification(**kw):
        with notif_lock:
            notifications.append(kw)
    monkeypatch.setattr(p20s, "add_notification", add_notification)
    monkeypatch.setattr(sched, "store", p20s)

    mh = FakeMarketHours(datetime(2026, 8, 10, 10, 0, tzinfo=IST))
    monkeypatch.setitem(sys.modules, "market_hours", mh)

    import scanner_coverage
    probes = [probe(ok=False, missing=("LTIM",)),
              probe(ok=False, missing=("LTIM", "WIPRO")),
              probe(ok=False, missing=("TATAMOTORS",))]
    local = threading.local()
    monkeypatch.setattr(scanner_coverage, "coverage_probe",
                        lambda: local.probe)

    def tick(i):
        local.probe = probes[i % len(probes)]
        sched._maybe_alert_low_coverage("OPEN")

    threads = [threading.Thread(target=tick, args=(i,)) for i in range(15)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # exactly one alert per distinct signature, no duplicates
    assert len(notifications) == 3
    sigs = sorted(n["context"]["signature"] for n in notifications)
    assert sigs == ["missing:LTIM", "missing:LTIM,WIPRO",
                    "missing:TATAMOTORS"]
    # all claims durable in the KV file (kv_set of the last-alert key did
    # not overwrite any concurrent claim)
    data = p20s._read_json(str(tmp_path / "phase20_kv.json"), {})
    claim_keys = [k for k in data if k.startswith("coverage_alert:2026-08-10:")]
    assert len(claim_keys) == 3
    assert data.get("coverage_alert_last") in claim_keys


def test_probe_exception_never_raises(env, monkeypatch):
    import scanner_coverage

    def boom():
        raise RuntimeError("probe exploded")
    monkeypatch.setattr(scanner_coverage, "coverage_probe", boom)
    out = sched._maybe_alert_low_coverage("OPEN")
    assert out["checked"] is False and "probe exploded" in out["error"]
