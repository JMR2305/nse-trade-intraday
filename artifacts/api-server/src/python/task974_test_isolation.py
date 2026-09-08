"""Test-only helpers for hermetic imports under ``sys.modules`` stubs."""

from __future__ import annotations

from contextlib import contextmanager
import os
import sys
from collections.abc import Iterator, Mapping, Sequence
from types import ModuleType


@contextmanager
def isolated_imports(
    stubs: Mapping[str, ModuleType],
    *,
    target_packages: Sequence[str] = (),
    environment: Mapping[str, str] | None = None,
) -> Iterator[None]:
    """Install test stubs and exactly restore modules and package attributes.

    ``patch.dict(sys.modules, ...)`` restores dictionary entries but cannot
    undo child-module attributes that Python adds to an already-imported
    parent package.  This helper snapshots both layers and removes cached
    target children before the test imports them under its stubs.
    """
    tracked = tuple(dict.fromkeys((*stubs.keys(), *target_packages)))
    saved_modules = {
        name: module
        for name, module in sys.modules.items()
        if any(name == prefix or name.startswith(prefix + ".") for prefix in tracked)
    }
    saved_package_dicts = {
        name: dict(module.__dict__)
        for name, module in saved_modules.items()
        if isinstance(module, ModuleType)
        and any(name == prefix or name.startswith(prefix + ".") for prefix in target_packages)
    }
    saved_environment = {
        name: os.environ.get(name) for name in (environment or {})
    }

    try:
        for name in list(sys.modules):
            if any(name == prefix or name.startswith(prefix + ".") for prefix in tracked):
                sys.modules.pop(name, None)
        sys.modules.update(stubs)
        if environment:
            os.environ.update(environment)
        yield
    finally:
        for name in list(sys.modules):
            if any(name == prefix or name.startswith(prefix + ".") for prefix in tracked):
                sys.modules.pop(name, None)
        sys.modules.update(saved_modules)
        for name, namespace in saved_package_dicts.items():
            module = sys.modules.get(name)
            if isinstance(module, ModuleType):
                module.__dict__.clear()
                module.__dict__.update(namespace)
        for name, value in saved_environment.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value
