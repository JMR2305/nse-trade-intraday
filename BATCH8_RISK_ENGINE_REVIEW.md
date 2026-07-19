# BATCH 8 RISK ENGINE — PRODUCTION INTEGRATION REVIEW
**Review Date:** 19 July 2026  
**Reviewer:** Main Agent (RC-7 Integration Review)  
**Reviewed Against:** RC-7 Execution Engine  
**Artifact:** `batch8_risk_engine_1784499617689.zip`

---

## Executive Summary

The Batch 8 Risk Engine is a well-structured, thoughtfully designed addition to the platform. The architecture is clean, the domain contracts are solid, the rule layer is deterministic, and the intent behind every module is sound. However, the submission contains **3 critical production blockers** that make the current build non-deployable as-is. An additional **5 major issues** must be resolved before merge. **9 of 111 self-submitted unit tests fail**, including tests for the kill switch — the most safety-critical component of the entire engine.

The RC-7 execution regression suite passes in full (336/336). Batch 8 does not break any existing code.

---

## Test Results

### RC-7 Regression Suite
```
artifacts/api-server/src/python/tests/unit/
    336 passed in 1.74s   ✅  FULL PASS — zero regressions
```

### Batch 8 Own Test Suite
```
tests/unit/risk/
    102 passed
      9 FAILED
   111 total     ❌  BLOCKED
```

#### Failing Tests

| Test | Root Cause |
|---|---|
| `test_kill_switch_blocks_all` | `RiskViolation(check_type="KILL_SWITCH")` → Pydantic ValidationError |
| `test_evaluate_order_active_blocks_all` | Same |
| `test_evaluate_order_risk_reducing_allowed` | Same |
| `test_evaluate_order_risk_reducing_short` | Same |
| `test_throttle` | `DuplicateOrderRule` class-level state pollutes between tests |
| `test_duplicate_order` | Same (cross-test state contamination) |
| `test_portfolio_heat` | `PortfolioHeatLimit` defaults to CRITICAL → BLOCK, but post-trade checks semantically require WARN |
| `test_turnover_velocity_exceeded` | `TurnoverVelocityLimit` defaults to CRITICAL → same root cause |
| `test_reset_daily` | `reset_daily()` does not clear kill switch state; test expects `False` |

---

## Section 1 — Architecture

**Score: 8.5 / 10**

### What is correct
- Clean `src/risk/` package with no imports from `src/execution/`. Dependency direction is correct: the Risk Engine is a consumer of execution types, never a dependency of them.
- Duck-typed order/position access (`isinstance(order, dict)` / `getattr(order, ...)`) correctly decouples the risk engine from the execution engine's frozen Pydantic types. This is the right pattern given the constraint that Batch 8 cannot import from execution.
- `RiskEngine` sits above `RiskState`, `KillSwitch`, and the rule layer — clean vertical layering within the package.
- `RULE_REGISTRY` + `RiskRule` Protocol is the correct pattern for extensible, pluggable rules.
- Persistence adapter wraps the engine without modifying it — mirrors the RC-7 persistence adapter pattern exactly.
- No circular imports. `contracts.py` has no intra-package imports (pure domain layer). `rules.py` only imports from `contracts.py`. `state.py` only imports from `contracts.py`. `engine.py` imports from `rules`, `state`, `kill_switch`. `persistence.py` imports from `engine` and `contracts`.

### Issues
- **[CRITICAL-3]** `database/models/risk_state.py` defines its own `Base` via `declarative_base()` instead of importing the shared `Base` from `database/models/base.py`. This makes `RiskStateModel` invisible to the project-wide schema setup. `Base.metadata.create_all()` from the execution layer will never create `risk_state_snapshots`.
- The `post_trade_check` design allows `BLOCK` as a valid return action (because limits default to CRITICAL severity). Post-trade "blocking" is semantically wrong — the fill already happened and the position already changed. The engine should either (a) enforce a maximum action of `WARN` for post-trade checks, or (b) require post-trade limits to use WARNING severity. The current code produces `BLOCK` for concentration violations, which the caller has no way to act on.
- `RULE_REGISTRY` is a module-level singleton with mutable rule instances. This is fine for production (single process) but makes test isolation require explicit `engine.reset()` calls between tests, which the test fixtures do not do.

