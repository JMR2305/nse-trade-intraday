# RTV-2C Automatic-Entry Root Cause

## Finding

RTV-2C found automatic paper entry activation in two places:

1. The tracked `phase20_settings.json` release settings contained
   `auto_paper_entries: true` and a non-null confirmation timestamp.
2. The daily session initializer independently wrote automatic entries on during
   normal daily initialization.

The source settings change is provably present in commit
`00daa873e1c3b251426ab34995130ca9e7063721`, authored at
2026-08-24T03:53:42Z. The confirmation timestamp in that file is
2026-08-24T03:33:38Z, which predates the commit. Git therefore proves that the
commit carried the unsafe state, but does not prove which earlier writer or
process first created it. The database row also did not retain an actor or
request audit record sufficient to attribute its original writer.

## Corrective action

- Restored the checked-in automatic-entry defaults to `false` and `null`.
- Made durable settings unavailable, unreadable, or malformed resolve to
  automatic entries disabled; a local JSON cache cannot authorize entries.
- Changed daily session initialization to preserve, rather than enable,
  automatic-entry state.
- Routed the legacy daily-session activation command through the existing
  Phase 22 readiness-and-typed-confirmation activation process.
- Disabled the currently active production setting using
  `PUT /api/phase20/settings` with only
  `{"auto_paper_entries": false}`.

## What was not changed

No scan, lifecycle job, manual entry, bootstrap action, broker order, portfolio
state, capital, universe, threshold, or ledger record was changed by RTV-2C.
Automatic exits remain enabled.

## Production evidence after remediation

- Automatic entries: `false`
- Automatic-entry confirmation: `null`
- Bootstrap: `false`
- Automatic exits: `true`
- Capital: ₹100,000
- Open or exit-pending trades: `0`
- Historical ledger: 6 `CLOSED` rows, realised P&L −₹278.74

The latest historical trade is dated 2026-08-20, before the RTV-2C repair.
No new row was created during the procedure.

## Remaining audit limitation

The exact original author/process of the unsafe setting remains indeterminate
without a durable setting-change audit trail. Future activation must use the
Phase 22 controlled path, which records its activation evidence after
readiness and acknowledgement.