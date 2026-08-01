# Web Intelligence Service — Final Summary

**Project:** ApexQuant AI — Web Intelligence Module  
**Audit date:** 2026-08-01  
**Status: MERGED ✅**

---

## What is this service?

The Web Intelligence service is a **standalone Python/FastAPI microservice** that safely collects, deduplicates, and stores structured intelligence from operator-approved external web sources (news outlets, regulatory sites, financial data feeds). It is completely isolated from the trading engine and holds no positions, sends no orders, and has no direct path to the broker.

It is located at `services/web_intelligence/` and has its own database schema, migrations, tests, and configuration — it can be deployed independently.

---

## Architecture at a glance

```
┌─────────────────────────────────────────────────────┐
│                  FastAPI application                │
│                                                     │
│  /health   /ready   /sources   /collect   /records  │
└────────────────────┬────────────────────────────────┘
                     │
        ┌────────────▼────────────┐
        │   Collection pipeline   │
        │                         │
        │  SourceRegistry         │  — approved source list (DB-backed)
        │  → RobotsChecker        │  — robots.txt enforcement (fail-closed)
        │  → URLValidator         │  — SSRF, scheme, redirect guard
        │  → FetchClient          │  — rate-limited HTTP with retry
        │  → ScraplingAdapter     │  — HTML parsing (Scrapling + fallback)
        │  → DeduplicationService │  — hash + reference dedup, source-scoped
        │  → IntelligenceRepo     │  — Postgres persistence via SQLAlchemy
        └────────────┬────────────┘
                     │
        ┌────────────▼────────────┐
        │   Postgres + Alembic    │
        │   (schema-managed)      │
        └─────────────────────────┘
```

---

## What was audited and fixed

The audit covered Revision 2 of the service. **14 defects** were found across 8 categories; all were fixed before merge.

### Security defects (Critical / High)

| # | What was broken | What was fixed |
|---|---|---|
| 1 | `RobotsChecker` returned `allow` on any fetch or parse failure (**fail-open**) | Rewrote to be **fail-closed**: any error → `False` (blocked) |
| 2 | Non-404 4xx responses (e.g. `403 Forbidden`) were not cached — every call re-hit the URL | Non-404 4xx now cached as `None` so subsequent calls skip the re-fetch |
| 3 | `robots_policy = "allow"` on a source was stored but never read | Checker now reads the source's policy; `"allow"` bypasses the robots.txt fetch entirely |
| 4 | SSRF protections for `localhost`, private IPs, and DNS-rebinding were gated on `production_mode = True` | Guards removed — protections now fire **unconditionally** in all environments |
| 5 | Multi-hop redirect validation compared each hop against the **original** URL, not the immediate predecessor | Fixed to pass `current_url` as the anchor on every hop |
| 6 | Cross-origin redirects (e.g. `approved.com` → `attacker.com`) were logged but **not blocked** | Now raises `URLValidationError` on any netloc change mid-redirect |

### Data integrity defects (High)

| # | What was broken | What was fixed |
|---|---|---|
| 7 | `find_duplicate()` was not scoped by `source_id` — records from one source could suppress valid records from another | All three dedup branches (`source_reference`, `content_hash`, `canonical_url+title`) now filter by `source_id` |
| 8 | New records were returned as `is_new=True` but never persisted, so the next call never saw them as duplicates | `process_record()` now calls `repo.save()` immediately on new records |
| 9 | `sync_from_db()` was never called at startup — operator-persisted sources were lost on every restart | Lifespan handler now calls `await registry.sync_from_db()` after building defaults |

### Schema / startup defects (Critical / High)

| # | What was broken | What was fixed |
|---|---|---|
| 10 | `init_db()` called `Base.metadata.create_all()` at startup, creating schema outside Alembic's control | Removed `init_db()` from lifespan; Alembic is sole schema manager |
| 11 | Migration `001_initial.py` was missing the `data_quality_status` column on `intelligence_records` | Column added; `alembic upgrade head` verified on fresh SQLite |

### API correctness defects (Medium)

