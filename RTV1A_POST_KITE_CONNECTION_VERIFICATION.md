# RTV-1A — Post-Kite Connection Verification

**Verification type:** Read-only runtime inspection  
**Checked:** 2026-08-23, approximately 19:25 IST (NSE weekend / closed)  
**Safety actions taken:** No trades, broker orders, order simulation, setting changes, universe changes, portfolio resets, code changes, or deployment.

## Final verdict

### C. KITE LOGIN EXISTS BUT RUNTIME NOT USING SESSION

The verification note reported a recent successful Kite connection, but the currently running ApexQuant API cannot load an authenticated Kite session. Its session status is `LOGIN_REQUIRED`, the access token is absent, and the runtime is correctly using explicit fallback data rather than treating it as Kite-live.

| Required result | Runtime result |
|---|---|
| Kite authenticated | **NO** |
| Token coverage | **1 / 50** |
| Coverage percentage | **2%** |
| Symbols using Kite | **0** |
| Symbols using fallback | **50** |
| Synthetic active symbols | **0** |
| Portfolio parity | **PASS** |
| Safety flags unchanged | **PASS** |

## 1. Kite session status

| Field | Observed value |
|---|---|
| `credentials_present` | `false` |
| `token_status` | `MISSING` |
| `connected` | `false` |
| `authenticated` | `false` — inferred from the missing token and `LOGIN_REQUIRED` state |
| `login_required` | `true` |
| Access-token/session age | unavailable |
| Session creation time | unavailable |
| Last successful real Kite API call | unavailable |
| Last successful real Kite quote call | unavailable |
| Session storage | `token_stored=false` |
| Runtime state | `LOGIN_REQUIRED` |

The API process is running and spawns Python command subprocesses for Kite status/quote requests. There is no authenticated, durable Kite token available to those subprocesses. The diagnostics endpoint’s separate **mock broker** health record is paper-mode test infrastructure; it is not evidence of a real Kite authentication.

### Failure trace

1. **Replit static credentials:** the provider key/secret configuration is present, but this is not a logged-in access token.
2. **Node API runtime:** `/api/kite/status` successfully invokes the Python status command.
3. **Python subprocess/token store:** no stored token is found (`token_stored=false`).
4. **Kite client:** cannot initialize an authenticated quote session.
5. **Status/quote endpoints:** correctly return `LOGIN_REQUIRED` and fallback classification.

No secret values, tokens, login URLs, callback parameters, or cookies are included in this report.

## 2. Instrument cache hydration

| Field | Observed value |
|---|---|
| Active universe | `NIFTY_50` |
| Active symbol count | 50 |
| Cache date | 2026-08-09 |
| Cache fetched timestamp | 2026-08-09T09:32:09Z |
| Cache record count | 1 |
| Cache fresh today | `false` |
| Valid active-universe tokens | 1 |
| Missing active-universe tokens | 49 |
| Token coverage | 2% |
| Hydrated after the reported login | **No evidence** |
| Hydration mode | Neither automatic nor manual hydration occurred in this runtime |

The cache predates the reported connection and contains only the RELIANCE mapping. Root cause for every missing active symbol is the same: the active runtime has not received a successful authenticated Kite instrument-cache refresh. There is no evidence that renamed symbols, duplicate aliases, or inactive instruments caused distinct per-symbol failures; those cannot be evaluated until the real cache is hydrated.

### Missing symbols (49)

`ADANIENT`, `ADANIPORTS`, `APOLLOHOSP`, `ASIANPAINT`, `AXISBANK`, `BAJAJ-AUTO`, `BAJAJFINSV`, `BAJFINANCE`, `BHARTIARTL`, `BRITANNIA`, `CIPLA`, `COALINDIA`, `DIVISLAB`, `DRREDDY`, `EICHERMOT`, `GRASIM`, `HCLTECH`, `HDFCBANK`, `HDFCLIFE`, `HEROMOTOCO`, `HINDALCO`, `HINDUNILVR`, `ICICIBANK`, `INDUSINDBK`, `INFY`, `ITC`, `JSWSTEEL`, `KOTAKBANK`, `LT`, `M&M`, `MARUTI`, `NESTLEIND`, `NTPC`, `ONGC`, `POWERGRID`, `SBILIFE`, `SBIN`, `SHRIRAMFIN`, `SUNPHARMA`, `TATACONSUM`, `TATASTEEL`, `TCS`, `TECHM`, `TITAN`, `TMCV`, `TMPV`, `TRENT`, `ULTRACEMCO`, `WIPRO`

## 3. Token-to-symbol mapping validation

Every active symbol was checked against the local Kite instrument cache.

| Mapping group | Exchange | Token mapping result | Duplicate tokens |
|---|---|---|---|
| `RELIANCE` | NSE | valid; token present | none |
| The 49 symbols listed above | NSE | missing token; no cached `tradingsymbol` row | none |

There are no duplicate tokens in the available cache. Because only one historical cache row exists, this is **not** proof that the full production mapping is clean; it only proves no duplicate exists in the incomplete cache.

## 4. Live quote provenance

The market is closed. The latest canonical scan is from 2026-08-21 09:55:44Z and is not fresh for the current session.

