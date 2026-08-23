# RTV-1B — Kite Session Persistence Diagnosis and Fix

**Scope:** Authentication/session persistence only  
**Mode:** Read-only diagnosis; no orders, trading activation, settings changes, universe changes, portfolio reset, code deployment, or scan/execution changes  
**Checked:** 2026-08-23

## Final verdict

### C. ENVIRONMENT/CALLBACK MISMATCH — USER ACTION REQUIRED

The user’s Kite login was successful in the **production Autoscale environment**. The earlier `LOGIN_REQUIRED` result came from inspecting the separate **development API** at `localhost:8080`, where no production session token exists.

The production runtime is authenticated and successfully returns read-only Kite quotes. No session-persistence code change is required to resolve the reported login symptom.

> Important: two independent production safety-baseline discrepancies were also observed: the active universe is `CUSTOM_LOW_PRICE_SECTOR`, not `NIFTY_50`, and the two portfolio endpoints do not currently agree. Those are recorded below and were not changed because they are outside this authentication-only scope.

## Environment and callback matrix

| Item | Result |
|---|---|
| Login environment | **Production** — inferred from the valid production token created after the reported login |
| Callback environment | **Production** — `https://nse-trade-intraday.replit.app/api/kite/callback` |
| API inspected in RTV‑1A | **Development** — `http://localhost:8080` |
| Development callback derived by code | `http://localhost/api/kite/callback` |
| Production deployment | public Autoscale |
| Do login/callback/earlier inspected API match? | **No** |
| Do login/callback/production inspected API match? | **Yes** |

The development and production runtimes have separate processes and durable state. A successful login in production must not be expected to populate the development runtime’s local session view.

## Actual authentication state

| Field | Development API | Production API |
|---|---|---|
| `credentials_present` | `false` | `true` |
| `token_status` | `MISSING` | `VALID` |
| `token_stored` | `false` | `true` |
| `token_expired` | `false` | `false` |
| `connected` | `false` | `true` |
| `connection_state` | `LOGIN_REQUIRED` | `CONNECTED` |
| `daily_login_required` | `true` | `false` |
| Probe source | `no_credentials` | `live` |
| Last successful Kite call | unavailable | recorded by the production status probe |
| Live broker orders | disabled | disabled |

The production status was independently forced through a live, read-only Kite profile probe. The token expiry is recorded for the next daily Kite expiry boundary. No credential, token, cookie, request token, login URL, or secret is included in this report.

## Login flow trace

| Step | Source / endpoint | Runtime process | Expected result | Observed result |
|---|---|---|---|---|
| Open Kite login | `routes/kite.ts` → `GET /api/kite/login` | Node API | Redirect to Kite with configured app key | code path established; user completed production login |
| Zerodha redirect | configured developer-console redirect URI | Zerodha → production API | callback reaches same environment | production callback URI matches deployed API |
| Callback validation | `routes/kite.ts` → `GET /api/kite/callback` | Node API | require `status=success` and valid request-token shape | source enforces both |
| Secure handoff | callback → `runPython(["kite_exchange"], {KITE_REQUEST_TOKEN})` | Node → Python child | request token passed only in child environment | source uses environment, not argv |
| Session exchange | `kite_session_manager.exchange_request_token()` | Python child | `generate_session()` returns access token | production status proves a valid token was stored and usable |
| Token persistence | `kite_token_store.save_token()` | Python child | write durable record plus local warm cache | production status shows `token_stored=true` |
| Status read | `kite_session_manager.get_status()` | Python child | load token, live `profile()` probe | production reports `CONNECTED`, `VALID`, `probe_source=live` |
| Read-only quote | `GET /api/kite/quote` → `kite_quote_provider` | Node → Python child | Kite quote provenance retained | 5/5 sample quotes returned `kite_live` |
| Instrument hydration | `kite_instrument_cache.refresh()` | Python child | current active-symbol mappings | **not executed automatically; cache remains stale** |

## Persistence mechanism

### Intended design

| Layer | Writer | Reader | Purpose |
|---|---|---|---|
| PostgreSQL `phase20_kv` key `kite_token_v1` | `kite_token_store._db_save()` | `kite_token_store._db_load()` | Authoritative, shared Autoscale storage |
| Local `.kite_token.json` | `kite_token_store._write_file()` | `kite_token_store.load()` | chmod-0600 warm cache only |
| Process environment | `kite_token_store.apply_to_env()` at Python startup | legacy Kite modules | child-process compatibility only |

The Node API does not hold the access token in application memory. Each request starts a Python command process, and that process resolves the stored session from the token store before it initializes the Kite client.

### Actual result

- Production: `token_stored=true`, `CONNECTED`, and successful live profile/quote checks prove the reader can resolve a usable session.
- Development: `token_stored=false`; this is a separate environment, not proof of a failed production login.
- Normal production restart / different Autoscale instance: not forced during this verification. The source design uses `phase20_kv` specifically for this purpose, but a restart was intentionally not triggered.

### Durability hardening gap found

