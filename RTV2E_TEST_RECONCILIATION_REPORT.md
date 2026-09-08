# RTV-2E — Pre-existing Test Expectation Reconciliation

**Date:** 2026-08-25 (IST)  
**Result:** PASS — test expectations reconciled without changing runtime safety

## Test 1 — Daily-session alert and heartbeat claims

| Item | Result |
| --- | --- |
| Root cause | The test used total mocked `kv_claim_once` call count as an alert assertion. The scheduler legitimately also claims a separate system-heartbeat key. |
| Classification | Stale, under-specified test expectation |
| Runtime behavior changed | No |

### Assertion change

- **Old assertion:** expected exactly one `kv_claim_once` call for the alert
  key.
- **New assertion:** confirms the expected
  `session_init_open_alert:<IST-date>` key was claimed and confirms a distinct
  `system_heartbeat:` claim can coexist.

Coverage is stronger, not weaker: the test still proves the critical alert is
emitted while additionally proving that unrelated scheduler deduplication does
not invalidate the alert assertion.

## Test 2 — Environment token authority

| Item | Result |
| --- | --- |
| Root cause | The test did not model the durable token authority. A reachable durable store with no valid record is an authoritative logout and must not fall back to an environment token. |
| Classification | Under-specified test fixture |
| Runtime behavior changed | No |

### Assertion and coverage change

The prior test assumed an environment-only token was always usable when it had
no timestamp. It now explicitly covers all three authority states:

1. an environment token remains supported when no durable authority is
   available;
2. an environment token without a timestamp is rejected when a reachable
   durable authority reports no active record;
3. a fresh timestamped environment token works when no durable authority is
   available.

This preserves fail-closed behavior for an authoritative durable logout while
retaining the documented legacy deployment-token path.

## Additional stale script expectation

The Phase 22 finalization script treated “Kite login required” as fallback
data. The implemented provider contract permits live-quality Yahoo data for
paper research when Kite is disconnected and blocks actual mock, fallback, or
unconfigured sources. The script now asserts the structured live-symbol
coverage rule and verifies that live Yahoo data is not misclassified as
fallback.

## Safety statement

No production runtime module, automatic-entry authority, broker behavior,
universe, ledger, portfolio, or deployment configuration was changed.
