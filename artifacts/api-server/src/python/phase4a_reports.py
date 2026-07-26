"""
phase4a_reports.py — Phase 4A Section 6: Session Report Generator.

Generates all 7 report types in JSON + Markdown:

  1. Daily Summary
  2. Trade Summary
  3. Risk Report
  4. Performance Report
  5. System Health Report
  6. AI Report
  7. Portfolio Report

Writes to:  docs/session_reports/YYYYMMDD/
Manifest:   docs/session_reports/YYYYMMDD/manifest.json

Usage:
    uv run python phase4a_reports.py --all [--date YYYY-MM-DD]
    uv run python phase4a_reports.py --type risk [--date YYYY-MM-DD]

PAPER TRADING / RESEARCH ONLY.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
from typing import Any, Optional

_DIR = os.path.dirname(os.path.abspath(__file__))
_DOCS = os.path.join(_DIR, "..", "..", "docs")

LABEL = "PAPER TRADING / RESEARCH ONLY"

REPORT_TYPES = [
    "daily_summary",
    "trade_summary",
    "risk_report",
    "performance_report",
    "system_health",
    "ai_report",
    "portfolio_report",
]


def _now_ist() -> str:
    try:
        import zoneinfo
        return datetime.datetime.now(zoneinfo.ZoneInfo("Asia/Kolkata")).isoformat()
    except Exception:
        return datetime.datetime.utcnow().isoformat() + "Z"


def _reports_dir(date_str: str) -> str:
    d = date_str.replace("-", "")
    path = os.path.join(_DOCS, "session_reports", d)
    os.makedirs(path, exist_ok=True)
    return path


def _write(rdir: str, name: str, data: dict, md_text: str) -> tuple[str, str]:
    json_path = os.path.join(rdir, f"{name}.json")
    md_path = os.path.join(rdir, f"{name}.md")
    with open(json_path, "w") as f:
        json.dump(data, f, indent=2, default=str)
    with open(md_path, "w") as f:
        f.write(md_text)
    return json_path, md_path


# ── 1. Daily Summary ──────────────────────────────────────────────────────────

def gen_daily_summary(date_str: str) -> dict:
    from phase4a_risk_metrics import compute_risk_metrics
    from phase4a_ai_metrics import compute_ai_metrics
    from phase4a_validate import run_validation

    risk = compute_risk_metrics(date_str)
    ai = compute_ai_metrics(date_str)
    val = run_validation()

    data = {
        "label": LABEL,
        "report_type": "daily_summary",
        "date": date_str,
        "generated_at": _now_ist(),
        "production_ready": val.get("production_ready"),
        "closed_trades": risk.get("closed_trades"),
        "win_rate_pct": risk.get("win_rate_pct"),
        "realised_pnl": None,   # from portfolio below
        "max_drawdown_pct": risk.get("max_drawdown_pct"),
        "total_signals": ai.get("signals_evaluated"),
        "buy_recommendations": ai.get("buy_count"),
        "avg_ai_confidence": ai.get("avg_confidence"),
        "kill_switch_events": risk.get("kill_switch_events"),
        "circuit_breaker_events": risk.get("circuit_breaker_events"),
        "invariants_passed": val.get("passed"),
        "invariants_failed": val.get("failed"),
    }

    # Try to get realised P&L from portfolio
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:8080/api/portfolio/snapshot", timeout=5) as r:
            port = json.loads(r.read())
            data["realised_pnl"] = port.get("realised_pnl")
            data["total_equity"] = port.get("total_equity")
    except Exception:
        pass

    md = _md_daily(data)
    return data, md


def _md_daily(d: dict) -> str:
    icon = "✅" if d.get("production_ready") else "❌"
    lines = [
        f"# Daily Session Summary — {d['date']}",
        "",
        f"**{d['label']}**  ",
        f"Generated: {d['generated_at']}  ",
        f"Production Ready: {icon}",
        "",
        "## Key Metrics",
        "",
        f"| Metric | Value |",
        f"|--------|-------|",
        f"| Closed Trades | {d.get('closed_trades', 0)} |",
        f"| Win Rate | {d.get('win_rate_pct', 0):.1f}% |",
        f"| Realised P&L | ₹{d.get('realised_pnl', 0) or 0:.2f} |",
        f"| Max Drawdown | {d.get('max_drawdown_pct', 0):.2f}% |",
        f"| Total Signals | {d.get('total_signals', 0)} |",
        f"| BUY Recommendations | {d.get('buy_recommendations', 0)} |",
        f"| Avg AI Confidence | {d.get('avg_ai_confidence', 0) or 0:.1f}% |",
        f"| Kill Switch Events | {d.get('kill_switch_events', 0)} |",
        f"| Circuit Breaker Events | {d.get('circuit_breaker_events', 0)} |",
        f"| Safety Invariants | {d.get('invariants_passed', 0)}/8 PASS |",
    ]
    return "\n".join(lines) + "\n"


# ── 2. Trade Summary ──────────────────────────────────────────────────────────

def gen_trade_summary(date_str: str) -> dict:
    from phase4a_trade_journal import build_journal
    journal = build_journal(date_str)

    data = {
        "label": LABEL,
        "report_type": "trade_summary",
        "date": date_str,
        "generated_at": _now_ist(),
        "trade_count": journal.get("trade_count", 0),
        "accounting_consistent": journal.get("portfolio_accounting_consistent"),
        "trades": journal.get("trades", []),
    }
    md = _md_trade(data)
    return data, md


def _md_trade(d: dict) -> str:
    lines = [
        f"# Trade Summary — {d['date']}",
        "",
        f"**{d['label']}**  ",
        f"Generated: {d['generated_at']}  ",
        f"Trades: {d['trade_count']}  ",
        f"Accounting: {'✅' if d.get('accounting_consistent') else '⚠️'}",
        "",
        "## Trades",
        "",
        "| Symbol | Signal | AI Conf | P&L | Exit Reason | Journal ID |",
        "|--------|--------|---------|-----|-------------|------------|",
    ]
    for t in d.get("trades", []):
        pnl = f"₹{t['pnl']:.2f}" if t.get("pnl") is not None else "OPEN"
        lines.append(
            f"| {t['symbol']} | {t['signal']} | {t['ai_confidence']:.1f}% "
            f"| {pnl} | {t.get('exit_reason') or '—'} | `{t['journal_id']}` |"
        )
    return "\n".join(lines) + "\n"


# ── 3. Risk Report ────────────────────────────────────────────────────────────

def gen_risk_report(date_str: str) -> dict:
    from phase4a_risk_metrics import compute_risk_metrics
    metrics = compute_risk_metrics(date_str)
    data = {"report_type": "risk_report", "date": date_str,
            "generated_at": _now_ist(), **metrics}
    md = _md_risk(data)
    return data, md


def _md_risk(d: dict) -> str:
    lines = [
        f"# Risk Report — {d['date']}",
        "",
        f"**{d['label']}**  ",
        f"Generated: {d['generated_at']}",
        "",
        "## Risk Metrics",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Win Rate | {d.get('win_rate_pct', 0):.1f}% |",
        f"| Loss Rate | {d.get('loss_rate_pct', 0):.1f}% |",
        f"| Avg Reward/Risk | {d.get('avg_reward_risk_ratio') or 'N/A'} |",
        f"| Profit Factor | {d.get('profit_factor', 0)} |",
        f"| Expectancy | ₹{d.get('expectancy', 0):.2f} |",
        f"| Max Drawdown | {d.get('max_drawdown_pct', 0):.2f}% |",
        f"| Largest Win | ₹{d.get('largest_win', 0):.2f} |",
        f"| Largest Loss | ₹{d.get('largest_loss', 0):.2f} |",
        f"| Daily Risk | {d.get('daily_risk_pct', 0):.4f}% |",
        f"| Capital Usage | {d.get('capital_usage_pct', 0):.2f}% |",
        f"| Position Exposure | {d.get('position_exposure_pct', 0):.2f}% |",
        f"| Kill Switch Events | {d.get('kill_switch_events', 0)} |",
        f"| Circuit Breaker Events | {d.get('circuit_breaker_events', 0)} |",
        f"| Open Pos Limit Usage | {d.get('open_position_limit_usage_pct', 0):.1f}% |",
        "",
        "## Sector Exposure",
        "",
        "| Sector | Exposure % |",
        "|--------|-----------|",
    ]
    for sector, pct in (d.get("sector_exposure") or {}).items():
        lines.append(f"| {sector} | {pct:.2f}% |")
    if not d.get("sector_exposure"):
        lines.append("| — | No open positions |")
    return "\n".join(lines) + "\n"


# ── 4. Performance Report ─────────────────────────────────────────────────────

def gen_performance_report(date_str: str) -> dict:
    from phase4a_risk_metrics import compute_risk_metrics
    metrics = compute_risk_metrics(date_str)
    data = {
        "label": LABEL,
        "report_type": "performance_report",
        "date": date_str,
        "generated_at": _now_ist(),
        "total_return_pct": metrics.get("total_return_pct"),
        "win_rate_pct": metrics.get("win_rate_pct"),
        "profit_factor": metrics.get("profit_factor"),
        "expectancy": metrics.get("expectancy"),
        "max_drawdown_pct": metrics.get("max_drawdown_pct"),
        "max_consecutive_wins": metrics.get("max_consecutive_wins"),
        "max_consecutive_losses": metrics.get("max_consecutive_losses"),
        "avg_win": metrics.get("avg_win"),
        "avg_loss": metrics.get("avg_loss"),
        "closed_trades": metrics.get("closed_trades"),
    }
    md = _md_performance(data)
    return data, md


def _md_performance(d: dict) -> str:
    lines = [
        f"# Performance Report — {d['date']}",
        "",
        f"**{d['label']}**  ",
        f"Generated: {d['generated_at']}",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Total Return | {d.get('total_return_pct', 0):.2f}% |",
        f"| Win Rate | {d.get('win_rate_pct', 0):.1f}% |",
        f"| Profit Factor | {d.get('profit_factor', 0)} |",
        f"| Expectancy | ₹{d.get('expectancy', 0):.2f} |",
        f"| Max Drawdown | {d.get('max_drawdown_pct', 0):.2f}% |",
        f"| Max Consecutive Wins | {d.get('max_consecutive_wins', 0)} |",
        f"| Max Consecutive Losses | {d.get('max_consecutive_losses', 0)} |",
        f"| Avg Win | ₹{d.get('avg_win', 0):.2f} |",
        f"| Avg Loss | ₹{d.get('avg_loss', 0):.2f} |",
        f"| Total Closed Trades | {d.get('closed_trades', 0)} |",
    ]
    return "\n".join(lines) + "\n"


# ── 5. System Health Report ───────────────────────────────────────────────────

def gen_system_health(date_str: str) -> dict:
    from phase4a_premarket import run_premarket_checks
    from phase4a_validate import run_validation

    premarket = run_premarket_checks()
    validation = run_validation()

    # Load today's timeline summary
    timeline_summary: dict = {}
    jsonl = os.path.join(_DOCS, f"session_timeline_{date_str.replace('-','')}.jsonl")
    if os.path.exists(jsonl):
        events = []
        with open(jsonl) as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        events.append(json.loads(line))
                    except Exception:
                        pass
        if events:
            lats = [e.get("api_latency_ms") for e in events if e.get("api_latency_ms")]
            mems = [e.get("memory_rss_mb") for e in events if e.get("memory_rss_mb")]
            cpus = [e.get("cpu_pct") for e in events if e.get("cpu_pct")]
            timeline_summary = {
                "ticks": len(events),
                "avg_api_latency_ms": round(sum(lats)/len(lats), 1) if lats else None,
                "max_memory_rss_mb": max(mems) if mems else None,
                "max_cpu_pct": max(cpus) if cpus else None,
            }

    data = {
        "label": LABEL,
        "report_type": "system_health",
        "date": date_str,
        "generated_at": _now_ist(),
        "premarket_overall": premarket.get("overall"),
        "premarket_checks": premarket.get("checks"),
        "validation_production_ready": validation.get("production_ready"),
        "validation_checks": validation.get("invariants"),
        "timeline_summary": timeline_summary,
    }
    md = _md_system_health(data)
    return data, md


def _md_system_health(d: dict) -> str:
    pre_icon = "✅" if d.get("premarket_overall") in ("READY", "READY_WITH_WARNINGS") else "❌"
    val_icon = "✅" if d.get("validation_production_ready") else "❌"
    ts = d.get("timeline_summary") or {}
    lines = [
        f"# System Health Report — {d['date']}",
        "",
        f"**{d['label']}**  ",
        f"Generated: {d['generated_at']}",
        "",
        f"## Pre-Market: {pre_icon} {d.get('premarket_overall', '?')}",
        "",
        "| Check | Verdict |",
        "|-------|---------|",
    ]
    for c in (d.get("premarket_checks") or []):
        icon = "✅" if c["verdict"] == "PASS" else "⚠️" if c["verdict"] == "WARN" else "❌"
        lines.append(f"| {c['name']} | {icon} {c['verdict']} |")
    lines += [
        "",
        f"## Safety Invariants: {val_icon} {'PASS' if d.get('validation_production_ready') else 'FAIL'}",
        "",
        "| Invariant | Verdict |",
        "|-----------|---------|",
    ]
    for i in (d.get("validation_checks") or []):
        icon = "✅" if i["verdict"] == "PASS" else "⚠️" if i["verdict"] == "WARN" else "❌"
        lines.append(f"| {i['invariant']} | {icon} {i['verdict']} |")
    if ts:
        lines += [
            "",
            "## Runtime Metrics",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Monitor ticks | {ts.get('ticks', 0)} |",
            f"| Avg API latency | {ts.get('avg_api_latency_ms')}ms |",
            f"| Max memory RSS | {ts.get('max_memory_rss_mb')}MB |",
            f"| Max CPU | {ts.get('max_cpu_pct')}% |",
        ]
    return "\n".join(lines) + "\n"


# ── 6. AI Report ──────────────────────────────────────────────────────────────

def gen_ai_report(date_str: str) -> dict:
    from phase4a_ai_metrics import compute_ai_metrics
    ai = compute_ai_metrics(date_str)
    data = {"report_type": "ai_report", "date": date_str,
            "generated_at": _now_ist(), **ai}
    md = _md_ai(data)
    return data, md


def _md_ai(d: dict) -> str:
    lines = [
        f"# AI Advisory Report — {d['date']}",
        "",
        f"**{d['label']}**  ",
        f"Generated: {d['generated_at']}  ",
        f"⚠️ AI advisory only — no trade execution by AI",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Signals evaluated | {d.get('signals_evaluated', 0)} |",
        f"| BUY recommendations | {d.get('buy_count', 0)} ({d.get('buy_pct', 0):.1f}%) |",
        f"| WATCH recommendations | {d.get('watch_count', 0)} ({d.get('watch_pct', 0):.1f}%) |",
        f"| NO TRADE recommendations | {d.get('no_trade_count', 0)} ({d.get('no_trade_pct', 0):.1f}%) |",
        f"| False positives | {d.get('false_positives', 0)} |",
        f"| False negatives | {d.get('false_negatives', 0)} |",
        f"| Avg confidence | {d.get('avg_confidence') or 'N/A'}% |",
        f"| Avg explanation latency | {d.get('avg_explanation_latency_ms') or 'N/A'}ms |",
        f"| Agreement with deterministic | {d.get('agreement_rate_pct') or 'N/A'}% |",
    ]
    return "\n".join(lines) + "\n"


# ── 7. Portfolio Report ───────────────────────────────────────────────────────

def gen_portfolio_report(date_str: str) -> dict:
    portfolio: dict = {}
    try:
        import urllib.request
        with urllib.request.urlopen("http://localhost:8080/api/portfolio/snapshot", timeout=6) as r:
            portfolio = json.loads(r.read())
    except Exception:
        pass

    data = {
        "label": LABEL,
        "report_type": "portfolio_report",
        "date": date_str,
        "generated_at": _now_ist(),
        "cash": portfolio.get("cash"),
        "invested_value": portfolio.get("invested_value"),
        "total_equity": portfolio.get("total_equity"),
        "realised_pnl": portfolio.get("realised_pnl"),
        "unrealised_pnl": portfolio.get("unrealised_pnl"),
        "drawdown_pct": portfolio.get("drawdown_pct"),
        "paper_mode": portfolio.get("paper_mode"),
        "positions": portfolio.get("positions", []),
    }
    md = _md_portfolio(data)
    return data, md


def _md_portfolio(d: dict) -> str:
    pm = "✅ PAPER" if d.get("paper_mode") else "⚠️ UNKNOWN"
    lines = [
        f"# Portfolio Report — {d['date']}",
        "",
        f"**{d['label']}**  ",
        f"Generated: {d['generated_at']}  ",
        f"Mode: {pm}",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Cash | ₹{d.get('cash', 0) or 0:.2f} |",
        f"| Invested | ₹{d.get('invested_value', 0) or 0:.2f} |",
        f"| Total Equity | ₹{d.get('total_equity', 0) or 0:.2f} |",
        f"| Realised P&L | ₹{d.get('realised_pnl', 0) or 0:.2f} |",
        f"| Unrealised P&L | ₹{d.get('unrealised_pnl', 0) or 0:.2f} |",
        f"| Drawdown | {d.get('drawdown_pct', 0) or 0:.2f}% |",
        "",
        "## Open Positions",
        "",
        "| Symbol | Qty | Avg Price | Current Price | P&L |",
        "|--------|-----|-----------|---------------|-----|",
    ]
    for pos in d.get("positions", []):
        sym = pos.get("symbol", "?")
        qty = pos.get("quantity", 0)
        avg = pos.get("avg_price", 0)
        cur = pos.get("current_price", avg)
        pnl = (cur - avg) * qty
        lines.append(f"| {sym} | {qty} | ₹{avg:.2f} | ₹{cur:.2f} | ₹{pnl:.2f} |")
    if not d.get("positions"):
        lines.append("| — | No open positions | | | |")
    return "\n".join(lines) + "\n"


# ── Manifest ──────────────────────────────────────────────────────────────────

def write_manifest(rdir: str, date_str: str, generated: list[dict]) -> None:
    manifest = {
        "label": LABEL,
        "date": date_str,
        "generated_at": _now_ist(),
        "reports": generated,
    }
    mpath = os.path.join(rdir, "manifest.json")
    with open(mpath, "w") as f:
        json.dump(manifest, f, indent=2, default=str)
    print(f"\n  Manifest: {mpath}")


# ── Generator dispatch ────────────────────────────────────────────────────────

GENERATORS = {
    "daily_summary": gen_daily_summary,
    "trade_summary": gen_trade_summary,
    "risk_report": gen_risk_report,
    "performance_report": gen_performance_report,
    "system_health": gen_system_health,
    "ai_report": gen_ai_report,
    "portfolio_report": gen_portfolio_report,
}

FILENAMES = {
    "daily_summary": "daily_summary",
    "trade_summary": "trade_summary",
    "risk_report": "risk_report",
    "performance_report": "performance_report",
    "system_health": "system_health",
    "ai_report": "ai_report",
    "portfolio_report": "portfolio_report",
}


def generate(report_type: str, date_str: str) -> Optional[dict]:
    gen = GENERATORS.get(report_type)
    if not gen:
        print(f"  Unknown report type: {report_type}")
        return None
    try:
        data, md = gen(date_str)
        rdir = _reports_dir(date_str)
        fname = FILENAMES[report_type]
        jp, mp = _write(rdir, fname, data, md)
        print(f"  ✅ {report_type}: {jp}")
        return {"type": report_type, "json": jp, "md": mp}
    except Exception as e:
        print(f"  ❌ {report_type}: {e}")
        return {"type": report_type, "error": str(e)}


def generate_all(date_str: str) -> list[dict]:
    print(f"\n{'=' * 60}")
    print(f"  Phase 4A Session Reports — {date_str}")
    print(f"  {LABEL}")
    print(f"{'=' * 60}\n")
    results = []
    for rt in REPORT_TYPES:
        r = generate(rt, date_str)
        if r:
            results.append(r)
    rdir = _reports_dir(date_str)
    write_manifest(rdir, date_str, results)
    print(f"\n  Reports directory: {rdir}")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 4A session reports")
    parser.add_argument("--all", action="store_true", help="Generate all 7 reports")
    parser.add_argument("--type", type=str, choices=REPORT_TYPES,
                        help="Generate a single report type")
    parser.add_argument("--date", type=str, default=None, help="YYYY-MM-DD (default: today)")
    args = parser.parse_args()

    date_str = args.date or datetime.date.today().isoformat()

    if args.all:
        generate_all(date_str)
    elif args.type:
        generate(args.type, date_str)
    else:
        generate_all(date_str)
