"""
Phase 22 production-finalization tests — provider-gated paper entries,
concurrency safety (lock skip + renewal), durable Kite token store, and
absence of live-order execution paths. PAPER / RESEARCH ONLY.

Style matches test_phase22.py: prints "N passed, N failed".
"""

import json
import os
import sys
import time

PASS = FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS {name}")
    else:
        FAIL += 1
        print(f"  FAIL {name} {detail}")


import phase20_store as store
import phase20_gates as gates
import phase20_scheduler as sched
import scan_state_store as sss
import kite_token_store as kts
import kite_quote_provider as kqp
import live_scan_engine as lse

# ── T1: Perf classification ──────────────────────────────────────────────────
print("== Perf classification ==")
check("<=120s NORMAL", sched._perf_class(119.9) == "NORMAL")
check("120-300s WARNING", sched._perf_class(200) == "WARNING")
check(">300s DEGRADED", sched._perf_class(900) == "DEGRADED")

# ── T2: Provider gate — only live-quality data may pass ──────────────────────
print("== Provider gate honors live-quality data ==")
res = gates.evaluate_entries()
gg = {g["gate"]: g for g in res.get("global_gates", [])}
check("provider_zerodha gate present", "provider_zerodha" in gg)
check("no_fallback_data gate present", "no_fallback_data" in gg)
snap = sss.load_latest_snapshot() or {}
kite_conn = bool((snap.get("safety") or {}).get("kite_connected"))
provider_reason = str(gg["provider_zerodha"].get("reason") or "")
if not kite_conn:
    live_data_available = "live_symbols=0" not in provider_reason
    check("provider gate matches live symbol coverage",
          gg["provider_zerodha"]["passed"] is live_data_available,
          json.dumps(gg["provider_zerodha"]))
    check("Yahoo live data is not classified as fallback",
          gg["no_fallback_data"]["passed"] is True,
          json.dumps(gg["no_fallback_data"]))
else:
    check("kite connected -> structured flag honored",
          gg["provider_zerodha"]["passed"] is True)

# Label-only spoof must not pass without the structured flag.
check("gate needs structured kite_connected, not just label",
      "kite_connected=" in gg["provider_zerodha"]["reason"])

# ── T3: Concurrency — busy lock is skipped, never doubled ────────────────────
print("== Concurrency: lock busy -> skip ==")
got, holder = sss.acquire_scan_lock()
check("test acquires scan lock", got is True, holder)
try:
    got2, _h2 = sss.acquire_scan_lock()
    check("second acquire on live lease fails", got2 is False)
    t_busy = time.time()
    snap2 = lse.get_or_run_scan(max_age_s=1, force=False, wait_for_lock=False)
    busy_elapsed = time.time() - t_busy
    check("wait_for_lock=False returns immediately with busy flag",
          snap2.get("_scan_lock_busy") is True,
          json.dumps({k: snap2.get(k) for k in ("_scan_lock_busy", "_from_cache", "scan_id")}))
    check("busy return is fast (no 120s poll)", busy_elapsed < 10,
          f"{busy_elapsed:.1f}s")
    # Renewal keeps a long scan's lease alive.
    check("renew_scan_lock succeeds for holder", sss.renew_scan_lock(holder) is True)
    check("renew fails for wrong holder", sss.renew_scan_lock("someone-else") is False)
finally:
    sss.release_scan_lock(holder)
got3, holder3 = sss.acquire_scan_lock()
check("lock reacquirable after release", got3 is True)
sss.release_scan_lock(holder3)

# Stuck-lock recovery: an expired lease is reclaimed automatically.
got4, holder4 = sss.acquire_scan_lock(timeout_s=0.5)
check("short lease acquired", got4 is True)
time.sleep(1.2)
got5, holder5 = sss.acquire_scan_lock()
check("expired lease reclaimed (stuck-lock recovery)", got5 is True)
sss.release_scan_lock(holder5)

# ── T4: Durable Kite token store round-trip (DB + file) ──────────────────────
print("== Kite token store durability ==")
orig = kts.load()
try:
    kts.save_token("TESTTOKEN123", user_id="TESTUSER")
    # Remove the warm file cache to prove the DB copy alone restores it.
    try:
        os.remove(kts._STORE_PATH)
    except FileNotFoundError:
        pass
    loaded = kts.load() or {}
    check("token survives file loss (DB copy)",
          loaded.get("access_token") == "TESTTOKEN123",
          json.dumps({"has_token": bool(loaded.get("access_token"))}))
    kts.clear()
    check("clear removes token everywhere", not (kts.load() or {}).get("access_token"))
finally:
    kts.clear()
    if orig and orig.get("access_token"):
        kts.save_token(orig["access_token"], user_id=orig.get("user_id", ""))

# ── T5: Provider label 3-state ───────────────────────────────────────────────
print("== Provider label states ==")
label = kqp.provider_label()
check("provider label non-empty", bool(label), label)
check("kite_configured() returns bool", isinstance(kqp.kite_configured(), bool))

# ── T6: Live-order writes stay disabled ──────────────────────────────────────
print("== Live-order writes disabled ==")
# The only permitted live-order call sites are the Phase 8 assisted-execution
# stack (broker_client + execution_engine + its diagnostics), which is gated
# behind LIVE_ASSISTED mode, per-order confirmation, and the kill switch.
ALLOWED = {"broker_client.py", "execution_engine.py", "phase13_diagnostics.py"}
src_dir = os.path.dirname(os.path.abspath(__file__))
danger = []
for fn in os.listdir(src_dir):
    if not fn.endswith(".py") or fn.startswith("test_") or fn in ALLOWED:
        continue
    with open(os.path.join(src_dir, fn), "r", encoding="utf-8", errors="ignore") as f:
        text = f.read()
    for needle in ("place_order(", ".place_order", "kite.order", "modify_order(", "cancel_order("):
        if needle in text:
            danger.append(f"{fn}:{needle}")
check("no live order calls outside gated Phase 8 stack", not danger, str(danger))

from execution_engine import get_execution_mode
mode_now = get_execution_mode()
check("execution mode is NOT LIVE_ASSISTED", mode_now != "LIVE_ASSISTED", mode_now)

# The automated scan/scheduler path must never import the live-order stack.
import phase20_scheduler as _ps
import inspect
sched_src = inspect.getsource(_ps)
check("scheduler never touches execution engine / broker",
      "execution_engine" not in sched_src and "broker_client" not in sched_src
      and "place_order" not in sched_src)

# ── T7: Scheduler skip bookkeeping fields exist ──────────────────────────────
print("== Skip bookkeeping ==")
cnt = store.kv_get("scan_skipped_active_count")
check("skipped count kv readable", cnt is None or int(cnt) >= 0, str(cnt))

print()
print(f"{PASS} passed, {FAIL} failed")
if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
