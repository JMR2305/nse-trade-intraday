"""Phase 26A — End-to-End Validation Engine unit tests.

All validators run on injected fixture data — no DB, no network, no live
stores. Covers clean passes, conservation failures, broken execution
chains, portfolio mismatches, missing-data cases, and append-only
persistence via the file fallback.
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")))

import phase26_store  # noqa: E402
import phase26_validation as p26  # noqa: E402
from validation_engines import PASS, WARN, FAIL, INSUFFICIENT  # noqa: E402

SCAN = "scan-26a-test"


# ── Fixture builders ─────────────────────────────────────────────────────────

def _counts(sid, n_in, n_out, rej=0, pend=0, canc=0):
    return {"label": sid, "in": n_in, "out": n_out, "rejected": rej,
            "pending": pend, "cancelled": canc}


def _stage(sid, n_in, n_out, rej=0, duration=100, anomalies=None,
           rejected_symbols=None, **extra):
    return {"id": sid, "label": sid, "stocks_in": n_in, "stocks_out": n_out,
            "rejected": rej, "duration_ms": duration,
            "anomalies": anomalies or [],
            "rejected_symbols": rejected_symbols or [], **extra}


def clean_replay():
    """3-symbol funnel: AAA executes, BBB blocked at execution (cancelled),
    CCC rejected at strategy. Conservation holds at every stage."""
    stages = [
        _stage("market_data", 3, 3),
        _stage("strategy", 3, 2, rej=1, rejected_symbols=["CCC"]),
        _stage("ai_decision", 2, 2),
        _stage("execution", 2, 1, cancelled_symbols=["BBB"]),
    ]
    counts = {
        "market_data": _counts("market_data", 3, 3),
        "strategy": _counts("strategy", 3, 2, rej=1),
        "ai_decision": _counts("ai_decision", 2, 2),
        "execution": _counts("execution", 2, 1, canc=1),
    }
    return {
        "scan_id": SCAN,
        "snapshot_ts": "2026-08-09T04:00:00+00:00",
        "stages": stages,
        "pipeline_counts": counts,
        "decisions": [
            {"symbol": "AAA", "final_action": "BUY", "confidence": 80,
             "paper_eligible": True, "all_gates_passed": True},
            {"symbol": "BBB", "final_action": "STRONG BUY", "confidence": 75,
             "paper_eligible": False, "all_gates_passed": True},
            {"symbol": "CCC", "final_action": "AVOID", "confidence": 20,
             "paper_eligible": False, "all_gates_passed": False},
        ],
        "execution_trades": [{"symbol": "AAA"}],
        "total_symbols": 3,
    }


def ledger_open_aaa():
    return [{
        "trade_id": "t-aaa", "symbol": "AAA", "scan_id": SCAN,
        "status": "OPEN", "quantity": 10, "fill_price": 100.0,
        "fill_ts": "2026-08-09T04:01:00+00:00", "realized_pnl": None,
        "sector": "IT",
    }]


def exec_events():
    return [{"id": 1, "scan_id": SCAN, "stage": "EXECUTION",
             "event_type": "ORDER_EXECUTED", "symbol": "AAA",
             "ts": "2026-08-09T04:01:00+00:00", "payload": {}}]


def stage_events():
    return {"stages": [
        {"stage": "MARKET_DATA", "events": 3,
         "last_ts": "2026-08-09T04:00:30+00:00"},
        {"stage": "EXECUTION", "events": 1,
         "last_ts": "2026-08-09T04:01:00+00:00"},
    ]}


def canonical_snapshot():
    """Snapshot exactly consistent with ledger_open_aaa (cap 100000)."""
    return {
        "initial_capital": 100_000.0, "cash": 99_000.0,
        "invested_value": 1_000.0, "equity": 100_050.0,
        "equity_complete": True, "realized_pnl": 0.0, "unrealized_pnl": 50.0,
        "open_position_count": 1, "closed_trade_count": 0,
        "positions": [{"trade_id": "t-aaa", "symbol": "AAA", "quantity": 10,
                       "avg_price": 100.0, "cost": 1_000.0,
                       "market_value": 1_050.0, "mark_price": 105.0,
                       "unrealized_pnl": 50.0, "sector": "IT"}],
        "sector_exposure": {"IT": 1_000.0},
        "portfolio_version": "1:x",
    }


# ── Pipeline cycle validator ─────────────────────────────────────────────────

class TestPipelineCycle:
    def test_clean_pass(self):
        r = p26.validate_pipeline_cycle(replay=clean_replay(),
                                        stage_events=stage_events())
        assert r["verdict"] == PASS
        assert r["scan_id"] == SCAN
        by = {c["check"]: c["status"] for c in r["checks"]}
        assert by["stage_conservation"] == PASS
        assert by["stage_chaining"] == PASS
        assert by["no_stage_anomalies"] == PASS
        assert by["snapshot_timestamp_valid"] == PASS

    def test_stage_report_shape(self):
        r = p26.validate_pipeline_cycle(replay=clean_replay(),
                                        stage_events=stage_events())
        rows = {s["stage"]: s for s in r["stage_report"]}
        md = rows["market_data"]
        assert md["input"] == 3 and md["output"] == 3
        assert md["latency_ms"] == 100
        assert md["last_event_ts"] == "2026-08-09T04:00:30+00:00"
        ex = rows["execution"]
        assert ex["cancelled"] == 1 and ex["conserved"] is True

    def test_conservation_violation_fails(self):
        rp = clean_replay()
        rp["pipeline_counts"]["strategy"] = _counts("strategy", 3, 2)  # lost 1
        r = p26.validate_pipeline_cycle(replay=rp, stage_events={})
        assert r["verdict"] == FAIL
        c = next(c for c in r["checks"] if c["check"] == "stage_conservation")
        assert c["status"] == FAIL and "strategy" in c["detail"]

    def test_chain_break_fails(self):
        rp = clean_replay()
        rp["stages"][2]["stocks_in"] = 3   # ai_decision in ≠ strategy out (2)
        r = p26.validate_pipeline_cycle(replay=rp, stage_events={})
        c = next(c for c in r["checks"] if c["check"] == "stage_chaining")
        assert c["status"] == FAIL and "strategy→ai_decision" in c["detail"]

    def test_duplicate_symbol_anomaly_fails(self):
        rp = clean_replay()
        rp["stages"][0]["anomalies"] = ["duplicate symbol AAA in scan"]
        r = p26.validate_pipeline_cycle(replay=rp, stage_events={})
        c = next(c for c in r["checks"] if c["check"] == "no_stage_anomalies")
        assert c["status"] == FAIL and "AAA" in c["detail"]

    def test_missing_replay_insufficient(self):
        r = p26.validate_pipeline_cycle(
            replay={"error": "not found", "scan_id": "nope"},
            stage_events={})
        assert r["verdict"] == INSUFFICIENT
        assert r["stage_report"] == []

    def test_future_snapshot_ts_warns(self):
        rp = clean_replay()
        rp["snapshot_ts"] = "2099-01-01T00:00:00+00:00"
        r = p26.validate_pipeline_cycle(replay=rp, stage_events={})
        c = next(c for c in r["checks"]
                 if c["check"] == "snapshot_timestamp_valid")
        assert c["status"] == WARN


# ── Execution chain validator ────────────────────────────────────────────────

class TestExecutionChain:
    def test_clean_chain_open_trade(self):
        r = p26.validate_execution_chain(
            replay=clean_replay(), ledger_rows=ledger_open_aaa(),
            execution_events=exec_events(), learning_trade_ids=[],
            portfolio_snapshot=canonical_snapshot())
        assert r["verdict"] == PASS
        assert r["errors"] == []
        chains = {c["symbol"]: c for c in r["chains"]}
        assert chains["AAA"]["status"] == "COMPLETE"
        assert chains["AAA"]["links"]["learning_record"] == "PENDING"
        # BBB was a BUY but not paper-eligible → legitimately blocked
        assert chains["BBB"]["status"] == "BLOCKED"

    def test_closed_trade_requires_learning_record(self):
        rows = ledger_open_aaa()
        rows[0].update(status="CLOSED", realized_pnl=50.0)
        r = p26.validate_execution_chain(
            replay=clean_replay(), ledger_rows=rows,
            execution_events=exec_events(), learning_trade_ids=[],
            portfolio_snapshot=canonical_snapshot())
        assert r["verdict"] == FAIL
        assert any(e["link"] == "learning_record" and e["symbol"] == "AAA"
                   for e in r["errors"])
        # and passes once the learning record exists
        r2 = p26.validate_execution_chain(
            replay=clean_replay(), ledger_rows=rows,
            execution_events=exec_events(), learning_trade_ids=["t-aaa"])
        assert r2["verdict"] == PASS

    def test_closed_trade_missing_pnl_errors(self):
        rows = ledger_open_aaa()
        rows[0].update(status="CLOSED", realized_pnl=None)
        r = p26.validate_execution_chain(
            replay=clean_replay(), ledger_rows=rows,
            execution_events=exec_events(), learning_trade_ids=["t-aaa"])
        assert any(e["link"] == "pnl_updated" for e in r["errors"])

    def test_eligible_unexecuted_is_blocked_warn_not_error(self):
        """Paper-eligible BUY with no ledger row and no block evidence:
        BLOCKED chain (replay counts it cancelled) + WARN, never ERROR —
        auto paper entries default OFF, so this is a routine outcome."""
        rp = clean_replay()
        rp["decisions"][1]["paper_eligible"] = True  # BBB eligible, no ledger
        r = p26.validate_execution_chain(
            replay=rp, ledger_rows=ledger_open_aaa(),
            execution_events=exec_events(), learning_trade_ids=[],
            portfolio_snapshot=canonical_snapshot())
        assert r["verdict"] == WARN
        assert r["errors"] == []
        bbb = next(c for c in r["chains"] if c["symbol"] == "BBB")
        assert bbb["status"] == "BLOCKED" and "no block evidence" \
            in bbb["reason"]
        c = next(c for c in r["checks"]
                 if c["check"] == "blocked_entries_have_evidence")
        assert c["status"] == WARN and "BBB" in c["detail"]

    def test_blocked_with_evidence_passes(self):
        rp = clean_replay()
        rp["decisions"][1]["paper_eligible"] = True
        rp["stages"][3]["blocked_entries"] = [{"symbol": "BBB",
                                               "reason": "circuit breaker"}]
        r = p26.validate_execution_chain(
            replay=rp, ledger_rows=ledger_open_aaa(),
            execution_events=exec_events(), learning_trade_ids=[],
            portfolio_snapshot=canonical_snapshot())
        assert r["verdict"] == PASS
        bbb = next(c for c in r["chains"] if c["symbol"] == "BBB")
        assert bbb["reason"] == "blocked by executor (evidence recorded)"

    def test_missing_pipeline_event_errors(self):
        r = p26.validate_execution_chain(
            replay=clean_replay(), ledger_rows=ledger_open_aaa(),
            execution_events=[], learning_trade_ids=[])
        assert any(e["link"] == "mission_control_visible"
                   for e in r["errors"])

    def test_missing_replay_event_errors(self):
        rp = clean_replay()
        rp["execution_trades"] = []
        r = p26.validate_execution_chain(
            replay=rp, ledger_rows=ledger_open_aaa(),
            execution_events=exec_events(), learning_trade_ids=[])
        assert any(e["link"] == "replay_event" for e in r["errors"])

    def test_no_fill_errors(self):
        rows = ledger_open_aaa()
        rows[0].update(fill_ts=None, fill_price=None)
        r = p26.validate_execution_chain(
            replay=clean_replay(), ledger_rows=rows,
            execution_events=exec_events(), learning_trade_ids=[])
        assert any(e["link"] == "execution_submitted" and
                   e["symbol"] == "AAA" for e in r["errors"])

    def test_open_trade_missing_from_portfolio_errors(self):
        """Aggregates can look fine while THIS trade's position is absent —
        the per-trade linkage must catch it."""
        snap = canonical_snapshot()
        snap["positions"] = [{"trade_id": "t-zzz", "symbol": "ZZZ",
                              "quantity": 10, "cost": 1_000.0}]
        r = p26.validate_execution_chain(
            replay=clean_replay(), ledger_rows=ledger_open_aaa(),
            execution_events=exec_events(), learning_trade_ids=[],
            portfolio_snapshot=snap)
        assert r["verdict"] == FAIL
        assert any(e["link"] == "portfolio_updated" and e["symbol"] == "AAA"
                   for e in r["errors"])

    def test_position_quantity_mismatch_errors(self):
        snap = canonical_snapshot()
        snap["positions"][0]["quantity"] = 7
        r = p26.validate_execution_chain(
            replay=clean_replay(), ledger_rows=ledger_open_aaa(),
            execution_events=exec_events(), learning_trade_ids=[],
            portfolio_snapshot=snap)
        assert any(e["link"] == "portfolio_updated" for e in r["errors"])

    def test_closed_trade_still_open_position_errors(self):
        rows = ledger_open_aaa()
        rows[0].update(status="CLOSED", realized_pnl=50.0)
        r = p26.validate_execution_chain(
            replay=clean_replay(), ledger_rows=rows,
            execution_events=exec_events(), learning_trade_ids=["t-aaa"],
            portfolio_snapshot=canonical_snapshot())  # t-aaa still a position
        assert any(e["link"] == "portfolio_updated" and
                   "still appears" in e["detail"] for e in r["errors"])

    def test_no_buy_decisions_insufficient(self):
        rp = clean_replay()
        rp["decisions"] = [{"symbol": "CCC", "final_action": "AVOID",
                            "paper_eligible": False}]
        r = p26.validate_execution_chain(
            replay=rp, ledger_rows=[], execution_events=[],
            learning_trade_ids=[],
            portfolio_snapshot=canonical_snapshot())
        assert r["verdict"] == INSUFFICIENT
        assert r["chains"] == [] and r["errors"] == []

    def test_missing_replay_insufficient(self):
        r = p26.validate_execution_chain(
            replay={"error": "x"}, ledger_rows=[], execution_events=[],
            learning_trade_ids=[],
            portfolio_snapshot=canonical_snapshot())
        assert r["verdict"] == INSUFFICIENT


# ── Portfolio validator (delegation) ─────────────────────────────────────────

class TestPortfolioAlignment:
    def test_consistent_snapshot_passes(self):
        r = p26.validate_portfolio_alignment(
            ledger_rows=ledger_open_aaa(), snapshot=canonical_snapshot())
        assert r["domain"] == "portfolio_alignment"
        assert r["verdict"] == PASS

    def test_cash_mismatch_fails(self):
        snap = canonical_snapshot()
        snap["cash"] = 98_500.0        # drifted from ledger-derived cash
        r = p26.validate_portfolio_alignment(
            ledger_rows=ledger_open_aaa(), snapshot=snap)
        assert r["verdict"] == FAIL
        c = next(c for c in r["checks"] if c["check"] == "cash_balances")
        assert c["status"] == FAIL

    def test_sector_exposure_mismatch_fails(self):
        snap = canonical_snapshot()
        snap["sector_exposure"] = {"IT": 900.0}
        r = p26.validate_portfolio_alignment(
            ledger_rows=ledger_open_aaa(), snapshot=snap)
        c = next(c for c in r["checks"]
                 if c["check"] == "sector_exposure_balances")
        assert c["status"] == FAIL


# ── Orchestrator + append-only persistence ───────────────────────────────────

class TestRunAndPersistence:
    @pytest.fixture(autouse=True)
    def _isolate_store(self, tmp_path, monkeypatch):
        monkeypatch.setattr(phase26_store, "RUNS_FILE",
                            str(tmp_path / "runs.json"))
        monkeypatch.setattr(phase26_store, "db_available", lambda: False)
        yield

    def _run(self, **kw):
        return p26.run_e2e_validation(
            replay=clean_replay(), ledger_rows=ledger_open_aaa(),
            snapshot=canonical_snapshot(), stage_events=stage_events(),
            execution_events=exec_events(), learning_trade_ids=[], **kw)

    def test_clean_run_passes_and_persists(self):
        run = self._run()
        assert run["verdict"] == PASS
        assert set(run["sections"]) == {"pipeline_cycle", "execution_chain",
                                        "portfolio_alignment"}
        assert run["totals"]["fail"] == 0 and run["totals"]["errors"] == 0
        hist = phase26_store.list_runs()
        assert [h["run_id"] for h in hist] == [run["run_id"]]
        stored = phase26_store.get_run(run["run_id"])
        assert stored["verdict"] == PASS
        assert stored["sections"]["pipeline_cycle"]["verdict"] == PASS

    def test_overall_verdict_is_worst_section(self):
        snap = canonical_snapshot()
        snap["cash"] = 0.0
        run = p26.run_e2e_validation(
            replay=clean_replay(), ledger_rows=ledger_open_aaa(),
            snapshot=snap, stage_events=stage_events(),
            execution_events=exec_events(), learning_trade_ids=[])
        assert run["verdict"] == FAIL
        assert run["sections"]["pipeline_cycle"]["verdict"] == PASS

    def test_append_only_never_overwrites(self):
        run = self._run()
        mutated = dict(run, verdict="FAIL")
        phase26_store.append_run(mutated)     # same run_id — must be ignored
        stored = phase26_store.get_run(run["run_id"])
        assert stored["verdict"] == PASS

    def test_history_ordering_and_summary(self):
        r1 = self._run()
        r2 = self._run()
        hist = phase26_store.list_runs()
        assert len(hist) == 2
        assert {h["run_id"] for h in hist} == {r1["run_id"], r2["run_id"]}
        s = p26.e2e_summary()
        assert s["ok"] is True
        assert s["latest"]["run_id"] in (r1["run_id"], r2["run_id"])
        assert s["history_verdicts"][PASS] == 2

    def test_persist_false_skips_store(self):
        self._run(persist=False)
        assert phase26_store.list_runs() == []

    def test_get_unknown_run_returns_none(self):
        assert phase26_store.get_run("e2e-nope") is None

    def test_fallback_cap_keeps_newest(self, monkeypatch):
        monkeypatch.setattr(phase26_store, "_FALLBACK_CAP", 3)
        ids = [self._run()["run_id"] for _ in range(5)]
        hist = phase26_store.list_runs(limit=500)
        assert len(hist) == 3
        assert {h["run_id"] for h in hist} == set(ids[-3:])

    def test_concurrent_appends_lose_nothing(self):
        import threading
        base = self._run(persist=False)
        errs = []

        def worker(i):
            try:
                phase26_store.append_run(dict(base, run_id=f"e2e-conc-{i}"))
            except Exception as e:   # pragma: no cover
                errs.append(e)

        threads = [threading.Thread(target=worker, args=(i,))
                   for i in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errs
        got = {h["run_id"] for h in phase26_store.list_runs(limit=500)}
        assert got == {f"e2e-conc-{i}" for i in range(12)}
