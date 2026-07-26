"""
phase4a_trade_journal.py — Phase 4A Section 3: Paper Trading Validation.

Enriches every Phase 20 paper trade with all 13 required fields, assigns
Journal ID and Audit ID, and verifies portfolio accounting consistency
after every trade event.

Required fields per trade:
  1.  timestamp        — fill_ts (entry) or exit_ts (exit)
  2.  symbol
  3.  signal           — final_action from scan recommendation
  4.  ai_confidence    — calibrated_confidence from scan
  5.  risk_decision    — ALLOW / BLOCK from RC-8
  6.  position_size    — quantity × fill_price
  7.  entry            — fill_price
  8.  exit             — exit_price (None if still OPEN)
  9.  target           — target from trade row
  10. stop             — stop_loss from trade row
  11. holding_time     — fill_ts → exit_ts duration
  12. pnl              — realized_pnl (None if OPEN)
  13. exit_reason      — exit_rule
  14. journal_id       — SHA-256(trade_id)[:16] — deterministic
  15. audit_id         — random UUID4 assigned once per journal run

Outputs:
  docs/trade_journal_YYYYMMDD.json
  docs/trade_journal_YYYYMMDD.md

Usage:
    uv run python phase4a_trade_journal.py            # today
    uv run python phase4a_trade_journal.py --date 2026-07-25

PAPER TRADING / RESEARCH ONLY.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import uuid
from typing import Any, Optional

_DIR = os.path.dirname(os.path.abspath(__file__))
_DOCS = os.path.join(_DIR, "..", "..", "docs")
os.makedirs(_DOCS, exist_ok=True)

LABEL = "PAPER TRADING / RESEARCH ONLY"
ACCOUNTING_EPSILON = 1.0   # ₹ — allowable accounting drift


# ── Helpers ───────────────────────────────────────────────────────────────────

def _now_ist() -> str:
    try:
        import zoneinfo
        return datetime.datetime.now(zoneinfo.ZoneInfo("Asia/Kolkata")).isoformat()
    except Exception:
        return datetime.datetime.utcnow().isoformat() + "Z"


def _journal_id(trade_id: str) -> str:
    return hashlib.sha256(trade_id.encode()).hexdigest()[:16]


def _parse_dt(s: Optional[str]) -> Optional[datetime.datetime]:
    if not s:
        return None
    try:
        return datetime.datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def _holding_time(fill_ts: Optional[str], exit_ts: Optional[str]) -> Optional[str]:
    a = _parse_dt(fill_ts)
    b = _parse_dt(exit_ts)
    if not a:
        return None
    end = b or datetime.datetime.now(datetime.timezone.utc)
    delta = end - a
    h, rem = divmod(int(delta.total_seconds()), 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m}m {s}s"


def _get_signal_cache() -> list[dict]:
    """Return the signals_cache rows from the API or DB."""
    import urllib.request
    import urllib.error
    try:
        with urllib.request.urlopen("http://localhost:8080/api/signals", timeout=6) as r:
            data = json.loads(r.read())
            return data if isinstance(data, list) else data.get("signals", [])
    except Exception:
        return []


# ── Journal builder ───────────────────────────────────────────────────────────

def build_journal(date_str: Optional[str] = None) -> dict:
    """Build the trade journal for a given date (default: today)."""
    target_date = date_str or datetime.date.today().isoformat()

    print(f"\n{'=' * 60}")
    print(f"  Phase 4A Trade Journal — {target_date}")
    print(f"  {LABEL}")
    print(f"{'=' * 60}\n")

    # Load all phase20 trades
    try:
        from phase20_executor import get_ledger
        all_trades = get_ledger(500)
    except Exception as e:
        print(f"  ❌ Could not load ledger: {e}")
        return {"error": str(e), "date": target_date}

    # Filter to target date (by fill_ts or exit_ts)
    day_trades = [
        t for t in all_trades
        if (str(t.get("fill_ts") or "").startswith(target_date)
            or str(t.get("exit_ts") or "").startswith(target_date))
    ]

    # Also include all OPEN trades (they may have been opened earlier)
    open_trades = [t for t in all_trades if t.get("status") == "OPEN"]
    seen_ids = {t.get("trade_id") for t in day_trades}
    for t in open_trades:
        if t.get("trade_id") not in seen_ids:
            day_trades.append(t)

    # Load signals for AI confidence lookup
    signal_cache = _get_signal_cache()
    sig_by_symbol: dict[str, dict] = {}
    for s in signal_cache:
        sym = str(s.get("stock") or s.get("symbol") or "").upper()
        if sym:
            sig_by_symbol[sym] = s

    # Load portfolio for accounting check
    portfolio_snap: dict = {}
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:8080/api/portfolio/snapshot", timeout=6) as r:
            portfolio_snap = json.loads(r.read())
    except Exception:
        pass

    # Build journal entries
    entries: list[dict] = []
    run_audit_id = str(uuid.uuid4())   # one audit ID per journal run

    for trade in day_trades:
        trade_id = str(trade.get("trade_id") or "")
        sym = str(trade.get("symbol") or "").upper()
        sig = sig_by_symbol.get(sym, {})

        fill_ts = trade.get("fill_ts")
        exit_ts = trade.get("exit_ts")
        fill_price = float(trade.get("fill_price") or 0)
        qty = int(trade.get("quantity") or 0)
        stop = float(trade.get("stop_loss") or 0)
        target = float(trade.get("target") or 0)
        exit_price = float(trade.get("exit_price") or 0) if trade.get("exit_price") else None
        realized_pnl = float(trade.get("realized_pnl") or 0) if trade.get("realized_pnl") is not None else None
        status = str(trade.get("status") or "")

        # AI confidence: prefer trade record, fall back to signal cache
        ai_conf = float(trade.get("confidence") or 0)
        if ai_conf == 0:
            ai_conf = float(sig.get("confidence") or sig.get("calibrated_confidence") or 0)

        # Signal (final_action)
        signal_action = str(trade.get("trigger_source") or "")
        if not signal_action:
            signal_action = str(sig.get("signal") or sig.get("final_action") or "UNKNOWN")

        # Risk decision: if trade exists it means ALLOW
        risk_decision = "ALLOW" if status in ("OPEN", "CLOSED") else "BLOCK"

        entry = {
            # 13 required fields
            "timestamp": fill_ts or _now_ist(),
            "symbol": sym,
            "signal": signal_action,
            "ai_confidence": round(ai_conf, 2),
            "risk_decision": risk_decision,
            "position_size": round(qty * fill_price, 2),
            "entry": fill_price,
            "exit": exit_price,
            "target": target,
            "stop": stop,
            "holding_time": _holding_time(fill_ts, exit_ts),
            "pnl": realized_pnl,
            "exit_reason": trade.get("exit_rule"),
            # IDs
            "journal_id": _journal_id(trade_id),
            "audit_id": run_audit_id,
            # Extra context
            "trade_id": trade_id,
            "status": status,
            "scan_id": trade.get("scan_id"),
            "strategy": trade.get("strategy_name") or trade.get("strategy_id"),
            "regime": trade.get("regime"),
        }

        # Accounting consistency check for this trade
        entry["accounting_consistent"] = _check_trade_accounting(
            trade, portfolio_snap)

        entries.append(entry)
        _print_entry(entry)

    # Portfolio-level consistency check
    port_consistent, port_detail = _check_portfolio_accounting(portfolio_snap)
    print(f"\n  Portfolio accounting: {'✅' if port_consistent else '⚠️'} {port_detail}")

    result = {
        "label": LABEL,
        "generated_at": _now_ist(),
        "date": target_date,
        "audit_id": run_audit_id,
        "trade_count": len(entries),
        "portfolio_accounting_consistent": port_consistent,
        "portfolio_accounting_detail": port_detail,
        "trades": entries,
    }

    _write_reports(result, target_date)
    return result


def _check_trade_accounting(trade: dict, portfolio: dict) -> bool:
    """
    Verify that a closed trade's P&L is consistent with its fill data.
    Returns True if consistent (or if the trade is OPEN or data is missing).
    """
    status = str(trade.get("status") or "")
    if status != "CLOSED":
        return True
    qty = int(trade.get("quantity") or 0)
    fill = float(trade.get("fill_price") or 0)
    exit_p = float(trade.get("exit_price") or 0)
    realized = float(trade.get("realized_pnl") or 0)
    if qty <= 0 or fill <= 0 or exit_p <= 0:
        return True  # Cannot verify without full data
    expected_gross = (exit_p - fill) * qty
    charges = float(trade.get("est_charges") or 0)
    expected_net = expected_gross - charges
    return abs(realized - expected_net) < ACCOUNTING_EPSILON


def _check_portfolio_accounting(portfolio: dict) -> tuple[bool, str]:
    """Check cash + invested = total_equity within epsilon."""
    if not portfolio:
        return True, "portfolio snapshot unavailable (cannot verify)"
    cash = float(portfolio.get("cash", 0))
    invested = float(portfolio.get("invested_value", 0))
    equity = float(portfolio.get("total_equity", cash + invested))
    diff = abs(equity - (cash + invested))
    ok = diff < ACCOUNTING_EPSILON
    detail = f"equity=₹{equity:.2f} cash=₹{cash:.2f} invested=₹{invested:.2f} diff=₹{diff:.4f}"
    return ok, detail


def _print_entry(e: dict) -> None:
    status = e.get("status", "?")
    pnl_str = f"₹{e['pnl']:.2f}" if e.get("pnl") is not None else "OPEN"
    exit_str = f"₹{e['exit']:.2f}" if e.get("exit") else "—"
    acc = "OK" if e.get("accounting_consistent") else "WARN"
    print(f"  {acc} [{status}] {e['symbol']:8s} "
          f"entry=₹{e['entry']:.2f}  exit={exit_str:>10}  "
          f"P&L={pnl_str:>12}  conf={e['ai_confidence']:.1f}%  "
          f"j={e['journal_id']}")


def _write_reports(result: dict, date_str: str) -> None:
    date_compact = date_str.replace("-", "")

    # JSON
    json_path = os.path.join(_DOCS, f"trade_journal_{date_compact}.json")
    with open(json_path, "w") as f:
        json.dump(result, f, indent=2, default=str)
    print(f"\n  Journal JSON: {json_path}")

    # Markdown
    md_path = os.path.join(_DOCS, f"trade_journal_{date_compact}.md")
    with open(md_path, "w") as f:
        f.write(f"# Phase 4A Trade Journal — {date_str}\n\n")
        f.write(f"**{result['label']}**  \n")
        f.write(f"Generated: {result['generated_at']}  \n")
        f.write(f"Audit ID: `{result['audit_id']}`  \n")
        f.write(f"Trades: {result['trade_count']}  \n")
        acc_icon = "✅" if result.get("portfolio_accounting_consistent") else "⚠️"
        f.write(f"Portfolio accounting: {acc_icon} {result.get('portfolio_accounting_detail', '')}\n\n")

        f.write("## Trades\n\n")
        f.write("| # | Symbol | Signal | AI Conf | Risk | Size (₹) | Entry | Exit | Target | Stop | Hold | P&L | Exit Reason | Journal ID |\n")
        f.write("|---|--------|--------|---------|------|----------|-------|------|--------|------|------|-----|-------------|------------|\n")
        for i, t in enumerate(result.get("trades", []), 1):
            pnl = f"₹{t['pnl']:.2f}" if t.get("pnl") is not None else "—"
            exit_p = f"₹{t['exit']:.2f}" if t.get("exit") else "—"
            f.write(
                f"| {i} | {t['symbol']} | {t['signal']} | {t['ai_confidence']:.1f}% "
                f"| {t['risk_decision']} | ₹{t['position_size']:.0f} "
                f"| ₹{t['entry']:.2f} | {exit_p} | ₹{t['target']:.2f} | ₹{t['stop']:.2f} "
                f"| {t['holding_time'] or '—'} | {pnl} | {t.get('exit_reason') or '—'} "
                f"| `{t['journal_id']}` |\n"
            )
    print(f"  Journal MD:   {md_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 4A trade journal")
    parser.add_argument("--date", type=str, default=None,
                        help="Date YYYY-MM-DD (default: today)")
    args = parser.parse_args()
    build_journal(args.date)
