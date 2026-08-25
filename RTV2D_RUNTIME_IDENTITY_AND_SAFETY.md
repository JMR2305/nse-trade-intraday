# RTV-2D — Runtime Identity and Safety

**Date:** 2026-08-25 (IST)  
**Scope:** Production, read-only verification

## Runtime identity

| Check | Result |
| --- | --- |
| Environment | `production` |
| Git commit | `2e54e5e2f23f8ac5df86c9ec97aceeb3c8426832` |
| Build ID | `apexquant-2e54e5e2f23f` |
| Deployment ID | Present |
| Runtime identity | Matches the deployed safety repair |

## Automatic-entry authority

- PostgreSQL `phase20_settings` is authoritative; JSON is a release default and
  warm cache only.
- Production durable state is `auto_paper_entries=false`,
  confirmation absent, `bootstrap_paper_enabled=false`, and
  `auto_paper_exits=true`.
- Daily initialization preserves the entry state; it does not enable entries.
- The scheduler observes the existing state; it does not activate entries.
- The executor re-checks durable state immediately before an entry commit.
- Phase 22 typed confirmation is the sole activation path.
- Missing, unavailable, unreadable, or malformed durable settings block entries
  rather than falling back to enabled behavior.

## Production safety posture

| Check | Result |
| --- | --- |
| Execution mode | Paper trading |
| Live order placement | Disabled |
| Active universe | `CUSTOM_LOW_PRICE_SECTOR` |
| Active universe count | 23 |
| Kite mappings | 23 / 23 |
| Closed ledger rows | 6 |
| Open rows | 0 |
| `EXIT_PENDING` rows | 0 |
| Automatic entry currently allowed | No |

## Production activation history

Automatic entries were historically active before the repair:

- earliest surviving evidence: a `BOOTSTRAP_AUTO` paper entry on 2026-08-18;
- latest surviving entry: a `BOOTSTRAP_AUTO` paper entry on 2026-08-20;
- associated historical ledger activity is the six closed rows reconciled in
  `RTV2D_PORTFOLIO_RECONCILIATION.md`.

The current production durable settings were explicitly disabled on
2026-08-24. No row was created after the last historical entry, and no
post-repair paper entry was detected.

## Kite and broker check

A read-only forced Kite status probe verified:

- credentials are configured;
- the stored token is valid, not expired, and authenticated;
- the connection is live;
- no manual login is currently required;
- the broker status remains paper-trading/read-only for live orders.

No credentials were created, changed, or exposed. No broker order was placed.
