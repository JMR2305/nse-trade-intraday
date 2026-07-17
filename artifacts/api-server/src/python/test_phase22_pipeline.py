"""
Phase 22 post-scan pipeline tests — bundle publish semantics, provider
clarity, scheduler-state enrichment. PAPER / RESEARCH ONLY.

Style matches test_phase22.py: prints "N passed, N failed".
"""

import json
import sys

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {detail}")


import scan_pipeline as sp
import phase20_store as store

# ── T1: Bundle constants & structure ─────────────────────────────────────────
print("== Constants ==")
check("model version set", bool(sp.MODEL_VERSION))
check("rule version set", bool(sp.RULE_VERSION))
check("required modules include consistency",
      "consistency" in sp.REQUIRED_MODULES)
check("required modules include intelligence",
      "intelligence" in sp.REQUIRED_MODULES)

# ── T2: Config hash stable & non-empty ───────────────────────────────────────
print("== Config hash ==")
h1, h2 = sp._config_hash(), sp._config_hash()
check("config hash non-empty", bool(h1) and h1 != "unavailable", h1)
check("config hash deterministic", h1 == h2)

# ── T3: Provider breakdown clarity ───────────────────────────────────────────
print("== Provider breakdown ==")
snap = {
    "provider_health": {"symbols_requested": 10, "symbols_succeeded": 9,
                        "unavailable_symbols": ["X"], "stale_symbols": []},
    "safety": {"data_provider": "yfinance"},
    "recommendations": [{"symbol": "TCS", "data_source": "yfinance"}],
}
pb = sp._provider_breakdown(snap)
check("full-scan provider labelled", pb["full_scan_provider"] == "yfinance")
check("kite not claimed when unused", pb["kite_used_in_this_scan"] is False)
check("missing count correct", pb["symbols_missing"] == 1)
check("received count correct", pb["symbols_received"] == 9)

# ── T4: Failure recording — attempt saved, pointer NOT advanced ─────────────
print("== Publish semantics ==")
saved = {}
orig_kv_set, orig_kv_get = store.kv_set, store.kv_get
store.kv_set = lambda k, v: saved.__setitem__(k, v)

# (a) Empty snapshot MUST fail fast and never publish scan_bundle_latest.
bad = sp.run_post_scan_pipeline({}, trigger="TEST")
check("pipeline never raises", isinstance(bad, dict))
check("empty snapshot rejected", bad.get("status") == "FAILED",
      json.dumps(bad)[:120])
check("attempt always recorded", sp.ATTEMPT_KEY in saved)
check("empty snapshot never published", sp.BUNDLE_KEY not in saved)
# Missing snapshot_ts alone must also be rejected.
bad2 = sp.run_post_scan_pipeline({"scan_id": "abc"}, trigger="TEST")
check("snapshot without snapshot_ts rejected", bad2.get("status") == "FAILED")
attempt = saved[sp.ATTEMPT_KEY]
check("attempt records trigger", attempt.get("trigger_source") == "TEST")
store.kv_set, store.kv_get = orig_kv_set, orig_kv_get

# (b) Monotonic publish — older pipeline must not overwrite a newer bundle.
print("== Monotonic publish ==")
orig_kv_get = store.kv_get
newer = {"scan_id": "NEW1", "snapshot_ts": "2026-07-17T05:00:00Z"}
store.kv_get = lambda k, d=None: newer if k == sp.BUNDLE_KEY else d
older = {"scan_id": "OLD1", "snapshot_ts": "2026-07-17T04:00:00Z"}
check("older bundle blocked", sp._is_newer_than_published(older) is False)
same = {"scan_id": "NEW1", "snapshot_ts": "2026-07-17T05:00:00Z"}
check("same scan republish allowed", sp._is_newer_than_published(same) is True)
newer2 = {"scan_id": "NEW2", "snapshot_ts": "2026-07-17T06:00:00Z"}
check("newer bundle allowed", sp._is_newer_than_published(newer2) is True)
store.kv_get = lambda k, d=None: d
check("first publish allowed when none exists",
      sp._is_newer_than_published(older) is True)
store.kv_get = orig_kv_get

# ── T5: Module runner isolates failures ──────────────────────────────────────
print("== Module isolation ==")
m = sp._run_module("boom", lambda: (_ for _ in ()).throw(RuntimeError("x")))
check("module failure captured", m["status"] == "FAILED" and m["error"] == "x")
ok = sp._run_module("fine", lambda: "done")
check("module success captured", ok["status"] == "OK" and ok["error"] is None)
check("module durations recorded",
      isinstance(m["duration_s"], float) and isinstance(ok["duration_s"], float))

# ── T6: Scheduler state enrichment persists new fields ───────────────────────
print("== Scheduler state ==")
health0 = store.get_scheduler_health()
store.update_scheduler_state(owner="test-host:123", last_trigger="TEST",
                             last_error=None,
                             heartbeat_at="2026-07-17T00:00:00Z")
h = store.get_scheduler_health()
check("owner persisted", h.get("owner") == "test-host:123")
check("last_trigger persisted", h.get("last_trigger") == "TEST")
check("heartbeat persisted", str(h.get("heartbeat_at") or "").startswith("2026-07-17"))
check("health verdict present",
      h.get("health") in ("HEALTHY", "DEGRADED", "DOWN", "UNKNOWN", "DISABLED"))
# restore previous owner-ish fields so live health display is not polluted
store.update_scheduler_state(owner=health0.get("owner"),
                             last_trigger=health0.get("last_trigger"),
                             heartbeat_at=health0.get("heartbeat_at"))

# ── T7: bundle_status shape ──────────────────────────────────────────────────
print("== bundle_status ==")
bs = sp.bundle_status()
check("bundle_status returns dict", isinstance(bs, dict))
for key in ("published_bundle", "last_attempt", "canonical_scan",
            "bundle_matches_canonical_scan", "label"):
    check(f"bundle_status has {key}", key in bs)
check("research-only label", bs.get("label") == "PAPER / RESEARCH ONLY")

# ── T8: Pipeline never enables trading ───────────────────────────────────────
print("== Safety ==")
src = open("scan_pipeline.py").read()
check("execute_trades always False in pipeline",
      "execute_trades=False" in src and "execute_trades=True" not in src)
for bad_call in ("place_order", "kite.order", "modify_order", "cancel_order"):
    check(f"no live-order call: {bad_call}", bad_call not in src)

print(f"\nPhase 22 pipeline tests: {PASS} passed, {FAIL} failed")
sys.exit(1 if FAIL else 0)