---

## Section 2 — Compatibility with RC-7

**Score: 9.5 / 10**

RC-7 regression suite: **336/336 passing**. Zero regressions confirmed.

### What is correct
- Zero imports from `src/execution/`. No risk of circular dependencies or tight coupling.
- `RiskCheckContext.order: Optional[Any]` accepts both `dict` and `ExecutionOrder` — compatible with both RC-7's domain types and plain dicts.
- The `RiskEngine.record_fill()` signature matches what `PositionEngineResult` provides: `realized_pnl`, `turnover`, `current_equity`.
- `RiskDecision` and `RiskAction` form a clean interface that can be checked by any caller before passing an order to the execution engine.
- No modifications to any RC-7 module, ORM model, or repository.

### Issues
- None at the compatibility level beyond the `Base` isolation issue (which is a deployment concern, not a runtime compatibility concern).

---

## Section 3 — Code Quality

**Score: 7.0 / 10**

### Strengths
- Consistent use of `Decimal` for all monetary values — no floats anywhere in the arithmetic chain.
- Pydantic `frozen=True` on all domain contracts — correct.
- `@validator` coercions ensure `Decimal` is enforced even when callers pass strings or ints.
- Docstrings on all public classes and methods. Module-level docstrings explain purpose clearly.
- `__all__` in `__init__.py` is complete and correct.
- `from __future__ import annotations` used consistently.

### Issues
- **No logging anywhere in the risk package.** No `import logging`, no `logger = logging.getLogger(__name__)`, no log statements for kill switch activations, FATAL violations, or throttle triggers. A risk engine that silently blocks, warns, and halts trading in production with zero observability is a severe operational problem.
- `_determine_action()` uses string comparison `v.severity.value == "FATAL"` instead of the enum `v.severity == RiskSeverity.FATAL`. Works due to `str, Enum` but bypasses the point of typed enums and is inconsistent with the rest of the codebase.
- `_limit_to_check_type()` builds a fresh `dict` on every call (every pre-trade limit evaluation). Should be a module-level constant.
- `_build_throttle_key()` is a private method on `MessageThrottleRule` but is accessed from `RiskEngine._record_message_throttle()` — cross-class private method access. Should be extracted to a module-level function or the recording path redesigned.
- `datetime.utcnow()` used throughout — deprecated in Python 3.12. Produces 243 deprecation warnings during the test run. All callsites should use `datetime.now(timezone.utc)`.
- `RiskCheckContext.order: Optional[Any]` — intentional for decoupling, but should carry a docstring comment: `# Accepts ExecutionOrder (RC-7 frozen Pydantic) or dict; duck-typed access in all rules`.

---

## Section 4 — Risk Logic

**Score: 7.5 / 10**

### Strengths
- Pre-trade / post-trade separation is clearly defined and enforced in the engine.
- Kill switch is evaluated first, before any other rule — correct safety priority.
- Message throttle is recorded before throttle limit evaluation — prevents an off-by-one where the current order escapes the throttle window.
- `DailyLossLimitRule` correctly distinguishes warning threshold (WARNING severity) from the hard limit (FATAL severity).
- `DrawdownRule` mirrors the same dual-threshold pattern.
- `PositionLimitRule` projects the post-fill quantity (`current_qty + side_multiplier * order_qty`) correctly for both LONG and SHORT.
- `SelfTradeRule._would_cross()` logic is correct for both BUY-crosses-SELL and SELL-crosses-BUY.
- `TriggerStateTracker`-equivalent logic is not needed here (that's the execution engine's concern). Risk engine correctly operates on current positions, not order triggers.

### Critical Issues

#### **[CRITICAL-1] `kill_switch.py:135` — `check_type="KILL_SWITCH"` is not in `RiskCheckType` enum**

