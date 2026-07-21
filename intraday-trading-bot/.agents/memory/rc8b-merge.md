---
name: RC-8B Risk Engine Merge
description: Key decisions and constraints from merging RC-8B into the project; Pydantic v2 compat, vocabulary break, wiring pattern.
---

## RC-8B Vocabulary Break (RC-8A → RC-8B)

Old names (RC-8A, now gone): `RiskDecision`, `OrderSizeLimit`, `PriceToleranceLimit`,
`RiskCheckContext`, `RiskLimit`, `RiskService.check_trade_risk()`.

New names (RC-8B, canonical): `RiskResult`, `OrderQuantityLimit`, `PriceBandLimit`,
`RiskRequest`, `RiskContext`, `RiskConfiguration`, `RiskStateSnapshot`,
`EmergencyHaltLimit`, `CircuitBreakerLimit`, `FillDeliveryError`.

**Why:** RC-8B is a complete engine replacement. Any future PR against risk code must use RC-8B names.

## Pydantic v2 Compat (critical)

The project runs Pydantic 2.7.4. Two breaking changes from RC-8B source:
1. `Field(default=..., const=True)` → replaced with `Literal[EnumValue] = EnumValue` type annotation.
2. `@validator(pre=True, always=True)` → replaced with `@field_validator("field", mode="before") @classmethod`.
3. Frozen model mutations raise `ValidationError` (not `TypeError`) → tests must use `pytest.raises(Exception)`.

**How to apply:** Any new Pydantic model in the risk package must use v2 syntax.

## ExecutionService Wiring Pattern

`execute_order()` builds an order dict → calls `self._risk_integration.submit_order(session_id, order)`.
The risk gate calls `ProjectExecutionAdapter.submit_order()` on approval, which calls
`ExecutionService._submit_approved_order()` (the RC-7 PaperBroker path).
`session_id` == `account_id` throughout the risk engine.

**Why:** Keeps RC-7 broker logic intact; RC-8B wraps it without rewriting it.

## RC-8B KillSwitch is Async + Account-Agnostic

`KillSwitch.__init__()` takes no arguments. Activation/deactivation are `async`.
`events` property (not `get_history()`). `event_type` (not `action`). `triggered_by` (not `actor`).
Per-account kill switch state is managed by `RiskEngine`, not `KillSwitch` directly.

## Pre-existing Failure

`tests/unit/test_kill_switch.py::TestKillSwitch::test_history` was failing BEFORE RC-8B.
Tests `KillSwitchManager` (project's original class). Unrelated to RC-8B.

## RiskStateModel Schema (0002 migration)

Four new columns: `trade_count INT`, `order_count INT`,
`emergency_halt_active BOOL`, `circuit_breaker_triggered BOOL`.
All have server_default so existing rows get 0/false. Hydration in risk_state.py uses `getattr(..., default)` for backward compat.

## PriceBandRule + Paper Mode

`ProjectExecutionAdapter.get_market_price()` always returns `None` (no real-time LTP).
`PriceBandRule.evaluate()` returns `None` when LTP is `None` — graceful skip by design.
