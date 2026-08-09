"""Regression tests — drawdown equity must include open-position value.

Pins the Task-#15 fix in state_manager._build_snapshot(): equity for
drawdown is ``cash.total + gross exposure``.  The original bug computed
drawdown from cash-only equity, so any normally-deployed portfolio (most
capital in positions) looked like a 70%+ drawdown and every allocation was
rejected with DRAWDOWN_LIMIT_BREACHED — silently blocking all trades.
"""
from __future__ import annotations

import asyncio
import os
import sys
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from unittest import mock

_PY_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_PY_ROOT) not in sys.path:
    sys.path.insert(0, str(_PY_ROOT))

# Hermetic: never touch Postgres even when DATABASE_URL is set.
os.environ.setdefault("PORTFOLIO_SNAPSHOT_DB_DISABLED", "1")
os.environ.setdefault("PORTFOLIO_EVENT_DB_DISABLED", "1")
os.environ.setdefault("PORTFOLIO_RECON_DB_DISABLED", "1")
os.environ.setdefault("PORTFOLIO_OVERRIDES_DISABLED", "1")

from src.portfolio.config import PortfolioConfig
from src.portfolio.contracts import PositionSide
from src.portfolio.state_manager import PortfolioStateManager


def _deploy_book(sm: PortfolioStateManager) -> None:
    """Deploy most of a ₹50k book into two positions, marks near cost."""
    fills = [
        # symbol, token, qty, price — ₹30,000 of a ₹50,000 book deployed
        # (60%: far beyond the drawdown cap if equity were cash-only, while
        # leaving enough free cash above the reserve floor for a new order).
        ("RELIANCE", 1, 15, "2000"),
    ]
    for sym, tok, qty, price in fills:
        asyncio.run(sm.apply_fill(
            idempotency_key=f"fill-{sym}",
            instrument_token=tok,
            instrument_symbol=sym,
            side=PositionSide.LONG,
            quantity=qty,
            price=Decimal(price),
            fill_id=f"f-{sym}",
            filled_at=datetime.now(timezone.utc),
            order_id=f"o-{sym}",
        ))
    # Marks near cost: tiny unrealised loss, nowhere near a real drawdown.
    asyncio.run(sm.update_market_price(1, Decimal("1990")))


class TestDrawdownIncludesPositionValue(unittest.TestCase):
    """Deployed capital is equity, not a drawdown."""

    def setUp(self):
        self.config = PortfolioConfig(
            initial_capital=Decimal("50000"),
            min_order_value=Decimal("50"),
        )
        self.sm = PortfolioStateManager(self.config)
        asyncio.run(self.sm.initialise(Decimal("50000")))
        _deploy_book(self.sm)

    def test_drawdown_small_when_capital_is_deployed(self):
        snap = self.sm.get_snapshot()
        # 60% of capital deployed; cash-only equity would read as a
        # 60%+ drawdown. True drawdown is only the tiny mark-to-market dip.
        self.assertLess(
            snap.pnl.drawdown, Decimal("0.02"),
            f"drawdown {snap.pnl.drawdown} — equity is being computed "
            "from cash only, ignoring open-position value",
        )
        # Equity must include position value.
        self.assertGreater(
            snap.exposure.portfolio_equity, Decimal("49000"))

    def test_evaluate_allocation_approves_modest_request(self):
        from src.portfolio.capital_allocator import evaluate_allocation
        snap = self.sm.get_snapshot()
        decision = asyncio.run(evaluate_allocation(
            strategy_id="ai_scan",
            requested_capital=Decimal("2000"),
            snapshot=snap,
            config=self.config,
            instrument_token=99,
        ))
        self.assertNotIn("DRAWDOWN_LIMIT_BREACHED",
                         list(decision.reason_codes or ()))
        self.assertEqual(decision.status.value, "APPROVED",
                         f"rejected: {decision.reason_codes}")
        self.assertGreater(decision.approved_capital, Decimal("0"))

    def test_cash_only_equity_would_have_breached(self):
        """Sanity: the bug's arithmetic really would trip the gate — proves
        this suite guards a meaningful behavior, not a tautology."""
        snap = self.sm.get_snapshot()
        cash_only_drawdown = (
            (snap.pnl.peak_equity - snap.cash.total) / snap.pnl.peak_equity)
        self.assertGreater(cash_only_drawdown, self.config.max_drawdown_pct)


class TestBridgePreCheckOnDeployedBook(unittest.TestCase):
    """portfolio_bridge.pre_check approves a small BUY on a normal book."""

    def setUp(self):
        import portfolio_bridge
        self.pb = portfolio_bridge
        canonical = {
            "initial_capital": 50000,
            "cash": 20000.0,
            "positions": [
                {"symbol": "RELIANCE", "quantity": 15, "avg_price": 2000.0,
                 "mark_price": 1990.0, "trade_id": "t1"},
            ],
        }
        self._patches = [
            mock.patch.object(self.pb, "_canonical_state",
                              return_value=canonical),
        ]
        for p in self._patches:
            p.start()
        self.pb._service = None
        self.pb._started = False
        self.pb._startup_error = None

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.pb._service = None
        self.pb._started = False

    def test_pre_check_approves_small_buy(self):
        result = self.pb.pre_check(
            symbol="TCS", quantity=1, price=1000.0)
        self.assertNotIn(
            "DRAWDOWN_LIMIT_BREACHED", result.get("reasons") or [],
            "deployed book misread as a drawdown breach",
        )
        self.assertTrue(
            result["approved"],
            f"pre_check blocked a modest BUY on a healthy deployed book: "
            f"{result}",
        )


if __name__ == "__main__":
    unittest.main()
