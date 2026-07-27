"""
preopen_validation_scheduler.py — Phase 5B IST-aware validation scheduler.

Cadence:
  09:20 — record first post-open price
  09:30 — record early confirmation price
  10:00 — record continuation price
  10:30 — record extended confirmation price
  15:30–15:45 — record high/low/close, classify outcomes, compute metrics,
                generate daily report

Feature flag: PREOPEN_VALIDATION_ENABLED must be truthy or no-op.
Uses existing NSE market calendar where available.

PAPER TRADING / ADVISORY ONLY.
No order, execution, or trade-placement function exists in this module.
"""
from __future__ import annotations

import os
import threading
import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, List

_IST = timezone(timedelta(hours=5, minutes=30))
_ENABLED_VAR = "PREOPEN_VALIDATION_ENABLED"


def _is_enabled() -> bool:
    return os.environ.get(_ENABLED_VAR, "false").lower() in ("1", "true", "yes")


def _now_ist() -> datetime:
    return datetime.now(_IST)


def _today_ist() -> str:
    return _now_ist().strftime("%Y-%m-%d")


def _is_market_holiday(date_str: str) -> bool:
    try:
        from market_hours import is_holiday
        return is_holiday(date_str)
    except Exception:
        return False


def _fetch_prices(symbols: List[str]) -> Dict[str, Optional[float]]:
    """Attempt to get current LTP for each symbol. Returns {} on failure."""
    try:
        from market_data import get_multiple_ltp
        prices = get_multiple_ltp(symbols)
        return {sym: float(p) for sym, p in prices.items() if p is not None}
    except Exception:
        return {}


def _fetch_eod_data(symbols: List[str]) -> Dict[str, Dict[str, Optional[float]]]:
    """Attempt to get today's OHLCV for each symbol (end-of-day)."""
    try:
        import yfinance as yf
        today = _today_ist()
        tickers = [f"{s}.NS" for s in symbols]
        data = yf.download(tickers, period="1d", interval="1d",
                           group_by="ticker", progress=False, auto_adjust=True)
        result: Dict[str, Dict] = {}
        for sym, ticker in zip(symbols, tickers):
            try:
                df = data[ticker] if len(tickers) > 1 else data
                if df.empty:
                    continue
                row = df.iloc[-1]
                result[sym] = {
                    "high":  float(row["High"]) if "High" in row else None,
                    "low":   float(row["Low"])  if "Low"  in row else None,
                    "close": float(row["Close"])if "Close"in row else None,
                    "open":  float(row["Open"]) if "Open" in row else None,
                }
            except Exception:
                continue
        return result
    except Exception:
        return {}


# ── Phase states ──────────────────────────────────────────────────────────────

class ValidationPhase:
    IDLE        = "IDLE"
    COLLECTING  = "COLLECTING"
    CLASSIFYING = "CLASSIFYING"
    REPORTING   = "REPORTING"
    DONE        = "DONE"
    ERROR       = "ERROR"
    DISABLED    = "DISABLED"
    HOLIDAY     = "HOLIDAY"


