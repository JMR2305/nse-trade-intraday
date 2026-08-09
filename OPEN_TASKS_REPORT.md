# Open Task Report — 2026-08-09

Snapshot of all open (not merged / not archived) project tasks for the ApexQuant AI NSE trading platform.

## Overview

| Status | Count |
|---|---|
| Active (in progress) | 1 |
| Active (waiting to start) | 4 |
| Drafts (awaiting acceptance) | 158 |
| **Total open** | **163** |

## Active — In Progress

| Ref | Title | Depends on | Updated |
|---|---|---|---|
| #533 | Show operators how many orders were rerouted to paper after a token expiry, right on the Broker page | #14 | 2026-08-09 |

## Active — Waiting to Start

| Ref | Title | Depends on | Updated |
|---|---|---|---|
| #534 | Confirm the new fallback-tagging database columns exist in production before the next live session | #14 | 2026-08-09 |
| #535 | Fix broken test imports so the full trading-bot test suite can run again | #14 | 2026-08-09 |
| #546 | Confirm the AI Performance page in the browser shows the same numbers the API computes | #215 | 2026-08-09 |
| #547 | Catch silently-lost trade metadata that would zero out AI confidence analytics | #215 | 2026-08-09 |

## Drafts (awaiting acceptance) — 158 tasks, newest first

