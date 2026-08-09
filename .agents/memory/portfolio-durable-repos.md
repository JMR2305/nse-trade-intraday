---
name: Durable portfolio repositories
description: Architectural rules for Postgres-backed portfolio state (events/snapshots/reconciliations) and the bridge recovery-vs-reseed startup strategy
---
- Startup rule: recover from the latest valid persisted snapshot, then dry-run reconcile against the canonical phase20 ledger; any CRITICAL discrepancy discards the recovered state and re-seeds from the ledger with a fresh service.
- **Why:** the canonical ledger stays authoritative — recovery preserves event/reservation history but a stale book must never drive limit checks.
- Replay boundary rule: wall-clock timestamps are NOT a safe replay cursor (fills committed after a snapshot can carry older occurrence times); the durable serial id stored with the snapshot is the only valid cross-process cursor, because per-process ledger sequences restart at 1.
- Cursor attachment rule: attach the replay cursor in ONE central snapshot-save path so automatic saves (fills/initialise) carry it too — a cursor only on explicit snapshot calls silently reverts recovery to timestamp filtering. Replay must also restore reservation/release events, not just fills, or post-snapshot reservations vanish on restart.
- Retention rule: durable event rows may be pruned only when older than the audit window AND below the replay baseline of every snapshot that could still be recovered from (conservatively, the minimum cursor across recent snapshots — not just the newest); latest-report reads must be bounded, never full-history scans.
- Replay idempotency rule: restored snapshots must mark their reservations' event keys as applied, and reservation mutations must be idempotent by order id — a gap-pinned cursor legitimately replays this service's own events, which must never double-block capital.
- Hermeticity rule: any test that can reach the shared dev database must either disable persistence or isolate under a unique portfolio id with cleanup — otherwise the next real startup recovers a test book (the reconcile fallback catches it, but noisily).
- Reservation rule: snapshots must persist reservation identity (order_id → amount), not just blocked-cash totals — **Why:** restoring only totals strands capital: a post-restart release/fill can never consume the reservation.
