# RC-10C1 Pre-Implementation Verification

**Document status:** Verified  
**Phase:** RC-10C1 Portfolio Core  
**Prepared against:** RC-7 (ExecutionEngine), RC-8 (Risk Engine), RC-10B (Advisory AI), RC-10D (Broker Layer)

---

## 1. Purpose

This document records the interface contracts consumed by RC-10C1, confirms frozen invariants, and serves as the pre-implementation gate that must be completed before any RC-10C1 module is written or modified.

---

## 2. Consumed Interfaces

### 2.1 RC-7 — Execution Engine

RC-10C1 consumes the following read-only outputs from RC-7:

| Interface | Purpose | Consumed as |
|-----------|---------|-------------|
| `OrderFill` / fill event stream | Triggers `FILL_RECEIVED` ledger entry | Event payload |
| `OrderStatus` updates | Resolves pending order reservations | Event payload |
| `ExecutionRecord` query | Cross-check during recovery | Read-only query |
| Execution audit trail | Replay verification after restart | Read-only query |

**RC-10C1 must not:**
- Place, modify, or cancel orders via RC-7
- Write to RC-7 internal state
- Import RC-7 private classes

### 2.2 RC-8 — Risk Engine

RC-10C1 supplies context to RC-8 and receives limit decisions:

| Interface | Direction | Notes |
|-----------|-----------|-------|
| `buying_power` | Portfolio → RC-8 | From `BuyingPower.net` |
| `current_drawdown` | Portfolio → RC-8 | From `PortfolioPnL.drawdown` |
| `daily_pnl` | Portfolio → RC-8 | From `PortfolioPnL.daily_pnl` |
| `open_position_count` | Portfolio → RC-8 | From `PortfolioSnapshot` |
| `sector_exposure` | Portfolio → RC-8 | From `ExposureSnapshot` |
| `strategy_exposure` | Portfolio → RC-8 | From `ExposureSnapshot` |
| `portfolio_readiness` | Portfolio → RC-8 | From `PortfolioHealth.readiness` |
| `LimitCheckReport` | RC-8 → caller | RC-8 remains final authority |

**RC-8 integration rule:** Portfolio pre-check approval is **necessary but not sufficient**. RC-8 performs its own independent evaluation and is the **final authority** on all order approvals. Portfolio limits cannot weaken RC-8 rules.

### 2.3 RC-10B — Advisory AI

RC-10B is advisory only. RC-10C1 may consume:

| Interface | Purpose | Constraint |
|-----------|---------|------------|
| `signal_confidence` (Decimal 0–1) | Optional position-sizing scaling | Must be configurable; controlled by `use_ai_confidence_sizing` flag |
| AI forecast output | Advisory input to capital allocator | Never binding; RC-8 retains authority |

**Enforced invariant:** `PortfolioConfig.use_ai_confidence_sizing` defaults to `False`. When `True`, AI confidence is an advisory scalar on sizing only — it cannot approve or reject orders.

### 2.4 RC-10D — Broker Layer (Neutral Snapshot Format)

RC-10D is the **only** permitted broker integration layer. RC-10C1 consumes broker-neutral dict format snapshots:

| Snapshot Key | Type | Description |
|---|---|---|
| `positions` | `list[dict]` | Per-instrument position records |
| `positions[].instrument_token` | `int` | NSE instrument identifier |
| `positions[].quantity` | `int` | Net open quantity |
| `positions[].average_price` | `str` (Decimal-safe) | Weighted average entry |
| `positions[].realised_pnl` | `str` | Broker-reported realised P&L |
| `positions[].unrealised_pnl` | `str` | Broker-reported unrealised P&L |
| `orders` | `list[dict]` | Open/pending order records |
| `trades` | `list[dict]` | Confirmed fill records |
| `funds.available_cash` | `str` | Available cash per broker |
| `funds.used_margin` | `str` | Margin consumed |
| `funds.available_margin` | `str` | Margin still available |
| `snapshot_at` | ISO-8601 string | Broker snapshot timestamp |
| `source` | `str` | e.g. `"zerodha_paper"`, `"zerodha_live"` |

All fields use string representations of monetary values to preserve Decimal precision across serialisation boundaries.

---

## 3. Confirmed: No Direct Zerodha SDK Imports

**Verification status: CONFIRMED**

The following constraints are enforced by module design:

