# Batch 9C Audit — Database Persistence Layer
**Date:** 21 July 2026  
**Reviewer:** Main Agent  
**Package contents:** 3 ORM models + 2 repository files (1 empty, 1 missing)  
**Verdict:** ❌ DO NOT MERGE — 5 blockers, 4 serious issues

---

## Files Delivered

| File | Lines | Status |
|---|---|---|
| `database/models/strategy.py` | 58 | Wrong path, wrong Base import |
| `database/models/strategy_signal.py` | 67 | Wrong path, `metadata` crash, wrong path |
| `database/models/strategy_state.py` | 59 | Wrong path, `metadata` crash, Numeric for ints |
| `database/repositories/strategy.py` | 159 | Wrong import path, `account_id` mismatch |
| `database/repositories/strategy_signal.py` | 0 | **EMPTY FILE** |
| `database/repositories/strategy_state.py` | — | **FILE DOES NOT EXIST** |

---

## BLOCKERS

### B1 — Wrong directory structure (all 5 files)
**Files:** All  
**Impact:** Import fails at startup

The deliverable ships to `database/models/strategy.py` etc., assuming a `database/models/` subdirectory with a `base.py`. The actual project has a **single flat file**: `src/database/models.py`. All models live in that one file. There is no `database/models/` package and no `database/models/base.py`.

```
# Deliverable assumes:
database/models/base.py          ← does not exist
database/models/strategy.py

# Actual project:
src/database/models.py           ← single file, all models here
src/database/connection.py       ← Base defined here
```

The three model files must be added as classes inside `src/database/models.py`, not as a separate package.

---

### B2 — Wrong Base import (all model files)
**Files:** `models/strategy.py`, `models/strategy_signal.py`, `models/strategy_state.py`  
**Impact:** `ImportError` at module load time

```python
# Deliverable:
from database.models.base import Base   # ← this module does not exist

# Correct:
from src.database.connection import Base  # ← declarative_base() lives here
```

Every existing model in `src/database/models.py` uses `from src.database.connection import Base`.

---

### B3 — `metadata` is a reserved SQLAlchemy attribute name (2 models)
**Files:** `models/strategy_signal.py` line 53, `models/strategy_state.py` line 41  
**Impact:** Hard crash at class definition time — `InvalidRequestError`

This was confirmed via live test:

```
sqlalchemy.exc.InvalidRequestError: Attribute name 'metadata' is reserved
when using the Declarative API.
```

Both models use `metadata = Column(JSON, ...)`. SQLAlchemy's `DeclarativeBase` reserves `metadata` as the class-level `MetaData` instance. Assigning a `Column` to that name raises an unrecoverable error before any migration or runtime code runs.

**Fix:** Rename to `extra_metadata` (matching `StrategyStateSnapshot.extra_metadata` in contracts) or `signal_metadata` / `extra_data` (matching `RiskStateModel.extra_data`).

---

### B4 — `strategy_signal.py` repository is empty (0 bytes)
**File:** `database/repositories/strategy_signal.py`  
**Impact:** Complete missing implementation

The file exists but contains zero bytes. No class, no imports, nothing. The `StrategySignalModel` has no working repository.

---

### B5 — `strategy_state` repository is missing entirely
**Impact:** Complete missing implementation

Three models were delivered but only one working repository (`strategy.py`). There is no repository for `StrategyStateModel`. The `strategy_state_snapshots` table cannot be read from or written to.

---

## SERIOUS

### S1 — `account_id` column has no source in `StrategyConfig`
**File:** `models/strategy.py` line 37, `repositories/strategy.py` line 30  
**Impact:** Repository `save()` cannot be called from any coordinator or runtime code

`StrategyModel` defines `account_id = Column(String(64), nullable=False)`. The `StrategyRepository.save()` method requires `account_id: str` as a parameter. But the domain contract `StrategyConfig` has **no `account_id` field**:

```python
class StrategyConfig(BaseModel, frozen=True):
    strategy_id: str
    strategy_type: str
    name: str
    # ...no account_id...
```

There is no place in the coordinator or runtime that has an `account_id` to pass. The NOT NULL constraint means the save will fail unless `account_id` is explicitly added to `StrategyConfig` (a contract change) or the column is made nullable / removed.

---

### S2 — Duplicate unique constraint on `strategy_id` (StrategyModel)
**File:** `models/strategy.py` lines 34, 55  
**Impact:** PostgreSQL creates two separate unique indexes on the same column — wasteful and a migration headache

```python
strategy_id = Column(String(64), nullable=False, unique=True, index=True)  # constraint #1
...
__table_args__ = (
    UniqueConstraint("strategy_id", name="uq_strategies_strategy_id"),  # constraint #2
    Index("ix_strategies_account_lifecycle", "account_id", "lifecycle_state"),
    ...
)
```

`unique=True` on the column already creates a unique constraint. The explicit `UniqueConstraint` in `__table_args__` creates a second one. Same problem appears in `StrategySignalModel` for `signal_id`.

**Fix:** Remove `unique=True` from the column definition (keep only the named `UniqueConstraint` in `__table_args__` for clarity), or remove the `UniqueConstraint` from `__table_args__` (keep only `unique=True`). Do not have both.

---

### S3 — `Numeric(20, 0)` for integer counters in `StrategyStateModel`
**File:** `models/strategy_state.py` lines 37–40  
**Impact:** Returns `Decimal` objects instead of `int` — type coercion required everywhere downstream

