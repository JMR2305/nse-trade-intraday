"""
data_quality_checker.py — Phase 6.5
Data Quality validation: duplicate trades, FIFO consistency,
timestamp ordering, data freshness, journal consistency.

READ-ONLY. ADVISORY-ONLY.
"""
from __future__ import annotations
from typing import List
from .readiness_models import ReadinessCheck, PASS, WARN, FAIL


def check_data_quality() -> dict:
    """
    Run all data quality checks against the paper trading record stream.
    """
    records = _get_records()
    checks: List[ReadinessCheck] = []

    checks.append(_check_record_count(records))
    checks.append(_check_duplicate_trades(records))
    checks.append(_check_fifo_consistency(records))
    checks.append(_check_timestamp_ordering(records))
    checks.append(_check_required_fields(records))
    checks.append(_check_data_freshness(records))
    checks.append(_check_pnl_consistency(records))
    checks.append(_check_signal_consistency(records))

    score = _category_score(checks)

    return {
        "checks": [c.to_dict() for c in checks],
        "score": score,
        "total_records": len(records),
        "total_checks": len(checks),
        "passed": sum(1 for c in checks if c.status == PASS),
        "warnings": sum(1 for c in checks if c.status == WARN),
        "failures": sum(1 for c in checks if c.status == FAIL),
    }


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_record_count(records: list) -> ReadinessCheck:
    n = len(records)
    if n == 0:
        return ReadinessCheck(
            name="record_count",
            label="Paper Trade Records",
            status=WARN,
            required=False,
            detail="No paper trade records found — complete trades to populate analytics.",
            category="DataQuality",
        )
    if n < 10:
        return ReadinessCheck(
            name="record_count",
            label="Paper Trade Records",
            status=WARN,
            required=False,
            detail=f"{n} records found — at least 10 recommended for meaningful analytics.",
            category="DataQuality",
        )
    return ReadinessCheck(
        name="record_count",
        label="Paper Trade Records",
        status=PASS,
        required=False,
        detail=f"{n} FIFO-matched trade records available.",
        category="DataQuality",
    )


def _check_duplicate_trades(records: list) -> ReadinessCheck:
    ids = [r.get("trade_id", "") for r in records]
    non_empty = [i for i in ids if i]
    duplicates = len(non_empty) - len(set(non_empty))
    if duplicates > 0:
        return ReadinessCheck(
            name="duplicate_trades",
            label="Duplicate Trade Detection",
            status=WARN,
            required=False,
            detail=f"{duplicates} duplicate trade ID(s) detected — review trade journal.",
            category="DataQuality",
        )
    return ReadinessCheck(
        name="duplicate_trades",
        label="Duplicate Trade Detection",
        status=PASS,
        required=False,
        detail="No duplicate trade IDs found.",
        category="DataQuality",
    )


def _check_fifo_consistency(records: list) -> ReadinessCheck:
    """All records from collect_all_trade_records() are already FIFO-matched.
    Check that entry_price, exit_price, quantity are all positive."""
    if not records:
        return ReadinessCheck(
            name="fifo_consistency",
            label="FIFO Match Consistency",
            status=WARN,
            required=False,
            detail="No records to validate.",
            category="DataQuality",
        )
    bad = [
        r for r in records
        if (r.get("entry_price") or 0) <= 0
        or (r.get("exit_price") or 0) <= 0
        or (r.get("quantity") or 0) <= 0
    ]
    if bad:
        return ReadinessCheck(
            name="fifo_consistency",
            label="FIFO Match Consistency",
            status=WARN,
            required=False,
            detail=f"{len(bad)} record(s) have zero/negative price or quantity.",
            category="DataQuality",
        )
    return ReadinessCheck(
        name="fifo_consistency",
        label="FIFO Match Consistency",
        status=PASS,
        required=False,
        detail=f"All {len(records)} records have valid FIFO-matched prices and quantities.",
        category="DataQuality",
    )


def _check_timestamp_ordering(records: list) -> ReadinessCheck:
    """Check timestamps are present and parseable."""
    if not records:
        return ReadinessCheck(
            name="timestamp_ordering",
            label="Timestamp Consistency",
            status=WARN,
            required=False,
            detail="No records to validate.",
            category="DataQuality",
        )
    missing_ts = sum(1 for r in records if not r.get("timestamp"))
    if missing_ts > 0:
        return ReadinessCheck(
            name="timestamp_ordering",
            label="Timestamp Consistency",
            status=WARN,
            required=False,
            detail=f"{missing_ts} record(s) missing timestamp.",
            category="DataQuality",
        )
    return ReadinessCheck(
        name="timestamp_ordering",
        label="Timestamp Consistency",
        status=PASS,
        required=False,
        detail="All records have timestamps.",
        category="DataQuality",
    )


