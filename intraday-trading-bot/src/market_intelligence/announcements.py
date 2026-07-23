"""AnnouncementIntelligenceService — in-memory cache and classification engine
for corporate announcements.

The `poll_and_classify()` method is a stub in this implementation — full HTTP
polling against BSE/NSE feeds is deferred to operational deployment.

Classification is keyword-based, case-insensitive, with the following
priority order (first match wins):
  EARNINGS_RESULT, DIVIDEND, BONUS, STOCK_SPLIT, MERGER_ACQUISITION,
  BOARD_MEETING, REGULATORY, OTHER
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set, Tuple

from market_intelligence.multi_timeframe_context import AnnouncementRecord

logger = logging.getLogger(__name__)

# Classification keyword lookup (priority order — first match wins)
_CLASSIFICATION_RULES: List[Tuple[str, List[str]]] = [
    ("EARNINGS_RESULT", ["earnings", "result", "quarterly", "annual result", "financial result", "net profit"]),
    ("DIVIDEND", ["dividend"]),
    ("BONUS", ["bonus issue", "bonus share", "bonus"]),
    ("STOCK_SPLIT", ["stock split", "face value", "sub-division", "subdivision"]),
    ("MERGER_ACQUISITION", ["merger", "acquisition", "amalgamation", "takeover", "demerger"]),
    ("BOARD_MEETING", ["board meeting", "board of directors"]),
    ("REGULATORY", ["sebi", "regulatory", "compliance", "exchange notice", "nse notice", "bse notice"]),
]


def classify_announcement(headline: str, body_text: str = "") -> str:
    """Classify an announcement headline+body into one of 8 categories.

    Case-insensitive keyword match; first match in the rule list wins.
    Falls back to 'OTHER' when no keyword matches.
    """
    text = (headline + " " + body_text).lower()
    for classification, keywords in _CLASSIFICATION_RULES:
        if any(kw in text for kw in keywords):
            return classification
    return "OTHER"


class AnnouncementIntelligenceService:
    """Cache-first announcement service.

    Ingested records are held in an in-memory dict keyed by
    (exchange, announcement_id).  Records older than ttl_hours are
    pruned on `clear_expired()`.
    """

    def __init__(
        self,
        repository: Optional[object] = None,
        ttl_hours: int = 24,
    ) -> None:
        self._repository = repository
        self._ttl = timedelta(hours=ttl_hours)
        # _cache: (exchange, announcement_id) -> AnnouncementRecord
        self._cache: Dict[Tuple[str, str], AnnouncementRecord] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ingest_announcement(self, record: AnnouncementRecord) -> bool:
        """Add a record to the in-memory cache.

        Returns True if the record was new, False if it was a duplicate.
        Deduplication key: (exchange, announcement_id).
        """
        key = (record.exchange, record.announcement_id)
        if key in self._cache:
            return False
        self._cache[key] = record
        logger.debug(
            "Ingested announcement %s/%s: %s",
            record.exchange,
            record.announcement_id,
            record.classification,
        )
        return True

    def get_active_announcements_sync(
        self, instrument_token: str
    ) -> List[AnnouncementRecord]:
        """Return all non-expired announcements for this instrument.

        Never raises — returns empty list on any error.
        """
        try:
            now = datetime.utcnow()
            return [
                r
                for r in self._cache.values()
                if r.instrument_token == instrument_token
                and (now - r.published_at) < self._ttl
            ]
        except Exception as exc:
            logger.warning("get_active_announcements_sync error: %s", exc)
            return []

    def clear_expired(self) -> int:
        """Remove expired records from the cache.  Returns count removed."""
        now = datetime.utcnow()
        expired_keys = [
            k for k, r in self._cache.items() if (now - r.published_at) >= self._ttl
        ]
        for k in expired_keys:
            del self._cache[k]
        if expired_keys:
            logger.debug("Cleared %d expired announcements", len(expired_keys))
        return len(expired_keys)

    def is_blackout_period(
        self, instrument_token: str, window_minutes: int = 30
    ) -> bool:
        """Return True if there is an active announcement within the blackout window."""
        now = datetime.utcnow()
        window = timedelta(minutes=window_minutes)
        return any(
            r.instrument_token == instrument_token
            and (now - r.published_at) < window
            for r in self._cache.values()
        )

    async def poll_and_classify(self, session: Optional[object]) -> int:
        """Poll BSE/NSE announcement feeds and classify results.

        Stub implementation — returns 0 (no HTTP calls in unit tests).
        Full HTTP implementation requires operational API credentials.
        """
        return 0
