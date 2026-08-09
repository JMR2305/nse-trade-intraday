"""pytest configuration for DB-backed integration tests.

These tests intentionally use the development database (isolated under
unique portfolio ids) and are kept OUT of tests/unit so the unit suite
stays hermetic.
"""
import sys
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
