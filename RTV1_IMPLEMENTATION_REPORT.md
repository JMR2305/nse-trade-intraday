# RTV-1 Implementation Report — Market Data + Portfolio Truth

## Scope and baseline

- **Starting branch:** `phase4a-controlled-paper-entry-framework-disabled`
- **Starting commit:** `cf87d0ed6ced7520ec0cbaf93508d1f6ceca96fb`
- **Ending branch:** `rtv1-market-data-portfolio-truth`
- **Ending commit:** branch `HEAD` after the final RTV-1 commit
- **Scope:** confirmed market-data, portfolio-truth, pre-open lifecycle, and safe admission defects only.

Safety state was preserved throughout:

| Control | Before | After |
|---|---:|---:|
| Initial paper capital | ₹100,000 | ₹100,000 |
| Automatic paper entries | disabled | disabled |
| Bootstrap paper trading | disabled | disabled |
| Automatic paper exits | enabled | enabled |
| Live broker order placement | disabled | disabled |
| Active universe | NIFTY 50 (50 symbols) | unchanged |

No manual trades, portfolio resets, broker order APIs, production database writes, deployment, strategy changes, threshold changes, or universe changes were made.

## Confirmed issues addressed

| RTV-0 issue | Root cause | RTV-1 correction |
|---|---|---|
| Fallback quote could appear as live Kite data | LTP helper discarded provider provenance; overlay trusted any positive price | Preserve per-symbol source/reason; only verified `kite_live` quotes receive execution-grade Kite labels. |
| Market readiness could be overclaimed | Service, scan, token, and per-quote freshness were not one fail-closed contract | Added cached, read-only readiness contract with separate service/data/session/trading states. Trading readiness requires authenticated Kite metadata, complete token coverage, a fresh scan timestamp, and valid fresh timestamps for every Kite-live quote. |
| Missing instrument tokens were silent | Existing cache had no full-universe coverage summary | Expose valid/missing coverage and the exact missing-symbol list; 100% coverage is required for trading readiness. |
| Disconnect could leave hydrated credentials usable | Store removal did not clear process-local hydrated values/caches | Disconnect now clears store-hydrated values and invalidates quote/session verification caches without mutating static secrets. |
| `/portfolio/snapshot` disagreed with canonical portfolio | Service/legacy peak history could be mixed with another equity basis | Portfolio snapshot is now canonical Phase-20-ledger first; it no longer reads the separate service snapshot for operator financial truth and does not mix legacy peaks. |
| Legacy portfolio API used different field names | Canonical values were returned only through historical aliases | `/portfolio` now exposes the unified canonical financial aliases alongside compatibility fields. |
| Capital authority was split | Active bridge/performance code imported static capital defaults | Active bridge and performance calculations call the Phase-20 configured-capital accessor. |
| EXIT_PENDING position could admit another BUY for same symbol | Persistence uniqueness applied only to `OPEN` | Locked admission explicitly treats `OPEN` and `EXIT_PENDING` as active before insertion. |
| Pre-open counts became zero after lifecycle writes | Partial upserts wrote omitted fields as defaults | Phase 5A/5B upserts preserve omitted fields; 5A emits collection-versus-persistence mismatch status. |
| Pre-open statuses could regress | Collection/checkpoint writes could overwrite frozen or terminal statuses | DB-boundary guards keep 5A/5B lifecycle transitions forward-only. |
| 5B/5C EOD status could overclaim completion | No-candidate and incomplete-close paths did not carry explicit terminal/retry semantics | 5B records `NO_CANDIDATES`; 5C uses `EOD_RETRY_REQUIRED` unless records are terminally resolved. |
| Backtest queue warnings | Node scheduler has a fixed 30-second watchdog | Root cause documented; no timeout redesign made because safe runtime evidence did not justify changing the existing policy. |

## Changed areas

- Kite quote, overlay, session/token hygiene, and cached market-readiness contract.
- Canonical portfolio adapter, active capital accessors, and BUY-admission duplicate guard.
- Phase 5A/5B persistence semantics, 5C EOD finalization semantics, and focused tests.
- Operator portfolio contract aliases; no UI hardcoded capital was added.

## Verification

| Check | Result |
|---|---|
| Focused RTV-1 Python suite | **92 passed**, 1 pre-existing deprecation warning |
| Paper analytics unit + real-DB smoke | **161 passed**, 1 pre-existing deprecation warning |
| Workspace API/dashboard TypeScript check | passed |
| API server rebuild/restart | passed; server listening on port 8080 |
| PortfolioLive browser verification | passed; ₹1,00,000 cash/equity, 0 positions, 0% drawdown, no console error |
| Read-only contract comparison | `/portfolio` and `/portfolio/snapshot` agree on canonical source, ₹100,000 capital/cash/equity, zero market value/utilisation/largest-position percentage |
| Independent code review | passed after fail-closed quote timestamp and monotonic lifecycle fixes |

## Remaining risk and live-session validation

### P0

None open in the implemented code path.

### P1 / live-session blockers

1. Kite is not authenticated in the runtime: `credentials_present=false`, token state is `MISSING`, and 49 of 50 active symbols lack a cached token.
2. The market is closed and the cached session is not fresh. `trading_data_ready=false` by design.
3. Instrument hydration, authenticated quote provenance, full token coverage, and live pre-open collection must be verified in the Monday NSE session.
4. The production backtest scheduler timeout warnings remain an operational follow-up; no research-system redesign was made.

## Completion-validation compatibility correction

The completion smoke test exposed a stale import in active paper-analytics readers after the dynamic capital-accessor correction. Those readers and their test seams now use the Phase-20 runtime capital accessor; the real-DB smoke and the full paper-analytics unit suite pass.

## Result

**CODE PASS — LIVE SESSION VERIFICATION PENDING**

The Monday checklist in `RTV1_MONDAY_LIVE_SESSION_CHECKLIST.md` is the required path to a live-session result.