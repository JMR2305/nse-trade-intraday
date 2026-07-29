"""Phase 7.4 – Historical similarity: find up to 5 past setups matching today's signal."""
from __future__ import annotations
from typing import Any, Dict, List

from .models import HistoricalMatch


def _similarity_score(current: Dict[str, Any], historical: Dict[str, Any]) -> float:
    """Simple heuristic similarity 0–1 between two signal records."""
    score = 0.0
    checks = 0

    # Signal direction match
    checks += 1
    if current.get("signal") == historical.get("signal"):
        score += 1.0

    # Regime match
    checks += 1
    if current.get("regime") == historical.get("regime"):
        score += 1.0

    # Confidence proximity (within 10 percentage points)
    checks += 1
    c_conf = float(current.get("confidence", 0.5) or 0.5)
    h_conf = float(historical.get("confidence", 0.5) or 0.5)
    if abs(c_conf - h_conf) <= 0.10:
        score += 1.0

    # Risk level match
    checks += 1
    if current.get("risk_level") == historical.get("risk_level"):
        score += 1.0

    return score / checks if checks > 0 else 0.0


def find_historical_matches(
    symbol: str,
    signal: Dict[str, Any],
    all_snapshots: List[Dict[str, Any]],
    max_results: int = 5,
) -> List[HistoricalMatch]:
    """Return up to `max_results` best historical matches for the current signal."""
    scored: List[tuple] = []
    for snap in all_snapshots:
        if snap.get("stock") == symbol or snap.get("symbol") == symbol:
            sim = _similarity_score(signal, snap)
            if sim >= 0.50:  # at least half the criteria must match
                scored.append((sim, snap))

    # Sort by similarity descending then by timestamp descending
    scored.sort(key=lambda x: (x[0], x[1].get("time", "")), reverse=True)
    top = scored[:max_results]

    results: List[HistoricalMatch] = []
    for sim, snap in top:
        sig_type = snap.get("signal", "HOLD")
        conf     = float(snap.get("confidence", 0.5) or 0.5)
        regime   = snap.get("regime", "NEUTRAL") or "NEUTRAL"
        ts       = snap.get("time", "unknown")
        outcome  = snap.get("outcome", "UNKNOWN")
        pnl      = snap.get("pnl_pct", None)

        match_reasons = []
        if snap.get("signal") == signal.get("signal"):
            match_reasons.append(f"Same signal direction ({sig_type})")
        if snap.get("regime") == signal.get("regime"):
            match_reasons.append(f"Same market regime ({regime})")
        if abs(conf - float(signal.get("confidence", 0.5) or 0.5)) <= 0.10:
            match_reasons.append(f"Similar confidence ({conf * 100:.0f}%)")
        if snap.get("risk_level") == signal.get("risk_level"):
            match_reasons.append(f"Matching risk level ({snap.get('risk_level', 'N/A')})")

        pnl_str = f"{pnl:+.2f}%" if pnl is not None else "N/A"

        results.append(
            HistoricalMatch(
                symbol=symbol,
                date=ts,
                signal_type=sig_type,
                regime=regime,
                confidence=conf,
                outcome=outcome,
                pnl_pct=pnl,
                similarity_score=round(sim, 3),
                match_reasons=match_reasons,
                narrative=(
                    f"On {ts}, {symbol} generated a {sig_type} signal in a {regime} regime "
                    f"with {conf * 100:.0f}% confidence. Outcome: {outcome} ({pnl_str})."
                ),
            )
        )

    return results
