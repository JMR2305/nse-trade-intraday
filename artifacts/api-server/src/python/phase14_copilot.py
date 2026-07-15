"""
phase14_copilot.py — Phase 14: AI Copilot Q&A over the learning layer.

RESEARCH ONLY. Every answer states sample size, reliability, and that the
conclusion is research-only.
"""
from __future__ import annotations

from phase14_learning import load_evaluation, learning_rows, reliability_label
from phase14_adjustments import load_adjustments, learning_frozen
from phase14_calibration import calibration_status
from phase14_governance import list_models, load_drift, promotion_checklist

DISCLAIMER = "Research-only conclusion from paper trades; not investment advice."


def _n() -> tuple[int, str]:
    n = len(learning_rows(only_audited=True))
    return n, reliability_label(n)


def answer_question(question: str) -> dict:
    q = (question or "").lower()
    n, rel = _n()
    base = {"sample_size": n, "reliability": rel, "research_only": True,
            "disclaimer": DISCLAIMER}

    if "why" in q and ("confidence" in q and "change" in q or "adjust" in q):
        adj = load_adjustments()
        active = [
            f"{src}:{key} → {e['adjustment']:+.1f} ({e['reason']})"
            for src, entries in adj.get("sources", {}).items()
            for key, e in entries.items() if e.get("adjustment")
        ]
        text = ("Confidence changes come from calibration plus bounded adaptive "
                "adjustments (±5/source, ±10 total). "
                + ("Active adjustments: " + "; ".join(active) if active
                   else f"No adjustments are active — evidence is {rel} with only {n} completed trades, so all sources contribute 0."))
        return {**base, "answer": text}

    if "learned" in q or "learning" in q and "what" in q:
        ev = load_evaluation()
        o = ev.get("overall", {})
        return {**base, "answer": (
            f"The model has {n} completed paper trades ({rel} reliability). "
            f"Overall: win rate {o.get('win_rate')}, expectancy ₹{o.get('expectancy')}, "
            f"profit factor {o.get('profit_factor')}. With reliability below MODERATE, "
            "no behavioural adjustments are applied yet.")}

    if "strongest" in q or ("which strategy" in q and "strong" in q):
        ev = load_evaluation()
        best = max(ev.get("by_strategy", {}).items(),
                   key=lambda kv: (kv[1].get("expectancy") or -1e9), default=None)
        if not best:
            return {**base, "answer": "No strategy evidence yet."}
        k, m = best
        return {**base, "answer": (
            f"Highest-expectancy strategy so far: {k} (expectancy ₹{m.get('expectancy')}, "
            f"PF {m.get('profit_factor')}, {m.get('sample_size')} trades, "
            f"{m.get('reliability')} reliability). "
            + ("Sample too small to act on." if not m.get("display_conclusions") else ""))}

    if "deteriorat" in q or "weakest" in q or "worst" in q:
        ev = load_evaluation()
        worst = min(ev.get("by_strategy", {}).items(),
                    key=lambda kv: (kv[1].get("expectancy") or 1e9), default=None)
        if not worst:
            return {**base, "answer": "No strategy evidence yet."}
        k, m = worst
        return {**base, "answer": (
            f"Lowest-expectancy strategy so far: {k} (expectancy ₹{m.get('expectancy')}, "
            f"{m.get('sample_size')} trades, {m.get('reliability')} reliability). "
            "Drift monitoring tracks per-strategy win-rate deterioration between halves of history.")}

    if "calibration" in q and ("reliable" in q or "trust" in q):
        cs = calibration_status()
        return {**base, "answer": (
            f"Active calibrator: {cs.get('active_version') or 'identity'} "
            f"({cs.get('active_method')}). {cs.get('warning') or 'Sample size adequate.'} "
            "Calibrators are trained on chronological splits and auto-fall back when "
            "a new one performs worse out-of-sample.")}

    if "rejected" in q and "model" in q:
        reg = list_models()
        rejected = [m for m in reg.get("models", []) if m.get("status") == "REJECTED"]
        if not rejected:
            return {**base, "answer": "No models have been rejected yet."}
        return {**base, "answer": "Rejected models: " + "; ".join(
            f"{m['model_version']} (approval {m.get('approval_status')})" for m in rejected)}

    if "promote" in q or "promotion" in q or "challenger" in q:
        reg = list_models()
        chal = [m for m in reg.get("models", []) if m.get("status") == "CHALLENGER"]
        if chal:
            cl = promotion_checklist(chal[0]["model_version"])
            failing = [c["check"] for c in cl.get("checks", []) if not c["passed"]]
            return {**base, "answer": (
                f"Challenger {chal[0]['model_version']} promotion requires: "
                + "; ".join(failing) + ". Promotion always needs explicit human approval.")}
        return {**base, "answer": (
            "No challenger exists. Promotion requires ≥100 completed OOS trades, "
            "3 test windows, positive expectancy, PF>1.10, Sharpe>0, acceptable "
            "drawdown, clean look-ahead audit, calibration parity, passing safety "
            "tests, and explicit human approval.")}

    if "drift" in q:
        dr = load_drift()
        frozen = learning_frozen()
        return {**base, "answer": (
            f"Drift status: {dr.get('overall_severity')} across "
            f"{len(dr.get('indicators', []))} indicators. "
            f"Learning frozen: {frozen.get('frozen')}. "
            "Critical drift freezes positive adjustments and blocks promotion, "
            "but never disables safety controls.")}

    if "evidence" in q and "adjustment" in q:
        adj = load_adjustments()
        lines = [
            f"{src}:{key} adj={e['adjustment']:+.1f}, n={e['sample_size']}, "
            f"rel={e['reliability']}, reason={e['reason']}"
            for src, entries in adj.get("sources", {}).items()
            for key, e in entries.items()
        ][:12]
        return {**base, "answer": "Adjustment evidence: " + (" | ".join(lines) or "none")}

    return {**base, "answer": (
        f"Phase 14 learning status: {n} completed trades ({rel}). Ask about: "
        "confidence changes, what the model learned, strongest/deteriorating "
        "strategy, calibration reliability, model rejections, promotion "
        "requirements, drift, or adjustment evidence.")}
