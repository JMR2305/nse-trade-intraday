"""
phase20_executor.py — Phase 20 paper entry execution and durable trade ledger.

When every eligibility gate passes, this module creates a simulated order +
position with a configurable paper fill model:

  LAST_TRADED_PRICE : fill at the stored eligible quote
  NEXT_QUOTE        : fill at the quote plus half the configured slippage
                      (approximates the next tick without look-ahead)
  SLIPPAGE_ADJUSTED : fill at the quote plus the full configured slippage
                      (default — most conservative)

Every trade row stores scan_id, snapshot_ts, strategy/model/rule versions,
config hash and the full decision evidence so decisions are reproducible.
Duplicates for a symbol with an open position are never created.

PAPER TRADING / RESEARCH ONLY. No live orders anywhere in this module.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import phase20_store as store
from scan_state_store import db_available, _connect

try:
    from phase3f_logging import get_logger as _get_logger
    _log = _get_logger("phase20_executor")
except Exception:
    _log = None

_DIR = os.path.dirname(os.path.abspath(__file__))
_LEDGER_FILE = os.path.join(_DIR, "phase20_ledger.json")

RULE_VERSION = "phase20-v1"

_SCHEMA_READY = False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or _now()).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_schema(conn) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS phase20_paper_trades (
                trade_id TEXT PRIMARY KEY,
                scan_id TEXT,
                snapshot_ts TEXT,
                symbol TEXT,
                sector TEXT,
                strategy_id TEXT,
                strategy_name TEXT,
                side TEXT,
                signal_ts TEXT,
                decision_ts TEXT,
                simulated_order_ts TEXT,
                fill_ts TEXT,
                signal_price DOUBLE PRECISION,
                fill_price DOUBLE PRECISION,
                quantity INTEGER,
                stop_loss DOUBLE PRECISION,
                target DOUBLE PRECISION,
                risk_amount DOUBLE PRECISION,
                est_charges DOUBLE PRECISION,
                slippage DOUBLE PRECISION,
                fill_model TEXT,
                confidence DOUBLE PRECISION,
                opportunity_score DOUBLE PRECISION,
                trade_quality_score DOUBLE PRECISION,
                regime TEXT,
                model_version TEXT,
                rule_version TEXT,
                config_hash TEXT,
                trigger_source TEXT,
                status TEXT,
                exit_ts TEXT,
                exit_price DOUBLE PRECISION,
                exit_rule TEXT,
                exit_scan_id TEXT,
                realized_pnl DOUBLE PRECISION,
                evidence JSONB,
                recomputed BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS phase20_open_symbol_uidx
            ON phase20_paper_trades (symbol) WHERE status = 'OPEN'
            """
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


_COLS = [
    "trade_id", "scan_id", "snapshot_ts", "symbol", "sector", "strategy_id",
    "strategy_name", "side", "signal_ts", "decision_ts", "simulated_order_ts",
    "fill_ts", "signal_price", "fill_price", "quantity", "stop_loss", "target",
    "risk_amount", "est_charges", "slippage", "fill_model", "confidence",
    "opportunity_score", "trade_quality_score", "regime", "model_version",
    "rule_version", "config_hash", "trigger_source", "status", "exit_ts",
    "exit_price", "exit_rule", "exit_scan_id", "realized_pnl", "evidence",
    "recomputed",
]


class DuplicateOpenTrade(Exception):
    """Raised when an OPEN Phase 20 trade already exists for the symbol."""


def _insert_row(row: Dict[str, Any]) -> None:
    """Insert a ledger row. Raises DuplicateOpenTrade if the partial unique
    index (one OPEN trade per symbol) rejects the insert."""
    if db_available():
        try:
            conn = _connect()
            try:
                _ensure_schema(conn)
                with conn.cursor() as cur:
                    placeholders = ", ".join(["%s"] * len(_COLS))
                    cur.execute(
                        f"INSERT INTO phase20_paper_trades ({', '.join(_COLS)}) "
                        f"VALUES ({placeholders})",
                        [json.dumps(row.get(c), default=str) if c == "evidence"
                         else row.get(c) for c in _COLS],
                    )
                conn.commit()
                return
            finally:
                conn.close()
        except Exception as exc:
            name = type(exc).__name__
            if "UniqueViolation" in name or "unique" in str(exc).lower():
                raise DuplicateOpenTrade(str(row.get("symbol"))) from exc
            # fall through to file fallback on other DB errors

    rows = _read_ledger_file()
    if row.get("status") == "OPEN" and any(
            r.get("status") == "OPEN"
            and str(r.get("symbol", "")).upper() == str(row.get("symbol", "")).upper()
            for r in rows):
        raise DuplicateOpenTrade(str(row.get("symbol")))
    rows.append(row)
    _write_ledger_file(rows)


def _delete_row(trade_id: str) -> None:
    def to_db(conn):
        with conn.cursor() as cur:
            cur.execute("DELETE FROM phase20_paper_trades WHERE trade_id = %s",
                        [trade_id])
        conn.commit()
        return True

    def to_file():
        rows = [r for r in _read_ledger_file() if r.get("trade_id") != trade_id]
        _write_ledger_file(rows)

    _with_db(to_db, to_file)


def _update_row(trade_id: str, fields: Dict[str, Any]) -> None:
    def to_db(conn):
        sets = ", ".join(f"{k} = %s" for k in fields) + ", updated_at = NOW()"
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE phase20_paper_trades SET {sets} WHERE trade_id = %s",
                list(fields.values()) + [trade_id],
            )
        conn.commit()
        return True

    def to_file():
        rows = _read_ledger_file()
        for r in rows:
            if r.get("trade_id") == trade_id:
                r.update(fields)
        _write_ledger_file(rows)

    _with_db(to_db, to_file)


def _read_ledger_file() -> List[Dict[str, Any]]:
    try:
        with open(_LEDGER_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def _write_ledger_file(rows: List[Dict[str, Any]]) -> None:
    try:
        with open(_LEDGER_FILE, "w") as f:
            json.dump(rows[-500:], f, default=str)
    except Exception:
        pass


def get_ledger(limit: int = 200) -> List[Dict[str, Any]]:
    def from_db(conn):
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {', '.join(_COLS)}, created_at FROM phase20_paper_trades "
                f"ORDER BY created_at DESC LIMIT %s",
                (int(limit),),
            )
            rows = cur.fetchall()
        out = []
        for r in rows:
            item = dict(zip(_COLS, r[:-1]))
            if isinstance(item.get("evidence"), str):
                try:
                    item["evidence"] = json.loads(item["evidence"])
                except Exception:
                    pass
            item["created_at"] = _iso(r[-1]) if isinstance(r[-1], datetime) else r[-1]
            out.append(item)
        return out

    return _with_db(from_db, lambda: list(reversed(_read_ledger_file()))[:limit])


