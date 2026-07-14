"""
Phase 4.3 — Research report exports: printable HTML and CSV ZIP.

Research-only. Reads the persisted report JSON produced by report_engine and
renders self-contained outputs (no external assets, no JavaScript required).
"""

import csv
import html
import io
import json
import os
import zipfile

from report_engine import DISCLAIMER, get_report


def _na(v):
    if v is None or v == "" or (isinstance(v, float) and v != v):
        return "N/A"
    return v


def _esc(v):
    return html.escape(str(_na(v)))


# ── CSV ZIP ──────────────────────────────────────────────────────────────────

def _rows_to_csv(rows, fieldnames=None):
    buf = io.StringIO()
    if not rows:
        buf.write("no_data\n")
        return buf.getvalue()
    if fieldnames is None:
        fieldnames = []
        for r in rows:
            for k in r.keys():
                if k not in fieldnames:
                    fieldnames.append(k)
    w = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow({k: _na(_flat(v)) for k, v in r.items() if k in fieldnames})
    return buf.getvalue()


def _flat(v):
    if isinstance(v, (dict, list)):
        return json.dumps(v, default=str)
    return v


def _kv_csv(d, prefix=""):
    rows = []
    for k, v in (d or {}).items():
        if isinstance(v, dict):
            rows.extend(_kv_csv(v, prefix=f"{prefix}{k}."))
        elif isinstance(v, list):
            rows.append({"metric": prefix + k, "value": json.dumps(v, default=str)[:500]})
        else:
            rows.append({"metric": prefix + k, "value": _na(v)})
    return rows


def export_csv_zip(exp_dir, out_path=None):
    got = get_report(exp_dir)
    if not got.get("success"):
        return got
    rep = got["report"]
    exp_id = rep.get("experiment_id")
    if out_path is None:
        out_path = os.path.join(exp_dir, "reports",
                                f"report_v{rep.get('report_version')}_csv.zip")
    dist = (rep.get("trade_distribution") or {}).get("tables") or {}
    files = {
        "summary.csv": _rows_to_csv(_kv_csv(rep.get("executive_summary")),
                                    ["metric", "value"]),
        "performance.csv": _rows_to_csv(_kv_csv(rep.get("performance_analysis")),
                                        ["metric", "value"]),
        "risk.csv": _rows_to_csv(_kv_csv(rep.get("risk_analysis")), ["metric", "value"]),
        "windows.csv": _rows_to_csv((rep.get("performance_analysis") or {}).get("windows") or []),
        "strategies.csv": _rows_to_csv(dist.get("by_strategy") or []),
        "stocks.csv": _rows_to_csv(dist.get("by_stock") or []),
        "sectors.csv": _rows_to_csv(dist.get("by_sector") or []),
        "regimes.csv": _rows_to_csv((rep.get("regime_analysis") or {}).get("tables") or []),
        "confidence_bands.csv": _rows_to_csv(dist.get("by_confidence_band") or []),
        "false_positives.csv": _rows_to_csv((rep.get("false_positive_analysis") or {}).get("subgroup_rates") or []),
        "missed_opportunities.csv": _rows_to_csv((rep.get("missed_opportunity_analysis") or {}).get("categories") or []),
        "features.csv": _rows_to_csv([
            {k: v for k, v in f.items() if k != "bins"}
            for f in (rep.get("feature_analysis") or {}).get("features") or []]),
        "holding_periods.csv": _rows_to_csv([
            {k: v for k, v in t.items() if k != "exit_reasons"}
            for t in (rep.get("holding_period_analysis") or {}).get("tables") or []]),
        "drawdowns.csv": _rows_to_csv([
            {k: v for k, v in e.items() if k != "main_loss_contributors"}
            for e in (rep.get("drawdown_analysis") or {}).get("episodes") or []]),
        "best_trades.csv": _rows_to_csv((rep.get("trade_examples") or {}).get("top_winners") or []),
        "worst_trades.csv": _rows_to_csv((rep.get("trade_examples") or {}).get("top_losers") or []),
        "recommendations.csv": _rows_to_csv(rep.get("recommendations") or []),
        "next_experiments.csv": _rows_to_csv([
            {k: _flat(v) for k, v in s.items()}
            for s in (rep.get("next_experiments") or {}).get("suggestions") or []]),
        "trades.csv": None,  # filled below from source file
        "README.txt": (f"Research report CSV export\nExperiment: {exp_id}\n"
                       f"Report version: {rep.get('report_version')}\n"
                       f"Generated: {rep.get('generated_at')}\n\n{DISCLAIMER}\n"),
    }
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, content in files.items():
            if name == "trades.csv":
                src = os.path.join(exp_dir, "wf_trades.csv")
                if os.path.exists(src):
                    z.write(src, "trades.csv")
                continue
            z.writestr(name, content)
    return {"success": True, "path": out_path}