```python
# kill_switch.py line 134-140 (BROKEN)
return RiskViolation(
    check_type="KILL_SWITCH",   # ← NOT a valid RiskCheckType value
    severity=RiskSeverity.FATAL,
    message=f"Kill switch active: {self._reason}. All new orders blocked.",
    rule_id="kill_switch",
    ...
)
```

Confirmed at runtime:
```
pydantic.ValidationError: 1 validation error for RiskViolation
check_type
  Input should be 'ORDER_SIZE', 'PRICE_TOLERANCE', ... or 'TURNOVER_VELOCITY'
```

**Impact:** `KillSwitch.evaluate_order()` raises `ValidationError` whenever the kill switch is active. The kill switch feature is entirely non-functional. 4 unit tests fail because of this single defect.

**Fix required:**
```python
# contracts.py — add to RiskCheckType
class RiskCheckType(str, Enum):
    ...
    KILL_SWITCH = "KILL_SWITCH"   # ← ADD THIS

# kill_switch.py — replace string literal
return RiskViolation(
    check_type=RiskCheckType.KILL_SWITCH,   # ← USE ENUM
    ...
)
```

### Major Risk Logic Issues

#### **[MAJOR-4] Post-trade checks can return `BLOCK` — semantically wrong**

`PortfolioHeatLimit` and `TurnoverVelocityLimit` both default to `severity=RiskSeverity.CRITICAL`. `_determine_action()` maps CRITICAL → `RiskAction.BLOCK`. But `post_trade_check` is called after a fill has already been processed — blocking at this point has no meaning because the position change is permanent.

The engine docstring says "post-trade checks typically produce WARN-level decisions" — but no code enforces this. The result is that `test_portfolio_heat` and `test_turnover_velocity_exceeded` expect `WARN` but receive `BLOCK`, causing 2 test failures.

**Fix required** (choose one):
- Option A: Cap post-trade action at `WARN` in `post_trade_check()`.
- Option B: Default severity for `PortfolioHeatLimit`, `DrawdownLimit`, `TurnoverVelocityLimit` to `RiskSeverity.WARNING`.
- Option C: Document in tests that post-trade limits must use WARNING severity and add a guard.

#### **[MAJOR-6] `reset_daily()` does not reset kill switch — test asserts it does**

```python
# state.py reset_daily() — does NOT clear kill switch
async def reset_daily(self, initial_equity: Decimal = Decimal("0")) -> None:
    async with self._lock:
        self.daily_realized_pnl = Decimal("0")
        self.daily_turnover = Decimal("0")
        self.peak_equity = initial_equity
        self.message_counts.clear()
        # kill_switch_active is NOT reset here

# test_state.py test_reset_daily — asserts it IS cleared (WRONG EXPECTATION)
await state.activate_kill_switch("Test")
await state.reset_daily(initial_equity=Decimal("100000"))
assert state.kill_switch_active is False  # ← FAILS
```

**Design decision required:** For production safety, kill switch should **not** be automatically cleared by a daily reset. It should require explicit `deactivate_kill_switch()` with actor attribution. The test has the wrong expectation. Fix the test, not the code.

However, if the intent is that a new trading day starts completely clean (paper trading context), then `reset_daily()` should also clear the kill switch — but this must be documented as an explicit design decision because it creates a gap: an automatic FATAL risk event (daily loss limit breached) that triggered the kill switch would be silently cleared at day reset without any human review.

**Recommended fix:** Remove the `assert state.kill_switch_active is False` line from the test. Add a separate test `test_reset_daily_does_not_clear_kill_switch`.

---

## Section 5 — Persistence

**Score: 4.0 / 10**

The persistence layer has three compounding issues that make it non-functional in production as delivered.

### **[CRITICAL-2] `RiskStateModel` column named `metadata` collides with SQLAlchemy reserved attribute**

```python
# database/models/risk_state.py line 50 — BROKEN
metadata = Column(JSONB, nullable=False, default=dict)
```

Confirmed at runtime:
```
sqlalchemy.exc.InvalidRequestError: 
  Attribute name 'metadata' is reserved when using the Declarative API.
```

`metadata` is a class attribute of every SQLAlchemy `Table`. Shadowing it crashes the ORM mapper at import time. **The entire ORM model is non-importable.**

