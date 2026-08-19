# ApexQuant AI — LTIM Removal and ₹100,000 Paper-Capital Migration Report

**Report date:** 19 August 2026  
**Scope:** PostgreSQL OHLCV cache migration, active-universe cleanup, paper-capital migration safety, dashboard controls, and production readiness  
**Trading mode:** Paper only. No live broker order API is called by this migration.

## 1. Executive result

The release code is implemented, tested, and ready to publish.

Production has **not** been changed by this work because its authoritative Phase 20 PostgreSQL ledger still contains an active paper position:

| Environment | LTIM active? | Active universe | Paper capital | Active paper rows | Auto entries | Capital migration |
|---|---:|---:|---:|---:|---:|---|
| Development after migration | No; retained inactive | 50 | ₹100,000 | 0 | Off | Applied and idempotency verified |
| Production snapshot at 2026-08-19 09:57 IST | Yes, pending publish/bootstrap | 51 | ₹500,000 | 1 OPEN | Off | **Not applied; must remain blocked** |

The active production row is:

- Trade: `P20-70dee2f8c0`
- Symbol: `GRASIM`
- Status: `OPEN`
- Quantity: `3`
- Fill price: `₹3,274.20`
- Trigger: `BOOTSTRAP_AUTO`

No production cash or capital rebase was attempted. The production deployment does not yet expose the new migration-status route (`404` before publish), which is additional proof that this release is not currently active there.

## 2. Safety rules enforced

The guarded migration enforces all of the following:

1. Phase 20 PostgreSQL ledger state is authoritative.
2. Any `OPEN` or `EXIT_PENDING` paper row blocks migration.
3. An unreadable ledger blocks migration; there is no JSON fallback.
4. Active rows are checked before idempotency, including when capital already equals ₹100,000.
5. The operator must supply this exact confirmation:

   > I confirm there are no open or exit-pending paper positions and approve rebasing paper capital to ₹100,000.

6. There is no force flag or bypass.
7. Generic Phase 20 settings updates cannot change `initial_capital`.
8. Generic Phase 11 capital configuration cannot change `starting_capital` or `topup_target`.
9. Rejection of guarded Phase 11 fields happens before any other configuration write, preventing partial updates.
10. A successful migration updates settings, legacy paper cash, and Phase 11 capital keys in one PostgreSQL transaction.
11. Closed trades and realized P&L are not rewritten.
12. Automatic entries remain paused after a successful migration and require a separate explicit re-enable action.
13. Migration and OPEN-entry admission serialize on one PostgreSQL advisory lock.
14. Every OPEN entry re-reads confirmed automatic-entry settings under that lock immediately before its ledger INSERT.
15. PostgreSQL entry-admission errors fail closed; OPEN entries cannot fall back to a JSON ledger.
16. Evidence is emitted only after the transaction commits.
17. The migration reports `broker_orders_called: false` and contains no broker-order path.

## 3. LTIM removal

LTIM was removed from the configured active NIFTY 50 universe without deleting history.

Development company-master result:

- Stored rows: `51`
- Active rows: `50`
- LTIM row retained: yes
- LTIM active: no
- Configured universe: `50` unique symbols
- `MIN_SYMBOLS_EXPECTED`: `50`

The company-master bootstrap now reconciles membership in both directions:

- Configured symbols are inserted/reactivated.
- Removed NIFTY 50 members are marked inactive.
- Historical company-master and OHLCV data remain available for audit.

Readiness, scanner coverage, cold-start checks, and post-market refresh now use the exact configured 50-symbol universe. There is no LTIM-specific exception or silent missing-symbol allowance.

## 4. OHLCV cache and scan verification

### Development after the change

- Cache source: local PostgreSQL-backed Yahoo Finance cache
- Symbols expected: `50`
- Live symbols: `50`
- Cache hit rate: `100%`
- Uncached symbols: none
- Stale symbols: none
- Missing required bars: none
- Company-master coverage: `100%`
- Latest scheduler scan: `50 requested / 50 received / 0 missing / 0 stale`
- Latest warm scan duration: approximately `4 seconds`
- Cold-start log: `cache warm, no backfill needed`

Data readiness was blocked only because the Zerodha/Kite session was not verified. The cache and company-master checks themselves passed. This is fail-safe: a missing verified quote session blocks paper BUY entries rather than substituting an unsafe execution price.

### Production before publish

The read-only production snapshot still reflects the old 51-symbol release:

- Symbols expected: `51`
- Live symbols: `50`
- Cache hit rate: `98%`
- Uncached symbols: `LTIM`
- Company-master active rows: `51`
- LTIM active: yes
- Most recent post-market/backfill result: `PARTIAL`
- Symbols updated: `50 / 51`
- Failed symbol: `LTIM`
- Duration: `1,015 seconds`

This production result is the exact stale condition this release fixes. It is not evidence of a failed new 50-symbol refresh because the new release has not been published.

The next post-close refresh after publish must be checked for:

- `symbols_requested: 50`
- no LTIM in failed or missing symbols
- all 50 symbols updated, or a truthful generic `PARTIAL`/`FAILED` result for any real provider issue

The refresh was not manually triggered during market hours.

## 5. Paper-capital migration verification

### Development blocked-state proof