def get_trade(trade_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a single trade row by trade_id.

    This function queries the DB directly by primary key — it does NOT go
    through get_ledger(500), which is bounded to the 500 newest rows.  A trade
    opened before 500 newer trades were created would be invisible via
    get_ledger, causing record_exit() to silently skip the update and leave the
    row permanently EXIT_PENDING.

    File fallback: scans the entire ledger file (no row cap).
    """
    def from_db(conn) -> Optional[Dict[str, Any]]:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {', '.join(_COLS)}, created_at "
                f"FROM phase20_paper_trades WHERE trade_id = %s",
                (trade_id,),
            )
            row = cur.fetchone()
        if row is None:
            return None
        item = dict(zip(_COLS, row[:-1]))
        if isinstance(item.get("evidence"), str):
            try:
                item["evidence"] = json.loads(item["evidence"])
            except Exception:
                pass
        item["created_at"] = _iso(row[-1]) if isinstance(row[-1], datetime) else row[-1]
        return item

    def from_file() -> Optional[Dict[str, Any]]:
        # Scan entire file — no row cap so legacy rows are never missed.
        for r in _read_ledger_file():
            if r.get("trade_id") == trade_id:
                return r
        return None

    return _with_db(from_db, from_file)


def get_open_trades() -> List[Dict[str, Any]]:
    return [t for t in get_ledger(500) if t.get("status") == "OPEN"]


def get_exit_pending_trades() -> List[Dict[str, Any]]:
    """Return ALL rows with status='EXIT_PENDING' with no row-count limit.

    Unlike get_ledger(500) — which fetches the 500 newest rows regardless of
    status — this function queries EXIT_PENDING rows directly and exhausts the
    full result set.  This is the correct source for _resolve_timeout_exit_pending
    and _retry_pending: a trade that entered EXIT_PENDING before 500 newer trades
    were created would otherwise fall out of the get_ledger window and be
    permanently stranded, defeating the force-close guarantee.

    File fallback: scans the entire local ledger file for EXIT_PENDING rows.
    """
    def from_db(conn) -> List[Dict[str, Any]]:
        with conn.cursor() as cur:
            cur.execute(
                f"SELECT {', '.join(_COLS)}, created_at "
                f"FROM phase20_paper_trades "
                f"WHERE status = 'EXIT_PENDING' "
                f"ORDER BY created_at ASC",   # oldest first so we resolve in FIFO order
            )
            rows = cur.fetchall()
        out = []
        for r in rows:
            item = dict(zip(_COLS, r[:-1]))
            if isinstance(item.get("evidence"), str):
                try:
                    item["evidence"] = json.loads(item["evidence"])
                except Exception:
                    pass
            item["created_at"] = _iso(r[-1]) if isinstance(r[-1], datetime) else r[-1]
            out.append(item)
        return out

    def from_file() -> List[Dict[str, Any]]:
        return [r for r in _read_ledger_file()
                if r.get("status") == "EXIT_PENDING"]

    return _with_db(from_db, from_file)


def get_open_positions_view() -> List[Dict[str, Any]]:
    """Open Phase 20 paper positions joined with live paper-portfolio prices."""
    open_trades = get_open_trades()
    try:
        from paper_trader import get_portfolio
        prices = {str(p["symbol"]).upper(): float(p["current_price"])
                  for p in get_portfolio()["positions"]}
    except Exception:
        prices = {}
    now = _now()
    out = []
    for t in open_trades:
        sym = str(t.get("symbol") or "").upper()
        cur = prices.get(sym) or float(t.get("fill_price") or 0)
        qty = int(t.get("quantity") or 0)
        fill = float(t.get("fill_price") or 0)
        # Compute holding duration with a fallback timestamp chain so
        # missing/malformed fill_ts never silently returns None.
        # Priority: fill_ts → signal_ts → snapshot_ts → created_at.
        # The result is clamped to ≥ 0 to absorb small clock-skew bugs.
        holding_days: Optional[float] = None
        _age_ts_source: Optional[str] = None
        for _ts_key in ("fill_ts", "signal_ts", "snapshot_ts", "created_at"):
            _raw = t.get(_ts_key)
            if not _raw:
                continue
            try:
                _ft = datetime.fromisoformat(str(_raw).replace("Z", "+00:00"))
                if _ft.tzinfo is None:
                    _ft = _ft.replace(tzinfo=timezone.utc)
                holding_days = round(max(0.0, (now - _ft).total_seconds() / 86400), 2)
                _age_ts_source = _ts_key
                break
            except Exception:
                continue
        out.append({
            **t,
            "current_price": cur,
            "unrealized_pnl": round((cur - fill) * qty, 2),
            "holding_days": holding_days,
            # Indicates which timestamp was used when fill_ts was absent/malformed.
            # "fill_ts" means the primary field was used (normal case).
            # None means no usable timestamp was found in the ledger row.
            "age_ts_source": _age_ts_source,
        })
    return out


# ── Fill models ───────────────────────────────────────────────────────────────

def compute_fill(entry_price: float, settings: Dict[str, Any],
                 side: str = "BUY") -> Dict[str, float]:
    """
    Deterministic paper fill from the stored eligible quote — never uses
    future data. Slippage always moves AGAINST the trade.
    """
    model = settings.get("fill_model", "SLIPPAGE_ADJUSTED")
    slip_pct = float(settings.get("slippage_pct", 0.15)) / 100.0
    direction = 1.0 if side == "BUY" else -1.0
    if model == "LAST_TRADED_PRICE":
        slip = 0.0
    elif model == "NEXT_QUOTE":
        slip = entry_price * slip_pct * 0.5 * direction
    else:  # SLIPPAGE_ADJUSTED
        slip = entry_price * slip_pct * direction
    fill_price = round(entry_price + slip, 2)
    return {"fill_price": fill_price, "slippage": round(abs(slip), 4)}


def compute_charges(turnover: float, settings: Dict[str, Any]) -> float:
    return round(turnover * float(settings.get("charges_pct", 0.12)) / 100.0, 2)


# ── Entry creation ───────────────────────────────────────────────────────────

def _build_row(trade_id: str, scan_id: Optional[str], snapshot_ts: Optional[str],
               sym: str, candidate: Dict[str, Any], sizing: Dict[str, Any],
               signal_price: float, fill: Dict[str, Any], fill_price: float,
               qty: int, charges: float, model_version: str,
               settings: Dict[str, Any], trigger_source: str,
               now_iso: str,
               # Kite LTP overlay provenance — must be passed explicitly by
               # create_paper_entry because they are its local variables, not
               # module-level globals.  Defaults make old call sites safe.
               kite_ltp_overlay_active: bool = False,
               signal_price_from_daily: Optional[float] = None,
               kite_ltp_used: Optional[float] = None) -> Dict[str, Any]:
    return {
        "trade_id": trade_id,
        "scan_id": scan_id,
        "snapshot_ts": snapshot_ts,
        "symbol": sym,
        "sector": candidate.get("sector"),
        "strategy_id": candidate.get("strategy_id"),
        "strategy_name": candidate.get("strategy_name"),
        "side": "BUY",
        "signal_ts": snapshot_ts,
        "decision_ts": now_iso,
        "simulated_order_ts": now_iso,
        "fill_ts": now_iso,
        "signal_price": signal_price,
        "fill_price": fill_price,
        "quantity": qty,
        "stop_loss": float(sizing.get("stop_loss") or 0),
        "target": float(sizing.get("target_price") or 0),
        "risk_amount": float(sizing.get("risk_amount") or 0),
        "est_charges": charges,
        "slippage": fill["slippage"],
        "fill_model": settings.get("fill_model"),
        "confidence": float(candidate.get("confidence") or 0),
        "opportunity_score": float(candidate.get("opportunity_score") or 0),
        "trade_quality_score": float(candidate.get("trade_quality_score") or 0),
        "regime": candidate.get("regime"),
        "model_version": model_version,
        "rule_version": RULE_VERSION,
        "config_hash": settings.get("config_hash"),
        "trigger_source": trigger_source,
        "status": "OPEN",
        "exit_ts": None, "exit_price": None, "exit_rule": None,
        "exit_scan_id": None, "realized_pnl": None,
        "evidence": {
            "gates": candidate.get("gates"),
            "failed_gates": candidate.get("failed_gates"),
            "sizing": sizing,
            "recommendation": candidate.get("recommendation"),
            "expected_holding_days": candidate.get("expected_holding_days"),
            # ── Task 3: Kite LTP overlay provenance ──────────────────────────
            "kite_ltp_overlay_enabled": kite_ltp_overlay_active,
            "indicator_source": candidate.get("indicator_source", "yfinance_daily_bars"),
            "ohlcv_source": candidate.get("ohlcv_source", "yfinance_daily_bars"),
            "signal_price_from_daily_bar": (
                signal_price_from_daily if signal_price_from_daily is not None
                else signal_price),
            "execution_price_from_kite_ltp": kite_ltp_used,
            "execution_price_source": candidate.get("execution_price_source", "yfinance_daily_bars"),
            "kite_ltp_timestamp": candidate.get("latest_price_time_ist"),
            "quote_reliable": candidate.get("quote_reliable", False),
        },
        "recomputed": False,
    }


def create_paper_entry(candidate: Dict[str, Any], settings: Dict[str, Any],
                       scan_id: Optional[str], snapshot_ts: Optional[str],
                       trigger_source: str = "AUTO") -> Dict[str, Any]:
    """Create one simulated order + position for an ELIGIBLE candidate."""
    if not candidate.get("eligible"):
        return {"created": False, "symbol": candidate.get("symbol"),
                "reason": f"Gates failed: {candidate.get('failed_gates')}"}

    sym = str(candidate["symbol"]).upper()
    sizing = candidate.get("sizing") or {}
    qty = int(sizing.get("quantity") or 0)
    signal_price = float(sizing.get("entry_price") or 0)   # yfinance daily close

    # ── Task 3: Kite LTP overlay — use live LTP as execution price ────────────
    # When KITE_LTP_OVERLAY_ENABLED=true and Kite LTP is available in the
    # candidate (set by the scan engine overlay loop), use it as the fill
    # base price. The daily-bar signal_price is still recorded separately
    # in evidence so the trade record is fully auditable.
    _signal_price_from_daily = signal_price   # always record the daily-bar price
    _kite_ltp_used: Optional[float] = None
    _kite_ltp_overlay_active = False
    try:
        from kite_ltp_overlay import is_overlay_enabled
        if (is_overlay_enabled()
                and candidate.get("kite_ltp_available")
                and candidate.get("execution_price_source") == "kite_live_ltp"):
            _kite_ltp = float(candidate.get("kite_ltp") or 0)
            if _kite_ltp > 0:
                signal_price = _kite_ltp
                _kite_ltp_used = _kite_ltp
                _kite_ltp_overlay_active = True
    except Exception:
        pass  # silently fall back to daily-bar price

    if qty < 1 or signal_price <= 0:
        return {"created": False, "symbol": sym, "reason": "Invalid sizing"}

    # Duplicate safety net (gates already check this).
    from paper_trader import get_portfolio, execute_buy
    if any(str(p["symbol"]).upper() == sym for p in get_portfolio()["positions"]):
        return {"created": False, "symbol": sym, "reason": "Open position exists"}

    fill = compute_fill(signal_price, settings, side="BUY")
    fill_price = fill["fill_price"]
    charges = compute_charges(fill_price * qty, settings)

    # ── Risk Agent pre-trade validation ──────────────────────────────────────
    # Every paper BUY order passes through the pre-trade risk gate before any
    # ledger claim or portfolio debit occurs. REJECTED trades are blocked here;
    # APPROVED_WARN trades proceed but warnings are embedded in evidence.
    # The validator never raises: errors degrade to APPROVED_WARN so a bug in
    # validation cannot silently drop legitimate trades.
    _rv_result: Dict[str, Any] = {}
    try:
        from risk_validation.pre_trade import validate_pre_trade
        rv = validate_pre_trade(
            symbol=sym,
            fill_price=fill_price,
            qty=qty,
            stop_loss=float(sizing.get("stop_loss") or 0),
            target=float(sizing.get("target_price") or 0),
            risk_amount=float(sizing.get("risk_amount") or 0),
            settings=settings,
            candidate=candidate,
        )
        _rv_result = rv.to_dict()
        if rv.verdict == "REJECTED":
            # Phase 1C: structured rejection payload — gate_name, actual_value,
            # required_value, action, human_readable_reason all included.
            _first_crit = next(
                (i for i in rv.issues if i.severity == "CRITICAL"), None)
            try:
                from pipeline_events import emit as _pe
                _pe("ORDER_REJECTED", "EXECUTION", scan_id=scan_id, symbol=sym,
                    payload={
                        "reason":               rv.reason,
                        "verdict":              "REJECTED",
                        "stage_detail":         "risk_agent_pre_trade",
                        "qty":                  qty,
                        "fill_price":           fill_price,
                        "gate_name":            _first_crit.check if _first_crit else None,
                        "actual_value":         _first_crit.value if _first_crit else None,
                        "required_value":       rv.summary.get("required_value"),
                        "action":               "BUY",
                        "human_readable_reason": rv.reason,
                    })
            except Exception:
                pass
            store.add_notification(
                "ENTRY_BLOCKED_RISK",
                f"Risk Agent REJECTED {sym} paper BUY",
                rv.reason,
                severity="WARN",
                context={"symbol": sym, "scan_id": scan_id,
                         "risk_validation": _rv_result},
            )
            return {"created": False, "symbol": sym,
                    "reason": f"Risk Agent: {rv.reason}",
                    "risk_validation": _rv_result}
        if rv.verdict == "APPROVED_WARN" and rv.issues:
            warnings_txt = " | ".join(
                i.message for i in rv.issues if i.severity == "WARNING")
            store.add_notification(
                "RISK_WARN",
                f"Risk Agent warnings for {sym}",
                warnings_txt,
                severity="INFO",
                context={"symbol": sym, "scan_id": scan_id},
            )
    except Exception as rv_exc:
        _rv_result = {"verdict": "APPROVED_WARN", "approved": True,
                      "error": str(rv_exc)[:200]}

    # ── Phase 1B: adopt capped quantity when SIZE_REDUCED_TO_CAP ─────────────
    # If the risk validator found the ideal qty exceeds the per-stock cap but
    # a smaller quantity fits, use that smaller quantity instead of rejecting.
    # This fixes the position-size cap rejection bug for DRREDDY, GRASIM,
    # BAJAJ-AUTO, BAJAJFINSV, TMPV and other higher-priced NIFTY constituents.
    #
    # BUG FIX (Task 1): size_reduced_to_cap and capped_qty live inside
    # rv.to_dict()["summary"], NOT at the top level of rv.to_dict().
    # Previous code checked _rv_result.get("size_reduced_to_cap") which always
    # evaluated to None because that key is nested one level deeper.
    _rv_summary = _rv_result.get("summary", {}) if isinstance(_rv_result, dict) else {}
    if (_rv_summary.get("size_reduced_to_cap")
            and int(_rv_summary.get("capped_qty") or 0) >= 1):
        _old_qty = qty
        _old_risk = float(sizing.get("risk_amount") or 0)
        qty = int(_rv_summary["capped_qty"])
        # Recompute charges (turnover-based) with new qty.
        charges = compute_charges(fill_price * qty, settings)
        # Recompute risk_amount proportionally: risk scales linearly with qty.
        _new_risk = round(_old_risk * qty / _old_qty, 2) if _old_qty > 0 else _old_risk
        # Update sizing reference so downstream evidence records the reduced qty.
        sizing = dict(sizing)
        sizing["quantity"] = qty
        sizing["risk_amount"] = _new_risk
        # Record original vs capped in the rv_result for evidence audit trail.
        _rv_result = dict(_rv_result)
        _rv_result["original_qty"] = _old_qty
        _rv_result["capped_qty"] = qty
        _rv_result["original_risk_amount"] = _old_risk
        _rv_result["capped_risk_amount"] = _new_risk
        # Emit a structured SIZE_REDUCED_TO_CAP pipeline event so the audit log
        # always shows the resize happened (not silently absorbed).
        try:
            from pipeline_events import emit as _pe2
            _pe2("SIZE_REDUCED_TO_CAP", "EXECUTION",
                 scan_id=scan_id, symbol=sym,
                 payload={
                     "original_qty":    _old_qty,
                     "capped_qty":      qty,
                     "fill_price":      fill_price,
                     "original_risk":   _old_risk,
                     "capped_risk":     _new_risk,
                     "trade_value_orig": round(fill_price * _old_qty, 2),
                     "trade_value_cap": round(fill_price * qty, 2),
                     "charges_recalculated": charges,
                     "note": "SIZE_REDUCED_TO_CAP: adopting capped qty from risk validator summary",
                 })
        except Exception:
            pass

    try:
        from model_versioning import get_active_version
        model_version = str(get_active_version().get("version", 0))
    except Exception:
        model_version = "0"

    now_iso = _iso()
    trade_id = f"P20-{uuid.uuid4().hex[:10]}"

    # Claim the (symbol, OPEN) slot in the ledger BEFORE executing the buy.
    # The partial unique index (one OPEN trade per symbol) makes this atomic
    # at the database level, so concurrent ticks cannot double-enter.
    row = _build_row(trade_id, scan_id, snapshot_ts, sym, candidate, sizing,
                     signal_price, fill, fill_price, qty, charges,
                     model_version, settings, trigger_source, now_iso,
                     kite_ltp_overlay_active=_kite_ltp_overlay_active,
                     signal_price_from_daily=_signal_price_from_daily,
                     kite_ltp_used=_kite_ltp_used)
    # Embed the risk-agent validation result in the immutable evidence record.
    if _rv_result:
        row.setdefault("evidence", {})["risk_validation"] = _rv_result

    try:
        from pipeline_events import emit as _pe
    except Exception:
        _pe = lambda *a, **k: None  # type: ignore
    _pe("ORDER_SUBMITTED", "EXECUTION", scan_id=scan_id, symbol=sym,
        payload={"trade_id": trade_id, "qty": qty, "signal_price": signal_price,
                 "fill_price": fill_price, "charges": charges,
                 "trigger_source": trigger_source})

    try:
        _insert_row(row)
    except DuplicateOpenTrade:
        _pe("ORDER_CANCELLED", "EXECUTION", scan_id=scan_id, symbol=sym,
            payload={"trade_id": trade_id,
                     "reason": "Open Phase 20 trade already exists (concurrent claim)"})
        return {"created": False, "symbol": sym,
                "reason": "Open Phase 20 trade already exists (concurrent claim)"}

    ok, msg = execute_buy(
        sym, qty, fill_price,
        ledger_trade_id=trade_id,
        scan_id=scan_id,
        reason=f"Phase 20 {trigger_source} paper entry (trade {trade_id})",
        signal_confidence=float(candidate.get("confidence") or 0),
        regime=str(candidate.get("regime") or "UNKNOWN"),
        ai_decision=str(candidate.get("recommendation") or ""),
        rr_ratio=float(sizing.get("rr_ratio") or 0),
        target=float(sizing.get("target_price") or 0),
        stop_loss_price=float(sizing.get("stop_loss") or 0),
        plain_english=f"Automated Phase 20 paper entry ({trigger_source})",
        strategy_id=str(candidate.get("strategy_id") or ""),
        strategy_name=str(candidate.get("strategy_name") or ""),
        opportunity_score=float(candidate.get("opportunity_score") or 0),
        trade_quality=float(candidate.get("trade_quality_score") or 0),
    )
    if not ok:
        _pe("ORDER_REJECTED", "EXECUTION", scan_id=scan_id, symbol=sym,
            payload={"trade_id": trade_id, "reason": msg,
                     "stage_detail": "execute_buy"})
        store.add_notification("ENTRY_BLOCKED", f"{sym} paper entry blocked",
                               msg, severity="WARN",
                               context={"symbol": sym, "scan_id": scan_id})
        # Release the claimed ledger slot since no position was created.
        _delete_row(trade_id)
        return {"created": False, "symbol": sym, "reason": msg}

    _pe("ORDER_EXECUTED", "EXECUTION", scan_id=scan_id, symbol=sym,
        payload={"trade_id": trade_id, "qty": qty, "fill_price": fill_price,
                 "slippage": fill.get("slippage"), "charges": charges})
    _pe("POSITION_OPENED", "PORTFOLIO", scan_id=scan_id, symbol=sym,
        payload={"trade_id": trade_id, "qty": qty, "fill_price": fill_price,
                 "stop_loss": float(sizing.get("stop_loss") or 0),
                 "target": float(sizing.get("target_price") or 0)})
    try:
        from canonical_portfolio import build_canonical_portfolio
        _cp = build_canonical_portfolio()
        _pe("PORTFOLIO_UPDATED", "PORTFOLIO", scan_id=scan_id, payload={
            "cash": _cp.get("cash"), "equity": _cp.get("equity"),
            "open_positions": len(_cp.get("positions") or []),
            "realized_pnl": _cp.get("realized_pnl"),
            "unrealized_pnl": _cp.get("unrealized_pnl"),
            "trigger": f"POSITION_OPENED {sym}"})
    except Exception:
        pass

    store.add_notification(
        "ENTRY_CREATED", f"Paper BUY {sym} × {qty} @ ₹{fill_price}",
        f"Trade {trade_id} from scan {scan_id} "
        f"(model {settings.get('fill_model')}, slippage ₹{fill['slippage']}, "
        f"charges ₹{charges}). Simulated only — no real order.",
        severity="INFO",
        context={"trade_id": trade_id, "symbol": sym, "scan_id": scan_id})
    return {"created": True, "trade_id": trade_id, "symbol": sym,
            "quantity": qty, "fill_price": fill_price}


def run_auto_entries(settings: Dict[str, Any]) -> Dict[str, Any]:
    """
    Automatic paper entries — ONLY callable when auto_paper_entries is ON and
    confirmed (enforced again here as defence in depth).
    """
    if not (settings.get("auto_paper_entries")
            and settings.get("auto_paper_entries_confirmed_at")):
        return {"ran": False, "reason": "auto_paper_entries OFF (default)"}

    # Circuit breaker: evaluate trip conditions FIRST (defence in depth — the
    # entry gates also carry an entry_circuit_breaker gate). While tripped,
    # no new paper entries may be created until manual review.
    from phase20_circuit_breaker import evaluate_and_maybe_trip
    cb_state = evaluate_and_maybe_trip(settings)
    if cb_state.get("tripped"):
        return {"ran": False,
                "reason": "Circuit breaker tripped — paper entries paused "
                          "pending manual review",
                "circuit_breaker": cb_state}

    from phase20_gates import evaluate_entries
    evaluation = evaluate_entries()
    created: List[Dict[str, Any]] = []
    blocked: List[Dict[str, Any]] = []
    _scan_id = evaluation.get("scan_id")
    _snap_ts = evaluation.get("snapshot_ts")
    for cand in evaluation.get("candidates", []):
        if not cand.get("eligible"):
            # Build a human-readable reason map from the full gate objects so
            # the outcome event carries actionable detail (not just gate names).
            _reasons: Dict[str, str] = {
                g["gate"]: str(g.get("reason") or "")
                for g in (cand.get("gates") or [])
                if not g.get("passed")
            }
            blocked.append({
                "symbol": cand["symbol"],
                "failed_gates": cand["failed_gates"],
                "failed_gate_reasons": _reasons,
            })
            # Emit a mandatory per-candidate outcome event so no BUY signal
            # disappears silently.  Before this fix, ineligible candidates were
            # appended to a blocked list and silently skipped — no pipeline
            # event, no per-symbol notification, no DB row.
            try:
                from pipeline_events import emit as _pe
                # Phase 1C: structured reason payload so every skip is auditable.
                _first_gate = (cand["failed_gates"][0]
                               if cand.get("failed_gates") else None)
                _human_reason = (
                    " | ".join(f"{k}: {v}" for k, v in _reasons.items())
                    if _reasons
                    else ("Failed gates: " + ", ".join(cand.get("failed_gates", [])))
                )
                _pe("EXECUTION_SKIPPED_WITH_REASON", "EXECUTION",
                    scan_id=_scan_id, symbol=cand["symbol"],
                    payload={
                        "failed_gates":           cand["failed_gates"],
                        "failed_gate_reasons":    _reasons,
                        "gate_name":              _first_gate,
                        "action":                 cand.get("recommendation"),
                        "human_readable_reason":  _human_reason,
                        "reason":                 _human_reason,
                        "opportunity_score":      cand.get("opportunity_score"),
                        "confidence":             cand.get("confidence"),
                        "auto_entry_attempted":   False,
                        "note": (
                            "Candidate failed entry-gate evaluation; "
                            "executor skipped without attempting order"
                        ),
                    })
            except Exception:
                pass
            continue
        res = create_paper_entry(cand, settings,
                                 _scan_id, _snap_ts,
                                 trigger_source="AUTO")
        created.append(res)
        # Re-check the daily limit after each creation.
        if len([c for c in created if c.get("created")]) \
                >= int(settings.get("max_trades_per_day", 3)):
            break
    if blocked:
        store.add_notification(
            "ENTRY_BLOCKED", f"{len(blocked)} paper entr(y/ies) blocked",
            "; ".join(f"{b['symbol']}: {', '.join(b['failed_gates'][:3])}"
                      for b in blocked[:5]),
            severity="INFO",
            context={"scan_id": _scan_id, "blocked": blocked})
    result = {"ran": True, "scan_id": _scan_id,
              "created": created, "blocked": blocked,
              "evaluation": evaluation}
    # Persist last run outcome so the pipeline stats UI can display
    # auto-entry attempted / final outcome per candidate without re-running.
    try:
        store.kv_set("last_auto_entries_result", {
            "ran_at":         _iso(),
            "scan_id":        _scan_id,
            "snapshot_ts":    _snap_ts,
            "created_count":  sum(1 for c in created if c.get("created")),
            "blocked_count":  len(blocked),
            "blocked": [
                {"symbol": b["symbol"], "failed_gates": b["failed_gates"],
                 "failed_gate_reasons": b.get("failed_gate_reasons", {})}
                for b in blocked
            ],
            "created": [
                {"symbol": c.get("symbol"), "trade_id": c.get("trade_id")}
                for c in created if c.get("created")
            ],
        })
    except Exception:
        pass
    return result


# ── Bootstrap paper entry (parallel track — never touches normal BUY logic) ──

# Thresholds mirror live_scan_engine.BOOTSTRAP_MIN_* constants.
_BOOTSTRAP_MAX_CLOSED_TRADES  = 20     # stop once the ledger has enough evidence
_BOOTSTRAP_MAX_ORDER_VALUE    = 1_500  # ₹ hard ceiling per bootstrap trade
_BOOTSTRAP_MIN_CONF           = 60.0
_BOOTSTRAP_MIN_OPP            = 50.0
_BOOTSTRAP_MIN_RR             = 1.5


def run_bootstrap_auto_entry(snapshot: Dict[str, Any],
                              settings: Dict[str, Any],
                              circuit_breaker_tripped: bool = False) -> Dict[str, Any]:
    """
    Create at most ONE small bootstrap paper trade per scan when:

    * The production paper ledger has fewer than _BOOTSTRAP_MAX_CLOSED_TRADES
      closed trades (ledger seeding purpose only — auto-disables when the
      system has enough history for normal evidence-driven BUY signals).
    * ``bootstrap_paper_enabled`` is True in phase20_settings (defaults False —
      operators must explicitly enable it).
    * ``auto_paper_entries`` is True AND ``auto_paper_entries_confirmed_at`` is
      set (same explicit-confirmation invariant as normal auto entries).
    * At least one WATCH recommendation has ``bootstrap_eligible=True``
      (set post-overlay by live_scan_engine when Kite LTP is live, all hard
      gates pass, confidence ≥ 60, and low_evidence blocks the normal path).

    Strictly parallel track:
    * NEVER modifies BUY_CONF, WATCH_CONF, paper_eligible, or any confidence.
    * NEVER calls live broker order APIs (paper_trader.execute_buy only).
    * Position size capped at ₹1,500; one trade per scan; normal exit engine.
    * Records trigger_source="BOOTSTRAP_AUTO", fill_model="bootstrap_paper".
    * Emits BOOTSTRAP_PAPER_TRADE_APPROVED pipeline event for full auditability.

    Evidence note: low_evidence is based on 6-month backtest trade count, NOT
    paper trades. Bootstrap paper trades do NOT reduce low_evidence — that clears
    naturally as the strategy walk-forward window accumulates ≥5 signals.
    """
    # ── Feature flag (safe-off default) ──────────────────────────────────────
    # bootstrap_paper_enabled defaults False in DEFAULT_SETTINGS; operators must
    # explicitly opt in via the settings API.
    if not settings.get("bootstrap_paper_enabled", False):
        return {"ran": False, "reason": "bootstrap_paper_enabled is off in settings"}

    # ── Operator confirmation guard (defense-in-depth) ────────────────────────
    # Mirror the exact same check as run_auto_entries / the scheduler gate so
    # direct/internal callers cannot bypass the Phase 20 explicit-confirmation
    # invariant. Bootstrap creates canonical paper positions — it must require
    # the same operator opt-in as any other automated entry path.
    if not (settings.get("auto_paper_entries") and
            settings.get("auto_paper_entries_confirmed_at")):
        return {"ran": False,
                "reason": "auto_paper_entries not confirmed — bootstrap requires the same "
                           "explicit operator confirmation as normal auto entries "
                           "(set auto_paper_entries=True with confirmation text)"}

    # Circuit breaker — fail-closed. Bootstrap must never open a position while
    # entries are paused for manual review. An unreadable/errored breaker state
    # is treated as tripped (circuit_breaker_tripped=True when state is unknown).
    if circuit_breaker_tripped:
        return {"ran": False,
                "reason": "Circuit breaker tripped — all entries paused including bootstrap"}

    # Kite LTP must be live at the snapshot level (safety double-check)
    safety = snapshot.get("safety") or {}
    if not (safety.get("kite_ltp_session_verified") or
            safety.get("kite_ltp_overlay_enabled")):
        return {"ran": False,
                "reason": "Kite LTP not verified in snapshot — bootstrap requires live quotes"}

    # Count closed production trades (bootstrap auto-disables above threshold)
    def _closed_count(conn) -> int:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FROM phase20_paper_trades WHERE status='CLOSED'"
            )
            return int(cur.fetchone()[0])

    closed = _with_db(_closed_count, lambda: 0)
    if closed >= _BOOTSTRAP_MAX_CLOSED_TRADES:
        return {"ran": False,
                "reason": f"Bootstrap complete — {closed} closed trades in ledger "
                           f"(threshold {_BOOTSTRAP_MAX_CLOSED_TRADES})"}

    # ── Per-scan atomic claim (one bootstrap trade per scan_id) ─────────────
    # kv_claim_once is an atomic first-claimant guard: the first caller wins and
    # subsequent callers (concurrent ticks, repeated ticks on the same stale
    # snapshot) see False and skip.  This prevents both concurrent races and
    # repeated execution against the same snapshot scan_id.
    scan_id_for_guard = snapshot.get("scan_id") or ""
    if scan_id_for_guard:
        try:
            import phase20_store as _bs_store
            _claim_key = f"bootstrap_scan:{scan_id_for_guard}"
            if not _bs_store.kv_claim_once(_claim_key):
                return {"ran": False,
                        "reason": f"Bootstrap already processed for scan {scan_id_for_guard} "
                                   "(kv_claim_once guard — concurrent/repeated tick blocked)"}
        except Exception as _ce:
            # kv unavailable — fail-closed: don't attempt to create a trade
            return {"ran": False,
                    "reason": f"Per-scan claim guard unavailable: {_ce!s:.100} — "
                               "skipping bootstrap to avoid duplicate trades"}
    else:
        # No scan_id in snapshot — cannot guarantee idempotency; skip.
        return {"ran": False, "reason": "Snapshot has no scan_id — bootstrap skipped for safety"}

    # Guard: don't create a bootstrap trade if a bootstrap trade is already OPEN.
    def _bootstrap_open(conn) -> bool:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM phase20_paper_trades "
                "WHERE status='OPEN' AND trigger_source='BOOTSTRAP_AUTO' LIMIT 1"
            )
            return cur.fetchone() is not None

    if _with_db(_bootstrap_open, lambda: False):
        return {"ran": False, "reason": "Bootstrap trade already OPEN — waiting for exit"}

    # Pick highest-confidence bootstrap_eligible candidate
    recs = snapshot.get("recommendations") or []
    candidates = [
        r for r in recs
        if r.get("bootstrap_eligible")
        and r.get("final_action") == "WATCH"
        and (r.get("calibrated_confidence") or 0) >= _BOOTSTRAP_MIN_CONF
        and (r.get("opportunity_score") or 0) >= _BOOTSTRAP_MIN_OPP
        and (r.get("rr_ratio") or 0) >= _BOOTSTRAP_MIN_RR
        and r.get("quote_reliable")
        and r.get("kite_session_verified_flag")
    ]
    if not candidates:
        return {"ran": False, "reason": "No bootstrap_eligible WATCH candidates in snapshot"}

    # Rank candidates: highest calibrated_confidence first, then opportunity_score
    ranked = sorted(
        candidates,
        key=lambda r: (
            float(r.get("calibrated_confidence") or 0),
            float(r.get("opportunity_score") or 0),
        ),
        reverse=True,
    )

    scan_id = snapshot.get("scan_id")
    snap_ts = snapshot.get("snapshot_ts")

    # Override fill_model to "bootstrap_paper" for clear ledger labelling.
    bootstrap_settings = dict(settings)
    bootstrap_settings["fill_model"] = "bootstrap_paper"

    slip_pct = float(settings.get("slippage_pct", 0.15)) / 100.0

    # Track every skip so the final return is auditable even if all fail.
    skipped: List[Dict[str, Any]] = []

    from paper_trader import get_portfolio  # single import for the loop

    for best in ranked:
        sym = str(best.get("symbol", "")).upper()

        # ── Independent gate re-verification ─────────────────────────────────
        # Defensive re-check on each candidate.  bootstrap_eligible is a
        # pre-computed flag that may reflect a stale scan or be overridden by a
        # caller in tests.  We verify each constituent condition independently.
        # Failures here skip to the next candidate rather than aborting the run.
        if not best.get("low_evidence"):
            skipped.append({"symbol": sym,
                             "reason": "low_evidence=False — normal BUY path unblocked"})
            continue
        if not best.get("all_gates_passed"):
            skipped.append({"symbol": sym,
                             "reason": "all_gates_passed=False — hard risk gate failure"})
            continue
        if not best.get("kite_ltp_available"):
            skipped.append({"symbol": sym,
                             "reason": "kite_ltp_available=False — live LTP required"})
            continue
        _exec_src = str(best.get("execution_price_source") or "")
        if "kite" not in _exec_src.lower():
            skipped.append({"symbol": sym,
                             "reason": f"execution_price_source '{_exec_src}' is not Kite"})
            continue

        price = float(best.get("kite_ltp") or 0)
        if price <= 0:
            skipped.append({"symbol": sym, "reason": "Invalid kite_ltp price (≤ 0)"})
            continue

        # Compute qty bounded by ₹1,500 ceiling against worst-case slippage fill.
        worst_fill = round(price * (1.0 + slip_pct), 2)
        if worst_fill > _BOOTSTRAP_MAX_ORDER_VALUE:
            skipped.append({"symbol": sym,
                             "reason": (f"Worst-case fill ₹{worst_fill:.2f} exceeds "
                                        f"₹{_BOOTSTRAP_MAX_ORDER_VALUE} cap — even 1 share")})
            continue
        qty = max(1, int(_BOOTSTRAP_MAX_ORDER_VALUE // worst_fill))
        while qty > 1 and qty * worst_fill > _BOOTSTRAP_MAX_ORDER_VALUE:
            qty -= 1
        order_value = round(qty * worst_fill, 2)

        # Gate: target_price must be populated and positive.
        # When target_price is null or 0 the downstream validate_pre_trade()
        # call computes RR = 0 and emits a generic STOP_LOSS_MISSING CRITICAL
        # rejection.  That rejection is hard to diagnose because the gate name
        # doesn't tell the operator WHY target is absent (it was null in the
        # scan snapshot).  We surface it here as TARGET_MISSING so the
        # pipeline-events log is unambiguous and the operator knows to check
        # live_scan_engine's strategy.compute_target() for the symbol.
        _target_price_raw = best.get("target_price")
        _target_price_val = float(_target_price_raw) if _target_price_raw is not None else 0.0
        if _target_price_val <= 0:
            _reason_no_target = (
                f"{sym}: target_price is {'null' if _target_price_raw is None else 0} "
                f"in the scan snapshot — R:R check would compute RR=0 and reject; "
                f"check strategy.compute_target() in live_scan_engine.py"
            )
            skipped.append({"symbol": sym, "reason": _reason_no_target})
            try:
                from pipeline_events import emit as _pe
                _pe("BOOTSTRAP_CANDIDATE_REJECTED", "EXECUTION",
                    scan_id=scan_id, symbol=sym,
                    payload={
                        "symbol":       sym,
                        "reason":       _reason_no_target,
                        "gate":         "TARGET_MISSING",
                        "target_price": _target_price_raw,
                        "stop_loss":    float(best.get("stop_loss") or 0),
                        "rr_ratio":     float(best.get("rr_ratio") or 0),
                        "note": (
                            "target_price was null or 0 in the scan snapshot. "
                            "The pre-trade R:R check would have silently produced "
                            "RR=0 and rejected with STOP_LOSS_MISSING. "
                            "Explicit TARGET_MISSING gate raised here so the "
                            "rejection is auditable without reading risk_validation."
                        ),
                    })
            except Exception:
                pass
            continue

        # Duplicate position guard — skip this symbol if already held.
        if any(str(p["symbol"]).upper() == sym for p in get_portfolio()["positions"]):
            skipped.append({"symbol": sym, "reason": "Open position already exists"})
            continue

        # Build a minimal candidate dict compatible with create_paper_entry
        sizing = {
            "quantity":    qty,
            "entry_price": price,
            "stop_loss":   float(best.get("stop_loss") or 0),
            "target_price": float(best.get("target_price") or 0),
            "rr_ratio":    float(best.get("rr_ratio") or 0),
            "order_value": order_value,
        }
        candidate: Dict[str, Any] = {
            "eligible":               True,
            "symbol":                 sym,
            "recommendation":         "WATCH",
            "confidence":             float(best.get("calibrated_confidence") or 0),
            "opportunity_score":      float(best.get("opportunity_score") or 0),
            "trade_quality_score":    float(best.get("technical_score") or 0),
            "regime":                 str(best.get("regime") or "UNKNOWN"),
            "strategy_id":            str(best.get("strategy_id") or ""),
            "strategy_name":          str(best.get("strategy_name") or ""),
            "kite_ltp_available":       bool(best.get("kite_ltp_available")),
            "execution_price_source":   str(best.get("execution_price_source") or ""),
            "kite_ltp":                 float(best.get("kite_ltp") or 0),
            "sizing":                   sizing,
            "failed_gates":             [],
        }

        # Emit approval event BEFORE creation for atomicity audit trail
        try:
            from pipeline_events import emit as _pe
            _pe("BOOTSTRAP_PAPER_TRADE_APPROVED", "EXECUTION",
                scan_id=scan_id, symbol=sym,
                payload={
                    "symbol":                sym,
                    "calibrated_confidence": best.get("calibrated_confidence"),
                    "opportunity_score":     best.get("opportunity_score"),
                    "rr_ratio":              best.get("rr_ratio"),
                    "kite_ltp":              best.get("kite_ltp"),
                    "order_value":           order_value,
                    "qty":                   qty,
                    "closed_trades_so_far":  closed,
                    "rank_in_candidates":    ranked.index(best) + 1,
                    "candidates_total":      len(ranked),
                    "reason": (
                        "Bootstrap paper trade: low_evidence (backtest < 5 trades) "
                        "blocked normal BUY path. Kite LTP live, all hard gates "
                        "passed. Max order value ₹1,500. No live broker API called. "
                        "Exit handled by normal phase20 exit engine."
                    ),
                })
        except Exception:
            pass

        try:
            result = create_paper_entry(candidate, bootstrap_settings,
                                        scan_id, snap_ts,
                                        trigger_source="BOOTSTRAP_AUTO")
        except Exception as _cpe:
            # create_paper_entry raised unexpectedly (e.g. Kite API timeout,
            # DB transient error).  Treat as a per-candidate rejection so the
            # loop can continue to the next candidate instead of aborting.
            _exc_reason = f"create_paper_entry raised: {_cpe!s:.120}"
            skipped.append({"symbol": sym, "reason": _exc_reason})
            try:
                from pipeline_events import emit as _pe
                _pe("BOOTSTRAP_CANDIDATE_REJECTED", "EXECUTION",
                    scan_id=scan_id, symbol=sym,
                    payload={
                        "symbol":                   sym,
                        "reason":                   _exc_reason,
                        "gate":                     "CREATE_PAPER_ENTRY_EXCEPTION",
                        "next_candidate_attempted": (ranked.index(best) + 1) < len(ranked),
                        "rank_in_candidates":       ranked.index(best) + 1,
                        "candidates_total":         len(ranked),
                    })
            except Exception:
                pass
            continue

        if result.get("created"):
            store.add_notification(
                "BOOTSTRAP_TRADE_CREATED",
                f"Bootstrap paper BUY {sym} × {qty} @ ₹{price:.2f}",
                (f"Trade {result.get('trade_id')} created to seed the paper ledger. "
                 f"Reason: low_evidence=True (backtest < 5 trades) blocked normal BUY. "
                 f"Kite LTP live, all risk gates passed. Max ₹1,500 position. "
                 f"Paper only — no live order. Exits via normal phase20 exit engine."),
                severity="INFO",
                context={"trade_id": result.get("trade_id"), "symbol": sym,
                         "scan_id": scan_id, "trigger_source": "BOOTSTRAP_AUTO"},
            )
            return {"ran": True, "symbol": sym, "result": result,
                    "closed_trades_before": closed,
                    "candidates_checked": len(ranked),
                    "skipped_before_success": skipped}

        # create_paper_entry rejected (pre-trade risk check, duplicate, etc.).
        # Compute slippage-adjusted R:R for the audit event.
        _stop  = float(best.get("stop_loss") or 0)
        _tgt   = float(best.get("target_price") or 0)
        _rr_after: Optional[float] = None
        if _stop > 0 and _tgt > worst_fill and worst_fill > _stop:
            _rr_after = round((_tgt - worst_fill) / (worst_fill - _stop), 4)

        _skip_entry = {
            "symbol":              sym,
            "reason":              result.get("reason", "create_paper_entry rejected"),
            "rr_before_slippage":  float(best.get("rr_ratio") or 0),
            "rr_after_slippage":   _rr_after,
            "fill_price":          worst_fill,
            "next_candidate_attempted": False,  # updated below if more remain
        }
        skipped.append(_skip_entry)

        _next_idx = ranked.index(best) + 1
        _has_next = _next_idx < len(ranked)
        _skip_entry["next_candidate_attempted"] = _has_next

        try:
            from pipeline_events import emit as _pe
            _pe("BOOTSTRAP_CANDIDATE_REJECTED", "EXECUTION",
                scan_id=scan_id, symbol=sym,
                payload={
                    "symbol":                    sym,
                    "reason":                    result.get("reason", "rejected"),
                    "gate":                      (result.get("risk_validation") or {})
                                                 .get("first_critical_check"),
                    "rr_before_slippage":        float(best.get("rr_ratio") or 0),
                    "rr_after_slippage":         _rr_after,
                    "fill_price":                worst_fill,
                    "next_candidate_attempted":  _has_next,
                    "rank_in_candidates":        _next_idx,
                    "candidates_total":          len(ranked),
                })
        except Exception:
            pass

    # All ranked candidates exhausted without a successful fill.
    try:
        from pipeline_events import emit as _pe
        _pe("BOOTSTRAP_ALL_CANDIDATES_REJECTED", "EXECUTION",
            scan_id=scan_id, symbol=None,
            payload={
                "candidates_checked":  len(ranked),
                "rejection_summary":   [
                    {"symbol": s["symbol"], "reason": s["reason"],
                     "rr_before_slippage": s.get("rr_before_slippage"),
                     "rr_after_slippage": s.get("rr_after_slippage")}
                    for s in skipped
                ],
                "reason": (f"All {len(ranked)} bootstrap candidate(s) exhausted — "
                           "no paper trade created this scan"),
            })
    except Exception:
        pass

    return {"ran": False,
            "reason": (f"All {len(ranked)} bootstrap candidate(s) rejected after "
                       f"pre-trade re-check — no paper trade created"),
            "candidates_checked": len(ranked),
            "skipped": skipped}


# ── Execution-outcome seal ────────────────────────────────────────────────────

# Terminal event types that close out an EXECUTION outcome for a symbol.
# Any of these means the symbol was processed — it did NOT slip through silently.
_EXECUTION_TERMINAL_TYPES: frozenset = frozenset({
    "ORDER_EXECUTED",
    "ORDER_REJECTED",
    "ORDER_CANCELLED",
    "EXECUTION_SKIPPED_WITH_REASON",
})


def seal_execution_outcomes(scan_id: str,
                             reason: str = "auto_paper_entries_off") -> Dict[str, Any]:
    """
    Ensure every BUY_GENERATED event for ``scan_id`` has a corresponding
    terminal EXECUTION-stage outcome event.

    For each symbol with a ``BUY_GENERATED`` event in this scan, if none of
    ORDER_EXECUTED / ORDER_REJECTED / ORDER_CANCELLED /
    EXECUTION_SKIPPED_WITH_REASON exist in the EXECUTION stage, one
    ``EXECUTION_SKIPPED_WITH_REASON`` is emitted so operators can see the
    outcome in the Agent Journey and the orphan-check query returns 0 rows.

    This closes the "last scan of the session" gap: when auto_paper_entries is
    OFF the executor never fires at all, leaving BUY_GENERATED events without
    any terminal outcome.  It also acts as a safety net after each auto-entry
    run in case any symbol slipped through without an event.

    Race-condition window (Autoscale concurrent ticks)
    --------------------------------------------------
    On Autoscale two scheduler ticks can overlap: one running run_auto_entries()
    (which emits ORDER_EXECUTED) and one calling seal_execution_outcomes() at
    nearly the same moment.  Because the seal reads terminal events BEFORE the
    executor has committed its ORDER_EXECUTED row, it may see no terminal event
    for a symbol and emit EXECUTION_SKIPPED_WITH_REASON — leaving both events
    in the table for the same (scan_id, symbol).

    The Agent Journey consumer guards against this at read time: when it selects
    the terminal event it prefers ORDER_EXECUTED over EXECUTION_SKIPPED_WITH_REASON
    by an explicit priority ordering, so the operator always sees the correct
    "PAPER BUY" outcome even when both events coexist.  The seal event is
    treated as a safe fallback that is silently superseded if a real execution
    event arrives later — no data is corrupted.

    NEVER raises. Returns a summary dict.
    """
    if not scan_id:
        return {"sealed": 0, "reason": "no scan_id"}
    try:
        from pipeline_events import query_events, emit as _pe

        # All BUY_GENERATED events for this scan (cap at 200 — ≫ NIFTY 50).
        buys = query_events(scan_id=scan_id, event_type="BUY_GENERATED", limit=200)
        buy_symbols: set = {str(e["symbol"]).upper() for e in buys if e.get("symbol")}

        if not buy_symbols:
            return {"sealed": 0, "scan_id": scan_id, "reason": "no BUY_GENERATED events"}

        # Collect symbols that already have a terminal execution outcome.
        terminal_symbols: set = set()
        for et in _EXECUTION_TERMINAL_TYPES:
            evs = query_events(scan_id=scan_id, event_type=et,
                               stage="EXECUTION", limit=200)
            terminal_symbols.update(
                str(e["symbol"]).upper() for e in evs if e.get("symbol")
            )

        orphans = buy_symbols - terminal_symbols
        for sym in sorted(orphans):
            _pe(
                "EXECUTION_SKIPPED_WITH_REASON", "EXECUTION",
                scan_id=scan_id, symbol=sym,
                payload={
                    "reason": reason,
                    "note": (
                        "Sealed by seal_execution_outcomes: BUY_GENERATED "
                        "event had no terminal execution outcome recorded"
                    ),
                    "auto_entry_attempted": False,
                },
            )
        return {
            "sealed": len(orphans),
            "scan_id": scan_id,
            "orphans": sorted(orphans),
            "reason": reason,
        }
    except Exception as exc:
        return {"sealed": 0, "scan_id": scan_id, "error": str(exc)[:200]}


# ── Exit recording (called by phase20_exits) ─────────────────────────────────

def record_exit(trade_id: str, exit_price: float, exit_rule: str,
                exit_scan_id: Optional[str], status: str = "CLOSED") -> None:
    trade = get_trade(trade_id)
    if not trade:
        return
    qty = int(trade.get("quantity") or 0)
    fill = float(trade.get("fill_price") or 0)
    pnl = round((exit_price - fill) * qty, 2) if status == "CLOSED" else None
    _update_row(trade_id, {
        "status": status,
        "exit_ts": _iso() if status in ("CLOSED", "EXIT_PENDING") else None,
        "exit_price": exit_price if status == "CLOSED" else None,
        "exit_rule": exit_rule,
        "exit_scan_id": exit_scan_id,
        "realized_pnl": pnl,
    })
    # Phase 23: pipeline events (fail-safe)
    try:
        from pipeline_events import emit as _pe
        sym = str(trade.get("symbol") or "")
        if status == "CLOSED":
            _pe("POSITION_CLOSED", "PORTFOLIO", scan_id=exit_scan_id, symbol=sym,
                payload={"trade_id": trade_id, "exit_price": exit_price,
                         "exit_rule": exit_rule, "realized_pnl": pnl})
            _pe("SELL_GENERATED", "EXECUTION", scan_id=exit_scan_id, symbol=sym,
                payload={"trade_id": trade_id, "exit_rule": exit_rule,
                         "exit_price": exit_price})
        else:
            _pe("POSITION_UPDATED", "PORTFOLIO", scan_id=exit_scan_id, symbol=sym,
                payload={"trade_id": trade_id, "status": status,
                         "exit_rule": exit_rule})
        try:
            from canonical_portfolio import build_canonical_portfolio
            _cp = build_canonical_portfolio()
            _pe("PORTFOLIO_UPDATED", "PORTFOLIO", scan_id=exit_scan_id, payload={
                "cash": _cp.get("cash"), "equity": _cp.get("equity"),
                "open_positions": len(_cp.get("positions") or []),
                "realized_pnl": _cp.get("realized_pnl"),
                "unrealized_pnl": _cp.get("unrealized_pnl"),
                "trigger": f"{status} {sym}"})
        except Exception:
            pass
    except Exception:
        pass


# ── Deterministic replay ─────────────────────────────────────────────────────

def replay_trade(trade_id: str) -> Dict[str, Any]:
    """
    Re-derive the entry decision from the STORED evidence and configuration.
    Deterministic: same stored inputs → same decision. The original record is
    never modified; results are labelled RECOMPUTED.
    """
    trade = get_trade(trade_id)
    if not trade:
        return {"found": False, "trade_id": trade_id}

    evidence = trade.get("evidence") or {}
    sizing = (evidence.get("sizing") or {})
    settings_hash = trade.get("config_hash")
    current = store.get_settings()

    # Recompute the fill from stored signal price + stored fill model config.
    recomputed_fill = compute_fill(
        float(trade.get("signal_price") or 0),
        {"fill_model": trade.get("fill_model"),
         "slippage_pct": (float(trade.get("slippage") or 0)
                          / float(trade.get("signal_price") or 1) * 100.0
                          / (0.5 if trade.get("fill_model") == "NEXT_QUOTE" else 1.0))
         if float(trade.get("signal_price") or 0) > 0 else 0.0},
        side=str(trade.get("side") or "BUY"),
    )
    gates = evidence.get("gates") or []
    failed = [g["gate"] for g in gates if not g.get("passed")]
    decision_match = (len(failed) == 0) == (trade.get("status") != "REJECTED")
    fill_match = abs(recomputed_fill["fill_price"] - float(trade.get("fill_price") or 0)) < 0.05

    return {
        "found": True,
        "label": "RECOMPUTED",
        "trade_id": trade_id,
        "original": {
            "scan_id": trade.get("scan_id"),
            "snapshot_ts": trade.get("snapshot_ts"),
            "decision_ts": trade.get("decision_ts"),
            "fill_price": trade.get("fill_price"),
            "quantity": trade.get("quantity"),
            "config_hash": settings_hash,
            "rule_version": trade.get("rule_version"),
            "model_version": trade.get("model_version"),
        },
        "recomputed": {
            "gates_failed": failed,
            "decision": "ENTER" if len(failed) == 0 else "BLOCK",
            "fill_price": recomputed_fill["fill_price"],
            "quantity": sizing.get("quantity"),
        },
        "deterministic_match": bool(decision_match and fill_match),
        "config_changed_since": settings_hash != current.get("config_hash"),
        "note": ("Replayed from the stored snapshot evidence and stored "
                 "configuration. Original record preserved unchanged."),
    }
