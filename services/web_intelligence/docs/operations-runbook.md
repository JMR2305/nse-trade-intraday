# Operations Runbook

## Local Setup
```bash
cd services/web_intelligence
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

## Database Migrations
```bash
alembic upgrade head
```

## Run API
```bash
uvicorn app.main:app --reload
```

## Run Fixture Collection
```bash
python -m app.cli.main collect-source local_fixture_source
```

## Run Tests
```bash
pytest tests/ -v
```

## Run Linting
```bash
ruff check app tests
mypy app
```

## Docker
```bash
docker-compose up --build
```

## Disabling a Source
```bash
python -m app.cli.main disable-source <source_id>
```
