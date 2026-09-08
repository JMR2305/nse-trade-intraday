"""Tests for balanced_decision_model.py — Phase 3A Balanced Decision Model."""
from __future__ import annotations
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd

import balanced_decision_model as b
from confidence_calibration import fit_calibrator

_passed = 0
_failed = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ✓ {label}")
    else:
        _failed += 1
        print(f"  ✗ {label}" + (f" — {detail}" if detail else ""))


def _item(**over):
    base = {
        "stock": "RELIANCE", "sector": "ENERGY",
        "confidence": 62.0, "opportunity_score": 58.0, "rr_ratio": 2.0,
        "volume_ratio": 1.2, "price": 100.0, "stop_loss": 95.0,
        "target": 110.0, "rsi": 55.0, "adx": 25.0, "atr": 2.1,
        "vwap": 99.0, "ema20": 98.0, "ema50": 96.0,
        "best_regime": "bullish", "live_signal": True,
        "best_strategy_id": "macd_cross", "best_strategy_name": "MACD",
        "technical_action": "BUY", "max_data_timestamp": "2024-02-01",
    }
    base.update(over)
    return base


_CAL = fit_calibrator([(30 + i * 1.5, 1 if i % 5 else 0) for i in range(40)])
_STATS_POS = {"trades": 25, "expectancy": 1.2, "profit_factor": 1.6}


