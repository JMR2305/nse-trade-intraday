#   Live NSE Session Validation Report

## Initial checkpoint verdict

**G. LIVE SESSION INCOMPLETE — CONTINUE OBSERVATION**

This is an observation-only result, not a failure of the already verified RTV-1H
baseline. The production clock was `2026-08-24T03:46:12.307799+05:30` at capture; NSE was
`CLOSED` and the API reported pre-open at `09:00 IST`, open at
`09:15 IST`, with the scheduler's next phase `init at 08:43 IST`. The natural
session had not begun, so the live-session requirements cannot be certified.

No scan, pre-open job, 5A/5B/5C lifecycle, order operation, portfolio mutation,
universe mutation, bootstrap enablement, or safety-setting change was performed.

## Task 1 — pre-session baseline: PASS

### Runtime

- environment: `production`
- git_commit: `4392f278ae25562f168f970e2b694f8c3d249d5c`
- build_id: `apexquant-4392f278ae25`
- deployment_id: `0d018179-abe0-42c2-a554-dbb19d11341f`
- runtime timestamp: `2026-08-23T22:16:12.492Z`

### Kite

- credentials_present: `True`
- token_status: `VALID`
- token_stored: `True`
- connected: `True`
- authenticated: `true` by connected, valid-token, and successful live probe state
- login_required: `False`
- token_expired: `False`
- mock session: `False`

### Universe

- mode: `CUSTOM_LOW_PRICE_SECTOR`
- active count: `23`
- active symbols: `BANKBARODA,BANKINDIA,CANBK,FEDERALBNK,IDFCFIRSTB,KTKBANK,MAHABANK,PNB,UNIONBANK,COALINDIA,GAIL,HUDCO,IRCON,IRFC,MRPL,NBCC,NMDC,NTPC,PFC,RECLTD,RVNL,SAIL,WIPRO`
- sectors: `BANK=9 / INFRA=13 / IT=1`
- valid mappings: `23/23`
- missing mappings: `0`
- duplicate mappings: `0`

### Portfolio

- initial capital: ₹100,000.00
- cash: ₹99,721.26
- realized P&L: ₹-278.74
- unrealized P&L: ₹0.00
- equity: ₹99,721.26
- open positions: `0`
- both portfolio endpoints match these values.

### Safety

- automatic paper entries: `False`
- bootstrap: `False`
- automatic exits: `True`
- live broker orders: `False`

## Tasks 2–5 — pre-open, 5B, and 5C: NOT OBSERVED

The scheduler reports `active=false`, `session_id=null`, `phases_done=[]`, and
next phase `init at 08:43 IST`. The current-day pre-open status has no updated
session data. The read-only report endpoint exposes only the historical session
`preopen-2026-08-21-0d3df7`, trading date 2026-08-21, status `COLLECTING`.

The provider health probe says `NSE Official — 50 symbols, data age 0s`, but this
is a provider-health probe and not evidence that today's scheduled Phase 5A
lifecycle ran. Today's rankings, sectors, and snapshots are empty. Therefore:

- 5A provider/persistence parity: `NOT_OBSERVED`
- 5B lifecycle and candidate counts: `NOT_OBSERVED`
- 5C lifecycle and signal counts: `NOT_OBSERVED`
- No `COMPLETE` or `NO_CANDIDATES` state was manufactured.

## Task 6 — first canonical scan: NOT OBSERVED

Today's scan history contains closed-market `SYSTEM_HEARTBEAT` / `NON_MARKET`
records only, with no scan ID and no requested or received symbol count. The
latest canonical scan remains historical: `76e307f291e7` at
`2026-08-21T10:02:20Z`, with 50 symbols. It was not rewritten.

Required checks—current universe mode, requested 23, received 23, exact symbol
list, scheduler source, command, provider, errors, and recommendations—remain
pending. See `RTV2_FIRST_CANONICAL_SCAN.csv`.

## Task 7 — legacy 50-symbol scheduled scan: D, unable to determine

Classification at this pre-session checkpoint: **D. unable to determine**.
There is no new canonical scan yet, so it is not possible to prove that the
future scheduled path will be 23-symbol only. The historical 50-symbol scan is
allowed history. No path was disabled during this observation.

## Tasks 8–9 — live quote and analytical provenance: pending

RTV1H's off-session direct quote baseline remains 23/23 `kite_live`, with zero
fallback and zero synthetic results. It is preserved in `RTV2_LIVE_KITE_PROVENANCE.csv`
with `verification_scope=RTV1H off-session read-only baseline`.

That baseline must not be relabeled as the first canonical live scan. For RTV-2,
all 23 current-scan quote timestamps, ages, live provenance, reliability, and
historical OHLCV distinctions remain **NOT_OBSERVED** until the natural scan runs.

## Task 10 — readiness transition: pending

Pre-session readiness was:

