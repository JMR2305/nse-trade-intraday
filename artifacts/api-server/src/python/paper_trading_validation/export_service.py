"""
export_service.py — Phase 6.1
CSV and JSON export for validation records.
Future-ready for PDF (placeholder stub included).
"""
from __future__ import annotations
import csv
import io
import json
from typing import List

from .validation_models import TradeRecord


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

CSV_HEADERS = [
    "trade_id", "timestamp", "symbol", "strategy", "market_regime", "sector",
    "entry_price", "exit_price", "quantity", "holding_time_minutes",
    "pnl", "pnl_pct", "execution_quality_score", "ai_confidence",
    "ai_recommendation", "signal_validation_status", "risk_score",
    "portfolio_value_at_entry", "executive_score_snapshot", "exit_reason",
]


def export_csv(records: List[TradeRecord]) -> str:
    """Return CSV string of all trade records."""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=CSV_HEADERS, extrasaction="ignore")
    writer.writeheader()
    for rec in records:
        writer.writerow(rec.to_dict())
    return output.getvalue()


# ---------------------------------------------------------------------------
# JSON export
# ---------------------------------------------------------------------------

def export_json(records: List[TradeRecord]) -> str:
    """Return JSON string array of all trade records."""
    return json.dumps([rec.to_dict() for rec in records], indent=2, default=str)


# ---------------------------------------------------------------------------
# PDF stub (future-ready)
# ---------------------------------------------------------------------------

def export_pdf_stub() -> dict:
    """
    PDF export is not implemented yet.
    Returns a metadata stub indicating it is future-ready.
    """
    return {
        "status": "NOT_IMPLEMENTED",
        "message": "PDF export is future-ready. Install reportlab or weasyprint to implement.",
        "future_fields": CSV_HEADERS,
    }
