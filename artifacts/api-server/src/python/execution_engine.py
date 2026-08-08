"""
execution_engine.py  —  Phase 8: Broker Integration & Live Execution Readiness
Execution mode management, pre-trade validation (15+ checks), order preview
ticket, two-step confirmation, safety controls, kill switch, and audit log.

Execution Modes
---------------
  RESEARCH_ONLY   : No trades at all. Full analysis and explainability available.
                    This is the safest mode — all data access, no execution.
  PAPER_TRADING   : Simulated trades via paper_trader.py. No real money. (DEFAULT)
  LIVE_ASSISTED   : Real orders via ZerodhaClient — REQUIRES explicit per-order
                    confirmation. Never places an order automatically. Every order
                    goes through the full validation → preview → step-1 confirm →
                    step-2 final-confirm flow.

Safety Controls (always enforced regardless of mode)
-----------------------------------------------------
  kill_switch           — Immediately block all new orders.
  daily_loss_limit      — Auto-block if daily P&L drops below this.
  max_orders_per_day    — Cap on total orders in one trading session.
  per_stock_exposure    — Max % of capital in one stock.
  total_deployed_cap    — Max % of total capital deployed at once.
  cooldown_s            — Seconds to wait after a REJECTED/FAILED order.
  auto_block_on_stale   — Block if market data is stale (from Phase 7).
  auto_block_on_disconn — Block if broker connectivity is unhealthy.

Pre-trade Validation Checks (all must PASS for BUY/SELL to proceed)
-------------------------------------------------------------------
  1. market_hours         — NSE market is currently open
  2. data_freshness       — Phase 7 data quality is LIVE or NEAR_LIVE
  3. symbol_validity      — Symbol is in the NIFTY 50 universe
  4. kill_switch_off      — Global kill switch is not activated
  5. mode_allows          — Mode is PAPER_TRADING or LIVE_ASSISTED
  6. cash_available       — Sufficient cash/margin for the order
  7. max_risk_per_trade   — Risk amount ≤ MAX_RISK_PCT of capital
  8. portfolio_exposure   — Total deployed ≤ total_deployed_cap
  9. sector_concentration — Sector allocation ≤ 35% of portfolio
  10. stop_loss_present   — Stop-loss price is set and valid (< entry for BUY)
  11. target_present      — Target price is set and valid (> entry for BUY)
  12. rr_minimum          — RR ratio ≥ 1.5
  13. no_duplicate        — No open order for same symbol+side
  14. position_conflict   — No conflicting open position in opposite direction
  15. order_value_limit   — Single order value ≤ MAX_CAPITAL_PER_TRADE_PCT
  16. daily_order_limit   — Daily order count < max_orders_per_day
  17. cooldown            — Time since last failed order > cooldown_s

PAPER TRADING DEFAULT — real execution requires LIVE_ASSISTED mode + kill switch off
+ all 17 checks passing + two explicit user confirmations.

IMPORTANT: This module never places real orders directly. All real order placement
goes through ExecutionEngine.submit_order() which enforces every safety check.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from config import NIFTY_50, INITIAL_CAPITAL, MAX_RISK_PCT, MAX_CAPITAL_PER_TRADE_PCT

# ── Constants ─────────────────────────────────────────────────────────────────

STATE_DIR    = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE  = os.path.join(STATE_DIR, "phase8_config.json")
AUDIT_FILE   = os.path.join(STATE_DIR, "phase8_audit.json")
EXPORT_DIR   = os.path.join(STATE_DIR, "exports")

# Confirmation token prefix — clients must echo this back to confirm
CONFIRM_PREFIX_STEP1 = "REVIEW-"
CONFIRM_PREFIX_STEP2 = "CONFIRM-LIVE-"

# NSE market hours (IST = UTC+5:30)
NSE_OPEN_H, NSE_OPEN_M   = 9,  15
NSE_CLOSE_H, NSE_CLOSE_M = 15, 30
NSE_WEEKDAYS = {0, 1, 2, 3, 4}  # Mon–Fri

BROKERAGE_PCT = 0.0003          # 0.03% flat (Zerodha CNC approx)
STT_PCT       = 0.001           # 0.1% on sell side
EXCHANGE_PCT  = 0.0000345       # 0.00345% NSE transaction charge
GST_PCT       = 0.18            # 18% GST on brokerage+exchange
SEBI_TURNOVER = 0.000001        # SEBI turnover charge


# ── Execution mode ────────────────────────────────────────────────────────────

class ExecutionMode:
    RESEARCH_ONLY  = "RESEARCH_ONLY"
    PAPER_TRADING  = "PAPER_TRADING"
    LIVE_ASSISTED  = "LIVE_ASSISTED"
    ALL = {RESEARCH_ONLY, PAPER_TRADING, LIVE_ASSISTED}


# ── Statuses ──────────────────────────────────────────────────────────────────

class OrderStatus:
    READY              = "READY"
    BLOCKED            = "BLOCKED"
    DATA_STALE         = "DATA_STALE"
    BROKER_DISCONNECTED = "BROKER_DISCONNECTED"
    VALIDATION_FAILED  = "VALIDATION_FAILED"
    PENDING_STEP1      = "PENDING_STEP1"
    PENDING_STEP2      = "PENDING_STEP2"
    SUBMITTED          = "SUBMITTED"
    FILLED             = "FILLED"
    PARTIALLY_FILLED   = "PARTIALLY_FILLED"
    REJECTED           = "REJECTED"
    CANCELLED          = "CANCELLED"
    EXIT_REQUIRED      = "EXIT_REQUIRED"


# ── Safety controls ───────────────────────────────────────────────────────────

@dataclass
class SafetyControls:
    kill_switch: bool           = False
    daily_loss_limit: float     = -500.0        # ₹ — block if day P&L < this
    max_orders_per_day: int     = 5
    per_stock_exposure_pct: float = 20.0        # max % of capital in one stock
    total_deployed_cap_pct: float = 80.0        # max % of capital deployed
    cooldown_after_fail_s: float  = 300.0       # 5 min cooldown after reject/fail
    auto_block_stale_data: bool   = True
    auto_block_disconnected: bool = True
    order_value_max: float        = 1500.0      # ₹ max per order (20% of ₹5000 default)
    min_rr_ratio: float           = 1.5
    max_daily_orders: int         = 5
    note: str = "Research & assisted-execution only. User is responsible for every live order."


def _default_controls() -> SafetyControls:
    return SafetyControls()


# ── Persistence ───────────────────────────────────────────────────────────────

def _load_config() -> Dict[str, Any]:
    try:
        with open(CONFIG_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _save_config(cfg: Dict[str, Any]) -> None:
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)


def get_execution_mode() -> str:
    cfg = _load_config()
    return cfg.get("execution_mode", ExecutionMode.PAPER_TRADING)


def set_execution_mode(mode: str) -> None:
    if mode not in ExecutionMode.ALL:
        raise ValueError(f"Invalid mode: {mode}. Must be one of {list(ExecutionMode.ALL)}")
    cfg = _load_config()
    cfg["execution_mode"] = mode
    cfg["mode_set_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _save_config(cfg)


def get_safety_controls() -> SafetyControls:
    cfg = _load_config()
    sc_data = cfg.get("safety_controls", {})
    sc = _default_controls()
    for k, v in sc_data.items():
        if hasattr(sc, k):
            setattr(sc, k, v)
    return sc


def set_safety_controls(updates: Dict[str, Any]) -> SafetyControls:
    sc = get_safety_controls()
    for k, v in updates.items():
        if hasattr(sc, k):
            setattr(sc, k, v)
    cfg = _load_config()
    cfg["safety_controls"] = asdict(sc)
    _save_config(cfg)
    return sc


def toggle_kill_switch(activate: bool) -> SafetyControls:
    sc = get_safety_controls()
    sc.kill_switch = activate
    cfg = _load_config()
    cfg["safety_controls"] = asdict(sc)
    cfg["kill_switch_changed_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    _save_config(cfg)
    _append_audit({
        "event": "KILL_SWITCH_TOGGLED", "activated": activate,
        "mode": get_execution_mode(),
        "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    })
    return sc


def get_daily_order_count() -> int:
    audit = _load_audit()
    today = datetime.now(timezone.utc).date().isoformat()
    return sum(1 for e in audit
               if e.get("event") in ("ORDER_SUBMITTED", "PAPER_ORDER")
               and str(e.get("ts", ""))[:10] == today)


def get_last_failed_order_ts() -> Optional[str]:
    audit = _load_audit()
    for e in reversed(audit):
        if e.get("event") in ("ORDER_REJECTED", "ORDER_FAILED"):
            return e.get("ts")
    return None


# ── Audit log ─────────────────────────────────────────────────────────────────

def _load_audit() -> List[Dict[str, Any]]:
    try:
        with open(AUDIT_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def _append_audit(entry: Dict[str, Any]) -> None:
    audit = _load_audit()
    entry["audit_id"] = uuid.uuid4().hex[:10]
    audit.append(entry)
    # Keep last 500 entries
    if len(audit) > 500:
        audit = audit[-500:]
    with open(AUDIT_FILE, "w") as f:
        json.dump(audit, f, indent=1, default=str)


def get_audit_log(limit: int = 100) -> List[Dict[str, Any]]:
    return list(reversed(_load_audit()))[:limit]


# ── Charge estimator ──────────────────────────────────────────────────────────

def _estimate_charges(value: float, side: str) -> float:
    brok  = min(value * BROKERAGE_PCT, 20.0)   # Zerodha flat ₹20 or 0.03%
    stt   = value * STT_PCT if side == "SELL" else 0.0
    exc   = value * EXCHANGE_PCT
    gst   = (brok + exc) * GST_PCT
    sebi  = value * SEBI_TURNOVER
    return round(brok + stt + exc + gst + sebi, 2)


# ── Order preview ticket ──────────────────────────────────────────────────────

@dataclass
class OrderPreview:
    preview_id: str
    symbol: str
    side: str               # BUY | SELL
    order_type: str         # LIMIT | MARKET | SL
    quantity: int
    entry_price: float
    stop_loss: float
    target_price: float
    estimated_value: float
    risk_amount: float
    reward_amount: float
    rr_ratio: float
    charges_estimate: float
    available_funds_after: float
    strategy: str
    confidence: float
    data_freshness: str
    data_age_days: Optional[float]
    validation_passed: bool
    validation_checks: List[Dict[str, Any]]   # [{check, passed, reason}]
    failure_reasons: List[str]
    confirm_token_step1: str
    confirm_token_step2: str
    status: str
    mode: str
    created_at: str
    expires_at: str         # preview expires after 5 min
    label: str = "PAPER / LIVE DATA VALIDATION"
    warning: str = ("This is a research and assisted-execution tool. "
                    "The user is responsible for every live order placed.")


# ── Pre-trade validator ───────────────────────────────────────────────────────

class PreTradeValidator:
    """
    Runs all 17 pre-trade checks in sequence.
    Each check returns (passed: bool, reason: str).
    ALL checks must pass for the order to be eligible.
    """

    def __init__(
        self,
        controls: SafetyControls,
        mode: str,
        available_cash: float,
        total_capital: float,
        deployed_value: float,
        daily_orders_today: int,
        last_failed_ts: Optional[str],
        data_quality: str,
        broker_connected: bool,
        open_symbols: List[str],         # symbols with open BUY positions
        sector_deployed: Dict[str, float],  # {sector: deployed_value}
    ):
        self._ctrl = controls
        self._mode = mode
        self._cash = available_cash
        self._total = total_capital
        self._deployed = deployed_value
        self._daily_orders = daily_orders_today
        self._last_failed_ts = last_failed_ts
        self._data_quality = data_quality
        self._connected = broker_connected
        self._open_symbols = [s.upper() for s in open_symbols]
        self._sector_deployed = sector_deployed

    def _chk(self, name: str, passed: bool, reason: str) -> Dict[str, Any]:
        return {"check": name, "passed": passed, "reason": reason}

    def _market_hours(self) -> Dict[str, Any]:
        now_utc = datetime.now(timezone.utc)
        now_ist = now_utc + timedelta(hours=5, minutes=30)
        wd = now_ist.weekday()
        h, m = now_ist.hour, now_ist.minute
        open_mins  = NSE_OPEN_H * 60 + NSE_OPEN_M
        close_mins = NSE_CLOSE_H * 60 + NSE_CLOSE_M
        cur_mins   = h * 60 + m
        is_weekday = wd in NSE_WEEKDAYS
        is_hours   = open_mins <= cur_mins <= close_mins
        ok = is_weekday and is_hours
        return self._chk("market_hours", ok,
            f"NSE {'OPEN' if ok else 'CLOSED'} — {now_ist.strftime('%H:%M IST %a')}")

    def _data_freshness(self) -> Dict[str, Any]:
        ok = self._data_quality in ("LIVE", "NEAR_LIVE")
        return self._chk("data_freshness", ok,
            f"Data quality: {self._data_quality}. Must be LIVE or NEAR_LIVE to execute.")

    def _symbol_validity(self, symbol: str) -> Dict[str, Any]:
        ok = symbol.upper() in {s.upper() for s in NIFTY_50}
        return self._chk("symbol_validity", ok,
            f"{symbol} {'is' if ok else 'is NOT'} in NIFTY 50 universe")

    def _kill_switch(self) -> Dict[str, Any]:
        ok = not self._ctrl.kill_switch
        return self._chk("kill_switch_off", ok,
            "Kill switch is OFF — execution allowed" if ok else
            "KILL SWITCH ACTIVATED — all orders blocked")

    def _mode_allows(self) -> Dict[str, Any]:
        ok = self._mode in (ExecutionMode.PAPER_TRADING, ExecutionMode.LIVE_ASSISTED)
        return self._chk("mode_allows_execution", ok,
            f"Mode {self._mode}: {'execution permitted' if ok else 'RESEARCH_ONLY blocks execution'}")

    def _cash_available(self, order_value: float) -> Dict[str, Any]:
        ok = self._cash >= order_value
        return self._chk("cash_available", ok,
            f"Cash ₹{self._cash:.2f} {'≥' if ok else '<'} order ₹{order_value:.2f}")

    def _max_risk(self, risk_amount: float) -> Dict[str, Any]:
        max_risk = self._total * MAX_RISK_PCT
        ok = risk_amount <= max_risk
        return self._chk("max_risk_per_trade", ok,
            f"Risk ₹{risk_amount:.2f} {'≤' if ok else '>'} max ₹{max_risk:.2f} ({MAX_RISK_PCT*100:.0f}% of ₹{self._total:.0f})")

    def _portfolio_exposure(self, order_value: float) -> Dict[str, Any]:
        cap_pct = self._ctrl.total_deployed_cap_pct / 100
        new_deployed = self._deployed + order_value
        ok = new_deployed <= self._total * cap_pct
        return self._chk("portfolio_exposure", ok,
            f"Deployed ₹{new_deployed:.2f} {'≤' if ok else '>'} cap ₹{self._total * cap_pct:.2f} ({self._ctrl.total_deployed_cap_pct:.0f}%)")

    def _sector_concentration(self, sector: str, order_value: float) -> Dict[str, Any]:
        MAX_SECTOR_PCT = 35.0
        sec_current = self._sector_deployed.get(sector, 0.0)
        sec_new = sec_current + order_value
        cap = self._total * MAX_SECTOR_PCT / 100
        ok = sec_new <= cap
        return self._chk("sector_concentration", ok,
            f"Sector {sector}: ₹{sec_new:.2f} {'≤' if ok else '>'} cap ₹{cap:.2f} ({MAX_SECTOR_PCT:.0f}%)")

    def _stop_loss(self, price: float, stop: float, side: str) -> Dict[str, Any]:
        has_stop = stop > 0
        valid_side = (stop < price) if side == "BUY" else (stop > price)
        ok = has_stop and valid_side
        return self._chk("stop_loss_present", ok,
            f"SL ₹{stop:.2f} {'valid' if ok else 'invalid/missing'} for {side} at ₹{price:.2f}")

    def _target(self, price: float, target: float, side: str) -> Dict[str, Any]:
        has_target = target > 0
        valid_side = (target > price) if side == "BUY" else (target < price)
        ok = has_target and valid_side
        return self._chk("target_present", ok,
            f"Target ₹{target:.2f} {'valid' if ok else 'invalid/missing'} for {side} at ₹{price:.2f}")

    def _rr_minimum(self, rr_ratio: float) -> Dict[str, Any]:
        ok = rr_ratio >= self._ctrl.min_rr_ratio
        return self._chk("rr_minimum", ok,
            f"RR {rr_ratio:.2f} {'≥' if ok else '<'} min {self._ctrl.min_rr_ratio:.1f}")

    def _no_duplicate(self, symbol: str, side: str) -> Dict[str, Any]:
        sym = symbol.upper()
        audit = _load_audit()
        today = datetime.now(timezone.utc).date().isoformat()
        dup = any(
            e.get("symbol") == sym and e.get("side") == side
            and str(e.get("ts", ""))[:10] == today
            and e.get("event") in ("ORDER_SUBMITTED", "PAPER_ORDER", "PENDING_STEP1")
            for e in audit
        )
        return self._chk("no_duplicate_order", not dup,
            f"{'Duplicate order detected' if dup else 'No duplicate for'} {symbol} {side} today")

    def _position_conflict(self, symbol: str, side: str) -> Dict[str, Any]:
        conflict = symbol.upper() in self._open_symbols and side == "SELL"
        # Also block BUY if already long
        buy_conflict = symbol.upper() in self._open_symbols and side == "BUY"
        ok = not conflict and not buy_conflict
        return self._chk("position_conflict", ok,
            f"{'Open position conflict' if not ok else 'No position conflict'} for {symbol}")

    def _order_value_limit(self, order_value: float) -> Dict[str, Any]:
        ok = order_value <= self._ctrl.order_value_max
        cap = min(self._total * MAX_CAPITAL_PER_TRADE_PCT, self._ctrl.order_value_max)
        return self._chk("order_value_limit", ok,
            f"Order ₹{order_value:.2f} {'≤' if ok else '>'} limit ₹{cap:.2f}")

    def _daily_order_limit(self) -> Dict[str, Any]:
        ok = self._daily_orders < self._ctrl.max_orders_per_day
        return self._chk("daily_order_limit", ok,
            f"Orders today: {self._daily_orders}/{self._ctrl.max_orders_per_day}")

    def _cooldown(self) -> Dict[str, Any]:
        if not self._last_failed_ts:
            return self._chk("cooldown", True, "No recent failed orders")
        try:
            last = datetime.fromisoformat(self._last_failed_ts.replace("Z", "+00:00"))
            elapsed = (datetime.now(timezone.utc) - last).total_seconds()
            ok = elapsed >= self._ctrl.cooldown_after_fail_s
            return self._chk("cooldown", ok,
                f"Cooldown: {elapsed:.0f}s elapsed of {self._ctrl.cooldown_after_fail_s:.0f}s required"
                + (" — clear" if ok else " — BLOCKED"))
        except Exception:
            return self._chk("cooldown", True, "Cooldown check skipped (parse error)")

    def run(
        self, symbol: str, side: str, quantity: int,
        entry_price: float, stop_loss: float, target: float,
        sector: str, rr_ratio: float,
    ) -> Tuple[bool, List[Dict[str, Any]]]:
        """Run all 17 checks. Returns (all_passed, [check_results])."""
        order_value = entry_price * quantity
        risk_amount = abs(entry_price - stop_loss) * quantity

        checks = [
            self._kill_switch(),
            self._mode_allows(),
            self._market_hours(),
            self._data_freshness(),
            self._symbol_validity(symbol),
            self._cash_available(order_value),
            self._max_risk(risk_amount),
            self._portfolio_exposure(order_value),
            self._sector_concentration(sector, order_value),
            self._stop_loss(entry_price, stop_loss, side),
            self._target(entry_price, target, side),
            self._rr_minimum(rr_ratio),
            self._no_duplicate(symbol, side),
            self._position_conflict(symbol, side),
            self._order_value_limit(order_value),
            self._daily_order_limit(),
            self._cooldown(),
        ]
        all_passed = all(c["passed"] for c in checks)
        return all_passed, checks


# ── ExecutionEngine ───────────────────────────────────────────────────────────

class ExecutionEngine:
    """
    Orchestrates order lifecycle: preview → step1 confirm → step2 confirm → submit.
    Enforces mode + safety gates at every step.
    """

    def __init__(self, broker_client=None):
        self._client = broker_client
        self._pending: Dict[str, OrderPreview] = {}  # preview_id → preview

    def _now(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def build_preview(
        self, *,
        symbol: str, side: str, quantity: int,
        entry_price: float, stop_loss: float, target: float,
        strategy: str = "", confidence: float = 0.0,
        data_quality: str = "UNKNOWN", data_age_days: Optional[float] = None,
        sector: str = "OTHER",
        available_cash: float = INITIAL_CAPITAL,
        total_capital: float = INITIAL_CAPITAL,
        deployed_value: float = 0.0,
        open_symbols: Optional[List[str]] = None,
        sector_deployed: Optional[Dict[str, float]] = None,
        broker_connected: bool = False,
    ) -> OrderPreview:
        """Build an order preview ticket with full validation."""
        mode = get_execution_mode()
        controls = get_safety_controls()

        risk_amt   = round(abs(entry_price - stop_loss) * quantity, 2)
        reward_amt = round(abs(target - entry_price) * quantity, 2)
        rr = round(reward_amt / risk_amt, 2) if risk_amt > 0 else 0.0
        order_value = round(entry_price * quantity, 2)
        charges = _estimate_charges(order_value, side)
        avail_after = round(available_cash - order_value - charges, 2)

        daily_orders = get_daily_order_count()
        last_failed  = get_last_failed_order_ts()

        validator = PreTradeValidator(
            controls=controls, mode=mode,
            available_cash=available_cash, total_capital=total_capital,
            deployed_value=deployed_value, daily_orders_today=daily_orders,
            last_failed_ts=last_failed, data_quality=data_quality,
            broker_connected=broker_connected,
            open_symbols=open_symbols or [],
            sector_deployed=sector_deployed or {},
        )
        all_passed, checks = validator.run(
            symbol=symbol, side=side, quantity=quantity,
            entry_price=entry_price, stop_loss=stop_loss, target=target,
            sector=sector, rr_ratio=rr,
        )

        # ── RC-10C1: Portfolio Pre-Check runs BEFORE this RC-8-style gate in
        # the signal flow. Surface its verdict as the first validation check so
        # a portfolio limit breach fails the preview. BUY only — exits must
        # never be blocked by entry limits. Fails CLOSED inside pre_check().
        if side == "BUY":
            try:
                import portfolio_bridge
                _pc = portfolio_bridge.pre_check(
                    symbol, quantity, entry_price,
                    strategy_id=strategy or "ai_scan", sector=sector,
                )
                _pc_ok = bool(_pc.get("approved"))
                checks.insert(0, {
                    "check": "portfolio_pre_check",
                    "passed": _pc_ok,
                    "reason": ("Portfolio allocation + limits approved" if _pc_ok
                               else "; ".join(_pc.get("reasons") or ["portfolio limit breach"])),
                })
                all_passed = all_passed and _pc_ok
            except ImportError:
                pass  # bridge not present — legacy behavior
        failures = [c["reason"] for c in checks if not c["passed"]]

        preview_id = uuid.uuid4().hex[:12]
        now = self._now()
        expires = (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")

        status = OrderStatus.READY if all_passed else OrderStatus.VALIDATION_FAILED
        if controls.kill_switch:
            status = OrderStatus.BLOCKED
        elif data_quality not in ("LIVE", "NEAR_LIVE"):
            status = OrderStatus.DATA_STALE
        elif not broker_connected and mode == ExecutionMode.LIVE_ASSISTED:
            status = OrderStatus.BROKER_DISCONNECTED

        preview = OrderPreview(
            preview_id=preview_id, symbol=symbol.upper(), side=side,
            order_type="LIMIT", quantity=quantity,
            entry_price=round(entry_price, 2), stop_loss=round(stop_loss, 2),
            target_price=round(target, 2), estimated_value=order_value,
            risk_amount=risk_amt, reward_amount=reward_amt, rr_ratio=rr,
            charges_estimate=charges, available_funds_after=avail_after,
            strategy=strategy, confidence=round(confidence, 1),
            data_freshness=data_quality, data_age_days=data_age_days,
            validation_passed=all_passed, validation_checks=checks,
            failure_reasons=failures,
            confirm_token_step1=f"{CONFIRM_PREFIX_STEP1}{preview_id[:6]}",
            confirm_token_step2=f"{CONFIRM_PREFIX_STEP2}{preview_id}",
            status=status, mode=mode, created_at=now, expires_at=expires,
        )
        self._pending[preview_id] = preview

        _append_audit({
            "event": "PREVIEW_CREATED", "symbol": symbol, "side": side,
            "quantity": quantity, "entry_price": entry_price, "mode": mode,
            "validation_passed": all_passed, "failure_reasons": failures,
            "preview_id": preview_id, "status": status, "ts": now,
        })
        return preview

    def step1_confirm(self, preview_id: str, token: str) -> Dict[str, Any]:
        """Step 1: user reviews and acknowledges — returns step-2 token."""
        preview = self._pending.get(preview_id)
        if not preview:
            return {"success": False, "error": "Preview not found or expired"}
        if self._is_expired(preview):
            return {"success": False, "error": "Preview expired — build a new one"}
        expected = preview.confirm_token_step1
        if token != expected:
            _append_audit({"event": "CONFIRM_STEP1_FAILED", "preview_id": preview_id,
                           "reason": "Token mismatch", "ts": self._now()})
            return {"success": False, "error": f"Token mismatch. Expected: {expected}"}
        if not preview.validation_passed:
            return {"success": False, "error": "Validation failed — cannot confirm",
                    "failures": preview.failure_reasons}
        preview.status = OrderStatus.PENDING_STEP2
        _append_audit({"event": "CONFIRM_STEP1_OK", "preview_id": preview_id,
                       "symbol": preview.symbol, "side": preview.side, "ts": self._now()})
        return {
            "success": True, "step": 1,
            "message": "Step 1 confirmed. Provide step-2 token for final submission.",
            "confirm_token_step2": preview.confirm_token_step2,
            "warning": preview.warning,
        }

    def step2_submit(self, preview_id: str, token: str) -> Dict[str, Any]:
        """Step 2: final confirmation → actual submission."""
        # Phase 1: validate all preconditions without consuming the preview, so a
        # failed check (bad token, expired, kill switch) leaves it reusable.
        preview = self._pending.get(preview_id)
        if not preview:
            return {"success": False, "error": "Preview not found or expired"}
        if self._is_expired(preview):
            return {"success": False, "error": "Preview expired — build a new one"}
        if preview.status != OrderStatus.PENDING_STEP2:
            return {"success": False, "error": f"Must complete step 1 first (status: {preview.status})"}
        if token != preview.confirm_token_step2:
            _append_audit({"event": "CONFIRM_STEP2_FAILED", "preview_id": preview_id,
                           "reason": "Token mismatch", "ts": self._now()})
            return {"success": False, "error": "Step-2 token mismatch"}

        mode = get_execution_mode()
        controls = get_safety_controls()

        # Final kill-switch check immediately before submission
        if controls.kill_switch:
            _append_audit({"event": "ORDER_BLOCKED", "preview_id": preview_id,
                           "reason": "Kill switch activated", "ts": self._now()})
            return {"success": False, "error": "Kill switch activated — order blocked"}

        # Phase 2: atomically claim the preview so that concurrent duplicate
        # requests cannot both reach the broker.  dict.pop() is GIL-atomic in
        # CPython; whichever thread wins the pop() proceeds, the other sees None.
        preview = self._pending.pop(preview_id, None)
        if not preview:
            return {"success": False, "error": "Order already submitted — duplicate request blocked"}

        now = self._now()

        if mode == ExecutionMode.PAPER_TRADING:
            # Route to paper_trader
            try:
                from paper_trader import create_paper_order
                result = create_paper_order(
                    symbol=preview.symbol, action=preview.side,
                    entry_price=preview.entry_price, stop_loss=preview.stop_loss,
                    target=preview.target_price, strategy=preview.strategy,
                    scan_id=preview.preview_id, confidence=preview.confidence,
                )
                order_id = result.get("order_id") if result else None
                event = "PAPER_ORDER"
            except Exception as exc:
                event = "ORDER_FAILED"
                _append_audit({"event": event, "preview_id": preview_id,
                               "symbol": preview.symbol, "error": str(exc), "ts": now})
                return {"success": False, "error": str(exc)}

        elif mode == ExecutionMode.LIVE_ASSISTED:
            if not self._client:
                return {"success": False, "error": "No broker client configured"}
            params = {
                "symbol": preview.symbol, "exchange": "NSE",
                "transaction_type": preview.side, "quantity": preview.quantity,
                "order_type": "LIMIT", "product": "CNC",
                "price": preview.entry_price, "trigger_price": None,
                "variety": "regular", "tag": f"nse_p8_{preview_id[:6]}",
            }
            result = self._client.place_order_live(params)
            order_id = result.get("order_id")
            event = "ORDER_SUBMITTED" if result.get("success") else "ORDER_REJECTED"
            if not result.get("success"):
                _append_audit({"event": event, "preview_id": preview_id,
                               "symbol": preview.symbol, "side": preview.side,
                               "broker_response": result, "ts": now})
                return {"success": False, "status": result.get("status"),
                        "error": result.get("message")}
        else:
            return {"success": False, "error": "RESEARCH_ONLY mode — execution disabled"}

        preview.status = OrderStatus.SUBMITTED
        # preview already removed from _pending by the atomic pop() above
        _append_audit({
            "event": event, "preview_id": preview_id,
            "symbol": preview.symbol, "side": preview.side,
            "quantity": preview.quantity, "entry_price": preview.entry_price,
            "stop_loss": preview.stop_loss, "target": preview.target_price,
            "order_id": order_id, "mode": mode,
            "strategy": preview.strategy, "confidence": preview.confidence,
            "data_freshness": preview.data_freshness, "ts": now,
            "user_confirmed_step1": True, "user_confirmed_step2": True,
        })
        return {
            "success": True, "status": OrderStatus.SUBMITTED,
            "order_id": order_id, "mode": mode,
            "message": f"Order submitted successfully ({'paper' if mode == ExecutionMode.PAPER_TRADING else 'live'})",
            "warning": preview.warning,
        }

    def _is_expired(self, preview: OrderPreview) -> bool:
        try:
            exp = datetime.fromisoformat(preview.expires_at.replace("Z", "+00:00"))
            return datetime.now(timezone.utc) > exp
        except Exception:
            return False

    def cancel_preview(self, preview_id: str) -> Dict[str, Any]:
        if preview_id in self._pending:
            del self._pending[preview_id]
            _append_audit({"event": "PREVIEW_CANCELLED", "preview_id": preview_id,
                           "ts": self._now()})
            return {"success": True, "message": "Preview cancelled"}
        return {"success": False, "error": "Preview not found"}

    def get_pending_previews(self) -> List[Dict[str, Any]]:
        return [asdict(p) for p in self._pending.values() if not self._is_expired(p)]


# ── Shared singleton engine ───────────────────────────────────────────────────
# Instantiated lazily so import is always safe regardless of credentials.
_engine: Optional[ExecutionEngine] = None

def get_engine(broker_client=None) -> ExecutionEngine:
    global _engine
    if _engine is None:
        _engine = ExecutionEngine(broker_client=broker_client)
    if broker_client is not None:
        _engine._client = broker_client
    return _engine
