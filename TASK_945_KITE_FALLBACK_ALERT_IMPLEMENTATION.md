# Kite fallback incident alert — implementation record

## Purpose

Adds durable, advisory-only evidence when execution-grade current-price authority is no longer completely fresh Zerodha Kite coverage. The feature does not alter provider selection, readiness gates, strategy decisions, the universe, portfolio state, orders, or notifications outside the application.

## Detection and lifecycle

- The completed canonical scan is persisted first, then evaluated through the same `market_data_health` contract used by `GET /api/live-data/health-v2`.
- Historical YFinance OHLCV provenance is stored as contextual evidence only; it never opens an incident by itself.
- An episode is `ACTIVE` when the latest scan does not prove complete, fresh Kite current-price authority.
- Repeated observations update the existing active episode. The detection count advances only for a new scan ID.
- A recovery is recorded only when the scan proves a non-empty active universe, all symbols on Kite, `LIVE` freshness, no fallback/stale/synthetic/unavailable symbols, fresh quote timestamps, and a fresh scan timestamp.

## Read-only surface

The API exposes:

- `GET /api/market-data/incidents/active`
- `GET /api/market-data/incidents`
- `GET /api/market-data/incidents/:id`

Mission Control displays the active authority state and links to `/market-data-incidents`, where filters and detail views are read-only. The UI explicitly says incident history is unavailable if the durable store cannot be reached rather than treating an empty response as healthy.

An empty incident record is also not treated as healthy: the active endpoint returns a separate authority state derived from current canonical health evidence, and Mission Control renders “Awaiting Authority Evidence” until that evidence proves fresh, complete Kite coverage.

## Safety boundary

No browser mutation endpoint exists. No scan is started by the incident UI, and no Telegram, email, SMS, Slack, push, webhook, or other external delivery was added.