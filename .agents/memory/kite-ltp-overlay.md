---
name: Kite LTP Overlay (Option A)
description: KITE_LTP_OVERLAY_ENABLED feature — overlays Kite live LTP on execution price only; all indicators remain yfinance_daily_bars forever.
---

## Rule
`kite_ltp_overlay.py` is the single module for the Option A overlay logic.
- `fetch_ltp_overlay(symbols)` — one bulk Kite quote call, 30s cached (by kite_quote_provider), always returns without raising.
- `build_symbol_overlay(symbol, yfinance_close, yfinance_data_quality, overlay_result)` — per-symbol dict of all new fields.
- `apply_overlay_to_rec(rec, overlay)` — mutates a Phase7Recommendation dataclass in-place.

## Option A invariants (enforced in kite_ltp_overlay.py, tested)
- `indicator_source = "yfinance_daily_bars"` — NEVER changes regardless of Kite state.
- `ohlcv_source = "yfinance_daily_bars"` — NEVER changes.
- `data_quality_for_indicators` = yfinance DataQuality — NEVER changes.
- `yfinance_last_close` = entry_price at scan time — always preserved.

## Where the overlay is applied
1. **live_scan_engine.py** — Phase 2B overlay loop runs AFTER `_scan_one()` for all symbols, BEFORE the safety/timings dict assembly. `recs` are mutated in-place. `timings["ltp_overlay_s"]` added. `safety` dict has `kite_ltp_overlay_enabled`, `kite_ltp_overlay_note`, `mode_label`.
2. **phase20_executor.py** `create_paper_entry()` — reads `kite_ltp_available` + `execution_price_source=="kite_live_ltp"` from candidate. Uses Kite LTP as signal_price when available. Evidence records `signal_price_from_daily_bar` and `execution_price_from_kite_ltp` separately.
3. **phase20_exits.py** `manage_open_positions()` — after baseline quote from `entry_price`, overlays `kite_ltp` when `kite_ltp_available` + `quote_reliable`. Same logic in `_retry_pending()` (dq forced to "LIVE" so eligibility check passes).

## Phase27Readiness integration (Task 8)
- `collect_inputs()` calls `_kite_ltp_overlay()` → stored as `inputs["kite_ltp_overlay"]`.
- `check_broker()` reads `inputs["kite_ltp_overlay"]["enabled"]` + `_market_open(inputs)`. When overlay enabled + market open + session unavailable → WARNING with explicit overlay-fallback text in remediation. Always non-blocking.

## New Phase7Recommendation fields (11 added)
`kite_ltp`, `kite_ltp_available`, `kite_session_verified_flag`, `kite_ltp_overlay_enabled`, `current_price_source`, `execution_price_source`, `quote_reliable`, `indicator_source`, `ohlcv_source`, `yfinance_last_close`, `data_quality_for_indicators`, `data_quality_for_execution`, `reason_not_live_ltp`, `latest_price_time_ist` — all Optional with defaults, so `_fail()` and positional construction is backward compatible.

**Why:** Paper exits were stuck as EXIT_PENDING forever because yfinance daily bars have `data_quality=ACCEPTABLE` which never satisfies the `LIVE/NEAR_LIVE` guard in `phase20_exits.py`. Kite LTP overlay sets `quote_reliable=True` and `data_quality_for_execution=LIVE` so the exit guard can pass.

**How to apply:** Set `KITE_LTP_OVERLAY_ENABLED=true` in environment. Requires a valid Kite session (`kite_session_verified()=True`). Falls back to yfinance daily close if Kite unavailable — no silent failures, no fabricated prices.
