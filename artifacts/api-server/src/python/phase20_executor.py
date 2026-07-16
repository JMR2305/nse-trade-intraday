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
    for t in get_ledger(500):
        if t.get("trade_id") == trade_id:
            return t
    return None


def get_open_trades() -> List[Dict[str, Any]]:
    return [t for t in get_ledger(500) if t.get("status") == "OPEN"]


def get_open_positions_view() -> List[Dict[str, Any]]:
    """Open Phase 20 paper positions joined with live paper-portfolio prices."""
    open_trades = get_open_trades()
    try:
        from paper_trader import get_portfolio
        prices = {str(p["symbol"]).upper(): float(p["current_price"])
                  for p in get_portfolio()["positions"]}
    except Exception:
        prices = {}
    out = []
    for t in open_trades:
        sym = str(t.get("symbol") or "").upper()
        cur = prices.get(sym) or float(t.get("fill_price") or 0)
        qty = int(t.get("quantity") or 0)
        fill = float(t.get("fill_price") or 0)
        out.append({**t, "current_price": cur,
                    "unrealized_pnl": round((cur - fill) * qty, 2)})
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
               now_iso: str) -> Dict[str, Any]:
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
    signal_price = float(sizing.get("entry_price") or 0)
    if qty < 1 or signal_price <= 0:
        return {"created": False, "symbol": sym, "reason": "Invalid sizing"}

    # Duplicate safety net (gates already check this).
    from paper_trader import get_portfolio, execute_buy
    if any(str(p["symbol"]).upper() == sym for p in get_portfolio()["positions"]):
        return {"created": False, "symbol": sym, "reason": "Open position exists"}

    fill = compute_fill(signal_price, settings, side="BUY")
    fill_price = fill["fill_price"]
    charges = compute_charges(fill_price * qty, settings)

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
                     model_version, settings, trigger_source, now_iso)
    try:
        _insert_row(row)
    except DuplicateOpenTrade:
        return {"created": False, "symbol": sym,
                "reason": "Open Phase 20 trade already exists (concurrent claim)"}

    ok, msg = execute_buy(
        sym, qty, fill_price,
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
        store.add_notification("ENTRY_BLOCKED", f"{sym} paper entry blocked",
                               msg, severity="WARN",
                               context={"symbol": sym, "scan_id": scan_id})
        # Release the claimed ledger slot since no position was created.
        _delete_row(trade_id)
        return {"created": False, "symbol": sym, "reason": msg}

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

    from phase20_gates import evaluate_entries
    evaluation = evaluate_entries()
    created: List[Dict[str, Any]] = []
    blocked: List[Dict[str, Any]] = []
    for cand in evaluation.get("candidates", []):
        if not cand.get("eligible"):
            blocked.append({"symbol": cand["symbol"],
                            "failed_gates": cand["failed_gates"]})
            continue
        res = create_paper_entry(cand, settings,
                                 evaluation.get("scan_id"),
                                 evaluation.get("snapshot_ts"),
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
            context={"scan_id": evaluation.get("scan_id"), "blocked": blocked})
    return {"ran": True, "scan_id": evaluation.get("scan_id"),
            "created": created, "blocked": blocked,
            "evaluation": evaluation}


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
