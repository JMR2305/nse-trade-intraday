---
name: Phase 5D multi-provider pre-open data
description: Multi-provider architecture for pre-open intelligence: NSE Official → Kite → Yahoo fallback chain
---

## Priority chain
NSE Official (primary) → Zerodha Kite (secondary) → Yahoo Finance (fallback only)

Managed by `preopen_provider_manager.get_best_provider()`. Provider cache TTL = 300s.

## Key files created
- `nse_preopen_provider.py` — NSEPreOpenProvider; two-request cookie dance (main page → NIFTY API)
- `kite_preopen_provider.py` — KitePreOpenProvider; uses KITE_ACCESS_TOKEN env var
- `preopen_provider_manager.py` — priority manager, `get_best_provider()` + `provider_chain_status()`
- `test_preopen_multi_provider.py` — 46 tests, all passing

## Key files modified
- `preopen_data_model.py` — added `provider_label: str` and `order_book_available: bool` to PreOpenSnapshot
- `preopen_provider.py` — YFinancePreOpenProvider gets PROVIDER_LABEL/PROVIDER_ID class attrs; order_book_available=False
- `preopen_engine.py` — `_get_provider()` uses manager (PREOPEN_PROVIDER=auto default); `get_snapshot()` returns provider_label
- `PreOpenIntelligence.tsx` — providerBadge() shows provider name; imbalance shows "—"/"Not supplied by provider" when !order_book_available

## NSE API notes
- Endpoint: `https://www.nseindia.com/api/market-data-pre-open?key=NIFTY`
- Requires two-request cookie dance (GET main page first, then API)
- IEP and buy/sell quantities are in `detail.preOpenMarket`, NOT in `metadata` (metadata.IEP is always null)
- Module-level session cache (270s TTL) and data cache (55s TTL) prevent rate-limiting
- Returns 200 from Replit environment (403 without cookie dance)

**Why:** `order_book_available=False` for Yahoo/Kite prevents displaying "0" as if it means balanced; "—" is shown instead. NSE provides the full auction order book including IEP, buy qty, sell qty, imbalance.

**How to apply:** When displaying buy/sell/imbalance from any snapshot, always check `order_book_available` before rendering values — `False` means the provider didn't supply auction data, not that quantities are zero.
