# Task 944 — Durable Kite Fallback Incidents in Mission Control

## Overview

Added durable, read-only monitoring for degraded Zerodha Kite current-price authority. The feature records fallback episodes after successful canonical scan persistence and surfaces them in Mission Control without changing trading behavior.

## Backend implementation

- Added `market_data_incidents.py` with:
  - Health classification based on the existing authoritative `market_data_health` contract.
  - Deterministic severity levels: `WARNING`, `HIGH`, and `CRITICAL`.
  - Optional constrained severity override through `MARKET_DATA_FALLBACK_INCIDENT_SEVERITY`.
  - Durable incident lifecycle: open, update, deduplicate, and recover.
  - Strict recovery proof requiring complete, fresh Kite current-price coverage.
  - Current health evidence lookup that never starts a scan or fetches quotes.
- Added a PostgreSQL-backed incident table with:
  - One active episode per incident type.
  - Detection counts based on distinct scan IDs.
  - Coverage, provider, freshness, and recovery evidence.
  - Transaction-scoped locking for concurrent workers.
- Connected incident evaluation to `run_live_scan()` only after canonical scan persistence.
- Added Python commands:
  - `market_data_incidents`
  - `market_data_incident_active`
  - `market_data_incident_detail`
- Added read-only API routes:
  - `GET /api/market-data/incidents/active`
  - `GET /api/market-data/incidents`
  - `GET /api/market-data/incidents/:id`

## Truthfulness and safety corrections

- A missing incident record is no longer treated as proof of healthy authority.
- The active endpoint now distinguishes:
  - `VERIFIED_HEALTHY`
  - `AWAITING_DURABLE_INCIDENT_EVIDENCE`
- Mission Control shows an explicit “Awaiting Authority Evidence” state until fresh, complete Kite coverage is proven.
- Empty incident history now states that absence of records is not proof of current authority health.
- Historical YFinance OHLCV provenance does not create or clear a current-price fallback incident.

## Frontend implementation

- Added the Data Authority widget to Mission Control.
- Added the read-only Authority Incidents page with:
  - Status filtering.
  - Severity filtering.
  - Active and recovered incident states.
  - Expandable desktop details.
  - Mobile detail presentation.
  - Loading, error, empty, storage-unavailable, and awaiting-evidence states.
  - Asia/Kolkata/IST timestamp rendering.
- Added React Query hooks and response types.
- Registered the new route and Market Data Agent navigation entry.
- Added route freshness coverage for the incidents page.

## Explicit non-goals

This implementation does not:

- Change provider selection or fallback policy.
- Change readiness, execution gates, strategies, portfolios, or orders.
- Trigger scans from the browser.
- Send Telegram, email, SMS, Slack, push, webhook, or other external notifications.
- Create synthetic production incidents.
- Modify the immutable August 26 production session.

## Verification

- Backend incident and market-data-health tests: **18 passed**.
- Focused dashboard tests: **150 passed**.
- API-server TypeScript check: passed.
- Dashboard TypeScript check: passed.
- Python compilation checks: passed.
- Dashboard production build: passed with the required `PORT` and `BASE_PATH`.
- API and dashboard workflows restarted successfully.
- Browser verification confirmed:
  - Mission Control renders the data-authority widget.
  - The Authority Incidents route is read-only.
  - Status and severity filters are present.
  - Empty history uses non-misleading copy.
  - Only GET incident-history requests were observed.
  - No scan, order, or notification requests were triggered.

## Follow-up note

Production verification must remain read-only. Active and recovered incident presentation should be tested later with controlled local fixtures or mocked API responses rather than by manufacturing an incident in production.