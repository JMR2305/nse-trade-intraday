"""
paper_exploration_engine.py — Paper Intraday Learning / Exploration Mode

When PAPER_EXPLORATION_MODE is enabled, the engine:

1. Cap-aware quantity resizing: BUY orders blocked ONLY by the pre-trade
   position-size cap (20%) are resized to the largest valid quantity instead
   of being rejected.  Label: SIZE_REDUCED_TO_CAP.

2. Exploratory WATCH trades: near-threshold WATCH candidates (confidence
   and R:R above the exploration minimums, with a volume or range signal)
   get a small paper trade within a separate daily exploration budget.
   Label: EXPERIMENTAL_BUY_FROM_WATCH.

Hard safety gates ALWAYS block exploration:
  market_closed, stale_scan (> 15 min), data_quality UNAVAILABLE,
  circuit_breaker tripped, no_price (entry_price == 0).

PAPER / RESEARCH ONLY — no broker APIs called, no live order placement.
Experimental trades go into `experimental_paper_trades`, NOT into the
canonical `phase20_paper_trades` ledger, so they never affect normal
trade counting, daily limits, or portfolio P&L.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import phase20_store as store
from scan_state_store import db_available, _connect

try:
    from phase3f_logging import get_logger as _get_logger
    _log = _get_logger("paper_exploration_engine")
except Exception:
    _log = None

# Hard-coded position-size cap from risk_validation/pre_trade.py.
# Must stay in sync with _MAX_POSITION_PCT there.
_PRETRADE_MAX_PCT = 20.0

_SCHEMA_READY = False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or _now()).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today_utc() -> str:
    return _now().strftime("%Y-%m-%d")


# ── DB schema ─────────────────────────────────────────────────────────────────

def _ensure_schema(conn) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS experimental_paper_trades (
                trade_id TEXT PRIMARY KEY,
                scan_id TEXT,
                snapshot_ts TEXT,
                symbol TEXT,
                action_type TEXT,
                original_action TEXT,
                entry_price DOUBLE PRECISION,
                fill_price DOUBLE PRECISION,
                quantity INTEGER,
                confidence DOUBLE PRECISION,
                opportunity_score DOUBLE PRECISION,
                rr_at_entry DOUBLE PRECISION,
                stop_loss DOUBLE PRECISION,
                target DOUBLE PRECISION,
                slippage DOUBLE PRECISION,
                reason_accepted TEXT,
                would_normally_reject TEXT,
                rule_allowed TEXT,
                strategy_id TEXT,
                strategy_name TEXT,
                regime TEXT,
                status TEXT DEFAULT 'OPEN',
                exit_ts TEXT,
                exit_price DOUBLE PRECISION,
                exit_rule TEXT,
                realized_pnl DOUBLE PRECISION,
                max_favorable_excursion DOUBLE PRECISION,
                max_adverse_excursion DOUBLE PRECISION,
                holding_days DOUBLE PRECISION,
                evidence JSONB,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
        # Index: fast today-lookup + dedup-by-symbol-open
        cur.execute(
            "CREATE INDEX IF NOT EXISTS exp_trades_created_idx "
            "ON experimental_paper_trades (created_at DESC)"
        )
        cur.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS exp_trades_open_sym_uidx "
            "ON experimental_paper_trades (symbol) WHERE status = 'OPEN'"
        )
    conn.commit()
    _SCHEMA_READY = True


def _with_db(fn, fallback):
    if not db_available():
        return fallback()
    try:
        conn = _connect()
        try:
            _ensure_schema(conn)
            return fn(conn)
        finally:
            conn.close()
    except Exception:
        return fallback()


# ── Budget tracking ───────────────────────────────────────────────────────────

def exploration_budget_today(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Return today's exploration budget utilisation."""
    max_trades = int(settings.get("exploration_max_trades_per_day", 2))
    max_exposure_pct = float(settings.get("exploration_max_total_exposure_pct", 10.0))

    today = _today_utc()

    def from_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT symbol, fill_price, quantity FROM experimental_paper_trades "
                "WHERE created_at::date = %s::date AND status IN ('OPEN', 'CLOSED')",
                (today,),
            )
            rows = cur.fetchall()
        return rows

    rows = _with_db(from_db, lambda: [])
    trades_used = len(rows) if rows else 0

    # Exposure: use portfolio total value to compute %
    portfolio_value = 50_000.0
    try:
        from paper_trader import get_portfolio
        portfolio_value = float(get_portfolio().get("total_value") or 50_000.0)
    except Exception:
        pass

    exposure_used_inr = 0.0
    if rows:
        for r in rows:
            price = float(r[1] or 0)
            qty = int(r[2] or 0)
            exposure_used_inr += price * qty

    exposure_used_pct = (exposure_used_inr / portfolio_value * 100.0) if portfolio_value > 0 else 0.0

    return {
        "trades_used": trades_used,
        "trades_remaining": max(0, max_trades - trades_used),
        # Canonical names
        "max_trades": max_trades,
        "max_exposure_pct": max_exposure_pct,
        # Dashboard-expected aliases (same values, different keys)
        "max_trades_per_day": max_trades,
        "max_total_exposure_pct": max_exposure_pct,
        "exposure_used_pct": round(exposure_used_pct, 2),
        "exposure_remaining_pct": round(max(0.0, max_exposure_pct - exposure_used_pct), 2),
        "budget_exhausted": (trades_used >= max_trades or
                             exposure_used_pct >= max_exposure_pct),
        "date": today,
    }


# ── Resize utility ────────────────────────────────────────────────────────────

def resize_to_cap(
    symbol: str,
    price: float,
    portfolio_value: float,
    settings: Dict[str, Any],
) -> int:
    """
    Return the largest integer qty such that qty × price ≤ effective_cap.

    effective_cap = min(per_stock_exposure_cap_pct, _PRETRADE_MAX_PCT)
    because the pre-trade validator in risk_validation/pre_trade.py
    enforces a hard 20% limit independent of settings.

    Returns 0 if no valid qty.
    """
    if price <= 0 or portfolio_value <= 0:
        return 0
    settings_cap_pct = float(settings.get("per_stock_exposure_cap_pct", 25.0))
    effective_cap_pct = min(settings_cap_pct, _PRETRADE_MAX_PCT)
    max_exposure = effective_cap_pct / 100.0 * portfolio_value
    qty = int(max_exposure / price)
    return max(0, qty)


