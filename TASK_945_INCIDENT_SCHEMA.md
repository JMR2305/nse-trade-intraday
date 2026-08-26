# Kite fallback incident schema

## Storage

`market_data_fallback_incidents` is an additive PostgreSQL table. It is initialized with the canonical incident module and is only used for observability evidence.

| Field | Meaning |
| --- | --- |
| `id` | Server-generated immutable episode identifier |
| `kind` | `KITE_CURRENT_PRICE_AUTHORITY` |
| `status` | `ACTIVE` or `RECOVERED` |
| `severity` | Deterministic `WARNING`, `HIGH`, or `CRITICAL`; optional environment override is constrained to the same values |
| `started_at`, `last_detected_at`, `recovered_at` | Lifecycle timestamps |
| `latest_scan_id` | Latest canonical scan evidence for the episode |
| `active_universe_count` | Expected current-price coverage count |
| `symbols_on_kite`, `symbols_fallback`, `symbols_stale`, `symbols_unavailable`, `symbols_synthetic` | Execution-grade coverage distribution |
| `current_quote_provider`, `current_quote_freshness` | Authoritative provider/freshness labels |
| `detection_count` | Number of distinct scan observations during one active episode |
| `evidence` | Provenance/freshness metadata, including historical provider context |
| `recovery_summary` | Fixed explanation of the strict recovery proof |

## Indexes and concurrency

- A partial unique index permits at most one `ACTIVE` row for this incident kind.
- A status/time history index serves newest-first history queries.
- A transaction-scoped PostgreSQL advisory lock serializes open/update/recover operations across workers.

The table has no trigger, callback, or foreign key into trading/execution state.