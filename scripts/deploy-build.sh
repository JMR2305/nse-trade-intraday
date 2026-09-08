#!/usr/bin/env bash
# ApexQuant AI — Autoscale deployment build script
# Runs during Replit deployment build phase.
# Ensures Python virtual environment + Node packages + API server bundle are all built.
set -euo pipefail

echo "========================================"
echo " ApexQuant AI — Deployment Build"
echo "========================================"

echo ""
echo "--- Step 0: Capture exact source identity for artifact builds ---"
# Artifact-specific production builds run after this root pre-build hook. The
# cleanup below removes .git to keep the publish image under its size limit,
# so preserve the exact commit in a tiny non-secret handoff file.
SOURCE_COMMIT="${APEXQUANT_GIT_COMMIT:-${REPLIT_GIT_COMMIT:-${GIT_COMMIT:-${SOURCE_COMMIT:-}}}}"
if [ -z "$SOURCE_COMMIT" ]; then
  SOURCE_COMMIT="$(git rev-parse HEAD 2>/dev/null || true)"
fi
if ! [[ "$SOURCE_COMMIT" =~ ^[0-9a-fA-F]{40}$ ]]; then
  echo "Unable to resolve a full 40-character source commit for deployment." >&2
  exit 1
fi
printf '%s\n' "$SOURCE_COMMIT" > .apexquant-source-commit
export APEXQUANT_GIT_COMMIT="$SOURCE_COMMIT"
echo "    Source commit: ${SOURCE_COMMIT:0:12}"

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
echo "--- Step 1d: Prune exports/ files older than 7 days ---"
# Keep the workspace tidy during development so a future deploy never hits
# the 8 GiB image limit again.  Step 5 removes the entire exports/ directory
# from the deploy image, but this step keeps the dev workspace clean between
# deploys by removing stale files right at build time.
find exports/ -maxdepth 1 -type f -mtime +7 -delete 2>/dev/null || true
echo "    Exports older than 7 days removed (Step 5 strips the full dir from image)"

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
echo "--- Step 5: Strip build-only bloat from the deployment image ---"
# The publish image has a hard 8 GiB limit (a 2026-08-09/10 publish failed on
# it). Everything below is not needed at runtime:
#   .git         — version history (1.2+ GiB)
#   .cache/*     — uv/pip/pnpm download caches refilled by this build
#                  EXCEPT .cache/replit — it holds the module environment
#                  (PATH to node/pnpm/python). Deleting it breaks production
#                  startup with 'exec: "node": executable file not found'.
#   .pythonlibs  — dev Python env; production uses the .venv built above
#   .local/state — workspace-local logs/state
#   exports/     — user-generated CSV/PDF/ZIP output (~1 GB, grows over time,
#                  not needed at runtime — this was the root cause of the
#                  2026-08-18 promote-step timeout: the Repl layer was so large
#                  the container took >300 s to unpack, killing health checks.
#   reports/     — generated markdown/PDF reports
#   verification/ — generated verification artefacts
#   screenshots/ — dev screenshots
#   **/.mypy_cache — mypy type-check cache (~30 MB)
#   **/__pycache__ — Python bytecode (regenerated on first use; ~31 MB)
# (.local/share/pnpm is stripped in the postBuild step, after pnpm store prune.)
rm -rf .git .pythonlibs .local/state exports/ reports/ verification/ screenshots/
find .cache -mindepth 1 -maxdepth 1 ! -name replit -exec rm -rf {} + 2>/dev/null || true
find . -name ".mypy_cache" -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true
find . -name "__pycache__"  -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true
echo "    Stripped .git, .cache/*, .pythonlibs, .local/state, exports/, reports/,"
echo "             verification/, screenshots/, .mypy_cache, __pycache__"
du -sh . 2>/dev/null | awk '{print "    Image workspace size after cleanup: " $1}'

echo ""
echo "========================================"
echo " Build complete"
echo "========================================"
