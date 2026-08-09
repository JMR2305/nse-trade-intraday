# Phase 27E + 27F — Joint Final Verification

Date: 2026-08-09. Both phases are read-only, advisory-only additions on
top of the canonical stores. PAPER TRADING / RESEARCH ONLY.

## Scope delivered
- **27E Operator Analytics** (`/operator-analytics`): funnel, timing,
  rejection analysis (events vs reason occurrences separated), decision
  quality, risk posture, trends; evidence states OK / PARTIAL /
  SOURCE_UNAVAILABLE / VERIFIED_EMPTY with a sources-availability banner.
- **27F System Readiness** (`/system-readiness`): deterministic
  READY/WARNING/BLOCKED/UNKNOWN fold across 10 domains with per-check
  expected/actual/evidence/remediation, blocking flags, safety-mode
  verification, freshness table (existing thresholds only), KV-backed
  light history, and a read-only "Run readiness check" cache bypass.

## Test matrix
| Suite | Result |
|---|---|
| test_phase27_operator_analytics.py | 21 passed |
| test_phase27_readiness.py | 33 passed |
| trading-dashboard tsc --noEmit | clean |
| tsc -b lib/* + api-server | clean |

## Shared invariants verified across both phases
1. **No fabrication**: missing evidence is labelled (27E:
   SOURCE_UNAVAILABLE / VERIFIED_EMPTY; 27F: UNKNOWN) — never presented
   as healthy data.
2. **Fail-safe readiness**: a blocking check without evidence prevents
   READY; corrupted breaker state blocks; live-execution configuration
   blocks.
3. **Canonical sources only**: both read the phase20 ledger, canonical
   scan snapshot, phase26 validation stores, and cached session-manager
   probes; neither adds probes, thresholds, or writes to trading state.
4. **Route pattern**: 30s cache + single-flight per aggregate endpoint;
   frontend uses long apiJson timeouts.

## Live verification (weekend session)
Both pages render with correct environmental states: stale-scan warnings
(closed-budget exceeded — no scan since Friday), broker LOGIN_REQUIRED,
everything else READY/OK. History records appended on forced readiness
runs. Screenshots captured for both pages during their respective
verifications (see PHASE27E_VERIFICATION.md / PHASE27F_VERIFICATION.md).

Verdict: Phase 27E and 27F complete and verified.
