# RTV-1H Next Open-Session Gate

## Purpose

RTV‑1H completed metadata hydration and read-only quote-plumbing verification
only. This gate covers the remaining **live-session** checks at the next NSE
session. It does not authorize a universe change, portfolio reset, historical
ledger change, automatic paper entry, bootstrap, live order, or manual scan.

Automatic paper entries must remain **disabled** throughout this gate.

## Pre-open checks

Before the open:

1. Reconfirm production identity:
   - environment = `production`
   - approved commit and matching commit-derived build ID
2. Confirm Kite authentication:
   - token status `VALID`
   - token stored
   - connected/authenticated
   - login not required
3. Confirm the current universe:
   - `CUSTOM_LOW_PRICE_SECTOR`
   - 23 active rows
   - BANK 9 / INFRA 13 / IT 1
   - WIPRO remains IT
4. Confirm 23/23 unique NSE mappings:
   - token present
   - exchange `NSE`
   - tradingsymbol matches active symbol
   - no duplicate tokens
5. Recheck portfolio parity:
   - capital ₹100,000
   - cash/equity ₹99,721.26 before any new paper activity
   - realized P&L ₹-278.74
   - zero open positions
6. Verify the 5A provider/persistence parity.
7. Verify the 5B lifecycle.
8. Verify the 5C lifecycle.

## Open-session checks

Only after the market is open:

1. Observe the first canonical scan using exactly 23 symbols.
2. Confirm the scheduler uses `CUSTOM_LOW_PRICE_SECTOR`.
3. Confirm no duplicate legacy 50-symbol scheduled scan runs.
4. Confirm fresh Kite provenance for all 23 active symbols.
5. Confirm current quote timestamps and valid live-price timestamps.
6. Confirm `session_fresh=true` only when the evidence justifies it.
7. Confirm `trading_data_ready=true` only after every readiness gate passes:
   - service ready;
   - data ready;
   - current scan covers the 23-symbol universe;
   - 23/23 valid tokens;
   - 23/23 Kite execution-grade quotes;
   - zero stale, unavailable, fallback-as-live, or synthetic execution data;
   - fresh market and session timestamps.

## Guardrails

- Do not manually trigger a market scan or pre-open lifecycle.
- Do not change the universe, ranks, sectors, thresholds, capital, or ledger.
- Do not enable automatic paper entries or bootstrap.
- Do not call any broker order API.
- If a condition fails, keep `trading_data_ready=false`, record the exact
  reason, and stop rather than fabricating readiness.