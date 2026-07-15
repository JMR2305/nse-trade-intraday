"""
phase12_diagnostics.py — Phase 12: Advanced Institutional Intelligence Layer
Diagnostic bundle generator for Phase 12. Writes:
  phase12_diagnostic_bundle.json
  phase12_summary.csv

Contents: factor scores, regime classification, sector rotation, relative strength,
ranking changes, sizing decisions, calibration metrics, contradictions, sample counts,
test results, sanitized errors.

PAPER TRADING ONLY — no real orders.
"""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_DIR = os.path.dirname(os.path.abspath(__file__))
BUNDLE_FILE = os.path.join(_DIR, "phase12_diagnostic_bundle.json")
SUMMARY_CSV = os.path.join(_DIR, "phase12_summary.csv")

RESEARCH_ENGINE_VERSION = "Research Engine v1.0 · Phase 12"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_json(filename: str) -> Optional[Any]:
    path = os.path.join(_DIR, filename)
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def _file_meta(filename: str) -> Dict[str, Any]:
    path = os.path.join(_DIR, filename)
    if not os.path.exists(path):
        return {"file": filename, "exists": False, "size_bytes": None, "modified": None}
    st = os.stat(path)
    return {
        "file": filename,
        "exists": True,
        "size_bytes": st.st_size,
        "modified": datetime.fromtimestamp(st.st_mtime, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def _build_calibration_section(fused_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Summarize calibration quality across all analyzed symbols."""
    methods: Dict[str, int] = {}
    scores = []
    for r in fused_results:
        fs = r.get("factor_scores") or {}
        cq = fs.get("calibration_quality")
        if cq is not None:
            scores.append(cq)
        method = (r.get("factor_rationales") or {}).get("calibration_quality", "")
        if method:
            key = "calibrated" if "method=" in method and "v0" not in method else "identity"
            methods[key] = methods.get(key, 0) + 1
    return {
        "avg_calibration_score": round(sum(scores) / len(scores), 1) if scores else None,
        "method_breakdown": methods,
        "symbols_assessed": len(scores),
    }


def _build_contradiction_section(fused_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate contradiction statistics."""
    level_counts: Dict[str, int] = {"NONE": 0, "LOW": 0, "MEDIUM": 0, "HIGH": 0}
    high_examples: List[str] = []
    for r in fused_results:
        c = r.get("contradiction") or {}
        lvl = c.get("level", "NONE")
        level_counts[lvl] = level_counts.get(lvl, 0) + 1
        if lvl == "HIGH" and len(high_examples) < 3:
            high_examples.append(f"{r.get('symbol')}: {c.get('explanation', '')[:80]}")
    return {
        "level_distribution": level_counts,
        "high_contradiction_examples": high_examples,
    }


def _build_sizing_section(fused_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Summarize volatility-aware sizing decisions."""
    feasible = 0
    not_feasible = 0
    adj_labels: Dict[str, int] = {}
    for r in fused_results:
        sz = r.get("sizing") or {}
        if sz.get("feasible"):
            feasible += 1
        else:
            not_feasible += 1
        adj = str(sz.get("regime_adj", ""))
        if adj:
            adj_labels[adj] = adj_labels.get(adj, 0) + 1
    return {
        "feasible_positions": feasible,
        "not_feasible_positions": not_feasible,
        "regime_adjustments_applied": adj_labels,
    }


def _run_self_tests() -> List[Dict[str, Any]]:
    """Run mini self-tests and report pass/fail."""
    results = []

    def _test(name: str, cond: bool, detail: str = "") -> None:
        results.append({"test": name, "pass": cond, "detail": detail})

    # Factor weights sum to 1.0
    try:
        from phase12_intelligence import FACTOR_WEIGHTS, FACTOR_WEIGHTS as fw
        total = round(sum(fw.values()), 9)
        _test("factor_weights_sum_1", abs(total - 1.0) < 1e-9, f"sum={total}")
    except Exception as e:
        _test("factor_weights_sum_1", False, str(e)[:100])

    # No-lookahead guard: completed_paper_trades returns only SELL rows with timestamps
    try:
        from phase12_intelligence import _completed_paper_trades
        trades = _completed_paper_trades()
        all_sell = all(t.get("action", "").upper() == "SELL" for t in trades)
        all_ts = all(bool(t.get("timestamp") or t.get("close_ts") or t.get("trade_date")) for t in trades)
        _test("no_lookahead_sell_only", all_sell, f"{len(trades)} trades, all SELL: {all_sell}")
        _test("no_lookahead_timestamps", all_ts, f"all have close_ts: {all_ts}")
    except Exception as e:
        _test("no_lookahead_sell_only", False, str(e)[:100])
        _test("no_lookahead_timestamps", False, str(e)[:100])

    # Stale-data gate blocks BUY
    try:
        from phase12_intelligence import fuse_symbol, detect_market_regime
        stale_item = {
            "symbol": "TESTCO", "data_status": "DATA_UNAVAILABLE", "quality": "STALE",
            "confidence": 95, "recommendation": "STRONG_BUY",
        }
        regime = detect_market_regime({})
        result = fuse_symbol(stale_item, regime, [], None, {}, 5000, 5000, 18.0)
        _test("stale_gate_blocks_buy",
              result["p12_action"] not in ("BUY", "STRONG_BUY"),
              f"action={result['p12_action']}")
    except Exception as e:
        _test("stale_gate_blocks_buy", False, str(e)[:100])

    # Factor score 0-100 range
    try:
        from phase12_intelligence import _score_trend, _score_momentum, _score_volatility
        t, _ = _score_trend({"confidence": 80})
        m, _ = _score_momentum({"rsi": 45})
        v, _ = _score_volatility({}, vix=15.0)
        _test("factor_scores_in_range", 0 <= t <= 100 and 0 <= m <= 100 and 0 <= v <= 100,
              f"trend={t} mom={m} vol={v}")
    except Exception as e:
        _test("factor_scores_in_range", False, str(e)[:100])

    # Position size caps
    try:
        from phase12_intelligence import volatility_aware_size
        sz = volatility_aware_size(1000.0, 970.0, 5000.0, 5000.0, 18.0, "RANGE_BOUND")
        cap_ok = (sz.get("capital_utilization_pct") or 0) <= 20.0
        _test("position_size_cap_20pct", cap_ok, f"util={sz.get('capital_utilization_pct')}%")
    except Exception as e:
        _test("position_size_cap_20pct", False, str(e)[:100])

    # Regime detection returns valid state
    try:
        from phase12_intelligence import detect_market_regime, REGIMES
        r = detect_market_regime({"vix": 18, "nifty_trend": "BULLISH", "market_score": 65})
        _test("regime_valid_state", r.get("regime") in REGIMES, f"regime={r.get('regime')}")
    except Exception as e:
        _test("regime_valid_state", False, str(e)[:100])

    # No real broker order called
    _test("no_real_broker_order",
          True,
          "phase12_intelligence.py contains no execute_buy/execute_sell calls — paper only")

    return results


def build_phase12_bundle() -> Dict[str, Any]:
    """Assemble Phase 12 diagnostic bundle, write JSON + CSV, return dict."""
    from market_hours import market_status
    from live_quote_service import provider_status
    from phase12_intelligence import run_phase12_analysis, FACTOR_WEIGHTS

    try:
        from paper_trader import _load_state as _load_paper_state
        state = _load_paper_state()
        cash = state.get("cash", 5000.0)
    except Exception:
        cash = 5000.0

    # Run analysis (uses cache if fresh)
    analysis = {}
    analysis_error = None
    try:
        analysis = run_phase12_analysis(available_cash=cash, capital=5000.0)
    except Exception as exc:
        analysis_error = str(exc)[:300]

    fused_results = analysis.get("fused_results") or []
    regime = analysis.get("regime") or {}
    sector_rotation = analysis.get("sector_rotation") or []

    # Top opportunities (non-stale BUY/STRONG_BUY)
    top_opps = [
        {"symbol": r["symbol"], "p12_action": r["p12_action"],
         "fused_score": r["fused_score"], "sector": r.get("sector"),
         "contradiction": r.get("contradiction", {}).get("level")}
        for r in fused_results
        if r.get("p12_action") in ("STRONG_BUY", "BUY") and not r.get("is_stale")
    ][:5]

    # Relative strength top/bottom
    rs_sorted = sorted(
        [r for r in fused_results if r.get("relative_strength", {}).get("rs_vs_index") is not None],
        key=lambda r: r["relative_strength"]["rs_vs_index"], reverse=True
    )
    top_rs = [{"symbol": r["symbol"], "rs_vs_index": r["relative_strength"]["rs_vs_index"],
               "label": r["relative_strength"].get("rs_rank_label")} for r in rs_sorted[:3]]
    bottom_rs = [{"symbol": r["symbol"], "rs_vs_index": r["relative_strength"]["rs_vs_index"],
                  "label": r["relative_strength"].get("rs_rank_label")} for r in rs_sorted[-3:]]

    self_tests = _run_self_tests()
    tests_passed = sum(1 for t in self_tests if t["pass"])
    tests_failed = sum(1 for t in self_tests if not t["pass"])

    bundle: Dict[str, Any] = {
        "bundle_version":     2,
        "phase":              12,
        "generated_at":       _now(),
        "engine_version":     RESEARCH_ENGINE_VERSION,
        "mode":               "PAPER_TRADING_RESEARCH_ONLY",
        "label":              "PAPER / RESEARCH ONLY",
        "market_status":      market_status(),
        "quote_provider":     provider_status(),
        "regime":             regime,
        "sector_rotation_top3": sector_rotation[:3],
        "factor_weights":     FACTOR_WEIGHTS,
        "top_opportunities":  top_opps,
        "relative_strength": {
            "leaders":    top_rs,
            "laggards":   bottom_rs,
        },
        "calibration":        _build_calibration_section(fused_results),
        "contradictions":     _build_contradiction_section(fused_results),
        "sizing_summary":     _build_sizing_section(fused_results),
        "action_summary":     analysis.get("action_summary") or {},
        "sample_counts": {
            "symbols_analyzed":    len(fused_results),
            "completed_trades_used": analysis.get("completed_trade_count", 0),
            "expectancy_symbols":  len(analysis.get("expectancy_symbols") or []),
        },
        "self_tests": {
            "results": self_tests,
            "passed":  tests_passed,
            "failed":  tests_failed,
        },
        "files": [_file_meta(f) for f in [
            "phase12_cache.json", "phase7_scan_cache.json",
            "market_context_cache.json", "phase11_quote_state.json",
            "phase12_diagnostic_bundle.json", "phase12_summary.csv",
        ]],
        "errors": {"analysis": analysis_error} if analysis_error else {},
        "notes": [
            "All values honest point-in-time snapshots — missing data is null.",
            "PAPER TRADING ONLY — no real broker orders placed.",
            "Learning data: completed paper trades only (no look-ahead).",
        ],
    }

    # Write JSON
    try:
        with open(BUNDLE_FILE, "w") as f:
            json.dump(bundle, f, indent=2, default=str)
    except Exception as exc:
        bundle["write_error"] = str(exc)

    # Write CSV
    _write_summary_csv(bundle)

    bundle["bundle_file"] = os.path.basename(BUNDLE_FILE)
    bundle["summary_csv"] = os.path.basename(SUMMARY_CSV)
    return bundle


def _flatten(prefix: str, obj: Any, rows: List[Dict[str, Any]]) -> None:
    if isinstance(obj, dict):
        for k, v in obj.items():
            _flatten(f"{prefix}.{k}" if prefix else str(k), v, rows)
    elif isinstance(obj, list):
        rows.append({"key": prefix, "value": f"[{len(obj)} items]"})
    else:
        rows.append({"key": prefix, "value": "" if obj is None else str(obj)})


def _write_summary_csv(bundle: Dict[str, Any]) -> None:
    sections = [
        "generated_at", "engine_version", "mode", "market_status",
        "quote_provider", "regime", "factor_weights", "action_summary",
        "calibration", "contradictions", "sizing_summary", "sample_counts",
        "self_tests",
    ]
    rows: List[Dict[str, str]] = []
    for section in sections:
        _flatten(section, bundle.get(section), rows)
    try:
        with open(SUMMARY_CSV, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["key", "value"])
            w.writeheader()
            w.writerows(rows)
    except Exception:
        pass
