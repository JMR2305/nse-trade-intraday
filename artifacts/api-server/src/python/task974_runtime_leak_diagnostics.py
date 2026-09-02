"""Pytest plugin that records the first runtime producer of module-stub leaks."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from types import ModuleType
from unittest.mock import Mock

import pytest


WATCHED_MODULES = (
    "phase20_store",
    "canonical_portfolio",
    "market_intelligence_hub",
    "research_lab",
    "event_intelligence",
    "macro_intelligence",
    "explainable_ai",
)
WATCHED_CHILDREN = ("shared_services",)
OUTPUT = Path("TASK_974_RUNTIME_MODULE_LEAKS.json")
_baseline: dict[str, dict] = {}
_events: list[dict] = []


def _describe(name: str) -> dict:
    module = sys.modules.get(name)
    if module is None:
        return {"present": False}
    result = {
        "present": True,
        "identity": id(module),
        "type": type(module).__name__,
        "file": getattr(module, "__file__", None),
        "is_mock": isinstance(module, Mock),
    }
    if isinstance(module, ModuleType):
        result["children"] = {
            child: {
                "identity": id(value),
                "type": type(value).__name__,
                "file": getattr(value, "__file__", None),
                "is_mock": isinstance(value, Mock),
            }
            for child in WATCHED_CHILDREN
            if (value := getattr(module, child, None)) is not None
        }
    return result


def _snapshot() -> dict[str, dict]:
    return {name: _describe(name) for name in WATCHED_MODULES}


def pytest_collection_finish(session):  # noqa: ARG001
    global _baseline
    _baseline = _snapshot()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):  # noqa: ARG001
    yield
    current = _snapshot()
    changes = {
        name: {"before": _baseline[name], "after": current[name]}
        for name in WATCHED_MODULES
        if current[name] != _baseline[name]
    }
    if changes:
        _events.append({"after_test": item.nodeid, "changes": changes})


def pytest_sessionfinish(session, exitstatus):  # noqa: ARG001
    OUTPUT.write_text(json.dumps({
        "collection_baseline": _baseline,
        "first_runtime_change": _events[0] if _events else None,
        "runtime_change_count": len(_events),
        "runtime_changes": _events[:25],
    }, indent=2, sort_keys=True) + "\n")
