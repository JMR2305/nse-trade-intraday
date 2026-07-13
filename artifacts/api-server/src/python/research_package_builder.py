"""
research_package_builder.py — Research Package & ChatGPT Report Generator.
v1.0

Assembles a timestamped research package (ZIP) and a standalone ChatGPT-ready
markdown briefing from all available analysis results.

Package structure:
  research_package_YYYYMMDD_HHMMSS.zip
  ├── README.md
  ├── executive_summary.md
  ├── chatgpt_report.md
  ├── metadata/
  │   ├── run_metadata.json
  │   └── config_snapshot.json
  ├── reports/
  │   ├── wf_report.csv
  │   ├── wf_windows.csv
  │   └── wf_evidence_report.csv
  ├── trades/
  │   ├── wf_trades.csv
  │   └── wf_evidence_trades.csv
  ├── calibration/
  │   └── wf_calibration.csv
  ├── costs/
  │   └── wf_costs.csv
  └── configuration/
      └── parameters.json

READ-ONLY — never modifies live trading state, portfolio, decisions, or any
running model. Only reads existing result files.

Paper trading and research only — no real orders are placed.
"""
from __future__ import annotations

import json
import os
import subprocess
import zipfile
from datetime import datetime

PYTHON_DIR = os.path.dirname(os.path.abspath(__file__))
VALIDATION_DIR = os.path.join(PYTHON_DIR, "validation_runs")
PACKAGES_DIR = os.path.join(PYTHON_DIR, "research_packages")
BASELINE_PATH = os.path.join(PACKAGES_DIR, "research_baseline.json")
LATEST_JSON_PATH = os.path.join(PACKAGES_DIR, "latest_package.json")
LATEST_CHATGPT_PATH = os.path.join(PACKAGES_DIR, "latest_chatgpt_report.md")

SAFETY_NOTE = (
    "Out-of-sample historical performance does not guarantee future results. "
    "Paper trading and research only. No real orders are placed."
)

KNOWN_LIMITATIONS = [
    "Only 50 NIFTY stocks tested — no mid/small-cap coverage.",
    "Daily candles only — intraday gaps and liquidity are approximated.",
    "Backfill survivorship bias possible if a stock left NIFTY 50 during test period.",
    "Short positions are not supported (long-only system).",
    "Capital limit ₹5,000 constrains position sizing and diversification.",
    "Confidence calibration re-fits per window but requires ≥10 prior completed trades.",
    "SEBI/GST/STT rates are hardcoded — changes in tax law are not auto-updated.",
    "Slippage and spread are estimated; actual market-impact costs may differ.",
    "Adaptive model weights are version-pinned for the whole run — no intra-run updates.",
    "Phase 3A.5 evidence targets 300+ OOS trades for PASS; small-window runs are INCONCLUSIVE.",
]

# ── Data loading helpers ──────────────────────────────────────────────────────

def _load_wf_result() -> dict | None:
    p = os.path.join(VALIDATION_DIR, "wf_result.json")
    if not os.path.exists(p):
        return None
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return None


def _csv_exists(filename: str) -> bool:
    return os.path.exists(os.path.join(VALIDATION_DIR, filename))


def _get_git_commit() -> dict:
    try:
        out = subprocess.check_output(
            ["git", "log", "-1", "--format=%H|%s|%ai"],
            cwd=PYTHON_DIR,
            stderr=subprocess.DEVNULL,
            timeout=5,
        ).decode().strip()
        parts = out.split("|", 2)
        return {
            "hash": parts[0][:12] if parts else "unavailable",
            "message": parts[1] if len(parts) > 1 else "",
            "date": parts[2] if len(parts) > 2 else "",
        }
    except Exception:
        return {"hash": "unavailable", "message": "", "date": ""}


def _load_baseline() -> dict | None:
    if not os.path.exists(BASELINE_PATH):
        return None
    try:
        with open(BASELINE_PATH) as f:
            return json.load(f)
    except Exception:
        return None


def _save_baseline(metrics: dict) -> None:
    os.makedirs(PACKAGES_DIR, exist_ok=True)
    try:
        with open(BASELINE_PATH, "w") as f:
            json.dump(metrics, f, indent=2)
    except Exception:
        pass


def _safe(val, default="—"):
    return val if val not in (None, "", "nan") else default


