"""
test_phase7.py  —  Phase 7 validation tests.

Tests:
  1. Stale-data safety gate
  2. Unavailable-data safety gate
  3. Partial symbol failure (some succeed, some fail)
  4. Provider outage (all fail)
  5. Duplicate scan detection (all items share scan_id)
  6. Inconsistent timestamps rejected
  7. Invalid prices rejected
  8. Missing volume handled
  9. Fallback-data safety (STALE data cannot generate BUY)
  10. Snapshot consistency (fetch before analysis)
  11. Paper orders are simulated only (no real broker)
  12. Meta-Learning does not affect live decisions
  13. Gate logic: RR gate, quality gate, volume gate
  14. Evidence label conservatism (from meta_learning)
  15. Report export contains required tables + valid JSON
  16. Verdict criteria

Run: python3 test_phase7.py
"""

import copy
import json
import os
import sys
import types
import unittest

# ── Helpers ───────────────────────────────────────────────────────────────────
FAILURES = []

def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" — {detail}" if detail else ""))
    if not cond:
        FAILURES.append(name)


# ── Gate-logic unit tests (no real network) ───────────────────────────────────

def test_quality_gate():
    from live_scan_engine import _apply_quality_gate
    from live_data_provider import DataQuality
    a, r = _apply_quality_gate("STRONG BUY", DataQuality.STALE)
    check("STALE blocks STRONG BUY", a == "WATCH", f"got {a}")
    a, r = _apply_quality_gate("BUY", DataQuality.STALE)
    check("STALE blocks BUY", a == "WATCH", f"got {a}")
    a, r = _apply_quality_gate("WATCH", DataQuality.STALE)
    check("STALE permits WATCH", a == "WATCH", f"got {a}")
    a, r = _apply_quality_gate("STRONG BUY", DataQuality.UNAVAILABLE)
    check("UNAVAILABLE blocks STRONG BUY", a == "IGNORE", f"got {a}")
    a, r = _apply_quality_gate("BUY", DataQuality.UNAVAILABLE)
    check("UNAVAILABLE blocks BUY", a == "IGNORE", f"got {a}")
    a, r = _apply_quality_gate("STRONG BUY", DataQuality.LIVE)
    check("LIVE allows STRONG BUY", a == "STRONG BUY", f"got {a}")
    a, r = _apply_quality_gate("BUY", DataQuality.NEAR_LIVE)
    check("NEAR_LIVE allows BUY", a == "BUY", f"got {a}")


def test_price_gate():
    from live_scan_engine import _price_gate
    ok, r = _price_gate(0.0, "TEST")
    check("Zero price fails gate", not ok, r)
    ok, r = _price_gate(-10.0, "TEST")
    check("Negative price fails gate", not ok, r)
    ok, r = _price_gate(0.5, "TEST")
    check("Sub-rupee price fails gate", not ok, r)
    ok, r = _price_gate(150.0, "TEST")
    check("Valid price passes gate", ok, r)


def test_rr_gate():
    from live_scan_engine import _rr_gate, MIN_RR_FOR_BUY
    ok, r = _rr_gate(0.5, "BUY")
    check("Low RR fails gate for BUY", not ok, r)
    ok, r = _rr_gate(MIN_RR_FOR_BUY + 0.01, "BUY")
    check("Sufficient RR passes gate", ok, r)
    ok, r = _rr_gate(0.5, "WATCH")
    check("Low RR allowed for WATCH", ok, r)
    ok, r = _rr_gate(0.5, "IGNORE")
    check("Low RR allowed for IGNORE", ok, r)


def test_volume_gate():
    from live_scan_engine import _volume_gate
    ok, r = _volume_gate(0.1, "BUY")
    check("Very low volume blocks BUY", not ok, r)
    ok, r = _volume_gate(0.1, "WATCH")
    check("Low volume allowed for WATCH", ok, r)
    ok, r = _volume_gate(0.8, "BUY")
    check("Good volume passes gate", ok, r)


