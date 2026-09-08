# Task 947 — NSE Timestamp and Phase Contract

## Primary sources

1. [NSE India — Pre-open session](https://www.nseindia.com/static/products-services/equity-market-pre-open), consulted 2026-08-27.
2. [NSE India — Market timings](https://www.nseindia.com/static/market-data/market-timings), consulted 2026-08-27.

The pre-open session source establishes:

- the full session is 09:00–09:15 IST;
- order collection lasts eight minutes with system-driven random closure between
  the seventh and eighth minute;
- order matching starts immediately when collection completes;
- after matching, a silent transition precedes the normal market; and
- indicative equilibrium/opening price and buy/sell quantities are
  disseminated in real time during the pre-open session.

## Application timestamp rule

NSE `lastUpdateTime` is parsed as an Asia/Kolkata wall-clock timestamp:

| Input condition | Result |
| --- | --- |
| Known, non-future timestamp with age under 300 seconds | Live at ingestion. |
| Age exactly 300 seconds or greater | Stale. |
| Missing or malformed timestamp | Stale. |
| Future timestamp | Stale (fail closed). |

This remains the normal data-ingestion rule. It must not be widened based on
HTTP success, symbol count, or an older successful collection.

## Phase-aware certification interpretation

The parser rule answers whether data was live **when collected**. It does not
mean every exchange-side timestamp must continue changing while matching or
the silent transition is in progress. At 09:15, measuring elapsed time again
would wrongly reject a final auction observation that was live when the
application collected it.

The certificate contract is therefore:

1. collect only through 09:12 IST;
2. require a final candidate captured from 09:08:00 inclusive to 09:12:00
   exclusive;
3. retain the ordinary `age < 300` test for every row at that capture;
4. stop replacing the candidate during matching/transition; and
5. freeze that exact batch at 09:15 only if all durable parity and liveness
   evidence remains present.

No historical raw `lastUpdateTime` values exist for the failed 2026-08-27
batch, so this contract does not claim a finer root cause than the recorded
stale classification.