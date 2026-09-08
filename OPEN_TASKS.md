# Open Project Tasks

Live snapshot: 2026-08-25. Open means not MERGED or CANCELLED. Total open tasks: **241**.

## Summary

| Status | Count |
|---|---:|
| PROPOSED | 238 |
| IN_PROGRESS | 1 |
| PENDING | 2 |

## Task list

| Ref | Task | Status | Brief comment |
|---|---|---|---|
| #30 | Keep the sidebar badge accurate when discrepancies are resolved from any page | PROPOSED | Proposed backlog item awaiting acceptance. depends on #20. |
| #31 | Confirm the reconciliation badge stays hidden when there are no open issues | PROPOSED | Proposed backlog item awaiting acceptance. depends on #20. |
| #36 | Run the reconciliation probe automatically so operators don't have to call it manually | PROPOSED | Proposed backlog item awaiting acceptance. depends on #22. |
| #37 | Show missed-reconciliation alerts on the Broker Execution page so operators see them in context | PROPOSED | Proposed backlog item awaiting acceptance. depends on #22. |
| #40 | Catch sector-level exposure warnings disappearing silently when positions close | PROPOSED | Proposed backlog item awaiting acceptance. depends on #32. |
| #54 | Confirm the resolved section always shows the note from the most recent resolution, not a stale one | PROPOSED | Proposed backlog item awaiting acceptance. depends on #44. |
| #55 | Prevent a discrepancy from being resolved while a reopen is still in flight | PROPOSED | Proposed backlog item awaiting acceptance. depends on #44. |
| #56 | Make it clear to operators why the Reopen button is missing on old discrepancies | PROPOSED | Proposed backlog item awaiting acceptance. depends on #45. |
| #57 | Confirm the Reopen cutoff is enforced on the server so a direct API call can't bypass it | PROPOSED | Proposed backlog item awaiting acceptance. depends on #45. |
| #58 | Confirm the badge disappears in the browser when positions close, not just in unit tests | PROPOSED | Proposed backlog item awaiting acceptance. depends on #48. |
| #59 | Make sure the exposure badge updates immediately when the API returns fresh data, not after a full page reload | PROPOSED | Proposed backlog item awaiting acceptance. depends on #48. |
| #60 | Confirm the badge disappears in the browser when positions close, not just in unit tests | PROPOSED | Proposed backlog item awaiting acceptance. depends on #49. |
| #61 | Make the exposure badge pulse or animate when a new CRITICAL breach appears so operators notice immediately | PROPOSED | Proposed backlog item awaiting acceptance. depends on #49. |
| #98 | Confirm the UNREACHABLE badge appears in the browser when the health API goes down, not just in source analysis | PROPOSED | Proposed backlog item awaiting acceptance. depends on #80. |
| #99 | Catch live position-row updates silently breaking if the snapshot polling config changes | PROPOSED | Proposed backlog item awaiting acceptance. depends on #80. |
| #106 | Confirm the consolidated outage banner disappears in the browser when the API recovers, not just in unit tests | PROPOSED | Proposed backlog item awaiting acceptance. depends on #90. |
| #107 | Prevent operators from seeing a stale snapshot for up to 15 seconds after the API server restarts | PROPOSED | Proposed backlog item awaiting acceptance. depends on #90. |
| #108 | Confirm the config panel refreshes in the browser the moment an operator saves a limit, not after the next poll | PROPOSED | Proposed backlog item awaiting acceptance. depends on #91. |
| #109 | Make sure limit edits survive a hot-reload of the API server so operators don't lose mid-session overrides unexpectedly | PROPOSED | Proposed backlog item awaiting acceptance. depends on #91. |
| #112 | Fix pre-existing TypeScript errors in dashboard pages so tsc can catch real regressions | PROPOSED | Proposed backlog item awaiting acceptance. depends on #110. |
| #113 | Confirm CORS blocks non-Replit origins so a misconfiguration can't open the API to the public | PROPOSED | Proposed backlog item awaiting acceptance. depends on #110. |
| #114 | Set production API URLs as environment variables so deployed connectivity is explicit, not inferred | PROPOSED | Proposed backlog item awaiting acceptance. depends on #110. |
| #122 | Confirm the MARKET CLOSED badge disappears in the browser when the market reopens on Monday morning | PROPOSED | Proposed backlog item awaiting acceptance. depends on #116. |
| #123 | Catch a stale MARKET CLOSED badge persisting across pages when the market reopens | PROPOSED | Proposed backlog item awaiting acceptance. depends on #116. |
| #129 | Make sure a partial position exit immediately updates the sector exposure badge, not just the full-close | PROPOSED | Proposed backlog item awaiting acceptance. depends on #125. |
| #166 | Warn operators when a stock's strategy has a poor track record in today's regime | PROPOSED | Proposed backlog item awaiting acceptance. depends on #164. |
| #167 | Persist the strategy×regime advisory panel across page refreshes so the panel is always visible, not just on first load | PROPOSED | Proposed backlog item awaiting acceptance. depends on #164. |
| #169 | Confirm performance analytics still pass at 1,000 trades without the 100 ms guarantee degrading | PROPOSED | Proposed backlog item awaiting acceptance. depends on #158. |
| #170 | Confirm the rolling 30-day accuracy chart still updates correctly in the browser after the sliding-window refactor | PROPOSED | Proposed backlog item awaiting acceptance. depends on #162. |
| #171 | Warn operators on the Trade Decisions page when AI accuracy has been declining for the past 30 days | PROPOSED | Proposed backlog item awaiting acceptance. depends on #162. |
| #172 | Prevent the AI health score from silently returning stale data when the learning analysis is recomputed twice per request | PROPOSED | Proposed backlog item awaiting acceptance. depends on #162. |
| #178 | Keep the runtime-managed key exclusion list in one place so it can't drift between modules | PROPOSED | Proposed backlog item awaiting acceptance. depends on #177. |
| #179 | Confirm accuracy session history shows on the Pre-Open Intelligence page after multiple trading days | PROPOSED | Proposed backlog item awaiting acceptance. depends on #145. |
| #180 | Prevent the 09:20 reconciliation from running when actual prices are all null and producing a misleading empty accuracy report | PROPOSED | Proposed backlog item awaiting acceptance. depends on #145. |
| #181 | Confirm the accuracy card refreshes automatically after market open without needing a page reload | PROPOSED | Proposed backlog item awaiting acceptance. depends on #145. |
| #182 | Confirm the readiness score also updates when auto-paper entries open, not only when positions close | PROPOSED | Proposed backlog item awaiting acceptance. depends on #175. |
| #183 | Show a live 'Last updated' timestamp on the Data Quality card so operators know the score is current | PROPOSED | Proposed backlog item awaiting acceptance. depends on #175. |
| #184 | Prevent the exits/tick endpoint from publishing a readiness event when no positions exist to evaluate | PROPOSED | Proposed backlog item awaiting acceptance. depends on #175. |
| #202 | Confirm the VIX risk label on the Executive Dashboard tile changes colour when VIX crosses HIGH and EXTREME thresholds | PROPOSED | Proposed backlog item awaiting acceptance. depends on #193. |
| #203 | Prevent the macro score from showing stale data when VIX fetch fails and the cache has expired | PROPOSED | Proposed backlog item awaiting acceptance. depends on #193. |
| #204 | Make sure the Macro Intelligence tile never shows an error state on the Executive Dashboard when one sub-module is slow | PROPOSED | Proposed backlog item awaiting acceptance. depends on #193. |
| #205 | Confirm PRE-OPEN ADVISORY hints appear when STRONG_GAP_UP data exists, and stay hidden when none qualify | PROPOSED | Proposed backlog item awaiting acceptance. depends on #144. |
| #206 | Let operators dismiss individual PRE-OPEN ADVISORY hints they've already reviewed | PROPOSED | Proposed backlog item awaiting acceptance. depends on #144. |
| #207 | Track whether PRE-OPEN ADVISORY candidates confirmed as gap-ups after market open, to measure prediction accuracy | PROPOSED | Proposed backlog item awaiting acceptance. depends on #144. |
| #208 | Confirm the Performance Snapshot shows accurate stats after paper trades, not zeros on a fresh portfolio | PROPOSED | Proposed backlog item awaiting acceptance. depends on #159. |
| #209 | Make the equity sparkline on the Portfolio page visible immediately by seeding it from the portfolio snapshot's equity history | PROPOSED | Proposed backlog item awaiting acceptance. depends on #159. |
| #210 | Add a P&L trend badge to the Portfolio sidebar entry so operators see session performance at a glance without opening the page | PROPOSED | Proposed backlog item awaiting acceptance. depends on #159. |
| #221 | Confirm the pre-open accuracy report shows real gap-prediction data after a morning cycle completes | PROPOSED | Proposed backlog item awaiting acceptance. depends on #143. |
| #222 | Pre-warm the Research Lab snapshot cache during the post-scan pipeline so the cold yfinance fetch never blocks an operator's HTTP request | PROPOSED | Proposed backlog item awaiting acceptance. depends on #216. |
| #229 | Mark each trade entry and exit on the equity curve so operators can see which trades drove drawdowns | PROPOSED | Proposed backlog item awaiting acceptance. depends on #228. |
| #230 | Confirm the equity chart still renders correctly when the paper portfolio has exactly 1 or 2 data points | PROPOSED | Proposed backlog item awaiting acceptance. depends on #228. |
| #231 | Confirm the AI Health score updates on the Executive Dashboard within 60 seconds after a new scan completes | PROPOSED | Proposed backlog item awaiting acceptance. depends on #212. |
| #232 | Show the AI Health score breakdown (accuracy, calibration, consistency) on hover so operators understand what drives the score | PROPOSED | Proposed backlog item awaiting acceptance. depends on #212. |
| #233 | Confirm the regime badges appear correctly after 5+ paper trades exist, not just on an empty dataset | PROPOSED | Proposed backlog item awaiting acceptance. depends on #213. |
| #234 | Show which strategies are viable for the current regime on the Trade Decisions page so operators choose the right one | PROPOSED | Proposed backlog item awaiting acceptance. depends on #213. |
| #235 | Prevent stale regime data from silently masking a regime transition that happened mid-session | PROPOSED | Proposed backlog item awaiting acceptance. depends on #213. |
| #236 | Apply _as_str coercion to string KPI fields in the shared_services snapshot functions used by non-executive pages | PROPOSED | Proposed backlog item awaiting acceptance. depends on #219. |
| #237 | Confirm the Executive Dashboard summary endpoint still returns valid JSON when every upstream module times out simultaneously | PROPOSED | Proposed backlog item awaiting acceptance. depends on #219. |
| #238 | Show pre-open gap-down advisory hints alongside gap-ups so operators can act on both directions | PROPOSED | Proposed backlog item awaiting acceptance. depends on #220. |
| #239 | Confirm the Pre-Open Advisory panel hides correctly outside pre-open hours, not just when hints are empty | PROPOSED | Proposed backlog item awaiting acceptance. depends on #220. |
| #240 | Confirm the Research Lab snapshot shows the correct grade after a live scan, not a stale cached value | PROPOSED | Proposed backlog item awaiting acceptance. depends on #224. |
| #241 | Prevent the Portfolio Performance snapshot from silently showing a wrong grade when the performance engine is unavailable | PROPOSED | Proposed backlog item awaiting acceptance. depends on #224. |
| #244 | Confirm the Paper Analytics tile in the Executive Dashboard still shows correctly after the API server restarts mid-session | PROPOSED | Proposed backlog item awaiting acceptance. depends on #243. |
| #329 | Confirm load_all stays fault-tolerant if any other section loader raises at startup | PROPOSED | Proposed backlog item awaiting acceptance. depends on #247. |
| #330 | Confirm the Executive Score neutral fallback survives a hot-reload without resetting to zero mid-session | PROPOSED | Proposed backlog item awaiting acceptance. depends on #247. |
| #334 | Stop repeated Opportunity Scan polls from spawning Python every time, not just concurrent ones | PROPOSED | Proposed backlog item awaiting acceptance. depends on #327. |
| #335 | Confirm all waiting callers see the failure when an in-flight Opportunity Scan errors mid-request | PROPOSED | Proposed backlog item awaiting acceptance. depends on #327. |
| #336 | Show the oldest-to-newest domain score trend so operators can see if a specific domain is getting worse over time, not just the latest value | PROPOSED | Proposed backlog item awaiting acceptance. depends on #258. |
| #337 | Confirm the domain sparkline grid still looks correct when a run is missing scores for one or more domains | PROPOSED | Proposed backlog item awaiting acceptance. depends on #258. |
| #338 | Let operators export per-domain trend data as CSV so they can track quality degradation in their own tools | PROPOSED | Proposed backlog item awaiting acceptance. depends on #258. |
| #339 | Stop the Agent Operations stats bar from showing 0 agents for 25 seconds after page load | PROPOSED | Proposed backlog item awaiting acceptance. depends on #328. |
| #340 | Make the diagnostics panel show the real active agent count, not zero | PROPOSED | Proposed backlog item awaiting acceptance. depends on #328. |
| #341 | Confirm all four dashboard pages show the same agent count after an API server restart, not just when manually tested | PROPOSED | Proposed backlog item awaiting acceptance. depends on #328. |
| #342 | Confirm the Executive Score drops visibly when a live data source fails during a session | PROPOSED | Proposed backlog item awaiting acceptance. depends on #259. |
| #343 | Show the Data Quality grade on the Executive Score ring tooltip so operators know which component dropped the score | PROPOSED | Proposed backlog item awaiting acceptance. depends on #259. |
| #344 | Show the Data Quality grade on the Executive Score ring tooltip so operators know which component dropped the score | PROPOSED | Proposed backlog item awaiting acceptance. depends on #260. |
| #345 | Confirm the trend chip stays Stable — not Declining — when data quality runs don't exist yet | PROPOSED | Proposed backlog item awaiting acceptance. depends on #260. |
| #346 | Prevent stale regime data from silently masking a regime transition that happened mid-session | PROPOSED | Proposed backlog item awaiting acceptance. depends on #260. |
| #347 | Confirm the AI Health tile also recovers gracefully when the API server restarts mid-session | PROPOSED | Proposed backlog item awaiting acceptance. depends on #261. |
| #348 | Confirm the Research Lab tile shows fresh data after a server restart, not a stale grade | PROPOSED | Proposed backlog item awaiting acceptance. depends on #261. |
| #349 | Show operators exactly how long to wait when the Scan button is rate-limited on mobile | PROPOSED | Proposed backlog item awaiting acceptance. depends on #295. |
| #350 | Confirm the mobile Scan button stops the spinner and surfaces an error when the server is busy | PROPOSED | Proposed backlog item awaiting acceptance. depends on #295. |
| #351 | Confirm the sparkline stays accurate when two positions share the same price in consecutive scans | PROPOSED | Proposed backlog item awaiting acceptance. depends on #303. |
| #352 | Prevent the sparkline from breaking when a timeline event carries a price of zero or null | PROPOSED | Proposed backlog item awaiting acceptance. depends on #303. |
| #353 | Trigger a price snapshot automatically after every scan so sparklines fill in without manual API calls | PROPOSED | Proposed backlog item awaiting acceptance. depends on #304. |
| #354 | Confirm sparkline snapshots from yesterday don't bleed into today's chart | PROPOSED | Proposed backlog item awaiting acceptance. depends on #304. |
| #355 | Prune old intraday snapshots so the price-history table doesn't grow indefinitely | PROPOSED | Proposed backlog item awaiting acceptance. depends on #304. |
| #356 | Confirm all three E2E specs pass together in CI without timeouts | PROPOSED | Proposed backlog item awaiting acceptance. depends on #305. |
| #357 | Confirm the Risk Agent card recovers automatically when phase20 data arrives after a cold start | PROPOSED | Proposed backlog item awaiting acceptance. depends on #313. |
| #358 | Prevent the Risk Agent card from going dark when the SnapshotBus restarts but phase20 data is intact | PROPOSED | Proposed backlog item awaiting acceptance. depends on #313. |
| #359 | Make sure ops-centre overview never blocks on the Risk Agent when it is slow to initialise | PROPOSED | Proposed backlog item awaiting acceptance. depends on #313. |
| #360 | Confirm the gate breakdown table shows correctly when all candidates pass (zero rejections) | PROPOSED | Proposed backlog item awaiting acceptance. depends on #314. |
| #361 | Show which specific gate blocked each candidate symbol so operators can act on individual stocks | PROPOSED | Proposed backlog item awaiting acceptance. depends on #314. |
| #362 | Apply the same offline caching to the Signals tab so operators see last-known signals instead of a blank screen when offline | PROPOSED | Proposed backlog item awaiting acceptance. depends on #315. |
| #422 | Show a run-freshness warning banner on the Missed Opps tab when the newest run is more than 7 days old | PROPOSED | Proposed backlog item awaiting acceptance. depends on #401. |
| #423 | Let operators filter the Missed Opps table by run so they can compare what changed between two backtests | PROPOSED | Proposed backlog item awaiting acceptance. depends on #401. |
| #424 | Confirm the Run ID chip on Missed Opps correctly pre-selects that run in Trade Simulation, not just navigates to the tab | PROPOSED | Proposed backlog item awaiting acceptance. depends on #401. |
| #425 | Run the codegen idempotency check automatically when the orval config changes so regressions can't be merged silently | PROPOSED | Proposed backlog item awaiting acceptance. depends on #393. |
| #426 | Make codegen:check faster by skipping the typecheck step so it can realistically run on every save | PROPOSED | Proposed backlog item awaiting acceptance. depends on #393. |
| #428 | Prevent the operator seeing two conflicting freshness labels at the same time on the Pipeline tab | PROPOSED | Proposed backlog item awaiting acceptance. depends on #363. |
| #429 | Confirm the 'Live' badge recovers automatically once the snapshot endpoint comes back up after an error | PROPOSED | Proposed backlog item awaiting acceptance. depends on #367. |
| #430 | Prevent the platform badge from briefly flashing 'Live' on page load when only the cached snapshot is available | PROPOSED | Proposed backlog item awaiting acceptance. depends on #367. |
| #431 | Confirm the 'Live' badge age ticker also advances when the snapshot is freshly computed | PROPOSED | Proposed backlog item awaiting acceptance. depends on #368. |
| #432 | Confirm staleness badges stay accurate when the browser tab is hidden for several minutes then brought back | PROPOSED | Proposed backlog item awaiting acceptance. depends on #369. |
| #433 | Show a staleness badge on the AI Paper Trader page so operators know how fresh the portfolio snapshot is | PROPOSED | Proposed backlog item awaiting acceptance. depends on #369. |
| #434 | Prevent the StalenessTag from flickering between Live and Cached on the first render before the timestamp arrives | PROPOSED | Proposed backlog item awaiting acceptance. depends on #369. |
| #435 | Confirm the AIOperationsCentrePage staleness badge also goes amber after 60 s of idle | PROPOSED | Proposed backlog item awaiting acceptance. depends on #370. |
| #436 | Prevent the Live pill from showing stale seconds counts when the browser tab sleeps | PROPOSED | Proposed backlog item awaiting acceptance. depends on #370. |
| #437 | Confirm the recovery push re-arms correctly after a second degradation following recovery | PROPOSED | Proposed backlog item awaiting acceptance. depends on #371. |
| #438 | Confirm health alerts reach a device that subscribes mid-session after a degradation has already fired | PROPOSED | Proposed backlog item awaiting acceptance. depends on #371. |
| #439 | Confirm the recovery push still fires correctly after an API server restart mid-incident | PROPOSED | Proposed backlog item awaiting acceptance. depends on #372. |
| #440 | Prevent orphaned degraded-token records from accumulating when a device unregisters | PROPOSED | Proposed backlog item awaiting acceptance. depends on #372. |
| #441 | Confirm recovery push fires for the right subscribers when each device has a different minHealthPct threshold | PROPOSED | Proposed backlog item awaiting acceptance. depends on #373. |
| #442 | Confirm minHealthPct is honoured when a push registration is updated via the API, not just at insert time | PROPOSED | Proposed backlog item awaiting acceptance. depends on #373. |
| #443 | Sync the confidence threshold from the server on launch, not just the health threshold | PROPOSED | Proposed backlog item awaiting acceptance. depends on #374. |
| #444 | Confirm the Alerts screen shows the server threshold when it opens before the launch sync finishes | PROPOSED | Proposed backlog item awaiting acceptance. depends on #374. |
| #445 | Confirm health alerts fire at exactly the clamped threshold in a live integration test | PROPOSED | Proposed backlog item awaiting acceptance. depends on #375. |
| #446 | Prevent the minConfidence threshold from being silently mis-applied the same way if it also reaches the DB as NULL | PROPOSED | Proposed backlog item awaiting acceptance. depends on #375. |
| #452 | Show operators how many filter conditions failed on each AVOID row so they can distinguish a gate-blocked setup from a genuinely weak one | PROPOSED | Proposed backlog item awaiting acceptance. depends on #389. |
| #453 | Let operators adjust the filter-failure threshold that turns AVOID into WATCH from the settings panel without a code deploy | PROPOSED | Proposed backlog item awaiting acceptance. depends on #389. |
| #454 | Confirm the trade decisions cache serves the correct WATCH/AVOID label after the market scan updates mid-session, not the stale one from 10 minutes ago | PROPOSED | Proposed backlog item awaiting acceptance. depends on #389. |
| #455 | Confirm the gate threshold change takes effect mid-session without restarting the server | PROPOSED | Proposed backlog item awaiting acceptance. depends on #390. |
| #456 | Show the active gate threshold on the Trade Decisions page so operators know which value is in effect | PROPOSED | Proposed backlog item awaiting acceptance. depends on #390. |
| #458 | Prevent the Overview KPIs from going blank while Performance Analytics and Optimizer data re-fetches after a backtest | PROPOSED | Proposed backlog item awaiting acceptance. depends on #400. |
| #459 | Confirm the LOW RELIABILITY badge also renders correctly in the browser and can't silently disappear | PROPOSED | Proposed backlog item awaiting acceptance. depends on #449. |
| #460 | Confirm the low-evidence badge still shows after the AI decision cache refreshes mid-session | PROPOSED | Proposed backlog item awaiting acceptance. depends on #449. |
| #461 | Confirm historical_sharpe displays correctly on the Trade Decisions page, not as undefined or zero | PROPOSED | Proposed backlog item awaiting acceptance. depends on #450. |
| #472 | Alert operators immediately when the research pipeline halts so they know paper entries are paused | PROPOSED | Proposed backlog item awaiting acceptance. depends on #469. |
| #473 | Confirm the research failure mode setting is reachable from the settings UI so operators can switch modes without touching code | PROPOSED | Proposed backlog item awaiting acceptance. depends on #469. |
| #474 | Show which research sources are timing out in the ops centre so operators know why the pipeline halted | PROPOSED | Proposed backlog item awaiting acceptance. depends on #469. |
| #475 | Confirm the 'Awaiting first scan' notice disappears once the first scan completes and real pipeline data is present | PROPOSED | Proposed backlog item awaiting acceptance. depends on #471. |
| #476 | Prevent the Supervisor recommendations panel from showing duplicate entries when stale and violation conditions overlap | PROPOSED | Proposed backlog item awaiting acceptance. depends on #471. |
| #524 | Show why certification is NOT READY on the Validation Dashboard, including stale-evidence warnings | PROPOSED | Proposed backlog item awaiting acceptance. depends on #516. |
| #525 | Confirm the amber and red token countdown states actually appear in the browser, not just for a fresh token | PROPOSED | Proposed backlog item awaiting acceptance. depends on #12. |
| #526 | Make the countdown tick down between polls so it never looks frozen | PROPOSED | Proposed backlog item awaiting acceptance. depends on #12. |
| #527 | Prevent the portfolio snapshot history table from growing unbounded in the database | PROPOSED | Proposed backlog item awaiting acceptance. depends on #25. |
| #528 | Confirm the Portfolio page shows recovered positions in the browser after a real server restart | PROPOSED | Proposed backlog item awaiting acceptance. depends on #25. |
| #529 | Make sure a changed expiry warning lead time takes effect after re-authentication without a restart | PROPOSED | Proposed backlog item awaiting acceptance. depends on #13. |
| #530 | Confirm the expiry monitor keeps running after the daily OAuth re-authentication, not just at startup | PROPOSED | Proposed backlog item awaiting acceptance. depends on #13. |
| #531 | Show operators which limits are overridden right on the config panel, with one-click revert per field | PROPOSED | Proposed backlog item awaiting acceptance. depends on #68. |
| #532 | Confirm exposure-limit edits (not just position counts) change gate decisions mid-session | PROPOSED | Proposed backlog item awaiting acceptance. depends on #68. |
| #536 | Make the manual 'Run fresh scan' button reliable in production, where background work can be cut short | PROPOSED | Proposed backlog item awaiting acceptance. depends on #100. |
| #537 | Record equity snapshots on a timer so the equity curve grows even on quiet days | PROPOSED | Proposed backlog item awaiting acceptance. depends on #24. |
| #538 | Confirm the new equity and daily P&L charts render safely when history data is malformed | PROPOSED | Proposed backlog item awaiting acceptance. depends on #24. |
| #539 | Add a guard test that keeps every dashboard stage list in sync with the canonical pipeline stage vocabulary | PROPOSED | Proposed backlog item awaiting acceptance. depends on #520. |
| #540 | Confirm the health/ready warning actually appears when the portfolio config breaks | PROPOSED | Proposed backlog item awaiting acceptance. depends on #127. |
| #541 | Confirm the coverage warning banner appears in the browser during a live session, not just in code | PROPOSED | Proposed backlog item awaiting acceptance. depends on #128. |
| #545 | Stop trade analytics from waiting 2 seconds on every run when the executive score is unavailable | PROPOSED | Proposed backlog item awaiting acceptance. depends on #214. |
| #548 | Confirm the paper-fallback count row appears in the browser when a token expiry actually reroutes orders | PROPOSED | Proposed backlog item awaiting acceptance. depends on #533. |
| #549 | Show which fallback reasons drove paper rerouting, not just the total count | PROPOSED | Proposed backlog item awaiting acceptance. depends on #533. |
| #551 | Show operators whether the portfolio book was recovered or rebuilt after a restart | PROPOSED | Proposed backlog item awaiting acceptance. depends on #521. |
| #557 | Catch percent-vs-fraction unit mixups on the AI Performance page before they reach the browser | PROPOSED | Proposed backlog item awaiting acceptance. depends on #546. |
| #564 | Give the trading bot its own database so its migrations (incl. fallback tagging) can actually run | PROPOSED | Proposed backlog item awaiting acceptance. depends on #534. |
| #565 | Show low-coverage alerts as a banner on the dashboard so operators see them without opening notifications | PROPOSED | Proposed backlog item awaiting acceptance. depends on #542. |
| #566 | Surface the metadata-integrity warning on the AI Performance page so operators see it, not just the API | PROPOSED | Proposed backlog item awaiting acceptance. depends on #547. |
| #583 | Confirm a FAIL alert email really reaches the operator's inbox path, not just the queue | PROPOSED | Proposed backlog item awaiting acceptance. depends on #567. |
| #584 | Make mid-session FAIL alerts impossible to miss on the dashboard, not just in the notifications list | PROPOSED | Proposed backlog item awaiting acceptance. depends on #567. |
| #586 | Confirm daily-report pruning also works against the real Postgres table, not just the local file | PROPOSED | Proposed backlog item awaiting acceptance. depends on #571. |
| #590 | Confirm filter good/bad counts turn green in the browser after a live trading session records outcomes | PROPOSED | Proposed backlog item awaiting acceptance. depends on #582. |
| #593 | Show real timestamps and processing times on the AI reasoning timeline instead of placeholder dashes | PROPOSED | Proposed backlog item awaiting acceptance. depends on #581. |
| #594 | Confirm the Why tab timeline renders in the browser for a scanned symbol, not just via the API | PROPOSED | Proposed backlog item awaiting acceptance. depends on #581. |
| #595 | Catch the paper-order import error surfacing in the Execution stage reason | PROPOSED | Proposed backlog item awaiting acceptance. depends on #581. |
| #597 | Let operators pick a past scan on Operator Analytics instead of only the latest | PROPOSED | Proposed backlog item awaiting acceptance. depends on #591. |
| #598 | Confirm the Operator Analytics page renders correctly in the browser when the event store is down | PROPOSED | Proposed backlog item awaiting acceptance. depends on #591. |
| #602 | Confirm stage timings show real millisecond values during the next live market session | PROPOSED | Proposed backlog item awaiting acceptance. depends on #596. |
| #603 | Let dashboard tests run without manual environment setup so checks can't be accidentally skipped | PROPOSED | Proposed backlog item awaiting acceptance. depends on #457. |
| #604 | Catch age-sensitive test dates going stale before they cause mystery failures | PROPOSED | Proposed backlog item awaiting acceptance. depends on #483. |
| #605 | Confirm production keeps the paper-fallback count after republish | PROPOSED | Proposed backlog item awaiting acceptance. depends on #563. |
| #606 | Retire the duplicate retention constant name so future edits can't tune the wrong knob | PROPOSED | Proposed backlog item awaiting acceptance. depends on #580. |
| #613 | Give every Python-backed API route the same clear error detail, not just the session routes | PROPOSED | Proposed backlog item awaiting acceptance. depends on #610. |
| #621 | Confirm the market-open failure alert email actually reaches operators, not just the notification list | PROPOSED | Proposed backlog item awaiting acceptance. depends on #620. |
| #622 | Keep the pipeline panel refreshing until the fresh scan actually finishes, so stale labels don't linger | PROPOSED | Proposed backlog item awaiting acceptance. depends on #612. |
| #623 | Tell operators when a fresh-scan request is rate-limited instead of failing silently | PROPOSED | Proposed backlog item awaiting acceptance. depends on #612. |
| #634 | Confirm the watchdog runs automatically on every backtest list request, not just when called directly | PROPOSED | Proposed backlog item awaiting acceptance. depends on #633. |
| #635 | Prevent the watchdog from silently ignoring a run whose timestamp field is malformed or missing entirely | PROPOSED | Proposed backlog item awaiting acceptance. depends on #633. |
| #636 | Confirm ghost runs disappear from the Investigation Center UI after the next poll, not just in the database | PROPOSED | Proposed backlog item awaiting acceptance. depends on #633. |
| #638 | Stop a hung yfinance download from freezing the backtest heartbeat and triggering a false-stale alarm | PROPOSED | Proposed backlog item awaiting acceptance. depends on #632. |
| #639 | Confirm the retry fires exactly once and a persistent DB outage still surfaces a FAILED run, not a silent hang | PROPOSED | Proposed backlog item awaiting acceptance. depends on #632. |
| #643 | Confirm the sweep-status line stays accurate after the API server restarts mid-session | PROPOSED | Proposed backlog item awaiting acceptance. depends on #642. |
| #644 | Prevent QUEUED backtests from sitting forever when the scheduler is disabled at startup | PROPOSED | Proposed backlog item awaiting acceptance. depends on #642. |
| #645 | Confirm the scheduler shows as disabled in the Investigation Center so operators know their maintenance pause is active | PROPOSED | Proposed backlog item awaiting acceptance. depends on #641. |
| #646 | Catch a misconfigured maintenance flag from accidentally freezing the backtest queue for the rest of the session | PROPOSED | Proposed backlog item awaiting acceptance. depends on #641. |
| #649 | Confirm back-to-back scheduler ticks can't run at the same time and corrupt the health counters | PROPOSED | Proposed backlog item awaiting acceptance. depends on #648. |
| #653 | Show the BUY execution audit inline on the Trade Decisions page so operators don't need curl | PROPOSED | Proposed backlog item awaiting acceptance. depends on #652. |
| #654 | Confirm the buy-audit endpoint stays accurate when the same scan_id has both an AUTO and a MANUAL trade | PROPOSED | Proposed backlog item awaiting acceptance. depends on #652. |
| #655 | Prevent the buy-audit from returning stale records when BUY signals from a cancelled scan appear in the event log | PROPOSED | Proposed backlog item awaiting acceptance. depends on #652. |
| #658 | Confirm the paper order confirmation flow works end-to-end in the browser, not just in unit tests | PROPOSED | Proposed backlog item awaiting acceptance. depends on #657. |
| #659 | Prevent paper-mode SELL orders from silently failing when no position exists | PROPOSED | Proposed backlog item awaiting acceptance. depends on #657. |
| #660 | Make the audit log accurately count paper orders toward the daily limit so the cap is never bypassed | PROPOSED | Proposed backlog item awaiting acceptance. depends on #657. |
| #668 | Confirm a local backtest run completes end-to-end so the setup guide can be trusted | PROPOSED | Proposed backlog item awaiting acceptance. depends on #667. |
| #674 | Confirm the Investigation Centre's stale-guard banner can't silently disappear after a page reload | PROPOSED | Proposed backlog item awaiting acceptance. depends on #670. |
| #685 | Confirm the post-close seal fires in the scheduler tick, not just in the seal function itself | PROPOSED | Proposed backlog item awaiting acceptance. depends on #680. |
| #686 | Prevent the orphan seal from running against yesterday's scan on non-trading days | PROPOSED | Proposed backlog item awaiting acceptance. depends on #680. |
| #687 | Confirm the Agent Journey shows the correct execution outcome when the database is unavailable | PROPOSED | Proposed backlog item awaiting acceptance. depends on #681. |
| #688 | Prevent the execution-outcome seal from making 4 database round trips per scan | PROPOSED | Proposed backlog item awaiting acceptance. depends on #681. |
| #694 | Retire the duplicate retention constant so future tuning can't accidentally target the wrong table | PROPOSED | Proposed backlog item awaiting acceptance. depends on #550. |
| #699 | Confirm performance data updates in the browser within 1 second of a manual trade, not just in unit tests | PROPOSED | Proposed backlog item awaiting acceptance. depends on #168. |
| #700 | Prevent stale performance data after a portfolio reset resets the trade list | PROPOSED | Proposed backlog item awaiting acceptance. depends on #168. |
| #701 | Confirm the equity curve on the Portfolio Performance page updates immediately after a new trade, not after a 30-second delay | PROPOSED | Proposed backlog item awaiting acceptance. depends on #168. |
| #703 | Prevent a DB-timeout error message from being silently truncated before operators can read the full retry advice | PROPOSED | Proposed backlog item awaiting acceptance. depends on #637. |
| #715 | Confirm the symbol grid auto-expands in the browser during an active scan, not just in source analysis | PROPOSED | Proposed backlog item awaiting acceptance. depends on #708. |
| #716 | Prevent the pipeline panel from collapsing a stage the operator just manually opened | PROPOSED | Proposed backlog item awaiting acceptance. depends on #708. |
| #718 | Confirm the scan history list opens and shows real rows in the browser, not just in unit tests | PROPOSED | Proposed backlog item awaiting acceptance. depends on #713. |
| #750 | Confirm the ⚠ Gap badge appears in the browser when a scan is overdue, not just in source analysis | PROPOSED | Proposed backlog item awaiting acceptance. depends on #717. |
| #751 | Make the ⚠ Gap badge link directly to the scan history panel so operators can investigate in one click | PROPOSED | Proposed backlog item awaiting acceptance. depends on #717. |
| #761 | Flag runs with synthetic data in the run list so operators spot contaminated results without clicking in | PROPOSED | Proposed backlog item awaiting acceptance. depends on #669. |
| #762 | Confirm the mock-candle warning banner renders in the browser after a completed run, not just in unit tests | PROPOSED | Proposed backlog item awaiting acceptance. depends on #669. |
| #763 | Prevent mock candles from entering the backtest cache silently when market_data_engine is called directly | PROPOSED | Proposed backlog item awaiting acceptance. depends on #669. |
| #773 | Confirm the copilot engine's R:R badge always shows the live configured minimum, not a hardcoded 1.5 | PROPOSED | Proposed backlog item awaiting acceptance. depends on #679. |
| #774 | Confirm the phase15 explainability card never shows a stale R:R benchmark after an operator tunes the threshold | PROPOSED | Proposed backlog item awaiting acceptance. depends on #679. |
| #775 | Show bootstrap-eligible WATCH symbols in the scan panel so operators know which symbols will be traded next | PROPOSED | Proposed backlog item awaiting acceptance. depends on #772. |
| #776 | Confirm bootstrap mode shuts off cleanly once the production ledger has enough real evidence | PROPOSED | Proposed backlog item awaiting acceptance. depends on #772. |
| #777 | Prevent bootstrap thresholds and low_evidence threshold from drifting apart when tuned independently | PROPOSED | Proposed backlog item awaiting acceptance. depends on #772. |
| #778 | Confirm the snapshot pruning runs automatically during normal trading so old rows don't silently accumulate | PROPOSED | Proposed backlog item awaiting acceptance. depends on #695. |
| #779 | Prevent the snapshot table from growing unboundedly if the pruning cooldown never resets between server restarts | PROPOSED | Proposed backlog item awaiting acceptance. depends on #695. |
| #780 | Confirm the watchdog sweep runs automatically on a schedule so stuck runs are caught without a user triggering a page view | PROPOSED | Proposed backlog item awaiting acceptance. depends on #702. |
| #781 | Expose the watchdog TTL as an operator-configurable setting so it can be tuned without a code deploy | PROPOSED | Proposed backlog item awaiting acceptance. depends on #702. |
| #782 | Make sure the Investigation Center shows a clear 'Watchdog killed' badge on timed-out runs so operators don't mistake them for logic failures | PROPOSED | Proposed backlog item awaiting acceptance. depends on #702. |
| #787 | Confirm the Bootstrap Status card disappears after bootstrap is disabled, without a page reload | PROPOSED | Proposed backlog item awaiting acceptance. depends on #786. |
| #788 | Show the timestamp of the last bootstrap trade on the status card so operators know when it fired | PROPOSED | Proposed backlog item awaiting acceptance. depends on #786. |
| #789 | Confirm EXIT_PENDING force-close fires correctly when the real DB has stuck trades | PROPOSED | Proposed backlog item awaiting acceptance. depends on #785. |
| #792 | Confirm the Age column shows correct values after a position has been open for multiple days | PROPOSED | Proposed backlog item awaiting acceptance. depends on #790. |
| #794 | Show the Age column on the mobile Holdings screen so field operators can spot stuck positions on their phones | PROPOSED | Proposed backlog item awaiting acceptance. depends on #790. |
| #813 | Confirm force-closed trades show up immediately on the dashboard without a page reload | PROPOSED | Proposed backlog item awaiting acceptance. depends on #807. |
| #814 | Prevent EXIT_PENDING positions from silently accumulating when the age-alert command shows 0 hours for legacy rows | PROPOSED | Proposed backlog item awaiting acceptance. depends on #807. |
| #815 | Make sure the phase20 exit tick runs on every scan even when the scheduler restarts mid-session | PROPOSED | Proposed backlog item awaiting acceptance. depends on #807. |
| #819 | Confirm the bootstrap cap change takes effect in the running API server without a restart breaking anything | PROPOSED | Proposed backlog item awaiting acceptance. depends on #818. |
| #820 | Prevent the bootstrap status panel from showing a stale ₹1,500 cap after the server is updated | PROPOSED | Proposed backlog item awaiting acceptance. depends on #818. |
| #835 | Confirm the EOD banner shows the right state when no positions exist at square-off time | PROPOSED | Proposed backlog item awaiting acceptance. depends on #833. |
| #836 | Confirm the EOD status endpoint returns safe fallback data when the paper trades table is missing | PROPOSED | Proposed backlog item awaiting acceptance. depends on #833. |
| #837 | Make the EOD square-off exit_ts human-readable on Mission Control so operators can see exactly when each position closed | PROPOSED | Proposed backlog item awaiting acceptance. depends on #833. |
| #838 | Prevent the CLOSED-state scheduler test from silently passing even when the real EOD import path is broken | PROPOSED | Proposed backlog item awaiting acceptance. depends on #834. |
| #856 | Show operators the OHLCV cache cold-start status on the dashboard so they can see if a backfill is in progress | PROPOSED | Proposed backlog item awaiting acceptance. depends on #849. |
| #858 | Cut cache reads from 50 DB round trips to 1 so scans stay fast as the universe grows | PROPOSED | Proposed backlog item awaiting acceptance. depends on #850. |
| #860 | Expose per-scan cache read latency so operators can see when DB performance degrades | PROPOSED | Proposed backlog item awaiting acceptance. depends on #850. |
| #864 | Finish the production LTIM removal and ₹100,000 rebase after GRASIM closes | PROPOSED | Proposed backlog item awaiting acceptance. depends on #863. |
| #865 | Keep paper-exit tests from reading or changing real development positions | PROPOSED | Proposed backlog item awaiting acceptance. depends on #863. |
| #880 | Catch an older paper position disappearing during database fallback | IN_PROGRESS | Currently being worked on. depends on #877. |
| #919 | Catch a stale dashboard identity before operators open Mission Control | PENDING | Accepted and waiting; blocked by CONCURRENCY_LIMIT. blocked by CONCURRENCY_LIMIT; depends on #917. |
| #924 | Show operators when custom-universe mappings need a refresh | PENDING | Accepted and waiting; blocked by CONCURRENCY_LIMIT. blocked by CONCURRENCY_LIMIT; depends on #922. |
| #925 | Catch an older pending exit being lost during a database outage | PROPOSED | Proposed backlog item awaiting acceptance. depends on #880. |
