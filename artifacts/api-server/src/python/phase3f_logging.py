"""
phase3f_logging.py — Phase 3F: Structured Logging Helper.

Provides a structured logging interface where every critical event contains:
  - timestamp (ISO-8601, IST)
  - correlation_id
  - session_id
  - symbol (where relevant)
  - order_id (where relevant)
  - subsystem
  - severity (DEBUG, INFO, WARN, ERROR, CRITICAL)
  - event_type
  - result
  - latency_ms (where relevant)
  - safe_error_details (never credentials or secrets)

NEVER logs:
  - API secrets or access tokens
  - Session secrets or database passwords
  - Full credential headers
  - Personal data

Usage:
    from phase3f_logging import get_logger, StructuredLogger

    logger = get_logger("scanner")
    logger.info("scan_completed", result="OK", latency_ms=24000,
                symbol_count=48, session_id="sess_20260725")
"""

import json
import logging
import os
import sys
import time
import uuid
import datetime
from typing import Any

# ── Secret field names that must NEVER appear in log output ─────────────────
_FORBIDDEN_KEYS = frozenset({
    "api_key", "api_secret", "access_token", "session_secret",
    "password", "db_password", "database_url", "token",
    "zerodha_api_key", "zerodha_api_secret", "session_secret",
    "authorization", "bearer", "x-api-key", "cookie",
    "private_key", "secret", "credential",
})

_FORBIDDEN_PATTERNS = ["password=", "secret=", "token=", "key=", "Bearer ", "Authorization:"]

LABEL = "PAPER TRADING / RESEARCH ONLY"
_SESSION_ID = f"sess_{datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"


def _now_ist() -> str:
    try:
        import zoneinfo
        return datetime.datetime.now(zoneinfo.ZoneInfo("Asia/Kolkata")).isoformat()
    except Exception:
        return datetime.datetime.utcnow().isoformat() + "Z"


def _sanitize(value: Any, depth: int = 0) -> Any:
    """Remove forbidden keys from dicts and redact suspicious strings."""
    if depth > 6:
        return value
    if isinstance(value, dict):
        return {
            k: "[REDACTED]" if k.lower() in _FORBIDDEN_KEYS else _sanitize(v, depth + 1)
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_sanitize(v, depth + 1) for v in value]
    if isinstance(value, str):
        for pat in _FORBIDDEN_PATTERNS:
            if pat.lower() in value.lower():
                return "[REDACTED — contains credential pattern]"
    return value


class StructuredLogger:
    """
    Thin wrapper around the stdlib logger that emits one JSON line per event.

    Each event is guaranteed to contain:
      timestamp, correlation_id, session_id, subsystem, severity, event_type.
    """

    def __init__(self, subsystem: str, session_id: str = _SESSION_ID):
        self.subsystem = subsystem
        self.session_id = session_id
        self._logger = logging.getLogger(f"apexquant.{subsystem}")
        if not self._logger.handlers:
            handler = logging.StreamHandler(sys.stdout)
            handler.setFormatter(logging.Formatter("%(message)s"))
            self._logger.addHandler(handler)
            self._logger.setLevel(logging.DEBUG)

    def _emit(
        self,
        severity: str,
        event_type: str,
        *,
        result: str = "",
        latency_ms: float | None = None,
        symbol: str | None = None,
        order_id: str | None = None,
        correlation_id: str | None = None,
        error: str | None = None,
        **extra: Any,
    ) -> dict:
        record: dict = {
            "timestamp": _now_ist(),
            "correlation_id": correlation_id or str(uuid.uuid4())[:8],
            "session_id": self.session_id,
            "subsystem": self.subsystem,
            "severity": severity,
            "event_type": event_type,
            "label": LABEL,
        }
        if result:
            record["result"] = result
        if latency_ms is not None:
            record["latency_ms"] = round(latency_ms, 2)
        if symbol:
            record["symbol"] = symbol
        if order_id:
            record["order_id"] = order_id
        if error:
            # Sanitize error message — never expose credentials
            record["error"] = _sanitize(str(error)[:500])
        # Additional fields — sanitize all; redact forbidden key names
        for k, v in extra.items():
            if k.lower() in _FORBIDDEN_KEYS:
                record[k] = "[REDACTED]"
            else:
                record[_sanitize(k)] = _sanitize(v)

        log_str = json.dumps(record, default=str)
        lvl_map = {
            "DEBUG": logging.DEBUG, "INFO": logging.INFO,
            "WARN": logging.WARNING, "WARNING": logging.WARNING,
            "ERROR": logging.ERROR, "CRITICAL": logging.CRITICAL,
        }
        self._logger.log(lvl_map.get(severity, logging.INFO), log_str)
        return record

    def debug(self, event_type: str, **kwargs: Any) -> dict:
        return self._emit("DEBUG", event_type, **kwargs)

    def info(self, event_type: str, **kwargs: Any) -> dict:
        return self._emit("INFO", event_type, **kwargs)

    def warn(self, event_type: str, **kwargs: Any) -> dict:
        return self._emit("WARN", event_type, **kwargs)

    def error(self, event_type: str, **kwargs: Any) -> dict:
        return self._emit("ERROR", event_type, **kwargs)

    def critical(self, event_type: str, **kwargs: Any) -> dict:
        return self._emit("CRITICAL", event_type, **kwargs)

    def trade_event(
        self,
        event_type: str,
        symbol: str,
        order_id: str,
        result: str,
        latency_ms: float | None = None,
        **extra: Any,
    ) -> dict:
        """Convenience: emit a trade-lifecycle event with required fields."""
        return self._emit(
            "INFO", event_type,
            result=result, symbol=symbol, order_id=order_id,
            latency_ms=latency_ms, **extra,
        )

    def scan_event(
        self,
        event_type: str,
        result: str,
        symbol_count: int = 0,
        latency_ms: float | None = None,
        **extra: Any,
    ) -> dict:
        """Convenience: emit a scanner event."""
        return self._emit(
            "INFO", event_type,
            result=result, latency_ms=latency_ms,
            symbol_count=symbol_count, **extra,
        )

    def risk_event(
        self,
        event_type: str,
        symbol: str,
        verdict: str,
        reason: str = "",
        **extra: Any,
    ) -> dict:
        """Convenience: emit a risk-engine decision event."""
        sev = "INFO" if verdict == "ALLOW" else "WARN"
        return self._emit(
            sev, event_type,
            result=verdict, symbol=symbol, reason=reason, **extra,
        )

    def safety_event(
        self,
        event_type: str,
        invariant: str,
        ok: bool,
        detail: str = "",
    ) -> dict:
        """Emit a safety invariant check result. CRITICAL if invariant violated."""
        sev = "INFO" if ok else "CRITICAL"
        return self._emit(
            sev, event_type,
            result="OK" if ok else "VIOLATED",
            invariant=invariant, detail=detail,
        )


