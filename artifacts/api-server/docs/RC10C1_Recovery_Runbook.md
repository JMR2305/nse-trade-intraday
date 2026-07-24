# RC-10C1 Recovery Runbook

**Document status:** Operational  
**Phase:** RC-10C1 Portfolio Core  
**Applicable module:** `src/portfolio/service.py`, `src/portfolio/state.py`, `src/portfolio/repositories/`

---

## 1. Recovery Overview

Portfolio recovery is the process of restoring authoritative portfolio state after a restart, crash, or planned downtime. The portfolio **must not accept new orders** until recovery is complete and reconciliation has verified consistency with the broker.

Recovery is initiated automatically on service startup via `PortfolioService.recover()`. It cannot be skipped.

---

## 2. Recovery Sequence

```
START
  │
  ▼
Step 1: Load Latest Valid Snapshot
  │  ├─ Query snapshot repository for most recent snapshot (by snapshotted_at DESC)
  │  ├─ Validate checksum
  │  ├─ If invalid: try next snapshot (see Section 4)
  │  └─ If no valid snapshot: start from initial state (cold start)
  │
  ▼
Step 2: Replay Subsequent Portfolio Events
  │  ├─ Load events with sequence > snapshot.version from event repository
  │  ├─ Sort by sequence (ascending, deterministic)
  │  ├─ Apply events one by one to in-memory state
  │  ├─ Skip events with already-seen idempotency keys (idempotent replay)
  │  └─ Verify final state.version matches last applied event sequence
  │
  ▼
Step 3: Cross-Check RC-7 Execution Records
  │  ├─ Query RC-7 for fills and orders since snapshot.snapshotted_at
  │  ├─ Compare against locally replayed fills
  │  ├─ Apply any RC-7 fills not yet in portfolio event ledger
  │  └─ Log discrepancies for reconciliation
  │
  ▼
Step 4: Reconcile Against RC-10D Broker Snapshot
  │  ├─ Request fresh broker snapshot via RC-10D
  │  ├─ Run reconciliation (dry_run=True first)
  │  ├─ If critical discrepancies: set status=DEGRADED, continue
  │  └─ If clean: set status=READY
  │
  ▼
Step 5: Set Readiness Gate
  │  ├─ PortfolioHealth.initialized = True
  │  ├─ PortfolioHealth.recovered = True
  │  ├─ PortfolioHealth.reconciled = True (if reconciliation passed)
  │  ├─ PortfolioHealth.readiness = True (only if status=READY)
  │  └─ Record STATE_RECOVERED event in ledger
  │
  ▼
READY (or DEGRADED if discrepancies remain)
```

---

## 3. Snapshot Integrity (Checksum Validation)

Every `PortfolioSnapshot` carries an optional `checksum` field. When present, it is validated before the snapshot is used for recovery.

### 3.1 Checksum Algorithm

```python
import hashlib
import json

def compute_checksum(snapshot: PortfolioSnapshot) -> str:
    """SHA-256 of the canonical JSON representation of the snapshot."""
    payload = snapshot.model_dump(exclude={"checksum"})
    canonical = json.dumps(payload, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

def validate_checksum(snapshot: PortfolioSnapshot) -> bool:
    if snapshot.checksum is None:
        return True  # No checksum present; trust the snapshot
    return snapshot.checksum == compute_checksum(snapshot)
```

### 3.2 Checksum Storage

Checksums are written to `PortfolioSnapshot.checksum` at snapshot creation time and persisted in the snapshot repository. They are not stored separately — they travel with the snapshot record.

### 3.3 Validation Timing

Checksum is validated:
1. When loading a snapshot for recovery (Step 1 above)
2. When receiving a snapshot from a remote node (DR scenario)
3. When performing a manual snapshot audit

Validation failures are logged with the snapshot ID and the computed vs stored checksum.

---

## 4. Corrupt Snapshot Handling

A snapshot is considered corrupt if:
- Checksum validation fails (`CorruptSnapshotError`)
- Pydantic model validation fails on load (malformed data)
- `version` field is inconsistent with the event ledger
- `snapshotted_at` is in the future or before portfolio initialization

### 4.1 Fallback Algorithm

```
Attempt to load snapshot N (most recent)
  ├─ Checksum OK → proceed to event replay
  └─ Checksum FAIL (CorruptSnapshotError)
       │
       └─ Attempt snapshot N-1
            ├─ Checksum OK → proceed (more events to replay, but safe)
            └─ Checksum FAIL
                 │
                 └─ Attempt snapshot N-2
                      ... (up to max_snapshot_fallback = 5)
                           │
                           └─ All corrupt → Cold Start
```

### 4.2 Cold Start

If no valid snapshot exists, recovery starts from `initial_capital` (from `PortfolioConfig`). The entire event ledger is replayed from sequence 1. This is safe but slow for large event histories; consider periodic snapshot compaction.

Cold start logs:
```
WARNING: No valid portfolio snapshot found. Starting cold recovery from event ledger.
WARNING: Cold start may take longer if event history is large.
```

