# RTV-1D — Runtime Identity and Safety

## Production identity observed

Endpoint: `https://nse-trade-intraday.replit.app/api/health/details`
Observed runtime timestamp: `2026-08-23T20:50:47.518Z`

| Field | Value | Assessment |
|---|---|---|
| environment | `production` | Present |
| git_commit | `unknown` | **FAIL — does not identify approved source** |
| build_id | `apexquant-v1.0.0` | **FAIL — not the approved candidate identity** |
| deployment_id | `0d018179-abe0-42c2-a554-dbb19d11341f` | Present |
| instance_id | `nse-trade-intraday.replit.app` | Present |
| runtime_timestamp | `2026-08-23T20:50:47.518Z` | Present |

Approved source commit:
`3ca36c4847c6309149aaf78a94da87b529034881`

The runtime identity mismatch is a hard stop. The existence of a deployment
ID does not compensate for the missing commit identity.

## Safety settings observed

The read-only `phase20/settings` response confirmed:

| Safety control | Production value | Result |
|---|---|---|
| Active universe | `CUSTOM_LOW_PRICE_SECTOR` | PASS |
| Initial capital | `100000` | PASS |
| Paper mode | enabled by paper settings | PASS |
| Automatic paper entries | `false` | PASS |
| Bootstrap paper trading | `false` | PASS |
| Automatic paper exits | `true` | PASS |
| Live broker order placement | not enabled by the configured paper-only path | PASS |
| Historical realized P&L | `-278.74` | PASS |
| Open positions | `0` | PASS |

No order endpoint was called. No trade, reset, universe refresh, threshold
change, strategy change, or safety-flag mutation was performed.

## Readiness safety interpretation

Production reported:

- `service_ready=true`
- `data_ready=true`
- `session_fresh=false`
- `trading_data_ready=false`
- `symbols_synthetic=0`

The distinction between service health and trading-data readiness is preserved.
The closed/stale market state is not itself a failure, and the false
`trading_data_ready` value is the safe result. However, the readiness response
was based on a 50-symbol legacy scan context with 2% token coverage, so it
cannot certify the required current 23-symbol universe.

## Final safety classification

Safety controls remained conservative and no trading action occurred.
Production verification nevertheless remains **FAILED** until the live
runtime reports the approved source commit and the stopped 23-symbol checks are
completed.