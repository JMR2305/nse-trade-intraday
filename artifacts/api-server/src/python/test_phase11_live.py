"""
test_phase11_live.py — Phase 11: Live Data Foundation & Real-Time Refresh.

20 automated tests covering:
  - IST market-hours state machine (open/pre-open/post-close/closed/weekend/holiday)
  - next_transition correctness
  - quote provider whitelist + symbol validation
  - TTL cache behaviour (open vs closed TTLs, persisted quote state)
  - circuit breaker open/half-open logic
  - honest normalization (NaN/None never fabricated)
  - system-event notifications with dedup/cooldown
  - diagnostic bundle JSON + summary CSV generation
  - main.py command dispatch for new Phase 11 commands

Isolated temp files are used wherever persistence is involved — never
pollutes real alert or quote-state files. No network calls are made.
Strictly paper/research.

Run: python3 test_phase11_live.py
"""

import csv
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime, date

_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _DIR)

import market_hours as mh
import live_quote_service as lqs
import copilot_engine as ce
import phase11_diagnostics as diag

PASS = 0
FAIL = 0
FAILURES = []


def check(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✓ {name}")
    else:
        FAIL += 1
        FAILURES.append(f"{name}: {detail}")
        print(f"  ✗ {name} — {detail}")


IST = mh.IST


def ist(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=IST)


print("── Market hours state machine ──")

# 1. Regular open hours (Wed 2026-07-15 11:00 IST)
check("T01 market OPEN during session",
      mh.market_state(ist(2026, 7, 15, 11, 0)) == "OPEN",
      f"got {mh.market_state(ist(2026, 7, 15, 11, 0))}")

# 2. Pre-open window
check("T02 PRE_OPEN at 09:05 IST",
      mh.market_state(ist(2026, 7, 15, 9, 5)) == "PRE_OPEN",
      f"got {mh.market_state(ist(2026, 7, 15, 9, 5))}")

# 3. Post-close window
check("T03 POST_CLOSE at 15:45 IST",
      mh.market_state(ist(2026, 7, 15, 15, 45)) == "POST_CLOSE",
      f"got {mh.market_state(ist(2026, 7, 15, 15, 45))}")

# 4. Closed at night
check("T04 CLOSED at 20:00 IST",
      mh.market_state(ist(2026, 7, 15, 20, 0)) == "CLOSED",
      f"got {mh.market_state(ist(2026, 7, 15, 20, 0))}")

# 5. Weekend
check("T05 WEEKEND on Saturday",
      mh.market_state(ist(2026, 7, 18, 11, 0)) == "WEEKEND",
      f"got {mh.market_state(ist(2026, 7, 18, 11, 0))}")

# 6. Holiday — first weekday holiday from the calendar
_holidays = mh._load_holidays()
_weekday_holiday = None
for iso in sorted(_holidays):
    d = date.fromisoformat(iso)
    if d.weekday() < 5:
        _weekday_holiday = d
        break
if _weekday_holiday:
    st = mh.market_state(ist(_weekday_holiday.year, _weekday_holiday.month, _weekday_holiday.day, 11, 0))
    check("T06 HOLIDAY on weekday holiday", st == "HOLIDAY",
          f"{_weekday_holiday} → {st}")
else:
    check("T06 HOLIDAY on weekday holiday", False, "no weekday holiday in calendar")

# 7. next_transition from mid-session points to market_close (same day 15:30)
nt = mh.next_transition(ist(2026, 7, 15, 11, 0))
check("T07 next_transition mid-session is market_close",
      nt["event"] == "market_close" and nt["at_ist"].startswith("2026-07-15T15:30")
      and nt["seconds_until"] == 4.5 * 3600,
      json.dumps(nt, default=str))

# 8. next_transition on Friday night skips the weekend to Monday open
nt2 = mh.next_transition(ist(2026, 7, 17, 20, 0))  # Friday
check("T08 next_transition skips weekend",
      nt2["event"] == "market_open" and nt2["at_ist"].startswith("2026-07-20T09:15"),
      json.dumps(nt2, default=str))

# 9. market_status payload shape (honest fields present)
ms = mh.market_status()
check("T09 market_status payload complete",
      all(k in ms for k in ("state", "is_open", "now_ist", "timezone",
                            "next_transition", "holiday_today", "session"))
      and ms["timezone"] == "Asia/Kolkata",
      json.dumps(ms, default=str)[:200])

print("── Quote provider & whitelist ──")

# 10. Whitelist accepts NIFTY 50 + indices
check("T10 whitelist accepts valid symbols",
      lqs.is_allowed_symbol("RELIANCE") and lqs.is_allowed_symbol("NIFTY")
      and lqs.is_allowed_symbol("banknifty"),
      "valid symbol rejected")

# 11. Whitelist rejects injection / unknown symbols
check("T11 whitelist rejects bad symbols",
      not lqs.is_allowed_symbol("EVIL;RM -RF") and not lqs.is_allowed_symbol("FAKEQUITY")
      and not lqs.is_allowed_symbol(""),
      "bad symbol accepted")

# 12. TTL config: open TTL much shorter than closed TTL
check("T12 TTL adapts to market state",
      lqs.QUOTE_TTL_S < lqs.QUOTE_TTL_CLOSED_S and lqs.QUOTE_TTL_S <= 60,
      f"open={lqs.QUOTE_TTL_S} closed={lqs.QUOTE_TTL_CLOSED_S}")

# 13. Honest number cleaning: NaN/inf/None → None, never fabricated
check("T13 honest numeric normalization",
      lqs._clean(float("nan")) is None and lqs._clean(float("inf")) is None
      and lqs._clean(None) is None and lqs._clean("junk") is None
      and lqs._clean("123.45678") == 123.4568,
      "fabricated or wrong value from _clean")

# Isolate quote state for cache/breaker tests
_tmp = tempfile.mkdtemp(prefix="phase11_live_test_")
lqs.STATE_FILE = os.path.join(_tmp, "quote_state.json")

# 14. get_quotes serves fresh cache within TTL without a provider call
_now = time.time()
_seed_quote = {"symbol": "NIFTY", "ltp": 24000.0, "prev_close": 23900.0,
               "change": 100.0, "change_pct": 0.4184, "day_high": None,
               "day_low": None, "volume": None, "currency": "INR",
               "source": "yfinance", "fetch_ts": lqs._utc_now_iso(),
               "latency_ms": 5, "quality": "NEAR_LIVE", "error": None}
lqs._save_state({"cache": {"NIFTY": {"cached_at": _now, "quote": _seed_quote}},
                 "breaker": {"failures": 0, "opened_at": None},
                 "last_success_ts": None, "fetch_count": 0, "error_count": 0})


class _BoomProvider(lqs.QuoteProvider):
    provider_id = "boom"
    provider_name = "Exploding Test Provider"
    calls = 0

    def fetch_quote(self, symbol):
        _BoomProvider.calls += 1
        raise AssertionError("provider must not be called on cache hit")


_orig_provider = lqs.YFinanceQuoteProvider
lqs.YFinanceQuoteProvider = _BoomProvider
try:
    r = lqs.get_quotes(["NIFTY"])
    q = r["quotes"]["NIFTY"]
    check("T14 fresh cache hit avoids provider call",
          _BoomProvider.calls == 0 and q["from_cache"] is True and q["ltp"] == 24000.0,
          f"calls={_BoomProvider.calls} q={json.dumps(q)[:150]}")
finally:
    lqs.YFinanceQuoteProvider = _orig_provider

# 15. Unknown symbols are rejected in batch calls
lqs.YFinanceQuoteProvider = _BoomProvider
try:
    r = lqs.get_quotes(["NOTREAL123"])
    check("T15 batch rejects non-whitelist symbols",
          r["rejected_symbols"] == ["NOTREAL123"] and r["quotes"] == {},
          json.dumps(r["rejected_symbols"]))
finally:
    lqs.YFinanceQuoteProvider = _orig_provider

# 16. Circuit breaker: opens after threshold, serves stale cache honestly
_state = lqs._load_state()
_state["breaker"] = {"failures": lqs.CB_FAILURE_THRESHOLD, "opened_at": time.time()}
# expire the cache so the breaker path (stale serve) is exercised
_state["cache"]["NIFTY"]["cached_at"] = time.time() - 10_000
lqs._save_state(_state)
check("T16a breaker reports OPEN", lqs._breaker_open(_state), json.dumps(_state["breaker"]))
lqs.YFinanceQuoteProvider = _BoomProvider
_BoomProvider.calls = 0
try:
    r = lqs.get_quotes(["NIFTY"])
    q = r["quotes"]["NIFTY"]
    check("T16 breaker serves stale cache with honest STALE flag",
          _BoomProvider.calls == 0 and q["quality"] == "STALE"
          and "Circuit breaker" in str(q["error"]) and q["ltp"] == 24000.0,
          json.dumps(q)[:200])
finally:
    lqs.YFinanceQuoteProvider = _orig_provider

# 17. Breaker half-opens after cooldown expiry
_state = lqs._load_state()
_state["breaker"]["opened_at"] = time.time() - (lqs.CB_COOLDOWN_S + 5)
check("T17 breaker half-open after cooldown",
      not lqs._breaker_open(_state), json.dumps(_state["breaker"]))

print("── System events (notifications) ──")

ce.ALERTS_FILE = os.path.join(_tmp, "alerts.json")

# 18. record_system_event creates alert then dedups within cooldown;
#     unknown types rejected honestly
r1 = ce.record_system_event("DATA_DISCONNECTED", reason="test disconnect")
r2 = ce.record_system_event("DATA_DISCONNECTED", reason="again")
r3 = ce.record_system_event("MADE_UP_EVENT")
check("T18 system event dedup + unknown-type rejection",
      r1.get("success") and not r1.get("suppressed")
      and r2.get("success") and r2.get("suppressed") is True
      and r3.get("success") is False and "Unknown" in str(r3.get("error")),
      f"r1={r1.get('suppressed')} r2={r2.get('suppressed')} r3={r3}")

print("── Diagnostic bundle & CLI dispatch ──")

# 19. Bundle builds JSON + CSV with honest fields
bundle = diag.build_diagnostic_bundle()
json_ok = os.path.exists(os.path.join(_DIR, "phase11_diagnostic_bundle.json"))
csv_path = os.path.join(_DIR, "phase11_summary.csv")
rows = []
if os.path.exists(csv_path):
    with open(csv_path) as f:
        rows = list(csv.reader(f))
check("T19 diagnostic bundle JSON + CSV written",
      json_ok and len(rows) >= 2
      and bundle.get("engine_version") == diag.RESEARCH_ENGINE_VERSION
      and "market_status" in bundle,
      f"json={json_ok} rows={len(rows)} keys={list(bundle)[:8]}")

# 20. main.py dispatch for Phase 11 market_status command
proc = subprocess.run(
    [sys.executable, os.path.join(_DIR, "main.py"), "market_status"],
    capture_output=True, text=True, cwd=_DIR, timeout=60,
)
try:
    out = json.loads(proc.stdout.strip())
except Exception:
    out = {}
check("T20 main.py market_status command dispatch",
      proc.returncode == 0 and out.get("success") is True and "state" in out,
      f"rc={proc.returncode} out={proc.stdout[:200]}")

print()
total = PASS + FAIL
print(f"Phase 11 Live Data tests: {PASS} passed, {FAIL} failed of {total}")
if __name__ == "__main__":
    if FAILURES:
        for f in FAILURES:
            print(f"  FAIL: {f}")
        sys.exit(1)
    sys.exit(0)