def _f(v, d: int = 2) -> str:
    try:
        return f"{float(v):.{d}f}"
    except Exception:
        return "—"


def _pct(v) -> str:
    try:
        return f"{float(v):.2f}%"
    except Exception:
        return "—"


def _inr(v) -> str:
    try:
        return f"₹{float(v):,.0f}"
    except Exception:
        return "—"


# ── Metric extraction ─────────────────────────────────────────────────────────

def _extract_metrics(wf: dict | None) -> dict:
    """Pull out the key headline numbers from wf_result.json."""
    if not wf:
        return {}
    overall = wf.get("overall") or {}
    full = overall.get("full_metrics") or {}
    base = overall.get("base_metrics") or {}
    gated = overall.get("gated_metrics") or {}
    verdict = (wf.get("verdict") or {})
    calib_report = (wf.get("calibration_report") or {})
    ev_exp = (wf.get("evidence_expansion") or {})
    stab = (wf.get("stability") or {})
    bench = (wf.get("benchmarks") or {})
    return {
        "generated_at": wf.get("generated_at", ""),
        "run_seconds": wf.get("run_seconds", ""),
        "windows": len([w for w in (wf.get("windows") or []) if not w.get("failed")]),
        "universe_size": wf.get("universe_size", ""),
        "adaptive_model_version": wf.get("adaptive_model_version", ""),
        "knowledge_trades": wf.get("knowledge_trades_available", ""),
        # Full model
        "full_trades": full.get("total_trades"),
        "full_return_pct": full.get("total_return_pct"),
        "full_win_rate": full.get("win_rate"),
        "full_expectancy": full.get("expectancy"),
        "full_profit_factor": full.get("profit_factor"),
        "full_sharpe": full.get("sharpe_ratio"),
        "full_drawdown": full.get("max_drawdown_pct"),
        "full_net_pnl": full.get("net_profit"),
        # Base model
        "base_trades": base.get("total_trades"),
        "base_return_pct": base.get("total_return_pct"),
        "base_win_rate": base.get("win_rate"),
        # Gated model
        "gated_trades": gated.get("total_trades"),
        "gated_return_pct": gated.get("total_return_pct"),
        "gated_win_rate": gated.get("win_rate"),
        # Verdict
        "verdict": verdict.get("verdict"),
        "verdict_summary": verdict.get("summary"),
        # Calibration
        "brier_score": calib_report.get("brier_score"),
        "ece": calib_report.get("ece"),
        "log_loss": calib_report.get("log_loss"),
        # Evidence expansion
        "ev_verdict": (ev_exp.get("verdict") or {}).get("verdict"),
        "ev_trades": ev_exp.get("n_trades"),
        "ev_windows": ev_exp.get("n_windows"),
        "ev_expectancy": ev_exp.get("expectancy_per_trade"),
        # Stability
        "profitable_windows_pct": stab.get("profitable_windows_pct"),
        "concentration_flags": len(stab.get("concentration_flags") or []),
        # Benchmarks
        "nifty_bh_pct": bench.get("nifty_buy_hold_pct"),
        "full_model_bench_pct": bench.get("full_model_pct"),
    }


def _diff_metrics(current: dict, baseline: dict | None) -> dict:
    """Produce a before/after comparison table."""
    if not baseline:
        return {}
    diffs = {}
    for k in ("full_return_pct", "full_win_rate", "full_expectancy",
               "full_sharpe", "full_drawdown", "full_net_pnl",
               "brier_score", "ece", "full_profit_factor", "ev_trades"):
        cv = current.get(k)
        bv = baseline.get(k)
        if cv is None or bv is None:
            continue
        try:
            diffs[k] = {"before": bv, "after": cv, "delta": float(cv) - float(bv)}
        except Exception:
            pass
    return diffs


# ── README ────────────────────────────────────────────────────────────────────

