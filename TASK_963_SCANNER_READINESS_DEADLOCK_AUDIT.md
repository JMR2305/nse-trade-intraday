# Task 963 Scanner Readiness Deadlock Audit

## Fix

The scheduler now launches independent single-flight lanes:

- Scheduled market scan
- Phase 5A pre-open intelligence
- Phase 5B pre-open validation
- Phase 5C signal validation
- Durable email alert queue
- Push delivery queue

A running market scan cannot suppress later minute ticks for the advisory lanes. A second market scan cannot start until the first child actually exits.

## Slow-scan handling

After five minutes, Node emits a `scan.slow` lifecycle event and warning. It does not kill the Python child, release the scan lane, or start overlapping transactional work. This preserves legitimate 7–22 minute cold-cache fallback and paper position management.

## Readiness states

The read-only coverage probe now distinguishes:

- `durable_authority_unavailable`
- `scan_metadata_unavailable`
- `no_current_version_scan`
- `stale_or_different_pinned_revision`
- `incomplete_current_scan`
- `healthy_current_scan`

Metadata-store failure is fail-closed (`success=false`) and is never mislabeled as proof that no scan exists.

No readiness probe triggers a scan.