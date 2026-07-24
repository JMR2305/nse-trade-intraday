# RC-10D Security Review

## Credential Handling

### What is stored
| Item | Storage | Notes |
|------|---------|-------|
| `ZERODHA_API_KEY` | Replit secret (env var) | Never in code or files |
| `ZERODHA_API_SECRET` | Replit secret (env var) | Never in code or files |
| `ZERODHA_ACCESS_TOKEN` | Env var (operator-managed) | Never in DB, never logged |
| Session metadata | `broker_sessions` table | user_id, validity flag, expiry — no token |

### What is NOT stored
- API key values in any file
- API secret in any file
- Access token in the database
- Request tokens (ephemeral, not persisted)

### Log safety
- `ZerodhaBrokerConfig.log_safe()` returns only boolean flags (`has_api_key`, `has_access_token`, etc.)
- `repr(config)` never emits credential values
- All exception messages are checked to exclude credential substrings
- `ZerodhaHttpClient._translate()` strips credential words from translated exceptions

---

## Authentication Attack Surface

| Threat | Mitigation |
|--------|-----------|
| Token leakage via logs | `log_safe()` on all structured log calls; `repr()` safe |
| Token leakage via exceptions | `_translate()` strips credential words; caught before re-raise |
| Token persisted to DB | Explicit decision not to store token in `broker_sessions` |
| Automated OAuth abuse | Interactive browser step cannot be automated |
| Stale token reuse | `validate_session()` probes broker; `BrokerSessionExpiredError` raised |

---

## Order Submission Security

| Threat | Mitigation |
|--------|-----------|
| Duplicate order submission | Idempotency key + `broker_order_correlations` table |
| Blind retry after timeout | Timeout → UNCERTAIN → reconciliation (no auto-retry) |
| Live order without authorization | 5-gate `is_live_order_allowed()` check |
| Strategy calling broker directly | Structurally impossible — only `ExecutionService` exposes the broker |
| Kill switch bypass | Checked first in `ZerodhaOrderGateway.place_order()` before any other logic |
| RC-8 bypass | `RiskIntegrationLayer` always created with `enabled=True` |

---

## Network Security

| Concern | Detail |
|---------|--------|
| API calls | All via official `kiteconnect` library over HTTPS |
| WebSocket | KiteTicker over WSS |
| No raw HTTP | `ZerodhaHttpClient` wraps KiteConnect — never raw requests |
| Timeout | 10s default per request; configurable |

---

## Audit Trail

- All order placements logged with structured fields (no credentials)
- Kill switch triggers logged at CRITICAL level
- Reconciliation discrepancies persisted to DB
- Session validation results logged at DEBUG level
- No PII beyond user_id (Zerodha client code) stored anywhere

---

## Findings

No critical or high severity findings in RC-10D implementation. All credential handling follows the established patterns from RC-8 and RC-19A (see `phase19a-kite-oauth.md` memory entry).