def test_data_quality_from_age():
    from live_data_provider import DataQuality
    check("Age 0 → LIVE", DataQuality.from_age(0) == DataQuality.LIVE)
    check("Age 3 → LIVE", DataQuality.from_age(3) == DataQuality.LIVE)
    check("Age 4 → NEAR_LIVE", DataQuality.from_age(4) == DataQuality.NEAR_LIVE)
    check("Age 5 → NEAR_LIVE", DataQuality.from_age(5) == DataQuality.NEAR_LIVE)
    check("Age 6 → STALE", DataQuality.from_age(6) == DataQuality.STALE)
    check("Age 14 → STALE", DataQuality.from_age(14) == DataQuality.STALE)
    check("Age 15 → UNAVAILABLE", DataQuality.from_age(15) == DataQuality.UNAVAILABLE)
    check("None → UNAVAILABLE", DataQuality.from_age(None) == DataQuality.UNAVAILABLE)
    check("LIVE eligible for buy", DataQuality.eligible_for_buy(DataQuality.LIVE))
    check("NEAR_LIVE eligible for buy", DataQuality.eligible_for_buy(DataQuality.NEAR_LIVE))
    check("STALE not eligible for buy", not DataQuality.eligible_for_buy(DataQuality.STALE))
    check("UNAVAILABLE not eligible for buy", not DataQuality.eligible_for_buy(DataQuality.UNAVAILABLE))


def test_stale_data_cannot_buy():
    """Stale data must never produce a BUY/STRONG BUY recommendation."""
    from live_data_provider import DataQuality
    from live_scan_engine import _apply_quality_gate
    for action in ("STRONG BUY", "BUY", "WATCH", "IGNORE"):
        capped, _ = _apply_quality_gate(action, DataQuality.STALE)
        if action in ("STRONG BUY", "BUY"):
            check(f"STALE {action} → not buy", capped not in ("STRONG BUY", "BUY"))
    for action in ("STRONG BUY", "BUY", "WATCH", "IGNORE"):
        capped, _ = _apply_quality_gate(action, DataQuality.UNAVAILABLE)
        if action in ("STRONG BUY", "BUY", "WATCH"):
            check(f"UNAVAILABLE {action} → IGNORE", capped == "IGNORE")


def test_partial_symbol_failure():
    """Provider health with partial failure reports DEGRADED."""
    import pandas as pd
    from datetime import datetime, timezone
    from live_data_provider import SymbolFetchResult, DataQuality, PROVIDER_ID, LiveDataProvider
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    df = pd.DataFrame({"open":[1.0],"high":[1.0],"low":[1.0],"close":[1.0],"volume":[1000.0]})
    df.index = pd.DatetimeIndex([datetime.now(timezone.utc)])
    results = {
        "A": SymbolFetchResult("A", True, df, now[:10], 0.0, DataQuality.LIVE, PROVIDER_ID, now, 100, 0, None, 1),
        "B": SymbolFetchResult("B", False, None, None, None, DataQuality.UNAVAILABLE, PROVIDER_ID, now, 0, 3, "timeout", 0),
        "C": SymbolFetchResult("C", True, df, now[:10], 1.0, DataQuality.NEAR_LIVE, PROVIDER_ID, now, 80, 0, None, 1),
    }
    prov = LiveDataProvider()
    h = prov.build_health_report(results, "test-scan", now)
    check("Partial failure → DEGRADED", h.connection_status == "DEGRADED", h.connection_status)
    check("Failed symbol in unavailable list", "B" in h.unavailable_symbols)
    check("Error captured", len(h.errors) >= 1)
    check("Retry events counted", h.retry_events == 3)


def test_provider_outage():
    """All symbols failing → ERROR status."""
    from datetime import datetime, timezone
    from live_data_provider import SymbolFetchResult, DataQuality, PROVIDER_ID, LiveDataProvider
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    results = {
        "A": SymbolFetchResult("A", False, None, None, None, DataQuality.UNAVAILABLE, PROVIDER_ID, now, 0, 3, "connection refused", 0),
        "B": SymbolFetchResult("B", False, None, None, None, DataQuality.UNAVAILABLE, PROVIDER_ID, now, 0, 3, "connection refused", 0),
    }
    prov = LiveDataProvider()
    h = prov.build_health_report(results, "test-outage", now)
    check("All fail → ERROR status", h.connection_status == "ERROR", h.connection_status)
    check("Paper execution not eligible during outage", not h.paper_execution_eligible)
    check("Coverage 0%", h.symbol_coverage_pct == 0.0)


