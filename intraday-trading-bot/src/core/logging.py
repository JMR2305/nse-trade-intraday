"""Structured JSON logging with correlation IDs."""

import logging
import sys
from typing import Any, Dict
from datetime import datetime, timezone
from pythonjsonlogger import jsonlogger

from src.core.config import settings


class StructuredLogFormatter(jsonlogger.JsonFormatter):
    """JSON formatter with standard fields for observability."""

    def add_fields(
        self,
        log_record: Dict[str, Any],
        record: logging.LogRecord,
        message_dict: Dict[str, Any],
    ) -> None:
        super().add_fields(log_record, record, message_dict)
        log_record["timestamp"] = datetime.now(timezone.utc).isoformat()
        log_record["level"] = record.levelname
        log_record["logger"] = record.name
        log_record["service"] = settings.app_name
        log_record["environment"] = settings.app_env

        # Include trace/span IDs if available on the record
        if hasattr(record, "trace_id"):
            log_record["trace_id"] = record.trace_id
        if hasattr(record, "span_id"):
            log_record["span_id"] = record.span_id
        if hasattr(record, "session_id"):
            log_record["session_id"] = record.session_id
        if hasattr(record, "correlation_id"):
            log_record["correlation_id"] = record.correlation_id

        # Remove default fields that clutter JSON output
        for key in ("message", "asctime", "levelname", "name"):
            log_record.pop(key, None)


def get_logger(name: str) -> logging.Logger:
    """Get a configured logger instance."""
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, settings.logging.level.upper()))

    # Avoid duplicate handlers
    if logger.handlers:
        return logger

    handler = logging.StreamHandler(sys.stdout)
    formatter = StructuredLogFormatter(
        "%(timestamp)s %(level)s %(name)s %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # Prevent propagation to root logger to avoid duplicate output
    logger.propagate = False

    return logger


# Module-level logger
logger = get_logger("intraday_bot")