def _build_readme() -> str:
    return """\
# NSE Trading Research Package

This package contains all research outputs from one validation run of the
NSE Algorithmic Paper Trading system.

## Contents

| Path | Description |
|------|-------------|
| `executive_summary.md` | High-level narrative summary — start here |
| `chatgpt_report.md` | Upload this single file to ChatGPT instead of screenshots |
| `metadata/run_metadata.json` | Timestamp, git commit, random seed, model version |
| `metadata/config_snapshot.json` | Full ValidationConfig parameters |
| `reports/wf_report.csv` | Overall walk-forward summary |
| `reports/wf_windows.csv` | Per-window metrics for all model variants |
| `reports/wf_evidence_report.csv` | Phase 3A.5 evidence expansion report |
| `trades/wf_trades.csv` | Every simulated OOS trade (full model) |
| `trades/wf_evidence_trades.csv` | OOS trades tagged with Phase 3A.5 metadata |
| `calibration/wf_calibration.csv` | Confidence calibration reliability bands |
| `costs/wf_costs.csv` | Execution cost breakdown |
| `configuration/parameters.json` | Run parameters and cost model |

## Reproducibility

All results are deterministic given the same config and random seed.
The `metadata/run_metadata.json` file contains everything needed to reproduce the run.

## Safety

{safety}
""".format(safety=SAFETY_NOTE)


# ── Executive Summary ─────────────────────────────────────────────────────────