| Provenance check | Observed value |
|---|---|
| Current real Kite quote timestamp | none |
| Current quote age | unavailable |
| Provider shown by health endpoint | Yahoo Finance / yfinance |
| Cached scan source | `local_yfinance_cache` / `yfinance_daily_bars` |
| Kite LTP in cached scan | unavailable |
| Kite session verified flag | `false` |
| Quote reliable flag | `false` |
| Symbols classified on Kite | 0 |
| Symbols classified fallback | 50 |
| Synthetic symbols | 0 |
| Current trading data ready | `false` |

The old scan’s analytical `LIVE` labels describe historical-data quality at scan time. They do **not** mean current live LTP: the scan explicitly records `quote_reliable=false`, no Kite LTP, no current quote timestamp, and an unverified Kite session. RTV-1’s current readiness contract correctly treats the cached scan as stale/off-hours.

## 5. Read-only Kite quote sample

The allowed read-only quote request was made for RELIANCE, TCS, INFY, HDFCBANK, and ICICIBANK. It did not call an order endpoint.

| Symbol | Cache token present | Kite quote success | Returned LTP | Runtime source | Result |
|---|---:|---:|---:|---|---|
| RELIANCE | yes | no | unavailable | `yfinance_fallback` | no authenticated Kite session |
| TCS | no | no | unavailable | `yfinance_fallback` | no authenticated Kite session |
| INFY | no | no | unavailable | `yfinance_fallback` | no authenticated Kite session |
| HDFCBANK | no | no | unavailable | `yfinance_fallback` | no authenticated Kite session |
| ICICIBANK | no | no | unavailable | `yfinance_fallback` | no authenticated Kite session |

The request returned a provider-level fallback response for all five symbols and no LTP value. It reported the missing access-token/session prerequisite without exposing it. An all-50 Kite quote request was not attempted because the safe sample already proved that no authenticated Kite client is available.

## 6. Market-data health

| Field | Observed value |
|---|---|
| `active_universe_count` | 50 |
| `kite_connected` | `false` |
| `authenticated` | `false` |
| `valid_instrument_tokens` | 1 |
| `missing_instrument_tokens` | 49 |
| `token_coverage_pct` | 2% |
| `symbols_on_kite` | 0 |
| `symbols_on_fallback` | 50 |
| `symbols_stale` | 0 in the original scan summary; current scan timestamp is stale/off-hours |
| `symbols_unavailable` | 0 |
| `symbols_synthetic` | 0 |
| `latest_quote_timestamp` | unavailable |
| `quote_age_seconds` | unavailable |
| `service_ready` | `true` |
| `data_ready` | `true` for cached analytical data |
| `session_fresh` | `false` |
| `trading_data_ready` | `false` |

The fail-closed result is correct for a weekend: it must not be changed merely to obtain a green status off-hours.

## 7. Synthetic and fallback safety

| Safety assertion | Result |
|---|---|
| Synthetic data blocked from execution-grade use | **PASS** — 0 synthetic active symbols |
| yfinance fallback explicitly identified | **PASS** |
| Cached/off-hours values kept out of current trading readiness | **PASS** |
| Fallback mislabeled as Kite-live | **No violation observed** |
| Synthetic symbol can pass paper-entry readiness | **No violation observed** |

No P0 fallback/provenance violation was found. The runtime’s data-quality and `quote_reliable` fields must continue to be interpreted together; only the strict readiness contract is eligible to describe current trading readiness.

## 8. Canonical portfolio safety

Kite login status did not alter portfolio truth.

| Metric | `/api/portfolio` | `/api/portfolio/snapshot` | Result |
|---|---:|---:|---|
| Source | `phase20_ledger` | `phase20_ledger` | PASS |
| Initial capital | ₹100,000 | ₹100,000 | PASS |
| Cash | ₹100,000 | ₹100,000 | PASS |
| Invested amount | ₹0 | ₹0 | PASS |
| Open positions | 0 | 0 | PASS |
| Realized P&L | ₹0 | ₹0 | PASS |
| Unrealized P&L | ₹0 | ₹0 | PASS |
| Total equity | ₹100,000 | ₹100,000 | PASS |

## 9. Safety flags

| Control | Observed value | Result |
|---|---|---|
| Paper trading mode | enabled / paper-only | PASS |
| Automatic paper entries | disabled | PASS |
| Bootstrap paper trading | disabled | PASS |
| Automatic paper exits | enabled | PASS |
| Live broker order placement | disabled | PASS |
| Active universe | `NIFTY_50` / 50 symbols | PASS |

## Required manual next step

No code change is justified by this verification. The necessary action is to complete the Kite login flow against the running API’s configured callback and confirm that the resulting session token is persisted where the Python runtime can read it. Do not add or change secrets automatically.

After that manual action, repeat this same read-only verification and require:

1. `token_status=VALID`, `connected=true`, and `authenticated=true`;
2. 50 valid active-universe mappings with no duplicates;
3. successful read-only Kite LTP results with Kite provenance;
4. fresh scan/quote timestamps during an NSE session; and
5. the same ₹100,000 canonical portfolio and unchanged safety flags.