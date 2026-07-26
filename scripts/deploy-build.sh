#!/usr/bin/env bash
# ApexQuant AI — Autoscale deployment build script
# Runs during Replit deployment build phase.
# Ensures Python virtual environment + Node packages + API server bundle are all built.
set -euo pipefail

echo "========================================"
echo " ApexQuant AI — Deployment Build"
echo "========================================"

echo ""
echo "--- Step 1: Create workspace-local virtualenv (.venv) ---"
# We explicitly create a .venv in the workspace filesystem so packages are
# guaranteed to be available at runtime.  uv sync without this flag installs
# into the Nix-managed .pythonlibs path which is rebuilt fresh on every
# runtime container start and loses anything installed during the build phase.
uv venv .venv
echo "    Virtualenv: $PWD/.venv"

echo ""
echo "--- Step 1b: Sync Python dependencies into .venv ---"
UV_PROJECT_ENVIRONMENT=.venv uv sync --frozen
echo "    Python env ready: $(.venv/bin/python3 --version)"

echo ""
echo "--- Step 1c: Write Python executable path for runtime resolution ---"
UV_PYTHON="$PWD/.venv/bin/python3"
UV_SITE=$(.venv/bin/python3 -c "import site; print(site.getsitepackages()[0])")
echo "$UV_PYTHON" > .python-exe
echo "$UV_SITE"   > .python-site
echo "    Executable : $UV_PYTHON"
echo "    Site-pkgs  : $UV_SITE"

echo ""
echo "--- Step 2: Verify critical Python imports (using .venv) ---"
.venv/bin/python3 -c "
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
