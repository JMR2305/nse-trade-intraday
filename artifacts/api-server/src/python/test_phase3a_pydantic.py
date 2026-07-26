"""
test_phase3a_pydantic.py — Phase 3A: Pydantic + PortfolioConfig regression tests.

Verifies that pydantic>=2.0 is available and that PortfolioConfig:
  - loads successfully with defaults
  - exposes all expected limit fields
  - rejects invalid negative values
  - rejects excessive exposure
  - rejects malformed types
  - enforces paper_mode=True
  - rejects inconsistent limit combinations
  - provides working convenience methods

PAPER TRADING / RESEARCH ONLY. No live broker calls.

Run:
    uv run python test_phase3a_pydantic.py
"""

import sys
import os
from decimal import Decimal

PASS = 0
FAIL = 0
_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  PASS  {name}")
    else:
        FAIL += 1
        _FAILURES.append(name)
        print(f"  FAIL  {name}  {detail}")


# ── T1: pydantic available ────────────────────────────────────────────────────
print("== T1: pydantic import ==")
try:
    import pydantic
    check("pydantic importable", True)
    check("pydantic version >= 2.0", int(pydantic.__version__.split(".")[0]) >= 2,
          f"got {pydantic.__version__}")
except ImportError as e:
    check("pydantic importable", False, str(e))
    check("pydantic version >= 2.0", False, "import failed")

# ── T2: PortfolioConfig loads ─────────────────────────────────────────────────
print("\n== T2: PortfolioConfig default load ==")
try:
    sys.path.insert(0, os.path.dirname(__file__))
    from src.portfolio.config import PortfolioConfig
    cfg = PortfolioConfig()
    check("PortfolioConfig instantiates", True)
    check("paper_mode is True", cfg.paper_mode is True)
    check("base_currency is INR", cfg.base_currency == "INR")
    check("initial_capital > 0", cfg.initial_capital > 0)
except Exception as e:
    check("PortfolioConfig instantiates", False, str(e))
    check("paper_mode is True", False, "load failed")
    check("base_currency is INR", False, "load failed")
    check("initial_capital > 0", False, "load failed")

# ── T3: all required limit fields present ────────────────────────────────────
print("\n== T3: Required limit fields ==")
try:
    cfg = PortfolioConfig()
    required = [
        "max_portfolio_exposure_pct", "max_instrument_exposure_pct",
        "max_sector_exposure_pct", "max_strategy_exposure_pct",
        "max_open_positions", "max_pending_orders",
        "max_daily_loss_pct", "max_drawdown_pct",
        "default_risk_per_trade_pct", "min_order_value", "max_order_value",
        "stale_state_threshold_s", "stale_price_threshold_s",
    ]
    for field in required:
        val = getattr(cfg, field, None)
        check(f"field '{field}' present and non-None", val is not None,
              f"got {val!r}")
except Exception as e:
    check("all required fields accessible", False, str(e))

# ── T4: missing optional fields use defaults ──────────────────────────────────
print("\n== T4: Optional fields default safely ==")
try:
    # Construct with explicit minimal values
    cfg2 = PortfolioConfig(
        initial_capital=Decimal("50000"),
        max_open_positions=5,
    )
    check("partial construction succeeds", True)
    check("initial_capital overridden", cfg2.initial_capital == Decimal("50000"))
    check("max_open_positions overridden", cfg2.max_open_positions == 5)
    check("paper_mode still True in partial config", cfg2.paper_mode is True)
    check("max_daily_loss_pct defaults to safe value",
          Decimal("0") < cfg2.max_daily_loss_pct <= Decimal("0.10"),
          f"got {cfg2.max_daily_loss_pct}")
except Exception as e:
    check("partial construction succeeds", False, str(e))

# ── T5: invalid negative values rejected ─────────────────────────────────────
print("\n== T5: Negative values rejected ==")
from pydantic import ValidationError

try:
    PortfolioConfig(max_daily_loss_pct=Decimal("-0.01"))
    check("negative max_daily_loss_pct rejected", False, "no error raised")
except ValidationError:
    check("negative max_daily_loss_pct rejected", True)
except Exception as e:
    check("negative max_daily_loss_pct rejected", False, str(e))

try:
    PortfolioConfig(initial_capital=Decimal("-1000"))
    check("negative initial_capital rejected", False, "no error raised")
except ValidationError:
    check("negative initial_capital rejected", True)
except Exception as e:
    check("negative initial_capital rejected", False, str(e))

try:
    PortfolioConfig(default_risk_per_trade_pct=Decimal("-0.05"))
    check("negative risk_per_trade rejected", False, "no error raised")
except ValidationError:
    check("negative risk_per_trade rejected", True)
except Exception as e:
    check("negative risk_per_trade rejected", False, str(e))

