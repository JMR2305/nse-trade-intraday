---
name: Batch 10A Market Intelligence Layer
description: Design decisions and quirks from the RC-10A market intelligence implementation
---

## Key decisions

### Optional injection pattern (ContextBuilder)
All intelligence services (`indicator_engine`, `regime_detector`, `announcement_service`, `watchlist_ranker`) are keyword-only `None`-default args on `ContextBuilder.__init__`. When all are `None` the behaviour is identical to RC-9. A new sync `build()` method was added for tests and future sync callers; the existing async `build_context()` is UNCHANGED.

**Why:** Zero risk of breaking the live trading loop; intelligence is a side-car, not a replacement.

### CompletedBar.timestamp is a datetime, not a string
Even though callers pass ISO strings, Pydantic coerces them to `datetime` on construction. Any code that calls `datetime.fromisoformat(bar.timestamp)` will crash with `TypeError: argument must be str`.

**How to apply:** Always guard with `isinstance(ts, datetime)` before calling `fromisoformat` — see `_parse_ts()` in `timeframe.py`.

### Count-based timeframe aggregation with gap/session-boundary detection
`TimeframeAggregator` emits after exactly N source bars (5/15/60). A day-change triggers an early emit + reset; so does a gap where inter-bar time > 2× the target interval in minutes.

**Why:** Intraday bars can be sparse near open/close; silent accumulation across session boundaries would produce garbage OHLCV values.

### Keyword classifier for announcement classification
`classify_announcement()` is a deterministic keyword-lookup table (case-insensitive). It returns one of: EARNINGS_RESULT, DIVIDEND, BONUS, STOCK_SPLIT, MERGER_ACQUISITION, BOARD_MEETING, REGULATORY, OTHER.

**Why:** Zero latency, fully testable, no external dependency; can be upgraded to LLM later without changing the interface.

### AnnouncementIntelligenceService dedup key
Dedup is by `(exchange, announcement_id)` — not just `announcement_id`. The same numeric ID can appear on both NSE and BSE for different filings.

### TTL for announcement cache
`ttl_hours` controls expiry. `clear_expired()` must be called explicitly (or on `get_active_announcements_sync` — implementation decides). With `ttl_hours=0` every record expires immediately (including ones published "now"), so tests that need a "fresh" record should use `ttl_hours >= 1`.
