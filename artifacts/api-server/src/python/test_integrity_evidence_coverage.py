"""
test_integrity_evidence_coverage.py
─────────────────────────────────────
Focused tests for check #10 ("Evidence Coverage") in
get_pipeline_integrity_check().

Proves:
  1. When >30% of scan symbols have <5 backtest trades the check is WARN.
  2. When ≤30% of scan symbols have <5 backtest trades the check is PASS.
  3. When the snapshot has no valid items the check is WARN.
  4. When no snapshot exists at all the check is WARN.
  5. "Evidence Coverage" is the 10th check entry in the returned list
     (index 9), confirming it has not been moved or removed.
  6. The WARN reason text mentions the count of low-evidence symbols.
  7. The PASS reason text confirms the low-evidence count is within range.
"""

import sys
import os
import unittest
from unittest.mock import MagicMock, patch

# ── Path setup ────────────────────────────────────────────────────────────────

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)


# ── Snapshot helpers ──────────────────────────────────────────────────────────

def _make_snapshot(items: list[dict]) -> dict:
    """Build a minimal scan snapshot payload."""
    return {"recommendations": items}


def _low_ev_item(symbol: str, trades: int = 2) -> dict:
    """Recommendation with fewer than 5 trades (thin evidence)."""
    return {"stock": symbol, "total_trades": trades, "error": None}


def _high_ev_item(symbol: str, trades: int = 20) -> dict:
    """Recommendation with ≥5 trades (sufficient evidence)."""
    return {"stock": symbol, "total_trades": trades, "error": None}


def _error_item(symbol: str) -> dict:
    """Item that failed during scan (should be excluded from denominator)."""
    return {"stock": symbol, "total_trades": 0, "error": "fetch failed"}


# ── Shared mock context ───────────────────────────────────────────────────────

def _mock_modules() -> dict:
    """
    sys.modules patches that satisfy all imports inside
    get_pipeline_integrity_check() *except* scan_state_store
    (which we patch separately per test to control snapshot data).
    """
    return {
        "research_agent": MagicMock(),
        "research_agent.shared_services": MagicMock(
            get_research_snapshot=MagicMock(return_value={"available": True,
                                                          "last_failure_at": None})
        ),
        "phase20_gates": MagicMock(
            get_last_evaluation=MagicMock(return_value={
                "global_pass": True,
                "candidates": [],
                "eligible_count": 0,
            })
        ),
        "ai_decision_agent": MagicMock(),
        "ai_decision_agent.shared_services": MagicMock(
            get_ai_decision_snapshot=MagicMock(return_value={
                "available": True,
                "avg_confidence": 0.6,
            })
        ),
        "paper_trader": MagicMock(
            get_portfolio=MagicMock(return_value={"cash": 100000, "positions": []})
        ),
        "scan_state_store": MagicMock(),   # overridden per-test
        "phase15_scan_context": MagicMock(
            build_scan_context=MagicMock(return_value={
                "scan_id": "test-001",
                "symbols": {},
            })
        ),
        "phase20_store": MagicMock(
            kv_get=MagicMock(return_value={"tripped": False})
        ),
        "phase20_executor": MagicMock(),
        "supervisor_agent": MagicMock(),
        "supervisor_agent.shared_services": MagicMock(),
        "market_data_agent": MagicMock(),
        "market_data_agent.shared_services": MagicMock(
            get_market_data_snapshot=MagicMock(return_value={
                "available": True,
                "coverage_pct": 90,
            })
        ),
        "stock_monitoring_agent": MagicMock(),
        "stock_monitoring_agent.shared_services": MagicMock(),
        "strategy_agent": MagicMock(),
        "strategy_agent.shared_services": MagicMock(),
        "risk_agent": MagicMock(),
        "risk_agent.shared_services": MagicMock(),
        "phase20_lifecycle": MagicMock(),
    }


def _run_integrity_check(snapshot_return) -> dict:
    """
    Run get_pipeline_integrity_check() with a controlled scan_state_store.

    snapshot_return: the value that load_latest_snapshot() should return.
    """
    from ops_centre import get_pipeline_integrity_check

    mods = _mock_modules()
    mods["scan_state_store"] = MagicMock(
        load_latest_snapshot=MagicMock(return_value=snapshot_return),
        load_latest_meta=MagicMock(return_value={"snapshot_ts": "2026-08-06T09:30:00Z"}),
    )

    with patch.dict("sys.modules", mods):
        return get_pipeline_integrity_check()


