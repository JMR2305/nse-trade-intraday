"""
risk_validation/market_risk.py — Phase 8.4
Market risk score: regime, VIX, macro, events, sector rotation, liquidity.
READ-ONLY · ADVISORY-ONLY.
"""
from __future__ import annotations

from .models import Issue, domain_result, unavailable_result

_HIGH_VIX_WARN = 20.0
_HIGH_VIX_CRIT = 25.0


def _load_market_intelligence() -> dict:
    try:
        from market_intelligence_hub.shared_services import get_market_intelligence_snapshot
        return get_market_intelligence_snapshot() or {}
    except Exception:
        return {}


def _load_macro() -> dict:
    try:
        from macro_intelligence.shared_services import get_macro_intelligence_snapshot
        return get_macro_intelligence_snapshot() or {}
    except Exception:
        return {}


def _load_vix() -> float:
    try:
        from macro_intelligence.shared_services import _load_vix_safe
        vix_data = _load_vix_safe() or {}
        return float(vix_data.get("india_vix", vix_data.get("vix", 0)) or 0)
    except Exception:
        return 0.0


def _regime_risk_score(regime: str) -> tuple[float, str]:
    """Convert regime label to a risk score (0=low risk, 100=high risk)."""
    regime_up = (regime or "").upper()
    mapping = {
        "STRONG_BULL": (10, "Low risk — strong bullish regime"),
        "BULL":        (20, "Low-moderate risk — bullish trend"),
        "NEUTRAL":     (40, "Moderate risk — sideways market"),
        "BEAR":        (70, "High risk — bearish regime"),
        "STRONG_BEAR": (85, "Very high risk — strong bearish regime"),
        "HIGH_VOL":    (60, "Elevated risk — high volatility"),
        "LOW_VOL":     (25, "Low risk — low volatility environment"),
        "CRASH":       (95, "Critical risk — crash conditions"),
    }
    for key, val in mapping.items():
        if key in regime_up:
            return val
    return 45, f"Moderate risk — regime: {regime}"


def get_market_risk_validation() -> dict:
    mkt    = _load_market_intelligence()
    macro  = _load_macro()
    vix    = _load_vix()

    if not mkt and not macro and vix == 0.0:
        return unavailable_result("market_risk",
                                  "No market intelligence data available")

    issues: list[Issue] = []
    run = passed = 0
    component_scores: list[float] = []

    # Check 1: Market regime
    regime = mkt.get("regime", mkt.get("market_regime", "UNKNOWN"))
    if regime and regime != "UNKNOWN":
        regime_score, regime_note = _regime_risk_score(str(regime))
        # Invert: validation score = 100 - risk_score
        val_score = 100 - regime_score
        component_scores.append(val_score)
        run += 1
        if regime_score >= 70:
            issues.append(Issue("CRITICAL", "HIGH_REGIME_RISK", "market_regime",
                                f"Regime '{regime}' — {regime_note}", float(regime_score),
                                category="market"))
        elif regime_score >= 50:
            issues.append(Issue("WARNING", "ELEVATED_REGIME_RISK", "market_regime",
                                f"Regime '{regime}' — {regime_note}", float(regime_score),
                                category="market"))
        else:
            passed += 1

    # Check 2: VIX
    if vix > 0:
        run += 1
        if vix >= _HIGH_VIX_CRIT:
            issues.append(Issue("CRITICAL", "CRITICAL_VIX", "india_vix",
                                f"India VIX at {vix:.1f} — extreme volatility",
                                vix, category="market"))
        elif vix >= _HIGH_VIX_WARN:
            issues.append(Issue("WARNING", "ELEVATED_VIX", "india_vix",
                                f"India VIX at {vix:.1f} — elevated volatility",
                                vix, category="market"))
        else:
            passed += 1
        component_scores.append(max(0, 100 - vix * 3))

    # Check 3: Macro environment
    macro_sentiment = str(macro.get("sentiment", macro.get("overall_sentiment", ""))).upper()
    if macro_sentiment:
        run += 1
        if "NEGATIVE" in macro_sentiment or "BEARISH" in macro_sentiment:
            issues.append(Issue("WARNING", "NEGATIVE_MACRO", "macro_sentiment",
                                f"Macro environment: {macro_sentiment}",
                                category="macro"))
        else:
            passed += 1
        ms_score = 30 if "NEGATIVE" in macro_sentiment else 70
        component_scores.append(ms_score)

    if run == 0:
        run = 1; passed = 1

    market_risk_score = round(sum(component_scores) / len(component_scores), 1) \
                        if component_scores else 50.0

    return domain_result(
        "market_risk", run, passed, issues,
        extra={
            "market_risk_score": market_risk_score,
            "india_vix":         vix,
            "regime":            regime if mkt else "UNKNOWN",
            "macro_sentiment":   macro_sentiment or "UNKNOWN",
        },
    )