**Fix:**
```python
extra_metadata = Column(JSONB, nullable=False, default=dict)
# or
model_metadata = Column(JSONB, nullable=False, default=dict)
```

### **[CRITICAL-3] `RiskStateModel` uses a local isolated `Base` instead of the shared project `Base`**

```python
# database/models/risk_state.py lines 15-21 — WRONG
from sqlalchemy.orm import declarative_base
# "For Batch 8 standalone, we define it locally for clarity"
Base = declarative_base()
```

**Impact:** `risk_state_snapshots` is in a different `MetaData` object than all other project tables. When the main application calls `Base.metadata.create_all(engine)` using the project's shared `Base` (from `database/models/base.py`), the `risk_state_snapshots` table is **never created**. The persistence layer will silently fail with `UndefinedTable` errors at runtime.

**Fix:**
```python
# database/models/risk_state.py
from database.models.base import Base   # ← Use shared project Base
```

### **[CRITICAL-4] `__table_args__` uses `postgresql_indexes` — invalid SQLAlchemy syntax, crashes at runtime**

```python
# database/models/risk_state.py lines 52-56 — BROKEN
__table_args__ = (
    {"postgresql_indexes": [
        {"name": "ix_risk_state_account_timestamp", ...}
    ]}
)
```

Confirmed at runtime:
```
sqlalchemy.exc.ArgumentError: Argument 'postgresql_indexes' is not accepted 
  by dialect 'postgresql' on behalf of <class 'sqlalchemy.sql.schema.Table'>
```

`postgresql_indexes` is not a valid SQLAlchemy `__table_args__` key. SQLAlchemy uses `Index()` objects.

**Fix:**
```python
from sqlalchemy import Index

__table_args__ = (
    Index(
        "ix_risk_state_account_timestamp",
        "account_id",
        "snapshot_timestamp",
    ),
)
```

### **[MAJOR-5] `RiskEnginePersistenceAdapter._persist_state()` is an explicit no-op**

```python
# persistence.py lines 105-115 — DOES NOTHING
async def _persist_state(self, account_id: Optional[str]) -> None:
    # We need a session to persist, but we don't have one here.
    # ...
    pass
```

The adapter is named `RiskEnginePersistenceAdapter` and all its public methods call `_persist_state()`, but `_persist_state` intentionally does nothing. The docstring says "actual persistence happens via explicit save calls from the service layer" — but no service layer is included in Batch 8.

Additionally, the account_id extraction is broken: `pre_trade_check` and `post_trade_check` use `kwargs.get("account_id")`, but `account_id` is a positional argument in the typical call signature. Confirmed:

```
Calls to _persist_state: [None]
account_id extracted correctly: False
```

This means even if `_persist_state` had a real implementation, it would never run with a valid account_id when called positionally.

**Fix required:**
1. Implement real persistence: the adapter must accept and propagate a session.
2. Fix account_id extraction: use `args[0] if args else kwargs.get("account_id")`.
3. Document explicitly in the class docstring that this is a "stub" if the service layer is out of scope for Batch 8.

### Repository — What is correct
- `RiskStateRepository` follows the session-injection pattern correctly — no commits.
- `_hydrate_snapshot()` correctly converts ORM numeric columns to `Decimal(str(...))`.
- `load_latest()` uses `ORDER BY snapshot_timestamp DESC LIMIT 1` — correct.
- `save()` implements upsert-by-select — matches RC-7 repository pattern.

---

## Section 6 — Performance

**Score: 8.0 / 10**

### Strengths
- Per-account `asyncio.Lock` in `RiskState` — correct granularity, no global lock contention.
- `RiskEngine._lock` protects only account registration — minimal critical section.
- Rules are stateless (with one exception below) — no per-rule locking required.
- `load_latest()` query has a `LIMIT 1` — does not scan full history.
- `BarBuilder` and market data pipeline are untouched.

### Issues

#### **[MAJOR-7] `DuplicateOrderRule._seen_orders` is a class-level variable (shared global state)**

