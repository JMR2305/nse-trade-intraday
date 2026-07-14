"""Phase 5 review CSV export — read-only reporting feature.

Builds two CSV files for external review of all Phase 5 functionality:
  * phase5_review_export.csv  — one row per review item across pages A–H
  * phase5_review_summary.csv — one row per page/section

Rules honoured:
  * Read-only: nothing here changes live/paper trading or experiment data.
  * Honest blanks: unavailable values are left empty, never invented.
  * Nested values are serialized as compact JSON.
  * No secrets, no stack traces (safe error summaries in `notes`).
"""
import csv
import io
import json
import os
import traceback  # noqa: F401  (imported to make clear we deliberately do NOT dump traces)
from datetime import datetime, timezone

from research_intelligence import (
    build_intelligence, compare_experiments, trade_diagnostics,
    _completed_experiments, EXPERIMENTS_DIR,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EXPORT_DIR = os.path.join(BASE_DIR, "exports")
MAIN_NAME = "phase5_review_export.csv"
SUMMARY_NAME = "phase5_review_summary.csv"
APP_VERSION = "v0.5"
PHASE = "Phase 5"

COLUMNS = [
    "export_generated_at", "app_version", "phase", "page", "section",
    "sub_section", "record_type", "entity_name", "experiment_name",
    "experiment_id", "strategy", "stock", "sector", "market_regime",
    "model_version", "status", "recommendation", "confidence",
    "evidence_level", "sample_size", "trades", "test_windows",
    "net_return_pct", "net_pnl", "gross_pnl", "profit_factor",
    "expectancy_per_trade", "win_rate_pct", "sharpe", "sortino",
    "max_drawdown_pct", "calibration_brier", "calibration_ece",
    "calibration_log_loss", "precision", "recall", "false_positives",
    "false_negatives", "feature_name", "feature_importance", "pattern_name",
    "pattern_type", "pattern_result", "pattern_expectancy",
    "pattern_profit_factor", "diagnosis", "reason", "supporting_evidence",
    "opposing_evidence", "suggested_improvement", "strategy_health_score",
    "risk_flag", "overfitting_flag", "data_quality_flag", "source_page_url",
    "source_record_id", "implementation_status", "files_modified",
    "api_endpoint", "notes",
]

_NOW = None  # set per generation


def _cell(v):
    """Serialize a value for a CSV cell. Blank for missing; compact JSON for nested."""
    if v is None or v == "":
        return ""
    if isinstance(v, float) and (v != v):  # NaN
        return ""
    if isinstance(v, (dict, list, tuple)):
        try:
            s = json.dumps(v, separators=(",", ":"), default=str)
            if len(s) <= 4000:
                return s
            # Keep the cell valid JSON instead of cutting mid-structure.
            if isinstance(v, dict):
                return json.dumps({"truncated": True, "keys": sorted(map(str, v.keys()))[:50]},
                                  separators=(",", ":"))
            return json.dumps({"truncated": True, "items": len(v)}, separators=(",", ":"))
        except Exception:
            return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    return v


def _row(page, section, record_type, **kw):
    r = {c: "" for c in COLUMNS}
    r.update({
        "export_generated_at": _NOW,
        "app_version": APP_VERSION,
        "phase": PHASE,
        "page": page,
        "section": section,
        "record_type": record_type,
    })
    for k, v in kw.items():
        if k in r:
            r[k] = _cell(v)
    return r


def _safe_err(e):
    return f"{type(e).__name__}: {str(e)[:200]}"


def _num_or_blank(v):
    try:
        if v is None:
            return ""
        f = float(v)
        if f != f:
            return ""
        return round(f, 4)
    except (TypeError, ValueError):
        return ""


def _evidence(n):
    try:
        n = int(n)
    except (TypeError, ValueError):
        return ""
    if n >= 100:
        return "STRONG"
    if n >= 30:
        return "MODERATE"
    if n >= 10:
        return "WEAK"
    return "INSUFFICIENT"


# ── Section builders — each returns (rows, audit_entries) ────────────────────

def _rows_research_factory(rows, audits, cmds):
    page, url = "Research Factory", "/experiments"

    # Queue
    try:
        exps = (cmds["experiment_list"]() or {}).get("experiments", [])
        for e in exps:
            rows.append(_row(page, "Experiment queue", "experiment",
                entity_name=e.get("name"), experiment_name=e.get("name"),
                experiment_id=e.get("id"), status=e.get("status"),
                source_page_url=url, source_record_id=e.get("id"),
                notes=_cell({"config_summary": e.get("config_summary")})))
        audits.append(("Research Factory", "Experiment queue", "COMPLETE", len(exps),
                       f"{len(exps)} experiments in registry", "", url))
    except Exception as e:
        audits.append(("Research Factory", "Experiment queue", "ERROR", 0, "", _safe_err(e), url))

    # Batches
    try:
        batches = (cmds["experiment_batch_list"]() or {}).get("batches", [])
        for b in batches:
            rows.append(_row(page, "Batches", "batch",
                entity_name=b.get("name") or b.get("id"), status=b.get("status"),
                sample_size=len(b.get("experiment_ids", []) or []),
                source_page_url=url, source_record_id=b.get("id")))
        audits.append(("Research Factory", "Batches", "COMPLETE", len(batches),
                       f"{len(batches)} batches", "", url))
    except Exception as e:
        audits.append(("Research Factory", "Batches", "ERROR", 0, "", _safe_err(e), url))

    # Leaderboard
    try:
        lb = (cmds["experiment_leaderboard"]() or {}).get("leaderboard", [])
        for i, e in enumerate(lb):
            rows.append(_row(page, "Leaderboard", "leaderboard_entry",
                entity_name=e.get("name"), experiment_name=e.get("name"),
                experiment_id=e.get("id"), status=e.get("verdict") or e.get("status"),
                trades=e.get("oos_trades"), test_windows=e.get("windows"),
                net_return_pct=_num_or_blank(e.get("net_return_pct")),
                profit_factor=_num_or_blank(e.get("profit_factor")),
                sharpe=_num_or_blank(e.get("sharpe")),
                max_drawdown_pct=_num_or_blank(e.get("max_drawdown_pct")),
                win_rate_pct=_num_or_blank(e.get("win_rate")),
                calibration_ece=_num_or_blank(e.get("calibration_ece")),
                evidence_level=_evidence(e.get("oos_trades")),
                confidence=_num_or_blank(e.get("score")),
                source_page_url=url, source_record_id=e.get("id"),
                notes=f"rank={i + 1}; score 0-100 composite"))
        audits.append(("Research Factory", "Leaderboard", "COMPLETE", len(lb),
                       f"{len(lb)} ranked entries", "", url))
    except Exception as e:
        audits.append(("Research Factory", "Leaderboard", "ERROR", 0, "", _safe_err(e), url))

    # Per-experiment report sections
    completed = []
    try:
        completed = _completed_experiments()
    except Exception as e:
        audits.append(("Research Factory", "Research reports", "ERROR", 0, "", _safe_err(e), url))

    report_sections = [
        ("Research verdict", "final_verdict"),
        ("Executive summary", "executive_summary"),
        ("Performance", "performance_analysis"),
        ("Risk", "risk_analysis"),
        ("Equity and drawdown", "drawdown_analysis"),
        ("Trade distribution", "trade_distribution"),
        ("Confidence calibration", "confidence_analysis"),
        ("False positives", "false_positive_analysis"),
        ("False negatives", "missed_opportunity_analysis"),
        ("Overfitting and robustness", "parameter_sensitivity"),
        ("Market-regime contribution", "regime_analysis"),
        ("Final recommendation", "recommendations"),
    ]
    n_report_rows = 0
    for exp_id, _d, status, config, df, report in completed:
        name = (status.get("name") or config.get("name") or exp_id)
        rurl = f"/experiments (report: {exp_id})"
        if not report:
            rows.append(_row(page, "Research verdict", "report_missing",
                experiment_name=name, experiment_id=exp_id, status="NO_REPORT",
                implementation_status="PARTIAL", source_page_url=rurl,
                source_record_id=exp_id,
                notes="Completed experiment without a generated research report."))
            n_report_rows += 1
            continue
        ex = report.get("executive_summary") or {}
        perf = report.get("performance_analysis") or {}
        risk = report.get("risk_analysis") or {}
        cal = report.get("confidence_analysis") or {}
        common = dict(
            experiment_name=name, experiment_id=exp_id,
            model_version=report.get("report_version"),
            trades=ex.get("oos_trades") or ex.get("total_trades"),
            test_windows=ex.get("windows"),
            evidence_level=_evidence(ex.get("oos_trades") or ex.get("total_trades")),
            source_record_id=exp_id, source_page_url=rurl,
        )
        for section_label, key in report_sections:
            sec = report.get(key)
            if sec in (None, {}, []):
                rows.append(_row(page, section_label, "report_section",
                    status="NOT_AVAILABLE", implementation_status="PARTIAL",
                    notes="Section not present in stored report.", **common))
                n_report_rows += 1
                continue
            extra = {}
            if key == "final_verdict":
                extra = dict(status=(sec.get("verdict") if isinstance(sec, dict) else ""),
                             recommendation=(sec.get("recommendation") if isinstance(sec, dict) else ""))
            if key == "executive_summary" and isinstance(sec, dict):
                extra = dict(
                    net_return_pct=_num_or_blank(sec.get("net_return_pct")),
                    net_pnl=_num_or_blank(sec.get("net_pnl")),
                    profit_factor=_num_or_blank(sec.get("profit_factor")),
                    win_rate_pct=_num_or_blank(sec.get("win_rate")),
                    status=sec.get("verdict"))
            if key == "performance_analysis" and isinstance(sec, dict):
                extra = dict(
                    net_return_pct=_num_or_blank(perf.get("net_return_pct")),
                    net_pnl=_num_or_blank(perf.get("net_pnl")),
                    gross_pnl=_num_or_blank(perf.get("gross_pnl")),
                    profit_factor=_num_or_blank(perf.get("profit_factor")),
                    expectancy_per_trade=_num_or_blank(perf.get("expectancy_rs") or perf.get("expectancy")),
                    win_rate_pct=_num_or_blank(perf.get("win_rate")),
                    sharpe=_num_or_blank(perf.get("sharpe")),
                    sortino=_num_or_blank(perf.get("sortino")))
            if key == "risk_analysis" and isinstance(sec, dict):
                extra = dict(max_drawdown_pct=_num_or_blank(risk.get("max_drawdown_pct")),
                             risk_flag=risk.get("risk_rating") or "")
            if key == "confidence_analysis" and isinstance(sec, dict):
                extra = dict(
                    calibration_brier=_num_or_blank(cal.get("brier_score") or cal.get("brier")),
                    calibration_ece=_num_or_blank(cal.get("ece_after") or cal.get("ece")),
                    calibration_log_loss=_num_or_blank(cal.get("log_loss")))
            row_kw = dict(common)
            row_kw.update(extra)
            rows.append(_row(page, section_label, "report_section",
                notes=_cell(sec), **row_kw))
            n_report_rows += 1
    for section_label, _k in report_sections:
        audits.append(("Research Factory", section_label,
                       "COMPLETE" if completed else "PARTIAL",
                       sum(1 for r in rows if r["page"] == page and r["section"] == section_label),
                       f"from {len(completed)} completed experiments' latest reports", "", url))

    # Strategy / sector contribution (from intelligence tables, cross-experiment)
    return completed


def _rows_intelligence(rows, audits, intel):
    page, url = "Research Factory", "/research-intelligence"
    ls = intel.get("learning_summary") or {}
    tables = ls.get("tables") or {}

    for label, key, sec_col in [
        ("Strategy contribution", "by_strategy", "strategy"),
        ("Sector contribution", "by_sector", "sector"),
        ("Market-regime contribution", "by_regime", "market_regime"),
    ]:
        t = tables.get(key) or []
        for g in t:
            rows.append(_row(page, label, "contribution",
                entity_name=g.get("group"),
                **{sec_col: g.get("group")},
                trades=g.get("trades"), net_pnl=_num_or_blank(g.get("net_pnl")),
                win_rate_pct=_num_or_blank(g.get("win_rate")),
                expectancy_per_trade=_num_or_blank(g.get("expectancy_rs")),
                profit_factor=_num_or_blank(g.get("profit_factor")),
                evidence_level=_evidence(g.get("trades")),
                source_page_url=url, source_record_id=f"{key}:{g.get('group')}",
                notes="Aggregated across all completed experiments (research only)."))
        audits.append(("Research Factory", label, "COMPLETE" if t else "PARTIAL",
                       len(t), f"{len(t)} groups", "" if t else "no data", url))

    for ins in intel.get("insights") or []:
        rows.append(_row(page, "Research insights", "insight",
            entity_name=ins.get("title"), strategy=ins.get("strategy") or "",
            confidence=ins.get("confidence_level"),
            trades=(ins.get("evidence") or {}).get("trades"),
            evidence_level=_evidence((ins.get("evidence") or {}).get("trades")),
            supporting_evidence=(ins.get("evidence") or {}).get("metric"),
            reason=ins.get("detail"), source_page_url=url,
            source_record_id=ins.get("id"),
            notes="Deterministic rule-based insight. Research only."))
    audits.append(("Research Factory", "Research insights", "COMPLETE",
                   len(intel.get("insights") or []), f"{len(intel.get('insights') or [])} insights", "", url))

    for r_ in intel.get("recommendations") or []:
        rows.append(_row(page, "AI recommendations", "recommendation",
            entity_name=r_.get("action"), recommendation=r_.get("action"),
            confidence=r_.get("confidence_level"),
            trades=r_.get("evidence_trades"),
            evidence_level=_evidence(r_.get("evidence_trades")),
            supporting_evidence=r_.get("supporting_evidence"),
            suggested_improvement=r_.get("expected_benefit"),
            status="ADVISORY_ONLY", source_page_url=url, source_record_id=r_.get("id"),
            notes="Research suggestion only — never applied automatically."))
    audits.append(("Research Factory", "AI recommendations", "COMPLETE",
                   len(intel.get("recommendations") or []),
                   f"{len(intel.get('recommendations') or [])} advisory recommendations", "", url))

    for h in intel.get("strategy_health") or []:
        rows.append(_row(page, "Strategy health", "strategy_health",
            entity_name=h.get("strategy"), strategy=h.get("strategy"),
            strategy_health_score=h.get("health_score"), status=h.get("rating"),
            trades=h.get("trades"), evidence_level=h.get("evidence") or _evidence(h.get("trades")),
            profit_factor=_num_or_blank(h.get("profit_factor")),
            expectancy_per_trade=_num_or_blank(h.get("expectancy_rs")),
            win_rate_pct=_num_or_blank(h.get("win_rate")),
            net_pnl=_num_or_blank(h.get("net_pnl")),
            sharpe=_num_or_blank(h.get("sharpe_proxy")),
            reason=h.get("explanation"), source_page_url=url,
            source_record_id=f"health:{h.get('strategy')}",
            notes="Sharpe column holds per-trade Sharpe proxy for this record type."))
    audits.append(("Research Factory", "Strategy health", "COMPLETE",
                   len(intel.get("strategy_health") or []),
                   f"{len(intel.get('strategy_health') or [])} strategies scored", "", url))

    # Cross-experiment findings (learning summary highlights)
    n = 0
    for label, obj, key in [
        ("Most consistent strategy", ls.get("most_consistent_strategy"), "strategy"),
        ("Weakest strategy", ls.get("weakest_strategy"), "strategy"),
        ("Safest regime", ls.get("safest_regime"), "regime"),
        ("Riskiest regime", ls.get("riskiest_regime"), "regime"),
        ("Best confidence band", ls.get("best_confidence_band"), "band"),
    ]:
        if not obj:
            rows.append(_row(page, "Cross-experiment findings", "finding",
                entity_name=label, status="NOT_AVAILABLE",
                source_page_url=url, notes="Insufficient data — honestly blank."))
            n += 1
            continue
        rows.append(_row(page, "Cross-experiment findings", "finding",
            entity_name=label, strategy=obj.get("strategy") or "",
            market_regime=obj.get("regime") or "",
            expectancy_per_trade=_num_or_blank(obj.get("expectancy_rs")),
            trades=obj.get("trades"), evidence_level=obj.get("sample_label") or _evidence(obj.get("trades")),
            source_page_url=url, source_record_id=f"finding:{label}",
            notes=_cell({k: v for k, v in obj.items() if k not in ("strategy", "regime")})))
        n += 1
    audits.append(("Research Factory", "Cross-experiment findings", "COMPLETE", n,
                   "learning summary highlights", "", url))


def _rows_compare(rows, audits, completed):
    page, url = "Research Factory", "/research-intelligence (Compare)"
    try:
        ids = [e[0] for e in completed]
        if not ids:
            audits.append(("Research Factory", "Experiment comparison", "PARTIAL", 0,
                           "no completed experiments", "", url))
            return
        cmp_ = compare_experiments(ids)
        n = 0
        for e in cmp_.get("experiments") or []:
            rows.append(_row(page, "Experiment comparison", "comparison_entry",
                entity_name=e.get("experiment_name"),
                experiment_name=e.get("experiment_name"),
                experiment_id=e.get("experiment_id"),
                status=e.get("verdict") if e.get("available") else "NO_REPORT",
                trades=e.get("oos_trades"), test_windows=e.get("windows"),
                net_return_pct=_num_or_blank(e.get("net_return_pct")),
                net_pnl=_num_or_blank(e.get("net_pnl")),
                profit_factor=_num_or_blank(e.get("profit_factor")),
                expectancy_per_trade=_num_or_blank(e.get("expectancy_rs")),
                win_rate_pct=_num_or_blank(e.get("win_rate")),
                sharpe=_num_or_blank(e.get("sharpe")),
                max_drawdown_pct=_num_or_blank(e.get("max_drawdown_pct")),
                calibration_ece=_num_or_blank(e.get("calibration_ece_after")),
                evidence_level=e.get("evidence_verdict") or _evidence(e.get("oos_trades")),
                market_regime=e.get("dominant_regime") or "",
                source_page_url=url, source_record_id=e.get("experiment_id"),
                notes="" if e.get("available") else (e.get("note") or "report unavailable")))
            n += 1
        audits.append(("Research Factory", "Experiment comparison", "COMPLETE", n,
                       f"{n} experiments compared", "", url))
    except Exception as e:
        audits.append(("Research Factory", "Experiment comparison", "ERROR", 0, "", _safe_err(e), url))


def _rows_learning_insights(rows, audits, cmds, intel):
    page, url = "Learning Insights", "/learning-insights"
    try:
        li = cmds["learning_insights"]() or {}
    except Exception as e:
        audits.append(("Learning Insights", "All sections", "ERROR", 0, "", _safe_err(e), url))
        return

    def pat_rows(section, items, ptype):
        for p in items or []:
            nm = " / ".join(str(p.get(k)) for k in ("strategy", "sector", "regime") if p.get(k))
            rows.append(_row(page, section, "pattern",
                entity_name=nm, pattern_name=nm, pattern_type=ptype,
                strategy=p.get("strategy") or "", sector=p.get("sector") or "",
                market_regime=p.get("regime") or "",
                trades=p.get("trades"), sample_size=p.get("trades"),
                evidence_level=_evidence(p.get("trades")),
                win_rate_pct=_num_or_blank(p.get("win_rate")),
                profit_factor=_num_or_blank(p.get("profit_factor")),
                pattern_profit_factor=_num_or_blank(p.get("profit_factor")),
                expectancy_per_trade=_num_or_blank(p.get("expectancy")),
                pattern_expectancy=_num_or_blank(p.get("expectancy")),
                pattern_result="PROFITABLE" if (p.get("expectancy") or 0) > 0 else "UNPROFITABLE",
                sharpe=_num_or_blank(p.get("sharpe")), sortino=_num_or_blank(p.get("sortino")),
                max_drawdown_pct=_num_or_blank(p.get("max_drawdown")),
                source_page_url=url, source_record_id=f"{section}:{nm}",
                notes="Deterministic aggregation of simulated historical trades. Research only."))
        audits.append(("Learning Insights", section, "COMPLETE" if items else "PARTIAL",
                       len(items or []), f"{len(items or [])} patterns", "", url))

    pat_rows("Winning patterns", li.get("top_patterns"), "WINNING")
    pat_rows("Losing patterns", li.get("worst_patterns"), "LOSING")
    pat_rows("Strategy-level findings", li.get("best_risk_adjusted_strategies"), "STRATEGY")
    pat_rows("Sector-level findings", li.get("best_strategy_by_sector"), "SECTOR")
    pat_rows("Regime-level findings", li.get("best_strategy_by_regime"), "REGIME")

    bands = ((intel.get("learning_summary") or {}).get("tables") or {}).get("by_confidence_band") or []
    for b in bands:
        rows.append(_row(page, "Confidence-band findings", "confidence_band",
            entity_name=b.get("group"), trades=b.get("trades"),
            evidence_level=_evidence(b.get("trades")),
            expectancy_per_trade=_num_or_blank(b.get("expectancy_rs")),
            win_rate_pct=_num_or_blank(b.get("win_rate")),
            net_pnl=_num_or_blank(b.get("net_pnl")),
            source_page_url="/research-intelligence",
            source_record_id=f"band:{b.get('group')}",
            notes="From cross-experiment OOS trades."))
    audits.append(("Learning Insights", "Confidence-band findings",
                   "COMPLETE" if bands else "PARTIAL", len(bands), f"{len(bands)} bands", "", url))
    audits.append(("Learning Insights", "Cross-experiment learning", "COMPLETE",
                   0, "see Research Factory > Cross-experiment findings rows", "", url))
    audits.append(("Learning Insights", "Recommendations", "COMPLETE",
                   0, "see Research Factory > AI recommendations rows", "", url))


def _rows_learning_review(rows, audits, cmds, intel):
    page, url = "Learning Review", "/learning-review"
    try:
        lr = cmds["learning_review"]() or {}
    except Exception as e:
        audits.append(("Learning Review", "All sections", "ERROR", 0, "", _safe_err(e), url))
        return

    rows.append(_row(page, "Model versions", "model_version",
        entity_name=f"Active model v{lr.get('active_model_version')}",
        model_version=lr.get("active_model_version"), status=lr.get("mode"),
        sample_size=lr.get("trades_evaluated"),
        precision="", recall="",
        source_page_url=url, source_record_id=f"model_v{lr.get('active_model_version')}",
        notes=_cell({"successful_predictions": lr.get("successful_predictions"),
                     "failed_predictions": lr.get("failed_predictions"),
                     "avg_prediction_error": lr.get("avg_prediction_error"),
                     "calibration_score": lr.get("calibration_score")})))
    audits.append(("Learning Review", "Model versions", "COMPLETE", 1,
                   f"active model v{lr.get('active_model_version')}", "", url))

    n = 0
    for b in lr.get("calibration_bands") or []:
        rows.append(_row(page, "Before-versus-after comparisons", "calibration_band",
            entity_name=b.get("band"), trades=b.get("trades"),
            evidence_level=_evidence(b.get("trades")),
            confidence=b.get("band"),
            diagnosis=b.get("conclusion"),
            suggested_improvement=b.get("recommended_correction"),
            source_page_url=url, source_record_id=f"cal_band:{b.get('band')}",
            notes=_cell({"predicted_success_rate": b.get("predicted_success_rate"),
                         "actual_success_rate": b.get("actual_success_rate"),
                         "gap": b.get("gap")})))
        n += 1
    audits.append(("Learning Review", "Before-versus-after comparisons",
                   "COMPLETE" if n else "PARTIAL", n, f"{n} calibration bands", "", url))

    n = 0
    for adj in lr.get("proposed_adjustments") or []:
        rows.append(_row(page, "Recommendation history", "proposed_adjustment",
            entity_name=adj.get("title") or adj.get("id"),
            recommendation=adj.get("recommendation") or adj.get("change"),
            status=adj.get("status"), source_page_url=url,
            source_record_id=adj.get("id"), notes=_cell(adj)))
        n += 1
    if n == 0:
        rows.append(_row(page, "Recommendation history", "empty_result",
            status="EMPTY", source_page_url=url,
            notes="No proposed adjustments recorded — shown honestly as empty."))
    audits.append(("Learning Review", "Recommendation history", "COMPLETE", n,
                   f"{n} proposed adjustments", "", url))

    n = 0
    for ev in intel.get("timeline") or []:
        rows.append(_row(page, "Learning timeline", "timeline_event",
            entity_name=ev.get("title"), status=ev.get("type"),
            experiment_id=ev.get("experiment_id") or "",
            source_page_url="/research-intelligence",
            source_record_id=f"timeline:{ev.get('date')}",
            notes=_cell(ev.get("detail"))))
        n += 1
    audits.append(("Learning Review", "Learning timeline", "COMPLETE", n,
                   f"{n} events", "", url))
    audits.append(("Learning Review", "Strategy improvement history",
                   "PARTIAL", 0,
                   "No dedicated improvement-history store; timeline + recommendations cover current state", "", url))


def _rows_pattern_quality(rows, audits, cmds):
    page, url = "Pattern Quality", "/pattern-quality"
    try:
        pq = cmds["pattern_quality"]() or {}
    except Exception as e:
        audits.append(("Pattern Quality", "All sections", "ERROR", 0, "", _safe_err(e), url))
        return
    pats = pq.get("patterns") or []
    for p in pats:
        nm = " / ".join(str(p.get(k)) for k in ("strategy", "sector", "regime") if p.get(k))
        wins, losses = p.get("wins"), p.get("losses")
        rows.append(_row(page, "Pattern stability", "pattern_quality",
            entity_name=nm, pattern_name=nm, pattern_type="AGGREGATE",
            strategy=p.get("strategy") or "", sector=p.get("sector") or "",
            market_regime=p.get("regime") or "",
            trades=p.get("trades"), sample_size=p.get("trades"),
            evidence_level=_evidence(p.get("trades")),
            win_rate_pct=_num_or_blank(p.get("win_rate")),
            precision=_num_or_blank(p.get("win_rate")),
            false_positives=losses, false_negatives="",
            pattern_expectancy=_num_or_blank(p.get("expectancy")),
            pattern_profit_factor=_num_or_blank(p.get("profit_factor")),
            pattern_result="PROFITABLE" if (p.get("expectancy") or 0) > 0 else "UNPROFITABLE",
            sharpe=_num_or_blank(p.get("sharpe")),
            data_quality_flag="LOW_SAMPLE" if (p.get("trades") or 0) < 10 else "",
            source_page_url=url, source_record_id=f"pq:{nm}",
            notes=json.dumps({"wins": wins, "losses": losses,
                              "note": "precision approximated by win rate (pattern hit rate); recall/false negatives not tracked — left blank"},
                             separators=(",", ":"))))
    audits.append(("Pattern Quality", "Pattern stability", "COMPLETE", len(pats),
                   f"{len(pats)} patterns from {pq.get('knowledge_trades')} knowledge trades", "", url))
    audits.append(("Pattern Quality", "Recall / false negatives", "PARTIAL", 0,
                   "Recall and false negatives are not tracked in the knowledge base — reported blank, not fabricated", "", url))


def _rows_feature_importance(rows, audits, cmds):
    page, url = "Feature Importance", "/feature-importance"
    try:
        fi = cmds["feature_importance"]() or {}
    except Exception as e:
        audits.append(("Feature Importance", "All sections", "ERROR", 0, "", _safe_err(e), url))
        return
    feats = fi.get("features") or []
    ranked = sorted(feats, key=lambda f: -(f.get("importance") or 0))
    for i, f in enumerate(ranked):
        rows.append(_row(page, "Feature importance", "feature",
            entity_name=f.get("label") or f.get("feature"),
            feature_name=f.get("feature"),
            feature_importance=_num_or_blank(f.get("importance")),
            sample_size=f.get("sample_size"),
            evidence_level=_evidence(f.get("sample_size")),
            confidence=f.get("confidence"),
            status=f.get("trend") or "",
            source_page_url=url, source_record_id=f.get("feature"),
            notes=json.dumps({"rank": i + 1, "direction": f.get("direction"),
                              "best_value": f.get("best_value"),
                              "best_value_lift": f.get("best_value_lift"),
                              "worst_value": f.get("worst_value"),
                              "worst_value_lift": f.get("worst_value_lift")},
                             separators=(",", ":"), default=str)))
    audits.append(("Feature Importance", "Feature importance", "COMPLETE", len(feats),
                   f"{len(feats)} features from {fi.get('total_trades')} trades", "", url))


def _rows_trade_replay(rows, audits, cmds, completed):
    page, url = "Trade Replay", "/trade-replay"
    n = 0
    try:
        trades = cmds["trade_replay"]() or []
        if isinstance(trades, dict):
            trades = trades.get("trades") or []
        for t in trades:
            rows.append(_row(page, "Paper trade replay", "paper_trade",
                entity_name=f"{t.get('symbol')} {t.get('id')}",
                stock=t.get("symbol"), market_regime=t.get("regime") or "",
                confidence=_num_or_blank(t.get("signal_confidence")),
                status=t.get("exit_type"),
                net_pnl=_num_or_blank(t.get("pnl")),
                net_return_pct=_num_or_blank(t.get("pnl_pct")),
                reason=t.get("reason_entry"),
                diagnosis=t.get("reason_exit") or t.get("exit_type"),
                recommendation=t.get("ai_decision") or "",
                source_page_url=url, source_record_id=t.get("id"),
                notes=json.dumps({"rr_ratio": t.get("rr_ratio"),
                                  "entry_price": t.get("entry_price"),
                                  "exit_price": t.get("exit_price"),
                                  "indicators_at_entry": "not stored for paper trades — blank, not fabricated"},
                                 separators=(",", ":"), default=str)))
            n += 1
        audits.append(("Trade Replay", "Paper trade replay", "COMPLETE", n,
                       f"{n} paper trades", "", url))
    except Exception as e:
        audits.append(("Trade Replay", "Paper trade replay", "ERROR", 0, "", _safe_err(e), url))

    # Experiment OOS trade diagnostics (Phase 5 trade-level diagnosis)
    n = 0
    try:
        for exp_id, d, status, config, _df, _rep in completed:
            name = status.get("name") or config.get("name") or exp_id
            diag = trade_diagnostics(d)
            for t in diag.get("trades") or []:
                rows.append(_row(page, "Trade diagnosis", "trade_diagnosis",
                    entity_name=f"{t.get('symbol')} {t.get('entry_date')}",
                    experiment_name=name, experiment_id=exp_id,
                    strategy=t.get("strategy_name") or "",
                    stock=t.get("symbol"), sector=t.get("sector") or "",
                    market_regime=t.get("market_regime") or "",
                    confidence=_num_or_blank(t.get("confidence")),
                    status=t.get("outcome"),
                    net_pnl=_num_or_blank(t.get("net_pnl")),
                    net_return_pct=_num_or_blank(t.get("return_pct")),
                    reason=t.get("entry_rationale"),
                    diagnosis=t.get("outcome_explanation"),
                    supporting_evidence=_cell(t.get("filters")),
                    suggested_improvement="",
                    source_page_url="/research-intelligence (Trade Diagnostics)",
                    source_record_id=f"{exp_id}:{t.get('symbol')}:{t.get('entry_date')}",
                    notes=json.dumps({"exit_reason": t.get("exit_reason"),
                                      "holding_days": t.get("holding_days"),
                                      "mae_pct": t.get("mae_pct"), "mfe_pct": t.get("mfe_pct"),
                                      "indicators_at_entry": "not stored — blank, not fabricated"},
                                     separators=(",", ":"), default=str)))
                n += 1
        audits.append(("Trade Replay", "Trade diagnosis", "COMPLETE", n,
                       f"{n} diagnosed OOS trades across {len(completed)} experiments", "", url))
    except Exception as e:
        audits.append(("Trade Replay", "Trade diagnosis", "ERROR", n, "", _safe_err(e), url))


def _rows_ai_decision(rows, audits, cmds):
    page, url = "AI Decision", "/ai-decision"
    try:
        decs = cmds["ai_decisions"]() or []
        if isinstance(decs, dict):
            decs = decs.get("decisions") or []
        n = 0
        for d in decs:
            rows.append(_row(page, "AI decisions", "ai_decision",
                entity_name=d.get("stock"), stock=d.get("stock"),
                recommendation=d.get("decision"),
                confidence=_num_or_blank(d.get("calibrated_confidence") or d.get("confidence")),
                status=d.get("risk_level"),
                supporting_evidence=_cell(d.get("upgrade_reasons")),
                opposing_evidence=_cell(d.get("downgrade_reasons")),
                reason=d.get("final_reason") or d.get("plain_reason") or "",
                source_page_url=url, source_record_id=d.get("stock"),
                notes=json.dumps({
                    "raw_confidence": d.get("raw_confidence"),
                    "calibrated_probability": d.get("calibrated_probability"),
                    "calibration_method": d.get("calibration_method"),
                    "technical_score": d.get("technical_score"),
                    "opportunity_score": d.get("opportunity_score"),
                    "rr_ratio": d.get("rr_ratio"),
                    "entry_price": d.get("entry_price"),
                    "stop_loss": d.get("stop_loss"), "target": d.get("target"),
                }, separators=(",", ":"), default=str)))
            n += 1
        audits.append(("AI Decision", "AI decisions", "COMPLETE", n,
                       f"{n} cached stock decisions (analysis only)", "", url))
    except Exception as e:
        audits.append(("AI Decision", "AI decisions", "ERROR", 0, "", _safe_err(e), url))


AUDIT_FEATURES = [
    ("Research Factory", "Experiment queue", "src/routes/trading.ts;src/python/experiment_manager.py", "GET /api/experiments"),
    ("Research Factory", "Batches", "src/python/experiment_manager.py", "GET /api/experiments/batches"),
    ("Research Factory", "Leaderboard", "src/python/experiment_manager.py", "GET /api/experiments/leaderboard"),
    ("Research Factory", "Experiment comparison", "src/python/research_intelligence.py", "GET /api/experiments/compare?ids="),
    ("Research Factory", "Research reports (verdict/summary/perf/risk/etc.)", "src/python/report_engine.py", "GET /api/experiments/:id/report"),
    ("Research Factory", "Research insights / AI recommendations / Strategy health / Cross-experiment findings", "src/python/research_intelligence.py", "GET /api/research/intelligence"),
    ("Learning Insights", "Patterns and findings", "src/python/learning_engine.py", "GET /api (learning_insights)"),
    ("Learning Review", "Model versions / timeline / history", "src/python/model_versioning.py", "GET /api (learning_review)"),
    ("Pattern Quality", "Pattern metrics", "src/python/trade_quality.py", "GET /api (pattern_quality)"),
    ("Feature Importance", "Feature scores", "src/python/explainability.py", "GET /api (feature_importance)"),
    ("Trade Replay", "Paper trades + diagnostics", "src/python/paper_trader.py;src/python/research_intelligence.py", "GET /api/experiments/:id/trade-diagnostics"),
    ("AI Decision", "Stock decisions", "src/python/ai_decision.py", "GET /api (ai_decisions)"),
]


def build_phase5_export(cmds):
    """Build both CSVs. `cmds` is a dict of read-only data callables."""
    global _NOW
    _NOW = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows, audits = [], []

    completed = _rows_research_factory(rows, audits, cmds) or []
    try:
        intel = build_intelligence()
    except Exception as e:
        intel = {}
        audits.append(("Research Factory", "Research intelligence", "ERROR", 0, "", _safe_err(e), "/research-intelligence"))
    _rows_intelligence(rows, audits, intel)
    _rows_compare(rows, audits, completed)
    _rows_learning_insights(rows, audits, cmds, intel)
    _rows_learning_review(rows, audits, cmds, intel)
    _rows_pattern_quality(rows, audits, cmds)
    _rows_feature_importance(rows, audits, cmds)
    _rows_trade_replay(rows, audits, cmds, completed)
    _rows_ai_decision(rows, audits, cmds)

    # Guarantee coverage: every audited (page, section) must have at least one
    # non-audit row in the main CSV — emit an honest empty row when data was absent.
    present = {(r["page"], r["section"]) for r in rows}
    for pg, section, status, count, key_result, err, url in list(audits):
        if (pg, section) not in present:
            rows.append(_row(pg, section, "empty_result",
                status="ERROR" if status == "ERROR" else "EMPTY",
                implementation_status=status,
                source_page_url=url,
                notes=(err or key_result or "No records available — shown honestly as empty, not hidden.")))

    # H. Completion / implementation audit — one row per Phase 5 feature.
    # Status is aggregated deterministically over that page's section audits:
    # ERROR > PARTIAL > COMPLETE.
    _SEVERITY = {"ERROR": 2, "PARTIAL": 1, "COMPLETE": 0}
    for pg, section, files, endpoint in AUDIT_FEATURES:
        matches = [a for a in audits if a[0] == pg]
        status = "COMPLETE"
        note_parts = []
        for a in matches:
            if _SEVERITY.get(a[2], 0) > _SEVERITY.get(status, 0):
                status = a[2]
            if a[2] in ("ERROR", "PARTIAL") and a[5]:
                note_parts.append(f"{a[1]}: {a[5]}")
            elif a[2] == "PARTIAL":
                note_parts.append(f"{a[1]}: partial ({a[4]})" if a[4] else f"{a[1]}: partial")
        rows.append(_row("Completion audit", f"{pg} — {section}", "implementation_audit",
            entity_name=f"{pg}: {section}",
            implementation_status=status,
            files_modified=files, api_endpoint=endpoint,
            status="RESEARCH_ONLY",
            source_page_url={"Research Factory": "/experiments",
                             "Learning Insights": "/learning-insights",
                             "Learning Review": "/learning-review",
                             "Pattern Quality": "/pattern-quality",
                             "Feature Importance": "/feature-importance",
                             "Trade Replay": "/trade-replay",
                             "AI Decision": "/ai-decision"}.get(pg, ""),
            notes="; ".join(note_parts) if note_parts else
                  "No database migrations required — file/SQLite-backed stores. Read-only export."))
    # Per-section audit rows (every section listed gets at least one row)
    for a in audits:
        pg, section, status, count, key_result, err, url = a
        rows.append(_row("Completion audit", f"{pg} — {section}", "section_audit",
            entity_name=f"{pg}: {section}",
            implementation_status=status, sample_size=count,
            source_page_url=url,
            notes=(err or key_result)))

    # summary CSV rows
    summary_rows = []
    for a in audits:
        pg, section, status, count, key_result, err, url = a
        ev = "STRONG" if count >= 100 else "MODERATE" if count >= 30 else "WEAK" if count >= 10 else "INSUFFICIENT"
        summary_rows.append({
            "page": pg, "section": section, "implementation_status": status,
            "record_count": count, "key_result": key_result,
            "evidence_level": ev if count else "",
            "major_issue": err,
            "recommended_next_step": ("Investigate error" if status == "ERROR"
                                      else "Collect more data" if status == "PARTIAL"
                                      else ""),
            "source_page_url": url,
        })
    return rows, summary_rows


def _write_csv(path, fieldnames, rows):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fieldnames, quoting=csv.QUOTE_MINIMAL,
                       lineterminator="\r\n", extrasaction="ignore")
    w.writeheader()
    for r in rows:
        w.writerow(r)
    data = buf.getvalue()
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(data)
    return len(rows)