def test_balanced_decision_model():
    global _passed, _failed
    _passed = _failed = 0
    # ── 1. Normalisers: bounds and smooth ramps (spec §B/§E) ─────────────────────
    print("1. Normalisers — bounds and smooth ramps")

    for fn, vals in ((b.normalize_technical, (-50, 0, 50, 100, 250, None)),
                     (b.normalize_opportunity, (-10, 0, 40, 47, 55, 100, 999, None)),
                     (b.normalize_volume, (-1, 0, 0.5, 1.0, 2.0, 9, None)),
                     (b.normalize_rr, (-1, 0, 1, 4, 40, None))):
        outs = [fn(v) for v in vals]
        check(f"{fn.__name__} stays within 0-100",
              all(0.0 <= o <= 100.0 for o in outs), str(outs))

    opp_grid = [b.normalize_opportunity(x / 10.0) for x in range(0, 1001)]
    mono = all(opp_grid[i] <= opp_grid[i + 1] + 1e-9 for i in range(len(opp_grid) - 1))
    max_step = max(abs(opp_grid[i + 1] - opp_grid[i]) for i in range(len(opp_grid) - 1))
    check("opportunity ramp is monotonic", mono)
    check("opportunity ramp has no cliffs (max step per 0.1 pt < 1.0)",
          max_step < 1.0, f"max_step={max_step}")
    check("opportunity 40-55 transition is gradual",
          abs(b.normalize_opportunity(47.5) - 40.0) < 5.0,
          str(b.normalize_opportunity(47.5)))

    vol_grid = [b.normalize_volume(x / 100.0) for x in range(0, 301)]
    check("volume ramp monotonic",
          all(vol_grid[i] <= vol_grid[i + 1] + 1e-9 for i in range(len(vol_grid) - 1)))
    check("regime alignment bounded",
          all(0 <= b.normalize_regime(_item(), r) <= 100
              for r in ("Bullish", "Neutral-Bullish", "Neutral-Bearish",
                        "Bearish", "Unknown", "", None)))
    check("regime alignment proportional (Bullish > Neutral > Bearish)",
          b.normalize_regime(_item(best_regime=""), "Bullish")
          > b.normalize_regime(_item(best_regime=""), "Neutral-Bearish")
          > b.normalize_regime(_item(best_regime=""), "Bearish"))

    # ── 2. Data quality multiplier ────────────────────────────────────────────────
    print("2. Data quality reliability multiplier")
    dq_full = b.data_quality(_item())
    dq_none = b.data_quality({k: 0 for k in
                              ("price", "rsi", "adx", "atr", "vwap", "ema20",
                               "ema50", "volume_ratio")})
    check("full data → multiplier 1.0", dq_full["multiplier"] == 1.0)
    check("no data → multiplier at floor",
          abs(dq_none["multiplier"] - b.DATA_QUALITY_MULT_MIN) < 1e-9)
    check("missing fields listed", len(dq_none["missing"]) == 8)

    comp = b.compute_components(_item(), "Bullish",
                                b.shrink_and_cap_adjustments(0, 0, 0, 0, 0))
    score_full = b.balanced_score(comp, dq_full)
    score_poor = b.balanced_score(comp, dq_none)
    check("poor data shrinks the score toward neutral 50",
          abs(score_poor["final_score"] - 50.0) < abs(score_full["final_score"] - 50.0)
          or score_full["final_score"] == 50.0)

    # ── 3. Adjustment shrinkage + caps (spec §D) ─────────────────────────────────
    print("3. Adjustment caps and Bayesian shrinkage")
    adj = b.shrink_and_cap_adjustments(30, 1000, 30, 20, 1000)
    check("adaptive capped at ±10", abs(adj["adaptive_post_cap"]) <= 10.0 + 1e-9)
    check("similarity capped at ±10", abs(adj["similarity_post_cap"]) <= 10.0 + 1e-9)
    check("combined capped at ±15",
          abs(adj["adaptive_post_cap"] + adj["similarity_post_cap"]) <= 15.0 + 1e-9)
    check("pre-cap values reported", adj["adaptive_pre_cap"] == 60.0
          and adj["similarity_pre_cap"] == 20.0)
    check("combined cap flag set", adj["combined_cap_applied"] is True)

    neg = b.shrink_and_cap_adjustments(-40, 1000, -10, -30, 1000)
    check("negative combined capped at -15",
          neg["adaptive_post_cap"] + neg["similarity_post_cap"] >= -15.0 - 1e-9)

    s_small = b.shrink_and_cap_adjustments(10, 2, 0, 10, 2)
    s_large = b.shrink_and_cap_adjustments(10, 50, 0, 10, 50)
    check("shrinkage: small samples shrink more",
          abs(s_small["adaptive_post_cap"]) < abs(s_large["adaptive_post_cap"])
          and abs(s_small["similarity_post_cap"]) < abs(s_large["similarity_post_cap"]))
    s_zero = b.shrink_and_cap_adjustments(15, 0, 0, 12, 0)
    check("zero evidence → zero evidence-based adjustment",
          s_zero["adaptive_post_cap"] == 0.0 and s_zero["similarity_post_cap"] == 0.0)

    prop = b.shrink_and_cap_adjustments(200, 10000, 0, 100, 10000)
    ratio = (prop["adaptive_post_cap"] / prop["similarity_post_cap"]
             if prop["similarity_post_cap"] else 0)
    check("combined cap rescales both paths proportionally (dedupe guard)",
          abs(ratio - 1.0) < 0.01, str(prop))

    # ── 4. Component table (spec §B) ──────────────────────────────────────────────
    print("4. Component table")
    check("weights sum to 100", abs(sum(b.BALANCED_WEIGHTS.values()) - 100.0) < 1e-9)
    comp = b.compute_components(_item(), "Bullish",
                                b.shrink_and_cap_adjustments(8, 25, 4, 6, 20))
    check("all 7 components present", set(comp) == set(b.BALANCED_WEIGHTS))
    check("every component reports raw/normalized/weight/contribution",
          all({"raw", "normalized", "weight_pct", "weighted_contribution"}
              <= set(v) for v in comp.values()))
    check("normalized values within 0-100",
          all(0 <= v["normalized"] <= 100 for v in comp.values()))
    check("contribution = normalized × weight",
          all(abs(v["weighted_contribution"]
                  - v["normalized"] * v["weight_pct"] / 100.0) < 0.011
              for v in comp.values()))

    # ── 5. Eligibility gates vs soft penalties (spec §A) ─────────────────────────
    print("5. Hard gates vs soft penalties")
    ok = b.evaluate_eligibility(_item(), sizing_budget=1000.0)
    check("healthy item passes all gates", ok["all_passed"], str(ok["failed"]))
    bad_rr = b.evaluate_eligibility(_item(rr_ratio=0.4), sizing_budget=1000.0)
    check("RR below absolute minimum fails gate", "min_risk_reward" in bad_rr["failed"])
    weak_rr = b.evaluate_eligibility(_item(rr_ratio=1.0), sizing_budget=1000.0)
    check("weak-but-legal RR does NOT hard-reject", weak_rr["all_passed"])
    no_lvl = b.evaluate_eligibility(_item(stop_loss=0, target=0), sizing_budget=1000.0)
    check("missing stop/target fails valid_levels", "valid_levels" in no_lvl["failed"])
    illiq = b.evaluate_eligibility(_item(volume_ratio=0.1), sizing_budget=1000.0)
    check("illiquidity fails gate", "liquidity" in illiq["failed"])
    weak_vol = b.evaluate_eligibility(_item(volume_ratio=0.6), sizing_budget=1000.0)
    check("weak volume is a penalty, not a gate", weak_vol["all_passed"])
    too_exp = b.evaluate_eligibility(_item(price=5000.0, stop_loss=4800.0,
                                           target=5500.0), sizing_budget=1000.0)
    check("impossible sizing fails gate", "sizing_possible" in too_exp["failed"])
    dis = b.evaluate_eligibility(_item(), strategy_eligible=False,
                                 strategy_reason="disabled", sizing_budget=1000.0)
    check("disabled strategy fails gate", "strategy_policy" in dis["failed"])
    port = b.evaluate_eligibility(_item(), portfolio_ok=False, sizing_budget=1000.0)
    check("portfolio limit fails gate", "portfolio_limits" in port["failed"])

    # ── 6. Labels (spec §G) ───────────────────────────────────────────────────────
    print("6. Shadow labels")
    check("gate failure → NO TRADE regardless of probability",
          b.shadow_label(0.95, gates_passed=False, live_signal=True,
                         evidence="positive", reliability_ok=True) == "NO TRADE")
    check("validated negative expectancy → AVOID",
          b.shadow_label(0.80, gates_passed=True, live_signal=True,
                         evidence="negative", reliability_ok=True) == "AVOID")
    check("p>=0.70 + live + positive evidence + reliable → STRONG BUY",
          b.shadow_label(0.72, gates_passed=True, live_signal=True,
                         evidence="positive", reliability_ok=True) == "STRONG BUY")
    check("p>=0.70 without reliability → BUY",
          b.shadow_label(0.72, gates_passed=True, live_signal=True,
                         evidence="positive", reliability_ok=False) == "BUY")
    check("p>=0.60 + live → BUY",
          b.shadow_label(0.65, gates_passed=True, live_signal=True,
                         evidence="neutral", reliability_ok=False) == "BUY")
    check("promising setup missing confirmation → WATCH",
          b.shadow_label(0.72, gates_passed=True, live_signal=False,
                         evidence="positive", reliability_ok=True) == "WATCH")
    check("0.45 <= p < 0.60 → WATCH",
          b.shadow_label(0.50, gates_passed=True, live_signal=True,
                         evidence="neutral", reliability_ok=False) == "WATCH")
    check("p < 0.45 → AVOID",
          b.shadow_label(0.30, gates_passed=True, live_signal=True,
                         evidence="neutral", reliability_ok=False) == "AVOID")

    check("expectancy evidence needs sample (n<10 → neutral)",
          b.expectancy_evidence({"trades": 5, "expectancy": -5.0,
                                 "profit_factor": 0.2}) == "neutral")
    check("validated negative expectancy detected",
          b.expectancy_evidence({"trades": 20, "expectancy": -1.0,
                                 "profit_factor": 0.7}) == "negative")

    # ── 7. score_decision: determinism, missing data, calibration isolation ─────
    print("7. score_decision — determinism / robustness / calibration isolation")
    kw = dict(pattern_adj=8, pattern_stats=_STATS_POS, model_adj=4, sim_adj=6,
              sim_matches=20, calibrator=_CAL, sizing_budget=1000.0)
    r1 = b.score_decision(_item(), "Bullish", **kw)
    r2 = b.score_decision(_item(), "Bullish", **kw)
    check("deterministic (identical output on identical input)", r1 == r2)

    empty = {k: None for k in _item()}
    r3 = b.score_decision(empty, None, pattern_adj=None, pattern_stats=None,
                          model_adj=None, sim_adj=None, sim_matches=None,
                          calibrator=None, sizing_budget=None)
    check("missing/None data never crashes", isinstance(r3["score"]["final_score"], float))
    check("missing data → NO TRADE via gates", r3["label"] == "NO TRADE")
    check("missing data shrinks toward 50",
          r3["score"]["data_quality_multiplier"] == b.DATA_QUALITY_MULT_MIN)

    cal_a = fit_calibrator([(50 + i, 1) for i in range(35)])   # optimistic window
    cal_b = fit_calibrator([(50 + i, 0) for i in range(35)])   # pessimistic window
    pa = b.score_decision(_item(), "Bullish", **{**kw, "calibrator": cal_a})
    pb = b.score_decision(_item(), "Bullish", **{**kw, "calibrator": cal_b})
    check("per-window calibrators are isolated (different windows → different probs)",
          pa["calibration"]["calibrated_probability"]
          > pb["calibration"]["calibrated_probability"],
          f"{pa['calibration']['calibrated_probability']} vs "
          f"{pb['calibration']['calibrated_probability']}")
    check("calibrated probability within [0,1]",
          0.0 <= pa["calibration"]["calibrated_probability"] <= 1.0)

    # ── 8. Verdict logic (spec §L) ────────────────────────────────────────────────
    print("8. Final recommendation logic")


    class _Cfg:
        initial_capital = 5000.0
        verdict_criteria = {"max_drawdown_pct": 20.0}


    def _fake_inputs(n_trades=50, expectancy=1.0, pf=1.5, dd=8.0, brier_g=0.20,
                     brier_c=0.25, violations=0, fp_g=10.0, fp_c=20.0,
                     windows_pos=2, windows_total=2, conc_flags=None):
        gm = {"total_trades": n_trades, "expectancy": expectancy,
              "profit_factor": pf, "max_drawdown_pct": dd}
        wins = ([{"net_return_pct": 1.0}] * windows_pos
                + [{"net_return_pct": -1.0}] * (windows_total - windows_pos))
        cal = {"balanced_model": {"brier_score": brier_g},
               "current_model": {"brier_score": brier_c}}
        cmp_rows = [{"model": "C", "false_positive_rate_pct": fp_c},
                    {"model": "G", "false_positive_rate_pct": fp_g}]
        conc = {"flags": conc_flags or []}
        fp = {"false_positive_rate_pct": fp_g}
        audit = {"lookahead_violations": violations}
        return gm, wins, cal, cmp_rows, conc, fp, audit


    v = b._final_recommendation(*_fake_inputs(), _Cfg())
    check("all criteria pass → ELIGIBLE FOR LIMITED SHADOW PAPER TEST",
          v["recommendation"] == "ELIGIBLE FOR LIMITED SHADOW PAPER TEST",
          v["summary"])
    check("verdict never auto-activates", v["auto_activation"] is False)
    check("every check has observed/threshold/passed",
          all({"name", "observed", "threshold", "passed"} <= set(c)
              for c in v["checks"]))

    v = b._final_recommendation(*_fake_inputs(violations=3), _Cfg())
    check("lookahead violation → REJECT", v["recommendation"] == "REJECT")
    v = b._final_recommendation(*_fake_inputs(expectancy=-0.5, pf=0.8), _Cfg())
    check("sufficient sample + negative expectancy → REJECT",
          v["recommendation"] == "REJECT")
    v = b._final_recommendation(*_fake_inputs(n_trades=10, expectancy=-0.5, pf=0.8),
                                _Cfg())
    check("insufficient sample → CONTINUE ANALYSIS (not REJECT)",
          v["recommendation"] == "CONTINUE ANALYSIS")
    v = b._final_recommendation(*_fake_inputs(brier_g=0.30), _Cfg())
    check("worse calibration → CONTINUE ANALYSIS",
          v["recommendation"] == "CONTINUE ANALYSIS")
    v = b._final_recommendation(*_fake_inputs(conc_flags=["one stock dominates"]),
                                _Cfg())
    check("concentration flag blocks eligibility",
          v["recommendation"] == "CONTINUE ANALYSIS")

    # ── 9. Synthetic end-to-end window simulation ────────────────────────────────
    print("9. simulate_window_balanced — synthetic end-to-end")


    class _FakeStrategy:
        name = "Fake MACD"
        best_regime = "bullish"

        def check_entry(self, last, prev):
            return bool(last["close"] > last["ema20"]), "trend up"

        def compute_stop_loss(self, last, price):
            return price * 0.95

        def compute_target(self, price, stop):
            return price + (price - stop) * 2.0

        def check_exit(self, row, prev, entry, stop, target):
            return False, ""


    def _synthetic_rows(n=120, start_price=100.0):
        dates = pd.bdate_range("2024-01-01", periods=n)
        rows = []
        price = start_price
        for i, d in enumerate(dates):
            price = price * (1.003 if i % 7 else 0.997)
            rows.append({
                "date": d, "open": price * 0.999, "high": price * 1.01,
                "low": price * 0.99, "close": price, "volume": 1_000_000.0,
                "rsi": 55.0, "adx": 25.0, "atr": price * 0.02,
                "vwap": price * 0.998, "ema9": price * 0.999,
                "ema20": price * 0.99, "ema50": price * 0.97,
                "ema200": price * 0.9, "macd_line": 1.0, "macd_signal": 0.5,
                "macd_hist": 0.5, "supertrend": price * 0.96,
                "volume_ratio": 1.4,
            })
        return pd.DataFrame(rows)


    def _run_synthetic():
        rows = _synthetic_rows()
        sym_rows = {"TESTSYM": rows}
        date_pos = {"TESTSYM": {str(r["date"])[:10]: i
                                for i, r in rows.iterrows()}}
        nifty = rows.set_index("date")[["close", "high", "low"]]
        test_days = list(nifty.index[70:100])
        window = {"label": "W1", "test_start": str(test_days[0])[:10],
                  "test_end": str(test_days[-1])[:10]}
        trained = {"TESTSYM": {"strategy": _FakeStrategy(), "strategy_id": "fake",
                               "metrics": {"total_trades": 30}, "perf": 72.0}}
        ctx = {"knowledge": [], "vectors": [], "model_weights": None,
               "model_version": 0}

        class _SimCfg:
            initial_capital = 5000.0
            intrabar_rule = "conservative"
            max_holding_days = 10
            verdict_criteria = {"max_drawdown_pct": 20.0}

        from execution_simulator import CostModel
        lookahead = {"decisions": 0, "violations": 0, "max_timestamp": "",
                     "max_knowledge_timestamp": "", "max_similarity_timestamp": ""}
        out = b.simulate_window_balanced(
            window, sym_rows, date_pos, trained, test_days, nifty, ctx,
            _SimCfg(), CostModel(), _CAL, None, None, lookahead_log=lookahead)
        return out, lookahead


    out, lookahead = _run_synthetic()
    check("window simulation completes", isinstance(out, dict))
    check("equity curve covers every test day", len(out["equity_curve"]) == 30)
    check("decisions were scored", sum(out["label_counts"].values()) > 0,
          str(out["label_counts"]))
    check("transition matrix populated", len(out["transitions"]) > 0)
    check("lookahead audit ran with zero violations",
          lookahead["decisions"] > 0 and lookahead["violations"] == 0,
          str(lookahead))
    check("metrics computed", "total_trades" in out["metrics"])
    check("cash time within 0-100", 0.0 <= out["cash_time_pct"] <= 100.0)
    out2, _ = _run_synthetic()
    t1 = [(t["symbol"], t["entry_date"], t["exit_date"], t["net_pnl"])
          for t in out["trades"]]
    t2 = [(t["symbol"], t["entry_date"], t["exit_date"], t["net_pnl"])
          for t in out2["trades"]]
    check("simulation is deterministic", t1 == t2 and
          out["equity_curve"] == out2["equity_curve"])

    # ── 10. Report aggregation ────────────────────────────────────────────────────
    print("10. build_balanced_report")
    overall = {v: {"total_trades": 10, "total_return_pct": 2.0, "expectancy": 0.5,
                   "profit_factor": 1.3, "max_drawdown_pct": 5.0,
                   "sharpe_ratio": 1.0, "win_rate": 55.0, "total_costs": 100.0}
               for v in ("A", "B", "C", "D", "E")}
    layer_comparison = [
        {"variant": v, "label": f"{v} — model", "cash_time_pct": 50.0}
        for v in ("A", "B", "C", "D", "E")]
    all_trades = {v: [{"recommendation": "BUY", "net_pnl": 100.0 if i % 2 else -50.0,
                       "gross_pnl": 120.0, "return_pct": 2.0, "holding_days": 4,
                       "market_regime": "Bullish", "confidence": 60.0,
                       "strategy_name": "MACD", "sector": "IT",
                       "symbol": f"S{i}", "exit_date": "2024-02-10"}
                      for i in range(6)] for v in ("A", "B", "C", "D", "E")}
    cal_rep = {"samples": 40, "after": {"brier_score": 0.24, "ece": 0.08,
                                        "log_loss": 0.65}}
    report = b.build_balanced_report([out], overall, layer_comparison, all_trades,
                                     _Cfg(), cal_rep, lookahead, [])
    check("report has model comparison incl. G",
          any(r["model"] == "G" for r in report["model_comparison"])
          and len(report["model_comparison"]) == 6)
    check("config displayed with weights and caps",
          report["config"]["weights"] == b.BALANCED_WEIGHTS
          and "adjustment_caps" in report["config"])
    check("transition matrix in report",
          "cells" in report["transition_matrix"])
    check("recommendation distribution present",
          isinstance(report["recommendation_distribution"], dict))
    check("calibration comparison present",
          "balanced_model" in report["calibration_comparison"])
    check("safety audit says analysis-only",
          report["safety_audit"]["analysis_only"] is True
          and report["safety_audit"]["live_recommendations_changed"] is False)
    check("final recommendation is one of the three verdicts",
          report["final_recommendation"]["recommendation"] in
          ("REJECT", "CONTINUE ANALYSIS",
           "ELIGIBLE FOR LIMITED SHADOW PAPER TEST"))
    check("window errors surface in safety audit",
          b.build_balanced_report([out], overall, layer_comparison, all_trades,
                                  _Cfg(), cal_rep, lookahead,
                                  ["W2: boom"])["safety_audit"]["window_errors"]
          == ["W2: boom"])

    print(f"\n{'='*60}\nPASSED: {_passed}  FAILED: {_failed}")
    assert _failed == 0, f"{_failed} balanced-decision checks failed"


if __name__ == "__main__":
    test_balanced_decision_model()
