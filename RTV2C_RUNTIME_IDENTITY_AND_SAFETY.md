# RTV-2C Runtime Identity and Safety

## Production identity verified

- URL: `https://nse-trade-intraday.replit.app`
- Environment: `production`
- Build ID: `apexquant-393747a8102e`
- Git commit: `393747a8102ee3fc8adaa36d60b6ed8db18bc4b8`
- Deployment ID: `0d018179-abe0-42c2-a554-dbb19d11341f`
- Health details endpoint: HTTP 200

RTV-2C did not publish a new release. The source repair is present in the
workspace and development API only until an approved publish occurs.

## Read-only production safety verification

| Check | Observed result |
| --- | --- |
| Active universe | `CUSTOM_LOW_PRICE_SECTOR` |
| Initial capital | ₹100,000 |
| Automatic paper entries | Disabled |
| Entry confirmation | Cleared / null |
| Bootstrap paper entries | Disabled |
| Automatic exits | Enabled |
| Open or exit-pending ledger rows | 0 |
| Portfolio cash | ₹100,000 |
| Portfolio positions | Empty |
| Closed ledger rows | 6 |
| Realised P&L | −₹278.74 |

The six closed rows span 2026-08-18 through 2026-08-20. No row was created
during RTV-2C and there are no later open, pending, or closed records.

## Development runtime verification

After the source repair, the managed API workflow was restarted successfully.
Its fresh log shows the service listening on port 8080, and
`/api/health/live` returned HTTP 200 with `status: ok`.

## Safety scope

The production database was queried read-only except for the supported settings
disable operation. No portfolio, ledger, universe, broker, token, capital,
threshold, scan, lifecycle, or execution state was modified.