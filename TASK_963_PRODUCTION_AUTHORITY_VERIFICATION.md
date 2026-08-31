# Task 963 Production Authority Verification

## Pre-deploy immutable baseline

Read-only production queries on 31 August 2026 confirmed:

- `CUSTOM_LOW_PRICE_SECTOR` has one production revision: ID 3/version 1
- Status: `ACTIVE`
- Effective from: `2026-08-31T03:30:00Z`
- Effective until: open
- Enabled members: `23`
- Exact-set hash: `22e5751f25686718f5572041834ce998b7c5ce9844d3b573bc3841749fe77016`
- The 31 August pin resolves to revision 3/version 1 with the same count/hash
- Active Phase 20 selector: `CUSTOM_LOW_PRICE_SECTOR`
- Historical failed session `preopen-2026-08-31-dee23c` remains `INITIALISING`
- That session still has no expected/persisted/frozen batch and only its original `init` phase

## Post-deploy proof

Pending explicit user approval to publish the reviewed Task 964 release.

After publishing, perform read-only checks only:

1. Production build identity exactly equals the approved Task 964 commit.
2. Revision 3/version 1 still has 23 members and the approved hash.
3. Runtime resolution returns revision 3 without `revision_not_found`.
4. Scanner readiness exposes the new machine-readable state.
5. Scheduler health is not permanently down because of stale revision status.
6. All consumers expose the same revision ID/version/hash.

No manual scan or Phase 5A invocation is authorized for this proof.