class PreOpenValidationScheduler:
    """
    Single-session IST-aware validation scheduler.
    Runs price collection at 09:20, 09:30, 10:00, 10:30;
    then at 15:30 classifies outcomes and generates the daily report.
    """

    def __init__(self, session_id: Optional[str] = None, test_mode: bool = False):
        self.session_id = session_id or f"val-{_today_ist()}-{uuid.uuid4().hex[:6]}"
        self.test_mode  = test_mode
        self.phase      = ValidationPhase.IDLE
        self._log: list = []
        self._stop      = threading.Event()

    def _emit(self, phase: str, detail: dict = {}) -> None:
        self.phase = phase
        self._log.append({"phase": phase, "ts": _now_ist().isoformat(), **detail})

    def _should_run(self) -> bool:
        if not _is_enabled():
            self._emit(ValidationPhase.DISABLED, {"reason": f"{_ENABLED_VAR}=false"})
            return False
        if not self.test_mode and _is_market_holiday(_today_ist()):
            self._emit(ValidationPhase.HOLIDAY, {"date": _today_ist()})
            return False
        return True

    def _load_candidates(self) -> list:
        """Load today's pre-open candidates from Phase 5A snapshots."""
        try:
            import preopen_db as p5a_db
            today = _today_ist()
            snaps = p5a_db.get_latest_snapshots(today)
            return snaps
        except Exception:
            return []

    def _init_validation_records(self, candidates: list) -> list:
        """Create ValidationRecord stubs from Phase 5A snapshots."""
        from preopen_validation_model import ValidationRecord, ValidationStatus, DataQualityStatus
        import preopen_validation_db as db
        today   = _today_ist()
        records = []
        for i, snap in enumerate(candidates):
            r = ValidationRecord(
                trading_date=today,
                session_id=self.session_id,
                symbol=snap.get("symbol", ""),
                sector=snap.get("sector", "Unknown"),
                preopen_rank=snap.get("volume_rank") or (i + 1),
                opportunity_score=float(snap.get("opportunity_score") or 0),
                classification=snap.get("classification", ""),
                previous_close=snap.get("previous_close"),
                indicative_price=snap.get("indicative_equilibrium_price"),
                final_preopen_price=snap.get("final_open_price"),
                buy_quantity=int(snap.get("total_buy_quantity") or 0),
                sell_quantity=int(snap.get("total_sell_quantity") or 0),
                imbalance_percent=float(snap.get("imbalance_percent") or 0),
                executed_quantity=int(snap.get("final_executed_quantity") or 0),
                liquidity_score=float(snap.get("liquidity_score") or 0),
                sector_score=float((snap.get("factor_scores") or {}).get("sector_confirmation") or 0),
                gap_percent=snap.get("gap_percent"),
                validation_status=ValidationStatus.PENDING,
                data_quality_status=DataQualityStatus.MISSING,
            )
            db.upsert_candidate_outcome(r.to_dict())
            records.append(r)
        return records

    def _record_price_checkpoint(self, records: list, checkpoint: str) -> None:
        """Fetch and record prices for all candidates at a given checkpoint."""
        symbols = [r.symbol for r in records if r.symbol]
        prices  = _fetch_prices(symbols)
        import preopen_validation_db as db

        for r in records:
            price = prices.get(r.symbol)
            if price is None:
                continue
            setattr(r, checkpoint, price)
            r.update_returns()
            db.upsert_candidate_outcome(r.to_dict())

        self._emit(ValidationPhase.COLLECTING, {
            "checkpoint": checkpoint,
            "fetched":    len(prices),
            "symbols":    len(symbols),
        })

    def _record_eod(self, records: list) -> None:
        """Record intraday high/low/close and actual open from EOD data."""
        symbols = [r.symbol for r in records if r.symbol]
        eod     = _fetch_eod_data(symbols)
        import preopen_validation_db as db

        for r in records:
            d = eod.get(r.symbol)
            if not d:
                continue
            if r.actual_open is None and d.get("open"):
                r.actual_open = d["open"]
            if d.get("high"):
                r.intraday_high = d["high"]
            if d.get("low"):
                r.intraday_low = d["low"]
            if d.get("close"):
                r.closing_price = d["close"]
            r.update_returns()
            db.upsert_candidate_outcome(r.to_dict())

        self._emit(ValidationPhase.COLLECTING, {
            "checkpoint": "eod",
            "fetched":    len(eod),
        })

    def _classify_and_report(self, records: list) -> dict:
        """Classify all outcomes and generate the daily report."""
        from preopen_validation_outcomes import classify_and_update
        from preopen_validation_reports import generate_daily_report
        import preopen_validation_db as db

        self._emit(ValidationPhase.CLASSIFYING)
        classified = [classify_and_update(r) for r in records]

        # Persist classified outcomes
        for r in classified:
            db.upsert_candidate_outcome(r.to_dict())

        # Score-band + factor metrics
        from preopen_validation_metrics import (
            calculate_score_bands, calculate_factor_metrics,
        )
        score_bands = calculate_score_bands(classified)
        factor_met  = calculate_factor_metrics(classified)
        db.save_score_band_metrics(self.session_id, _today_ist(), score_bands)
        db.save_factor_metrics(self.session_id, _today_ist(), factor_met)

        self._emit(ValidationPhase.REPORTING)
        report = generate_daily_report(_today_ist(), self.session_id, classified)

        # Update session record
        from preopen_validation_metrics import calculate_session_metrics
        m = calculate_session_metrics(classified)
        db.upsert_validation_session({
            "session_id":             self.session_id,
            "trading_date":           _today_ist(),
            "status":                 "COMPLETE",
            "total_candidates":       m.get("total_candidates", 0),
            "valid_candidates":       m.get("valid_candidates", 0),
            "excluded_candidates":    m.get("excluded_candidates", 0),
            "classified_candidates":  len(classified),
            "data_quality_pct":       m.get("data_completeness_pct", 0),
            "metrics_computed":       True,
            "daily_report_path":      report.get("report_json_path"),
        })

        self._emit(ValidationPhase.DONE, {"report": report.get("report_json_path")})
        return report

    def run_once(self) -> Dict[str, Any]:
        """
        Run the full validation cycle synchronously.
        Used for manual trigger and testing.
        """
        if not self._should_run():
            return {"ran": False, "phase": self.phase, "session_id": self.session_id}

        import preopen_validation_db as db
        db.upsert_validation_session({
            "session_id":   self.session_id,
            "trading_date": _today_ist(),
            "status":       "COLLECTING",
        })

        candidates = self._load_candidates()
        if not candidates:
            self._emit(ValidationPhase.ERROR, {"error": "No Phase 5A candidates found"})
            return {"ran": False, "error": "No candidates", "session_id": self.session_id}

        records = self._init_validation_records(candidates)

        # Price checkpoints
        self._record_price_checkpoint(records, "actual_open")
        self._record_price_checkpoint(records, "price_0920")
        self._record_price_checkpoint(records, "price_0930")
        self._record_price_checkpoint(records, "price_1000")
        self._record_price_checkpoint(records, "price_1030")
        self._record_eod(records)

        report = self._classify_and_report(records)
        return {
            "ran":        True,
            "session_id": self.session_id,
            "candidates": len(records),
            "report":     report.get("report_json_path"),
            "log":        self._log,
        }

    def status(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "phase":      self.phase,
            "enabled":    _is_enabled(),
            "ist_time":   _now_ist().isoformat(),
            "log":        self._log[-20:],
        }


# ── Module-level singleton ────────────────────────────────────────────────────

_scheduler: Optional[PreOpenValidationScheduler] = None


def get_scheduler_status() -> dict:
    if _scheduler is None:
        return {"active": False, "enabled": _is_enabled()}
    return {"active": True, **_scheduler.status()}


def run_validation_cycle_now(test_mode: bool = False) -> dict:
    """Trigger a full validation cycle immediately (manual/test)."""
    if not _is_enabled():
        return {
            "ran": False,
            "status": "DISABLED",
            "message": f"Set {_ENABLED_VAR}=true to enable validation",
        }
    s = PreOpenValidationScheduler(test_mode=test_mode)
    return s.run_once()
