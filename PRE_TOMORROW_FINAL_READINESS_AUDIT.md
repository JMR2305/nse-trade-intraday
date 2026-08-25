# Pre-Tomorrow Final Readiness Audit — Read Only

**Observed:** 2026-08-25, approximately 16:20 IST  
**Production:** `https://nse-trade-intraday.replit.app`  
**Method:** Production `GET` requests and a rendered-page observation only. No
scan, pre-open collection, refresh, replay, retry, login, settings, universe,
portfolio, ledger, entry, bootstrap, broker, or order mutation was made.

## Final classification

**C. NOT READY — READINESS AUTHORITY ISSUE**

Most operating controls are healthy: the configured custom universe has 23
active symbols and 23 unique Kite mappings; safety remains paper-only; and the
canonical portfolio/ledger remains unchanged. However, the Phase 5A pre-open
status surface still records a 10-symbol scheduled collection for the preserved
historical session and omits the required exact-coverage fields. It cannot be
used as evidence for the next-session certification, and it does not establish
that the next natural pre-open run will produce the required 23-symbol durable
proof.

No retry or corrective action was attempted. The next natural session must
either produce the complete evidence defined in `RTV3A_NEXT_NATURAL_SESSION_GATE.md`
or fail closed.

## 1. Production identity — PASS

| Check | Observed |
| --- | --- |
| Environment | `production` |
| Current commit | `cafc2c18a99fc6e0affe61afb9fac29c3c3251ee` |
| Build ID | `apexquant-cafc2c18a99f` |
| Deployment ID | `0d018179-abe0-42c2-a554-dbb19d11341f` |
| Published build | Successful |

This is a post-RTV-3D release. The local Git object for the deployed commit is
present and identifies it as the August 25 pre-open accuracy-report release.
The rendered Mission Control page displayed the same UI and API build IDs with
`MATCH`; it did not show the former stale `UI apexquant-v1.0.0` identity.

## 2. Observability status

| Area | Result | Evidence |
| --- | --- | --- |
| Build identity | PASS | Rendered Mission Control shows separate UI/API build IDs, both `apexquant-cafc2c18a99f`, with `MATCH`. |
| Scanner coverage denominator | PASS | `/api/live-data/coverage` reports `CUSTOM_LOW_PRICE_SECTOR`, expected/minimum/requested/coverage all `23`, and no missing symbols. |
| Current-price provenance card | OBSERVABILITY ISSUE | The rendered card did not falsely claim Kite LTP: it showed `Awaiting current scan provenance` and `UNKNOWN`. The read-only API simultaneously reported Kite connected and Yahoo Finance as the current quote provider, so the card did not yet surface that source/connection state in this after-close observation. |

The card observation is non-trading UI observability only. It is not the
readiness-authority blocker in the final classification.

## 3. Readiness authority — PASS for canonical scans; FAIL for Phase 5A proof

### Canonical live-data readiness

| Requirement | Observed | Result |
| --- | ---: | --- |
| Active universe | `CUSTOM_LOW_PRICE_SECTOR` | PASS |
| Expected symbols | 23 | PASS |
| Requested symbols | 23 | PASS |
| Coverage | 23 | PASS |
| Missing symbols | 0 | PASS |
| Minimum expected symbols | 23 | PASS |
| Legacy 50-symbol threshold | Not present | PASS |
| Latest canonical scan origin | `SCHEDULED` | PASS |
| Latest canonical scan symbol count | 23 | PASS |

The market was closed. Accordingly, stale cached quote timestamps and
`trading_data_ready=false` were not treated as a live-session readiness
failure. `/api/live-data/health-v2` correctly identified Yahoo Finance
(`yfinance`) as the quote provider and did not permit stale cache timestamps
to be treated as fresh live Kite quotes.

### Phase 5A pre-open authority

The current pre-open status payload is not certifying evidence:

| Field | Observed | Required next-session proof |
| --- | ---: | ---: |
| Visible session | `preopen-2026-08-25-9b8340` | A new future session |
| Source | `SCHEDULED` | `SCHEDULED` |
| Symbol count | 10 | 23 |
| Provider-collected count | 10 | 23 |
| Persisted count | 10 | 23 |
| Expected count | `null` | 23 |
| Normalized count | `null` | 23 |
| Missing/duplicate/malformed/unexpected | `null` | 0 each |
| Collection coverage | `null` | Exact expected and normalized symbol lists |
| Persistence status | `MATCH` | `MATCH` plus exact 23-symbol proof |