# ── printable HTML ───────────────────────────────────────────────────────────

_CSS = """
body{font-family:Georgia,'Times New Roman',serif;margin:2rem auto;max-width:960px;
     color:#1a202c;line-height:1.5;padding:0 1rem}
h1{font-size:1.6rem;border-bottom:3px solid #1a202c;padding-bottom:.4rem}
h2{font-size:1.2rem;margin-top:2rem;border-bottom:1px solid #cbd5e0;padding-bottom:.2rem}
table{border-collapse:collapse;width:100%;font-size:.82rem;margin:.6rem 0}
th,td{border:1px solid #cbd5e0;padding:.28rem .5rem;text-align:left}
th{background:#edf2f7}
.disclaimer{background:#fff5f5;border:1px solid #feb2b2;padding:.7rem 1rem;
            font-size:.85rem;margin:1rem 0;font-weight:bold}
.badge{display:inline-block;padding:.15rem .6rem;border:2px solid #1a202c;
       font-weight:bold;font-size:1rem}
.meta{color:#4a5568;font-size:.85rem}
.warn{color:#9b2c2c}
ul{margin:.3rem 0}
@media print{body{margin:.5in}}
"""


def _table(rows, cols=None, limit=50):
    if not rows:
        return "<p class='meta'>N/A — no data available for this section.</p>"
    if cols is None:
        cols = []
        for r in rows[:5]:
            for k in r.keys():
                if k not in cols and not isinstance(r[k], (dict, list)):
                    cols.append(k)
        cols = cols[:12]
    out = ["<table><tr>" + "".join(f"<th>{_esc(c)}</th>" for c in cols) + "</tr>"]
    for r in rows[:limit]:
        out.append("<tr>" + "".join(f"<td>{_esc(r.get(c))}</td>" for c in cols) + "</tr>")
    out.append("</table>")
    return "".join(out)


def _kv_table(d, keys=None):
    d = d or {}
    items = [(k, v) for k, v in d.items()
             if not isinstance(v, (dict, list)) and (keys is None or k in keys)]
    if not items:
        return "<p class='meta'>N/A</p>"
    return ("<table>" +
            "".join(f"<tr><th>{_esc(k)}</th><td>{_esc(v)}</td></tr>" for k, v in items) +
            "</table>")


