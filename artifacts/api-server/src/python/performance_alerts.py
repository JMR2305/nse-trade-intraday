"""
performance_alerts.py — Phase 20 strategy-performance degradation alerts.

Advisory-only alert rules evaluated after each scheduler tick's paper
management step. When a rule triggers, a notification is added to the
existing notification system (phase20_store.add_notification) so the user
can intervene early. Unlike the circuit breaker, this module NEVER blocks
entries or changes any behaviour — it only notifies.

Rules (configurable via Phase 20 settings):
  1. LOSING_STREAK — consecutive losing closed paper trades reach
     perf_alert_consecutive_losses.
  2. LOW_WIN_RATE  — win rate over the last perf_alert_window_trades closed
     trades drops below perf_alert_min_win_rate_pct (requires a full window;
     small samples never alert).

De-duplication: alerts are re-evaluated only when a NEW trade has closed
since the last alert for that rule (tracked in durable kv), so a persistent
condition never spams a notification on every tick.

PAPER TRADING / RESEARCH ONLY.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import phase20_store as store

KV_KEY = "perf_alert_state"


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _closed_trades() -> List[Dict[str, Any]]:
    """CLOSED Phase 20 ledger trades with realised P&L, oldest → newest.
    Same read-only source the circuit breaker uses."""
    from phase20_executor import get_ledger
    closed = [t for t in get_ledger(500)
              if t.get("status") == "CLOSED"
              and t.get("realized_pnl") is not None]
    closed.sort(key=lambda t: str(t.get("exit_ts") or ""))
    return closed


def compute_metrics(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Compute alert metrics from closed trades. Never raises upstream."""
    closed = _closed_trades()

    consecutive = 0
    for t in reversed(closed):
        if float(t.get("realized_pnl") or 0) < 0:
            consecutive += 1
        else:
            break

    window_n = int(settings.get("perf_alert_window_trades", 10) or 10)
    window = closed[-window_n:]
    win_rate: Optional[float] = None
    wins = 0
    if len(window) >= window_n:
        wins = sum(1 for t in window if float(t.get("realized_pnl") or 0) > 0)
        win_rate = round(wins / len(window) * 100.0, 1)

    last_id = str(closed[-1].get("id")) if closed else None
    return {
        "computed_at": _now_iso(),
        "closed_trades": len(closed),
        "consecutive_losses": consecutive,
        "window_trades": window_n,
        "window_filled": len(window) >= window_n,
        "window_wins": wins,
        "win_rate": win_rate,
        "last_closed_trade_id": last_id,
    }


def evaluate_and_notify(settings: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Evaluate the configured alert rules and add a notification for each rule
    that triggers on NEW information (a trade closed since the last alert for
    that rule). Advisory only — never blocks anything. Never raises.
    """
    try:
        if settings is None:
            settings = store.get_settings()
        if not settings.get("perf_alert_enabled", True):
            return {"enabled": False, "alerts": []}

        metrics = compute_metrics(settings)
        last_id = metrics.get("last_closed_trade_id")
        if last_id is None:
            return {"enabled": True, "alerts": [], "metrics": metrics}

        raw = store.kv_get(KV_KEY)
        state: Dict[str, Any] = raw if isinstance(raw, dict) else {}
        alerts: List[str] = []

        loss_limit = int(settings.get("perf_alert_consecutive_losses", 3) or 3)
        if metrics["consecutive_losses"] >= loss_limit:
            if state.get("losing_streak_last_id") != last_id:
                store.add_notification(
                    "PERFORMANCE_ALERT",
                    f"Losing streak: {metrics['consecutive_losses']} "
                    f"consecutive losing paper trades",
                    f"The strategy has closed {metrics['consecutive_losses']} "
                    f"losing paper trades in a row (alert threshold "
                    f"{loss_limit}). Review recent trades and consider "
                    f"pausing automation. Total closed trades: "
                    f"{metrics['closed_trades']}."
                    + (f" Win rate over last {metrics['window_trades']} "
                       f"trades: {metrics['win_rate']}%."
                       if metrics.get("win_rate") is not None else ""),
                    severity="WARN",
                    context={"rule": "LOSING_STREAK",
                             "consecutive_losses": metrics["consecutive_losses"],
                             "threshold": loss_limit,
                             "win_rate": metrics.get("win_rate"),
                             "window_trades": metrics.get("window_trades"),
                             "closed_trades": metrics["closed_trades"]},
                )
                state["losing_streak_last_id"] = last_id
                alerts.append("LOSING_STREAK")
        else:
            # Streak broken — allow a future streak to alert again.
            state.pop("losing_streak_last_id", None)

        min_wr = float(settings.get("perf_alert_min_win_rate_pct", 40.0) or 0.0)
        wr = metrics.get("win_rate")
        if wr is not None and min_wr > 0 and wr < min_wr:
            if state.get("low_win_rate_last_id") != last_id:
                store.add_notification(
                    "PERFORMANCE_ALERT",
                    f"Win rate {wr}% below {min_wr}% threshold",
                    f"Win rate over the last {metrics['window_trades']} closed "
                    f"paper trades is {wr}% ({metrics['window_wins']} wins / "
                    f"{metrics['window_trades']} trades), below the configured "
                    f"minimum of {min_wr}%. Consider reviewing entry gates or "
                    f"pausing automation. Current losing streak: "
                    f"{metrics['consecutive_losses']}.",
                    severity="WARN",
                    context={"rule": "LOW_WIN_RATE",
                             "win_rate": wr,
                             "threshold": min_wr,
                             "window_trades": metrics["window_trades"],
                             "window_wins": metrics["window_wins"],
                             "consecutive_losses": metrics["consecutive_losses"],
                             "closed_trades": metrics["closed_trades"]},
                )
                state["low_win_rate_last_id"] = last_id
                alerts.append("LOW_WIN_RATE")
        elif wr is not None and (min_wr <= 0 or wr >= min_wr):
            state.pop("low_win_rate_last_id", None)

        state["last_evaluated_at"] = metrics["computed_at"]
        try:
            store.kv_set(KV_KEY, state)
        except Exception:
            pass
        return {"enabled": True, "alerts": alerts, "metrics": metrics}
    except Exception as exc:
        return {"error": str(exc)[:200]}
