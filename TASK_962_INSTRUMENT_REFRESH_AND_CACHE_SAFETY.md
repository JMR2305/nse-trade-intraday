# Task 962 Instrument Refresh and Cache Safety

## Status

`NOT EXECUTED — BLOCKED BY KITE AUTHENTICATION`

## Required live authentication result

Observed at `2026-08-28T04:53:21Z`:

- Provider: `Zerodha Kite Connect`
- Credentials present: `false`
- Token status: `MISSING`
- Token stored: `false`
- Token expired: `true`
- Daily login required: `true`
- Connected: `false`
- Connection state: `LOGIN_REQUIRED`
- Mock mode: `true`
- Probe source: `no_credentials`
- Live broker order placement: `false`
- Last recorded success: `2026-08-27T18:31:05Z`

## Refresh accounting

- Provider instrument fetch attempted: `no`
- Instrument refresh POST sent: `no`
- Active cache replaced: `no`
- Custom universe metadata hydrated: `no`
- Migration attempted: `no`

## Required recurrence fix not yet applied

After authentication is restored, the implementation still needs:

- Complete-fetch validation before promotion
- Realistic minimum NSE row threshold
- NSE cash/EQ subset validation
- Duplicate token and duplicate symbol rejection
- Last-known-good preservation
- Atomic promotion only after validation
- Provider retrieval timestamp and row-count metadata
- Durable sync status, failure reason, and audit evidence
- Concurrency serialization compatible with Task 938

These changes were not made because Task 962 explicitly requires stopping when
Kite authentication is invalid.
