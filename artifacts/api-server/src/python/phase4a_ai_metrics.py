"""
phase4a_ai_metrics.py — Phase 4A Section 5: AI Performance Tracking.

Tracks AI advisory statistics against actual trade outcomes:

  1.  buy_count           — BUY recommendations issued
  2.  watch_count         — WATCH recommendations issued
  3.  no_trade_count      — NO_TRADE / AVOID / EXIT recommendations
  4.  false_positives     — BUY recs where trade resulted in a loss
  5.  false_negatives     — NO_TRADE recs for stocks that later showed profit
  6.  avg_confidence      — mean calibrated_confidence across all signals
  7.  avg_explanation_latency_ms — mean latency from signal_ts to explanation
  8.  agreement_rate_pct  — % agreement between AI rec and deterministic signal

AI never executes trades. This module is read-only.

Usage:
    uv run python phase4a_ai_metrics.py [--date YYYY-MM-DD]

PAPER TRADING / RESEARCH ONLY.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
from typing import Any, Optional

_DIR = os.path.dirname(os.path.abspath(__file__))
_DOCS = os.path.join(_DIR, "..", "..", "docs")
os.makedirs(_DOCS, exist_ok=True)

LABEL = "PAPER TRADING / RESEARCH ONLY"


def _now_ist() -> str:
    try:
        import zoneinfo
        return datetime.datetime.now(zoneinfo.ZoneInfo("Asia/Kolkata")).isoformat()
    except Exception:
        return datetime.datetime.utcnow().isoformat() + "Z"


def _parse_dt(s: Optional[str]) -> Optional[datetime.datetime]:
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def _get_signals() -> list[dict]:
    """Load current signals from API or directly from cache."""
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:8080/api/signals", timeout=6) as r:
            data = json.loads(r.read())
            return data if isinstance(data, list) else data.get("signals", [])
    except Exception:
        pass
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:8080/api/phase15/scan-context", timeout=6) as r:
            data = json.loads(r.read())
            return data.get("recommendations", [])
    except Exception:
        pass
    return []


def _get_closed_trades() -> list[dict]:
    """Load closed Phase 20 paper trades."""
    try:
        from phase20_executor import get_ledger
        return [t for t in get_ledger(500)
                if t.get("status") == "CLOSED"
                and t.get("realized_pnl") is not None]
    except Exception:
        return []


def _classify_action(action: str) -> str:
    """Normalise signal action to BUY / WATCH / NO_TRADE."""
    a = str(action or "").upper()
    if a in ("BUY", "STRONG_BUY"):
        return "BUY"
    if a in ("WATCH", "HOLD", "MONITOR"):
        return "WATCH"
    return "NO_TRADE"


def compute_ai_metrics(date_str: Optional[str] = None) -> dict:
    """Compute all 8 AI performance metrics."""
    target_date = date_str or datetime.date.today().isoformat()

    signals = _get_signals()
    closed_trades = _get_closed_trades()

    # Map symbol → closed trade P&L for outcome matching
    trade_by_symbol: dict[str, float] = {}
    for t in closed_trades:
        sym = str(t.get("symbol") or "").upper()
        pnl = float(t.get("realized_pnl") or 0)
        trade_by_symbol[sym] = trade_by_symbol.get(sym, 0) + pnl

    # Counters
    buy_count = 0
    watch_count = 0
    no_trade_count = 0
    false_positives = 0    # BUY rec → resulted in a loss
    false_negatives = 0    # NO_TRADE rec → stock would have been profitable
    confidences: list[float] = []
    latencies_ms: list[float] = []
    agreement_count = 0    # AI agrees with deterministic signal
    total_comparable = 0   # signals with both AI and deterministic fields

    for sig in signals:
        sym = str(sig.get("stock") or sig.get("symbol") or "").upper()

        # AI recommendation field
        ai_action_raw = str(sig.get("ai_recommendation") or
                            sig.get("copilot_recommendation") or
                            sig.get("ai_signal") or "")
        # Deterministic final_action
        det_action_raw = str(sig.get("signal") or sig.get("final_action") or "")

        ai_action = _classify_action(ai_action_raw) if ai_action_raw else None
        det_action = _classify_action(det_action_raw) if det_action_raw else None

        # Count by AI action (fall back to deterministic if no AI field)
        display_action = ai_action or det_action or "NO_TRADE"
        if display_action == "BUY":
            buy_count += 1
        elif display_action == "WATCH":
            watch_count += 1
        else:
            no_trade_count += 1

        # Agreement rate
        if ai_action and det_action:
            total_comparable += 1
            if ai_action == det_action:
                agreement_count += 1

        # Confidence
        conf = sig.get("calibrated_confidence") or sig.get("confidence") or sig.get("ai_confidence")
        if conf is not None:
            try:
                confidences.append(float(conf))
            except Exception:
                pass

        # Explanation latency: signal_ts → explanation_ts
        sig_ts = _parse_dt(sig.get("signal_ts") or sig.get("scan_ts"))
        exp_ts = _parse_dt(sig.get("explanation_ts") or sig.get("ai_ts") or sig.get("updated_at"))
        if sig_ts and exp_ts and exp_ts > sig_ts:
            lat_ms = (exp_ts - sig_ts).total_seconds() * 1000
            if 0 < lat_ms < 120_000:   # sanity: < 2 min
                latencies_ms.append(lat_ms)

        # False positive: AI said BUY but trade lost money
        if display_action == "BUY" and sym in trade_by_symbol:
            if trade_by_symbol[sym] < 0:
                false_positives += 1

        # False negative: AI said NO_TRADE but stock was profitable
        if display_action == "NO_TRADE" and sym in trade_by_symbol:
            if trade_by_symbol[sym] > 0:
                false_negatives += 1

    total_recs = buy_count + watch_count + no_trade_count
    avg_confidence = round(sum(confidences) / len(confidences), 2) if confidences else None
    avg_latency_ms = round(sum(latencies_ms) / len(latencies_ms), 1) if latencies_ms else None
    agreement_rate_pct = round(agreement_count / total_comparable * 100, 1) \
        if total_comparable > 0 else None

    metrics = {
        "label": LABEL,
        "computed_at": _now_ist(),
        "date": target_date,
        "advisory_only": True,
        "signals_evaluated": len(signals),
        "closed_trades_compared": len(closed_trades),
        # 8 required metrics
        "buy_count": buy_count,
        "watch_count": watch_count,
        "no_trade_count": no_trade_count,
        "false_positives": false_positives,
        "false_negatives": false_negatives,
        "avg_confidence": avg_confidence,
        "avg_explanation_latency_ms": avg_latency_ms,
        "agreement_rate_pct": agreement_rate_pct,
        # Supporting stats
        "total_recommendations": total_recs,
        "buy_pct": round(buy_count / total_recs * 100, 1) if total_recs > 0 else 0,
        "watch_pct": round(watch_count / total_recs * 100, 1) if total_recs > 0 else 0,
        "no_trade_pct": round(no_trade_count / total_recs * 100, 1) if total_recs > 0 else 0,
        "confidence_samples": len(confidences),
        "latency_samples": len(latencies_ms),
        "comparable_signals": total_comparable,
    }
    return metrics


def print_metrics(m: dict) -> None:
    print(f"\n{'=' * 60}")
    print(f"  Phase 4A AI Performance Metrics — {m['date']}")
    print(f"  {m['label']}")
    print(f"  advisory_only=True  (AI never executes trades)")
    print(f"{'=' * 60}")
    print(f"  Signals evaluated:      {m['signals_evaluated']}")
    print(f"  BUY recommendations:    {m['buy_count']} ({m['buy_pct']}%)")
    print(f"  WATCH recommendations:  {m['watch_count']} ({m['watch_pct']}%)")
    print(f"  NO TRADE recommendations:{m['no_trade_count']} ({m['no_trade_pct']}%)")
    print(f"  False positives:        {m['false_positives']}")
    print(f"  False negatives:        {m['false_negatives']}")
    print(f"  Avg confidence:         {m['avg_confidence']}%")
    print(f"  Avg explanation latency:{m['avg_explanation_latency_ms']}ms")
    print(f"  Agreement with determ.: {m['agreement_rate_pct']}%")
    print(f"{'=' * 60}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 4A AI metrics")
    parser.add_argument("--date", type=str, default=None)
    args = parser.parse_args()
    m = compute_ai_metrics(args.date)
    print_metrics(m)
    date_compact = m["date"].replace("-", "")
    out = os.path.join(_DOCS, f"ai_metrics_{date_compact}.json")
    with open(out, "w") as f:
        json.dump(m, f, indent=2, default=str)
    print(f"\n  Saved: {out}")
