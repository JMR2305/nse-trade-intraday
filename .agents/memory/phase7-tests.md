---
name: Phase 7 test pattern
description: How test_phase7.py is structured and what it covers
---
test_phase7.py has 71 test assertions, all passing. Run: python3 test_phase7.py
Tests are pure unit tests (no real yfinance calls). They use:
- SymbolFetchResult constructed directly with synthetic data
- LiveDataProvider.build_health_report() called with synthetic results
- Gate functions imported directly (_apply_quality_gate, _price_gate, etc.)
- phase7_report._build_tables() and generate_report() with a minimal synthetic scan dict

Covers: data quality taxonomy, all 4 safety gates, partial failure, outage, duplicate scan_id detection, stale BUY detection, zero price, missing volume, meta-learning isolation, report table completeness, verdict logic.

**Why:** Full end-to-end scan test would hit yfinance and be slow/flaky. Unit tests are sufficient and deterministic.
