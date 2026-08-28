# Task 962 Kite Instrument Root Cause

## Primary root cause

Production starts each published instance with the committed
`kite_instruments_cache.json` file. That file is a one-row `RELIANCE` fixture
dated `2026-08-09`, not a complete durable Kite instrument master.

The current application has no startup or scheduled instrument-master refresh.
Its only refresh entry point is the authenticated operator POST:

`POST /api/kite/instruments/refresh`

Therefore a new production instance continues to expose the bundled one-row
file until an authenticated operator performs a successful refresh.

## Unsafe refresh behavior identified

The current refresh implementation:

1. Fetches `kite.instruments("NSE")`.
2. Accepts any returned list, including one row or an empty list.
3. Writes the result to a temporary file and uses `os.replace`.
4. Marks the cache with today's date without minimum-count, completeness,
   duplicate-token, or NSE cash/EQ sanity validation.
5. Keeps no durable sync audit, last-successful metadata, or failure record.

`os.replace` prevents a torn JSON write, but it does not prevent a complete
last-known-good cache from being atomically replaced by a validly encoded
partial provider response.

## Source and production evidence

- Committed cache date: `2026-08-09`
- Committed cache fetched at: `2026-08-09T09:32:09Z`
- Committed cache rows: `1`
- Committed symbol: `RELIANCE`
- Production cache path:
  `/home/runner/workspace/artifacts/api-server/src/python/kite_instruments_cache.json`
- Production cache date: `2026-08-09`
- Production cache rows: `1`
- Production cache fresh: `false`
- Earlier production evidence showed a successful operator refresh could fetch
  approximately `10,222` NSE rows, but that instance-local result was not
  preserved across later publication/startup.

## Why repair did not proceed

Task 962 requires valid live Kite authentication before provider retrieval or
cache mutation. Production authentication failed that gate, so no repair or
code change was attempted.
