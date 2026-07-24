# RC-10D Broker Architecture

## Overview

RC-10D adds a Zerodha Kite adapter **below** the existing RC-7 Execution Engine. RC-7 remains the sole owner of order lifecycle, state transitions, kill-switch enforcement, and audit trail. RC-10D only translates RC-7-approved commands into Zerodha API calls and normalises responses back.

---

## Data Flow

```
Strategy (RC-9)
    │
    ▼ signal
SignalRouter
    │
    ▼ validated signal
RC-8 RiskIntegrationLayer          ← mandatory gate (never bypassed)
    │   acquire per-account lock
    │   evaluate risk rules
    │   on APPROVED:
    ▼
ExecutionService._submit_approved_order()   ← RC-7
    │   create DB order record
    │   build BrokerOrderRequest (Pydantic, frozen)
    ▼
ZerodhaOrderGateway.place_order()           ← RC-10D
    │   1. Check kill_switch_manager.state.can_place_orders()
    │   2. Check idempotency (broker_order_correlations table)
    │   3. Check config.is_live_order_allowed() → paper OR live branch
    │
    ├─── paper mode ──▶  PaperBroker.place_order()
    │                      │ simulate fill + slippage
    │                      ▼ OrderResponse (legacy)
    │                    normalise → BrokerOrderResponse
    │
    └─── live mode ──▶  BrokerRateLimiter.acquire_order()
                         │
                         ▼ ZerodhaHttpClient.place_order()
                           │ (runs KiteConnect in thread pool)
                           ▼ broker_order_id  OR  BrokerTimeoutError
                             → UNCERTAIN correlation if timeout
                             → enter ReconciliationEngine
```

---

## Module Responsibilities

| Module | Responsibility |
|--------|----------------|
| `src/brokers/contracts.py` | 14 frozen Pydantic broker-neutral types |
| `src/brokers/exceptions.py` | 15 domain exception types |
| `src/brokers/interface.py` | `BrokerInterface` (legacy) + `BrokerAdapter` (RC-10D) |
| `src/brokers/factory.py` | `create_broker_adapter()` — PaperBroker by default |
| `src/brokers/zerodha/config.py` | `ZerodhaBrokerConfig` — frozen, credential-safe |
| `src/brokers/zerodha/authentication.py` | `ZerodhaSessionManager` — OAuth2, no automation |
| `src/brokers/zerodha/rate_limiter.py` | `BrokerRateLimiter` — per-category sliding window |
| `src/brokers/zerodha/client.py` | `ZerodhaHttpClient` — async wrapper, retry policy |
| `src/brokers/zerodha/mapper.py` | `ZerodhaStatusMapper` — raw dict → contracts |
| `src/brokers/zerodha/order_gateway.py` | `ZerodhaOrderGateway` — place/modify/cancel |
| `src/brokers/zerodha/account_gateway.py` | `ZerodhaAccountGateway` — read-only account |
| `src/brokers/zerodha/market_gateway.py` | `ZerodhaMarketGateway` — instruments/quotes |
| `src/brokers/zerodha/instrument_sync.py` | `InstrumentSyncEngine` — master download |
| `src/brokers/zerodha/websocket.py` | `ZerodhaWebSocketManager` — real-time updates |
| `src/brokers/zerodha/reconnect.py` | `ReconnectManager` — bounded, back-off |
| `src/brokers/zerodha/health.py` | `BrokerHealthTracker` — live health state |
| `src/brokers/zerodha/reconciliation.py` | `ReconciliationEngine` — 9-type discrepancy |
| `src/brokers/zerodha/adapter.py` | `ZerodhaAdapter` — composes all sub-components |
| `src/database/broker_models.py` | 6 ORM models for broker-specific tables |
| `migrations/versions/0006_rc10d_broker_layer.py` | Alembic migration |

---

## Key Design Invariants

1. **PaperBroker is the default.** `create_broker_adapter()` always returns `PaperBroker` unless all 5 live-mode conditions are explicitly satisfied.
2. **Kill switch is checked before every order placement** — in `ZerodhaOrderGateway.place_order()`, before any mode-specific logic.
3. **Order placement timeouts become UNCERTAIN** — never blindly retried. Reconciliation resolves them.
4. **Credentials are never logged.** `log_safe()` omits all credential values. `repr()` shows only boolean flags.
5. **Raw kiteconnect exceptions never escape `src/brokers/zerodha/`.** All are translated to domain exceptions.
6. **RC-8 is never bypassed.** `RiskIntegrationLayer` is always constructed with `enabled=True`.
7. **No strategy/AI/UI code can call Zerodha directly.** The only public surface is `ExecutionService`.

---

## Database Tables Added

| Table | Purpose |
|-------|---------|
| `broker_sessions` | Session metadata (no tokens stored) |
| `broker_order_correlations` | Idempotent order submission tracking |
| `broker_event_inbox` | Unresolvable broker events for review |
| `broker_reconciliation_runs` | Per-run reconciliation records |
| `broker_reconciliation_discrepancies` | Per-discrepancy detail |
| `instrument_sync_runs` | Instrument master download log |