| Ref | Title | Depends on | Updated |
|---|---|---|---|
| #545 | Stop trade analytics from waiting 2 seconds on every run when the executive score is unavailable | #214 | 2026-08-09 |
| #542 | Alert operators automatically when coverage stays below 50 well into the session, not only on page view | #128 | 2026-08-09 |
| #541 | Confirm the coverage warning banner appears in the browser during a live session, not just in code | #128 | 2026-08-09 |
| #540 | Confirm the health/ready warning actually appears when the portfolio config breaks | #127 | 2026-08-09 |
| #539 | Add a guard test that keeps every dashboard stage list in sync with the canonical pipeline stage vocabulary | #520 | 2026-08-09 |
| #538 | Confirm the new equity and daily P&L charts render safely when history data is malformed | #24 | 2026-08-09 |
| #537 | Record equity snapshots on a timer so the equity curve grows even on quiet days | #24 | 2026-08-09 |
| #536 | Make the manual 'Run fresh scan' button reliable in production, where background work can be cut short | #100 | 2026-08-08 |
| #531 | Show operators which limits are overridden right on the config panel, with one-click revert per field | #68 | 2026-08-08 |
| #532 | Confirm exposure-limit edits (not just position counts) change gate decisions mid-session | #68 | 2026-08-08 |
| #530 | Confirm the expiry monitor keeps running after the daily OAuth re-authentication, not just at startup | #13 | 2026-08-08 |
| #529 | Make sure a changed expiry warning lead time takes effect after re-authentication without a restart | #13 | 2026-08-08 |
| #527 | Prevent the portfolio snapshot history table from growing unbounded in the database | #25 | 2026-08-08 |
| #528 | Confirm the Portfolio page shows recovered positions in the browser after a real server restart | #25 | 2026-08-08 |
| #525 | Confirm the amber and red token countdown states actually appear in the browser, not just for a fresh token | #12 | 2026-08-08 |
| #526 | Make the countdown tick down between polls so it never looks frozen | #12 | 2026-08-08 |
| #524 | Show why certification is NOT READY on the Validation Dashboard, including stale-evidence warnings | #516 | 2026-08-08 |
| #521 | Keep portfolio limit checks accurate across restarts by storing portfolio state in the database | #15 | 2026-08-08 |
| #522 | Catch the drawdown gate silently blocking every trade before it ships again | #15 | 2026-08-08 |
| #513 | Make Market Breadth show real advance/decline numbers instead of dashes during market hours | — | 2026-08-08 |
| #512 | Verify the Market Session widget shows 'closed' on NSE holidays, not a fake in-session progress bar | — | 2026-08-08 |
| #511 | Confirm Investigate links land on the exact moment even when opening an older backtest run | — | 2026-08-08 |
| #483 | Fix the 3 failing trailing-stop safety tests so exit protection is provably working | #482 | 2026-08-08 |
| #475 | Confirm the 'Awaiting first scan' notice disappears once the first scan completes and real pipeline data is present | #471 | 2026-08-07 |
| #476 | Prevent the Supervisor recommendations panel from showing duplicate entries when stale and violation conditions overlap | #471 | 2026-08-07 |
| #472 | Alert operators immediately when the research pipeline halts so they know paper entries are paused | #469 | 2026-08-07 |
| #473 | Confirm the research failure mode setting is reachable from the settings UI so operators can switch modes without touching code | #469 | 2026-08-07 |
| #474 | Show which research sources are timing out in the ops centre so operators know why the pipeline halted | #469 | 2026-08-07 |
| #461 | Confirm historical_sharpe displays correctly on the Trade Decisions page, not as undefined or zero | #450 | 2026-08-07 |
| #459 | Confirm the LOW RELIABILITY badge also renders correctly in the browser and can't silently disappear | #449 | 2026-08-07 |
| #460 | Confirm the low-evidence badge still shows after the AI decision cache refreshes mid-session | #449 | 2026-08-07 |
| #458 | Prevent the Overview KPIs from going blank while Performance Analytics and Optimizer data re-fetches after a backtest | #400 | 2026-08-07 |
| #457 | Confirm Performance Analytics and Optimizer tabs show fresh data immediately after a backtest — not after a 60-second wait | #400 | 2026-08-07 |
| #455 | Confirm the gate threshold change takes effect mid-session without restarting the server | #390 | 2026-08-07 |
| #456 | Show the active gate threshold on the Trade Decisions page so operators know which value is in effect | #390 | 2026-08-07 |
| #452 | Show operators how many filter conditions failed on each AVOID row so they can distinguish a gate-blocked setup from a genuinely weak one | #389 | 2026-08-07 |
| #453 | Let operators adjust the filter-failure threshold that turns AVOID into WATCH from the settings panel without a code deploy | #389 | 2026-08-07 |
| #454 | Confirm the trade decisions cache serves the correct WATCH/AVOID label after the market scan updates mid-session, not the stale one from 10 minutes ago | #389 | 2026-08-07 |
| #446 | Prevent the minConfidence threshold from being silently mis-applied the same way if it also reaches the DB as NULL | #375 | 2026-08-06 |
| #445 | Confirm health alerts fire at exactly the clamped threshold in a live integration test | #375 | 2026-08-06 |
| #443 | Sync the confidence threshold from the server on launch, not just the health threshold | #374 | 2026-08-06 |
| #444 | Confirm the Alerts screen shows the server threshold when it opens before the launch sync finishes | #374 | 2026-08-06 |
| #441 | Confirm recovery push fires for the right subscribers when each device has a different minHealthPct threshold | #373 | 2026-08-06 |
| #442 | Confirm minHealthPct is honoured when a push registration is updated via the API, not just at insert time | #373 | 2026-08-06 |
| #439 | Confirm the recovery push still fires correctly after an API server restart mid-incident | #372 | 2026-08-06 |
| #440 | Prevent orphaned degraded-token records from accumulating when a device unregisters | #372 | 2026-08-06 |
| #438 | Confirm health alerts reach a device that subscribes mid-session after a degradation has already fired | #371 | 2026-08-06 |
| #437 | Confirm the recovery push re-arms correctly after a second degradation following recovery | #371 | 2026-08-06 |
| #436 | Prevent the Live pill from showing stale seconds counts when the browser tab sleeps | #370 | 2026-08-06 |
| #435 | Confirm the AIOperationsCentrePage staleness badge also goes amber after 60 s of idle | #370 | 2026-08-06 |
| #434 | Prevent the StalenessTag from flickering between Live and Cached on the first render before the timestamp arrives | #369 | 2026-08-06 |
| #433 | Show a staleness badge on the AI Paper Trader page so operators know how fresh the portfolio snapshot is | #369 | 2026-08-06 |
| #432 | Confirm staleness badges stay accurate when the browser tab is hidden for several minutes then brought back | #369 | 2026-08-06 |
| #431 | Confirm the 'Live' badge age ticker also advances when the snapshot is freshly computed | #368 | 2026-08-06 |
| #429 | Confirm the 'Live' badge recovers automatically once the snapshot endpoint comes back up after an error | #367 | 2026-08-06 |
| #430 | Prevent the platform badge from briefly flashing 'Live' on page load when only the cached snapshot is available | #367 | 2026-08-06 |
| #427 | Confirm a corrupt or outdated Pipeline cache is cleared from storage so it never blocks fresh data | #363 | 2026-08-06 |
| #428 | Prevent the operator seeing two conflicting freshness labels at the same time on the Pipeline tab | #363 | 2026-08-06 |
| #426 | Make codegen:check faster by skipping the typecheck step so it can realistically run on every save | #393 | 2026-08-06 |
| #425 | Run the codegen idempotency check automatically when the orval config changes so regressions can't be merged silently | #393 | 2026-08-06 |
| #424 | Confirm the Run ID chip on Missed Opps correctly pre-selects that run in Trade Simulation, not just navigates to the tab | #401 | 2026-08-06 |
| #423 | Let operators filter the Missed Opps table by run so they can compare what changed between two backtests | #401 | 2026-08-06 |
| #422 | Show a run-freshness warning banner on the Missed Opps tab when the newest run is more than 7 days old | #401 | 2026-08-06 |
| #362 | Apply the same offline caching to the Signals tab so operators see last-known signals instead of a blank screen when offline | #315 | 2026-08-05 |
| #360 | Confirm the gate breakdown table shows correctly when all candidates pass (zero rejections) | #314 | 2026-08-05 |
| #361 | Show which specific gate blocked each candidate symbol so operators can act on individual stocks | #314 | 2026-08-05 |
| #359 | Make sure ops-centre overview never blocks on the Risk Agent when it is slow to initialise | #313 | 2026-08-05 |
| #358 | Prevent the Risk Agent card from going dark when the SnapshotBus restarts but phase20 data is intact | #313 | 2026-08-05 |
| #357 | Confirm the Risk Agent card recovers automatically when phase20 data arrives after a cold start | #313 | 2026-08-05 |
| #356 | Confirm all three E2E specs pass together in CI without timeouts | #305 | 2026-08-05 |
| #353 | Trigger a price snapshot automatically after every scan so sparklines fill in without manual API calls | #304 | 2026-08-05 |
| #354 | Confirm sparkline snapshots from yesterday don't bleed into today's chart | #304 | 2026-08-05 |
| #355 | Prune old intraday snapshots so the price-history table doesn't grow indefinitely | #304 | 2026-08-05 |
| #351 | Confirm the sparkline stays accurate when two positions share the same price in consecutive scans | #303 | 2026-08-05 |
| #352 | Prevent the sparkline from breaking when a timeline event carries a price of zero or null | #303 | 2026-08-05 |
| #349 | Show operators exactly how long to wait when the Scan button is rate-limited on mobile | #295 | 2026-08-05 |
| #350 | Confirm the mobile Scan button stops the spinner and surfaces an error when the server is busy | #295 | 2026-08-05 |
| #347 | Confirm the AI Health tile also recovers gracefully when the API server restarts mid-session | #261 | 2026-08-05 |
| #348 | Confirm the Research Lab tile shows fresh data after a server restart, not a stale grade | #261 | 2026-08-05 |
| #346 | Prevent stale regime data from silently masking a regime transition that happened mid-session | #260 | 2026-08-05 |
| #344 | Show the Data Quality grade on the Executive Score ring tooltip so operators know which component dropped the score | #260 | 2026-08-05 |
| #345 | Confirm the trend chip stays Stable — not Declining — when data quality runs don't exist yet | #260 | 2026-08-05 |
| #343 | Show the Data Quality grade on the Executive Score ring tooltip so operators know which component dropped the score | #259 | 2026-08-05 |
| #342 | Confirm the Executive Score drops visibly when a live data source fails during a session | #259 | 2026-08-05 |
| #339 | Stop the Agent Operations stats bar from showing 0 agents for 25 seconds after page load | #328 | 2026-08-05 |
| #341 | Confirm all four dashboard pages show the same agent count after an API server restart, not just when manually tested | #328 | 2026-08-05 |
| #340 | Make the diagnostics panel show the real active agent count, not zero | #328 | 2026-08-05 |
| #338 | Let operators export per-domain trend data as CSV so they can track quality degradation in their own tools | #258 | 2026-08-05 |
| #336 | Show the oldest-to-newest domain score trend so operators can see if a specific domain is getting worse over time, not just the latest value | #258 | 2026-08-05 |
| #337 | Confirm the domain sparkline grid still looks correct when a run is missing scores for one or more domains | #258 | 2026-08-05 |
| #334 | Stop repeated Opportunity Scan polls from spawning Python every time, not just concurrent ones | #327 | 2026-08-05 |
| #335 | Confirm all waiting callers see the failure when an in-flight Opportunity Scan errors mid-request | #327 | 2026-08-05 |
| #330 | Confirm the Executive Score neutral fallback survives a hot-reload without resetting to zero mid-session | #247 | 2026-08-05 |
| #329 | Confirm load_all stays fault-tolerant if any other section loader raises at startup | #247 | 2026-08-05 |
| #244 | Confirm the Paper Analytics tile in the Executive Dashboard still shows correctly after the API server restarts mid-session | #243 | 2026-07-31 |
| #240 | Confirm the Research Lab snapshot shows the correct grade after a live scan, not a stale cached value | #224 | 2026-07-31 |
| #241 | Prevent the Portfolio Performance snapshot from silently showing a wrong grade when the performance engine is unavailable | #224 | 2026-07-31 |
| #239 | Confirm the Pre-Open Advisory panel hides correctly outside pre-open hours, not just when hints are empty | #220 | 2026-07-31 |
| #238 | Show pre-open gap-down advisory hints alongside gap-ups so operators can act on both directions | #220 | 2026-07-31 |
| #237 | Confirm the Executive Dashboard summary endpoint still returns valid JSON when every upstream module times out simultaneously | #219 | 2026-07-31 |
| #236 | Apply _as_str coercion to string KPI fields in the shared_services snapshot functions used by non-executive pages | #219 | 2026-07-31 |
| #233 | Confirm the regime badges appear correctly after 5+ paper trades exist, not just on an empty dataset | #213 | 2026-07-31 |
| #235 | Prevent stale regime data from silently masking a regime transition that happened mid-session | #213 | 2026-07-31 |
| #234 | Show which strategies are viable for the current regime on the Trade Decisions page so operators choose the right one | #213 | 2026-07-31 |
| #231 | Confirm the AI Health score updates on the Executive Dashboard within 60 seconds after a new scan completes | #212 | 2026-07-31 |
| #232 | Show the AI Health score breakdown (accuracy, calibration, consistency) on hover so operators understand what drives the score | #212 | 2026-07-31 |
| #229 | Mark each trade entry and exit on the equity curve so operators can see which trades drove drawdowns | #228 | 2026-07-31 |
| #230 | Confirm the equity chart still renders correctly when the paper portfolio has exactly 1 or 2 data points | #228 | 2026-07-31 |
| #222 | Pre-warm the Research Lab snapshot cache during the post-scan pipeline so the cold yfinance fetch never blocks an operator's HTTP request | #216 | 2026-07-30 |
| #221 | Confirm the pre-open accuracy report shows real gap-prediction data after a morning cycle completes | #143 | 2026-07-30 |
| #210 | Add a P&L trend badge to the Portfolio sidebar entry so operators see session performance at a glance without opening the page | #159 | 2026-07-30 |
| #209 | Make the equity sparkline on the Portfolio page visible immediately by seeding it from the portfolio snapshot's equity history | #159 | 2026-07-30 |
| #208 | Confirm the Performance Snapshot shows accurate stats after paper trades, not zeros on a fresh portfolio | #159 | 2026-07-30 |
| #205 | Confirm PRE-OPEN ADVISORY hints appear when STRONG_GAP_UP data exists, and stay hidden when none qualify | #144 | 2026-07-30 |
| #207 | Track whether PRE-OPEN ADVISORY candidates confirmed as gap-ups after market open, to measure prediction accuracy | #144 | 2026-07-30 |
| #206 | Let operators dismiss individual PRE-OPEN ADVISORY hints they've already reviewed | #144 | 2026-07-30 |
| #203 | Prevent the macro score from showing stale data when VIX fetch fails and the cache has expired | #193 | 2026-07-30 |
| #204 | Make sure the Macro Intelligence tile never shows an error state on the Executive Dashboard when one sub-module is slow | #193 | 2026-07-30 |
| #202 | Confirm the VIX risk label on the Executive Dashboard tile changes colour when VIX crosses HIGH and EXTREME thresholds | #193 | 2026-07-30 |
| #182 | Confirm the readiness score also updates when auto-paper entries open, not only when positions close | #175 | 2026-07-29 |
| #184 | Prevent the exits/tick endpoint from publishing a readiness event when no positions exist to evaluate | #175 | 2026-07-29 |
| #183 | Show a live 'Last updated' timestamp on the Data Quality card so operators know the score is current | #175 | 2026-07-29 |
| #179 | Confirm accuracy session history shows on the Pre-Open Intelligence page after multiple trading days | #145 | 2026-07-29 |
| #180 | Prevent the 09:20 reconciliation from running when actual prices are all null and producing a misleading empty accuracy report | #145 | 2026-07-29 |
| #181 | Confirm the accuracy card refreshes automatically after market open without needing a page reload | #145 | 2026-07-29 |
| #178 | Keep the runtime-managed key exclusion list in one place so it can't drift between modules | #177 | 2026-07-29 |
| #170 | Confirm the rolling 30-day accuracy chart still updates correctly in the browser after the sliding-window refactor | #162 | 2026-07-29 |
| #171 | Warn operators on the Trade Decisions page when AI accuracy has been declining for the past 30 days | #162 | 2026-07-29 |
| #172 | Prevent the AI health score from silently returning stale data when the learning analysis is recomputed twice per request | #162 | 2026-07-29 |
| #168 | Confirm the performance cache clears itself when a new paper trade is recorded, not just after 30 seconds | #158 | 2026-07-29 |
| #169 | Confirm performance analytics still pass at 1,000 trades without the 100 ms guarantee degrading | #158 | 2026-07-29 |
| #166 | Warn operators when a stock's strategy has a poor track record in today's regime | #164 | 2026-07-29 |
| #167 | Persist the strategy×regime advisory panel across page refreshes so the panel is always visible, not just on first load | #164 | 2026-07-29 |
| #129 | Make sure a partial position exit immediately updates the sector exposure badge, not just the full-close | #125 | 2026-07-25 |
| #122 | Confirm the MARKET CLOSED badge disappears in the browser when the market reopens on Monday morning | #116 | 2026-07-25 |
| #123 | Catch a stale MARKET CLOSED badge persisting across pages when the market reopens | #116 | 2026-07-25 |
| #114 | Set production API URLs as environment variables so deployed connectivity is explicit, not inferred | #110 | 2026-07-25 |
| #112 | Fix pre-existing TypeScript errors in dashboard pages so tsc can catch real regressions | #110 | 2026-07-25 |
| #113 | Confirm CORS blocks non-Replit origins so a misconfiguration can't open the API to the public | #110 | 2026-07-25 |
| #108 | Confirm the config panel refreshes in the browser the moment an operator saves a limit, not after the next poll | #91 | 2026-07-25 |
| #109 | Make sure limit edits survive a hot-reload of the API server so operators don't lose mid-session overrides unexpectedly | #91 | 2026-07-25 |
| #107 | Prevent operators from seeing a stale snapshot for up to 15 seconds after the API server restarts | #90 | 2026-07-25 |
| #106 | Confirm the consolidated outage banner disappears in the browser when the API recovers, not just in unit tests | #90 | 2026-07-25 |
| #98 | Confirm the UNREACHABLE badge appears in the browser when the health API goes down, not just in source analysis | #80 | 2026-07-25 |
| #99 | Catch live position-row updates silently breaking if the snapshot polling config changes | #80 | 2026-07-25 |
| #60 | Confirm the badge disappears in the browser when positions close, not just in unit tests | #49 | 2026-07-25 |
| #61 | Make the exposure badge pulse or animate when a new CRITICAL breach appears so operators notice immediately | #49 | 2026-07-25 |
| #59 | Make sure the exposure badge updates immediately when the API returns fresh data, not after a full page reload | #48 | 2026-07-25 |
| #58 | Confirm the badge disappears in the browser when positions close, not just in unit tests | #48 | 2026-07-25 |
| #56 | Make it clear to operators why the Reopen button is missing on old discrepancies | #45 | 2026-07-25 |
| #57 | Confirm the Reopen cutoff is enforced on the server so a direct API call can't bypass it | #45 | 2026-07-25 |
| #55 | Prevent a discrepancy from being resolved while a reopen is still in flight | #44 | 2026-07-25 |
| #54 | Confirm the resolved section always shows the note from the most recent resolution, not a stale one | #44 | 2026-07-25 |
| #40 | Catch sector-level exposure warnings disappearing silently when positions close | #32 | 2026-07-25 |
| #37 | Show missed-reconciliation alerts on the Broker Execution page so operators see them in context | #22 | 2026-07-25 |
| #36 | Run the reconciliation probe automatically so operators don't have to call it manually | #22 | 2026-07-25 |
| #30 | Keep the sidebar badge accurate when discrepancies are resolved from any page | #20 | 2026-07-25 |
| #31 | Confirm the reconciliation badge stays hidden when there are no open issues | #20 | 2026-07-25 |
