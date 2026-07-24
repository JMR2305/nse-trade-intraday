# RC-10C1 Production Audit

**Document status:** Audit Reference  
**Phase:** RC-10C1 Portfolio Core  
**Purpose:** Independent audit reference for RC-10C1 freeze decision

---

## 1. Acceptance Criteria Checklist (Spec Section 24)

The following criteria must all be satisfied before RC-10C1 is submitted for independent audit. Each criterion maps directly to the specification.

| # | Criterion | Verification Method | Status |
|---|-----------|---------------------|--------|
| 1 | One authoritative portfolio state exists | Single `StateManager` instance; dependency injection enforced | Must verify |
| 2 | Portfolio events are idempotent and replayable | `idempotency_key` enforced; replay tests pass | Must verify |
| 3 | Position lifecycle supports partial fills and recovery | Partial fill tests (test suite C) pass | Must verify |
| 4 | Capital reserve is protected | `cash_reserve_pct` enforced; `ReservedCapitalViolationError` raised on breach | Must verify |
| 5 | Position sizing uses Decimal arithmetic | All `pnl.py` and `position_sizer.py` arithmetic uses `Decimal`; no float | Must verify |
| 6 | Pending orders are included in exposure | `ExposureSnapshot.pending_order_exposure` populated from reservations | Must verify |
| 7 | Portfolio limits are enforced | Test suite G; every limit has boundary test | Must verify |
| 8 | P&L is deterministic and auditable | Replay produces identical P&L; test suite H | Must verify |
| 9 | Broker-state reconciliation is implemented | `reconciliation.py` and test suite I | Must verify |
| 10 | No direct Zerodha dependency exists | `grep -r "kiteconnect\|pyzerodha" src/portfolio/` returns empty | Must verify |
| 11 | RC-8 remains the final risk authority | Flow diagram; no portfolio bypass path exists in signal router | Must verify |
| 12 | RC-7 remains the execution authority | No order placement in `src/portfolio/`; test suite K | Must verify |
| 13 | Stale or unreconciled portfolio state blocks new orders | `PortfolioNotReadyError` on stale state; test suite J | Must verify |
| 14 | Snapshot and replay recovery are verified | Test suite J; recovery runbook tested | Must verify |
| 15 | All new tests pass | CI test run — zero failures | Must verify |
| 16 | All RC-6 through RC-10D regression tests pass | Regression suite M — zero regressions | Must verify |
| 17 | Independent audit reports zero Critical findings | External reviewer confirmation | Required for freeze |
| 18 | All High findings are resolved before freeze | Tracking log of High findings | Required for freeze |

### 1.1 Verification Commands

```bash
# Check for forbidden Zerodha imports
grep -rn "kiteconnect\|pyzerodha\|from kite\|import kite" \
    artifacts/api-server/src/python/src/portfolio/
# Expected: no output

# Check paper_mode enforcement
grep -n "paper_mode" \
    artifacts/api-server/src/python/src/portfolio/config.py
# Expected: field definition + model_validator raising ValueError

# Check float usage in P&L calculations (should be absent)
grep -n "float(" \
    artifacts/api-server/src/python/src/portfolio/pnl.py \
    artifacts/api-server/src/python/src/portfolio/position_manager.py
# Expected: no output (all arithmetic uses Decimal)

# Run full test suite
cd artifacts/api-server && python -m pytest src/python/tests/portfolio/ -v

# Run regression suite
cd artifacts/api-server && python -m pytest src/python/tests/ -v --ignore=src/python/tests/portfolio/
```

---

## 2. Frozen Invariants Verification

The following invariants are structural — they cannot be overridden via configuration or environment variables. Each must be independently verified.

