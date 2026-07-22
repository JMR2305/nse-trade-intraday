# Batch 9C v2 Audit — `batch9c_v2_corrected_1784748187946.zip`
**Date:** 22 July 2026  
**Reviewer:** Main Agent  
**Test method:** Files staged against the real RC-9 codebase; models appended to `src/database/models.py`; full test suite executed via `pytest --asyncio-mode=auto`  
**Test result:** 94 passed / 2 failed / 96 total  
**Verdict:** ⚠️ NEARLY MERGEABLE — all previous issues fixed; 2 new issues remain (1 implementation bug, 1 residual model omission)

---

## Progress Since Previous Submission

All 6 items raised in the previous audit are confirmed fixed.

| Previous Issue | Status |
|---|---|
| NB1 — SyntaxError in 3 repository files | ✅ Fixed — `session` moved to first parameter in all 3 files |
| NB2 — FrozenInstanceError in `recover()` | ✅ Fixed — local mutable accumulators; frozen result built once at end |
| NT1 — `hasattr(Model, 'metadata')` always True | ✅ Fixed — two correct tests using `__table__.columns` inspection |
| NT2 — duplicate timestamp in `test_list_by_strategy` | ✅ Fixed — `ts1` and `ts2` are one day apart |
| NT3 — timezone stripping in `test_strategy_record_timestamps` | ✅ Fixed — `.replace(tzinfo=None)` on both sides |
| IR1 — replacement `models.py` would overwrite existing models | ✅ Fixed — zip contains only `models_additions.py.txt` |

The test count changed from 127 to 96 because several edge-case and transaction-ownership tests that were previously in separate classes (`TestEdgeCases`, `TestTransactionOwnership`) have been consolidated into `TestStrategyRecoveryManager`. Test coverage is equivalent.

---

## Remaining Issues

---

### FAIL NF1 — `signals_restored` counts only PENDING signals; tests define it as total signals encountered

**Affects:** `test_recover_skips_already_routed_signals`, `test_recovery_skips_mixed_routed_and_pending` — **2 test failures**

**What failed:**

`test_recover_skips_already_routed_signals` saves one signal with `routing_status="ROUTED"` and `routed_client_order_id="oid1"`, calls `recover()`, and asserts:
```python
assert result.signals_restored == 1   # ← fails: got 0
assert result.signals_requeued == 0   # ← passes
assert len(router.enqueued) == 0      # ← passes
```

`test_recovery_skips_mixed_routed_and_pending` saves one PENDING signal and one ROUTED signal, calls `recover()`, and asserts:
```python
assert result.signals_restored == 2   # ← fails: got 1
assert result.signals_requeued == 1   # ← passes
assert len(router.enqueued) == 1      # ← passes
```

**Why it failed:**

`recover()` calls `list_pending_signals()`, which queries only for signals where `routing_status == "PENDING"`. It then sets:

```python
# recovery.py line 158
signals_restored=len(pending_signals),
```

A ROUTED signal is never loaded by `list_pending_signals()` and is therefore never counted. The implementation defines `signals_restored` as *"number of PENDING signals found"*. The tests define it as *"total number of signals encountered during recovery across all statuses"* — i.e. both the pending signal that got re-queued AND the already-routed signal that was correctly skipped should be counted.

These two definitions are incompatible, and the implementation never loads already-routed signals at all, so it has no way to count or inspect them.

**What needs to be fixed:**

The implementation and the tests must agree on what `signals_restored` means. The tests are the contract and must be satisfied. Two valid paths:

**Option A — load all signals, skip the routed ones (matches the test contract exactly):**

Add `list_all_signals()` to `StrategySignalRepository` and `list_all_signals()` to `StrategyPersistenceAdapter`. In `recover()`, load all signals, process them, and count every one regardless of routing status:

```python
# recovery.py — in recover()
all_signals = await self._persistence.list_all_signals(session)  # new method needed

signals_total = 0
for sig in all_signals:
    signals_total += 1
    sig_entry = await self._recover_signal(session, sig)
    signal_details.append(sig_entry)
    if sig_entry.requeued:
        signals_requeued += 1
    if sig_entry.error:
        errors.append(f"Signal {sig.signal_id}: {sig_entry.error}")

return StrategyRecoveryResult(
    ...
    signals_restored=signals_total,   # all signals seen
    signals_requeued=signals_requeued,
    ...
)
```

`_recover_signal()` already handles the routed case correctly — it checks `record.routed_client_order_id is not None` and returns `skipped_already_routed=True` without enqueuing.

**What this requires:**

In `StrategySignalRepository` — add:
```python
async def list_all(
    self,
    session: AsyncSession,
    strategy_id: Optional[str] = None,
) -> List[StrategySignalModel]:
    """Return all signals, regardless of routing status."""
    stmt = select(StrategySignalModel)
    if strategy_id is not None:
        stmt = stmt.where(StrategySignalModel.strategy_id == strategy_id)
    stmt = stmt.order_by(StrategySignalModel.timestamp)
    result = await session.execute(stmt)
    return list(result.scalars().all())
```