Although the scheduler reported a different runtime session identifier
(`preopen-2026-08-25-b0ccc0`), the exposed durable session/freeze/reconcile
evidence remained the 10-symbol historical record above. Per the natural
session gate, null counts and a 10/10 batch are a fail condition, not partial
success. This record is preserved and must not be retried, replayed, or
relabelled as Task #930 evidence.

## 4. Universe and mappings — PASS with mapping-age warning

| Check | Observed |
| --- | ---: |
| Active symbols | 23 |
| Inactive candidates | `IOB`, `UCOBANK`, `RELIANCE` |
| Complete mappings | 23/23 |
| Valid non-empty instrument tokens | 23 |
| Duplicate active tokens | 0 |
| Invalid active mappings | 0 |
| Active-symbol set | Exact 23-symbol durable custom set |

The mapping cache is two days old and the dashboard marks a metadata refresh
as required. No refresh was performed. The mappings remain complete and unique
for this audit; their age is an observability warning to retain for the next
session, not a reason to change data during a read-only check.

## 5. Kite read-only health — PASS

- Credentials present, token stored, and token status `VALID`.
- Token expired: `false`; daily login required: `false`.
- Read-only authenticated connection: `CONNECTED`; mock mode: `false`.
- Live broker order placement: `false`.
- The provider explicitly remains read-only until separately enabled; no login
  or token refresh was performed.

## 6. Safety settings — PASS

| Requirement | Observed |
| --- | --- |
| Automatic paper entries | `false` |
| Entry confirmation | `null` |
| Bootstrap paper mode | `false` |
| Automatic paper exits | `true` |
| Controlled entry status | `DISABLED` |
| Controlled execution allowed | `false` |
| Execution mode | `PAPER_TRADING` |
| Live broker order placement | `false` |
| Orders today | 0 |

No enabled entry or live-execution path was observed.

## 7. Portfolio and ledger parity — PASS

| Check | Portfolio | Snapshot |
| --- | ---: | ---: |
| Source | `phase20_ledger` | `phase20_ledger` |
| Contract | `phase20-ledger-v1` | `phase20-ledger-v1` |
| Initial capital | ₹100,000.00 | ₹100,000.00 |
| Cash | ₹99,721.26 | ₹99,721.26 |
| Equity | ₹99,721.26 | ₹99,721.26 |
| Realized P&L | −₹278.74 | −₹278.74 |
| Unrealized P&L | ₹0.00 | ₹0.00 |
| Open positions | 0 | 0 |

The ledger contains six closed historical rows, with zero `OPEN` and zero
`EXIT_PENDING` rows. No unexplained order was observed.

## 8. Manual-scan provenance — NON-BLOCKING OPEN ISSUE

The prior scan remains visible exactly as historical evidence:

| Field | Observed |
| --- | --- |
| Scan ID | `e1ded4dfba2e` |
| Started/completed | 2026-08-25 13:56:35–13:57:03 IST |
| Job type | `MANUAL_SCAN` |
| Source | `MANUAL` |
| Requested symbols | 23 |
| Entry/execution eligible | `false` / `false` |

The scanned history response exposes no actor, endpoint, request provenance, or
approval record for this row, and the notification response did not supply one.
It remains an open provenance issue for Task #929. It does not convert into
Phase 5A evidence and did not create an order; it is not the reason this audit
is classified not ready.

## 9. Scheduler health — PASS with the Phase 5A authority exception above

- Scheduler health: `HEALTHY`; current state `IDLE` because the market is
  closed.
- Last trigger: `SCHEDULED`; missed count: 0; last error: `null`.
- No active scan lock or stuck job was reported.
- No bootstrap, entry, broker, retry, or replay action was requested by this
  audit.

The scheduler-health pass does not override the separate Phase 5A requirement
for a future exact 23-symbol durable batch.

## 10. Task #930 next-natural-session gate

Do not run a manual collection, scan, retry, or replay to make this pass. At
the next naturally scheduled NSE pre-open session, certification can proceed
only if one new `SCHEDULED` batch proves all of the following:

```text
expected_count = provider_collected_count = persisted_count = 23
provider_returned_count >= 23
normalized symbols = exact durable 23-symbol set
missing = duplicate = malformed = unexpected = failed = 0
persistence_status = MATCH
23 distinct snapshot IDs and 23 distinct expected symbols
verified batch pointer before freeze, with freeze reading that same batch
new SCHEDULED canonical scan covering 23 symbols
paper-only safety and portfolio/ledger parity unchanged
```

Any null coverage field, 10-symbol collection, manual trigger, failed status,
or set mismatch must stop certification and be documented without retry.

## Audit boundary

This document is not Task #930 certification evidence. It records a read-only
precondition audit and preserves the existing historical Phase 5A failure
evidence unchanged.