# ── Hard safety gate check ────────────────────────────────────────────────────

def _check_hard_gates() -> Optional[str]:
    """
    Return a reason string if any hard gate is active, else None.
    Hard gates block ALL exploration regardless of mode settings.
    """
    try:
        from phase15_scan_context import build_scan_context
        ctx = build_scan_context()
    except Exception as exc:
        return f"Cannot read scan context: {exc}"

    if not ctx.get("available"):
        return "No scan available"

    age_s = float(ctx.get("scan_age_seconds") or 9999)
    if age_s > 15 * 60:
        return f"Scan stale: {age_s:.0f}s old (hard limit 900s)"

    # Market must be open
    try:
        from market_hours import market_status
        mstat = market_status()
        mstate = str(mstat.get("state") or mstat.get("market_state") or "").upper()
        if mstate != "OPEN":
            return f"Market not open (state={mstate})"
    except Exception as exc:
        return f"Market hours check failed: {exc}"

    # Circuit breaker
    try:
        from phase20_circuit_breaker import get_state as _cb_state
        cb = _cb_state()
        if cb.get("tripped"):
            return "Circuit breaker tripped"
    except Exception:
        # CB unavailable → block (fail-safe)
        return "Circuit breaker state unavailable (fail-safe block)"

    return None


# ── Has open experimental position for symbol? ────────────────────────────────

def _has_open_exp_position(symbol: str) -> bool:
    sym = symbol.upper()

    def from_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM experimental_paper_trades "
                "WHERE symbol = %s AND status = 'OPEN' LIMIT 1",
                (sym,),
            )
            return cur.fetchone() is not None

    return _with_db(from_db, lambda: False)


# ── Exploration candidate evaluation ──────────────────────────────────────────