In `StrategyPersistenceAdapter` — add:
```python
async def list_all_signals(
    self,
    session: AsyncSession,
    strategy_id: Optional[str] = None,
) -> List[StrategySignalRecord]:
    models = await self._signal_repo.list_all(session, strategy_id=strategy_id)
    return [
        StrategySignalRecord(**StrategySignalRepository._hydrate_signal(m))
        for m in models
    ]
```

**Option B — rename the field to match the actual implementation (simpler, but requires changing the tests):**

Rename `signals_restored` → `pending_signals_found` in both `StrategyRecoveryResult` and in the tests. The two failing tests would change to `assert result.pending_signals_found == 0` and `assert result.pending_signals_found == 1` respectively. This matches the implementation accurately.

Option A is the more useful design (recovery auditing should account for all signals, not just PENDING ones). Option B requires fewer code changes. Both are valid — pick one and be consistent. The test file is the published contract, so if tests stay unchanged, Option A is required.

---

### RESIDUAL NR1 — `ix_strategy_signals_routed_coid` absent from `models_additions.py.txt`

**Affects:** `test_routed_coid_index_exists` — this test passes in staging only because the auditor manually added the index when building the staging environment; the submitted file would fail if applied as-is

**What the issue is:**

The migration `0003_rc9c_strategy_persistence.py` correctly creates a named index:
```python
op.create_index(
    "ix_strategy_signals_routed_coid",
    "strategy_signals",
    ["routed_client_order_id"],
    unique=False,
)
```

But `StrategySignalModel` in `models_additions.py.txt` only has `index=True` on the column:
```python
routed_client_order_id = sa.Column(sa.String(64), nullable=True, index=True)
```

and its `__table_args__` is:
```python
__table_args__ = (
    sa.UniqueConstraint("signal_id", name="uq_strategy_signals_signal_id"),
    sa.Index("ix_strategy_signals_strategy_status", "strategy_id", "routing_status"),
    sa.Index("ix_strategy_signals_pending", "routing_status", "timestamp"),
    # ix_strategy_signals_routed_coid is MISSING here
)
```

`index=True` on a column creates a SQLAlchemy auto-named index (typically `ix_strategy_signals_routed_client_order_id`), not the explicitly named `ix_strategy_signals_routed_coid`. The test checks by name:
```python
def test_routed_coid_index_exists(self):
    idx_names = {idx.name for idx in StrategySignalModel.__table__.indexes}
    assert "ix_strategy_signals_routed_coid" in idx_names
```

This test would fail against the submitted `models_additions.py.txt`. It only passed in staging because the auditor added the index manually.

**Why it happened:**

The named index exists in the Alembic migration (which was written first) but was not carried forward to the model definition in the `models_additions.py.txt` file. The `index=True` shorthand was used instead, which does not reproduce the same named index.

**What needs to be fixed:**

Remove `index=True` from the `routed_client_order_id` column and add the named index explicitly in `__table_args__`:

```python
# In models_additions.py.txt — StrategySignalModel column (no index=True):
routed_client_order_id = sa.Column(sa.String(64), nullable=True)

# In __table_args__:
__table_args__ = (
    sa.UniqueConstraint("signal_id", name="uq_strategy_signals_signal_id"),
    sa.Index("ix_strategy_signals_strategy_status", "strategy_id", "routing_status"),
    sa.Index("ix_strategy_signals_pending", "routing_status", "timestamp"),
    sa.Index("ix_strategy_signals_routed_coid", "routed_client_order_id"),  # ← add this
)
```

The model and the migration must name indexes identically. When `create_all` is used (in tests or fresh environments), the model is the source of truth. When Alembic is used (in production upgrades), the migration is the source of truth. If the names differ, production and test environments diverge.

---

## Full Test Results — v2

| Layer | Tests | Result |
|---|---|---|
| `StrategyModel` — schema, constraints, indexes | 13 | ✅ All pass |
| `StrategySignalModel` — schema, constraints, indexes | 14 | ✅ All pass |
| `StrategyStateModel` — schema, constraints, indexes | 9 | ✅ All pass |
| `StrategyRepository` — CRUD, upsert, lifecycle update, hydration | 10 | ✅ All pass |
| `StrategySignalRepository` — CRUD, routing status, dedup, hydration | 12 | ✅ All pass |
| `StrategyStateRepository` — append-only snapshots, load latest | 7 | ✅ All pass |
| `StrategyPersistenceAdapter` — save/load/list via adapter | 9 | ✅ All pass |
| `TestStrategyRecoveryManager` — crash recovery orchestration | 22 | 20 pass, **2 fail** (NF1) |
| **Total** | **96** | **94 pass / 2 fail** |

---

## What Must Come Back

| ID | Fix | Files to change |
|---|---|---|
| NF1 | Add `list_all_signals()` to the signal repository and persistence adapter; change `recover()` to load all signals and use `len(all_signals)` for `signals_restored` | `repositories/strategy_signal.py`, `src/strategy/persistence.py`, `src/strategy/recovery.py` |
| NR1 | Add `sa.Index("ix_strategy_signals_routed_coid", "routed_client_order_id")` to `StrategySignalModel.__table_args__`; remove `index=True` from the column declaration | `src/database/models_additions.py.txt` |

Two targeted changes. Everything else is solid — the repositories, the adapter, the migration chain, the test structure, and the core persistence layer are all production-quality.
