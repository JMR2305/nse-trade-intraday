"""Phase 7.5 – Historical replay engine (read-only, no production impact)."""
from __future__ import annotations
from typing import Any, Dict, List, Optional

from .models import ReplayFrame


def _outcome(signal: Dict[str, Any]) -> str:
    pnl = signal.get("pnl_pct") or signal.get("outcome")
    if pnl is None:
        return "UNKNOWN"
    if isinstance(pnl, (int, float)):
        return "WIN" if float(pnl) >= 0 else "LOSS"
    s = str(pnl).upper()
    if "WIN" in s or "PROFIT" in s:  return "WIN"
    if "LOSS" in s or "FAIL" in s:   return "LOSS"
    return "UNKNOWN"


def build_replay_frames(
    snapshots: List[Dict[str, Any]],
    limit: int = 50,
) -> List[ReplayFrame]:
    """
    Convert historical signal snapshots into replay frames.
    Sorted by timestamp descending (most recent first).
    Returns up to `limit` frames.
    """
    frames: List[ReplayFrame] = []

    for i, snap in enumerate(snapshots[:limit * 2]):
        symbol  = snap.get("stock") or snap.get("symbol") or "UNKNOWN"
        ts      = snap.get("time") or snap.get("snapshot_ts") or f"frame-{i}"
        sig     = snap.get("signal", "NO_TRADE")
        conf    = float(snap.get("confidence", 0.5) or 0.5)
        if conf > 1.0:
            conf /= 100.0
        price   = snap.get("price")
        regime  = snap.get("regime") or "NEUTRAL"
        reasons = snap.get("reasons") or []
        reason  = reasons[0] if reasons else (
            snap.get("explanation", {}) or {}
        ).get("plain_english", f"{sig} signal generated.")

        frames.append(ReplayFrame(
            frame_id=f"{symbol}-{i}",
            timestamp=str(ts),
            symbol=symbol,
            signal_type=sig,
            confidence=round(conf, 3),
            price=float(price) if price else None,
            regime=str(regime),
            reason=str(reason)[:200],
            outcome=_outcome(snap),
            pnl_pct=float(snap["pnl_pct"]) if snap.get("pnl_pct") is not None else None,
        ))

    # Sort by timestamp descending (best-effort string sort)
    frames.sort(key=lambda f: f.timestamp, reverse=True)
    return frames[:limit]


def replay_summary(frames: List[ReplayFrame]) -> Dict[str, Any]:
    """Aggregate statistics over a set of replay frames."""
    if not frames:
        return {
            "total_frames": 0,
            "win_count": 0, "loss_count": 0, "unknown_count": 0,
            "win_rate": 0.0, "avg_confidence": 0.0,
            "symbols_covered": 0, "regimes_seen": [],
        }

    wins    = sum(1 for f in frames if f.outcome == "WIN")
    losses  = sum(1 for f in frames if f.outcome == "LOSS")
    unknown = sum(1 for f in frames if f.outcome == "UNKNOWN")
    total   = len(frames)

    win_rate   = wins / total if total else 0.0
    avg_conf   = sum(f.confidence for f in frames) / total

    symbols_seen = {f.symbol for f in frames}
    regimes_seen = list({f.regime for f in frames})

    return {
        "total_frames":    total,
        "win_count":       wins,
        "loss_count":      losses,
        "unknown_count":   unknown,
        "win_rate":        round(win_rate, 3),
        "avg_confidence":  round(avg_conf, 3),
        "symbols_covered": len(symbols_seen),
        "regimes_seen":    regimes_seen,
    }