def _build_executive_summary(wf: dict | None, m: dict, git: dict, ts: str) -> str:
    verdict_emoji = {"PASS": "✅", "INCONCLUSIVE": "⚠️", "FAIL": "❌",
                     "INSUFFICIENT_DATA": "⚠️"}.get(str(m.get("verdict", "")), "❓")
    ev_emoji = {"PASS": "✅", "INCONCLUSIVE": "⚠️", "FAIL": "❌",
                "INSUFFICIENT_EVIDENCE": "⚠️"}.get(str(m.get("ev_verdict", "")), "❓")

    lines = [
        "# NSE Algorithmic Trading — Executive Summary",
        "",
        f"**Generated:** {ts}  ",
        f"**Git Commit:** `{git['hash']}` — {git.get('message', '')}  ",
        f"**System:** Paper trading, research only · ₹5,000 capital · NIFTY 50 universe",
        "",
        "---",
        "",
        "## Overall Verdict",
        "",
    ]

    if not wf:
        lines += [
            "> ⚠️ No walk-forward validation result found.",
            "> Run a validation to populate this section.",
            "",
        ]
    else:
        lines += [
            f"**Walk-Forward Verdict:** {verdict_emoji} **{m.get('verdict', '—')}**  ",
            f"**Evidence Expansion (3A.5):** {ev_emoji} **{m.get('ev_verdict', '—')}**  ",
            "",
            f"> {m.get('verdict_summary', '')}",
            "",
        ]

    # Performance table
    lines += [
        "## Key Performance Metrics (Full Model — Variant C)",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| OOS Trades | {_safe(m.get('full_trades'))} |",
        f"| Total Return | {_pct(m.get('full_return_pct'))} |",
        f"| Net P&L | {_inr(m.get('full_net_pnl'))} |",
        f"| Win Rate | {_pct(m.get('full_win_rate'))} |",
        f"| Profit Factor | {_f(m.get('full_profit_factor'))} |",
        f"| Expectancy | {_inr(m.get('full_expectancy'))} / trade |",
        f"| Sharpe Ratio | {_f(m.get('full_sharpe'))} |",
        f"| Max Drawdown | {_pct(m.get('full_drawdown'))} |",
        "",
    ]

    # Model comparison
    lines += [
        "## Model Comparison",
        "",
        "| Model | Trades | Return | Win Rate |",
        "|-------|--------|--------|----------|",
        f"| A — Base Technical | {_safe(m.get('base_trades'))} | {_pct(m.get('base_return_pct'))} | {_pct(m.get('base_win_rate'))} |",
        f"| C — Full Model | {_safe(m.get('full_trades'))} | {_pct(m.get('full_return_pct'))} | {_pct(m.get('full_win_rate'))} |",
        f"| D — Gated Model | {_safe(m.get('gated_trades'))} | {_pct(m.get('gated_return_pct'))} | {_pct(m.get('gated_win_rate'))} |",
        "",
    ]

    # Benchmarks
    lines += [
        "## Benchmarks",
        "",
        "| Benchmark | Return |",
        "|-----------|--------|",
        f"| Full Model (compounded) | {_pct(m.get('full_model_bench_pct'))} |",
        f"| NIFTY 50 Buy & Hold | {_pct(m.get('nifty_bh_pct'))} |",
        "",
    ]

    # Calibration
    lines += [
        "## Confidence Calibration",
        "",
        "| Metric | Value |",
        "|--------|-------|",
        f"| Brier Score | {_f(m.get('brier_score'), 4)} |",
        f"| ECE | {_f(m.get('ece'), 4)} |",
        f"| Log Loss | {_f(m.get('log_loss'), 4)} |",
        "",
    ]

    # Evidence expansion
    lines += [
        "## Phase 3A.5 — Evidence Expansion",
        "",
        f"| Metric | Value |",
        "|--------|-------|",
        f"| Verdict | {m.get('ev_verdict', '—')} |",
        f"| OOS Trades | {_safe(m.get('ev_trades'))} (target: ≥300) |",
        f"| Windows | {_safe(m.get('ev_windows'))} (target: ≥8) |",
        f"| Expectancy/Trade | {_inr(m.get('ev_expectancy'))} |",
        "",
    ]

    # Stability summary
    if wf:
        stab = wf.get("stability") or {}
        lines += [
            "## Stability",
            "",
            f"| Metric | Value |",
            "|--------|-------|",
            f"| Profitable Windows | {_pct(stab.get('profitable_windows_pct'))} |",
            f"| Concentration Flags | {len(stab.get('concentration_flags') or [])} |",
            "",
        ]

    # Regime breakdown from evidence expansion
    if wf:
        ev = wf.get("evidence_expansion") or {}
        rc = (ev.get("regime_coverage") or {}).get("by_regime") or []
        if rc:
            lines += [
                "## Performance by Market Regime",
                "",
                "| Regime | Trades | % of Total | Under-Represented |",
                "|--------|--------|------------|-------------------|",
            ]
            for r in rc:
                lines.append(
                    f"| {r.get('regime', '—')} | {r.get('trades', 0)} "
                    f"| {r.get('pct_of_total', 0):.1f}% "
                    f"| {'⚠️' if r.get('underrepresented') else '—'} |"
                )
            lines.append("")

        # Strategy distribution
        by_strat = ev.get("by_strategy") or []
        if by_strat:
            lines += [
                "## Performance by Strategy",
                "",
                "| Strategy | Trades | Net P&L | Win Rate | Expectancy |",
                "|----------|--------|---------|----------|------------|",
            ]
            for s in by_strat:
                lines.append(
                    f"| {s.get('group', '—')} | {s.get('trades', 0)} "
                    f"| {_inr(s.get('net_pnl'))} "
                    f"| {_pct(s.get('win_rate'))} "
                    f"| {_inr(s.get('expectancy'))} |"
                )
            lines.append("")

        # Sector distribution
        by_sector = ev.get("by_sector") or []
        if by_sector:
            lines += [
                "## Performance by Sector",
                "",
                "| Sector | Trades | Net P&L | Win Rate |",
                "|--------|--------|---------|----------|",
            ]
            for s in by_sector[:10]:
                lines.append(
                    f"| {s.get('group', '—')} | {s.get('trades', 0)} "
                    f"| {_inr(s.get('net_pnl'))} "
                    f"| {_pct(s.get('win_rate'))} |"
                )
            lines.append("")

    # Known limitations
    lines += [
        "## Known Limitations",
        "",
    ]
    for lim in KNOWN_LIMITATIONS:
        lines.append(f"- {lim}")
    lines.append("")

    # Run metadata
    lines += [
        "## Run Metadata",
        "",
        f"| Field | Value |",
        "|-------|-------|",
        f"| Generated | {ts} |",
        f"| Git Commit | `{git['hash']}` |",
        f"| Model Version | {_safe(m.get('adaptive_model_version'))} |",
        f"| Universe | {_safe(m.get('universe_size'))} stocks |",
        f"| Knowledge Trades | {_safe(m.get('knowledge_trades'))} |",
        f"| Run Duration | {_f(m.get('run_seconds'), 1)}s |",
        "",
        f"---",
        "",
        f"*{SAFETY_NOTE}*",
    ]

    return "\n".join(lines)


# ── ChatGPT Report ────────────────────────────────────────────────────────────

