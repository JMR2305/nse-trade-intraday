# RTV-2A — Pre-open persistence root cause

**Date:** 2026-08-24  
**Scope:** Phase 5A pre-open intelligence persistence and observation safety  
**Safety posture:** Paper-only; automatic entries remain disabled; automatic exits remain enabled; live broker execution remains disabled.

## Observed RTV-2 evidence

The RTV-2 production evidence recorded an `init` event for session
`preopen-2026-08-24-226281`, but did not record readiness, collection, or
freeze completion. Therefore the session did not provide durable
provider/snapshot parity and cannot certify a pre-open lifecycle.

## Root-cause chain

The source review identified multiple independent gaps that could turn an
incomplete lifecycle into an apparently completed one:

1. Phase progress was held in a process-local JSON sidecar. A restart or
   autoscale handoff could lose the completed-phase truth.
2. Database persistence failures were swallowed by the database wrapper, so
   collection could report success without proving that its snapshots landed.
3. Collection did not require `provider_collected_count ==
   persisted_count` from the same collection batch.
4. Freeze could create rankings/watchlists without proving a complete,
   durable collection for the session.
5. The once-only tick marked a phase complete even when its work failed,
   suppressing the retry that would be needed to recover safely.
6. The old phase windows overlapped at 09:00 and 09:15, making boundary
   ownership ambiguous.
7. Reconciliation windows were time-gated but did not require durable
   completion of their preceding phase, so a blocked freeze could otherwise
   have been followed by a misleading reconciled session.
8. A forced API scan passed `origin=` before `force`, while the Python command
   parser originally only recognized force in the first argument position.
9. Freeze verified one session's collection counts but selected snapshots by
   trading date, allowing a different same-day session's rows to be mixed in.
10. A single session may retry collection several times; selecting newest rows
    per symbol could mix a later partial batch with symbols from an earlier
    batch despite only the later batch having a verified count proof.
11. The initial batch-column migration covered the new table definition but
    omitted the additive upgrade for an existing snapshot table before creating
    its dependent batch index.

The observed session alone does not prove which one of those gaps interrupted
the 2026-08-24 production lifecycle. It proves that durable lifecycle evidence
was insufficient. RTV-2A removes the paths that allowed incomplete evidence to
be treated as success.

## Corrective controls

- Phase state is now durable per session and can be recovered after a
  sidecar/process loss.
- Session creation, collection persistence, phase writes, and frozen status
  writes report success/failure explicitly.
- A collection is successful only when the provider count equals the
  committed snapshot count for that same batch.
- No-data, provider-unavailable, persistence-failed, and retryable error
  outcomes are distinct.
- Freeze is blocked and recorded when collection parity or durable snapshots
  are absent.
- Windows are end-exclusive: 09:00 belongs to collection and 09:15 belongs
  to freeze.
- A failed phase remains retryable rather than being marked complete.
- Reconciliation requires a durable `FROZEN` session, and the 09:30 enrichment
  requires a durable `RECONCILED` session. The tick independently blocks both
  phases unless their predecessor is durably recorded.
- A sidecar can no longer unlock a phase by itself; database phase state is
  reloaded on every tick and outranks the local cache.
- API-triggered scans send `force` before their `origin=API_TRIGGERED` marker;
  force parsing is also order-independent.
- Freeze, reconciliation, frozen watchlists, and 09:30 reconciliation updates
  are session-scoped. They cannot read or mutate another session's same-day
  evidence.
- Every collection attempt has an immutable durable batch ID. A successful
  parity proof atomically records its verified-batch pointer; freeze verifies
  exact row, snapshot-ID, and symbol counts from that batch before pinning it
  for all downstream reconciliation.
- The snapshot batch-column upgrade runs additively before its batch index, so
  existing production tables remain available through the rollout.

## Certification impact

This repair does not reconstruct a missing pre-open session. The next natural
scheduled session must satisfy the validation gate in
`RTV2A_NEXT_SESSION_VALIDATION_GATE.md`.