- No file under `src/portfolio/` may import from `kiteconnect`, `pyzerodha`, or any broker-specific SDK.
- All broker data arrives via RC-10D's broker-neutral dict format.
- Reconciliation consumes `PortfolioReconciliationReport` and `PortfolioDiscrepancy` domain objects, not broker API responses.
- The `exceptions.py` module contains no broker references.
- The `contracts.py` module uses only `Decimal`, `datetime`, `UUID`, and pydantic — no broker SDK types.

If a future compatibility fix requires wrapping a broker type, it must be done in RC-10D and exposed as a broker-neutral contract. A separate compatibility-fix document is required before any such change.

---

## 4. Confirmed: `paper_mode` Enforced in PortfolioConfig

**Verification status: CONFIRMED**

From `config.py` model validator:

```python
@model_validator(mode="after")
def _validate_consistency(self) -> "PortfolioConfig":
    if not self.paper_mode:
        raise ValueError(
            "paper_mode must be True — live trading is structurally disabled in RC-10C1"
        )
```

- `paper_mode: bool = Field(default=True)` — hardcoded default
- Any attempt to set `paper_mode=False` raises `ValueError` at construction time
- No environment variable override path exists for `paper_mode` in this release
- `PortfolioSnapshot.paper_mode` defaults to `True` and is propagated from config

**Live trading is structurally disabled in RC-10C1.**

---

## 5. Confirmed: RC-8 Remains Final Authority

**Verification status: CONFIRMED**

The portfolio pre-check is an **additional safeguard** operating before the RC-8 evaluation. The flow is:

```
Strategy Signal
  → Portfolio Pre-Check  (necessary, not sufficient)
      → checks: buying power, exposure limits, position count, daily loss, drawdown
      → raises: InsufficientCapitalError, ExposureLimitBreachedError, PortfolioLimitBreachedError
  → RC-8 Risk Engine     (final authority — may reject even if portfolio approved)
  → RC-7 Execution Engine
  → RC-10D Broker Layer
```

Portfolio approval grants no implicit RC-8 bypass. An `AllocationDecision` with `status=APPROVED` only means the portfolio has capacity; RC-8 may still reject the trade on its own criteria.

If the portfolio is degraded or unreconciled (`PortfolioHealth.readiness=False`), new order requests must be rejected before reaching RC-8. This is a fail-closed rule: stale or unreconciled portfolio state causes the pre-check to block, not skip.

---

## 6. Compatibility: Portfolio Hooks via Optional PortfolioService Injection

**Verification status: CONFIRMED — no breaking changes**

RC-10C1 integrates with the existing system through optional dependency injection:

- `PortfolioService` is injected into the signal router / order pipeline as an optional dependency
- If `PortfolioService` is `None` (not configured), the pipeline continues without portfolio pre-check — preserving backward compatibility with RC-6 through RC-10D
- No existing RC-7 or RC-8 contracts are modified
- No existing RC-10D contracts are modified
- RC-9 (Strategy Engine) and RC-10A (Market Intelligence) are unaware of the portfolio module and remain unchanged

Any integration point that consumes portfolio context (e.g., RC-8 receiving `buying_power`) does so through an optional field, defaulting to its prior behaviour if portfolio state is unavailable.

---

## 7. Interface Version Registry

| Component | Contract Version | Frozen Since | Consumed by RC-10C1 |
|-----------|----------------|-------------|---------------------|
| RC-7 ExecutionEngine | v1 | RC-7 freeze | Fill events, execution records |
| RC-8 RiskEngine | v1 | RC-8 freeze | Limit evaluation, final authority |
| RC-10B Advisory AI | v1 | RC-10B freeze | Optional confidence scalar |
| RC-10D BrokerLayer | v1 | RC-10D freeze | Broker-neutral snapshot dict |
| RC-10C1 Portfolio | v1 | This release | All portfolio contracts |

---

## 8. Pre-Implementation Gate Checklist

- [x] RC-10D freeze status confirmed — broker-neutral dict format documented above
- [x] RC-7 public contracts recorded — fill events and execution records identified
- [x] RC-8 public contracts recorded — context inputs and authority boundary confirmed
- [x] RC-10B advisory-only status confirmed — no binding authority
- [x] No Zerodha SDK imports in portfolio module
- [x] `paper_mode=True` enforced by model validator
- [x] RC-8 remains final risk authority
- [x] Portfolio injection is optional — no breaking changes to existing components
- [x] All interfaces to be consumed are read-only or event-driven
- [x] No compatibility fixes required at this time
