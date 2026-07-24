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

## Token Expiry

Zerodha access tokens expire at midnight IST (06:00 UTC). The system detects expiry on the next API call and raises `BrokerSessionExpiredError`. The operator must repeat the daily flow.

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
