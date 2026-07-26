#!/usr/bin/env bash
# ApexQuant AI — Autoscale deployment build script
# Runs during Replit deployment build phase.
# Ensures Python virtual environment + Node packages + API server bundle are all built.
set -euo pipefail

echo "========================================"
echo " ApexQuant AI — Deployment Build"
echo "========================================"

echo ""
echo "--- Step 1: Sync Python dependencies (uv sync --frozen) ---"
uv sync --frozen
echo "    Python env ready: $(uv run python --version)"

echo ""
echo "--- Step 2: Verify critical Python imports ---"
uv run python -c "
imports = [
    'yfinance', 'pydantic', 'pandas', 'numpy',
    'sqlalchemy', 'asyncpg', 'psycopg2',
    'kiteconnect', 'reportlab', 'openpyxl'
]
failed = []
for m in imports:
    try:
        __import__(m)
    except ImportError as e:
        failed.append(f'{m}: {e}')
if failed:
    print('MISSING IMPORTS:')
    for f in failed:
        print(f'  {f}')
    raise SystemExit(1)
print(f'  All {len(imports)} critical Python imports OK')
"

echo ""
echo "--- Step 3: Install Node dependencies ---"
pnpm install --frozen-lockfile

echo ""
echo "--- Step 4: Build API server bundle ---"
pnpm --filter @workspace/api-server run build

echo ""
echo "========================================"
echo " Build complete"
echo "========================================"
