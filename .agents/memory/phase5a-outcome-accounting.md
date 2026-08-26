---
name: Phase 5A outcome accounting
description: Durable pre-open collection rule for custom-universe provider scope, missing data, and freeze proof.
---

For any Phase 5A custom-universe collection, use the full eligible NSE scope
and retain one immutable outcome for every expected symbol in the exact
collection batch. Outcomes explain provider presence, normalization, and
failure, but never become synthetic snapshot rows.

**Why:** A NIFTY-scoped request against a custom 23-symbol universe produced a
3/23 collection. Aggregate counts showed the batch was incomplete but could
not explain the 20 missing symbols because raw provider evidence was not
stored.

**How to apply:** Keep the provider response cache scoped by its query key;
persist collection outcomes transactionally with real snapshot candidates; and
require exact expected-set parity of both the outcome matrix and real live
snapshots before a batch can be verified or frozen. Liveness must be explicit
(`is_stale=false` and `source_status=LIVE`), not inferred from a missing field.
`NO_PREOPEN_DATA`,
normalization failure, duplicate, omission, or provider failure is observable
evidence but must remain fail-closed for certification.

After the active universe resolves, retain its original batch ID and write an
outcome matrix even when enrichment, serialization, or persistence processing
throws. A generic error-only batch breaks exact-batch auditability.

NSE `lastUpdateTime` is an Asia/Kolkata wall-clock timestamp; parsing it as UTC
can silently make stale rows appear live. Treat missing/invalid timestamps and
future timestamps, plus ages at or above five minutes, as stale.