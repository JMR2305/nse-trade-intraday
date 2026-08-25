---
name: Observability provenance
description: Rules for truthful Mission Control price and manual-scan audit provenance.
---

Mission Control must present current-quote provider/timestamp/freshness separately from the historical OHLCV provider and scan provenance. A closed-market `MARKET CLOSED / LAST KNOWN` state requires a recorded row-level quote timestamp; a scan completion time is never quote-time evidence. The price-provenance block remains visible even when the custom universe is inactive; absent evidence is displayed as `UNAVAILABLE / NOT PROVEN`, not `UNKNOWN` or a fabricated live source.

**Why:** Operator-facing market data can be last-known after close, can use a different historical provider, and can be unavailable while the custom-universe mapping review remains visible. Combining those states leads to false claims about current Kite prices or hides known limitations.

**How to apply:** Derive current quote time from recorded quote rows only, and historical OHLCV provider from recorded OHLCV/indicator fields only—not from scan freshness or the spot-quote service. Preserve existing readiness and execution predicates. New manual scan audit records must carry only allowlisted server-shaped IDs; legacy rows are rendered with explicit unavailable/unknown audit fields and are never backfilled.