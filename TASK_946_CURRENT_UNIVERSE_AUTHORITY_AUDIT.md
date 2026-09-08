# Task 946 — Current Universe Authority Audit

Audit date: 2026-08-26. Scope: `CUSTOM_LOW_PRICE_SECTOR`; read-only inspection
of the existing authority before adding the versioning foundation.

## Finding

The current custom membership authority is the PostgreSQL table
`custom_universe_master`, filtered by:

```sql
allowed_universe = 'CUSTOM_LOW_PRICE_SECTOR' AND is_active = TRUE
```

The audited development database contains 23 active rows and 2 excluded rows.
The exact active set is:

`BANKBARODA, BANKINDIA, CANBK, COALINDIA, FEDERALBNK, GAIL, HUDCO, IDFCFIRSTB,
IRCON, IRFC, KTKBANK, MAHABANK, MRPL, NBCC, NMDC, NTPC, PFC, PNB, RECLTD,
RVNL, SAIL, UNIONBANK, WIPRO`

The existing membership refresh writes the current master and the append-only
`custom_universe_membership_history` snapshot in one transaction. The new
versioning tables do not replace or rewrite either table.

## Selection precedence

1. Runtime callers ask `config.get_active_intraday_universe()`.
2. That function reads `phase20_settings.data.active_intraday_universe` when
   the durable settings row is readable.
3. On an exception, the compatibility fallback is
   `ACTIVE_INTRADAY_UNIVERSE`, initialized from `ACTIVE_INTRADAY_UNIVERSE` in
   the process environment.
4. A malformed environment value falls back to `NIFTY_50`.
5. Phase 20 `DEFAULT_SETTINGS` also validates the setting and defaults to
   `NIFTY_50`.
6. In custom mode, live scan, market scanner, pre-open, and coverage code read
   active rows from `custom_universe_master`; they do not read the new
   revision store.

At audit time the local Phase 20 setting reported `NIFTY_50`; this is a
selection setting and was not changed. The 23-row custom master remains the
approved custom baseline to be imported.

## Other paths and bypasses found

* `config.NIFTY_50` is a code-derived static index list and remains the
  fallback/default mode. It is not used to substitute for an empty custom
  master in custom-mode scan/coverage paths.
* `config.DEFAULT_WATCHLIST` and optional `watchlist.json` serve the legacy
  watchlist endpoints and Phase 4A reporting. They are not the custom
  low-price membership source.
* Explicit caller-provided symbol lists are supported by scanner/backtest
  APIs for controlled research and tests. They intentionally bypass automatic
  selection and are not active-universe authority.
* Readiness currently defaults to `config.NIFTY_50` when called without an
  explicit symbol list; this is a duplicate denominator path that must be
  retired when runtime consumers are migrated in a later task.
* Phase 4A labels a legacy watchlist source in its report. This is reporting
  provenance, not a custom universe resolver, but should be removed or clearly
  scoped during the later resolver migration.
* Fixed expectations of 23 occur in Task #930 certification evidence/tests.
  They are immutable certification assertions, not runtime membership
  sources, and were not modified.

## Planned retirement path

The new `trading_universes` revision and member tables are additive in this
task. A later runtime migration should make one session-pinned resolver the
source for live scan, pre-open, readiness, execution eligibility, reporting,
and historical evidence, then retain `custom_universe_master` only as a
compatibility/import source until parity is proven. The legacy watchlist and
NIFTY fallback remain available for their explicitly separate modes.

No runtime consumer, settings record, portfolio, capital, ledger, schedule,
execution flag, Task #930 evidence, or historical table was modified by this
task.