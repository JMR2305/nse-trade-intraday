"""
phase22_evidence.py — Phase 22 durable evidence dataset (append-only).

For EVERY candidate evaluated (opened or blocked) a row is appended with the
full decision context. Outcome fields (returns at 15m/30m/60m/EOD/1d/3d/5d,
MAE, MFE, final outcome) are filled in ONLY after the corresponding time has
actually elapsed, using observed quotes — never future or fabricated data.

Append-only contract:
- Decision-context columns are written once at insert and never modified.
- Outcome columns are write-once: each horizon return is set a single time,
  from the first reliable observation at-or-after the horizon.
- Rows are never deleted.

PAPER TRADING / RESEARCH ONLY. No live orders anywhere.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import phase20_store as store

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_FILE = os.path.join(BASE_DIR, "phase22_evidence.json")

_HORIZONS_MIN = {"ret_15m": 15, "ret_30m": 30, "ret_60m": 60}
_HORIZONS_TDAYS = {"ret_1d": 1, "ret_3d": 3, "ret_5d": 5}
_MAX_OBS = 400

_SCHEMA_READY = False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime] = None) -> str:
    return (dt or _now()).isoformat()


def _parse(ts: Optional[str]) -> Optional[datetime]:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


def _ensure_schema(conn) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS phase22_evidence (
                evidence_id TEXT PRIMARY KEY,
                recorded_at TEXT,
                scan_id TEXT,
                snapshot_ts TEXT,
                symbol TEXT,
                decision TEXT,
                raw_confidence DOUBLE PRECISION,
                calibrated_confidence DOUBLE PRECISION,
                opportunity_score DOUBLE PRECISION,
                trade_quality_score DOUBLE PRECISION,
                rank INTEGER,
                strategy TEXT,
                regime TEXT,
                sector TEXT,
                quote_source TEXT,
                gates JSONB,
                eligibility_result TEXT,
                trade_opened BOOLEAN,
                paper_trade_id TEXT,
                blocking_reasons JSONB,
                signal_price DOUBLE PRECISION,
                observations JSONB,
                ret_15m DOUBLE PRECISION, ret_15m_at TEXT,
                ret_30m DOUBLE PRECISION, ret_30m_at TEXT,
                ret_60m DOUBLE PRECISION, ret_60m_at TEXT,
                ret_eod DOUBLE PRECISION, ret_eod_at TEXT,
                ret_1d DOUBLE PRECISION, ret_1d_at TEXT,
                ret_3d DOUBLE PRECISION, ret_3d_at TEXT,
                ret_5d DOUBLE PRECISION, ret_5d_at TEXT,
                mae_pct DOUBLE PRECISION,
                mfe_pct DOUBLE PRECISION,
                final_outcome TEXT,
                outcome_complete BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
            """
        )
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS phase22_evidence_scan_sym_uidx
            ON phase22_evidence (scan_id, symbol)
            """
        )
    conn.commit()
    _SCHEMA_READY = True


def _with_db(fn, fallback):
    def wrapped(conn):
        _ensure_schema(conn)
        return fn(conn)
    return store._with_db(wrapped, fallback)


# ── File fallback helpers ────────────────────────────────────────────────────

def _read_file() -> List[Dict[str, Any]]:
    try:
        with open(_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def _write_file(rows: List[Dict[str, Any]]) -> None:
    tmp = _FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(rows, f, default=str)
    os.replace(tmp, _FILE)


_COLS = ["evidence_id", "recorded_at", "scan_id", "snapshot_ts", "symbol",
         "decision", "raw_confidence", "calibrated_confidence",
         "opportunity_score", "trade_quality_score", "rank", "strategy",
         "regime", "sector", "quote_source", "gates", "eligibility_result",
         "trade_opened", "paper_trade_id", "blocking_reasons", "signal_price",
         "observations", "ret_15m", "ret_15m_at", "ret_30m", "ret_30m_at",
         "ret_60m", "ret_60m_at", "ret_eod", "ret_eod_at", "ret_1d",
         "ret_1d_at", "ret_3d", "ret_3d_at", "ret_5d", "ret_5d_at",
         "mae_pct", "mfe_pct", "final_outcome", "outcome_complete"]
_JSON_COLS = {"gates", "blocking_reasons", "observations"}


def _insert(row: Dict[str, Any]) -> bool:
    def to_db(conn):
        cols = ", ".join(_COLS)
        ph = ", ".join(["%s"] * len(_COLS))
        vals = [json.dumps(row.get(c)) if c in _JSON_COLS else row.get(c)
                for c in _COLS]
        with conn.cursor() as cur:
            cur.execute(
                f"INSERT INTO phase22_evidence ({cols}) VALUES ({ph}) "
                f"ON CONFLICT (scan_id, symbol) DO NOTHING", vals)
            inserted = cur.rowcount > 0
        conn.commit()
        return inserted

    def to_file():
        rows = _read_file()
        if any(r.get("scan_id") == row["scan_id"]
               and r.get("symbol") == row["symbol"] for r in rows):
            return False
        rows.append(row)
        _write_file(rows)
        return True

    return bool(_with_db(to_db, to_file))


def _update_outcomes(evidence_id: str, fields: Dict[str, Any]) -> None:
    """Write-once outcome updates only. Decision context is never touched."""
    allowed = {"observations", "mae_pct", "mfe_pct", "final_outcome",
               "outcome_complete"} | {
        k for h in list(_HORIZONS_MIN) + list(_HORIZONS_TDAYS) + ["ret_eod"]
        for k in (h, f"{h}_at")}
    fields = {k: v for k, v in fields.items() if k in allowed}
    if not fields:
        return

    # Columns that may legitimately be re-written as observations accumulate
    # until the outcome is complete; everything else is strictly write-once.
    mutable = {"observations", "mae_pct", "mfe_pct"}

    def to_db(conn):
        sets = ", ".join(
            f"{k} = %s" if k in mutable else f"{k} = COALESCE({k}, %s)"
            for k in fields)
        vals = [json.dumps(v) if k in _JSON_COLS else v
                for k, v in fields.items()]
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE phase22_evidence SET {sets} "
                f"WHERE evidence_id = %s AND outcome_complete IS NOT TRUE",
                vals + [evidence_id])
        conn.commit()
        return True

    def to_file():
        rows = _read_file()
        for r in rows:
            if r.get("evidence_id") == evidence_id \
                    and not r.get("outcome_complete"):
                for k, v in fields.items():
                    if k in mutable or r.get(k) is None:
                        r[k] = v
        _write_file(rows)
        return True

    _with_db(to_db, to_file)


# ── Recording candidates ─────────────────────────────────────────────────────

def record_candidates(evaluation: Dict[str, Any],
                      created: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Append one evidence row per candidate (opened AND blocked)."""
    import uuid
    scan_id = evaluation.get("scan_id")
    snapshot_ts = evaluation.get("snapshot_ts")
    if not scan_id:
        return {"recorded": 0, "reason": "No scan_id — nothing recorded"}

    created_by_symbol = {str(c.get("symbol") or "").upper(): c
                         for c in (created or []) if c.get("created")}
    try:
        from phase15_scan_context import build_scan_context
        ctx = build_scan_context()
        symbols_ctx = ctx.get("symbols") or {}
    except Exception:
        symbols_ctx = {}

    n = 0
    for cand in evaluation.get("candidates", []):
        sym = str(cand.get("symbol") or "").upper()
        if not sym:
            continue
        rec = symbols_ctx.get(sym) or {}
        opened = sym in created_by_symbol
        sizing = cand.get("sizing") or {}
        signal_price = float(sizing.get("entry_price")
                             or rec.get("entry_price") or 0)
        row = {
            "evidence_id": f"EV22-{uuid.uuid4().hex[:12]}",
            "recorded_at": _iso(),
            "scan_id": scan_id,
            "snapshot_ts": snapshot_ts,
            "symbol": sym,
            "decision": cand.get("recommendation") or rec.get("final_action"),
            "raw_confidence": cand.get("confidence"),
            "calibrated_confidence": rec.get("confidence"),
            "opportunity_score": cand.get("opportunity_score"),
            "trade_quality_score": cand.get("trade_quality_score"),
            "rank": rec.get("rank"),
            "strategy": cand.get("strategy_name") or cand.get("strategy_id"),
            "regime": cand.get("regime") or rec.get("regime"),
            "sector": cand.get("sector") or rec.get("sector"),
            "quote_source": rec.get("data_quality") or "UNKNOWN",
            "gates": cand.get("gates") or [],
            "eligibility_result": "ELIGIBLE" if cand.get("eligible") else "BLOCKED",
            "trade_opened": opened,
            "paper_trade_id": (created_by_symbol.get(sym) or {}).get("trade_id"),
            "blocking_reasons": cand.get("failed_gates") or [],
            "signal_price": signal_price if signal_price > 0 else None,
            "observations": [],
            "outcome_complete": False,
        }
        if _insert(row):
            n += 1
    return {"recorded": n, "scan_id": scan_id, "label": "PAPER / RESEARCH ONLY"}