| Invariant | Enforcement Mechanism | Audit Check |
|-----------|----------------------|-------------|
| `paper_mode = True` | `PortfolioConfig` model validator raises `ValueError` if `False` | Attempt to construct `PortfolioConfig(paper_mode=False)` — must raise |
| No Zerodha imports | Module-level import prohibition; CI lint check | Static analysis scan of `src/portfolio/` |
| No order placement | `src/portfolio/` has no calls to RC-7 order endpoints | Code review; grep for order placement functions |
| RC-8 is final authority | Signal router calls RC-8 after portfolio pre-check | Integration test: approved portfolio allocation + rejected RC-8 = no order |
| Stale state blocks orders | `PortfolioNotReadyError` on staleness | Test: advance mock clock beyond `stale_state_threshold_s`; verify rejection |
| Reserve never allocated | `ReservedCapitalViolationError` | Test: request capital = available_cash - reserve + 1 INR; verify rejection |
| Idempotent events | Duplicate `idempotency_key` → `DuplicateEventError` | Test: apply same fill twice; verify single application |
| No blind corrections | Reconciliation corrections require explicit non-dry-run | Test: dry-run produces report; live run applies with audit |

---

## 3. Metrics Exposed (Spec Section 17)

All metrics are emitted in structured log format and, where applicable, as Prometheus-compatible counters/gauges.

| Metric Name | Type | Description | Labels |
|-------------|------|-------------|--------|
| `portfolio_equity` | Gauge | Current portfolio equity (INR) | `portfolio_id`, `paper_mode` |
| `portfolio_cash` | Gauge | Available cash (INR) | `portfolio_id` |
| `portfolio_buying_power` | Gauge | Net buying power (INR) | `portfolio_id` |
| `portfolio_gross_exposure` | Gauge | Gross exposure (INR) | `portfolio_id` |
| `portfolio_net_exposure` | Gauge | Net exposure (INR) | `portfolio_id` |
| `portfolio_unrealised_pnl` | Gauge | Unrealised P&L (INR) | `portfolio_id` |
| `portfolio_realised_pnl` | Gauge | Realised P&L today (INR) | `portfolio_id`, `trading_date` |
| `portfolio_drawdown` | Gauge | Current drawdown (fraction 0–1) | `portfolio_id` |
| `open_positions` | Gauge | Count of open positions | `portfolio_id` |
| `pending_orders` | Gauge | Count of pending order reservations | `portfolio_id` |
| `allocation_requests_total` | Counter | Total allocation requests received | `portfolio_id`, `strategy_id` |
| `allocation_rejections_total` | Counter | Total allocation rejections | `portfolio_id`, `strategy_id`, `reason_code` |
| `limit_breaches_total` | Counter | Total limit breach events | `portfolio_id`, `limit_name`, `severity` |
| `reconciliation_discrepancies` | Gauge | Count of unresolved discrepancies | `portfolio_id`, `severity` |
| `stale_portfolio_state` | Gauge | 1 if state is stale, 0 otherwise | `portfolio_id` |
| `portfolio_recovery_duration` | Histogram | Recovery duration in seconds | `portfolio_id`, `recovery_type` |

### 3.1 Metric Emission Points

| Component | Metrics emitted |
|-----------|----------------|
| `StateManager` | `portfolio_equity`, `portfolio_cash`, `portfolio_buying_power`, `open_positions` |
| `ExposureEngine` | `portfolio_gross_exposure`, `portfolio_net_exposure` |
| `PnLCalculator` | `portfolio_unrealised_pnl`, `portfolio_realised_pnl`, `portfolio_drawdown` |
| `CapitalAllocator` | `allocation_requests_total`, `allocation_rejections_total` |
| `LimitsChecker` | `limit_breaches_total` |
| `Reconciliation` | `reconciliation_discrepancies` |
| `HealthService` | `stale_portfolio_state` |
| `RecoveryService` | `portfolio_recovery_duration`, `pending_orders` |

---

## 4. Log Hygiene Rules

### 4.1 Never Log

The following must **never** appear in logs, regardless of log level:

