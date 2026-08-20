# ApexQuant AI — Custom Low-Price IT/Infra/Bank Universe Report

## 1. Purpose
Paper-only intraday learning universe for lower-priced NSE EQ securities.

## 2. Active Universe Mode
`CUSTOM_LOW_PRICE_SECTOR`

## 3. Eligibility Price Band
₹20.00 to ₹200.00 inclusive.

## 4. Eligible Sector Buckets
IT, INFRA, BANK (provider aliases normalised).

## 5. NSE EQ Instrument Filter
Only NSE instruments marked as EQ are considered.

## 6. Liquidity Filters
≥500,000 average 20-day volume and ≥₹5 crore average 20-day turnover.

## 7. OHLCV Evidence Requirement
At least 120 cached daily bars are required.

## 8. Active Symbol Count
0

## 9. Sector Breakdown
- No active symbols

## 10. Inclusion Evidence
- No included symbols

## 11. Exclusion Evidence
- No excluded symbols

## 12. Data Sources and Coverage
- OHLCV cache hit rate: 0.0%
- Kite LTP status: FALLBACK_OR_UNAVAILABLE
- ASM/GSM ingestion: unavailable, skip.

## 13. Safety and Governance
- PAPER TRADING ONLY. No live broker order API is called.
- Existing per-stock, sector, portfolio, and daily-loss caps are unchanged.
- Historical backtests resolve verified symbols as-of the requested date to avoid look-ahead.

Last refresh: not yet refreshed
