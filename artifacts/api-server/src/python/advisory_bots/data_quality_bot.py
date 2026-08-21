"""Fail-closed data-quality checks for advisory strategy inputs."""

from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Any, Dict, Iterable, Mapping

from .contracts import advisory_output


ACCEPTED_QUALITIES = frozenset({"LIVE", "NEAR_LIVE"})


def check_symbol_quality(
    symbol: str,
    data: Mapping[str, Any] | None,
    *,
    master_row: Mapping[str, Any] | None = None,
    now: datetime | None = None,
    max_age_seconds: int = 900,
    scan_id: str | None = None,
    build_id: str = "phase2b-dev",
    config_hash: str = "phase2b-default",
) -> Dict[str, Any]:
    """Return a quality verdict; never substitutes unsupported market data."""
    data = dict(data or {})
    master_row = dict(master_row or {})
    reasons: list[str] = []
    quality = str(data.get("data_quality") or data.get("quality") or "").upper()
    if master_row.get("ohlcv_available") is not True:
        reasons.append("master_ohlcv_unavailable")
    if quality not in ACCEPTED_QUALITIES:
        reasons.append(f"data_quality={quality or 'MISSING'}")

    price = data.get("current_price", data.get("price", data.get("ltp")))
    volume = data.get("volume")
    if not _positive_finite(price):
        reasons.append("missing_price")
    if not _positive_finite(volume):
        reasons.append("missing_volume")

    snapshot_ts = data.get("snapshot_ts") or data.get("timestamp")
    age_seconds = None
    if not snapshot_ts:
        reasons.append("missing_snapshot_timestamp")
    else:
        parsed = _parse_timestamp(snapshot_ts)
        if parsed is None:
            reasons.append("invalid_snapshot_timestamp")
        else:
            reference = now or datetime.now(timezone.utc)
            if parsed > reference:
                reasons.append("future_snapshot_timestamp")
            age_seconds = max(0.0, (reference - parsed).total_seconds())
            if age_seconds > max_age_seconds:
                reasons.append(f"stale_age_seconds={round(age_seconds, 1)}")

    healthy = not reasons
    return advisory_output(
        symbol=symbol,
        bot_name="data-quality-bot",
        strategy_name="DATA_QUALITY",
        score=100 if healthy else 0,
        decision="WATCH" if healthy else "BLOCKED_DATA_QUALITY",
        reason="required price, volume, OHLCV, and freshness checks passed" if healthy else "; ".join(reasons),
        data_quality="PASS" if healthy else "BLOCKED",
        risk_flags=[] if healthy else ["DATA_QUALITY_BLOCK"],
        scan_id=scan_id,
        build_id=build_id,
        config_hash=config_hash,
        age_seconds=age_seconds,
        eligible_for_scoring=healthy,
    )


def check_universe_quality(
    active_rows: Iterable[Mapping[str, Any]],
    scan_items: Iterable[Mapping[str, Any]],
    **kwargs: Any,
) -> Dict[str, Any]:
    """Check each active custom symbol against the matching scan item."""
    active_rows = [dict(row) for row in active_rows]
    by_symbol = {
        str(item.get("symbol") or item.get("Symbol") or "").strip().upper(): dict(item)
        for item in scan_items
        if isinstance(item, Mapping)
    }
    outputs = []
    eligible = []
    blocked = []
    for row in active_rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        result = check_symbol_quality(symbol, by_symbol.get(symbol), master_row=row, **kwargs)
        outputs.append(result)
        (eligible if result["decision"] == "WATCH" else blocked).append(symbol)
    return {
        "outputs": outputs,
        "eligible_symbols": eligible,
        "blocked_symbols": blocked,
        "all_healthy": not blocked and len(eligible) == len(list(active_rows)),
        "advisory_only": True,
        "paper_only": True,
    }


def _parse_timestamp(value: Any) -> datetime | None:
    try:
        text = str(value).replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _positive_finite(value: Any) -> bool:
    try:
        return math.isfinite(float(value)) and float(value) > 0
    except (TypeError, ValueError):
        return False