```python
class DuplicateOrderRule:
    # Class-level variable — shared across ALL instances
    _seen_orders: Dict[str, List[tuple]] = {}
```

Confirmed:
```
Class-level shared state (BUG): True
r2 sees r1 data: True
```

**Impacts:**
1. **Test pollution:** State persists across tests between test runs (causes `test_throttle` and `test_duplicate_order` failures when run together — the `DuplicateOrderRule` instance in `RULE_REGISTRY` retains state from previous tests).
2. **Multi-instance safety:** Creating a second `DuplicateOrderRule` for testing or configuration would share state with the registry instance.
3. **Broken "stateless evaluators" contract:** The module docstring explicitly states "Rules are stateless evaluators." This rule is not stateless.

The module-level `RULE_REGISTRY` singleton means there is only one `DuplicateOrderRule` instance in production (which is fine), but the class-level `_seen_orders` makes the class non-instantiable safely in any other context.

**Fix:**
```python
class DuplicateOrderRule:
    def __init__(self):
        self._seen_orders: Dict[str, List[tuple]] = {}   # ← Instance variable
```

#### `_limit_to_check_type()` allocates a new dict on every call

Every call to `pre_trade_check` iterates all limits and calls `_limit_to_check_type()` for each, allocating a fresh 11-entry dict. Minor for small limit sets; add as a constant at class level.

#### `SelfTradeRule` is O(N×M) — N new orders × M open orders

For accounts with hundreds of open orders, this is a linear scan per open order per new order. Acceptable for paper trading; document the complexity for production scaling discussions.

#### `DuplicateOrderRule._seen_orders` cleanup is O(N) per call

The window-expiry cleanup at lines 493-496 is a linear scan of all entries per account. For high-frequency scenarios with large windows, this accumulates. A `collections.deque` with `maxlen` would be O(1).

---

## Section 7 — Testing

**Score: 6.5 / 10**

### Strengths
- 111 tests covering all 11 rule types, the kill switch, state management, and the engine.
- Fixtures (`engine`, `sample_limits`, `base_context`, `base_state`) are clean and composable.
- Positive and negative cases for all rules: pass, fail, disabled, no-order, wrong instrument.
- Concurrent access test (`test_concurrent_access`) validates asyncio lock safety — good.
- `test_from_snapshot` validates round-trip state serialisation.

### Failures (9 total)

1. **4 kill switch tests** — fail due to `check_type="KILL_SWITCH"` not in enum (**CRITICAL-1**)
2. **2 throttle/duplicate tests** — fail due to cross-test `DuplicateOrderRule` class-level state pollution (**MAJOR-7**)
3. **2 post-trade severity tests** — fail due to CRITICAL default severity producing BLOCK not WARN (**MAJOR-4**)
4. **1 reset_daily test** — fails due to wrong expectation on kill switch survival (**MAJOR-6**)

