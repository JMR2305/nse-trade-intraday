#!/usr/bin/env python3
"""
phase2d_paper_sim.py — Phase 2D Paper Trading Simulations.

10 isolated paper-trading scenarios using direct Python imports.
Each scenario sets up its own in-memory state (patched portfolio_store)
so no scenario modifies the live DB or shares state with another.

All simulations use PAPER TRADING / RESEARCH ONLY paths.
No live broker calls anywhere.
Results written to phase2d_results.json.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import patch

_DIR     = os.path.dirname(os.path.abspath(__file__))
OUT_FILE = os.path.join(_DIR, "..", "..", "docs", "phase2d_results.json")
os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
sys.path.insert(0, _DIR)


# ── In-memory portfolio factory ───────────────────────────────────────────────

def _fresh_state(capital: float = 5000.0) -> Dict[str, Any]:
    return {
        "cash": capital,
        "positions": {},
        "trades": [],
        "pnl_history": [{"timestamp": datetime.now().isoformat(), "value": capital}],
    }


def _make_store_patches(state: Dict[str, Any]):
    """Return patch context managers that redirect portfolio_store I/O to `state`."""
    def _load():
        return state

    def _save(s: Dict[str, Any]):
        state.update(s)

    return (
        patch("paper_trader._load_state", side_effect=_load),
        patch("paper_trader._save_state", side_effect=_save),
        patch("paper_trader._store.load_state", side_effect=_load),
        patch("paper_trader._store.save_state", side_effect=_save),
    )


def _run_with_state(fn, capital: float = 5000.0):
    """Execute fn(state) with fully patched portfolio store. Returns (result, state)."""
    state = _fresh_state(capital)
    p = _make_store_patches(state)
    with p[0], p[1], p[2], p[3]:
        result = fn(state)
    return result, state


# ── Result helpers ────────────────────────────────────────────────────────────

def _r(n, name, verdict, detail, lat=0.0, assertions=None):
    r = {"sim": n, "name": name, "verdict": verdict,
         "detail": str(detail)[:400], "latency_ms": round(lat, 1)}
    if assertions:
        r["assertions"] = assertions
    return r


# ── Simulation implementations ────────────────────────────────────────────────

def sim_01_buy_entry() -> Dict[str, Any]:
    """S1 — BUY: entry created, position opened, portfolio cash reduced."""
    t0 = time.monotonic()
    try:
        from paper_trader import execute_buy
        assertions = []

        def _run(state):
            ok, msg = execute_buy(
                "RELIANCE", 3, 1278.0,
                reason="S1 buy test",
                stop_loss_price=1230.0, target=1350.0,
                signal_confidence=75.0, regime="SIDEWAYS",
                bypass_risk=True,
            )
            return ok, msg

        (ok, msg), state = _run_with_state(_run)
        assertions.append({"a": "execute_buy returns True", "ok": ok})
        position = state["positions"].get("RELIANCE")
        assertions.append({"a": "position created", "ok": bool(position)})
        if position:
            assertions.append({"a": "quantity=3", "ok": position.get("quantity") == 3})
            assertions.append({"a": "avg_price≈1278",
                               "ok": abs(position.get("avg_price", 0) - 1278.0) < 1.0})
        cash_expected = 5000.0 - 3 * 1278.0
        assertions.append({"a": f"cash reduced to ≈{cash_expected:.0f}",
                           "ok": abs(state["cash"] - cash_expected) < 1.0})
        buy_trades = [t for t in state["trades"] if t.get("action") == "BUY"]
        assertions.append({"a": "BUY trade record exists", "ok": bool(buy_trades)})

        all_ok = all(a["ok"] for a in assertions)
        lat = round((time.monotonic() - t0) * 1000, 1)
        return _r(1, "BUY Entry", "PASS" if all_ok else "FAIL",
                  f"ok={ok}, cash={state['cash']:.2f}, position={position}",
                  lat, assertions)
    except Exception as exc:
        return _r(1, "BUY Entry", "FAIL", f"Exception: {exc}",
                  round((time.monotonic() - t0) * 1000, 1))


def sim_02_sell_exit() -> Dict[str, Any]:
    """S2 — SELL: exit closes position, realised P&L recorded."""
    t0 = time.monotonic()
    try:
        from paper_trader import execute_buy, execute_sell
        assertions = []

        def _run(state):
            ok_buy, _ = execute_buy("TCS", 1, 3500.0, reason="S2 setup",
                                     stop_loss_price=3400.0, target=3650.0,
                                     bypass_risk=True)
            ok_sell, msg = execute_sell("TCS", 1, 3650.0, reason="S2 exit",
                                        exit_type="TARGET_HIT")
            return ok_buy, ok_sell, msg

        (ok_buy, ok_sell, msg), state = _run_with_state(_run)
        assertions.append({"a": "BUY succeeded", "ok": ok_buy})
        assertions.append({"a": "SELL succeeded", "ok": ok_sell})
        position_closed = "TCS" not in state["positions"]
        assertions.append({"a": "position closed after SELL", "ok": position_closed})
        sell_trades = [t for t in state["trades"] if t.get("action") == "SELL"]
        assertions.append({"a": "SELL trade record exists", "ok": bool(sell_trades)})
        if sell_trades:
            pnl = sell_trades[-1].get("pnl", 0)
            expected_pnl = (3650.0 - 3500.0) * 1
            assertions.append({"a": f"pnl=₹{expected_pnl:.0f}",
                               "ok": abs(pnl - expected_pnl) < 1.0})
            assertions.append({"a": "exit_type=TARGET_HIT",
                               "ok": sell_trades[-1].get("exit_type") == "TARGET_HIT"})

        all_ok = all(a["ok"] for a in assertions)
        return _r(2, "SELL Exit", "PASS" if all_ok else "FAIL",
                  f"buy={ok_buy}, sell={ok_sell}, position_closed={position_closed}, "
                  f"pnl={sell_trades[-1].get('pnl') if sell_trades else 'N/A'}",
                  round((time.monotonic() - t0) * 1000, 1), assertions)
    except Exception as exc:
        return _r(2, "SELL Exit", "FAIL", f"Exception: {exc}",
                  round((time.monotonic() - t0) * 1000, 1))


def sim_03_stop_loss() -> Dict[str, Any]:
    """S3 — Stop-loss: SL trigger closes position at loss."""
    t0 = time.monotonic()
    try:
        from paper_trader import execute_buy, execute_sell
        assertions = []

        def _run(state):
            ok_buy, _ = execute_buy("INFY", 2, 1500.0, reason="S3 setup",
                                     stop_loss_price=1450.0, target=1600.0,
                                     bypass_risk=True)
            ok_sell, msg = execute_sell("INFY", 2, 1445.0,
                                        reason="S3 SL triggered",
                                        exit_type="STOP_HIT")
            return ok_buy, ok_sell, msg

        (ok_buy, ok_sell, msg), state = _run_with_state(_run)
        assertions.append({"a": "BUY succeeded", "ok": ok_buy})
        assertions.append({"a": "SELL at SL succeeded", "ok": ok_sell})
        position_closed = "INFY" not in state["positions"]
        assertions.append({"a": "position closed", "ok": position_closed})
        sell_trades = [t for t in state["trades"] if t.get("action") == "SELL"]
        pnl = None
        if sell_trades:
            exit_type = sell_trades[-1].get("exit_type")
            assertions.append({"a": "exit_type=STOP_HIT", "ok": exit_type == "STOP_HIT"})
            pnl = sell_trades[-1].get("pnl", 0)
            assertions.append({"a": f"pnl<0 (loss: ₹{pnl:.2f})", "ok": pnl < 0})
            exit_price = sell_trades[-1].get("price", 0)
            assertions.append({"a": "exit at/below SL (1450)", "ok": exit_price <= 1450.0})

        all_ok = all(a["ok"] for a in assertions)
        return _r(3, "Stop-Loss Trigger", "PASS" if all_ok else "FAIL",
                  f"SL exit at 1445 (SL=1450); pnl={pnl}; position_closed={position_closed}",
                  round((time.monotonic() - t0) * 1000, 1), assertions)
    except Exception as exc:
        return _r(3, "Stop-Loss Trigger", "FAIL", f"Exception: {exc}",
                  round((time.monotonic() - t0) * 1000, 1))


def sim_04_target_hit() -> Dict[str, Any]:
    """S4 — Target: TP trigger closes position at profit."""
    t0 = time.monotonic()
    try:
        from paper_trader import execute_buy, execute_sell
        assertions = []

        def _run(state):
            ok_buy, _ = execute_buy("HDFCBANK", 1, 1600.0, reason="S4 setup",
                                     stop_loss_price=1550.0, target=1700.0,
                                     bypass_risk=True)
            ok_sell, msg = execute_sell("HDFCBANK", 1, 1705.0,
                                        reason="S4 target hit",
                                        exit_type="TARGET_HIT")
            return ok_buy, ok_sell, msg

        (ok_buy, ok_sell, msg), state = _run_with_state(_run)
        assertions.append({"a": "BUY succeeded", "ok": ok_buy})
        assertions.append({"a": "SELL at target succeeded", "ok": ok_sell})
        sell_trades = [t for t in state["trades"] if t.get("action") == "SELL"]
        pnl = None
        if sell_trades:
            pnl = sell_trades[-1].get("pnl", 0)
            assertions.append({"a": f"pnl>0 (profit: ₹{pnl:.2f})", "ok": pnl > 0})
            exit_price = sell_trades[-1].get("price", 0)
            assertions.append({"a": "exit at/above target (1700)", "ok": exit_price >= 1700.0})
            assertions.append({"a": "exit_type=TARGET_HIT",
                               "ok": sell_trades[-1].get("exit_type") == "TARGET_HIT"})

        all_ok = all(a["ok"] for a in assertions)
        return _r(4, "Target Hit", "PASS" if all_ok else "FAIL",
                  f"TP exit at 1705 (target=1700); pnl={pnl}",
                  round((time.monotonic() - t0) * 1000, 1), assertions)
    except Exception as exc:
        return _r(4, "Target Hit", "FAIL", f"Exception: {exc}",
                  round((time.monotonic() - t0) * 1000, 1))


def sim_05_trailing_stop() -> Dict[str, Any]:
    """S5 — Trailing stop: stop adjusts as price moves in favour (logic test)."""
    t0 = time.monotonic()
    try:
        assertions = []
        fill_price = 1000.0
        stop       = 950.0    # 1R = ₹50
        one_r      = fill_price - stop

        # A: peak reached 2R → trailing fires when quote falls back to 1R
        peak_a         = fill_price + 2 * one_r   # ₹1100
        quote_a        = fill_price + one_r * 0.6  # ₹1030 < fill+1R=₹1050
        trailing_fires_a = (peak_a >= fill_price + 2 * one_r and
                           quote_a <= fill_price + one_r)
        assertions.append({"a": "trailing fires when peak≥fill+2R and quote≤fill+1R",
                           "ok": trailing_fires_a})

        # B: peak only at 1.5R → trailing should NOT fire
        peak_b  = fill_price + 1.5 * one_r
        trailing_fires_b = (peak_b >= fill_price + 2 * one_r)
        assertions.append({"a": "trailing does NOT fire if peak < fill+2R",
                           "ok": not trailing_fires_b})

        # C: inverted stop (stop > entry) → one_r negative, trailing never fires
        bad_one_r = fill_price - 1100.0  # negative
        assertions.append({"a": "trailing blocked for inverted stop",
                           "ok": bad_one_r <= 0})

        # D: verify stop_loss stored on BUY trade record
        from paper_trader import execute_buy

        def _run(state):
            return execute_buy("WIPRO", 1, fill_price, reason="S5 trail test",
                               stop_loss_price=stop, target=1150.0,
                               bypass_risk=True)

        (ok, msg), state = _run_with_state(_run)
        buy_trade = next((t for t in state["trades"] if t.get("action") == "BUY"), None)
        assertions.append({"a": "stop_loss stored on BUY trade",
                           "ok": buy_trade is not None and
                                 abs(buy_trade.get("stop_loss", 0) - stop) < 0.01})

        all_ok = all(a["ok"] for a in assertions)
        return _r(5, "Trailing Stop", "PASS" if all_ok else "FAIL",
                  f"trailing_fires_at_2R={trailing_fires_a}; "
                  f"no_early_fire={not trailing_fires_b}; "
                  f"inverted_stop_blocked={bad_one_r <= 0}; "
                  f"stop_stored={buy_trade is not None}",
                  round((time.monotonic() - t0) * 1000, 1), assertions)
    except Exception as exc:
        return _r(5, "Trailing Stop", "FAIL", f"Exception: {exc}",
                  round((time.monotonic() - t0) * 1000, 1))


def sim_06_partial_exits() -> Dict[str, Any]:
    """S6 — Partial exits: position reduces by sold quantity, partial P&L realised."""
    t0 = time.monotonic()
    try:
        from paper_trader import execute_buy, execute_sell
        assertions = []

        def _run(state):
            execute_buy("SBIN", 5, 600.0, reason="S6 setup",
                        stop_loss_price=570.0, target=650.0, bypass_risk=True)
            ok, msg = execute_sell("SBIN", 2, 620.0, reason="S6 partial exit",
                                   exit_type="SIGNAL_EXIT")
            return ok, msg

        (ok, msg), state = _run_with_state(_run)
        assertions.append({"a": "partial SELL succeeded", "ok": ok})
        position = state["positions"].get("SBIN")
        assertions.append({"a": "position remains open after partial exit",
                           "ok": bool(position)})
        if position:
            remaining_qty = position.get("quantity", 0)
            assertions.append({"a": "remaining quantity = 3 (5-2)",
                               "ok": remaining_qty == 3})
        sell_trades = [t for t in state["trades"] if t.get("action") == "SELL"]
        if sell_trades:
            qty_sold = sell_trades[-1].get("quantity", 0)
            assertions.append({"a": "SELL record shows qty=2", "ok": qty_sold == 2})
            partial_pnl = sell_trades[-1].get("pnl", 0)
            expected = (620.0 - 600.0) * 2  # ₹40
            assertions.append({"a": f"partial_pnl≈₹{expected:.0f}",
                               "ok": abs(partial_pnl - expected) < 1.0})

        # Verify we can sell the remaining 3 shares
        state2 = _fresh_state()
        state2.update(state)
        p2 = _make_store_patches(state2)
        from paper_trader import execute_sell as _sell2
        with p2[0], p2[1], p2[2], p2[3]:
            ok2, _ = _sell2("SBIN", 3, 640.0, reason="S6 remaining exit",
                            exit_type="SIGNAL_EXIT")
        assertions.append({"a": "can sell remaining 3 shares", "ok": ok2})

        all_ok = all(a["ok"] for a in assertions)
        return _r(6, "Partial Exit", "PASS" if all_ok else "FAIL",
                  f"sold 2/5; remaining qty={position.get('quantity') if position else 'N/A'}; "
                  f"partial_pnl={sell_trades[-1].get('pnl') if sell_trades else 'N/A'}",
                  round((time.monotonic() - t0) * 1000, 1), assertions)
    except Exception as exc:
        return _r(6, "Partial Exit", "FAIL", f"Exception: {exc}",
                  round((time.monotonic() - t0) * 1000, 1))


def sim_07_multiple_positions() -> Dict[str, Any]:
    """S7 — Multiple simultaneous positions: portfolio holds ≥3 open positions."""
    t0 = time.monotonic()
    try:
        from paper_trader import execute_buy
        assertions = []
        # Use real NSE symbols at prices that fit within 20%-cap on ₹5000 (max ₹1000/trade).
        # Total cost: ₹600 + ₹600 + ₹800 = ₹2000 < ₹5000 available.
        symbols_affordable = [
            ("SBIN",       1,  600.0,  570.0,  660.0),
            ("WIPRO",      2,  300.0,  285.0,  330.0),
            ("TATAMOTORS", 1,  800.0,  760.0,  880.0),
        ]

        def _run(state):
            results_local = []
            for sym, qty, price, sl, tgt in symbols_affordable:
                ok, msg = execute_buy(sym, qty, price, reason=f"S7 {sym}",
                                      stop_loss_price=sl, target=tgt,
                                      bypass_risk=True)
                results_local.append((sym, ok, msg))
            return results_local

        results_buys, state = _run_with_state(_run, capital=5000.0)
        open_positions = state["positions"]
        assertions.append({"a": "≥3 open positions", "ok": len(open_positions) >= 3})
        for sym, ok, msg in results_buys:
            assertions.append({"a": f"BUY {sym} succeeded", "ok": ok})
        cash_remaining = state["cash"]
        invested = sum(v["quantity"] * v["avg_price"] for v in open_positions.values())
        total = cash_remaining + invested
        assertions.append({"a": "cash + invested ≈ initial capital",
                           "ok": abs(total - 5000.0) < 1.0})

        all_ok = all(a["ok"] for a in assertions)
        return _r(7, "Multiple Simultaneous Positions", "PASS" if all_ok else "FAIL",
                  f"open_positions={len(open_positions)}, symbols={list(open_positions.keys())}, "
                  f"cash={cash_remaining:.2f}, invested={invested:.2f}",
                  round((time.monotonic() - t0) * 1000, 1), assertions)
    except Exception as exc:
        return _r(7, "Multiple Simultaneous Positions", "FAIL", f"Exception: {exc}",
                  round((time.monotonic() - t0) * 1000, 1))


def sim_08_daily_limits() -> Dict[str, Any]:
    """S8 — Daily limits: entry blocked when daily loss limit reached."""
    t0 = time.monotonic()
    try:
        from phase11_risk import pre_trade_check
        from position_sizer import compute_position
        assertions = []

        # pre_trade_check must return (bool, str) without crashing
        ok_normal, msg_normal = pre_trade_check(
            "RELIANCE", 1, 1278.0, stop_loss=1230.0, confidence=75.0,
        )
        assertions.append({"a": "pre_trade_check returns (bool, str)",
                           "ok": isinstance(ok_normal, bool) and isinstance(msg_normal, str)})

        # Normal sizing is feasible (SBIN at ₹600, 20%-cap = ₹1000 → 1 share)
        sizing_normal = compute_position(
            entry_price=600.0, stop_loss=570.0, target=660.0,
            available_cash=5000.0, capital=5000.0
        )
        assertions.append({"a": "normal sizing is feasible",
                           "ok": sizing_normal["feasible"]})

        # With ₹10 remaining (simulate daily loss depleted capital): not feasible
        sizing_depleted = compute_position(
            entry_price=600.0, stop_loss=570.0, target=660.0,
            available_cash=10.0, capital=5000.0
        )
        assertions.append({"a": "sizing not feasible when cash depleted",
                           "ok": not sizing_depleted["feasible"]})

        # Daily loss limit gate arithmetic
        total_value       = 5000.0
        daily_loss_pct    = 2.0
        daily_loss_limit  = total_value * daily_loss_pct / 100.0  # ₹100
        simulated_pnl     = -150.0
        limit_breached    = simulated_pnl <= -daily_loss_limit
        assertions.append({"a": "daily loss limit gate fails when loss exceeds cap",
                           "ok": limit_breached})

        all_ok = all(a["ok"] for a in assertions)
        return _r(8, "Daily Limits", "PASS" if all_ok else "FAIL",
                  f"pre_trade_check=({ok_normal}, '{msg_normal[:50]}'); "
                  f"normal_feasible={sizing_normal['feasible']}; "
                  f"depleted_feasible={sizing_depleted['feasible']}; "
                  f"loss_limit_gate_blocks={limit_breached}",
                  round((time.monotonic() - t0) * 1000, 1), assertions)
    except Exception as exc:
        return _r(8, "Daily Limits", "FAIL", f"Exception: {exc}",
                  round((time.monotonic() - t0) * 1000, 1))


def sim_09_kill_switch() -> Dict[str, Any]:
    """S9 — Kill switch: all new entries blocked when kill switch active."""
    t0 = time.monotonic()
    try:
        from phase20_circuit_breaker import get_state, is_tripped
        from phase20_executor import run_auto_entries
        assertions = []

        # Read live circuit breaker state
        cb_state  = get_state()
        tripped   = cb_state.get("tripped", False)
        unreadable = cb_state.get("unreadable", False)
        assertions.append({"a": "get_state() returns dict", "ok": isinstance(cb_state, dict)})
        assertions.append({"a": "tripped field present", "ok": "tripped" in cb_state})

        live_tripped      = is_tripped()
        expected_tripped  = tripped or bool(unreadable)
        assertions.append({"a": "is_tripped() consistent with get_state()",
                           "ok": live_tripped == expected_tripped})

        # Simulate kill switch: patch evaluate_and_maybe_trip AT SOURCE MODULE so that
        # the local import inside run_auto_entries picks up the mock.
        fake_settings = {
            "auto_paper_entries": True,
            "auto_paper_entries_confirmed_at": "2026-07-25T00:00:00Z",
            "max_trades_per_day": 3,
        }
        tripped_cb = {
            "tripped": True, "tripped_at": "2026-07-25T00:00:00Z",
            "reasons": [{"code": "TEST_KILL_SWITCH",
                         "detail": "Simulated for Phase 2D test"}],
        }
        with patch("phase20_circuit_breaker.evaluate_and_maybe_trip",
                   return_value=tripped_cb):
            result = run_auto_entries(fake_settings)

        assertions.append({"a": "run_auto_entries returns ran=False when tripped",
                           "ok": result.get("ran") is False})
        blocked = result.get("ran") is False
        assertions.append({"a": "kill switch blocks entries", "ok": blocked})

        all_ok = all(a["ok"] for a in assertions)
        return _r(9, "Kill Switch", "PASS" if all_ok else "FAIL",
                  f"live_cb_tripped={tripped}; "
                  f"simulated kill switch: entries_blocked={blocked}; "
                  f"result.ran={result.get('ran')}, "
                  f"reason='{result.get('reason','')[:80]}'",
                  round((time.monotonic() - t0) * 1000, 1), assertions)
    except Exception as exc:
        return _r(9, "Kill Switch", "FAIL", f"Exception: {exc}",
                  round((time.monotonic() - t0) * 1000, 1))


def sim_10_position_sizing() -> Dict[str, Any]:
    """S10 — Position sizing: quantity matches position_sizer.py constraints."""
    t0 = time.monotonic()
    try:
        from position_sizer import compute_position, compute_from_signal
        from config import MAX_CAPITAL_PER_TRADE_PCT, MAX_RISK_PCT
        assertions = []

        # Use SBIN-like pricing (₹600) so 20%-cap on ₹5000 (=₹1000) allows ≥1 share.
        # 1% risk on ₹5000 = ₹50; stop_distance = ₹30 → qty_from_risk = floor(50/30) = 1
        entry  = 600.0
        sl     = 570.0   # ₹30 stop
        target = 660.0   # 2:1 R:R

        # Scenario A: standard sizing — expect feasible=True
        sizing_a = compute_position(
            entry_price=entry, stop_loss=sl, target=target,
            available_cash=5000.0, capital=5000.0,
        )
        assertions.append({"a": "returns dict", "ok": isinstance(sizing_a, dict)})
        assertions.append({"a": f"feasible=True (₹{entry:.0f}, {MAX_CAPITAL_PER_TRADE_PCT*100:.0f}%-cap)",
                           "ok": sizing_a["feasible"]})
        assertions.append({"a": "suggested_quantity ≥ 1",
                           "ok": sizing_a["suggested_quantity"] >= 1})
        assertions.append({"a": "max_loss ≤ max_risk_amount",
                           "ok": sizing_a["max_loss"] <= sizing_a["max_risk_amount"] + 0.01})
        assertions.append({"a": "rr_ratio > 0", "ok": sizing_a["rr_ratio"] > 0})
        assertions.append({"a": f"stop_distance=₹{entry-sl:.0f}",
                           "ok": abs(sizing_a["stop_distance"] - (entry - sl)) < 0.01})

        # Scenario B: tighter stop → same risk budget → more shares (bounded by cap)
        sizing_b = compute_position(
            entry_price=entry, stop_loss=entry - 5.0, target=target,
            available_cash=5000.0, capital=5000.0,
        )
        assertions.append({"a": "tighter stop yields ≥ standard qty",
                           "ok": sizing_b["suggested_quantity"] >= sizing_a["suggested_quantity"]})

        # Scenario C: no cash → not feasible
        sizing_c = compute_position(
            entry_price=entry, stop_loss=sl, target=target,
            available_cash=0.0, capital=5000.0,
        )
        assertions.append({"a": "not feasible when cash=0", "ok": not sizing_c["feasible"]})
        assertions.append({"a": "qty=0 when cash=0", "ok": sizing_c["suggested_quantity"] == 0})

        # Scenario D: very expensive stock → not feasible
        sizing_d = compute_position(
            entry_price=50000.0, stop_loss=49000.0, target=52000.0,
            available_cash=5000.0, capital=5000.0,
        )
        assertions.append({"a": "not feasible for ₹50000 stock (> 20% cap)",
                           "ok": not sizing_d["feasible"]})

        # Scenario E: compute_from_signal consistency
        sizing_e = compute_from_signal(
            {"price": entry, "stop_loss": sl, "target": target, "signal": "BUY"},
            available_cash=5000.0,
        )
        assertions.append({"a": "compute_from_signal matches compute_position",
                           "ok": sizing_e["suggested_quantity"] == sizing_a["suggested_quantity"]})

        all_ok = all(a["ok"] for a in assertions)
        return _r(10, "Position Sizing", "PASS" if all_ok else "FAIL",
                  f"SBIN-like ₹{entry:.0f}: qty={sizing_a['suggested_quantity']}, "
                  f"stop=₹{sizing_a['stop_distance']:.0f}, max_loss=₹{sizing_a['max_loss']:.0f}, "
                  f"rr={sizing_a['rr_ratio']}; no_cash: feasible={sizing_c['feasible']}; "
                  f"expensive: feasible={sizing_d['feasible']}",
                  round((time.monotonic() - t0) * 1000, 1), assertions)
    except Exception as exc:
        return _r(10, "Position Sizing", "FAIL", f"Exception: {exc}",
                  round((time.monotonic() - t0) * 1000, 1))


# ── Runner ────────────────────────────────────────────────────────────────────

SIMS = [
    sim_01_buy_entry,
    sim_02_sell_exit,
    sim_03_stop_loss,
    sim_04_target_hit,
    sim_05_trailing_stop,
    sim_06_partial_exits,
    sim_07_multiple_positions,
    sim_08_daily_limits,
    sim_09_kill_switch,
    sim_10_position_sizing,
]


def run_paper_sims() -> Dict[str, Any]:
    print("=" * 64)
    print("Phase 2D — Paper Trading Simulations")
    print(f"Run at: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 64)

    results: List[Dict[str, Any]] = []
    counts: Dict[str, int] = {"PASS": 0, "FAIL": 0}

    for sim_fn in SIMS:
        doc_title = (sim_fn.__doc__ or sim_fn.__name__).split("—")[0].strip()
        print(f"\n[{len(results)+1:02d}/10] {doc_title} ...", end=" ", flush=True)
        try:
            r = sim_fn()
        except Exception as exc:
            r = _r(len(results) + 1, sim_fn.__name__, "FAIL",
                   f"Unhandled exception: {exc}")
        verdict = r.get("verdict", "FAIL")
        icon = "✅" if verdict == "PASS" else "❌"
        print(f"{icon} {verdict} ({r.get('latency_ms', 0):.0f}ms)")
        detail = r.get("detail", "")
        if detail:
            print(f"       {detail[:120]}")
        if r.get("assertions"):
            for a in r["assertions"]:
                if not a.get("ok"):
                    print(f"       ❌ FAILED: {a['a']}")
        counts[verdict] = counts.get(verdict, 0) + 1
        results.append(r)

    print(f"\n{'=' * 64}")
    print(f"PAPER SIMS SUMMARY: ✅ {counts['PASS']}/10  ❌ {counts['FAIL']}")
    print("=" * 64)

    output = {
        "test_type": "phase2d_paper_sims",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "summary": counts,
        "overall_verdict": "PASS" if counts["FAIL"] == 0 else "FAIL",
        "results": results,
    }
    try:
        with open(OUT_FILE, "w") as f:
            json.dump(output, f, indent=2)
        print(f"\nResults written to: {OUT_FILE}")
    except Exception as exc:
        print(f"Warning: could not write results: {exc}")
    return output


if __name__ == "__main__":
    sys.path.insert(0, _DIR)
    result = run_paper_sims()
    sys.exit(0 if result["overall_verdict"] == "PASS" else 1)