def cmd_phase5_export(mode, cmds):
    """Generate both review CSVs (mode='generate') or reuse recent files.

    Returns metadata; the API layer streams the files from disk.
    """
    os.makedirs(EXPORT_DIR, exist_ok=True)
    main_path = os.path.join(EXPORT_DIR, MAIN_NAME)
    summary_path = os.path.join(EXPORT_DIR, SUMMARY_NAME)
    meta_path = os.path.join(EXPORT_DIR, "phase5_review_meta.json")

    if mode == "reuse" and os.path.exists(main_path) and os.path.exists(summary_path) and os.path.exists(meta_path):
        try:
            with open(meta_path) as f:
                meta = json.load(f)
            return meta
        except Exception:
            pass  # fall through to regenerate

    rows, summary_rows = build_phase5_export(cmds)
    n_main = _write_csv(main_path, COLUMNS, rows)
    summary_cols = ["page", "section", "implementation_status", "record_count",
                    "key_result", "evidence_level", "major_issue",
                    "recommended_next_step", "source_page_url"]
    n_summary = _write_csv(summary_path, summary_cols, summary_rows)

    pages = sorted({r["page"] for r in rows})
    meta = {
        "success": True, "research_only": True,
        "generated_at": _NOW,
        "main_file": main_path, "summary_file": summary_path,
        "main_rows": n_main, "summary_rows": n_summary,
        "columns": len(COLUMNS), "pages": pages,
        "note": "Read-only export. Unavailable values left blank — never invented.",
    }
    try:
        with open(meta_path, "w") as f:
            json.dump(meta, f)
    except Exception:
        pass
    return meta