def _build_chatgpt_report(
    wf: dict | None,
    m: dict,
    git: dict,
    ts: str,
    diffs: dict,
) -> str:
    """
    Generates a self-contained markdown briefing for ChatGPT.
    Upload this single file instead of 15 screenshots.
    """
    lines = [
        "# NSE Trading System — ChatGPT Research Briefing",
        "",
        "*Upload this single file to ChatGPT for a full system briefing.*",
        "",
        "---",
        "",
        "## System Context",
        "",
        "```",
        "System:    NSE Algorithmic Paper Trading (research only)",
        "Capital:   ₹5,000",
        "Universe:  NIFTY 50 (50 stocks)",
        "Style:     Long-only, daily candles",
        "No real money — paper trading simulation only",
        "```",
        "",
        f"**Report date:** {ts}  ",
        f"**Git commit:** `{git['hash']}` — {git.get('message', '')}  ",
        f"**Model version:** {_safe(m.get('adaptive_model_version'))}",
        "",
        "---",
        "",
        "## What This System Does",
        "",
        "- Scans all 50 NIFTY stocks daily using a rule-based + ML-enhanced decision engine",
        "- Generates BUY/WATCH/AVOID recommendations with confidence scores",
        "- Runs walk-forward validation: rolling train→test windows on historical data",
        "  (training never sees test data; no lookahead)",
        "- 5 model variants compared: base technical (A), pattern+similarity (B),",
        "  full model (C), gated (D), strict-gate (E)",
        "- Calibration re-fits per window using only prior completed trades",
        "- Phase 3A.5 assesses evidence quality (target: 300+ OOS trades, 8+ windows)",
        "",
    ]

    # Walk-forward results section
    if not wf:
        lines += [
            "## Walk-Forward Validation Results",
            "",
            "> No validation result available. Run a walk-forward validation first.",
            "",
        ]
    else:
        verdict = m.get("verdict", "—")
        ev_verdict = m.get("ev_verdict", "—")
        lines += [
            "## Walk-Forward Validation Results",
            "",
            f"**Overall Verdict:** {verdict}",
            f"**Evidence Quality (3A.5):** {ev_verdict}",
            "",
            f"> {m.get('verdict_summary', '')}",
            "",
            "### Full Model Performance (Variant C)",
            "",
            "```",
            f"OOS Trades:       {_safe(m.get('full_trades'))}",
            f"Windows:          {_safe(m.get('windows'))}",
            f"Total Return:     {_pct(m.get('full_return_pct'))}",
            f"Net P&L:          {_inr(m.get('full_net_pnl'))}",
            f"Win Rate:         {_pct(m.get('full_win_rate'))}",
            f"Profit Factor:    {_f(m.get('full_profit_factor'))}",
            f"Expectancy:       {_inr(m.get('full_expectancy'))}/trade",
            f"Sharpe Ratio:     {_f(m.get('full_sharpe'))}",
            f"Max Drawdown:     {_pct(m.get('full_drawdown'))}",
            "```",
            "",
            "### Benchmarks",
            "",
            f"- Full model compounded: {_pct(m.get('full_model_bench_pct'))}",
            f"- NIFTY 50 buy & hold:  {_pct(m.get('nifty_bh_pct'))}",
            "",
            "### Confidence Calibration",
            "",
            "```",
            f"Brier Score:  {_f(m.get('brier_score'), 4)}  (lower = better, perfect = 0)",
            f"ECE:          {_f(m.get('ece'), 4)}  (lower = better, perfect = 0)",
            f"Log Loss:     {_f(m.get('log_loss'), 4)}  (lower = better)",
            "```",
            "",
        ]

        # Evidence expansion
        ev = wf.get("evidence_expansion") or {}
        ev_stab = ev.get("stability") or {}
        lines += [
            "### Phase 3A.5 Evidence Expansion",
            "",
            "```",
            f"Verdict:              {ev_verdict}",
            f"OOS Trades:           {_safe(m.get('ev_trades'))} / 300 target",
            f"Windows:              {_safe(m.get('ev_windows'))} / 8 target",
            f"Expectancy/trade:     {_inr(m.get('ev_expectancy'))}",
            f"Profitable windows:   {_safe(ev_stab.get('profitable_windows_pct'))}%",
            f"Median return:        {_pct(ev_stab.get('median_return_pct'))}",
            f"Return dispersion:    {_pct(ev_stab.get('return_dispersion'))}",
            "```",
            "",
        ]

        # Regime coverage
        rc = (ev.get("regime_coverage") or {}).get("by_regime") or []
        if rc:
            lines += ["### Market Regime Coverage", ""]
            lines += ["| Regime | Trades | % |"]
            lines += ["|--------|--------|---|"]
            for r in rc:
                flag = " ⚠️" if r.get("underrepresented") else ""
                lines.append(
                    f"| {r.get('regime')} | {r.get('trades')} "
                    f"| {r.get('pct_of_total')}%{flag} |"
                )
            lines.append("")

        # Strategy distribution
        by_strat = ev.get("by_strategy") or []
        if by_strat:
            lines += ["### Strategy Breakdown", ""]
            lines += ["| Strategy | Trades | Net P&L | Win% | Expect. |"]
            lines += ["|----------|--------|---------|------|---------|"]
            for s in by_strat:
                lines.append(
                    f"| {s.get('group')} | {s.get('trades')} "
                    f"| {_inr(s.get('net_pnl'))} "
                    f"| {_pct(s.get('win_rate'))} "
                    f"| {_inr(s.get('expectancy'))} |"
                )
            lines.append("")

        # Sector distribution
        by_sector = ev.get("by_sector") or []
        if by_sector:
            lines += ["### Sector Breakdown (top 10)", ""]
            lines += ["| Sector | Trades | Net P&L | Win% |"]
            lines += ["|--------|--------|---------|------|"]
            for s in by_sector[:10]:
                lines.append(
                    f"| {s.get('group')} | {s.get('trades')} "
                    f"| {_inr(s.get('net_pnl'))} "
                    f"| {_pct(s.get('win_rate'))} |"
                )
            lines.append("")

        # Concentration warnings
        conc = ev.get("concentration_flags") or []
        stab_wf = wf.get("stability") or {}
        conc_wf = stab_wf.get("concentration_flags") or []
        all_conc = list(conc_wf) + [c for c in conc if c not in conc_wf]
        if all_conc:
            lines += ["### ⚠️ Concentration Warnings", ""]
            for c in all_conc:
                lines.append(f"- {c}")
            lines.append("")

        # Per-window breakdown
        windows = wf.get("windows") or []
        if windows:
            lines += ["### Walk-Forward Windows", ""]
            lines += ["| Window | Test Period | Trades | Return | PF |"]
            lines += ["|--------|-------------|--------|--------|----|"]
            for w in windows:
                if w.get("failed"):
                    lines.append(
                        f"| {w.get('label')} | {w.get('test_start')}–{w.get('test_end')} "
                        f"| FAILED: {w.get('failure_reason', '')} | — | — |"
                    )
                else:
                    fm = (w.get("full_metrics") or {})
                    lines.append(
                        f"| {w.get('label')} | {w.get('test_start')}–{w.get('test_end')} "
                        f"| {_safe(fm.get('total_trades'))} "
                        f"| {_pct(fm.get('total_return_pct'))} "
                        f"| {_f(fm.get('profit_factor'))} |"
                    )
            lines.append("")

    # Before/After comparison
    if diffs:
        lines += [
            "## Before vs After (vs Previous Package)",
            "",
            "| Metric | Before | After | Change |",
            "|--------|--------|-------|--------|",
        ]
        metric_labels = {
            "full_return_pct": "Full Model Return %",
            "full_win_rate": "Win Rate %",
            "full_expectancy": "Expectancy (₹)",
            "full_sharpe": "Sharpe Ratio",
            "full_drawdown": "Max Drawdown %",
            "full_net_pnl": "Net P&L (₹)",
            "brier_score": "Brier Score",
            "ece": "ECE",
            "full_profit_factor": "Profit Factor",
            "ev_trades": "Evidence Trades",
        }
        for k, label in metric_labels.items():
            if k not in diffs:
                continue
            d = diffs[k]
            delta = d["delta"]
            arrow = "▲" if delta > 0 else ("▼" if delta < 0 else "=")
            lines.append(
                f"| {label} | {_f(d['before'])} | {_f(d['after'])} "
                f"| {arrow} {abs(delta):.2f} |"
            )
        lines.append("")
    else:
        lines += [
            "## Before vs After",
            "",
            "_No previous research package baseline found. "
            "A baseline will be saved from this run for future comparison._",
            "",
        ]

    # Config snapshot
    if wf:
        cfg = wf.get("config") or {}
        lines += [
            "## Configuration Snapshot",
            "",
            "```json",
            json.dumps(cfg, indent=2, default=str),
            "```",
            "",
        ]

    # Known limitations
    lines += [
        "## Known Limitations",
        "",
    ]
    for lim in KNOWN_LIMITATIONS:
        lines.append(f"- {lim}")
    lines.append("")

    # Live behaviour impact
    lines += [
        "## Live Behaviour Change?",
        "",
        "**No.** This package contains analysis-only results. No live paper-trading",
        "recommendations, strategy rankings, portfolio positions, or thresholds were",
        "changed by generating this report. All Phase 3A/3A.5 sections are shadow",
        "models — they observe but never influence execution.",
        "",
    ]

    # What to ask ChatGPT
    lines += [
        "## Suggested Questions for ChatGPT",
        "",
        "1. Looking at the walk-forward results above, what is your assessment",
        "   of this strategy's edge? Is the evidence statistically meaningful?",
        "2. The evidence expansion shows ____ OOS trades across ____ windows.",
        "   What are the risks of making conclusions from this evidence set?",
        "3. Which market regime is most profitable/risky based on the breakdown above?",
        "4. The profit factor is ____. Is that robust enough for a long-only system",
        "   with a ₹5,000 capital limit?",
        "5. Based on the concentration warnings above, how should I diversify?",
        "6. The calibration ECE is ____. Is that good? What does it mean practically?",
        "7. What would be a reasonable next step to improve evidence quality?",
        "",
        "---",
        "",
        f"*{SAFETY_NOTE}*",
    ]

    return "\n".join(lines)


