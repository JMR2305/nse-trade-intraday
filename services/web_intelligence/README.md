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

## Local Setup
```bash
cd services/web_intelligence
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
# Edit .env as needed
```

## Database Migrations
```bash
alembic upgrade head
```

## Docker Setup
```bash
docker-compose up --build
```

## Running Tests
```bash
pytest tests/ -v --tb=short
```

## Running Linting
```bash
ruff check app tests
mypy app
```

## Fixture-Based Collection
```bash
python -m app.cli.main collect-source local_fixture_source
```

## Adding a Source Safely
See `docs/source-onboarding.md` for the mandatory checklist.

## Known Limitations
- POC only: no real external financial websites configured
- Scheduling is disabled by default
- Raw content is not exposed via public API
- SQLite used for local tests; PostgreSQL for deployment

## Why No Live Prices?
Live price collection is explicitly out of scope. This is an intelligence-support service only, not a market data feed.

## Branch and Merge Policy
- Work only on `feature/web-intelligence-collector`
- Do not modify main, develop, intraday, swing, release, or production branches
- Merge requires security and compliance review
