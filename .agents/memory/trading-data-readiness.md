---
name: Trading-data readiness contract
description: Fail-closed rules for deciding whether current market data is safe enough for any execution-grade path.
---

`trading_data_ready` must be independent of server and analytical-data readiness. It can be true only with complete active-universe instrument coverage, an authenticated valid provider session, a fresh parseable scan timestamp, and fresh parseable timestamps for every quote classified as provider-live.

**Why:** A fresh scan envelope or a healthy process can still contain stale, malformed, fallback, or token-incomplete prices. Treating those as trading-ready creates a false live-data assurance.

**How to apply:** Keep fallback and synthetic rows visibly classified but out of execution-grade readiness. Missing, malformed, future-dated, or stale timestamps and incomplete token coverage must fail closed while leaving service/data diagnostics informative.