# ApexQuant Web Intelligence Collector

## Purpose
Isolated intelligence collection service for ApexQuant AI. Collects approved public information (corporate announcements, exchange circulars, market holidays, regulatory notices) completely separate from trading execution.

## Strict Separation from Trading
This service:
- Does NOT collect live prices
- Does NOT generate trade signals
- Does NOT approve trades
- Does NOT access Zerodha
- Does NOT write to the trading engine database
- Runs in a separate branch: `feature/web-intelligence-collector`

---

## Local Setup (PostgreSQL)

```bash
cd services/web_intelligence
pip install -e ".[dev]"
cp .env.example .env
# Edit .env — set DATABASE_URL to your PostgreSQL instance:
# DATABASE_URL=postgresql+asyncpg://user:password@localhost:5432/web_intelligence
```

Run Alembic migrations **before** starting the service:
```bash
alembic upgrade head
```

Start the service:
```bash
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

## Docker Compose (full stack)

Starts PostgreSQL, runs migrations automatically, then starts the service:

```bash
docker compose up --build
```

The `migrate` service runs `alembic upgrade head` and waits for PostgreSQL to be ready before starting the web-intelligence container. No external healthcheck exec is needed.

Check logs:
```bash
docker compose logs -f web-intelligence
docker compose logs migrate
```

Verify it's up:
```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
```

---

## Database Migrations

```bash
# Apply all pending migrations
alembic upgrade head

# Check current revision
alembic current

# Create a new migration
alembic revision --autogenerate -m "describe your change"
```

---

## Running Tests

```bash
# Runs against an isolated in-memory SQLite DB per test — no PostgreSQL needed
DATABASE_URL=sqlite+aiosqlite:///./test.db pytest tests/ -v --tb=short
```

---

## Running Linting

```bash
ruff check app tests
mypy app --ignore-missing-imports
```

---

## CLI Commands

```bash
# List all registered sources
python -m app.cli.main list-sources

# Validate a source configuration
python -m app.cli.main validate-source <source_id>

# Trigger a collection run
python -m app.cli.main collect-source <source_id>

# Inspect a previous run
python -m app.cli.main inspect-run <run_id>

# Disable / enable a source (persists across restarts via DB)
python -m app.cli.main disable-source <source_id>
python -m app.cli.main enable-source <source_id>
```

---

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Service root / isolation confirmation |
| GET | `/health` | Liveness probe |
| GET | `/ready` | Readiness probe (DB + storage + scrapling) |
| GET | `/api/v1/sources` | List registered sources |
| GET | `/api/v1/sources/{id}` | Get a specific source |
| GET | `/api/v1/collection-runs` | List collection runs |
| GET | `/api/v1/collection-runs/{id}` | Inspect a run |
| GET | `/api/v1/intelligence` | List intelligence records |
| GET | `/api/v1/intelligence/{id}` | Get a specific record |
| GET | `/api/v1/snapshots/{id}` | Get a raw snapshot |

---

## Adding a Source Safely
See `docs/source-onboarding.md` for the mandatory checklist.

---

## Known Limitations
- POC only: no real external financial websites configured
- Scheduling is disabled by default
- Raw content is not exposed via public API
- Docker healthcheck exec is blocked in some sandbox environments;
  the compose file uses a Python TCP-probe loop inside the migrate command instead

## Why No Live Prices?
Live price collection is explicitly out of scope. This is an intelligence-support service only, not a market data feed.

## Branch and Merge Policy
- Work only on `feature/web-intelligence-collector`
- Do not modify main, develop, intraday, swing, release, or production branches
- Merge requires security and compliance review
