"""
ai_performance/metadata_integrity.py — Guard against silently-lost trade metadata.

Context: portfolio_store flattens the JSONB metadata column back onto the
trade dict, so signal_confidence / market_regime_at_entry / strategy_id must
appear as TOP-LEVEL keys on each trade. If a writer nests them under a
"metadata" key instead, strategy_intelligence reads signal_confidence as 0.0
and every trade lands in the "Below 60" bucket — analytics degrade silently
with no error.

This module detects that failure class:
  * wrong-shape rows — a trade carrying a dict under "metadata" that itself
    contains signal fields (definite mis-shaped writer);
  * mass zero-confidence — most BUY trades have signal_confidence missing/0,
    which is the observable symptom of the same bug.

READ-ONLY, advisory-only. Never raises.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# Signal fields that must be top-level on the trade dict (flattened metadata).
SIGNAL_FIELDS = ("signal_confidence", "market_regime_at_entry", "regime",
                 "strategy_id", "strategy_name", "stop_loss", "target",
                 "exit_type", "pnl", "pnl_pct")

# Flag when more than this fraction of BUY trades carry zero/missing confidence.
ZERO_CONFIDENCE_PCT_THRESHOLD = 80.0
# Don't flag tiny samples — one or two manual trades without metadata are fine.
MIN_SAMPLE = 3


def check_metadata_integrity(
    trades: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Return an advisory data-quality verdict on trade metadata shape.

    trades: raw trade dicts (as returned by portfolio_store loaders). When
    None, loads all trades (current + archived) from portfolio_store.
    """
    try:
        if trades is None:
            from portfolio_store import load_all_trades_any
            trades = load_all_trades_any()

        buys = [t for t in trades if isinstance(t, dict)
                and t.get("action") == "BUY"]
        total_buys = len(buys)

        zero_conf = 0
        nested_rows: List[str] = []
        for t in buys:
            conf = t.get("signal_confidence")
            try:
                if conf is None or float(conf) == 0.0:
                    zero_conf += 1
            except (TypeError, ValueError):
                zero_conf += 1
            meta = t.get("metadata")
            if isinstance(meta, dict) and any(f in meta for f in SIGNAL_FIELDS):
                nested_rows.append(str(t.get("id", "")))

        zero_pct = round(zero_conf / total_buys * 100, 2) if total_buys else 0.0

        warnings: List[str] = []
        if nested_rows:
            warnings.append(
                f"{len(nested_rows)} trade(s) carry signal fields NESTED under "
                "a 'metadata' key instead of top-level — a writer is storing "
                "metadata in the wrong shape; confidence/regime/strategy "
                "analytics will silently read defaults for these trades."
            )
        if total_buys >= MIN_SAMPLE and zero_pct > ZERO_CONFIDENCE_PCT_THRESHOLD:
            warnings.append(
                f"{zero_pct}% of {total_buys} BUY trades have "
                "signal_confidence missing or 0 — AI confidence analytics are "
                "effectively zeroed. Likely cause: trade metadata written in "
                "the wrong shape (nested instead of top-level keys)."
            )

        return {
            "ok": not warnings,
            "flagged": bool(warnings),
            "total_buy_trades": total_buys,
            "zero_confidence_trades": zero_conf,
            "zero_confidence_pct": zero_pct,
            "nested_metadata_trades": len(nested_rows),
            "nested_metadata_trade_ids": nested_rows[:20],
            "threshold_pct": ZERO_CONFIDENCE_PCT_THRESHOLD,
            "min_sample": MIN_SAMPLE,
            "warnings": warnings,
        }
    except Exception as exc:  # advisory guard must never break analytics
        return {"ok": False, "flagged": False,
                "error": str(exc)[:300], "warnings": []}