Before migration, the development ledger had four `EXIT_PENDING` rows.

An actual guarded migration request returned:

- HTTP `409`
- Status: `BLOCKED_OPEN_POSITIONS`
- Open rows: `0`
- Exit-pending rows: `4`
- Capital remained: `₹50,000`
- Automatic entries after request: off
- Broker orders called: false

This proves EXIT_PENDING rows are treated as active and no cash rebase occurs while they exist.

### Development successful migration

After the authoritative ledger reported no `OPEN` or `EXIT_PENDING` rows, the migration was run with the exact confirmation.

Verified result:

- First request: HTTP `200`, evidence notification status `APPLIED`
- Second request: HTTP `200`, status `ALREADY_APPLIED`
- Phase 20 `initial_capital`: `₹100,000`
- Legacy paper cash: `₹100,000`
- Canonical portfolio initial capital: `₹100,000`
- Canonical portfolio cash: `₹100,000`
- Phase 11 starting capital: `₹100,000`
- Phase 11 top-up target: `₹100,000`
- Automatic paper entries: off
- Open positions: `0`
- Closed trade count preserved: `4`
- Realized P&L preserved: `₹0`
- Broker orders called: false

Derived amount limits after migration:

| Limit | Value |
|---|---:|
| Per-stock exposure cap (25%) | ₹25,000 |
| Sector exposure cap (40%) | ₹40,000 |
| Portfolio deployed cap (80%) | ₹80,000 |
| Risk per trade (1%) | ₹1,000 |
| Daily loss / circuit-breaker limit (3%) | ₹3,000 |
| Bootstrap maximum order value | ₹15,000 |

### Production decision

Production capital remains `₹500,000` because the GRASIM paper position is OPEN.

This is intentional. The migration must not be run successfully until every production `OPEN` and `EXIT_PENDING` row has been resolved and the PostgreSQL ledger can be read successfully.

Production automatic entries are already paused.

## 6. Dashboard behavior

The AI Paper Trader page now:

- Reads the actual nested Phase 20 settings envelope.
- Uses the migration-status endpoint as the authority.
- Never assumes ₹100,000 when settings/status are missing.
- Shows `BLOCKED_STATE_UNREADABLE` explicitly.
- Lists active blocking positions and counts.
- Requires the exact confirmation text.
- Explains that closed history and realized P&L are preserved.
- States that the operation is paper-only and calls no live broker orders.
- Refreshes settings, migration status, session status, and portfolio data after any migration attempt, including a blocked attempt that pauses automatic entries.
- Displays `₹100K ✓` and “Guarded baseline applied” only for `APPLIED` or `ALREADY_APPLIED`.

Browser end-to-end verification passed at a 1440×1000 viewport:

- Page rendered successfully.
- Daily Capital displayed `₹100K ✓`.
- Migration control was disabled after application.
- Auto Entries displayed `OFF`.
- No migration settings/status request failed.
- No browser console error was observed.

Screenshot evidence is stored at:

`screenshots/ai-paper-trader-capital-migration.jpg`

## 7. Validation evidence

Final validation completed:

- Focused backend regression suite: **182 passed**
- Two-connection PostgreSQL race test: passed; a pre-approved entry waited behind migration, observed the pause, and inserted no OPEN row
- PostgreSQL-unavailable entry test: passed; no JSON ledger fallback occurred
- Shared libraries + API server TypeScript build: passed
- Trading dashboard TypeScript check: passed
- Trading mobile TypeScript check: passed
- Changed Python modules compiled successfully
- Git diff whitespace validation: passed
- API server workflow: running cleanly
- Trading dashboard workflow: running cleanly
- Browser end-to-end test: passed
- Independent architecture/safety review: **PASS**
- Workspace publish-image check: `4.2 GiB`, below the `8 GiB` limit

An expanded 630-test backend run produced 623 passes and seven existing state-dependent failures in unrelated Phase 20 timeout-exit and Phase 11 closed-position tests. None of the changed migration, OHLCV, universe, capital-config, or portfolio-config tests failed. The focused final suite and browser/API runtime checks passed after the review fixes.

## 8. Required production sequence

1. Publish this release.
2. Run or allow the company-master bootstrap and verify:
   - 51 stored historical rows
   - 50 active rows
   - LTIM inactive
3. Recheck the production migration-status endpoint.
4. Do not migrate while GRASIM or any other row is `OPEN` or `EXIT_PENDING`.
5. After all active rows are resolved, submit the exact confirmation through the guarded UI/API.
6. Verify:
   - status `APPLIED`
   - Phase 20 capital `₹100,000`
   - paper cash `₹100,000`
   - Phase 11 starting capital/top-up target `₹100,000`
   - automatic entries still off
   - closed history and realized P&L unchanged
7. Submit the same request once more and verify `ALREADY_APPLIED`.
8. After market close, run/observe the post-market refresh and verify exactly 50 symbols with no LTIM.
9. Run a fresh scan and verify 50/50 coverage and warm-cache timing.

## 9. Final sign-off

**Code status:** Ready to publish.  
**Development migration:** Complete.  
**Production LTIM deactivation:** Pending publish/bootstrap.  
**Production capital migration:** Blocked and intentionally unapplied because GRASIM is OPEN.  
**Live-order risk:** None introduced; migration is paper-only.