### 4.3 Corrupt Snapshot Reporting

All corrupt snapshots are:
1. Flagged in the snapshot repository with `is_corrupt=True`
2. Never used for recovery (even if more recent than a valid snapshot)
3. Retained for forensic analysis — never deleted automatically
4. Reported in the `PortfolioHealth` failure_reason field

---

## 5. Idempotent Replay Guarantee

Event replay is idempotent by construction:

1. Every `PortfolioEvent` has a unique `idempotency_key` assigned at creation.
2. The event ledger maintains a set of applied idempotency keys.
3. During replay, each event's idempotency key is checked before application.
4. Duplicate keys are skipped with a `DEBUG` log — they are not errors during replay.
5. State transitions are deterministic: same events in the same sequence always produce the same state.

**Guarantee:** Replaying the same set of events twice produces the same final portfolio state as replaying them once.

**Out-of-order protection:** Events are always sorted by `sequence` (ledger-assigned monotonic integer) before replay. Wall-clock timestamps are not used for ordering.

**Version verification:** After replay, the state version is verified against the sequence number of the last applied event:

```python
assert state.version == last_event.sequence, (
    f"State version mismatch after replay: "
    f"state.version={state.version}, last_event.sequence={last_event.sequence}"
)
```

If this assertion fails, the recovery is aborted and the system enters `UNAVAILABLE` status.

---

## 6. Startup Readiness Gate

**No orders are accepted until `PortfolioHealth.readiness == True`.**

The readiness gate progresses through these states:

```
INITIALISING  →  RECOVERING  →  RECONCILING  →  READY
                                                     │
                                              (or DEGRADED if
                                               discrepancies remain)
```

| State | `readiness` | New orders accepted |
|-------|------------|---------------------|
| `INITIALISING` | `False` | **No** |
| `RECOVERING` | `False` | **No** |
| `RECONCILING` | `False` | **No** |
| `READY` | `True` | **Yes** |
| `DEGRADED` | `False` | **No** |
| `HALTED` | `False` | **No** |
| `UNAVAILABLE` | `False` | **No** |

Any pre-check call to `CapitalAllocator.evaluate()` when `readiness=False` raises `PortfolioNotReadyError` immediately, without evaluating other constraints.

---

## 7. DR (Disaster Recovery) Playbook

### 7.1 Planned Restart (Graceful)

```
1. Signal all new order requests to pause (via flag in PortfolioService)
2. Wait for in-flight RC-7 orders to complete or timeout (max 60s)
3. Create a snapshot via PortfolioService.create_snapshot()
4. Verify snapshot checksum
5. Shut down
6. Start new instance
7. Automatic recovery executes (Steps 1–5 in Section 2)
8. Verify PortfolioHealth.readiness == True
9. Resume order acceptance
```

### 7.2 Unplanned Crash

```
1. New instance starts
2. Automatic recovery executes
3. Snapshot from last successful snapshot_interval_s cycle is loaded
4. All events since snapshot are replayed from event ledger
5. RC-7 cross-check applied (fills since last snapshot)
6. Broker reconciliation performed
7. If DEGRADED: alert operator; investigation required
8. If READY: resume automatically
```

### 7.3 Database Failure

```
1. Portfolio enters UNAVAILABLE status
2. All new order requests rejected with PortfolioNotReadyError
3. In-flight orders continue via RC-7 and RC-10D (no portfolio dependency for execution)
4. On database recovery:
   a. Verify database consistency
   b. Run cold recovery or snapshot recovery
   c. Re-reconcile with broker
   d. Restore readiness
```

### 7.4 Broker Snapshot Unavailable

```
1. If RC-10D cannot fetch broker snapshot, reconciliation is skipped (not failed)
2. Portfolio status remains at last known state
3. broker_freshness_s increases; stale_broker_threshold_s triggers DEGRADED
4. On snapshot recovery:
   a. Reconciliation runs automatically
   b. Readiness restored if reconciliation passes
```

### 7.5 Recovery Time Objectives

| Scenario | Expected Recovery Time | Max Acceptable |
|----------|----------------------|----------------|
| Graceful restart | < 10 seconds | 60 seconds |
| Crash recovery (recent snapshot) | < 30 seconds | 120 seconds |
| Cold recovery (full event replay) | < 5 minutes | 15 minutes |
| DR failover | < 10 minutes | 30 minutes |

### 7.6 Pre-Market Startup Checklist

Before the NSE session opens (09:15 IST):

- [ ] Portfolio service started and `readiness == True`
- [ ] Last reconciliation within `reconciliation_interval_s`
- [ ] No unresolved CRITICAL discrepancies
- [ ] `PortfolioHealth.broker_freshness_s` within threshold
- [ ] `PortfolioHealth.state_freshness_s` within threshold
- [ ] `paper_mode == True` confirmed
- [ ] Event ledger accessible and writable
- [ ] Snapshot repository accessible and writable
- [ ] RC-7 execution records accessible for cross-check
- [ ] All metrics endpoints responding

If any item fails, do not accept strategy signals until resolved.