def export_html(exp_dir, out_path=None):
    got = get_report(exp_dir)
    if not got.get("success"):
        return got
    rep = got["report"]
    exp_id = rep.get("experiment_id")
    es = rep.get("executive_summary") or {}
    fv = rep.get("final_verdict") or {}
    dist = (rep.get("trade_distribution") or {}).get("tables") or {}
    parts = [
        "<!DOCTYPE html><html><head><meta charset='utf-8'>",
        f"<title>Research Report — {_esc(es.get('experiment_name'))}</title>",
        f"<style>{_CSS}</style></head><body>",
        f"<h1>Experiment Research Report — {_esc(es.get('experiment_name'))}</h1>",
        f"<p class='meta'>Experiment ID: {_esc(exp_id)} &nbsp;|&nbsp; Report version: "
        f"{_esc(rep.get('report_version'))} &nbsp;|&nbsp; Generated: {_esc(rep.get('generated_at'))}</p>",
        f"<div class='disclaimer'>{_esc(DISCLAIMER)}</div>",
        f"<h2>1. Final Research Verdict</h2><p><span class='badge'>{_esc(fv.get('verdict'))}</span></p>",
        "<ul>" + "".join(f"<li>{_esc(r)}</li>" for r in fv.get("reasons") or []) + "</ul>",
        _kv_table(fv.get("thresholds")),
        "<h2>2. Executive Summary</h2>",
        f"<p>{_esc(es.get('explanation'))}</p>", _kv_table(es),
        "<h2>3. Performance</h2>", _kv_table(rep.get("performance_analysis")),
        "<h3>Benchmarks</h3>", _kv_table((rep.get("performance_analysis") or {}).get("benchmarks")),
        "<h3>Windows</h3>", _table((rep.get("performance_analysis") or {}).get("windows") or []),
        "<h2>4. Risk</h2>", _kv_table(rep.get("risk_analysis")),
        "<ul>" + "".join(f"<li class='warn'>{_esc(w)}</li>"
                         for w in (rep.get("risk_analysis") or {}).get("warnings") or []) + "</ul>",
        "<h2>5. Drawdown Episodes</h2>",
        _table([{k: v for k, v in e.items() if k != "main_loss_contributors"}
                for e in (rep.get("drawdown_analysis") or {}).get("episodes") or []]),
        f"<p>{_esc((rep.get('drawdown_analysis') or {}).get('largest_drawdown_explanation'))}</p>",
        "<h2>6. Trade Distribution</h2>",
    ]
    for name, rows in dist.items():
        parts.append(f"<h3>{_esc(name.replace('_', ' ').title())}</h3>")
        parts.append(_table(rows))
    conf = rep.get("confidence_analysis") or {}
    parts += [
        "<h2>7. Confidence Calibration</h2>",
        "<h3>Before calibration</h3>", _kv_table(conf.get("before_calibration")),
        "<h3>After calibration</h3>", _kv_table(conf.get("after_calibration")),
        "<h3>Reliability buckets</h3>", _table(conf.get("reliability_buckets") or []),
        "<ul>" + "".join(f"<li class='warn'>{_esc(w)}</li>" for w in conf.get("warnings") or []) + "</ul>",
        "<h2>8. False Positives</h2>",
        f"<p>{_esc((rep.get('false_positive_analysis') or {}).get('definition'))}</p>",
        _kv_table(rep.get("false_positive_analysis"),
                  keys=["count", "total_trades", "rate_pct", "avg_mae_pct", "avg_mfe_pct", "avg_holding_days"]),
        _table((rep.get("false_positive_analysis") or {}).get("subgroup_rates") or []),
        "<h2>9. Missed Opportunities</h2>",
        f"<p>{_esc((rep.get('missed_opportunity_analysis') or {}).get('note'))}</p>",
        _table((rep.get("missed_opportunity_analysis") or {}).get("categories") or []),
        "<h2>10. Feature Analysis</h2>",
        _table([{k: v for k, v in f.items() if k != "bins"}
                for f in (rep.get("feature_analysis") or {}).get("features") or []]),
        f"<p class='meta'>{_esc((rep.get('feature_analysis') or {}).get('note'))}</p>",
        "<h2>11. Parameter Sensitivity</h2>",
        f"<p class='meta'>{_esc((rep.get('parameter_sensitivity') or {}).get('note'))}</p>",
    ]
    for name, rows in ((rep.get("parameter_sensitivity") or {}).get("sweeps") or {}).items():
        parts.append(f"<h3>{_esc(name.replace('_', ' ').title())}</h3>")
        parts.append(_table(rows))
    parts += [
        "<h2>12. Market Regimes</h2>",
        _table((rep.get("regime_analysis") or {}).get("tables") or []),
        "<h3>Regime eligibility (analysis only)</h3>",
        _table((rep.get("regime_analysis") or {}).get("eligibility_recommendations") or []),
        f"<p class='meta'>{_esc((rep.get('regime_analysis') or {}).get('disclaimer'))}</p>",
        "<h2>13. Holding Periods</h2>",
        _table([{k: v for k, v in t.items() if k != "exit_reasons"}
                for t in (rep.get("holding_period_analysis") or {}).get("tables") or []]),
        "<h3>Controlled alternative-exit analysis</h3>",
        _table((rep.get("holding_period_analysis") or {}).get("alternative_exits") or []),
        f"<p class='meta'>{_esc((rep.get('holding_period_analysis') or {}).get('alternative_exit_note'))}</p>",
        "<h2>14. Best and Worst Trades</h2>",
        "<h3>Top winners</h3>", _table((rep.get("trade_examples") or {}).get("top_winners") or [], limit=10),
        "<h3>Top losers</h3>", _table((rep.get("trade_examples") or {}).get("top_losers") or [], limit=10),
        "<h3>High-confidence losses</h3>",
        _table((rep.get("trade_examples") or {}).get("high_confidence_losses") or [], limit=10),
        "<h2>15. Strengths</h2>", _table(rep.get("strengths") or []),
        "<h2>16. Weaknesses</h2>", _table(rep.get("weaknesses") or []),
        "<h2>17. Recommendations</h2>", _table(rep.get("recommendations") or []),
        "<h2>18. Suggested Next Experiments</h2>",
        _table([{k: _flat(v) for k, v in s.items() if k not in ("control_config", "treatment_config")}
                for s in (rep.get("next_experiments") or {}).get("suggestions") or []]),
        "<h2>19. Diagnostics</h2>", _kv_table(rep.get("diagnostics")),
        _kv_table((rep.get("diagnostics") or {}).get("lookahead_audit")),
        f"<div class='disclaimer'>{_esc(DISCLAIMER)}</div>",
        "</body></html>",
    ]
    html_doc = "".join(parts)
    if out_path is None:
        out_path = os.path.join(exp_dir, "reports",
                                f"report_v{rep.get('report_version')}.html")
    with open(out_path, "w") as f:
        f.write(html_doc)
    return {"success": True, "path": out_path}