### Missing Test Coverage
- `RiskEnginePersistenceAdapter` — no tests at all (the adapter's `pre_trade_check`, `post_trade_check`, `record_fill`, `activate/deactivate_kill_switch`, `restore_state` are completely untested)
- `RiskStateRepository` — no tests (would require mock `AsyncSession`)
- `RiskStateModel` — cannot be instantiated due to `metadata` column crash; no tests exist
- `DuplicateOrderRule` cross-account isolation — no test verifying account A's dedup does not affect account B
- `KillSwitchAlreadyActiveError` / `KillSwitchNotActiveError` — defined but never raised and never tested
- Emergency stop idempotency — no test for activating an already-active kill switch
- Post-trade FATAL drawdown → kill switch auto-activation (not implemented — `post_trade_check` explicitly does NOT auto-activate the kill switch, but `DrawdownRule` returns FATAL)

---

## Section 8 — Complete Issue Register

### Critical Issues (must fix before merge)

| ID | Location | Issue | Impact |
|---|---|---|---|
| CRITICAL-1 | `kill_switch.py:135` | `check_type="KILL_SWITCH"` not in `RiskCheckType` enum → `ValidationError` at runtime | Kill switch is completely non-functional. 4 tests fail. |
| CRITICAL-2 | `database/models/risk_state.py:50` | Column named `metadata` reserved by SQLAlchemy Declarative API → `InvalidRequestError` at import | ORM model cannot be instantiated. Entire persistence layer is non-importable. |
| CRITICAL-3 | `database/models/risk_state.py:21` | Local `Base = declarative_base()` isolates model from project shared `Base` | `risk_state_snapshots` is never created by `Base.metadata.create_all()`. Silent production failure. |
| CRITICAL-4 | `database/models/risk_state.py:52-56` | `postgresql_indexes` is not valid SQLAlchemy `__table_args__` syntax → `ArgumentError` | Composite index is never created; model crashes on load. |

### Major Issues (must fix before merge)

| ID | Location | Issue | Impact |
|---|---|---|---|
| MAJOR-4 | `engine.py:262`, rule defaults | Post-trade checks can return `BLOCK` (CRITICAL severity default) — semantically incorrect | 2 test failures; callers have no meaningful action on a post-trade BLOCK. |
| MAJOR-5 | `persistence.py:105-115`, `:43` | `_persist_state()` is a no-op; `account_id` always extracted as `None` from positional args | Persistence adapter never persists anything. Risk state is ephemeral. |
| MAJOR-6 | `state.py:129-135`, `test_state.py:122` | `reset_daily()` does not reset kill switch; test asserts it does | Test failure; design ambiguity over kill switch survival across daily reset. |
| MAJOR-7 | `rules.py:473` | `DuplicateOrderRule._seen_orders` is class-level (shared global state) | 2 test failures due to cross-test pollution; breaks "stateless evaluators" contract; cross-instance state leakage. |
| MAJOR-8 | `kill_switch.py:61,88` | `KillSwitchAlreadyActiveError` / `KillSwitchNotActiveError` defined but never raised | Idempotency guarantee for kill switch activations is unverifiable; silent overwrites. |

### Minor Observations

| ID | Location | Observation |
|---|---|---|
| MINOR-1 | All `*.py` in `src/risk/` | No `logging` anywhere in the risk package. Zero observability in production. |
| MINOR-2 | `engine.py:404,407,412` | `v.severity.value == "FATAL"` — string comparison instead of `v.severity == RiskSeverity.FATAL`. |
| MINOR-3 | `engine.py:419-438` | `_limit_to_check_type()` builds a fresh dict on every call — should be a module-level constant. |
| MINOR-4 | `engine.py:393` | `MessageThrottleRule()` instantiated fresh; `rule._build_throttle_key()` accesses private method cross-class. |
| MINOR-5 | All `*.py` | `datetime.utcnow()` deprecated in Python 3.12 — 243 deprecation warnings in test run. |
| MINOR-6 | `contracts.py:261` | `order: Optional[Any]` should have an inline type comment documenting accepted types. |
| MINOR-7 | `rules.py:493-496` | `DuplicateOrderRule` cleanup is O(N) linear scan; use `deque` for O(1) amortised. |
| MINOR-8 | `persistence.py` | No tests for `RiskEnginePersistenceAdapter` — zero coverage on the persistence layer. |
| MINOR-9 | `engine.py` | Post-trade FATAL drawdown (`DrawdownRule` → FATAL) does not auto-activate kill switch. Should it? |
| MINOR-10 | `state.py:137-138` | `to_snapshot()` docstring says "Callers should hold the lock or accept a slightly stale read" — the unlocked path is used in `engine.py:184` after throttle recording; document why this is safe in asyncio. |

---

## Section 9 — Recommended Fixes (Priority Order)

### Fix 1 — Add `KILL_SWITCH` to `RiskCheckType` (CRITICAL-1)

```python
# contracts.py
class RiskCheckType(str, Enum):
    ORDER_SIZE = "ORDER_SIZE"
    PRICE_TOLERANCE = "PRICE_TOLERANCE"
    POSITION_LIMIT = "POSITION_LIMIT"
    PORTFOLIO_EXPOSURE = "PORTFOLIO_EXPOSURE"
    DAILY_LOSS_LIMIT = "DAILY_LOSS_LIMIT"
    MESSAGE_THROTTLE = "MESSAGE_THROTTLE"
    DUPLICATE_ORDER = "DUPLICATE_ORDER"
    SELF_TRADE = "SELF_TRADE"
    PORTFOLIO_HEAT = "PORTFOLIO_HEAT"
    DRAWDOWN = "DRAWDOWN"
    TURNOVER_VELOCITY = "TURNOVER_VELOCITY"
    KILL_SWITCH = "KILL_SWITCH"   # ← ADD
```

```python
# kill_switch.py line 135 — replace string literal
check_type=RiskCheckType.KILL_SWITCH,  # ← USE ENUM (also add import)
```

### Fix 2 — Rename `metadata` column (CRITICAL-2)

```python
# database/models/risk_state.py line 50
extra_metadata = Column(JSONB, nullable=False, default=dict)  # ← RENAME
```

### Fix 3 — Import shared `Base` (CRITICAL-3)

```python
# database/models/risk_state.py — remove declarative_base() import and local Base
from database.models.base import Base  # ← IMPORT SHARED BASE
```

### Fix 4 — Fix `__table_args__` composite index (CRITICAL-4)

```python
# database/models/risk_state.py
from sqlalchemy import Column, String, DateTime, Numeric, Boolean, Text, Index  # ← add Index

__table_args__ = (
    Index(
        "ix_risk_state_account_timestamp",
        "account_id",
        "snapshot_timestamp",
    ),
)
```

### Fix 5 — Move `DuplicateOrderRule._seen_orders` to instance variable (MAJOR-7)

```python
class DuplicateOrderRule:
    def __init__(self):
        self._seen_orders: Dict[str, List[tuple]] = {}  # ← Instance, not class

    # remove the class-level declaration
```

Update `RULE_REGISTRY` to instantiate it:
```python
RULE_REGISTRY: Dict[RiskCheckType, RiskRule] = {
    ...
    RiskCheckType.DUPLICATE_ORDER: DuplicateOrderRule(),  # ← Already done, remains correct
    ...
}
```

### Fix 6 — Post-trade severity design (MAJOR-4)

Cap post-trade action at WARN in `post_trade_check()`:

```python
async def post_trade_check(self, ...) -> RiskDecision:
    ...
    action = self._determine_action(violations)
    # Post-trade checks cannot block (the fill already happened)
    if action == RiskAction.BLOCK:
        action = RiskAction.WARN
    ...
```

### Fix 7 — Fix test expectation for `reset_daily` (MAJOR-6)

```python
# test_state.py test_reset_daily — remove wrong assertion
async def test_reset_daily(self, state):
    ...
    await state.reset_daily(initial_equity=Decimal("100000"))
    assert state.daily_realized_pnl == Decimal("0")
    assert state.daily_turnover == Decimal("0")
    assert state.peak_equity == Decimal("100000")
    assert state.message_counts == {}
    # Kill switch survives daily reset — requires explicit deactivation
    assert state.kill_switch_active is True   # ← CORRECT EXPECTATION

# Add a new test:
async def test_reset_daily_does_not_clear_kill_switch(self, state):
    """Kill switch requires explicit deactivation; daily reset does not clear it."""
    await state.activate_kill_switch("Loss limit reached")
    await state.reset_daily()
    assert state.kill_switch_active is True
    assert state.kill_switch_reason == "Loss limit reached"
```

### Fix 8 — Fix `RiskEnginePersistenceAdapter` account_id extraction (MAJOR-5)

```python
async def pre_trade_check(self, *args, **kwargs) -> Any:
    result = await self._engine.pre_trade_check(*args, **kwargs)
    account_id = args[0] if args else kwargs.get("account_id")  # ← FIX
    await self._persist_state(account_id, kwargs.get("session"))
    return result
```

### Fix 9 — Raise defined exceptions (MAJOR-8)

```python
# kill_switch.py
def activate(self, reason: str, ...) -> KillSwitchEvent:
    if self._active:
        raise KillSwitchAlreadyActiveError(
            f"Kill switch for {self.account_id} is already active: {self._reason}"
        )
    ...

def deactivate(self, reason: str, ...) -> KillSwitchEvent:
    if not self._active:
        raise KillSwitchNotActiveError(
            f"Kill switch for {self.account_id} is not active"
        )
    ...
```

### Fix 10 — Add logging (MINOR-1)

```python
# Add to each module:
import logging
logger = logging.getLogger(__name__)

# engine.py — examples:
logger.warning("Risk BLOCK for account %s: %s", account_id, [v.rule_id for v in violations])
logger.critical("Kill switch ACTIVATED for account %s: %s", account_id, reason)
logger.info("Kill switch DEACTIVATED for account %s by %s: %s", account_id, actor, reason)
```

---

## Scores

| Dimension | Score | Notes |
|---|---|---|
| Architecture | 8.5 / 10 | Clean separation, correct layering. Isolated Base is the main gap. |
| RC-7 Compatibility | 9.5 / 10 | Zero regressions. Duck-typed correctly. |
| Code Quality | 7.0 / 10 | No logging is the biggest gap. Minor inconsistencies. |
| Risk Logic | 7.5 / 10 | Sound design. Kill switch enum bug is critical. |
| Persistence | 4.0 / 10 | Three critical bugs make persistence non-functional as delivered. |
| Performance | 8.0 / 10 | Correct async patterns. Class-level shared state is the defect. |
| Testing | 6.5 / 10 | 9/111 failures. Adapter has zero test coverage. |
| **Overall** | **7.3 / 10** | Good bones, blocked by fixable issues. |

---

## Overall Architecture Score: **8.5 / 10**
## Production Readiness Score: **3.5 / 10** (due to 3 critical blockers in persistence)

---

## Final Verdict

```
╔════════════════════════════════════════════════════╗
║                                                    ║
║            CHANGES REQUIRED                        ║
║                                                    ║
╚════════════════════════════════════════════════════╝
```

**4 critical issues and 5 major issues must be resolved before this can be merged into the main project.**

The fundamental architecture is sound. The rule engine design is correct, the contracts are solid, and no existing RC-7 code is broken. With the fixes applied — particularly the 4 critical persistence/ORM bugs and the kill switch enum defect — this will be ready for an approval re-review.

**Estimated fix effort:** 3–4 hours for an experienced developer. All issues are localised and well-understood; no redesign is required.

### Required before resubmission
1. ✅ Confirmed: RC-7 regression suite passes (336/336) — retain this
2. ❌ Fix CRITICAL-1: Add `KILL_SWITCH` to `RiskCheckType`; use enum in `kill_switch.py`
3. ❌ Fix CRITICAL-2: Rename `metadata` column to `extra_metadata`
4. ❌ Fix CRITICAL-3: Import shared `Base` from `database.models.base`
5. ❌ Fix CRITICAL-4: Replace `postgresql_indexes` with `Index()` objects
6. ❌ Fix MAJOR-7: Move `_seen_orders` to instance variable in `DuplicateOrderRule`
7. ❌ Fix MAJOR-4: Cap post-trade check action at `WARN`
8. ❌ Fix MAJOR-6: Correct the `test_reset_daily` assertion
9. ❌ Fix MAJOR-5: Fix `_persist_state` account_id extraction (and implement or stub honestly)
10. ❌ Fix MAJOR-8: Raise `KillSwitchAlreadyActiveError` / `KillSwitchNotActiveError`

### Resubmission acceptance criteria
- All 111 Batch 8 tests pass
- RC-7 regression suite still passes (336/336)
- `RiskStateModel` is importable without errors
- `RiskStateModel` is in the project shared `Base.metadata`
- `KillSwitch.evaluate_order()` does not raise `ValidationError` when active
- `DuplicateOrderRule._seen_orders` is an instance variable

---

*Review conducted by: Main Agent*  
*Review method: Full source read + runtime probing + complete test execution*  
*RC-7 regression suite executed: Yes — 336/336 pass*  
*Batch 8 test suite executed: Yes — 102/111 pass, 9 fail*
