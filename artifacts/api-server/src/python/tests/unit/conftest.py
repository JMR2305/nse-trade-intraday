"""pytest configuration for unit tests.

Ensures 'src' package is importable by adding the project root to sys.path.
"""
import os
import sys
from pathlib import Path

# Hermetic by default: unit tests must never write portfolio snapshots,
# events, or reconciliation history to the development Postgres database —
# polluted snapshots would otherwise be picked up by the bridge's
# recover-first startup on the next real process.  DB-backed integration
# tests lift these explicitly (and restore them) in setUp.
os.environ.setdefault("PORTFOLIO_SNAPSHOT_DB_DISABLED", "1")
os.environ.setdefault("PORTFOLIO_EVENT_DB_DISABLED", "1")
os.environ.setdefault("PORTFOLIO_RECON_DB_DISABLED", "1")

project_root = Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