def evaluate_exploration_candidates(
    settings: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Identify candidates for exploration trading.

    Returns dict with:
      hard_gate_blocked: bool + reason
      cap_resize_candidates: list of SIZE_REDUCED_TO_CAP candidates
      watch_candidates: list of EXPERIMENTAL_BUY_FROM_WATCH candidates
      budget: exploration_budget_today result
    """
    result: Dict[str, Any] = {
        "evaluated_at": _iso(),
        "hard_gate_blocked": False,
        "hard_gate_reason": None,
        "cap_resize_candidates": [],
        "watch_candidates": [],
        "budget": {},
        "skipped": [],
    }

    # Hard gates first
    gate_reason = _check_hard_gates()
    if gate_reason:
        result["hard_gate_blocked"] = True
        result["hard_gate_reason"] = gate_reason
        return result

    # Check budget
    budget = exploration_budget_today(settings)
    result["budget"] = budget
    if budget["budget_exhausted"]:
        result["hard_gate_blocked"] = True
        result["hard_gate_reason"] = "Daily exploration budget exhausted"
        return result

    # Load scan context + portfolio
    try:
        from phase15_scan_context import build_scan_context
        ctx = build_scan_context()
    except Exception as exc:
        result["hard_gate_blocked"] = True
        result["hard_gate_reason"] = f"Context load failed: {exc}"
        return result

    try:
        from paper_trader import get_portfolio
        portfolio = get_portfolio()
        portfolio_value = float(portfolio.get("total_value") or 50_000.0)
        cash = float(portfolio.get("cash") or 0.0)
        open_positions = {str(p["symbol"]).upper() for p in portfolio.get("positions", [])}
    except Exception:
        portfolio_value = 50_000.0
        cash = portfolio_value
        open_positions = set()

    symbols_ctx: Dict[str, Any] = ctx.get("symbols") or {}

    min_confidence = float(settings.get("exploration_min_confidence", 60.0))
    min_rr = float(settings.get("exploration_min_rr", 1.2))
    max_pct_per_trade = float(settings.get("exploration_max_pct_per_trade", 5.0))
    trades_remaining = budget["trades_remaining"]

    # ── 1. Cap-resize candidates (BUY blocked EXCLUSIVELY by position-size cap)
    # Only admits candidates whose SOLE failed gate is per_stock_cap.  Candidates
    # that failed any other gate (regime, data quality, confidence, etc.) are NOT
    # eligible for cap-resizing — they were rejected for a real signal reason.
    try:
        last_eval = store.kv_get("last_entry_evaluation") or {}
        if isinstance(last_eval, str):
            last_eval = json.loads(last_eval)
        buy_candidates = [
            c for c in last_eval.get("candidates", [])
            if (
                not c.get("eligible") and
                # Exactly one gate must have failed, and it must be per_stock_cap
                len([g for g in c.get("gates", []) if not g.get("passed")]) == 1 and
                any(g.get("gate") == "per_stock_cap" and not g.get("passed")
                    for g in c.get("gates", []))
            )
        ]
    except Exception:
        buy_candidates = []

    for cand in buy_candidates:
        if trades_remaining <= 0:
            break
        sym = str(cand.get("symbol") or "").upper()
        if not sym:
            continue

        # Skip if already has open experimental position
        if _has_open_exp_position(sym):
            result["skipped"].append({"symbol": sym, "reason": "open experimental position exists"})
            continue

        # Skip if already has open normal position
        if sym in open_positions:
            result["skipped"].append({"symbol": sym, "reason": "open normal position exists"})
            continue

        sizing = cand.get("sizing") or {}
        entry_price = float(sizing.get("entry_price") or 0)
        rr = float(sizing.get("rr_ratio") or 0)
        stop = float(sizing.get("stop_loss") or 0)
        target = float(sizing.get("target_price") or 0)
        conf = float(cand.get("confidence") or 0)
        dq = str((symbols_ctx.get(sym) or {}).get("data_quality") or "UNKNOWN").upper()

        if entry_price <= 0:
            result["skipped"].append({"symbol": sym, "reason": "no entry price"})
            continue
        if dq not in ("LIVE", "NEAR_LIVE"):
            result["skipped"].append({"symbol": sym, "reason": f"data_quality {dq} not LIVE/NEAR_LIVE"})
            continue

        resized_qty = resize_to_cap(sym, entry_price, portfolio_value, settings)
        if resized_qty < 1:
            result["skipped"].append({"symbol": sym, "reason": "resize yields 0 shares"})
            continue

        # Check cash available
        if resized_qty * entry_price > cash:
            result["skipped"].append({"symbol": sym, "reason": "insufficient cash after resize"})
            continue

        # Check exploration per-trade exposure
        exploration_exposure_pct = resized_qty * entry_price / portfolio_value * 100.0
        if exploration_exposure_pct > max_pct_per_trade:
            # Further cap to exploration limit
            resized_qty = int(max_pct_per_trade / 100.0 * portfolio_value / entry_price)
            if resized_qty < 1:
                result["skipped"].append({"symbol": sym, "reason": "exploration per-trade cap yields 0"})
                continue

        # Check budget exposure
        new_exposure_pct = resized_qty * entry_price / portfolio_value * 100.0
        if new_exposure_pct > budget["exposure_remaining_pct"]:
            result["skipped"].append({"symbol": sym, "reason": "would exceed exploration exposure budget"})
            continue

        result["cap_resize_candidates"].append({
            "symbol": sym,
            "action_type": "SIZE_REDUCED_TO_CAP",
            "original_action": str(cand.get("recommendation") or "BUY").upper(),
            "entry_price": entry_price,
            "quantity": resized_qty,
            "confidence": conf,
            "opportunity_score": float(cand.get("opportunity_score") or 0),
            "rr_at_entry": rr,
            "stop_loss": stop,
            "target": target,
            "strategy_id": cand.get("strategy_id"),
            "strategy_name": cand.get("strategy_name"),
            "regime": cand.get("regime"),
            "data_quality": dq,
            "reason_accepted": (
                f"BUY candidate resized from {int(sizing.get('quantity') or 0)} "
                f"to {resized_qty} shares to fit within "
                f"{min(_PRETRADE_MAX_PCT, float(settings.get('per_stock_exposure_cap_pct',25.0))):.0f}% cap"
            ),
            "would_normally_reject": (
                f"position_size_exceeded: "
                f"{int(sizing.get('quantity') or 0)} shares × ₹{entry_price:.0f} "
                f"= ₹{int(sizing.get('quantity') or 0)*entry_price:.0f} "
                f"= {int(sizing.get('quantity') or 0)*entry_price/portfolio_value*100:.1f}% "
                f"of portfolio (hard limit {_PRETRADE_MAX_PCT:.0f}%)"
            ),
            "rule_allowed": "SIZE_REDUCED_TO_CAP",
        })
        trades_remaining -= 1
        # Update budget remaining for next candidate
        budget["exposure_remaining_pct"] = max(
            0.0, budget["exposure_remaining_pct"] - new_exposure_pct)

    # ── 2. WATCH → EXPERIMENTAL_BUY_FROM_WATCH ───────────────────────────────
    watch_pool = [
        (s, r) for s, r in symbols_ctx.items()
        if str(r.get("final_action") or "").upper() == "WATCH"
    ]

    for sym_raw, rec in watch_pool:
        if trades_remaining <= 0:
            break
        sym = str(sym_raw).upper()

        if _has_open_exp_position(sym):
            result["skipped"].append({"symbol": sym, "reason": "open experimental position exists"})
            continue
        if sym in open_positions:
            result["skipped"].append({"symbol": sym, "reason": "open normal position exists"})
            continue

        entry_price = float(rec.get("entry_price") or 0)
        conf = float(rec.get("calibrated_confidence") or rec.get("confidence") or 0)
        opp = float(rec.get("opportunity_score") or 0)
        rr = float(rec.get("rr_ratio") or 0)
        stop = float(rec.get("stop_loss") or 0)
        target = float(rec.get("target_price") or 0)
        dq = str(rec.get("data_quality") or "UNKNOWN").upper()
        # volume_ratio may be top-level or nested under "indicators" depending
        # on the build_scan_context() version; try both paths.
        _indicators = rec.get("indicators") or {}
        vol_ratio = float(
            rec.get("volume_ratio") or _indicators.get("volume_ratio") or 0
        )

        # Hard filters for WATCH exploration
        if entry_price <= 0:
            result["skipped"].append({
                "symbol": sym, "reason": "no price",
                "gap_to_threshold": None
            })
            continue
        if dq not in ("LIVE", "NEAR_LIVE"):
            result["skipped"].append({
                "symbol": sym, "reason": f"data_quality={dq}",
                "gap_to_threshold": None
            })
            continue
        if conf < min_confidence:
            result["skipped"].append({
                "symbol": sym, "reason": "confidence below exploration_min_confidence",
                "confidence": conf, "min_confidence": min_confidence,
                "gap_to_threshold": round(min_confidence - conf, 1)
            })
            continue
        if rr < min_rr:
            result["skipped"].append({
                "symbol": sym, "reason": "R:R below exploration_min_rr",
                "rr": rr, "min_rr": min_rr,
                "gap_to_threshold": round(min_rr - rr, 2)
            })
            continue

        # Volume or intraday signal required
        rule_allowed = None
        if vol_ratio >= 1.2:
            rule_allowed = f"volume_ratio={vol_ratio:.2f}>=1.2"
        else:
            result["skipped"].append({
                "symbol": sym, "reason": "no volume/intraday signal (vol_ratio<1.2)",
                "vol_ratio": vol_ratio,
                "gap_to_threshold": round(max(0.0, 1.2 - vol_ratio), 2)
            })
            continue

        # Exploration sizing: up to exploration_max_pct_per_trade
        max_exposure_inr = max_pct_per_trade / 100.0 * portfolio_value
        qty = min(int(max_exposure_inr / entry_price), int(cash / entry_price))
        qty = max(0, qty)
        if qty < 1:
            result["skipped"].append({
                "symbol": sym, "reason": "exploration qty=0 (cash or pct limit)"
            })
            continue

        trade_exposure_pct = qty * entry_price / portfolio_value * 100.0
        if trade_exposure_pct > budget["exposure_remaining_pct"]:
            result["skipped"].append({
                "symbol": sym, "reason": "exceeds exploration exposure budget"
            })
            continue

        result["watch_candidates"].append({
            "symbol": sym,
            "action_type": "EXPERIMENTAL_BUY_FROM_WATCH",
            "original_action": "WATCH",
            "entry_price": entry_price,
            "quantity": qty,
            "confidence": conf,
            "opportunity_score": opp,
            "rr_at_entry": rr,
            "stop_loss": stop,
            "target": target,
            "strategy_id": rec.get("strategy_id"),
            "strategy_name": rec.get("strategy_name"),
            "regime": rec.get("regime"),
            "data_quality": dq,
            "vol_ratio": vol_ratio,
            "reason_accepted": (
                f"WATCH candidate: conf={conf:.1f}%, R:R={rr:.2f}, {rule_allowed}"
            ),
            "would_normally_reject": (
                "WATCH decision: confidence or opportunity_score did not reach "
                "BUY threshold in the normal Decision agent evaluation"
            ),
            "rule_allowed": rule_allowed,
        })
        trades_remaining -= 1
        budget["exposure_remaining_pct"] = max(
            0.0, budget["exposure_remaining_pct"] - trade_exposure_pct)

    return result


# ── Experimental trade insertion ──────────────────────────────────────────────

def _insert_exp_row(row: Dict[str, Any]) -> bool:
    """Insert one experimental trade. Returns True on success."""
    cols = [
        "trade_id", "scan_id", "snapshot_ts", "symbol", "action_type",
        "original_action", "entry_price", "fill_price", "quantity",
        "confidence", "opportunity_score", "rr_at_entry",
        "stop_loss", "target", "slippage",
        "reason_accepted", "would_normally_reject", "rule_allowed",
        "strategy_id", "strategy_name", "regime", "status", "evidence",
    ]

    def to_db(conn):
        ph = ", ".join(["%s"] * len(cols))
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO experimental_paper_trades ({', '.join(cols)}) "
                f"VALUES ({ph}) ON CONFLICT (trade_id) DO NOTHING",
                [json.dumps(row.get(c), default=str)
                 if c == "evidence" else row.get(c)
                 for c in cols],
            )
        conn.commit()
        return True

    return bool(_with_db(to_db, lambda: False))


def create_exploration_entry(
    candidate: Dict[str, Any],
    settings: Dict[str, Any],
    scan_id: Optional[str],
    snapshot_ts: Optional[str],
) -> Dict[str, Any]:
    """
    Create one experimental paper trade (does NOT call execute_buy,
    does NOT affect paper portfolio, does NOT create ORDER_SUBMITTED events).
    """
    sym = str(candidate.get("symbol") or "").upper()
    action_type = candidate.get("action_type", "EXPERIMENTAL_BUY_FROM_WATCH")
    entry_price = float(candidate.get("entry_price") or 0)
    qty = int(candidate.get("quantity") or 0)

    if not sym or entry_price <= 0 or qty < 1:
        return {"created": False, "symbol": sym, "reason": "Invalid candidate"}

    # Final duplicate guard
    if _has_open_exp_position(sym):
        return {"created": False, "symbol": sym,
                "reason": "Open experimental position already exists"}

    # Compute fill with slippage
    slip_pct = float(settings.get("slippage_pct", 0.15)) / 100.0
    fill_price = round(entry_price * (1 + slip_pct), 2)
    slippage = round(abs(fill_price - entry_price), 4)

    trade_id = f"EXP-{uuid.uuid4().hex[:10]}"
    now_iso = _iso()

    row = {
        "trade_id": trade_id,
        "scan_id": scan_id,
        "snapshot_ts": snapshot_ts,
        "symbol": sym,
        "action_type": action_type,
        "original_action": candidate.get("original_action", "WATCH"),
        "entry_price": entry_price,
        "fill_price": fill_price,
        "quantity": qty,
        "confidence": float(candidate.get("confidence") or 0),
        "opportunity_score": float(candidate.get("opportunity_score") or 0),
        "rr_at_entry": float(candidate.get("rr_at_entry") or 0),
        "stop_loss": float(candidate.get("stop_loss") or 0),
        "target": float(candidate.get("target") or 0),
        "slippage": slippage,
        "reason_accepted": candidate.get("reason_accepted"),
        "would_normally_reject": candidate.get("would_normally_reject"),
        "rule_allowed": candidate.get("rule_allowed"),
        "strategy_id": candidate.get("strategy_id"),
        "strategy_name": candidate.get("strategy_name"),
        "regime": candidate.get("regime"),
        "status": "OPEN",
        "evidence": {
            "data_quality": candidate.get("data_quality"),
            "vol_ratio": candidate.get("vol_ratio"),
            "entry_ts": now_iso,
            "settings_hash": settings.get("config_hash"),
        },
    }

    ok = _insert_exp_row(row)
    if not ok:
        return {"created": False, "symbol": sym, "reason": "DB insert failed"}

    # Emit exploration pipeline event (not ORDER_SUBMITTED — it's experimental)
    try:
        from pipeline_events import emit as _pe
        _pe(
            "EXPERIMENTAL_PAPER_TRADE_PLACED", "EXECUTION",
            scan_id=scan_id, symbol=sym,
            payload={
                "trade_id": trade_id,
                "action_type": action_type,
                "qty": qty,
                "fill_price": fill_price,
                "confidence": row["confidence"],
                "rr": row["rr_at_entry"],
                "rule_allowed": row["rule_allowed"],
                "label": "EXPERIMENTAL_PAPER_TRADE",
            },
        )
    except Exception:
        pass

    store.add_notification(
        "EXPLORATION_ENTRY_CREATED",
        f"Experimental paper trade: {sym} ({action_type})",
        f"{qty} shares @ ₹{fill_price:.2f} | conf={row['confidence']:.1f}% | "
        f"R:R={row['rr_at_entry']:.2f} | rule={row['rule_allowed']}",
        severity="INFO",
        context={"trade_id": trade_id, "symbol": sym,
                 "action_type": action_type, "scan_id": scan_id},
    )

    return {"created": True, "symbol": sym, "trade_id": trade_id,
            "action_type": action_type, "qty": qty, "fill_price": fill_price}


# ── Exit / MFE / MAE tracking ─────────────────────────────────────────────────

def update_experimental_exits(settings: Dict[str, Any]) -> Dict[str, Any]:
    """
    For each OPEN experimental trade, update MFE/MAE from current prices
    and close any that hit stop or target.
    Called from the exploration tick each scheduler run.
    """
    max_holding_days = int(settings.get("max_holding_days", 10))

    def get_open(conn):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT trade_id, symbol, fill_price, quantity, stop_loss, target, "
                "max_favorable_excursion, max_adverse_excursion, created_at "
                "FROM experimental_paper_trades WHERE status = 'OPEN'"
            )
            rows = cur.fetchall()
        return rows

    open_trades = _with_db(get_open, lambda: [])
    if not open_trades:
        return {"checked": 0, "closed": 0}

    symbols = [str(r[1]).upper() for r in open_trades]
    prices: Dict[str, float] = {}
    try:
        from market_data import get_multiple_ltp
        prices = get_multiple_ltp(symbols) or {}
    except Exception:
        pass

    now = _now()
    closed_count = 0

    for row in open_trades:
        tid, sym, fill_px, qty, stop, target, mfe, mae, created_at = row
        sym = str(sym or "").upper()
        cur_price = float(prices.get(sym) or prices.get(sym + ".NS") or 0)
        if cur_price <= 0:
            continue

        fill_px = float(fill_px or 0)
        stop = float(stop or 0)
        target = float(target or 0)
        qty = int(qty or 0)
        mfe = float(mfe or 0)
        mae = float(mae or 0)

        pnl_per_share = cur_price - fill_px
        new_mfe = max(mfe, pnl_per_share)
        new_mae = min(mae, pnl_per_share)

        exit_reason = None
        if stop > 0 and cur_price <= stop:
            exit_reason = "STOP_LOSS"
        elif target > 0 and cur_price >= target:
            exit_reason = "TARGET_HIT"
        elif created_at:
            try:
                if isinstance(created_at, str):
                    from datetime import timezone as _tz
                    created_dt = datetime.fromisoformat(
                        created_at.replace("Z", "+00:00"))
                else:
                    created_dt = created_at
                if created_dt.tzinfo is None:
                    from datetime import timezone as _tz
                    created_dt = created_dt.replace(tzinfo=_tz.utc)
                days_held = (now - created_dt).total_seconds() / 86400.0
                if days_held >= max_holding_days:
                    exit_reason = "MAX_HOLDING_DAYS"
            except Exception:
                pass

        def upd(conn, _tid=tid, _mfe=new_mfe, _mae=new_mae,
                _exit_reason=exit_reason, _cur_price=cur_price,
                _fill_px=fill_px, _qty=qty):
            realized_pnl = round((_cur_price - _fill_px) * _qty, 2) if _exit_reason else None
            if _exit_reason:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE experimental_paper_trades "
                        "SET status='CLOSED', exit_ts=%s, exit_price=%s, exit_rule=%s, "
                        "realized_pnl=%s, max_favorable_excursion=%s, "
                        "max_adverse_excursion=%s, updated_at=NOW() "
                        "WHERE trade_id=%s",
                        (_iso(), _cur_price, _exit_reason,
                         realized_pnl, _mfe, _mae, _tid),
                    )
            else:
                with conn.cursor() as cur:
                    cur.execute(
                        "UPDATE experimental_paper_trades "
                        "SET max_favorable_excursion=%s, max_adverse_excursion=%s, "
                        "updated_at=NOW() WHERE trade_id=%s",
                        (_mfe, _mae, _tid),
                    )
            conn.commit()
            return True

        _with_db(upd, lambda: None)
        if exit_reason:
            closed_count += 1

    return {"checked": len(open_trades), "closed": closed_count}


# ── Learning summary ──────────────────────────────────────────────────────────

def get_exploration_learning_summary() -> Dict[str, Any]:
    """
    Per-rule win rates, average MFE/MAE, and natural-language observations
    from completed experimental trades.
    """
    def load_closed(conn):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT action_type, rule_allowed, realized_pnl, "
                "max_favorable_excursion, max_adverse_excursion, "
                "rr_at_entry, confidence, holding_days, fill_price "
                "FROM experimental_paper_trades WHERE status='CLOSED'"
            )
            return [dict(zip(
                ["action_type", "rule_allowed", "realized_pnl", "mfe",
                 "mae", "rr_at_entry", "confidence", "holding_days",
                 "fill_price"],
                r)) for r in cur.fetchall()]

    trades = _with_db(load_closed, lambda: [])
    if not trades:
        return {
            "sample_size": 0,
            "reliability": "INSUFFICIENT",
            "by_rule": {},
            "observation": (
                "No completed experimental trades yet — "
                "exploration mode needs at least one closed trade to learn."
            ),
        }

    by_rule: Dict[str, Any] = {}
    for t in trades:
        rule = str(t.get("rule_allowed") or t.get("action_type") or "UNKNOWN")
        by_rule.setdefault(rule, {"wins": 0, "losses": 0, "pnl": [],
                                  "mfe": [], "mae": [], "rr": []})
        pnl = float(t.get("realized_pnl") or 0)
        by_rule[rule]["pnl"].append(pnl)
        if pnl > 0:
            by_rule[rule]["wins"] += 1
        else:
            by_rule[rule]["losses"] += 1
        # MFE/MAE stored as ₹/share absolute; convert to % of fill price
        # so all downstream callers receive percentage values.
        _fill_px = float(t.get("fill_price") or 0)
        if t.get("mfe") is not None and _fill_px > 0:
            by_rule[rule]["mfe"].append(float(t["mfe"]) / _fill_px * 100.0)
        if t.get("mae") is not None and _fill_px > 0:
            by_rule[rule]["mae"].append(float(t["mae"]) / _fill_px * 100.0)
        if t.get("rr_at_entry"):
            by_rule[rule]["rr"].append(float(t["rr_at_entry"]))

    rule_summaries: Dict[str, Any] = {}
    observations: List[str] = []
    for rule, d in by_rule.items():
        n = len(d["pnl"])
        win_rate = d["wins"] / n if n else 0
        avg_mfe = sum(d["mfe"]) / len(d["mfe"]) if d["mfe"] else None
        avg_mae = sum(d["mae"]) / len(d["mae"]) if d["mae"] else None
        avg_pnl = sum(d["pnl"]) / n if n else 0
        rule_summaries[rule] = {
            "sample_size": n,
            "win_rate": round(win_rate, 3),
            "avg_pnl": round(avg_pnl, 2),
            "avg_mfe": round(avg_mfe, 4) if avg_mfe is not None else None,
            "avg_mae": round(avg_mae, 4) if avg_mae is not None else None,
        }
        # Natural-language observation
        if n >= 3:
            wr_pct = win_rate * 100
            if rule == "SIZE_REDUCED_TO_CAP":
                observations.append(
                    f"Cap-resized BUY trades ({n} trades): {wr_pct:.0f}% win rate, "
                    f"avg P&L ₹{avg_pnl:.0f} — "
                    + ("signals are viable after resizing." if wr_pct >= 50
                       else "resized signals are underperforming; review cap threshold.")
                )
            else:
                observations.append(
                    f"WATCH exploration ({rule}, {n} trades): {wr_pct:.0f}% win rate, "
                    f"avg P&L ₹{avg_pnl:.0f} — "
                    + ("volume signal trades are profitable." if wr_pct >= 55
                       else "volume signal alone is insufficient; needs additional confirmation.")
                )

    return {
        "sample_size": len(trades),
        "reliability": "LOW" if len(trades) >= 3 else "INSUFFICIENT",
        "by_rule": rule_summaries,
        "observation": " ".join(observations) if observations else (
            "Insufficient completed experimental trades for learning (<3)."
        ),
    }


# ── Daily report ──────────────────────────────────────────────────────────────

def generate_daily_report() -> Dict[str, Any]:
    """
    Generate PAPER_INTRADAY_LEARNING_EXECUTION_REPORT for the latest market day.
    Returns markdown text and structured data.
    """
    from datetime import timezone as _tz

    # IST today
    try:
        from zoneinfo import ZoneInfo
        now_ist = datetime.now(ZoneInfo("Asia/Kolkata"))
        ist_date = now_ist.strftime("%Y-%m-%d")
        ist_label = now_ist.strftime("%d %b %Y")
    except Exception:
        ist_date = _today_utc()
        ist_label = ist_date

    # Scan counts today
    total_scans = 0
    try:
        from scan_state_store import count_scans_today_ist
        total_scans = count_scans_today_ist() or 0
    except Exception:
        pass

    # Pipeline event counts (BUY_GENERATED / WATCH_GENERATED / ORDER_REJECTED)
    buy_gen = watch_gen = order_rej = 0
    try:
        from scan_state_store import _connect as _sc, db_available as _dba
        if _dba():
            conn = _sc()
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT event_type, COUNT(*) FROM pipeline_events "
                    "WHERE created_at::date = NOW()::date "
                    "GROUP BY event_type",
                )
                for et, cnt in cur.fetchall():
                    if et == "BUY_GENERATED":
                        buy_gen = int(cnt)
                    elif et == "WATCH_GENERATED":
                        watch_gen = int(cnt)
                    elif et == "ORDER_REJECTED":
                        order_rej = int(cnt)
            conn.close()
    except Exception:
        pass

    # Normal paper trades today
    normal_trades_today: List[Dict[str, Any]] = []
    try:
        from phase20_executor import get_ledger
        for t in get_ledger(100):
            ts = str(t.get("simulated_order_ts") or t.get("created_at") or "")
            if ts.startswith(ist_date):
                normal_trades_today.append(t)
    except Exception:
        pass

    # Experimental trades today
    def load_exp_today(conn):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT trade_id, symbol, action_type, fill_price, quantity, "
                "confidence, rr_at_entry, realized_pnl, status, rule_allowed, "
                "reason_accepted, would_normally_reject "
                "FROM experimental_paper_trades "
                "WHERE created_at::date = %s::date "
                "ORDER BY created_at DESC",
                (ist_date,),
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    exp_trades = _with_db(load_exp_today, lambda: [])
    learning = get_exploration_learning_summary()

    # Compute experimental P&L
    exp_pnl = sum(float(t.get("realized_pnl") or 0) for t in exp_trades
                  if t.get("status") == "CLOSED")

    # Build markdown
    md_lines = [
        f"# PAPER_INTRADAY_LEARNING_EXECUTION_REPORT",
        f"",
        f"**Date:** {ist_label} (IST)  ",
        f"**Generated:** {_iso()}  ",
        f"",
        f"## Summary",
        f"",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Total scans | {total_scans} |",
        f"| BUY_GENERATED events | {buy_gen} |",
        f"| WATCH_GENERATED events | {watch_gen} |",
        f"| ORDER_REJECTED events | {order_rej} |",
        f"| Normal paper trades executed | {len(normal_trades_today)} |",
        f"| Experimental trades placed | {len(exp_trades)} |",
        f"| Experimental trades closed | {sum(1 for t in exp_trades if t.get('status')=='CLOSED')} |",
        f"| Experimental P&L (closed) | ₹{exp_pnl:.2f} |",
        f"",
    ]

    if order_rej > 0:
        md_lines += [
            f"## Order Rejections",
            f"",
            f"{order_rej} paper BUY orders were rejected today. "
            f"Most likely cause: position size exceeds the 20% pre-trade cap. "
            f"Cap-aware resizing (PAPER_EXPLORATION_MODE) would convert these "
            f"to smaller valid trades.",
            f"",
        ]

    if exp_trades:
        md_lines += [
            f"## Experimental Trades",
            f"",
            f"| Symbol | Type | Fill ₹ | Qty | Conf% | R:R | Status | P&L ₹ | Rule |",
            f"|--------|------|--------|-----|-------|-----|--------|--------|------|",
        ]
        for t in exp_trades:
            pnl_str = f"₹{float(t.get('realized_pnl') or 0):.2f}" if t.get("realized_pnl") is not None else "—"
            md_lines.append(
                f"| {t.get('symbol')} | {t.get('action_type','').replace('_',' ')} | "
                f"₹{float(t.get('fill_price') or 0):.2f} | {t.get('quantity')} | "
                f"{float(t.get('confidence') or 0):.1f} | "
                f"{float(t.get('rr_at_entry') or 0):.2f} | {t.get('status')} | "
                f"{pnl_str} | {t.get('rule_allowed') or '—'} |"
            )
        md_lines.append("")
    else:
        md_lines += [f"## Experimental Trades", f"", f"No experimental trades placed today.", f""]

    md_lines += [
        f"## AI Learning Observations",
        f"",
        f"**Sample size:** {learning.get('sample_size', 0)} completed experimental trades  ",
        f"**Reliability:** {learning.get('reliability', 'INSUFFICIENT')}  ",
        f"",
        f"{learning.get('observation', '')}",
        f"",
    ]

    if learning.get("by_rule"):
        md_lines += [
            f"### Per-Rule Statistics",
            f"",
            f"| Rule | Trades | Win Rate | Avg P&L ₹ |",
            f"|------|--------|----------|-----------|",
        ]
        for rule, stats in learning["by_rule"].items():
            md_lines.append(
                f"| {rule} | {stats.get('sample_size',0)} | "
                f"{stats.get('win_rate',0)*100:.0f}% | "
                f"₹{stats.get('avg_pnl',0):.2f} |"
            )
        md_lines.append("")

    md_lines += [
        f"*PAPER TRADING / RESEARCH ONLY — no live orders.*",
    ]

    markdown = "\n".join(md_lines)

    return {
        "date": ist_date,
        "markdown": markdown,
        "total_scans": total_scans,
        "buy_generated": buy_gen,
        "watch_generated": watch_gen,
        "order_rejected": order_rej,
        "normal_trades_today": len(normal_trades_today),
        "experimental_trades_today": len(exp_trades),
        "experimental_pnl": round(exp_pnl, 2),
        "learning": learning,
    }


# ── Main tick entry point ─────────────────────────────────────────────────────

def run_exploration_tick(settings: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main entry point called by phase20_scheduler._manage_exploration().

    1. Updates MFE/MAE and exits for open experimental trades.
    2. Evaluates new exploration candidates.
    3. Creates exploration entries within the daily budget.
    Returns a summary dict (never raises).
    """
    result: Dict[str, Any] = {
        "ran": False, "reason": None,
        "exits": {}, "created": [], "skipped": [],
        "cap_resize": 0, "watch_explore": 0,
    }

    if not settings.get("paper_exploration_mode"):
        result["reason"] = "PAPER_EXPLORATION_MODE disabled"
        return result

    # Update exits first
    try:
        result["exits"] = update_experimental_exits(settings)
    except Exception as exc:
        result["exits"] = {"error": str(exc)[:200]}

    # Evaluate new candidates
    try:
        evaluation = evaluate_exploration_candidates(settings)
    except Exception as exc:
        # Persist a minimal failed-evaluation snapshot so the status endpoint
        # always has fresh gate state, even when evaluation throws.
        try:
            store.kv_set("last_exploration_eval", json.dumps({
                "evaluated_at": _iso(),
                "hard_gate_blocked": True,
                "hard_gate_reason": f"Evaluation error: {str(exc)[:200]}",
                "candidates": [],
            }, default=str))
        except Exception:
            pass
        result["reason"] = f"Evaluation failed: {exc}"
        return result

    result["ran"] = True
    result["skipped"] = evaluation.get("skipped", [])

    # ── Always persist evaluation state before any early return ──────────────
    # This ensures the status endpoint shows current hard-gate state even when
    # gates block entry (the most important time for operators to see warnings).
    def _persist_eval(eval_dict: Dict[str, Any]) -> None:
        try:
            combined = []
            for c in eval_dict.get("cap_resize_candidates", []):
                combined.append({
                    "symbol": c.get("symbol"),
                    "rule_type": c.get("action_type", "SIZE_REDUCED_TO_CAP"),
                    "price": c.get("entry_price", 0),
                    "confidence": c.get("confidence", 0),
                    "rr_ratio": c.get("rr_at_entry", 0),
                    "quantity": c.get("quantity", 0),
                    "eligible": True,
                    "blocked_reason": None,
                })
            for c in eval_dict.get("watch_candidates", []):
                combined.append({
                    "symbol": c.get("symbol"),
                    "rule_type": c.get("action_type", "EXPERIMENTAL_BUY_FROM_WATCH"),
                    "price": c.get("entry_price", 0),
                    "confidence": c.get("confidence", 0),
                    "rr_ratio": c.get("rr_at_entry", 0),
                    "quantity": c.get("quantity", 0),
                    "eligible": True,
                    "blocked_reason": None,
                })
            for s in eval_dict.get("skipped", []):
                combined.append({
                    "symbol": s.get("symbol", ""),
                    "rule_type": "SIZE_REDUCED_TO_CAP",
                    "price": 0,
                    "confidence": 0,
                    "rr_ratio": 0,
                    "quantity": 0,
                    "eligible": False,
                    "blocked_reason": s.get("reason"),
                })
            store.kv_set("last_exploration_eval", json.dumps({
                "evaluated_at": eval_dict.get("evaluated_at", _iso()),
                "hard_gate_blocked": eval_dict.get("hard_gate_blocked", False),
                "hard_gate_reason": eval_dict.get("hard_gate_reason"),
                "candidates": combined,
            }, default=str))
        except Exception:
            pass

    _persist_eval(evaluation)

    if evaluation.get("hard_gate_blocked"):
        result["reason"] = evaluation.get("hard_gate_reason", "Hard gate blocked")
        return result

    scan_id = None
    snapshot_ts = None
    try:
        from phase15_scan_context import build_scan_context
        ctx = build_scan_context()
        scan_id = ctx.get("scan_id")
        snapshot_ts = ctx.get("snapshot_ts")
    except Exception:
        pass

    all_candidates = (
        evaluation.get("cap_resize_candidates", []) +
        evaluation.get("watch_candidates", [])
    )

    for cand in all_candidates:
        try:
            entry_result = create_exploration_entry(
                cand, settings, scan_id, snapshot_ts)
            result["created"].append(entry_result)
            if entry_result.get("created"):
                atype = cand.get("action_type", "")
                if atype == "SIZE_REDUCED_TO_CAP":
                    result["cap_resize"] += 1
                else:
                    result["watch_explore"] += 1
        except Exception as exc:
            result["created"].append({
                "created": False,
                "symbol": cand.get("symbol"),
                "reason": str(exc)[:200],
            })

    result["budget"] = evaluation.get("budget", {})
    return result


# ── Status endpoint helper ────────────────────────────────────────────────────

def _normalise_trade_row(r: dict) -> dict:
    """
    Map actual DB column names → dashboard-expected field names.

    MFE/MAE are stored as rupee-per-share price differences (cur_price - fill_px).
    Convert to percentages relative to entry/fill price so the dashboard renders
    meaningful values (e.g. +1.5% rather than ₹18).
    """
    ca = r.get("created_at")
    if hasattr(ca, "isoformat"):
        ca = ca.isoformat()
    entry_px = float(r.get("entry_price") or r.get("fill_price") or 0)
    # MFE/MAE stored as ₹/share absolute; convert to % of entry price
    raw_mfe = r.get("max_favorable_excursion")
    raw_mae = r.get("max_adverse_excursion")
    mfe_pct = round(float(raw_mfe) / entry_px * 100, 2) if raw_mfe is not None and entry_px > 0 else None
    mae_pct = round(float(raw_mae) / entry_px * 100, 2) if raw_mae is not None and entry_px > 0 else None
    return {
        "id": r.get("trade_id"),
        "symbol": r.get("symbol"),
        "rule_type": r.get("action_type"),
        "entry_price": entry_px,
        "stop_price": float(r.get("stop_loss") or 0),
        "target_price": float(r.get("target") or 0),
        "quantity": int(r.get("quantity") or 0),
        "confidence": float(r.get("confidence") or 0),
        "rr_ratio": float(r.get("rr_at_entry") or 0),
        "status": r.get("status", "OPEN"),
        "entry_ts": ca,
        "exit_ts": r.get("exit_ts"),
        "exit_price": r.get("exit_price"),
        "realized_pnl": r.get("realized_pnl"),
        "mfe_pct": mfe_pct,
        "mae_pct": mae_pct,
        "notes": r.get("reason_accepted"),
    }


def get_exploration_status(settings: Dict[str, Any]) -> Dict[str, Any]:
    """
    Full status for the /api/paper/exploration/status endpoint.

    Returns the exact shape the PaperLearningMode dashboard expects:
      enabled, settings, budget, open_trades, candidates,
      learning_summary, hard_gates_blocked, last_tick_at, label
    """
    enabled = bool(settings.get("paper_exploration_mode", False))
    budget = exploration_budget_today(settings)

    # ── Open experimental positions ───────────────────────────────────────────
    def load_open(conn):
        with conn.cursor() as cur:
            cur.execute(
                "SELECT trade_id, symbol, action_type, entry_price, fill_price, "
                "stop_loss, target, quantity, confidence, rr_at_entry, "
                "status, exit_ts, exit_price, realized_pnl, "
                "max_favorable_excursion, max_adverse_excursion, "
                "reason_accepted, created_at "
                "FROM experimental_paper_trades "
                "WHERE status = 'OPEN' "
                "ORDER BY created_at DESC"
            )
            cols = [d[0] for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    open_trades = [_normalise_trade_row(r)
                   for r in _with_db(load_open, lambda: [])]

    # ── Candidates + hard-gate status from last persisted evaluation ──────────
    last_eval: dict = {}
    try:
        raw = store.kv_get("last_exploration_eval")
        if raw:
            last_eval = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        pass

    candidates = last_eval.get("candidates", [])
    hard_gates_blocked: List[str] = []
    if last_eval.get("hard_gate_blocked"):
        reason = last_eval.get("hard_gate_reason")
        if reason:
            hard_gates_blocked = [reason]

    # ── Learning summary: convert by_rule dict → list the dashboard renders ───
    raw_learning = get_exploration_learning_summary()
    learning_summary = []
    for rule, stats in raw_learning.get("by_rule", {}).items():
        learning_summary.append({
            "rule_type": rule,
            "trades": stats.get("sample_size", 0),
            "win_rate_pct": round(float(stats.get("win_rate", 0)) * 100, 1),
            "avg_mfe_pct": float(stats.get("avg_mfe") or 0.0),
            "avg_mae_pct": abs(float(stats.get("avg_mae") or 0.0)),
            "observation": raw_learning.get("observation", ""),
        })

    return {
        "enabled": enabled,
        "settings": {
            k: settings.get(k)
            for k in [
                "paper_exploration_mode",
                "exploration_max_pct_per_trade",
                "exploration_max_trades_per_day",
                "exploration_max_total_exposure_pct",
                "exploration_min_rr",
                "exploration_min_confidence",
            ]
        },
        "budget": budget,
        "open_trades": open_trades,
        "candidates": candidates,
        "learning_summary": learning_summary,
        "hard_gates_blocked": hard_gates_blocked,
        "last_tick_at": last_eval.get("evaluated_at"),
        "label": "PAPER / RESEARCH ONLY — EXPERIMENTAL",
    }
