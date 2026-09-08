---
name: Custom universe historical membership
description: How custom scanner universe membership is made safe for historical backtests.
---

Custom scanner universe refreshes must write an immutable membership snapshot in the same transaction as their mutable current-state master update. Historical replay resolves the latest snapshot observed on or before its as-of date, not a current active row filtered by a timestamp.

**Why:** Upserting current eligibility overwrites both active status and verification time. Querying it for old backtests introduces survivorship and look-ahead bias whenever a symbol enters or leaves the universe after the target date.

**How to apply:** Any new dynamic scanner universe should persist all included and excluded candidates per refresh, then have its backtest resolver select one complete snapshot. Missing history fails closed by default; any current-membership fallback requires explicit operator opt-in and must be recorded as degraded evidence.