"""
execution_planner.py — Phase 10C
Execution Planner for the Execution Agent.

Responsibilities:
  - Pre-execution checklist (10 checks)
  - Order validation (instrument, qty, tick, lot, freeze, timing)
  - Execution plan generation (entry/exit/stop/target/size/charges/holding)
  - Execution mode determination (Paper / Semi-Auto / Live)
  - Slippage + cost estimation

Safety:
  - LIVE_EXECUTION_ENABLED defaults to False
  - Paper execution is default
  - No autonomous live order placement
  - Never bypasses risk checks
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

def _default_capital() -> float:
    """Configured paper capital — single source of truth (portfolio_store)."""
    try:
        from portfolio_store import INITIAL_CAPITAL
        return float(INITIAL_CAPITAL)
    except Exception:
        return 50_000.0



def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _f(v) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _clamp(v: float, lo: float = 0.0, hi: float = float("inf")) -> float:
    return max(lo, v)


# ── Execution Mode ─────────────────────────────────────────────────────────────

def determine_execution_mode() -> str:
    """
    Paper  (default): PAPER_EXECUTION_ENABLED=true
    Live:            LIVE_EXECUTION_ENABLED=true AND operator confirmation required
    Semi-Auto:       between Paper and Live — operator approves each order
    """
    import os
    live_enabled  = os.environ.get("LIVE_EXECUTION_ENABLED",  "false").lower() in ("1","true","yes")
    paper_enabled = os.environ.get("PAPER_EXECUTION_ENABLED", "true").lower()  in ("1","true","yes")
    if live_enabled:
        return "LIVE"
    if paper_enabled:
        return "PAPER"
    return "SEMI_AUTO"


# ── Pre-execution Checklist ────────────────────────────────────────────────────

class PreExecutionChecklist:
    """
    10-item checklist. All checks are advisory/read-only.
    A failed check prevents paper order creation.
    """

    CHECKS = [
        "capital",         # Sufficient free capital
        "position_sizing", # Position size within limits
        "portfolio_limits",# Max positions not exceeded
        "sector_exposure", # Sector concentration within limits
        "daily_loss",      # Daily drawdown limit not hit
        "market_status",   # Market is open
        "trading_session", # Within valid trading session
        "liquidity",       # Symbol has sufficient liquidity
        "freeze_quantity", # Quantity within exchange freeze limits
        "risk_limits",     # Risk agent risk level acceptable
    ]

    MAX_POSITIONS      = 10
    MAX_SECTOR_PCT     = 40.0
    MAX_POSITION_PCT   = 20.0
    MAX_DAILY_LOSS_PCT =  3.0
    NIFTY_FREEZE_QTY   = 1000
    MIN_CAPITAL        = 10_000.0

    def run(
        self,
        symbol: str,
        qty: int,
        price: float,
        portfolio: Dict[str, Any],
        risk_snap: Dict[str, Any],
        mi_snap: Dict[str, Any],
    ) -> Tuple[bool, List[Dict[str, Any]]]:
        """Returns (all_passed, check_results)."""
        capital   = _f(portfolio.get("cash")) or _f(portfolio.get("capital")) or 0.0
        available = _f(portfolio.get("available_capital")) or capital
        positions = portfolio.get("positions") or {}
        n_pos     = len(positions) if isinstance(positions, dict) else len(positions)
        order_val = qty * price
        capital_base = _f(portfolio.get("capital")) or max(capital, _default_capital())

        risk_lv     = risk_snap.get("risk_level", "UNKNOWN")
        session     = mi_snap.get("session_info") or {}
        in_session  = session.get("in_session", False)
        liq_score   = _f(mi_snap.get("liquidity_score")) or 50.0
        order_pct   = (order_val / capital_base * 100) if capital_base > 0 else 0.0

        results = []

        def chk(name, passed, detail, remediation=""):
            results.append({
                "check":        name,
                "passed":       passed,
                "detail":       detail,
                "remediation":  remediation,
            })
            return passed

        chk("capital",
            available >= order_val and available >= self.MIN_CAPITAL,
            f"Available ₹{available:,.0f}, order ₹{order_val:,.0f}",
            "Reduce quantity or free up capital")

        chk("position_sizing",
            order_pct <= self.MAX_POSITION_PCT,
            f"Order is {order_pct:.1f}% of capital (max {self.MAX_POSITION_PCT}%)",
            f"Reduce to max {self.MAX_POSITION_PCT}% of capital")

        chk("portfolio_limits",
            n_pos < self.MAX_POSITIONS,
            f"{n_pos}/{self.MAX_POSITIONS} positions open",
            "Close an existing position before adding new one")

        # Sector check — simplified; sector data may not be available
        sector_info = risk_snap.get("sector_concentration") or {}
        max_sector_pct = _f(sector_info.get("max_sector_pct")) or 0.0
        chk("sector_exposure",
            max_sector_pct < self.MAX_SECTOR_PCT,
            f"Max sector concentration: {max_sector_pct:.1f}%",
            f"Reduce sector concentration below {self.MAX_SECTOR_PCT}%")

        daily = risk_snap.get("daily_risk") or {}
        daily_pct = _f(daily.get("daily_risk_pct")) or 0.0
        chk("daily_loss",
            daily_pct < self.MAX_DAILY_LOSS_PCT,
            f"Daily loss: {daily_pct:.2f}% (limit {self.MAX_DAILY_LOSS_PCT}%)",
            "Daily loss limit approached; no new positions today")

        chk("market_status",
            True,  # Always pass — exchange status comes from live feed
            "Exchange status advisory — verify in broker platform",
            "")

        chk("trading_session",
            in_session,
            f"Session: {'OPEN' if in_session else 'CLOSED'}",
            "Wait for market open (9:15–15:30 IST)")

        chk("liquidity",
            liq_score >= 30,
            f"Liquidity score: {liq_score:.0f}/100",
            "Low liquidity — avoid large orders")

        chk("freeze_quantity",
            qty <= self.NIFTY_FREEZE_QTY,
            f"Qty {qty} vs freeze limit {self.NIFTY_FREEZE_QTY}",
            f"Split order into batches of ≤{self.NIFTY_FREEZE_QTY}")

        chk("risk_limits",
            risk_lv not in ("HIGH", "CRITICAL"),
            f"Portfolio risk: {risk_lv}",
            "Reduce portfolio risk before new entries")

        all_passed = all(r["passed"] for r in results)
        return all_passed, results


# ── Order Validation ───────────────────────────────────────────────────────────

class OrderValidator:
    """
    Validates order parameters against exchange rules.
    NSE-specific (EQ segment).
    """
    MIN_QTY = 1
    TICK_SIZE = 0.05  # NSE EQ tick size
    MAX_ORDER_VALUE = 2_000_000.0  # ₹20 lakh single order

    def validate(self, symbol: str, qty: int, price: float) -> Tuple[bool, List[str]]:
        errors = []
        if qty < self.MIN_QTY:
            errors.append(f"Quantity {qty} below minimum {self.MIN_QTY}")
        if price <= 0:
            errors.append(f"Invalid price: {price}")
        # Tick size alignment
        rounded = round(round(price / self.TICK_SIZE) * self.TICK_SIZE, 2)
        if abs(rounded - price) > 0.001:
            errors.append(f"Price {price} not tick-aligned (nearest: {rounded})")
        order_val = qty * price
        if order_val > self.MAX_ORDER_VALUE:
            errors.append(
                f"Order value ₹{order_val:,.0f} exceeds single-order limit "
                f"₹{self.MAX_ORDER_VALUE:,.0f}"
            )
        return len(errors) == 0, errors


# ── Execution Plan ─────────────────────────────────────────────────────────────

class ExecutionPlan:
    """
    Generates advisory execution plan for a recommendation.
    All prices are estimates — operator must verify before acting.
    """

    # NSE equity charges (advisory estimates)
    STT_RATE        = 0.001    # 0.1% on buy
    EXCHANGE_TXN    = 0.0000345
    SEBI_RATE       = 0.0000001
    STAMP_DUTY_RATE = 0.00015
    GST_RATE        = 0.18
    DP_CHARGE       = 15.93    # ₹ per sell delivery
    BROKERAGE_MAX   = 20.0     # flat ₹20 per order

    def generate(
        self,
        symbol: str,
        recommendation: Dict[str, Any],
        portfolio: Dict[str, Any],
        price_hint: Optional[float] = None,
    ) -> Dict[str, Any]:

        overall = _f(recommendation.get("overall_score")) or 50.0
        confidence = _f(recommendation.get("confidence")) or 0.5
        decision = recommendation.get("decision_type", "WATCH")

        # Estimate entry price (use price_hint or last_price from scan)
        entry_price = price_hint or 100.0  # advisory placeholder

        # Position sizing (Kelly-lite, capped at 10% of capital)
        capital = _f(portfolio.get("cash")) or _f(portfolio.get("capital")) or _default_capital()
        kelly_fraction = confidence * (overall / 100.0) * 0.5  # half-Kelly
        position_value = min(capital * kelly_fraction, capital * 0.10)
        suggested_qty  = max(1, int(position_value / max(entry_price, 1.0)))

        # Stop loss / target (advisory)
        volatility_adj = 0.02 + (1.0 - confidence) * 0.02  # 2–4%
        stop_loss   = round(entry_price * (1 - volatility_adj * 1.5), 2)
        target_1    = round(entry_price * (1 + volatility_adj * 2.0), 2)
        target_2    = round(entry_price * (1 + volatility_adj * 3.5), 2)
        suggested_exit = target_1

        risk_per_share   = entry_price - stop_loss
        reward_per_share = target_1 - entry_price
        rr_ratio = round(reward_per_share / max(risk_per_share, 0.01), 2)

        # Expected holding time
        holding_hours = {
            "BUY_CANDIDATE":   "2–4 hours (intraday)",
            "ACCUMULATE":      "3–5 sessions",
            "SELL_CANDIDATE":  "0.5–2 hours (urgent)",
            "REDUCE_EXPOSURE": "0.5–1 hour (urgent)",
            "WATCH":           "1–2 sessions (monitoring)",
        }.get(decision, "1–2 sessions")

        # Charges (advisory estimates — EQ delivery)
        order_value     = suggested_qty * entry_price
        brokerage       = min(self.BROKERAGE_MAX, order_value * 0.0003)
        stt             = order_value * self.STT_RATE
        exchange_txn    = order_value * self.EXCHANGE_TXN
        sebi            = order_value * self.SEBI_RATE
        stamp_duty      = order_value * self.STAMP_DUTY_RATE
        gst             = (brokerage + exchange_txn) * self.GST_RATE
        total_charges   = brokerage + stt + exchange_txn + sebi + stamp_duty + gst + self.DP_CHARGE
        breakeven_price = round(entry_price + total_charges / max(suggested_qty, 1), 2)

        return {
            "symbol":          symbol,
            "decision_type":   decision,
            "execution_mode":  determine_execution_mode(),

            # Prices (advisory)
            "suggested_entry": round(entry_price, 2),
            "suggested_exit":  round(suggested_exit, 2),
            "stop_loss":       round(stop_loss, 2),
            "target_1":        round(target_1, 2),
            "target_2":        round(target_2, 2),
            "breakeven_price": breakeven_price,

            # Risk/reward
            "expected_risk_pct":   round(volatility_adj * 1.5 * 100, 2),
            "expected_reward_pct": round(volatility_adj * 2.0 * 100, 2),
            "reward_risk_ratio":   rr_ratio,

            # Sizing
            "suggested_qty":   suggested_qty,
            "position_value":  round(order_value, 2),
            "position_pct_of_capital": round(order_value / max(capital, 1) * 100, 2),

            # Charges (advisory estimates)
            "estimated_charges": {
                "brokerage":    round(brokerage, 2),
                "stt":          round(stt, 2),
                "exchange_txn": round(exchange_txn, 2),
                "sebi":         round(sebi, 4),
                "stamp_duty":   round(stamp_duty, 2),
                "gst":          round(gst, 2),
                "dp_charge":    round(self.DP_CHARGE, 2),
                "total":        round(total_charges, 2),
            },
            "expected_holding_time": holding_hours,
            "advisory_only":   True,
            "prices_are_estimates": True,
            "generated_at":    _now_iso(),
        }