# ── Outcome accumulation (time-safe) ─────────────────────────────────────────

def _trading_days_between(d0, d1) -> int:
    """Weekday count between two dates (NSE holiday-approximate)."""
    days, cur = 0, d0
    while cur < d1:
        cur += timedelta(days=1)
        if cur.weekday() < 5:
            days += 1
    return days


def update_outcomes() -> Dict[str, Any]:
    """Observe current reliable quotes and fill any horizons that have elapsed.

    Time-safety: a horizon return is computed only from an observation whose
    timestamp is at-or-after snapshot_ts + horizon. Observations are appended
    as quotes actually arrive — future data can never be used because it is
    never present in the observation list.
    """
    try:
        from phase15_scan_context import build_scan_context
        ctx = build_scan_context()
    except Exception as exc:
        return {"updated": 0, "reason": f"No scan context: {exc}"}
    if not ctx.get("available") or ctx.get("stale", True):
        return {"updated": 0, "reason": "No fresh scan — no observations added"}
    symbols_ctx = ctx.get("symbols") or {}

    rows = list_evidence(limit=1000, incomplete_only=True)
    now = _now()
    now_iso = _iso(now)
    updated = 0

    ledger_by_id: Dict[str, Dict[str, Any]] = {}
    try:
        from phase20_executor import get_ledger
        ledger_by_id = {str(t.get("trade_id")): t for t in get_ledger(500)}
    except Exception:
        pass

    for row in rows:
        sym = str(row.get("symbol") or "").upper()
        base = float(row.get("signal_price") or 0)
        snap_dt = _parse(row.get("snapshot_ts")) or _parse(row.get("recorded_at"))
        if base <= 0 or not snap_dt:
            continue
        rec = symbols_ctx.get(sym) or {}
        quote = float(rec.get("entry_price") or 0)
        dq = str(rec.get("data_quality") or "").upper()
        reliable = quote > 0 and dq in ("LIVE", "NEAR_LIVE") and not rec.get("error")

        obs = list(row.get("observations") or [])
        fields: Dict[str, Any] = {}

        if reliable:
            obs.append({"ts": now_iso, "price": quote})
            if len(obs) > _MAX_OBS:
                obs = obs[:1] + obs[-(_MAX_OBS - 1):]
            fields["observations"] = obs

        # MAE / MFE from actually-observed prices only.
        prices = [float(o["price"]) for o in obs if float(o.get("price") or 0) > 0]
        if prices:
            fields["mae_pct"] = round(min(0.0, (min(prices) - base) / base * 100), 3)
            fields["mfe_pct"] = round(max(0.0, (max(prices) - base) / base * 100), 3)

        def first_obs_at_or_after(target_dt: datetime):
            for o in obs:
                odt = _parse(o.get("ts"))
                if odt and odt >= target_dt and float(o.get("price") or 0) > 0:
                    return o
            return None

        # Minute horizons.
        for col, minutes in _HORIZONS_MIN.items():
            if row.get(col) is not None:
                continue
            target = snap_dt + timedelta(minutes=minutes)
            if now < target:
                continue
            o = first_obs_at_or_after(target)
            if o:
                fields[col] = round((float(o["price"]) - base) / base * 100, 3)
                fields[f"{col}_at"] = o["ts"]

        # End of day: first observation on a later calendar date or after
        # 10:00 UTC (15:30 IST market close) on the snapshot date.
        if row.get("ret_eod") is None:
            eod_target = snap_dt.replace(hour=10, minute=0, second=0,
                                         microsecond=0)
            if eod_target < snap_dt:
                eod_target = snap_dt
            if now >= eod_target:
                o = first_obs_at_or_after(eod_target)
                if o:
                    fields["ret_eod"] = round(
                        (float(o["price"]) - base) / base * 100, 3)
                    fields["ret_eod_at"] = o["ts"]

        # Trading-day horizons.
        for col, tdays in _HORIZONS_TDAYS.items():
            if row.get(col) is not None:
                continue
            if _trading_days_between(snap_dt.date(), now.date()) < tdays:
                continue
            o = None
            for cand_o in obs:
                odt = _parse(cand_o.get("ts"))
                if odt and _trading_days_between(snap_dt.date(), odt.date()) >= tdays \
                        and float(cand_o.get("price") or 0) > 0:
                    o = cand_o
                    break
            if o:
                fields[col] = round((float(o["price"]) - base) / base * 100, 3)
                fields[f"{col}_at"] = o["ts"]

        # Final outcome for opened trades from the paper ledger.
        if row.get("trade_opened") and not row.get("final_outcome"):
            t = ledger_by_id.get(str(row.get("paper_trade_id")))
            if t and t.get("status") == "CLOSED":
                pnl = float(t.get("realized_pnl") or 0)
                fields["final_outcome"] = (
                    f"CLOSED_{'WIN' if pnl > 0 else 'LOSS' if pnl < 0 else 'FLAT'}"
                    f":{t.get('exit_rule')}")

        # Completeness: all horizons resolved (or 5 trading days passed with
        # returns filled where observations existed).
        merged = {**row, **fields}
        horizon_cols = list(_HORIZONS_MIN) + ["ret_eod"] + list(_HORIZONS_TDAYS)
        all_done = all(merged.get(c) is not None for c in horizon_cols)
        outcome_done = (not merged.get("trade_opened")) or \
            bool(merged.get("final_outcome"))
        if all_done and outcome_done:
            fields["outcome_complete"] = True

        if fields:
            _update_outcomes(str(row["evidence_id"]), fields)
            updated += 1

    return {"updated": updated, "evaluated_rows": len(rows),
            "label": "PAPER / RESEARCH ONLY"}


