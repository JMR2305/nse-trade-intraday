"""Repository-wide pytest isolation for interpreter module state."""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import Mock

import pytest


@pytest.fixture(autouse=True)
def _restore_sys_modules_after_test():
    """Prevent one test's import stubs from becoming another test's runtime."""
    before = dict(sys.modules)
    # Python also caches child modules on their parent packages. Restoring the
    # registry alone leaves `from package import child` pointing at an object
    # that importlib.reload can no longer find (or at a test-only mock).
    packages = [
        (module, dict(vars(module)))
        for module in before.values()
        if isinstance(module, ModuleType) and "__path__" in vars(module)
    ]
    try:
        yield
    finally:
        sys.modules.clear()
        sys.modules.update(before)
        for package, namespace in packages:
            current = vars(package)
            for name in set(current) | set(namespace):
                if isinstance(current.get(name), (ModuleType, Mock)) or isinstance(
                    namespace.get(name), (ModuleType, Mock)
                ):
                    if name in namespace:
                        current[name] = namespace[name]
                    else:
                        current.pop(name, None)
