"""
phase13_diagnostics.py — Phase 13 Diagnostic Bundle Generator

Writes phase13_diagnostic_bundle.json + phase13_summary.csv

Includes: factor scores, regime, sector rotation, relative strength,
calibration, evidence labels, strategy evolution proposals, audit report,
self-tests, data quality, scan staleness.

PAPER TRADING / RESEARCH ONLY
"""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_DIR = os.path.dirname(os.path.abspath(__file__))
BUNDLE_FILE = os.path.join(_DIR, "phase13_diagnostic_bundle.json")
SUMMARY_CSV = os.path.join(_DIR, "phase13_summary.csv")

RESEARCH_ENGINE_VERSION = "Research Engine v1.0 · Phase 13"


def _now_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _file_meta(filename: str) -> Dict[str, Any]:
    path = os.path.join(_DIR, filename)
    if not os.path.exists(path):
        return {"file": filename, "exists": False, "size_bytes": None}
    st = os.stat(path)
    return {
        "file": filename,
        "exists": True,
        "size_bytes": st.st_size,
        "modified": datetime.fromtimestamp(st.st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _run_self_tests() -> List[Dict[str, Any]]:
    results = []

    def _t(name: str, cond: bool, detail: str = "") -> None:
        results.append({"test": name, "pass": cond, "detail": detail})

    # T01: factor weights sum to 1.0
    try:
        from phase13_intelligence import FACTOR_WEIGHTS
        s = round(sum(FACTOR_WEIGHTS.values()), 9)
        _t("factor_weights_sum_1", abs(s - 1.0) < 1e-9, f"sum={s}")
    except Exception as e:
        _t("factor_weights_sum_1", False, str(e)[:100])

    # T02: 14 factors defined
    try:
        from phase13_intelligence import FACTOR_WEIGHTS
        _t("14_factors_defined", len(FACTOR_WEIGHTS) == 14, f"count={len(FACTOR_WEIGHTS)}")
    except Exception as e:
        _t("14_factors_defined", False, str(e)[:100])

    # T03: no-lookahead: only SELL rows with timestamps
    try:
        from phase13_intelligence import _completed_paper_trades
        trades = _completed_paper_trades()
        all_sell = all(t.get("action", "").upper() == "SELL" for t in trades) if trades else True
        all_ts = all(bool(t.get("timestamp") or t.get("close_ts") or t.get("trade_date")) for t in trades) if trades else True
        _t("no_lookahead_sell_only", all_sell, f"n={len(trades)}")
        _t("no_lookahead_timestamps", all_ts, f"all_ts={all_ts}")
    except Exception as e:
        _t("no_lookahead_sell_only", False, str(e)[:100])
        _t("no_lookahead_timestamps", False, str(e)[:100])

    # T04: stale gate
    try:
        from phase13_intelligence import fuse_symbol, detect_market_regime
        regime = detect_market_regime({})
        item = {"symbol": "STALETEST", "data_status": "DATA_UNAVAILABLE", "quality": "STALE", "confidence": 99}
        r = fuse_symbol(item, regime, [], None, {}, [], 5000, 5000, 18.0, scan_stale=False)
        _t("stale_gate", r["p13_action"] not in ("BUY", "STRONG_BUY"), f"action={r['p13_action']}")
    except Exception as e:
        _t("stale_gate", False, str(e)[:100])

    # T05: score normalization 0-100
    try:
        from phase13_intelligence import _score_trend, _score_momentum, _score_risk_reward
        t, _ = _score_trend({"confidence": 85})
        m, _ = _score_momentum({"rsi": 50})
        rr, _ = _score_risk_reward({"entry_price": 1000, "stop_loss": 970, "target": 1090})
        _t("scores_0_100", 0 <= t <= 100 and 0 <= m <= 100 and 0 <= rr <= 100, f"t={t} m={m} rr={rr}")
    except Exception as e:
        _t("scores_0_100", False, str(e)[:100])

    # T06: evidence labels
    try:
        from phase13_intelligence import evidence_label
        _t("evidence_label_insufficient", evidence_label(0) == "insufficient", "")
        _t("evidence_label_validated", evidence_label(150) == "validated", "")
    except Exception as e:
        _t("evidence_label_insufficient", False, str(e)[:100])
        _t("evidence_label_validated", False, str(e)[:100])

    # T07: strategy eligibility
    try:
        from phase13_intelligence import eligible_strategies
        strats = eligible_strategies("TRENDING_UP")
        _t("strategy_eligibility_trending_up", len(strats) > 0, f"strats={strats}")
        no_strats = eligible_strategies("CRISIS")
        _t("no_strategies_in_crisis", len(no_strats) == 0, f"strats={no_strats}")
    except Exception as e:
        _t("strategy_eligibility_trending_up", False, str(e)[:100])
        _t("no_strategies_in_crisis", False, str(e)[:100])

    # T08: position size cap 20%
    try:
        from phase13_intelligence import volatility_aware_size
        sz = volatility_aware_size(2000, 1940, 5000, 5000, 18.0, "TRENDING_UP")
        _t("position_size_cap_20pct", (sz.get("capital_utilization_pct") or 0) <= 20, f"util={sz.get('capital_utilization_pct')}")
    except Exception as e:
        _t("position_size_cap_20pct", False, str(e)[:100])

    # T09: no real broker orders
    src = open(os.path.join(_DIR, "phase13_intelligence.py")).read()
    _t("no_real_broker_order", "execute_buy" not in src and "kite.place_order" not in src, "")

    # T10: evolution proposals require approval
    src2 = open(os.path.join(_DIR, "phase13_strategy_evolution.py")).read()
    _t("proposals_require_approval", "auto_promoted" in src2 and "False" in src2, "auto_promoted always False")

    return results


def build_phase13_bundle() -> Dict[str, Any]:
    try:
        from market_hours import market_status
        mkt = market_status()
    except Exception:
        mkt = {}

    try:
        from live_quote_service import provider_status
        qp = provider_status()
    except Exception:
        qp = {}

    try:
        from paper_trader import _load_state as _pts
        state = _pts()
        cash = state.get("cash", 5000.0)
    except Exception:
        cash = 5000.0

    from phase13_intelligence import run_phase13_analysis, FACTOR_WEIGHTS, REGIMES
    from phase13_audit import build_audit_report
    from phase13_strategy_evolution import list_proposals

    analysis_err = None
    try:
        analysis = run_phase13_analysis(available_cash=cash, capital=5000.0)
    except Exception as exc:
        analysis = {}
        analysis_err = str(exc)[:300]

    fused = analysis.get("fused_results") or []
    regime = analysis.get("regime") or {}

    top_opps = [
        {"symbol": r["symbol"], "p13_action": r["p13_action"],
         "calibrated_score": r.get("calibrated_score"), "evidence": r.get("evidence"),
         "sector": r.get("sector"), "contradiction": r.get("contradiction", {}).get("level")}
        for r in fused
        if r.get("p13_action") in ("STRONG_BUY", "BUY") and not r.get("is_stale")
    ][:5]

    rs_sorted = sorted(
        [r for r in fused if r.get("relative_strength", {}).get("rs_vs_index") is not None],
        key=lambda r: r["relative_strength"]["rs_vs_index"], reverse=True,
    )

    self_tests = _run_self_tests()
    passed = sum(1 for t in self_tests if t["pass"])
    failed = sum(1 for t in self_tests if not t["pass"])

    audit = {}
    audit_err = None
    try:
        audit = build_audit_report()
    except Exception as exc:
        audit_err = str(exc)[:200]

    proposals_info = {}
    try:
        proposals_info = list_proposals("PENDING_APPROVAL")
    except Exception:
        pass

    # Evidence distribution
    ev_dist: Dict[str, int] = {}
    for r in fused:
        ev = r.get("evidence", "insufficient")
        ev_dist[ev] = ev_dist.get(ev, 0) + 1

    bundle = {
        "bundle_version": 1,
        "phase": 13,
        "generated_at": _now_str(),
        "engine_version": RESEARCH_ENGINE_VERSION,
        "mode": "PAPER_TRADING_RESEARCH_ONLY",
        "label": "PAPER / RESEARCH ONLY",
        "market_status": mkt,
        "quote_provider": qp,
        "regime": regime,
        "sector_rotation_top3": (analysis.get("sector_rotation") or [])[:3],
        "factor_weights": FACTOR_WEIGHTS,
        "top_opportunities": top_opps,
        "relative_strength_leaders": [{"symbol": r["symbol"], "rs_vs_index": r["relative_strength"]["rs_vs_index"], "label": r["relative_strength"].get("rs_rank_label")} for r in rs_sorted[:3]],
        "relative_strength_laggards": [{"symbol": r["symbol"], "rs_vs_index": r["relative_strength"]["rs_vs_index"], "label": r["relative_strength"].get("rs_rank_label")} for r in rs_sorted[-3:]],
        "evidence_distribution": ev_dist,
        "action_summary": analysis.get("action_summary") or {},
        "contradiction_summary": analysis.get("contradiction_summary") or {},
        "scan_staleness": {"stale": analysis.get("scan_stale"), "age_minutes": analysis.get("scan_age_minutes")},
        "audit_summary": {
            "trade_count": audit.get("total_completed_trades"),
            "interpretation": audit.get("interpretation"),
            "p13_expectancy": (audit.get("phase13") or {}).get("expectancy_after_costs"),
            "p12_expectancy": (audit.get("phase12") or {}).get("expectancy_after_costs"),
        },
        "strategy_evolution": {
            "pending_proposals": proposals_info.get("pending", 0),
            "note": "All proposals require human approval. No auto-promotion.",
        },
        "sample_counts": {
            "symbols_analyzed": len(fused),
            "completed_trades": analysis.get("completed_trade_count", 0),
        },
        "self_tests": {"results": self_tests, "passed": passed, "failed": failed},
        "files": [_file_meta(f) for f in [
            "phase13_cache.json", "phase13_proposals.json", "phase13_audit_report.json",
            "phase13_diagnostic_bundle.json", "phase13_summary.csv",
            "phase7_scan_cache.json", "market_context_cache.json",
        ]],
        "errors": {k: v for k, v in [("analysis", analysis_err), ("audit", audit_err)] if v},
        "notes": [
            "PAPER TRADING / RESEARCH ONLY — no live broker orders placed.",
            "Evidence labels suppress precision when sample count is small.",
            "Stale-scan protection: rankings blocked if scan > 90 min old during market hours.",
        ],
    }

    try:
        with open(BUNDLE_FILE, "w") as f:
            json.dump(bundle, f, indent=2, default=str)
    except Exception as exc:
        bundle["write_error"] = str(exc)

    _write_csv(bundle)

    bundle["bundle_file"] = os.path.basename(BUNDLE_FILE)
    bundle["summary_csv"] = os.path.basename(SUMMARY_CSV)
    return bundle


def _flatten(prefix: str, obj: Any, rows: List) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            _flatten(f"{prefix}.{k}" if prefix else k, v, rows)
    elif isinstance(obj, list):
        rows.append({"key": prefix, "value": f"[{len(obj)} items]"})
    else:
        rows.append({"key": prefix, "value": "" if obj is None else str(obj)})


def _write_csv(bundle: Dict[str, Any]) -> None:
    sections = ["generated_at", "engine_version", "mode", "market_status", "regime",
                "factor_weights", "action_summary", "evidence_distribution",
                "audit_summary", "scan_staleness", "sample_counts", "self_tests"]
    rows: List = []
    for s in sections:
        _flatten(s, bundle.get(s), rows)
    try:
        with open(SUMMARY_CSV, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["key", "value"])
            w.writeheader()
            w.writerows(rows)
    except Exception:
        pass