```python
emitted_signal_count = Column(Numeric(20, 0), nullable=False, default=0)
routed_signal_count  = Column(Numeric(20, 0), nullable=False, default=0)
rejected_signal_count = Column(Numeric(20, 0), nullable=False, default=0)
fill_count           = Column(Numeric(20, 0), nullable=False, default=0)
```

Every existing model in this project uses `Integer` or `BigInteger` for integer counters. `Numeric` is for monetary values (prices, P&L). Using it for counts means SQLAlchemy returns `Decimal("5")` instead of `5`, which will fail comparisons and arithmetic throughout the codebase.

`StrategyStateSnapshot.filled_today` and `rejected_today` in contracts are typed `int`. Hydration code will need explicit `int(model.emitted_signal_count)` casts, or the column type should be `Integer`.

**Fix:** Replace all four with `Column(Integer, nullable=False, default=0)` (or `BigInteger` if overflow is a concern).

---

### S4 — Duplicate unique constraint on `signal_id` (StrategySignalModel)
**File:** `models/strategy_signal.py` lines 35, 56  

Same problem as S2. `signal_id = Column(String(64), nullable=False, unique=True, index=True)` plus `UniqueConstraint("signal_id", name="uq_strategy_signals_signal_id")` creates two PostgreSQL unique constraints on the same column.

---

## MODERATE

### M1 — `signal_id` type mismatch: `UUID` in contracts, `String(64)` in model
**File:** `models/strategy_signal.py` line 35  

`Signal.signal_id` is `UUID` (from `uuid.UUID`). The model stores it as `String(64)`. This works only if the caller explicitly converts: `str(signal.signal_id)`. Neither the empty repository nor any helper function documents or enforces this conversion. The `RiskStateModel` uses `PGUUID(as_uuid=True)` for UUID columns — this should too, or the conversion must be explicit in the repository.

---

### M2 — `instrument_token` stored as `String(32)` — may truncate
**File:** `models/strategy_signal.py` line 38  

`Signal.instrument_token` in contracts is `str`. Storing as `String(32)` is internally consistent with the domain contract, but 32 characters may be tight if instrument tokens ever include exchange prefixes (`NSE:RELIANCE-EQ`). The project convention everywhere else (`Order`, `Fill`, `Position`, `MinuteBar`) is `BigInteger` for Zerodha numeric tokens. If `Signal.instrument_token` is meant to be a numeric Zerodha token (like `408065`), it should be `BigInteger` matching the rest of the schema.

---

### M3 — Unused import in `StrategyRepository`
**File:** `repositories/strategy.py` line 4  

```python
from decimal import Decimal  # never referenced anywhere in the file
```

---

## MINOR

### N1 — `StrategyRepository.to_dict()` deviates from project hydration pattern
**File:** `repositories/strategy.py` lines 145–159  

`RiskStateRepository` (the canonical RC-8 pattern) exposes `_hydrate_snapshot(model) -> RiskStateSnapshot` returning a domain object. `StrategyRepository.to_dict()` returns a plain `Dict[str, Any]`. There is no hydration method that reconstructs a `StrategyConfig` from an ORM row — which is what recovery would need. The `to_dict()` helper is fine as a secondary serializer, but the primary hydration path to a domain object is missing.

---

### N2 — No `__init__.py` provided for new package (if structure is corrected)
If the decision is to create a `database/models/` package rather than add to the flat file, `__init__.py` files are required for `database/models/` and any sub-packages. Neither is included.

---

## Summary Table

| ID | Severity | File | Description |
|---|---|---|---|
| B1 | **Blocker** | All | Wrong directory structure — must go into `src/database/models.py` |
| B2 | **Blocker** | All models | Wrong Base import path |
| B3 | **Blocker** | signal, state | `metadata` column name crashes SQLAlchemy (`InvalidRequestError`) |
| B4 | **Blocker** | repo/signal | Repository file is 0 bytes |
| B5 | **Blocker** | — | `strategy_state` repository missing entirely |
| S1 | Serious | model/strategy, repo/strategy | `account_id` NOT NULL has no source in `StrategyConfig` |
| S2 | Serious | model/strategy | Duplicate unique constraint on `strategy_id` |
| S3 | Serious | model/state | `Numeric(20,0)` for int counters returns `Decimal` not `int` |
| S4 | Serious | model/signal | Duplicate unique constraint on `signal_id` |
| M1 | Moderate | model/signal | `signal_id` UUID↔String(64) mismatch — no conversion helper |
| M2 | Moderate | model/signal | `instrument_token String(32)` — may truncate; inconsistent with DB convention |
| M3 | Moderate | repo/strategy | Unused `Decimal` import |
| N1 | Minor | repo/strategy | `to_dict()` returns dict, not domain object — hydration path missing |
| N2 | Minor | — | Missing `__init__.py` for new package (if package structure is chosen) |

---

## What Needs to Come Back

A corrected Batch 9C must deliver:

1. **Three model classes added to `src/database/models.py`** (not a separate package), importing from `src.database.connection import Base`
2. **`metadata` column renamed** in both `StrategySignalModel` and `StrategyStateModel` (e.g. `extra_data`)
3. **`account_id` decision**: either add `account_id` to `StrategyConfig`, or make it nullable, or remove it from the model
4. **Duplicate unique constraints removed** — pick one mechanism per column
5. **`Numeric(20, 0)` → `Integer`** for all counter columns
6. **`StrategySignalRepository` fully implemented** (currently empty)
7. **`StrategyStateRepository` created** (currently missing)
8. **Tests** for all three repositories following the existing test conventions