# ── Configuration snapshot ────────────────────────────────────────────────────

def _build_parameters(wf: dict | None, git: dict, ts: str) -> dict:
    cfg = {}
    if wf:
        cfg = wf.get("config") or {}
    return {
        "generated_at": ts,
        "git_commit": git,
        "config": cfg,
        "adaptive_model_version": (wf or {}).get("adaptive_model_version"),
        "intrabar_rule_label": (wf or {}).get("intrabar_rule_label"),
        "universe_size": (wf or {}).get("universe_size"),
        "known_limitations": KNOWN_LIMITATIONS,
        "safety": SAFETY_NOTE,
    }


# ── ZIP assembly ──────────────────────────────────────────────────────────────

def _add_str(zf: zipfile.ZipFile, arcname: str, content: str) -> None:
    zf.writestr(arcname, content.encode("utf-8"))


def _add_file_if_exists(zf: zipfile.ZipFile, src: str, arcname: str) -> bool:
    if os.path.exists(src):
        zf.write(src, arcname)
        return True
    return False


def _build_zip(wf: dict | None, m: dict, git: dict, ts: str, diffs: dict) -> str:
    """Build the full research package ZIP and return its path."""
    os.makedirs(PACKAGES_DIR, exist_ok=True)
    slug = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_name = f"research_package_{slug}.zip"
    zip_path = os.path.join(PACKAGES_DIR, zip_name)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Top-level files
        _add_str(zf, "README.md", _build_readme())
        _add_str(zf, "executive_summary.md",
                 _build_executive_summary(wf, m, git, ts))
        chatgpt_md = _build_chatgpt_report(wf, m, git, ts, diffs)
        _add_str(zf, "chatgpt_report.md", chatgpt_md)

        # metadata/
        meta = {
            "generated_at": ts,
            "git_commit": git,
            "adaptive_model_version": m.get("adaptive_model_version"),
            "validation_generated_at": m.get("generated_at"),
            "run_seconds": m.get("run_seconds"),
            "universe_size": m.get("universe_size"),
            "knowledge_trades_available": m.get("knowledge_trades"),
            "random_seed": (wf or {}).get("config", {}).get("random_seed"),
            "safety": SAFETY_NOTE,
        }
        _add_str(zf, "metadata/run_metadata.json", json.dumps(meta, indent=2))
        _add_str(zf, "metadata/config_snapshot.json",
                 json.dumps(_build_parameters(wf, git, ts), indent=2))

        # reports/
        for src_name, arc_name in [
            ("wf_report.csv", "reports/wf_report.csv"),
            ("wf_windows.csv", "reports/wf_windows.csv"),
            ("wf_evidence_report.csv", "reports/wf_evidence_report.csv"),
        ]:
            _add_file_if_exists(zf,
                os.path.join(VALIDATION_DIR, src_name), arc_name)

        # trades/
        for src_name, arc_name in [
            ("wf_trades.csv", "trades/wf_trades.csv"),
            ("wf_evidence_trades.csv", "trades/wf_evidence_trades.csv"),
        ]:
            _add_file_if_exists(zf,
                os.path.join(VALIDATION_DIR, src_name), arc_name)

        # calibration/
        _add_file_if_exists(zf,
            os.path.join(VALIDATION_DIR, "wf_calibration.csv"),
            "calibration/wf_calibration.csv")

        # costs/
        _add_file_if_exists(zf,
            os.path.join(VALIDATION_DIR, "wf_costs.csv"),
            "costs/wf_costs.csv")

        # configuration/
        _add_str(zf, "configuration/parameters.json",
                 json.dumps(_build_parameters(wf, git, ts), indent=2))

    return zip_path, chatgpt_md


