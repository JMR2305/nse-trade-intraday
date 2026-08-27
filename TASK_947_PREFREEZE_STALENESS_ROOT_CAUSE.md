# Task 947 — Pre-freeze Staleness Root Cause

## Result

**Confirmed lifecycle defect; raw-provider timestamp subtype remains unproven.**

The natural 2026-08-27 session collected through 09:14 even though NSE order
collection closes at a system-selected point between 09:07 and 09:08.  The
shared NSE `lastUpdateTime` can legitimately stop advancing during order
matching and the silent transition.  The existing five-minute ingestion rule
then correctly classified each late row as stale, and the late batch replaced
the session's current collection state immediately before freeze.

This is a scheduler timing and phase-contract defect, not evidence that stale
data should be accepted.

## Durable evidence

| Observation | Evidence |
| --- | --- |
| 09:00:24 IST | 23 expected, returned, normalized, persisted, and live; `MATCH`. |
| 09:05 / 09:09 IST | Repeated natural collections remained exact and live. |
| 09:14:49 IST | 23 expected/returned/normalized/persisted, 0 live, 23 stale; `COVERAGE_INCOMPLETE`. |
| Failed batch | `collection-6bbe038e85644fb7a42a364966691b88`. |
| Prior verified pointer | `collection-867b53a6ab4b48a58ae02582c4861c7e`. |
| Freeze result | Withheld: frozen batch and freeze time were both null. |

The durable record therefore proves the 23/23-to-0/23 transition and correct
fail-closed behavior. It does not prove the exact raw NSE timestamp values:
they were parsed into freshness status but were not retained with the
collection evidence. It is consequently not possible to distinguish old,
missing, malformed, or future-dated provider timestamps after the fact.

## Why the timing explains the transition

The NSE official pre-open documentation states that the session runs from
09:00 to 09:15, order collection is randomly closed between the seventh and
eighth minute, order matching begins immediately afterward, and a silent
transition follows matching. Indicative equilibrium/opening price and
buy/sell quantities are disseminated in real time during order collection.

At the exact freshness boundary, a provider time of 09:07:00 is 299 seconds
old at 09:11:59 and 300 seconds old at 09:12:00. The application correctly
treats `age >= 300` as stale. A 09:14 collection can therefore turn an
otherwise legitimate static matching-phase timestamp into a failed batch.

## Corrective conclusion

Do not weaken the five-minute parser rule and do not resurrect an arbitrary
earlier verified batch. Instead, take the final certificate candidate only
from a naturally scheduled 09:08–09:12 IST collection that was fully live at
ingestion, then freeze that exact immutable batch unchanged at 09:15.

The original 2026-08-27 failure remains immutable and is not reclassified.