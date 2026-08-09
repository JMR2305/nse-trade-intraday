"""Regression tests for the single-identity import namespace guard.

The source tree is importable both as ``src.<pkg>`` (root conftest, API
tests) and as bare ``<pkg>`` (intra-source imports via pythonpath=["src"]).
If those ever resolve to two distinct module objects, SQLAlchemy models get
registered twice on the shared MetaData and imports fail order-dependently
with InvalidRequestError. The conftest meta-path finder must keep the two
names aliased to ONE module object.
"""

import importlib


def _assert_same(bare: str) -> None:
    bare_mod = importlib.import_module(bare)
    src_mod = importlib.import_module(f"src.{bare}")
    assert bare_mod is src_mod, (
        f"'{bare}' and 'src.{bare}' resolved to different module objects; "
        "double-import guard in tests/conftest.py is broken"
    )


def test_database_models_single_identity():
    _assert_same("database.models")


def test_strategy_contracts_single_identity():
    _assert_same("strategy.contracts")


def test_execution_contracts_single_identity():
    _assert_same("execution.contracts")


def test_ai_forecast_config_single_identity():
    _assert_same("ai_forecast.config")


def test_market_intelligence_single_identity():
    _assert_same("market_intelligence")
