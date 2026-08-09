"""
phase26_consistency.py — Phase 26B: cross-page consistency validation.

Derives the canonical value set ONCE per scan_id (latest scan meta, unified
replay snapshot, canonical portfolio, phase20 ledger, pipeline events) and
compares the data backing every major page against it:

  Mission Control       — pipeline_events stage counts vs replay counts
  AI Operations Centre  — phase15 derived caches (ai_decisions/opportunity)
                          vs the canonical scan context (composes the
                          existing phase15 consistency checker — never
                          re-implements it)
  Replay                — replay snapshot must reference the canonical scan
  Investigation Centre  — replay-backed: same scan reference check + event
                          duplicates (one-shot events must be unique)
  Portfolio / Broker    — canonical portfolio equity = cash + position value;
                          executed trades in replay = ledger rows for scan
  Performance           — realized PnL consistent between canonical
                          portfolio and CLOSED ledger rows
  Learning Centre       — every CLOSED ledger row has a phase24 record
  Validation Dashboard  — latest 26A run references a real scan

Every mismatch is reported with source (page), field, expected vs actual.
Missing REQUIRED fields are ERRORS — never skipped (a page that cannot prove
parity is a finding, not a pass).

All inputs are injectable for tests. STRICTLY READ-ONLY.
PAPER TRADING / RESEARCH ONLY.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

TOLERANCE = 0.05          # rupee tolerance for derived monetary values

# One-shot event types: more than one per (symbol, scan) is a duplicate.
ONE_SHOT_EVENTS = ("ORDER_EXECUTED", "POSITION_OPENED", "POSITION_CLOSED")

ADVISORY = ("Cross-page consistency over canonical stores. Nothing is "
            "modified. PAPER TRADING / RESEARCH ONLY.")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _is_executed(row: Dict[str, Any]) -> bool:
    """Fill-based executed predicate, aligned with the replay engine's
    ledger query (`_get_execution_trades`): a trade is executed iff it
    carries an actual fill (fill_price > 0 / fill_ts), regardless of its
    later lifecycle status (OPEN, EXIT_PENDING, CLOSED all keep their
    fill). Rows without a fill — rejected/cancelled/submitted — are not."""
    try:
        if row.get("fill_price") is not None and float(row["fill_price"]) > 0:
            return True
    except (TypeError, ValueError):
        pass
    return bool(row.get("fill_ts"))


def _f(v, default: float = 0.0) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def run_cross_page_consistency(
        scan_meta: Optional[Dict[str, Any]] = None,
        replay: Optional[Dict[str, Any]] = None,
        portfolio: Optional[Dict[str, Any]] = None,
        ledger_rows: Optional[List[Dict[str, Any]]] = None,
        stage_events: Optional[Dict[str, Any]] = None,
        scan_events: Optional[List[Dict[str, Any]]] = None,
        learning_trade_ids: Optional[List[str]] = None,
        phase15_report: Optional[Dict[str, Any]] = None,
        e2e_runs: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Compare every page's backing data against the canonical value set.
    Returns {available, verdict, scan_id, mismatches, issues, ...}."""
    mismatches: List[Dict[str, Any]] = []
    checks = 0

    def add(source: str, field: str, expected: Any, actual: Any,
            severity: str, note: str, symbol: Optional[str] = None) -> None:
        mismatches.append({
            "source": source, "field": field, "symbol": symbol,
            "expected": expected, "actual": actual,
            "severity": severity, "note": note})

    def require(source: str, field: str, value: Any, note: str) -> bool:
        """Missing required field ⇒ ERROR, never skipped."""
        nonlocal checks
        checks += 1
        if value in (None, "", []):
            add(source, field, "present", None, "ERROR",
                f"{source} is missing required field '{field}' — {note}")
            return False
        return True

    def compare_num(source: str, field: str, expected: Any, actual: Any,
                    note: str, symbol: Optional[str] = None,
                    tol: float = TOLERANCE) -> None:
        nonlocal checks
        checks += 1
        try:
            if abs(float(expected) - float(actual)) > tol:
                add(source, field, expected, actual, "ERROR", note, symbol)
        except (TypeError, ValueError):
            add(source, field, expected, actual, "ERROR",
                f"{note} (non-numeric value)", symbol)

    # ── Canonical anchor: latest scan ────────────────────────────────────────
    if scan_meta is None:
        try:
            import scan_state_store
            scan_meta = scan_state_store.load_latest_meta() or {}
        except Exception:
            scan_meta = {}
    scan_id = scan_meta.get("scan_id")
    if not scan_id:
        return {"available": False, "reason": "no canonical scan snapshot",
                "generated_at": _now_iso(), "mismatches": [], "issues": [],
                "verdict": "INSUFFICIENT", "note": ADVISORY}

    # ── Replay page (also backs Investigation Centre) ────────────────────────
    if replay is None:
        try:
            from replay_engine import build_replay
            replay = build_replay("latest") or {}
        except Exception as exc:
            replay = {"error": str(exc)[:200]}
    if require("replay", "scan_id", replay.get("scan_id"),
               "replay cannot prove it tracks the canonical scan"):
        checks += 1
        if str(replay.get("scan_id")) != str(scan_id):
            add("replay", "scan_id", scan_id, replay.get("scan_id"), "ERROR",
                "Replay/Investigation pages show a different scan than the "
                "canonical latest — missing replay update")

    # ── Ledger + Portfolio pages ─────────────────────────────────────────────
    if ledger_rows is None:
        try:
            import phase20_executor as p20
            ledger_rows = p20.get_ledger(limit=10_000)
        except Exception:
            ledger_rows = []
    scan_rows = [r for r in ledger_rows if r.get("scan_id") == scan_id]
    # Execution parity compares EXECUTED trades only — rows that were merely
    # created/submitted or were rejected/cancelled never produced an
    # ORDER_EXECUTED event or a replay `out` count, so counting them would
    # raise false critical mismatches on perfectly consistent pages.
    executed_rows = [r for r in scan_rows if _is_executed(r)]

    if portfolio is None:
        try:
            from canonical_portfolio import build_canonical_portfolio
            portfolio = build_canonical_portfolio()
        except Exception as exc:
            portfolio = {"error": str(exc)[:200]}

    if require("portfolio", "cash", portfolio.get("cash"),
               "portfolio page cannot prove cash parity"):
        positions = portfolio.get("positions") or []
        pos_value = sum(
            _f(p.get("current_value"),
               _f(p.get("mark_price"), _f(p.get("avg_price")))
               * _f(p.get("quantity"))) for p in positions)
        equity = portfolio.get("equity")
        if require("portfolio", "equity", equity,
                   "equity must be derivable as cash + position value"):
            compare_num("portfolio", "equity",
                        _f(portfolio.get("cash")) + pos_value, equity,
                        "Portfolio page equity ≠ cash + position value from "
                        "the same canonical snapshot", tol=1.0)

    # Broker / execution parity: replay's own ledger-derived trade list
    # (`execution_trades`, scan-scoped fills) must equal the filled ledger
    # rows for the scan. NOTE: pipeline_counts.execution.out is a SYMBOL
    # count from the scan snapshot and can legitimately exceed ledger rows
    # (blocked entries never produce a ledger row) — comparing to it would
    # raise false mismatches on consistent systems. The trade list is
    # REQUIRED whenever replay tracks the canonical scan; an empty list is
    # a value (compared), a missing field is an ERROR.
    if replay.get("scan_id") and str(replay.get("scan_id")) == str(scan_id):
        replay_trades = replay.get("execution_trades")
        checks += 1
        if not isinstance(replay_trades, list):
            add("replay", "execution_trades", "present", None, "ERROR",
                "replay is missing required field 'execution_trades' — "
                "replay cannot prove executed-trade parity")
        else:
            compare_num("broker", "executed_trades",
                        len(executed_rows), len(replay_trades),
                        "Broker/Replay executed-trade count disagrees with "
                        "the filled phase20 ledger rows for this scan",
                        tol=0.0)

    # ── Mission Control: canonical event stream ─────────────────────────────
    if stage_events is None:
        try:
            from pipeline_events import stage_summary
            stage_events = stage_summary(scan_id=scan_id)
        except Exception:
            stage_events = {}
    stage_map = {str(s.get("stage") or "").upper(): s
                 for s in (stage_events or {}).get("stages") or []}
    if scan_events is None:
        try:
            # ALL stages: POSITION_OPENED/POSITION_CLOSED are emitted in the
            # PORTFOLIO stage, ORDER_EXECUTED in EXECUTION — a stage-filtered
            # query would blind the duplicate check.
            from pipeline_events import query_events
            scan_events = query_events(scan_id=scan_id, limit=5000)
        except Exception:
            scan_events = []

    executed_events = [e for e in scan_events
                       if e.get("event_type") == "ORDER_EXECUTED"]
    checks += 1
    if len(executed_events) != len(executed_rows):
        add("mission_control", "executed_events",
            len(executed_rows), len(executed_events), "ERROR",
            "EXECUTION-stage ORDER_EXECUTED events disagree with the ledger "
            "rows for this scan — Mission Control shows a different picture "
            "than the Broker page")

    # Duplicate one-shot events (Investigation Centre integrity). Keyed by
    # trade_id when present (multiple legitimate trades on one symbol are
    # possible across sessions), falling back to symbol.
    seen: Dict[str, int] = {}
    sym_of: Dict[str, str] = {}
    for e in scan_events:
        if e.get("event_type") not in ONE_SHOT_EVENTS:
            continue
        # Canonical event shape (pipeline_events.query_events) carries
        # metadata under `payload`; the executor emits trade_id there.
        ident = None
        for container in (e.get("payload"), e.get("detail"), e):
            if isinstance(container, dict) and container.get("trade_id"):
                ident = str(container["trade_id"])
                break
        if ident is None and e.get("symbol"):
            ident = str(e.get("symbol")).upper()
        if not ident:
            continue
        k = f"{e['event_type']}:{ident}"
        seen[k] = seen.get(k, 0) + 1
        sym_of[k] = str(e.get("symbol") or ident).upper()
    dupes = {k: n for k, n in seen.items() if n > 1}
    checks += 1
    for k, n in dupes.items():
        add("investigation", "duplicate_event", 1, n, "ERROR",
            f"one-shot event {k} appears {n}× for scan {scan_id} — "
            "duplicate pipeline events", symbol=sym_of.get(k))

    # ── Performance page: realized PnL vs CLOSED ledger rows ────────────────
    closed = [r for r in ledger_rows
              if str(r.get("status") or "").upper() == "CLOSED"]
    if closed and portfolio.get("realized_pnl") is not None:
        ledger_pnl = sum(_f(r.get("realized_pnl")) for r in closed)
        compare_num("performance", "realized_pnl", ledger_pnl,
                    portfolio.get("realized_pnl"),
                    "Performance/Portfolio realized PnL disagrees with the "
                    "sum of CLOSED ledger rows", tol=1.0)

    # ── Learning Centre: CLOSED trades must have learning records ───────────
    if learning_trade_ids is None:
        try:
            import phase24_store
            learning_trade_ids = [
                str(r.get("trade_id") or "")
                for r in phase24_store.list_trade_records(limit=1000)]
        except Exception:
            learning_trade_ids = []
    known = {str(t) for t in learning_trade_ids}
    checks += 1
    missing_learning = [str(r.get("trade_id") or r.get("symbol") or "?")
                        for r in closed
                        if str(r.get("trade_id") or "") not in known]
    if missing_learning:
        add("learning", "trade_records", len(closed),
            len(closed) - len(missing_learning), "WARNING",
            f"{len(missing_learning)} CLOSED trades missing from the "
            f"Learning Centre records: {missing_learning[:5]}")

    # ── AI Ops Centre / Trade Decisions: compose phase15 checker ────────────
    if phase15_report is None:
        try:
            from phase15_consistency import run_consistency_check
            phase15_report = run_consistency_check()
        except Exception as exc:
            phase15_report = {"available": False, "error": str(exc)[:200]}
    checks += 1
    if phase15_report.get("available"):
        for m in phase15_report.get("mismatches") or []:
            sev = str(m.get("severity") or "")
            add(f"ai_ops:{m.get('source')}", str(m.get("field")),
                m.get("canonical_value"), m.get("source_value"),
                "ERROR" if sev in ("ERROR", "CRITICAL") else "WARNING",
                str(m.get("note") or "phase15 derived-cache mismatch"),
                symbol=m.get("symbol"))
    else:
        add("ai_ops", "phase15_report", "available",
            phase15_report.get("error") or phase15_report.get("reason"),
            "WARNING", "phase15 consistency checker could not run — AI Ops "
            "derived caches were NOT validated this cycle")

    # ── Validation Dashboard: latest 26A run must reference a real scan ─────
    if e2e_runs is None:
        try:
            import phase26_store
            e2e_runs = phase26_store.list_runs(limit=1)
        except Exception:
            e2e_runs = []
    checks += 1
    if e2e_runs:
        latest_run_scan = e2e_runs[0].get("scan_id")
        if latest_run_scan and str(latest_run_scan) != str(scan_id):
            add("validation_dashboard", "scan_id", scan_id, latest_run_scan,
                "WARNING",
                "Validation Dashboard's latest E2E run predates the current "
                "canonical scan — rerun to re-validate")

    # ── Verdict + issue normalization ────────────────────────────────────────
    hard = [m for m in mismatches if m["severity"] == "ERROR"]
    verdict = "PASS" if not mismatches else ("FAIL" if hard else "WARN")

    issues = [{
        "category": "CONSISTENCY",
        "key": f"{m['source']}:{m['field']}"
               + (f":{m['symbol']}" if m.get("symbol") else ""),
        "severity": "CRITICAL" if m["severity"] == "ERROR" else "WARNING",
        "title": f"{m['source']} mismatch on {m['field']}",
        "detail": (f"expected {m['expected']!r}, got {m['actual']!r} — "
                   f"{m['note']}")[:900],
        "source": "cross_page_consistency",
    } for m in mismatches]

    return {
        "available": True,
        "generated_at": _now_iso(),
        "scan_id": scan_id,
        "checks_performed": checks,
        "mismatch_count": len(mismatches),
        "hard_mismatch_count": len(hard),
        "mismatches": mismatches[:200],
        "issues": issues,
        "verdict": verdict,
        "note": ADVISORY,
    }
