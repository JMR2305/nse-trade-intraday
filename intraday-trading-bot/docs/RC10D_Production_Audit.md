# RC-10D Production Audit

Date: 2026-07-24

## 17 Audit Questions

### 1. Are all secrets stored in Replit secrets (not in code)?
**YES.** `ZERODHA_API_KEY` and `ZERODHA_API_SECRET` are Replit secrets. `ZERODHA_ACCESS_TOKEN` is an env var, not a secret in the traditional sense since it rotates daily.

### 2. Does any log line include a credential value?
**NO.** All structured log calls use `config.log_safe()` which emits only boolean flags. Exception messages are sanitised in `ZerodhaHttpClient._translate()`.

### 3. Is live order placement possible in this release?
**YES — when all 5 runtime gates pass.** The startup-time `TradingSettings.enforce_paper_mode()` validator was removed in the paper-to-live validation pass. Live orders are now gated entirely by `ZerodhaBrokerConfig.is_live_order_allowed()` which requires 5 explicit conditions simultaneously (`enabled`, `not paper_trading`, `live_trading_enabled`, `api_key` present, `access_token` present). Any condition not met routes the order to `PaperBroker` automatically. All three enabling env vars (`ZERODHA_ENABLED`, `ZERODHA_PAPER_TRADING=false`, `ZERODHA_LIVE_TRADING_ENABLED`) are operator-set; they are not on by default.

### 4. Is the kill switch checked before every order?
**YES.** `ZerodhaOrderGateway.place_order()` checks `kill_switch_manager.state.can_place_orders()` as the first operation, before any mode or idempotency logic.

### 5. Is RC-8 (risk gate) always enforced?
**YES.** `ExecutionService` always creates `RiskIntegrationLayer(enabled=True)`. There is no code path that bypasses it.

### 6. Are order placement timeouts handled safely?
**YES.** `BrokerTimeoutError` on placement → marks correlation as `UNCERTAIN` → triggers reconciliation. No blind retry of order placement.

### 7. Is idempotency enforced for order submission?
**YES.** `broker_order_correlations` table stores `idempotency_key` as UNIQUE. `ZerodhaOrderGateway` checks in-memory cache; DB is source of truth on restart.

### 8. Is the WebSocket reconnect bounded?
**YES.** `ReconnectManager` enforces `max_attempts` (default 10). After exhaustion, logs CRITICAL and stops.

### 9. Is reconciliation triggered after reconnect?
**YES.** `ZerodhaWebSocketManager` calls `on_reconcile` callback after each successful reconnect (via `ReconnectManager.on_reconnect_success`).

### 10. Are credentials stored in the database?
**NO.** Only session metadata (user_id, validity flag, expiry time) is stored in `broker_sessions`. No API key, secret, or access token is persisted to the DB.

### 11. Can a strategy component call Zerodha directly?
**NO.** The only public surface is `ExecutionService`. Zerodha gateways are not exposed as dependencies anywhere else.

### 12. Are raw kiteconnect exceptions translated?
**YES.** `ZerodhaHttpClient._translate()` maps all kiteconnect exceptions to domain types. Raw exceptions do not cross the `src/brokers/zerodha/` boundary.

### 13. Is paper mode the default in all code paths?
**YES.** `PaperBroker` is the default in `create_broker_adapter()`, `ExecutionService.__init__()`, and `ZerodhaBrokerConfig` (`paper_trading=True` by default).

### 14. Is the rate limiter protecting all API categories?
**YES.** Separate sliding-window buckets for order (10 rps), quote (1 rps), account (2 rps), historical (3 rps). `BrokerRateLimitError` raised on exhaustion.

### 15. Is the instrument sync atomic?
**YES.** `InstrumentSyncEngine._upsert_to_db()` uses a transaction with `COMMIT` or `ROLLBACK` — no partial updates.

### 16. Is all broker health tracked and observable?
**YES.** `BrokerHealthTracker` exposes `get_health() → BrokerHealth` with 13 fields including status, authenticated, session_valid, websocket_connected, reconnect_count, unresolved_orders.

### 17. Are all 6 new DB tables covered by the Alembic migration?
**YES.** Migration `0006` creates: `broker_sessions`, `broker_order_correlations`, `broker_event_inbox`, `broker_reconciliation_runs`, `broker_reconciliation_discrepancies`, `instrument_sync_runs`. ORM models in `src/database/broker_models.py` match.
