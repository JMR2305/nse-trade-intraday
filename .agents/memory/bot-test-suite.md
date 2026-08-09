---
name: Trading-bot test suite conventions
description: How the intraday-trading-bot pytest suite (unit + integration) is kept green — namespace aliasing, isolated test DB, event-loop and commit-boundary pitfalls.
---

- Bare vs `src.*` imports are the same module via a conftest meta-path alias finder; without it SQLAlchemy models double-register ("Table already defined"). Regression tests live in tests/unit/test_import_namespace.py.
- Integration tests run against a dedicated Postgres DB `intraday_bot_test` on the workspace server; conftest derives its URL from settings, strips `sslmode` (asyncpg wants `connect_args["ssl"]`, not libpq query params), and overrides settings BEFORE importing the app.
- Hermetic per run: drop_all+create_all at conftest import, seed a placeholder instrument row with instrument_token=0 (the order API records token 0, FK to instrument_master). tests/integration/conftest.py truncates all existing tables except instrument_master per module — needed because sessions are idempotent per trading day.
- The app engine must be pre-created with NullPool for tests: TestClient makes a fresh event loop per `with` block and pooled asyncpg connections die with "attached to a different loop".
- **Request-boundary commit contract:** repos/services never commit; `get_db_session()` commits on clean exit. Without it every API write silently rolls back. Guarded by tests/integration/test_write_persistence.py.
- bcrypt must stay <5 while passlib 1.7.4 is used (bcrypt 5 changed >72-byte handling).
- Paper MARKET orders fill instantly → cancel afterwards legitimately returns 404; don't "fix" that.
- OrderRepository.update takes `order_pk` (row PK) — Order also has an `order_id` COLUMN (broker id) passed via kwargs; a param named order_id collides.