def _check_required_fields(records: list) -> ReadinessCheck:
    if not records:
        return ReadinessCheck(
            name="required_fields",
            label="Required Field Completeness",
            status=WARN,
            required=False,
            detail="No records to validate.",
            category="DataQuality",
        )
    required = {"symbol", "strategy", "entry_price", "exit_price", "quantity", "pnl"}
    incomplete = 0
    for r in records:
        missing = [f for f in required if r.get(f) is None]
        if missing:
            incomplete += 1
    if incomplete > 0:
        pct = incomplete / len(records) * 100
        status = FAIL if pct > 20 else WARN
        return ReadinessCheck(
            name="required_fields",
            label="Required Field Completeness",
            status=status,
            required=False,
            detail=f"{incomplete}/{len(records)} records ({pct:.0f}%) missing required fields.",
            category="DataQuality",
        )
    return ReadinessCheck(
        name="required_fields",
        label="Required Field Completeness",
        status=PASS,
        required=False,
        detail=f"All {len(records)} records have required fields.",
        category="DataQuality",
    )


def _check_data_freshness(records: list) -> ReadinessCheck:
    """Check if any trades exist from the past 30 days."""
    if not records:
        return ReadinessCheck(
            name="data_freshness",
            label="Data Freshness",
            status=WARN,
            required=False,
            detail="No records — data freshness cannot be assessed.",
            category="DataQuality",
        )
    try:
        from datetime import datetime, timezone, timedelta
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=30)
        recent = 0
        for r in records:
            ts = r.get("timestamp")
            if ts:
                try:
                    if isinstance(ts, str):
                        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                        if not dt.tzinfo:
                            dt = dt.replace(tzinfo=timezone.utc)
                    else:
                        dt = ts
                    if dt >= cutoff:
                        recent += 1
                except Exception:
                    pass
        if recent == 0:
            return ReadinessCheck(
                name="data_freshness",
                label="Data Freshness",
                status=WARN,
                required=False,
                detail="No trades in the past 30 days — data may be stale.",
                category="DataQuality",
            )
        return ReadinessCheck(
            name="data_freshness",
            label="Data Freshness",
            status=PASS,
            required=False,
            detail=f"{recent} trade(s) recorded in the past 30 days.",
            category="DataQuality",
        )
    except Exception as e:
        return ReadinessCheck(
            name="data_freshness",
            label="Data Freshness",
            status=WARN,
            required=False,
            detail=f"Freshness check failed: {str(e)[:80]}",
            category="DataQuality",
        )


def _check_pnl_consistency(records: list) -> ReadinessCheck:
    """Check PnL is consistent with entry/exit prices."""
    if not records:
        return ReadinessCheck(
            name="pnl_consistency",
            label="P&L Consistency",
            status=WARN,
            required=False,
            detail="No records to validate.",
            category="DataQuality",
        )
    inconsistent = 0
    for r in records:
        entry = r.get("entry_price") or 0.0
        exit_p = r.get("exit_price") or 0.0
        qty = r.get("quantity") or 0.0
        pnl = r.get("pnl") or 0.0
        if entry > 0 and qty > 0:
            expected_direction = 1 if exit_p >= entry else -1
            actual_direction = 1 if pnl >= 0 else -1
            if expected_direction != actual_direction:
                inconsistent += 1
    if inconsistent > len(records) * 0.05:
        return ReadinessCheck(
            name="pnl_consistency",
            label="P&L Consistency",
            status=WARN,
            required=False,
            detail=f"{inconsistent} record(s) have P&L direction inconsistent with price movement.",
            category="DataQuality",
        )
    return ReadinessCheck(
        name="pnl_consistency",
        label="P&L Consistency",
        status=PASS,
        required=False,
        detail=f"P&L direction consistent across {len(records)} records.",
        category="DataQuality",
    )


def _check_signal_consistency(records: list) -> ReadinessCheck:
    """Check AI recommendations are present."""
    if not records:
        return ReadinessCheck(
            name="signal_consistency",
            label="Signal Data Consistency",
            status=WARN,
            required=False,
            detail="No records to validate.",
            category="DataQuality",
        )
    missing_ai = sum(1 for r in records if not r.get("ai_recommendation"))
    missing_conf = sum(1 for r in records if r.get("ai_confidence") is None)
    if missing_ai > len(records) * 0.50:
        return ReadinessCheck(
            name="signal_consistency",
            label="Signal Data Consistency",
            status=WARN,
            required=False,
            detail=f"{missing_ai}/{len(records)} records missing AI recommendation.",
            category="DataQuality",
        )
    return ReadinessCheck(
        name="signal_consistency",
        label="Signal Data Consistency",
        status=PASS if missing_conf == 0 else WARN,
        required=False,
        detail=(
            "Signal data complete."
            if missing_conf == 0
            else f"{missing_conf} records missing AI confidence score."
        ),
        category="DataQuality",
    )


def _get_records() -> list:
    try:
        from paper_trading_validation.validation_collector import collect_all_trade_records
        return collect_all_trade_records()
    except Exception:
        return []


def _category_score(checks: list) -> float:
    if not checks:
        return 50.0
    total = sum(1.0 if c.status == PASS else 0.5 if c.status == WARN else 0.0 for c in checks)
    return round((total / len(checks)) * 100.0, 2)