`kite_token_store._db_save()` suppresses durable-store exceptions, so `save_token()` can return normally after only writing the instance-local warm file. In that failure mode, the callback could redirect with `auth=success` even though an Autoscale-safe write did not occur. The same issue affects reporting a successful disconnect if durable deletion fails.

This is a real hardening gap, but it did **not** cause the current production login symptom: the production token is present and passes a live probe. It was not changed in this authentication diagnosis, because the confirmed root cause was the development/production environment mismatch.

## Static credential-loading reconciliation

| Variable / state | Expected by | Development | Production | Notes |
|---|---|---|---|---|
| `ZERODHA_API_KEY` | Node login route; Python exchange/status/quote | present to status path | present to status path | never reported unmasked |
| `ZERODHA_API_SECRET` | Python `generate_session()` exchange | configured | configured | never exposed |
| `KITE_REQUEST_TOKEN` | callback Python child only | not retained | not retained | passed via child environment only |
| `ZERODHA_ACCESS_TOKEN` | Python status/quote client | absent | resolved from token store | never exposed |
| `ZERODHA_TOKEN_TIMESTAMP` | Python expiry metadata | absent | resolved for stored session | expiry handled daily |

The RTV‑1A phrase `credentials_present=false` means **API key plus an active access token were not jointly available in that development process**. It does not mean the static API-key/secret configuration was missing.

## Read-only post-login verification

### Authentication and quotes

| Check | Result |
|---|---|
| Production token status | `VALID` |
| Production token stored | `true` |
| Production authenticated / connected | `true` |
| Production login required | `false` |
| RELIANCE read-only LTP | Kite success; `kite_live` |
| TCS read-only LTP | Kite success; `kite_live` |
| INFY read-only LTP | Kite success; `kite_live` |
| HDFCBANK read-only LTP | Kite success; `kite_live` |
| ICICIBANK read-only LTP | Kite success; `kite_live` |
| Orders called | **No** |

### Instrument cache and coverage

| Check | Result |
|---|---|
| Instrument cache date | 2026-08-09 |
| Instrument cache records | 1 |
| Cache fresh | `false` |
| Required active-universe mappings | 50 |
| Confirmed token coverage | **1 / 50 (2%)** |
| Duplicate mappings | none in the one-record cache |
| Automatic hydration after valid auth | **not observed** |

Kite quote calls use `NSE:SYMBOL` and can work without an instrument token, which explains the successful quote sample despite the incomplete instrument cache. The target remains 50/50 valid active mappings. No refresh endpoint was invoked because this report was restricted to diagnosis and read-only verification.

### Readiness reporting

Production’s scan status reports 50 symbols received with the `Zerodha Kite Connect (Live) + Yahoo Finance (History)` provider label. The production `/api/live-data/health-v2` response currently does **not** include the RTV‑1 `market_data_readiness` object expected by the development source, so production token/freshness readiness cannot be certified from that consolidated contract. No deployment was performed to change this.

## Safety regression check

### Controls that remain safe

| Control | Production result |
|---|---|
| Automatic paper entries | disabled |
| Bootstrap paper trading | disabled |
| Automatic paper exits | enabled |
| Live broker order placement | disabled |
| Paper mode | enabled |
| Synthetic quote use in the sample | none |

### Baseline discrepancies — no mutation performed

| Required RTV‑1B baseline | Actual production observation | Result |
|---|---|---|
| Active universe: `NIFTY_50` / 50 | `CUSTOM_LOW_PRICE_SECTOR` | **FAIL — configuration drift from the requested baseline** |
| Canonical portfolio: ₹100,000, no positions | `/api/portfolio` reported ₹99,721.26 cash and -₹278.74 realized P&L; snapshot reported ₹100,000 cash/equity and zero positions | **FAIL — endpoints do not agree** |
| `/api/portfolio == /api/portfolio/snapshot` | values and financial field shapes differ | **FAIL** |

These discrepancies are outside the authentication-only scope. No portfolio reset, settings change, universe change, or repair was attempted.

## Files changed

- `RTV1B_KITE_SESSION_PERSISTENCE_REPORT.md` — this evidence report only.

No application code, secrets, runtime settings, trading controls, broker state, scan configuration, or deployment configuration was changed.

## Tests and checks performed

- Development `/api/kite/status?force=true`
- Production `/api/kite/status?force=true`
- Production read-only Kite quote sample for RELIANCE, TCS, INFY, HDFCBANK, and ICICIBANK
- Production instrument-cache status
- Production scan and coverage metadata
- Development and production Phase-20 settings / portfolio endpoint inspection
- Source trace of callback, token exchange, token store, Node-to-Python handoff, expiry handling, and disconnect behavior

## Remaining checks before any paper-entry discussion

1. Use the production API and callback environment for all Kite verification; do not compare a production login to the local development API.
2. Refresh and validate the production instrument master through an approved, read-only cache-hydration procedure; require 50/50 mappings before claiming token coverage success.
3. Resolve the production universe and portfolio-parity discrepancies in a separately authorized task.
4. Harden callback/disconnect persistence acknowledgement so a durable KV failure cannot be represented as a successful login/logout.
5. During an NSE session, confirm fresh scan and per-quote provenance through the production readiness contract.