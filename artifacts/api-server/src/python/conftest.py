"""Repository-wide pytest isolation for interpreter module state."""

from __future__ import annotations

import sys

import pytest


@pytest.fixture(autouse=True)
def _restore_sys_modules_after_test():
    """Prevent one test's import stubs from becoming another test's runtime."""
    before = dict(sys.modules)
    try:
        yield
    finally:
        sys.modules.clear()
        sys.modules.update(before)