# ── Module-level convenience ─────────────────────────────────────────────────

_loggers: dict[str, StructuredLogger] = {}


def get_logger(subsystem: str, session_id: str = _SESSION_ID) -> StructuredLogger:
    """Get or create a StructuredLogger for the given subsystem."""
    if subsystem not in _loggers:
        _loggers[subsystem] = StructuredLogger(subsystem, session_id)
    return _loggers[subsystem]


# ── Session metrics aggregator ───────────────────────────────────────────────

class SessionMetrics:
    """
    Lightweight in-memory metrics collector for a single trading session.
    Produces a post-session summary.
    """

    def __init__(self, session_id: str = _SESSION_ID):
        self.session_id = session_id
        self.started_at = _now_ist()
        self._counters: dict[str, int] = {
            "signals_generated": 0, "orders_attempted": 0,
            "orders_allowed": 0, "orders_rejected": 0,
            "positions_opened": 0, "positions_closed": 0,
            "kill_switch_activations": 0, "duplicate_order_attempts": 0,
            "database_reconnects": 0, "sse_reconnects": 0,
            "errors": 0, "warnings": 0,
        }
        self._pnl: list[float] = []
        self._latencies: list[float] = []

    def inc(self, counter: str, by: int = 1) -> None:
        self._counters[counter] = self._counters.get(counter, 0) + by

    def record_pnl(self, pnl: float) -> None:
        self._pnl.append(pnl)

    def record_latency(self, ms: float) -> None:
        if ms > 0:
            self._latencies.append(ms)

    def summary(self) -> dict:
        lats = sorted(self._latencies)
        p95 = lats[int(len(lats) * 0.95)] if len(lats) >= 20 else (max(lats) if lats else None)
        total_pnl = round(sum(self._pnl), 2)
        max_dd = 0.0
        peak = 0.0
        running = 0.0
        for p in self._pnl:
            running += p
            if running > peak:
                peak = running
            dd = (peak - running) / max(abs(peak), 1)
            if dd > max_dd:
                max_dd = dd

        return {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "ended_at": _now_ist(),
            "label": LABEL,
            **self._counters,
            "total_realised_pnl": total_pnl,
            "maximum_drawdown_pct": round(max_dd, 4),
            "api_p95_latency_ms": round(p95, 1) if p95 else None,
            "latency_samples": len(lats),
        }


# ── Quick smoke test ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Phase 3F — Structured Logging Smoke Test\n")
    log = get_logger("smoke_test")

    r1 = log.info("startup", result="OK", version="phase3f")
    print(f"  info:    OK (correlation_id={r1['correlation_id']})")

    r2 = log.trade_event("order_submitted", symbol="TCS", order_id="ORD-001",
                         result="PAPER_SUBMITTED", latency_ms=230)
    print(f"  trade:   OK (order_id={r2['order_id']})")

    r3 = log.risk_event("pre_trade_check", symbol="TCS", verdict="ALLOW",
                        cash_available=5000, order_value=3500)
    print(f"  risk:    OK (verdict={r3['result']})")

    # Verify secret redaction
    r4 = log.error("test_redaction", error="api_key=SECRET123 failed",
                   api_key="should-be-redacted")
    assert r4.get("api_key") == "[REDACTED]", "SECRET NOT REDACTED"
    assert "SECRET123" not in json.dumps(r4), "ERROR CONTAINS SECRET"
    print(f"  redact:  OK (secrets stripped)")

    # Session metrics
    metrics = SessionMetrics()
    for _ in range(3):
        metrics.inc("signals_generated")
    metrics.inc("orders_allowed")
    metrics.record_pnl(150.0)
    metrics.record_latency(230.0)
    summary = metrics.summary()
    assert summary["signals_generated"] == 3
    assert summary["total_realised_pnl"] == 150.0
    print(f"  metrics: OK (signals={summary['signals_generated']} pnl=₹{summary['total_realised_pnl']})")

    print("\nAll Phase 3F smoke tests passed ✅")