def _evidence_check(result: dict) -> dict:
    """Extract the 'Evidence Coverage' check from the result."""
    checks: list = result.get("checks", [])
    for c in checks:
        if c.get("component") == "Evidence Coverage":
            return c
    raise AssertionError(
        f"'Evidence Coverage' check not found in checks: "
        f"{[c.get('component') for c in checks]}"
    )


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestEvidenceCoverageCheck(unittest.TestCase):

    # ── 1. High thin-evidence ratio → WARN ───────────────────────────────────

    def test_warn_when_majority_low_evidence(self):
        """
        >30% low-evidence symbols → WARN.

        Scenario: 4 out of 5 symbols have <5 trades (80%) — well above the
        30% WARN threshold.
        """
        snap = _make_snapshot([
            _low_ev_item("RELIANCE", trades=2),
            _low_ev_item("TCS",      trades=1),
            _low_ev_item("HDFCBANK", trades=3),
            _low_ev_item("WIPRO",    trades=4),
            _high_ev_item("INFY",    trades=25),
        ])
        result = _run_integrity_check(snap)
        chk = _evidence_check(result)
        self.assertEqual(chk["status"], "WARN",
                         f"Expected WARN but got {chk['status']}: {chk['reason']}")

    # ── 2. Low thin-evidence ratio → PASS ────────────────────────────────────

    def test_pass_when_most_symbols_well_evidenced(self):
        """
        ≤30% low-evidence symbols → PASS.

        Scenario: 1 out of 5 symbols has <5 trades (20%) — within the
        acceptable range.
        """
        snap = _make_snapshot([
            _low_ev_item("RELIANCE", trades=2),
            _high_ev_item("INFY",    trades=25),
            _high_ev_item("TCS",     trades=30),
            _high_ev_item("HDFCBANK",trades=12),
            _high_ev_item("WIPRO",   trades=8),
        ])
        result = _run_integrity_check(snap)
        chk = _evidence_check(result)
        self.assertEqual(chk["status"], "PASS",
                         f"Expected PASS but got {chk['status']}: {chk['reason']}")

    # ── 3. Exactly at threshold (30%) → PASS ─────────────────────────────────

    def test_pass_at_30_percent_boundary(self):
        """
        Exactly 30% low-evidence → PASS (threshold is strictly >30%).

        3 out of 10 symbols = 30% exactly.
        """
        items = (
            [_low_ev_item(f"LOW{i}", trades=i + 1) for i in range(3)]
            + [_high_ev_item(f"HIGH{i}", trades=10 + i) for i in range(7)]
        )
        result = _run_integrity_check(_make_snapshot(items))
        chk = _evidence_check(result)
        self.assertEqual(chk["status"], "PASS",
                         f"Expected PASS at 30% but got {chk['status']}: {chk['reason']}")

    # ── 4. Just above threshold (40%) → WARN ─────────────────────────────────

    def test_warn_above_30_percent(self):
        """
        4 out of 10 symbols = 40% → WARN.
        """
        items = (
            [_low_ev_item(f"LOW{i}", trades=i + 1) for i in range(4)]
            + [_high_ev_item(f"HIGH{i}", trades=10 + i) for i in range(6)]
        )
        result = _run_integrity_check(_make_snapshot(items))
        chk = _evidence_check(result)
        self.assertEqual(chk["status"], "WARN",
                         f"Expected WARN at 40% but got {chk['status']}: {chk['reason']}")

    # ── 5. No valid items → WARN ──────────────────────────────────────────────

    def test_warn_when_all_items_errored(self):
        """
        When every scan item has an error field, the valid list is empty
        → WARN (no coverage data to assess).
        """
        snap = _make_snapshot([
            _error_item("RELIANCE"),
            _error_item("INFY"),
        ])
        result = _run_integrity_check(snap)
        chk = _evidence_check(result)
        self.assertEqual(chk["status"], "WARN",
                         f"Expected WARN for all-error snapshot: {chk['reason']}")

    # ── 6. No snapshot at all → WARN ─────────────────────────────────────────

    def test_warn_when_no_snapshot(self):
        """
        load_latest_snapshot() returns None → WARN (no scan has run yet).
        """
        result = _run_integrity_check(None)
        chk = _evidence_check(result)
        self.assertEqual(chk["status"], "WARN",
                         f"Expected WARN for missing snapshot: {chk['reason']}")

    # ── 7. Position in the checks list ───────────────────────────────────────

    def test_evidence_coverage_is_check_number_10(self):
        """
        'Evidence Coverage' must be exactly the 10th entry (index 9) in the
        checks list, confirming it has not been moved or removed.
        """
        snap = _make_snapshot([_high_ev_item("INFY", trades=20)])
        result = _run_integrity_check(snap)
        checks: list = result.get("checks", [])
        self.assertGreaterEqual(len(checks), 10,
                                f"Expected at least 10 checks, got {len(checks)}")
        self.assertEqual(checks[9]["component"], "Evidence Coverage",
                         f"Check #10 (index 9) should be 'Evidence Coverage', "
                         f"got '{checks[9]['component']}'")

    # ── 8. WARN reason mentions low-evidence count ────────────────────────────

    def test_warn_reason_mentions_low_evidence_count(self):
        """
        When status is WARN, the reason text must name the number of
        low-evidence symbols so operators can act on it.
        """
        snap = _make_snapshot([
            _low_ev_item("RELIANCE", trades=2),
            _low_ev_item("TCS",      trades=1),
            _high_ev_item("INFY",    trades=20),
        ])
        result = _run_integrity_check(snap)
        chk = _evidence_check(result)
        # 2 out of 3 = 66% → WARN
        self.assertEqual(chk["status"], "WARN")
        self.assertIn("2", chk["reason"],
                      "WARN reason must mention the count of low-evidence symbols")

    # ── 9. PASS reason confirms low-evidence count is within range ────────────

    def test_pass_reason_confirms_count(self):
        """
        When status is PASS, the reason text must name the low-evidence count
        so operators can see what the check measured.
        """
        snap = _make_snapshot([
            _low_ev_item("RELIANCE", trades=3),   # 1 low-evidence
            _high_ev_item("INFY",    trades=25),
            _high_ev_item("TCS",     trades=30),
            _high_ev_item("HDFCBANK",trades=12),
            _high_ev_item("WIPRO",   trades=8),
        ])
        result = _run_integrity_check(snap)
        chk = _evidence_check(result)
        self.assertEqual(chk["status"], "PASS")
        self.assertIn("1", chk["reason"],
                      "PASS reason must include the count of low-evidence symbols")

    # ── 10. Error items excluded from denominator ─────────────────────────────

    def test_error_items_excluded_from_denominator(self):
        """
        Items with a non-None 'error' field are excluded from both the
        numerator (low-ev count) and denominator (valid total), so a
        single real low-ev stock in an otherwise errored scan doesn't
        appear artificially PASS.

        Scenario: 1 valid low-ev + 9 errored → 1/1 = 100% → WARN.
        """
        items = (
            [_low_ev_item("RELIANCE", trades=2)]
            + [_error_item(f"ERR{i}") for i in range(9)]
        )
        result = _run_integrity_check(_make_snapshot(items))
        chk = _evidence_check(result)
        self.assertEqual(chk["status"], "WARN",
                         f"Expected WARN (1/1 valid = 100% low-ev): {chk['reason']}")

    # ── 11. All items well-evidenced → PASS, 0 low-evidence count ────────────

    def test_pass_when_zero_low_evidence_symbols(self):
        """
        When every symbol has ≥5 trades, the low-evidence count is 0
        and the check is PASS.
        """
        snap = _make_snapshot([
            _high_ev_item("INFY",    trades=25),
            _high_ev_item("TCS",     trades=30),
            _high_ev_item("HDFCBANK",trades=12),
        ])
        result = _run_integrity_check(snap)
        chk = _evidence_check(result)
        self.assertEqual(chk["status"], "PASS")
        self.assertIn("0", chk["reason"],
                      "Reason should mention 0 low-evidence symbols")

    # ── 12. Exactly 4 trades counts as low-evidence ───────────────────────────

    def test_four_trades_counts_as_low_evidence(self):
        """
        The threshold is strictly <5 trades.  A symbol with exactly 4 trades
        must be counted as low-evidence, not excluded.

        Scenario: 4 symbols with exactly 4 trades → 4/4 = 100% → WARN.
        """
        items = [_low_ev_item(f"SYM{i}", trades=4) for i in range(4)]
        result = _run_integrity_check(_make_snapshot(items))
        chk = _evidence_check(result)
        self.assertEqual(chk["status"], "WARN",
                         "4 trades must be treated as low-evidence (<5)")

    # ── 13. Exactly 5 trades is NOT low-evidence ──────────────────────────────

    def test_five_trades_is_not_low_evidence(self):
        """
        The threshold is strictly <5.  A symbol with exactly 5 trades
        must NOT be counted as low-evidence.

        Scenario: all symbols have ≥5 trades → 0% → PASS.
        """
        items = [_high_ev_item(f"SYM{i}", trades=5) for i in range(5)]
        result = _run_integrity_check(_make_snapshot(items))
        chk = _evidence_check(result)
        self.assertEqual(chk["status"], "PASS",
                         "5 trades should NOT be low-evidence (threshold is <5)")

    # ── 14. Overall result structure ──────────────────────────────────────────

    def test_integrity_check_returns_required_fields(self):
        """
        get_pipeline_integrity_check() must return a dict with the standard
        envelope fields and exactly 10 checks.
        """
        snap = _make_snapshot([_high_ev_item("INFY", trades=20)])
        result = _run_integrity_check(snap)

        self.assertIn("checks",      result)
        self.assertIn("overall",     result)
        self.assertIn("pass_count",  result)
        self.assertIn("warn_count",  result)
        self.assertIn("fail_count",  result)
        self.assertIn("advisory_only", result)
        self.assertTrue(result["advisory_only"])

        checks = result["checks"]
        self.assertEqual(len(checks), 10,
                         f"Expected exactly 10 checks, got {len(checks)}: "
                         f"{[c['component'] for c in checks]}")

    # ── 15. Each check has required fields ────────────────────────────────────

    def test_evidence_coverage_check_has_required_fields(self):
        """
        The Evidence Coverage check dict must have all required fields:
        component, status, reason, suggested_action.
        """
        snap = _make_snapshot([_high_ev_item("INFY", trades=20)])
        result = _run_integrity_check(snap)
        chk = _evidence_check(result)

        for field in ("component", "status", "reason", "suggested_action"):
            self.assertIn(field, chk,
                          f"Evidence Coverage check missing field: {field}")
        self.assertEqual(chk["component"], "Evidence Coverage")
        self.assertIn(chk["status"], ("PASS", "WARN", "FAIL"),
                      f"Unexpected status: {chk['status']}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
