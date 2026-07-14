"""
readiness_checker.py  —  Phase 8: Live Readiness Checklist & Score

Computes a scored checklist of N conditions that must ALL be met before
live-assisted execution is considered READY. The score is 0–100 but the
status stays NOT_READY until every required check passes.

Checklist items
---------------
  1.  broker_connected       — Broker API responds and token is VALID          [required]
  2.  token_valid            — Access token not expired or missing              [required]
  3.  mode_live_assisted     — Execution mode is LIVE_ASSISTED                  [required]
  4.  kill_switch_off        — Global kill switch is OFF                        [required]
  5.  market_hours           — NSE market is currently open                     [required]
  6.  data_freshness         — Phase 7 data quality LIVE or NEAR_LIVE           [required]
  7.  credentials_present    — API_KEY + ACCESS_TOKEN env vars set              [required]
  8.  cash_sufficient        — Available cash > ₹0 and margin available         [required]
  9.  daily_orders_under_cap — Orders today < max_orders_per_day               [required]
  10. cooldown_clear         — No active cooldown from recent failure           [advisory]
  11. last_scan_recent       — Last full Phase 7 scan < 60 min old             [advisory]
  12. paper_mode_experience  — At least 1 paper trade recorded (experience)    [advisory]

Required checks (1–9): ALL must pass for READY status.
Advisory checks (10–12): Shown as warnings but do not block READY.

Scoring:
  required_score = (required_passed / required_total) * 70
  advisory_score = (advisory_passed / advisory_total) * 30
  total_score    = required_score + advisory_score

Status:
  READY         → all required checks pass (score = required 100%, advisory varies)
  NOT_READY     → any required check fails
  LOCKED        → kill switch ON (immediate, regardless of other checks)
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from execution_engine import (
    ExecutionMode, SafetyControls,
    get_execution_mode, get_safety_controls, get_daily_order_count,
    get_last_failed_order_ts, _load_config,
)

REQUIRED_CHECKS = {
    "broker_connected", "token_valid", "mode_live_assisted",
    "kill_switch_off", "market_hours", "data_freshness",
    "credentials_present", "cash_sufficient", "daily_orders_under_cap",
}
ADVISORY_CHECKS = {"cooldown_clear", "last_scan_recent", "paper_mode_experience"}

NSE_OPEN_H, NSE_OPEN_M   = 9, 15
NSE_CLOSE_H, NSE_CLOSE_M = 15, 30
NSE_WEEKDAYS = {0, 1, 2, 3, 4}


@dataclass
class CheckItem:
    name: str
    label: str
    passed: bool
    required: bool
    detail: str
    severity: str   # PASS | WARN | FAIL


@dataclass
class ReadinessResult:
    status: str                     # READY | NOT_READY | LOCKED
    score: float                    # 0–100
    required_score: float
    advisory_score: float
    required_passed: int
    required_total: int
    advisory_passed: int
    advisory_total: int
    checks: List[CheckItem]
    blocking_reasons: List[str]     # human-readable reasons for NOT_READY
    warnings: List[str]             # advisory failures
    computed_at: str
    label: str = "PAPER / LIVE DATA VALIDATION"
    note: str = ("This is a research and assisted-execution tool. "
                 "Live Assisted mode requires ALL required checks to pass. "
                 "The user is responsible for every live order.")


class LiveReadinessChecker:
    """Compute full readiness checklist from live system state."""

    def __init__(
        self, *,
        broker_connection_status: Optional[Dict[str, Any]] = None,
        available_cash: float = 0.0,
        data_quality: str = "UNKNOWN",
        last_scan_ts: Optional[str] = None,
        paper_trade_count: int = 0,
    ):
        self._broker = broker_connection_status or {}
        self._cash   = available_cash
        self._data_q = data_quality
        self._scan_ts = last_scan_ts
        self._paper_count = paper_trade_count

    def _market_open(self) -> Tuple[bool, str]:
        now_ist = datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)
        wd = now_ist.weekday()
        h, m = now_ist.hour, now_ist.minute
        cur = h * 60 + m
        ok  = wd in NSE_WEEKDAYS and (NSE_OPEN_H * 60 + NSE_OPEN_M) <= cur <= (NSE_CLOSE_H * 60 + NSE_CLOSE_M)
        return ok, f"NSE {'OPEN' if ok else 'CLOSED'} — {now_ist.strftime('%H:%M IST %a')}"

    def check(self) -> ReadinessResult:
        mode     = get_execution_mode()
        controls = get_safety_controls()
        now      = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        items: List[CheckItem] = []

        def req(name: str, label: str, passed: bool, detail: str):
            items.append(CheckItem(name=name, label=label, passed=passed, required=True,
                                   detail=detail, severity="PASS" if passed else "FAIL"))

        def adv(name: str, label: str, passed: bool, detail: str):
            items.append(CheckItem(name=name, label=label, passed=passed, required=False,
                                   detail=detail, severity="PASS" if passed else "WARN"))

        # 1. kill_switch_off — checked first so LOCKED state is immediate
        ks_ok = not controls.kill_switch
        req("kill_switch_off", "Kill Switch OFF",
            ks_ok, "Kill switch is OFF" if ks_ok else "KILL SWITCH ACTIVATED — all orders blocked")

        # 2. credentials_present
        from broker_client import creds_present
        creds_ok = creds_present()
        req("credentials_present", "Broker Credentials Set",
            creds_ok, "API_KEY and ACCESS_TOKEN env vars are set" if creds_ok
            else "ZERODHA_API_KEY and ZERODHA_ACCESS_TOKEN env vars not set")

        # 3. broker_connected
        conn_ok = self._broker.get("connected", False)
        req("broker_connected", "Broker Connected",
            conn_ok, f"Status: {self._broker.get('connection_status', 'UNKNOWN')}" if not conn_ok
            else f"Connected to {self._broker.get('broker', 'broker')}")

        # 4. token_valid
        tok_ok = self._broker.get("token_status") == "VALID"
        req("token_valid", "Access Token Valid",
            tok_ok, f"Token status: {self._broker.get('token_status', 'UNKNOWN')}")

        # 5. mode_live_assisted
        mode_ok = mode == ExecutionMode.LIVE_ASSISTED
        req("mode_live_assisted", "Mode: Live Assisted",
            mode_ok, f"Current mode: {mode}. Must be LIVE_ASSISTED for real execution.")

        # 6. market_hours
        mkt_ok, mkt_detail = self._market_open()
        req("market_hours", "NSE Market Hours", mkt_ok, mkt_detail)

        # 7. data_freshness
        dq_ok = self._data_q in ("LIVE", "NEAR_LIVE")
        req("data_freshness", "Live Data Fresh",
            dq_ok, f"Data quality: {self._data_q}. Must be LIVE or NEAR_LIVE.")

        # 8. cash_sufficient
        cash_ok = self._cash > 0
        req("cash_sufficient", "Cash Available",
            cash_ok, f"Available cash: ₹{self._cash:.2f}")

        # 9. daily_orders_under_cap
        daily = get_daily_order_count()
        ord_ok = daily < controls.max_orders_per_day
        req("daily_orders_under_cap", "Daily Order Cap",
            ord_ok, f"Orders today: {daily}/{controls.max_orders_per_day}")

        # 10. cooldown_clear (advisory)
        last_fail = get_last_failed_order_ts()
        if last_fail:
            try:
                lf = datetime.fromisoformat(last_fail.replace("Z", "+00:00"))
                elapsed = (datetime.now(timezone.utc) - lf).total_seconds()
                cool_ok = elapsed >= controls.cooldown_after_fail_s
            except Exception:
                cool_ok = True
        else:
            cool_ok = True
        adv("cooldown_clear", "Cooldown Clear",
            cool_ok, "No cooldown active" if cool_ok else
            f"Cooldown: {controls.cooldown_after_fail_s:.0f}s required after last failure")

        # 11. last_scan_recent (advisory)
        scan_ok = False
        if self._scan_ts:
            try:
                scan_dt = datetime.fromisoformat(self._scan_ts.replace("Z", "+00:00"))
                age_min = (datetime.now(timezone.utc) - scan_dt).total_seconds() / 60
                scan_ok = age_min < 60
                scan_detail = f"Last scan: {age_min:.0f} min ago {'(fresh)' if scan_ok else '(stale)'}"
            except Exception:
                scan_detail = "Could not parse scan timestamp"
        else:
            scan_detail = "No Phase 7 scan has been run yet"
        adv("last_scan_recent", "Phase 7 Scan Recent", scan_ok, scan_detail)

        # 12. paper_mode_experience (advisory)
        exp_ok = self._paper_count >= 1
        adv("paper_mode_experience", "Paper Trading Experience",
            exp_ok, f"{self._paper_count} paper trade(s) recorded" if exp_ok
            else "No paper trades recorded — recommend paper trading first")

        # ── Compute scores ────────────────────────────────────────────────────
        req_items = [i for i in items if i.required]
        adv_items = [i for i in items if not i.required]
        req_pass  = sum(1 for i in req_items if i.passed)
        adv_pass  = sum(1 for i in adv_items if i.passed)

        req_score = (req_pass / len(req_items)) * 70 if req_items else 0.0
        adv_score = (adv_pass / len(adv_items)) * 30 if adv_items else 0.0
        total_score = round(req_score + adv_score, 1)

        # ── Status ────────────────────────────────────────────────────────────
        if controls.kill_switch:
            status = "LOCKED"
        elif req_pass == len(req_items):
            status = "READY"
        else:
            status = "NOT_READY"

        blocking = [i.detail for i in req_items if not i.passed]
        warnings = [i.detail for i in adv_items if not i.passed]

        return ReadinessResult(
            status=status, score=total_score,
            required_score=round(req_score, 1), advisory_score=round(adv_score, 1),
            required_passed=req_pass, required_total=len(req_items),
            advisory_passed=adv_pass, advisory_total=len(adv_items),
            checks=items, blocking_reasons=blocking, warnings=warnings,
            computed_at=now,
        )
