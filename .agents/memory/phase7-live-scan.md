---
name: Phase 7 live scan design
description: Architecture decisions for canonical scan_id/snapshot_ts, quick health probe, and cache strategy
---
The canonical scan (live_scan_engine.run_live_scan) generates one scan_id (uuid hex[:12]) and one snapshot_ts at the start. ALL 50 symbols are fetched BEFORE any analysis begins — enforced by design (batch fetch first, then analyse loop).

Health endpoint (phase7_health / GET /api/live-data/health) probes only 3 symbols (RELIANCE, INFY, TCS) for speed (~3s). It also reads the disk cache to return last full-scan summary if available.

Full scan is cached to phase7_scan_cache.json in the Python dir. Cache TTL in TS routes: 10 min (P7_CACHE_MS).

**Why:** First-time health check must not block UI for 30s. Full scan is expensive (50 yfinance calls). Separation allows the page to load quickly and trigger full scan on demand.

**How to apply:** Never call get_or_run_scan() from the health CLI command. Use fetch_symbol() on 2-4 probe symbols only.