- service_ready: `True`
- data_ready: `False`
- session_fresh: `False`
- trading_data_ready: `False`
- current active universe count: `23`
- valid tokens: `23`
- missing tokens: `0`
- latest scan: `76e307f291e7 / 2026-08-21T10:02:20Z`

No after-scan transition exists. `trading_data_ready` must remain false until a
fresh 23-symbol canonical scan and every required live-data gate pass.

## Tasks 11–12 — portfolio and historical ledger baseline: PASS

The current baseline remains reconciled at ₹100,000 capital, ₹99,721.26
cash/equity, ₹-278.74 realized P&L, ₹0 unrealized P&L, and zero open positions.
The ledger contains `6` CLOSED rows with total historical realized
P&L ₹-278.74. No ledger rows were modified.

During-session invariance is not yet certifiable because the session has not
started; the next observation must compare both portfolio endpoints again.

## Task 13 — safety flags: PASS at baseline; after-session checkpoint pending

Beginning-of-session values match the controlling baseline. The controlled paper
entry status endpoint remains HTTP `404` (disabled/unavailable).
No broker order endpoint was called. After-pre-open and after-first-scan safety
checkpoints remain pending because those lifecycles have not run.

## Task 14 — error and log monitoring

The inspected API request window returned successful read-only responses for
identity, health, Kite status, universe, portfolio, scheduler, pre-open, scan
history, cadence, pipeline, ledger, and positions. No current-session Kite,
quote, scan, pre-open, database, readiness, synthetic-data, or duplicate-scan
failure was observed because no live session has started.

The runtime log also contains two earlier `Backtest queue tick timed out after
30 s` warnings before this RTV-2 baseline. They are non-market support-job
warnings, not evidence of a live-session scan or pre-open failure, and were not
cleared.

## Current state

- pre-open lifecycle: not started
- first canonical scan: not observed
- new scheduled legacy 50-symbol scan: not determinable before the session
- direct off-session quote baseline: 23/23 Kite live, 0 fallback, 0 synthetic
- `trading_data_ready`: false, fail-closed
- automatic paper entries: disabled
- bootstrap: disabled
- live broker orders: disabled

See the other five RTV-2 artifacts for structured evidence. Continue only with
natural scheduled observation at the next checkpoint; do not manually trigger
anything.


---

## Continuation checkpoint — 2026-08-24 natural-session observation

## Final verdict after continuation

**B. PRE-OPEN FAILURE — LIVE-SESSION PASS NOT CERTIFIABLE**

The scheduled production pre-open session was created (`preopen-2026-08-24-226281`;
created `2026-08-24T03:14:55.448638+00:00`), and its scheduler progressed through
`collect` and `freeze`. However, after that window its durable session remained
`INITIALISING`, with `symbol_count=None`,
`valid_count=None`, `stale_count=None`,
and no persisted current-day snapshot. This does not meet Phase 5A
provider-collected/persisted-count parity. The production pre-open lifecycle is
therefore a **PRE-OPEN 5A FAILURE**.

A second, independent boundary prevents live-session certification: during this
observation, `GET /api/live-data/recommendations` was used under the assumption
it served a stored canonical snapshot. Source verification immediately after
showed that route calls `getP7Scan(false)`, which, when the market is OPEN and
its cache is empty, invokes `spawnP7Scan(["phase7_scan"])`. The resulting scan
`fb88f7199f27` at `2026-08-24T03:50:49Z` must be recorded as **non-certifying** and must
not be called a natural scheduled scan. No further production observations or
writes were performed after this was established.

### Non-certifying scan evidence retained for audit

The scan output itself used `CUSTOM_LOW_PRICE_SECTOR`, contained exactly 23
symbols matching the RTV1H active universe, and reported:

- 23/23 `kite_live_ltp` current and execution price sources;
- 23/23 reliable quotes;
- zero fallback and zero synthetic execution sources;
- historical indicators/OHLCV from `yfinance_daily_bars`;
- zero symbol errors; and
- no paper orders.

These facts are audit evidence only. They do **not** satisfy the requirement for
the first naturally scheduled canonical scan or the post-natural-scan readiness
transition.

### Remaining fields deliberately not claimed

- Phase 5B was not certified from a durable production lifecycle result.
- Phase 5C was not certified from a durable production lifecycle result.
- No new scheduled 50-symbol-path classification is possible from the invalid
  observation boundary; classification remains **D. unable to determine**.
- No post-natural-scan readiness transition, portfolio/ledger comparison, or
  safety recheck was performed after the stop condition.
- Automatic entries, bootstrap, and live broker orders were not enabled; no
  broker order operation, portfolio reset, universe change, or ledger mutation
  was performed.

The current RTV-2 run must not be promoted to verdict A. Any future validation
must use scheduler-emitted durable scan/state evidence only and must avoid
endpoints that invoke `getP7Scan` during market-open cache misses.