- Broker API access tokens or session tokens
- Broker account passwords or secrets
- Full broker account numbers (mask last 4 digits only: `****1234`)
- Raw private broker API response bodies
- Webhook signing secrets
- Database connection strings or credentials
- Any value read from environment variables prefixed with `SECRET_`, `TOKEN_`, `PASSWORD_`, `KEY_`

### 4.2 Always Log (at appropriate levels)

| Event | Level | Required Fields |
|-------|-------|----------------|
| Portfolio recovery started | INFO | `portfolio_id`, `recovery_type` |
| Recovery completed | INFO | `portfolio_id`, `duration_s`, `events_replayed` |
| Reconciliation started | INFO | `portfolio_id`, `dry_run` |
| Discrepancy detected | WARNING/CRITICAL | `discrepancy_type`, `severity`, `instrument_token`, `instrument_symbol` |
| Allocation rejected | INFO | `strategy_id`, `reason_codes`, `requested_capital` (amount only, not personal account) |
| Limit breached | WARNING/CRITICAL | `limit_name`, `current_value`, `configured_limit`, `severity` |
| Fill applied | INFO | `fill_id`, `instrument_token`, `quantity`, `price` |
| Position opened/closed | INFO | `position_id`, `instrument_token`, `side`, `quantity` |
| Portfolio halted | CRITICAL | `reason`, `portfolio_id` |
| Snapshot created | DEBUG | `snapshot_id`, `version` |

### 4.3 Structured Log Format

All portfolio logs use structured JSON with a standard envelope:

```json
{
    "timestamp": "2024-01-15T09:32:10.123+05:30",
    "level": "INFO",
    "component": "portfolio.reconciliation",
    "portfolio_id": "default",
    "event": "discrepancy_detected",
    "discrepancy_type": "QUANTITY_MISMATCH",
    "instrument_symbol": "RELIANCE",
    "local_value": "100",
    "broker_value": "80",
    "severity": "CRITICAL"
}
```

---

## 5. Performance Considerations

### 5.1 StateManager Lock Contention

The `asyncio.Lock` in `StateManager` is a potential bottleneck under high event rates. Mitigation:

- Never hold the lock while awaiting I/O (DB writes, network calls)
- Snapshot production acquires lock briefly for consistent read, then releases
- Repository writes happen outside the lock (with snapshot copy)
- Event application is designed to complete in < 1ms (pure in-memory arithmetic)

### 5.2 Event Replay Performance

Large event histories increase cold-start recovery time. Mitigations:

- Periodic snapshots compress event history (`snapshot_interval_s` default: 60s)
- Event repository uses indexed queries by `sequence` and `portfolio_id`
- Recovery loads only events with `sequence > snapshot.version`

### 5.3 Repository I/O

All repository operations use `asyncio.to_thread` to avoid blocking the event loop. For write-heavy scenarios:

- Batch insert for event replay (use `executemany` or equivalent)
- Separate read and write database connections where possible
- Index on `(portfolio_id, sequence)` for event queries
- Index on `(portfolio_id, snapshotted_at DESC)` for snapshot queries

### 5.4 Decimal Arithmetic

`Decimal` arithmetic is significantly slower than `float`. Mitigations:

- Pre-compute and cache frequently used values (e.g., `reserve_amount`)
- Avoid recomputing exposure from scratch on every tick; use incremental updates
- Profile hot paths in `ExposureEngine` and `PnLCalculator` under simulated load

### 5.5 Expected Throughput

For the NSE intraday platform scope (single account, paper trading):

| Operation | Expected latency | Acceptable max |
|-----------|-----------------|----------------|
| Capital allocation evaluation | < 5ms | 50ms |
| Position sizing | < 2ms | 20ms |
| Fill application | < 10ms | 100ms |
| Reconciliation (full) | < 500ms | 5s |
| Snapshot creation | < 100ms | 1s |
| Recovery (recent snapshot) | < 5s | 30s |