| # | What was broken | What was fixed |
|---|---|---|
| 12 | `list_records()` fetched **all matching rows** into Python and called `len()` for the total count | Replaced with `SELECT COUNT(*)` |
| 13 | `/ready` probe accumulated test snapshot files on every call — never deleted them | Added `contextlib.suppress`-guarded `storage.delete()` after round-trip assert |
| 14 | `/ready` had no check for parser library availability | Added `checks["scrapling"]` via import probe |

---

## Test results

| Category | Tests | Result |
|---|---|---|
| Deduplication (mock) | 3 | ✅ |
| Deduplication (real SQLite, cross-source scoping) | 5 | ✅ |
| Fetch client | 5 | ✅ |
| Parsers | 5 | ✅ |
| Robots checker | 8 | ✅ **new** |
| Security / SSRF / redirects | 9 + 10 | ✅ **new** |
| Source registry | 5 | ✅ |
| Registry DB persistence | 3 | ✅ **new** |
| Health / readiness endpoints | 4 | ✅ **new** |
| Storage | 4 | ✅ |
| **Total** | **61 / 61** | **✅ all pass** |

30 of the 61 tests are new, added specifically to cover every defect fixed.

---

## Quality checks

| Check | Result |
|---|---|
| `python -m compileall app/` | ✅ Zero syntax errors |
| `pytest tests/unit/` | ✅ 61/61 passed |
| `ruff check app/ tests/` | ✅ Zero violations (2 pre-existing FastAPI `B008` not introduced here) |
| `mypy app/ --ignore-missing-imports` | ✅ Zero new errors (7 pre-existing upstream SQLAlchemy typing gaps) |
| `alembic upgrade head` (fresh SQLite) | ✅ `Running upgrade → 001_initial, initial` — clean |

---

## Files changed

| File | What changed |
|---|---|
| `app/security/robots_checker.py` | Fully rewritten — fail-closed, policy override, 4xx caching |
| `app/security/url_validator.py` | SSRF guards unconditional; cross-origin redirect → error |
| `app/collectors/fetch_client.py` | Multi-hop redirect anchor fixed (`current_url`) |
| `app/collectors/scrapling_adapter.py` | Fallback parser handles compound CSS selectors (`tag.class`) |
| `app/repositories/intelligence_repository.py` | `find_duplicate` scoped by `source_id`; `SELECT COUNT(*)` |
| `app/services/deduplication.py` | Saves new records; passes `source_id` |
| `app/storage/snapshot_storage.py` | Added `delete()` method |
| `app/api/health.py` | Cleanup of test artifact; scrapling check; removed unused import |
| `app/main.py` | Removed `init_db()`; added `sync_from_db()` at startup |
| `migrations/versions/001_initial.py` | Added `data_quality_status` column |
| `tests/unit/test_robots_checker.py` | **New** — 8 tests |
| `tests/unit/test_security_extended.py` | **New** — 10 tests |
| `tests/unit/test_dedup_scoped.py` | **New** — 5 tests |
| `tests/unit/test_registry_persistence.py` | **New** — 3 tests |
| `tests/unit/test_health_readiness.py` | **New** — 4 tests |
| `tests/unit/test_deduplication.py` | Updated mock signature to accept `source_id` |

---

## Isolation guarantee

The service has **zero imports from any trading-engine module**. It does not import from:
- `artifacts/api-server/`
- `artifacts/trading-dashboard/`
- `lib/api-client-react/`, `lib/api-zod/`, or `lib/db/`

It reads from and writes to its **own Postgres schema** and may be deployed, scaled, or removed without touching the trading engine.

---

## How to run

```bash
# Install dependencies
cd services/web_intelligence
pip install -e ".[dev]"

# Apply schema (once, on a fresh DB)
alembic upgrade head

# Start the service
uvicorn app.main:app --reload

# Run all tests
pytest tests/unit/ -v
```

> **Note:** Set `DATABASE_URL` in your environment (e.g. `postgresql+asyncpg://user:pass@localhost/wi`) before starting. For local unit tests, the default SQLite URL is used automatically.