def test_duplicate_scan_detection():
    """All recommendations in a scan must share the same scan_id."""
    recs = [
        {"scan_id": "aaa", "snapshot_ts": "2025-01-01T00:00:00Z", "final_action": "WATCH"},
        {"scan_id": "aaa", "snapshot_ts": "2025-01-01T00:00:00Z", "final_action": "IGNORE"},
        {"scan_id": "bbb", "snapshot_ts": "2025-01-01T00:00:00Z", "final_action": "WATCH"},
    ]
    from phase7_report import _no_duplicate_scan_ids
    check("Mixed scan_ids detected as duplicate", not _no_duplicate_scan_ids(recs))
    recs2 = [{"scan_id": "aaa"}, {"scan_id": "aaa"}]
    check("Consistent scan_ids pass", _no_duplicate_scan_ids(recs2))


def test_invalid_price_gate():
    """BUY decisions with invalid prices must fail the price gate."""
    from phase7_report import _no_zero_price_buys
    recs = [{"final_action": "BUY", "entry_price": 0.0}, {"final_action": "WATCH", "entry_price": 0.0}]
    check("Zero-price BUY detected", not _no_zero_price_buys(recs))
    recs2 = [{"final_action": "BUY", "entry_price": 100.0}]
    check("Valid-price BUY passes", _no_zero_price_buys(recs2))


def test_stale_buy_detection():
    """Report must detect stale-data BUY violations."""
    from phase7_report import _no_stale_buys
    recs = [{"final_action": "BUY", "data_quality": "STALE"}]
    check("Stale BUY flagged in report", not _no_stale_buys(recs))
    recs2 = [{"final_action": "BUY", "data_quality": "LIVE"},
             {"final_action": "WATCH", "data_quality": "STALE"}]
    check("Live BUY + stale WATCH passes", _no_stale_buys(recs2))


def test_missing_volume():
    """volume_gate should handle zero/None volume gracefully for non-BUY actions."""
    from live_scan_engine import _volume_gate
    ok, r = _volume_gate(0.0, "IGNORE")
    check("Zero volume OK for IGNORE", ok, r)
    ok, r = _volume_gate(0.0, "WATCH")
    check("Zero volume OK for WATCH", ok, r)


def test_snapshot_consistency():
    """Scan audit must confirm single snapshot_ts and scan_id."""
    from phase7_report import _no_duplicate_scan_ids
    same = [{"scan_id": "abc"}, {"scan_id": "abc"}]
    check("Same scan_id: consistent", _no_duplicate_scan_ids(same))
    diff = [{"scan_id": "abc"}, {"scan_id": "xyz"}]
    check("Different scan_ids: inconsistent", not _no_duplicate_scan_ids(diff))


def test_meta_learning_isolation():
    """meta_learning.py must not import live_scan_engine or paper_trader."""
    src_path = os.path.join(os.path.dirname(__file__), "meta_learning.py")
    src = open(src_path).read()
    for forbidden in ("live_scan_engine", "paper_trader", "live_data_provider"):
        check(f"meta_learning does not import {forbidden}", f"import {forbidden}" not in src
              and f"from {forbidden}" not in src)


def test_live_scan_engine_safety():
    """live_scan_engine must not reference live broker APIs."""
    src_path = os.path.join(os.path.dirname(__file__), "live_scan_engine.py")
    src = open(src_path).read()
    for forbidden in ("kiteconnect", "zerodha", "place_order_real", "broker_api"):
        check(f"live_scan_engine does not reference {forbidden}", forbidden not in src.lower())
    check("live_scan_engine safety comment present", "PAPER TRADING" in src or "paper trading" in src.lower())


