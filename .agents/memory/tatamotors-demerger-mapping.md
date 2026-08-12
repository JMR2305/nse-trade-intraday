---
name: TATAMOTORS demerger symbol mapping
description: TATAMOTORS.NS is dead post-demerger; TMPV + TMCV are the live NSE successors; what was changed and how to extend it.
---

## Rule
TATAMOTORS is deprecated. Never add it back to NIFTY_50, SECTOR_MAP, or any picker list. Use TMPV (Tata Motors PV, ~₹343) and TMCV (Tata Motors CV, ~₹457) instead.

**Why:** The Tata Motors 2024 demerger split the NSE equity into two instruments. yfinance raises `'exchangeTimezoneName'` for `TATAMOTORS.NS` — the exchange metadata no longer exists. Any price shown for TATAMOTORS was a stale historical close, not a live tradeable price.

**How to apply:**
- New symbols needing deprecation: add an entry to `_DEMERGED` in `live_quote_service.py` and to `DEPRECATED_SYMBOLS` in `symbol_validation.py`. The validate + quote flows pick it up automatically.
- NIFTY_50 is now 51 members (50 - 1 TATAMOTORS + 2 TMPV/TMCV). `MIN_SYMBOLS_EXPECTED = len(NIFTY_50)` is dynamic so scanner coverage tests adapt automatically — but any test that hardcodes `_meta(50)` for "full coverage" must become `_meta(MIN_SYMBOLS_EXPECTED)`.
- The scan-engine quality gate (`_apply_quality_gate` in `live_scan_engine.py`) already caps UNAVAILABLE → IGNORE. No strategy logic changes are ever needed for demerged symbols.
