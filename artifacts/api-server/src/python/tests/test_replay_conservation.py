"""
Replay pipeline conservation tests.

Enforces the data-integrity rules:
  1. Every stage: stocks_out <= stocks_in (no stage creates records).
  2. Every stage: stocks_in == stocks_out + rejected + pending + cancelled.
  3. Execution output is a subset of Decision BUY output; paper-eligible rows
     without a BUY decision are surfaced as anomalies, never counted.
  4. Starting capital comes from the configured paper capital (₹50,000),
     never a hardcoded ₹100,000.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from replay_engine import _build_stages_from_snapshot, _configured_capital  # noqa: E402


def _rec(symbol, action="BUY", paper=False, gates=True, strategy="s", dq="GOOD", **kw):
    r = {
        "symbol": symbol,
        "final_action": action,
        "paper_eligible": paper,
        "all_gates_passed": gates,
        "strategy_id": strategy,
        "data_quality": dq,
    }
    r.update(kw)
    return r


def _snap(recs, requested=None, received=None):
    n = len(recs)
    return {
        "universe_size": requested or n,
        "provider_health": {
            "symbols_requested": requested or n,
            "symbols_received": received if received is not None else n,
        },
        "recommendations": recs,
        "timings": {},
        "scan_audit": {},
    }


def _stage(stages, sid):
    return next(s for s in stages if s["id"] == sid)


class TestConservation:
    def test_no_stage_creates_records(self):
        recs = (
            [_rec(f"B{i}", paper=True) for i in range(5)]
            + [_rec("AV1", action="AVOID")]
            + [_rec("NOSTRAT", strategy=None)]
            + [_rec("BADDQ", dq="UNAVAILABLE")]
            + [_rec("NOGATE", gates=False)]
        )
        stages = _build_stages_from_snapshot(_snap(recs, requested=12, received=9))
        for s in stages:
            assert s["stocks_out"] <= s["stocks_in"], f"{s['id']} creates records"

    def test_counts_fully_accounted(self):
        recs = [_rec(f"B{i}", paper=(i % 2 == 0)) for i in range(6)]
        stages = _build_stages_from_snapshot(_snap(recs))
        for s in stages:
            accounted = s["stocks_out"] + max(0, s["rejected"]) + s["pending"] + s["cancelled"]
            assert accounted == s["stocks_in"], (
                f"{s['id']}: in={s['stocks_in']} accounted={accounted}"
            )

    def test_execution_never_exceeds_decision(self):
        # 6 BUY (5 paper-eligible) + 2 paper-eligible WITHOUT BUY decision
        recs = (
            [_rec(f"B{i}", paper=(i < 5)) for i in range(6)]
            + [_rec("ORPH1", action="AVOID", paper=True)]
            + [_rec("ORPH2", action="WATCH", paper=True)]
        )
        stages = _build_stages_from_snapshot(_snap(recs))
        ex = _stage(stages, "execution")
        dec = _stage(stages, "ai_decision")
        assert ex["stocks_in"] == dec["stocks_out"] == 6
        assert ex["stocks_out"] == 5          # only BUY ∩ paper_eligible
        assert ex["rejected"] == 1            # the BUY that wasn't eligible
        assert ex["anomaly_count"] == 2
        assert set(ex["anomalies"]) == {"ORPH1", "ORPH2"}
        assert "ORPH1" not in ex["stocks"] and "ORPH2" not in ex["stocks"]

    def test_symbol_filtered_upstream_cannot_reappear(self):
        # GHOST has strategy+gates+BUY but UNAVAILABLE data quality:
        # it must be rejected at Market Intelligence and never resurface.
        recs = [_rec("OK", paper=True), _rec("GHOST", paper=True, dq="UNAVAILABLE")]
        stages = _build_stages_from_snapshot(_snap(recs))
        for sid in ("strategy", "risk", "ai_decision", "execution"):
            assert "GHOST" not in _stage(stages, sid)["stocks"], f"GHOST reappeared in {sid}"

    def test_buy_requires_risk_approval(self):
        recs = [_rec("NOGATE", gates=False, paper=True)]
        stages = _build_stages_from_snapshot(_snap(recs))
        assert _stage(stages, "ai_decision")["stocks_out"] == 0
        assert _stage(stages, "execution")["stocks_out"] == 0


class TestMalformedSnapshots:
    def test_empty_snapshot(self):
        stages = _build_stages_from_snapshot(_snap([], requested=0, received=0))
        for s in stages:
            assert s["stocks_out"] <= s["stocks_in"]
            assert s["stocks_in"] == s["stocks_out"] + max(0, s["rejected"]) + s["pending"] + s["cancelled"]

    def test_received_exceeds_requested_is_clamped_and_flagged(self):
        recs = [_rec("A", paper=True), _rec("B")]
        stages = _build_stages_from_snapshot(_snap(recs, requested=2, received=99))
        md = _stage(stages, "market_data")
        assert md["stocks_out"] <= md["stocks_in"]
        assert md["rejected"] >= 0
        assert "PROVIDER_COUNT_MISMATCH" in md["anomalies"]
        for s in stages:
            accounted = s["stocks_out"] + max(0, s["rejected"]) + s["pending"] + s["cancelled"]
            assert accounted == s["stocks_in"]

    def test_duplicate_symbols_deduped_never_duplicated_downstream(self):
        recs = [_rec("DUP", paper=True), _rec("DUP", paper=True), _rec("DUP", paper=True), _rec("OK", paper=True)]
        stages = _build_stages_from_snapshot(_snap(recs, requested=4, received=4))
        md = _stage(stages, "market_data")
        assert md["anomaly_count"] >= 2  # two duplicate rows removed
        ex = _stage(stages, "execution")
        assert ex["stocks"].count("DUP") <= 1
        assert ex["stocks_out"] == 2  # DUP once + OK
        for s in stages:
            assert s["stocks"].count("DUP") <= 1, f"duplicate DUP in {s['id']}"
            accounted = s["stocks_out"] + max(0, s["rejected"]) + s["pending"] + s["cancelled"]
            assert accounted == s["stocks_in"]

    def test_missing_provider_health(self):
        recs = [_rec("A", paper=True)]
        snap = _snap(recs)
        snap["provider_health"] = {}
        stages = _build_stages_from_snapshot(snap)
        for s in stages:
            assert s["stocks_out"] <= s["stocks_in"]
            accounted = s["stocks_out"] + max(0, s["rejected"]) + s["pending"] + s["cancelled"]
            assert accounted == s["stocks_in"]


class TestCapital:
    def test_configured_capital_is_50k(self):
        assert _configured_capital() == 50_000.0
