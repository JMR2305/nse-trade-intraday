# RC-10D Zerodha Authentication Runbook

## Overview

Zerodha uses OAuth2 with a daily token rotation. Access tokens expire at midnight IST (06:00 UTC). The interactive browser step cannot be automated.

---

## Prerequisites

Before authentication, set the following Replit secrets:

| Secret | Description |
|--------|-------------|
| `ZERODHA_API_KEY` | Obtained from Kite Connect developer portal |
| `ZERODHA_API_SECRET` | Obtained from Kite Connect developer portal |

---

## Daily Authentication Flow

### Step 1 — Generate the login URL

```python
from src.brokers.zerodha.config import load_config_from_env
from src.brokers.zerodha.authentication import ZerodhaSessionManager

config = load_config_from_env()
manager = ZerodhaSessionManager(config)
url = manager.get_login_url()
print(url)
```

### Step 2 — Complete browser login

Open the URL in a browser. After login, Zerodha redirects to:
```
http://localhost:8000/broker/callback?request_token=<TOKEN>&action=login&status=success
```
Extract `<TOKEN>` from the URL.

### Step 3 — Exchange the request token

```bash
export ZERODHA_REQUEST_TOKEN=<TOKEN>
```

Or via Python:
```python
session = manager.exchange_request_token(request_token="<TOKEN>")
print(f"Session established: {session}")
```

### Step 4 — Store the access token

The access token returned by `exchange_request_token()` must be stored in the environment for the system to use it on restart:

```bash
export ZERODHA_ACCESS_TOKEN=<ACCESS_TOKEN>
```

This is the operator's responsibility. The platform does NOT store the raw access token.

### Step 5 — Restore on restart

```python
session = manager.restore_session()  # Reads ZERODHA_ACCESS_TOKEN
```

---

## Session Validation

Use `manager.validate_session()` to probe Zerodha and confirm the session is alive. This makes a lightweight `/profile` API call.

---

## Token Expiry and Proactive Monitoring

Zerodha access tokens expire at midnight IST (06:00 UTC).

### Proactive expiry detection

The system monitors token expiry with a configurable warning lead-time (default **30 minutes**).

| Condition | System action |
|-----------|--------------|
| Token expires in ≤ 30 min | Logs CRITICAL, sends email alert, routes new orders to paper mode |
| Token already expired | Same as above + marks session invalid in health tracker |
| Reactive detection (API call fails) | `BrokerSessionExpiredError` raised; health tracker marks session invalid |

The `TokenExpiryMonitor` background task polls every 60 seconds by default. It is started alongside the adapter in live mode.

### Graceful degradation to paper mode

When expiry is detected (proactively or reactively):

1. `ZerodhaAdapter._session_expired_paper_fallback` is set to `True`.
2. All subsequent `place_broker_order()` calls are routed to `PaperBroker` — no live orders are placed.
3. Health endpoint returns `token_expiry_warning: true` and `session_valid: false`.
4. A CRITICAL log entry and an email alert are sent (best-effort).

Open orders that were already submitted to Zerodha before degradation are **not** affected — they are tracked via reconciliation.

### Recovery path after token expiry

Follow these steps to restore live trading:

**Step 1 — Generate a fresh login URL**

```
GET /broker/auth/login-url
```

Open the returned URL in a browser and complete the Zerodha login.

**Step 2 — Exchange the new request token**

```
POST /broker/auth/exchange
{ "request_token": "<TOKEN_FROM_REDIRECT>" }
```

**Step 3 — Persist the access token**

```bash
export ZERODHA_ACCESS_TOKEN=<NEW_ACCESS_TOKEN>
```

In production (Autoscale), update the Replit secret `ZERODHA_ACCESS_TOKEN` via the dashboard and restart the service.

**Step 4 — Confirm session is valid**

```
GET /broker/health
```

Expect:
```json
{
  "session_valid": true,
  "token_expiry_warning": false,
  "authenticated": true
}
```

**Step 5 — Live trading resumes automatically**

Once `mark_authenticated()` is called by `restore_session()`, `_session_expired_paper_fallback` is cleared and new orders route to Zerodha again.

> **Note**: `_session_expired_paper_fallback` is cleared by `authenticate()` / `restore_session()` in the adapter. No manual flag reset is needed.

---

## Security Rules

- `ZERODHA_API_SECRET` is **never** stored in code, files, or logs
- `ZERODHA_ACCESS_TOKEN` is **never** persisted in the database
- All `log_safe()` and `repr()` calls redact credential values
- Session metadata (expiry, validity flag, user_id) is stored in `broker_sessions` — not the token itself
- `ZerodhaSessionManager` raises `BrokerAuthenticationError` if any credential is missing; the error message does not include the credential value

---

## Troubleshooting

| Symptom | Likely Cause | Action |
|---------|-------------|--------|
| `BrokerSessionExpiredError` | ZERODHA_ACCESS_TOKEN not set | Run the daily flow |
| `BrokerAuthenticationError` on URL generation | ZERODHA_API_KEY empty | Set ZERODHA_API_KEY secret |
| `validate_session()` returns False | Token expired or invalid | Re-authenticate |
| Token exchange fails | Wrong request_token | Re-generate from login URL |