# ── Reads ────────────────────────────────────────────────────────────────────

def list_evidence(limit: int = 200, incomplete_only: bool = False,
                  symbol: Optional[str] = None) -> List[Dict[str, Any]]:
    def from_db(conn):
        q = "SELECT * FROM phase22_evidence"
        conds, vals = [], []
        if incomplete_only:
            conds.append("outcome_complete = FALSE")
        if symbol:
            conds.append("symbol = %s")
            vals.append(symbol.upper())
        if conds:
            q += " WHERE " + " AND ".join(conds)
        q += " ORDER BY recorded_at DESC LIMIT %s"
        vals.append(int(limit))
        with conn.cursor() as cur:
            cur.execute(q, vals)
            cols = [d[0] for d in cur.description]
            out = []
            for r in cur.fetchall():
                d = dict(zip(cols, r))
                d.pop("created_at", None)
                out.append(d)
            return out

    def from_file():
        rows = _read_file()
        if incomplete_only:
            rows = [r for r in rows if not r.get("outcome_complete")]
        if symbol:
            rows = [r for r in rows if r.get("symbol") == symbol.upper()]
        rows.sort(key=lambda r: str(r.get("recorded_at") or ""), reverse=True)
        return rows[:limit]

    return _with_db(from_db, from_file) or []


def evidence_summary() -> Dict[str, Any]:
    rows = list_evidence(limit=5000)
    opened = [r for r in rows if r.get("trade_opened")]
    return {
        "total_rows": len(rows),
        "opened": len(opened),
        "blocked": len([r for r in rows if r.get("eligibility_result") == "BLOCKED"]),
        "outcome_complete": len([r for r in rows if r.get("outcome_complete")]),
        "distinct_scans": len({r.get("scan_id") for r in rows}),
        "distinct_days": len({str(r.get("recorded_at") or "")[:10] for r in rows}),
        "append_only": True,
        "label": "PAPER / RESEARCH ONLY",
    }