# ── Entry points ──────────────────────────────────────────────────────────────

def generate_research_package() -> dict:
    """
    Build the full timestamped research package ZIP.
    Returns JSON-serialisable metadata about the generated package.
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    git = _get_git_commit()
    wf = _load_wf_result()
    m = _extract_metrics(wf)

    # Before/after comparison
    baseline = _load_baseline()
    diffs = _diff_metrics(m, baseline)

    # Build ZIP
    zip_path, chatgpt_md = _build_zip(wf, m, git, ts, diffs)
    size_kb = round(os.path.getsize(zip_path) / 1024.0, 1)

    # Save ChatGPT report separately for quick download
    os.makedirs(PACKAGES_DIR, exist_ok=True)
    with open(LATEST_CHATGPT_PATH, "w", encoding="utf-8") as f:
        f.write(chatgpt_md)

    # Save metadata for download route
    info = {
        "generated_at": ts,
        "zip_path": zip_path,
        "zip_filename": os.path.basename(zip_path),
        "size_kb": size_kb,
        "chatgpt_report_path": LATEST_CHATGPT_PATH,
        "validation_available": wf is not None,
        "verdict": m.get("verdict"),
        "ev_verdict": m.get("ev_verdict"),
        "git_commit": git["hash"],
    }
    with open(LATEST_JSON_PATH, "w") as f:
        json.dump(info, f, indent=2)

    # Update baseline for next comparison
    _save_baseline(m)

    return {
        "ok": True,
        "filename": os.path.basename(zip_path),
        "size_kb": size_kb,
        "generated_at": ts,
        "git_commit": git["hash"],
        "verdict": m.get("verdict"),
        "ev_verdict": m.get("ev_verdict"),
        "validation_available": wf is not None,
        "has_previous_baseline": baseline is not None,
        "safety": SAFETY_NOTE,
    }


def generate_chatgpt_report() -> dict:
    """
    Generate only the ChatGPT markdown report (fast path, no ZIP).
    Returns metadata; the file is written to LATEST_CHATGPT_PATH.
    """
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    git = _get_git_commit()
    wf = _load_wf_result()
    m = _extract_metrics(wf)
    baseline = _load_baseline()
    diffs = _diff_metrics(m, baseline)

    md = _build_chatgpt_report(wf, m, git, ts, diffs)
    os.makedirs(PACKAGES_DIR, exist_ok=True)
    with open(LATEST_CHATGPT_PATH, "w", encoding="utf-8") as f:
        f.write(md)

    size_kb = round(len(md.encode("utf-8")) / 1024.0, 1)
    return {
        "ok": True,
        "size_kb": size_kb,
        "generated_at": ts,
        "git_commit": git["hash"],
        "validation_available": wf is not None,
        "safety": SAFETY_NOTE,
    }


def get_latest_package_path() -> str | None:
    if not os.path.exists(LATEST_JSON_PATH):
        return None
    try:
        with open(LATEST_JSON_PATH) as f:
            info = json.load(f)
        p = info.get("zip_path")
        return p if p and os.path.exists(p) else None
    except Exception:
        return None


def get_latest_chatgpt_path() -> str | None:
    return LATEST_CHATGPT_PATH if os.path.exists(LATEST_CHATGPT_PATH) else None