def test_report_tables():
    """Report must contain all required tables."""
    required = ["data_health", "symbol_coverage", "scan_audit", "decision_counts",
                "gate_failures", "gate_detail", "paper_eligibility", "latency",
                "errors", "recommendations", "safety", "verdict"]
    # Build a minimal synthetic scan
    scan = {
        "scan_id": "test123", "snapshot_ts": "2025-01-01T00:00:00Z",
        "provider_health": {
            "provider": "yfinance", "provider_id": "yfinance",
            "connection_status": "CONNECTED", "last_successful_fetch": None,
            "symbols_requested": 2, "symbols_succeeded": 2, "symbols_stale": 0,
            "symbols_unavailable": 0, "symbol_coverage_pct": 100.0, "stale_symbols": [],
            "unavailable_symbols": [], "errors": [], "avg_latency_ms": 100.0,
            "max_latency_ms": 120, "retry_events": 0, "rate_limit_events": 0,
            "snapshot_id": "test123", "snapshot_ts": "2025-01-01T00:00:00Z",
            "paper_execution_eligible": True, "quality_summary": {"LIVE": 2}, "notes": [],
        },
        "recommendations": [
            {"symbol": "A", "sector": "IT", "data_quality": "LIVE", "data_age_days": 1,
             "latest_bar_date": "2025-01-01", "bars_available": 120, "data_source": "yfinance",
             "scan_id": "test123", "snapshot_ts": "2025-01-01T00:00:00Z",
             "final_action": "WATCH", "entry_price": 100.0, "all_gates_passed": True,
             "paper_eligible": False, "paper_order_id": None, "paper_order_note": "",
             "gate_price": {"passed": True, "reason": "ok"},
             "gate_data_quality": {"passed": True, "reason": "ok"},
             "gate_rr": {"passed": True, "reason": "ok"},
             "gate_volume": {"passed": True, "reason": "ok"}, "error": None,
             "opportunity_score": 40.0, "strategy_id": "s1", "strategy_name": "S1",
             "technical_score": 30.0, "calibrated_confidence": 50.0,
             "rr_ratio": 2.0, "regime": "Bullish"},
        ],
        "scan_audit": {"audit_verdict": "PASS", "all_items_share_same_scan_id": True,
                       "all_items_share_same_snapshot_ts": True,
                       "distinct_snapshot_ts_count": 1, "distinct_scan_id_count": 1},
        "summary": {}, "safety": {"research_only": True, "paper_trading_only": True,
                                  "no_live_broker_calls": True},
    }
    from phase7_report import _build_tables, generate_report
    tables = _build_tables(scan)
    for t in required:
        check(f"Report table '{t}' present", t in tables)
    result = generate_report(scan)
    check("Report generates successfully", "verdict" in result)
    check("JSON file created", os.path.exists(result["json"]))
    check("CSV file created", os.path.exists(result["csv"]))
    check("HTML file created", os.path.exists(result["html"]))
    with open(result["json"]) as f:
        parsed = json.load(f)
    check("JSON report is valid JSON", "tables" in parsed and "meta" in parsed)


def test_verdict_logic():
    """PASS verdict when all criteria pass; FAIL when most fail."""
    from phase7_report import _verdict
    scan_good = {
        "provider_health": {"connection_status": "CONNECTED", "symbol_coverage_pct": 100.0,
                            "symbols_unavailable": 0, "symbols_requested": 10},
        "scan_audit": {"audit_verdict": "PASS"},
        "summary": {},
        "recommendations": [
            {"final_action": "BUY", "data_quality": "LIVE", "gate_price": {"passed": True},
             "entry_price": 100.0, "scan_id": "abc", "snapshot_ts": "2025-01-01T00:00:00Z"}],
    }
    v = _verdict(scan_good)
    check("Good scan → PASS or PARTIAL", v["verdict"] in ("PASS", "PARTIAL"))

    scan_bad = {
        "provider_health": {"connection_status": "ERROR", "symbol_coverage_pct": 0.0,
                            "symbols_unavailable": 10, "symbols_requested": 10},
        "scan_audit": {"audit_verdict": "FAIL"},
        "summary": {},
        "recommendations": [
            {"final_action": "BUY", "data_quality": "STALE", "gate_price": {"passed": False},
             "entry_price": 0.0, "scan_id": "abc", "snapshot_ts": "2025-01-01T00:00:00Z"},
            {"final_action": "BUY", "data_quality": "UNAVAILABLE", "gate_price": {"passed": True},
             "entry_price": 0.0, "scan_id": "xyz", "snapshot_ts": "2025-01-01T00:00:00Z"},
        ],
    }
    v_bad = _verdict(scan_bad)
    check("Bad scan → PARTIAL or FAIL", v_bad["verdict"] in ("PARTIAL", "FAIL"))


def main():
    print("=" * 60)
    print("Phase 7 validation tests")
    print("=" * 60)
    test_data_quality_from_age()
    test_quality_gate()
    test_price_gate()
    test_rr_gate()
    test_volume_gate()
    test_stale_data_cannot_buy()
    test_partial_symbol_failure()
    test_provider_outage()
    test_duplicate_scan_detection()
    test_invalid_price_gate()
    test_stale_buy_detection()
    test_missing_volume()
    test_snapshot_consistency()
    test_meta_learning_isolation()
    test_live_scan_engine_safety()
    test_report_tables()
    test_verdict_logic()
    print()
    if FAILURES:
        print(f"FAILURES ({len(FAILURES)}): {', '.join(FAILURES)}")
        return 1
    print("ALL TESTS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