# ── T6: excessive exposure rejected ──────────────────────────────────────────
print("\n== T6: Excessive exposure rejected ==")
try:
    # Exposure > 1.0 should fail the (0, 1] validator
    PortfolioConfig(max_portfolio_exposure_pct=Decimal("1.5"))
    check("exposure > 1.0 rejected", False, "no error raised")
except ValidationError:
    check("exposure > 1.0 rejected", True)
except Exception as e:
    check("exposure > 1.0 rejected", False, str(e))

try:
    # cash_reserve + max_exposure > 1.0 should fail model_validator
    PortfolioConfig(
        cash_reserve_pct=Decimal("0.20"),
        max_portfolio_exposure_pct=Decimal("0.90"),
    )
    check("reserve+exposure > 1.0 rejected", False, "no error raised")
except ValidationError:
    check("reserve+exposure > 1.0 rejected", True)
except Exception as e:
    check("reserve+exposure > 1.0 rejected", False, str(e))

# ── T7: malformed types rejected ─────────────────────────────────────────────
print("\n== T7: Malformed types rejected ==")
try:
    PortfolioConfig(max_open_positions=-1)
    check("max_open_positions=-1 rejected", False, "no error raised")
except ValidationError:
    check("max_open_positions=-1 rejected", True)
except Exception as e:
    check("max_open_positions=-1 rejected", False, str(e))

try:
    PortfolioConfig(min_order_value=Decimal("0"))
    check("min_order_value=0 rejected", False, "no error raised")
except ValidationError:
    check("min_order_value=0 rejected", True)
except Exception as e:
    check("min_order_value=0 rejected", False, str(e))

# ── T8: paper_mode cannot be set to False ────────────────────────────────────
print("\n== T8: paper_mode=True enforced ==")
try:
    PortfolioConfig(paper_mode=False)
    check("paper_mode=False rejected", False, "no error raised — SAFETY VIOLATION")
except ValidationError:
    check("paper_mode=False rejected", True)
except Exception as e:
    check("paper_mode=False rejected", False, str(e))

# ── T9: min_order_value >= max_order_value rejected ──────────────────────────
print("\n== T9: Order value consistency enforced ==")
try:
    PortfolioConfig(
        min_order_value=Decimal("50000"),
        max_order_value=Decimal("5000"),
    )
    check("min >= max order_value rejected", False, "no error raised")
except ValidationError:
    check("min >= max order_value rejected", True)
except Exception as e:
    check("min >= max order_value rejected", False, str(e))

# ── T10: convenience methods work ────────────────────────────────────────────
print("\n== T10: Convenience methods ==")
try:
    cfg = PortfolioConfig()
    equity = Decimal("100000")
    reserve = cfg.reserve_amount(equity)
    deployable = cfg.max_deployable(equity)
    daily_loss = cfg.max_daily_loss_amount(equity)
    risk_amt = cfg.risk_amount(equity)
    check("reserve_amount positive", reserve > 0, f"got {reserve}")
    check("max_deployable positive", deployable > 0, f"got {deployable}")
    check("reserve + deployable <= equity",
          reserve + deployable <= equity,
          f"reserve={reserve} deployable={deployable}")
    check("max_daily_loss_amount positive", daily_loss > 0, f"got {daily_loss}")
    check("risk_amount positive", risk_amt > 0, f"got {risk_amt}")
except Exception as e:
    check("convenience methods work", False, str(e))

# ── T11: fallback behavior when config unavailable ───────────────────────────
print("\n== T11: Fallback behavior ==")
# Simulate what portfolio_snapshot.py does when PortfolioConfig is unavailable
HARDCODED_DEFAULTS = {
    "max_instrument_pct": 0.20,
    "max_sector_pct": 0.35,
    "max_portfolio_pct": 0.90,
}
try:
    cfg = PortfolioConfig()
    loaded = True
except Exception:
    loaded = False
check("config loaded (not using hardcoded fallback)", loaded)
if loaded:
    check("config max_instrument_pct is conservative",
          float(cfg.max_instrument_exposure_pct) <= HARDCODED_DEFAULTS["max_instrument_pct"] * 2,
          f"got {cfg.max_instrument_exposure_pct}")
    check("config max_sector_pct is conservative",
          float(cfg.max_sector_exposure_pct) <= HARDCODED_DEFAULTS["max_sector_pct"] * 2,
          f"got {cfg.max_sector_exposure_pct}")

# ── T12: frozen config cannot be mutated ─────────────────────────────────────
print("\n== T12: Config immutability ==")
try:
    cfg = PortfolioConfig()
    cfg.paper_mode = False  # type: ignore
    check("frozen config rejects mutation", False, "mutation succeeded — SAFETY VIOLATION")
except Exception:
    check("frozen config rejects mutation", True)

# ── Result ───────────────────────────────────────────────────────────────────
print(f"\n{'=' * 60}")
print(f"Phase 3A Pydantic tests: {PASS} passed, {FAIL} failed")
if _FAILURES:
    for f in _FAILURES:
        print(f"  FAIL: {f}")
print("=" * 60)

if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
