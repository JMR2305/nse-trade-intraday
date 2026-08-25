# RTV-3 — Restricted Natural NSE Session Certification

**Certification date:** 2026-08-25 (Asia/Kolkata)  
**Target:** Production only  
**Observation mode:** Read-only  
**Final verdict:** **B. PHASE 5A PERSISTENCE FAILURE**

## Why certification stopped

The production baseline was captured at `2026-08-25T00:52:01 IST`, before the
next NSE open at `09:15 IST`. No naturally scheduled current-session Phase 5A,
5B, 5C, or canonical scan evidence was available. The procedure explicitly
prohibits manual scans, manual lifecycle triggers, retries, and simulated
evidence, so certification stopped without attempting any of them.

The latest durable canonical scan was:

- scan ID: `a6e6166567be`
- timestamp: `2026-08-24T15:07:05 IST`
- origin: `SCHEDULED`
- universe: `CUSTOM_LOW_PRICE_SECTOR`
- symbols: 23
- current-session freshness: `false`

This prior scheduled scan is recorded as baseline context only and is not
counted as the RTV‑3 natural-session scan.

## Task 1 — Production pre-session baseline

| Field | Observed value |
| --- | --- |
| Environment | production |
| Git commit | `2e54e5e2f23f8ac5df86c9ec97aceeb3c8426832` |
| Build ID | `apexquant-2e54e5e2f23f` |
| Deployment ID | `0d018179-abe0-42c2-a554-dbb19d11341f` |
| Active universe | `CUSTOM_LOW_PRICE_SECTOR` |
| Active count | 23 |
| Kite mappings | 23/23 |
| Kite token state | stored, valid, unexpired, connected |
| Auto paper entries | `false` |
| Entry confirmation | `null` / absent |
| Bootstrap | `false` |
| Auto exits | `true` |
| Execution mode | `PAPER_TRADING` |
| Live broker orders | disabled |
| Daily broker orders | 0 |
| Initial capital | ₹100,000.00 |
| Cash/equity | ₹99,721.26 |
| Realized P&L | −₹278.74 |
| Unrealized P&L | ₹0.00 |
| Open positions | 0 |
| Exit-pending positions | 0 |
| Historical closed ledger rows | 6 |

## Natural-session evidence status

| Required area | Status | Evidence |
| --- | --- | --- |
| Durable Phase 5A session | Not observed | Session had not opened |
| Durable phase state | Not observed | Session had not opened |
| Immutable collection batch | Not observed | No current-session batch ID |
| Provider/persisted parity | Not observed | No current-session collection |
| Freeze after parity | Not observed | No current-session freeze |
| 5B / 5C | Not observed | No current-session lifecycle |
| Canonical scheduled scan | Not observed | Prior scan was stale for this session |
| 23 current Kite execution-grade quotes | Not proven | Current quote timestamp fields unavailable |
| Readiness transition | Not observed | No before/after natural-session pair |
| Observation GET purity | Not run as certification sequence | No natural-session state to compare |
| Automatic-entry safety | Baseline confirmed | Entries false, confirmation absent |
| Paper-trade safety | Baseline confirmed | No new trade in baseline |
| Portfolio/ledger parity | Baseline confirmed | `/api/portfolio` and snapshot matched |

## Production read-only observations

- Market state: `CLOSED`; next transition reported as `market_open` at
  `2026-08-25T09:15:00+05:30`.
- Service readiness: `true`.
- Data readiness: `true`.
- Trading-data readiness: `false`.
- Latest scan origin: `SCHEDULED`, but not fresh for the current session.
- Active symbols unavailable: 0 in the stored prior scan.
- Fallback symbols: 0 in the stored prior scan.
- Synthetic symbols: 0 in the stored prior scan.
- Current Kite quote timestamp freshness: not proven; latest timestamp was
  `null` and all 23 symbols were listed as having invalid live quote
  timestamps in the readiness response.

## Prohibited actions respected

No automatic entries, bootstrap, broker order, manual scan, lifecycle trigger,
portfolio reset, ledger modification, universe change, strategy change, or
threshold change was performed.

## Certification decision

This is an incomplete-session record, not a pass and not a fabricated failure.
The natural-session gate remains closed until one real scheduled NSE session
supplies all required evidence.

## Continuation checkpoint — 2026-08-25 natural session

At `2026-08-25T09:09:28 IST`, the production scheduler had created the current
day Phase 5A session:

- session ID: `preopen-2026-08-25-9b8340`
- lifecycle status: `COLLECTED`
- collection source: `SCHEDULED`
- provider status: `LIVE`
- collection started: `2026-08-25T09:09:34.507633+05:30`
- collection completed: `2026-08-25T09:09:34.507633+05:30`
- immutable collection batch: `collection-6073abbd096c44e7b4e4b51a205696ba`
- provider-collected count: **10**
- persisted count: **10**
- failed count: 0
- persistence status: `MATCH`

The counts match each other, but they do not satisfy the required
`CUSTOM_LOW_PRICE_SECTOR` active-universe count of 23. This is a Phase 5A
coverage/persistence failure: **10/23**, not 23/23.

The procedure therefore stopped immediately. Freeze, reconciliation,
enrichment, 5B, 5C, and the first certifying scheduled scan were not accepted
or triggered. No manual retry was performed.

### Exact failure context

- The durable Phase 5A record reported `symbol_count=10` and
  `provider_collected_count=10`.
- The production readiness baseline still reported active universe count 23,
  with 23 valid Kite mappings.
- No current-session canonical scan existed at the failure checkpoint.
- The current market state was `PRE_OPEN`; automatic paper entry remained
  blocked.

The final verdict is **B. PHASE 5A PERSISTENCE FAILURE**, not a natural-session
certification. The original baseline remains preserved above.
