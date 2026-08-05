/** Sections 1, 2, 3, 4, 12, 13 — enhanced candidate card */
import { useState } from "react";
import {
  ChevronDown, ChevronUp, CheckCircle2, XCircle, Info,
  TrendingUp, AlertTriangle, Lightbulb,
} from "lucide-react";
import type { Candidate } from "./types";
import {
  computeRiskScore, getSeverity, SEVERITY_CONFIG, riskScoreLevel,
  parseThreshold, generatePassHint, computeExpectedOpportunity,
  generateDecisionExplainer, GATE_RECOMMENDATIONS,
  fmt1, fmt2, fmtCur, fmtPct,
} from "./helpers";

interface Props {
  candidate: Candidate;
  defaultExpanded?: boolean;
  onGateClick?: (gateId: string) => void;
}

export function EnhancedCandidateCard({ candidate: c, defaultExpanded, onGateClick }: Props) {
  const [gatesOpen,      setGatesOpen]      = useState(defaultExpanded ?? !c.eligible);
  const [oppOpen,        setOppOpen]        = useState(false);
  const [recoOpen,       setRecoOpen]       = useState(false);

  const rs       = computeRiskScore(c);
  const severity = getSeverity(c);
  const sevCfg   = SEVERITY_CONFIG[severity];
  const slCfg    = riskScoreLevel(rs.score);
  const opp      = computeExpectedOpportunity(c);
  const explainer= generateDecisionExplainer(c);

  const failedGates  = c.gates.filter(g => !g.passed);
  const passedGates  = c.gates.filter(g => g.passed);
  const failedLocal  = failedGates.filter(g => !g.is_global);
  const recommendations = failedGates
    .filter(g => GATE_RECOMMENDATIONS[g.gate])
    .map(g => ({ gate: g, text: GATE_RECOMMENDATIONS[g.gate] }));

  return (
    <div className={`rounded-xl border ${c.eligible ? "border-emerald-700/40 bg-emerald-950/10" : "border-slate-700/40 bg-slate-800/40"}`}>
      {/* ── Header ─────────────────────────────────────────────────────────── */}
      <div className="flex flex-wrap items-center gap-2 px-4 py-3 border-b border-slate-700/30">
        {/* Symbol + sector */}
        <div className="flex-1 min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-bold text-white text-base">{c.symbol}</span>
            <span className="text-xs text-slate-400 bg-slate-700/50 px-2 py-0.5 rounded">
              {c.sector || "—"}
            </span>
            {c.strategy_name && (
              <span className="text-xs text-blue-400 bg-blue-900/30 border border-blue-700/40 px-2 py-0.5 rounded">
                {c.strategy_name}
              </span>
            )}
          </div>
          {c.regime && (
            <div className="text-xs text-slate-500 mt-0.5">Regime: {c.regime}</div>
          )}
        </div>

        {/* Severity badge (Section 3) — only for rejected */}
        {!c.eligible && (
          <span className={`text-xs font-bold px-2 py-0.5 rounded ${sevCfg.bg} ${sevCfg.color}`}>
            {sevCfg.label}
          </span>
        )}

        {/* Risk Score ring (Section 12) */}
        <div className={`flex items-center gap-1.5 px-2 py-1 rounded border text-xs font-semibold ${slCfg.bg}`}>
          <span className={slCfg.color}>{rs.score}</span>
          <span className="text-slate-400">/100</span>
          <span className={`${slCfg.color}`}>{rs.level} Risk</span>
        </div>

        {/* Verdict chip */}
        {c.eligible ? (
          <span className="flex items-center gap-1 text-xs font-bold text-emerald-300 bg-emerald-900/30 border border-emerald-700/40 px-2 py-0.5 rounded">
            <CheckCircle2 className="w-3.5 h-3.5" /> ELIGIBLE
          </span>
        ) : (
          <span className="flex items-center gap-1 text-xs font-bold text-red-300 bg-red-900/30 border border-red-700/40 px-2 py-0.5 rounded">
            <XCircle className="w-3.5 h-3.5" /> REJECTED · {failedGates.length} gate{failedGates.length !== 1 ? "s" : ""} failed
          </span>
        )}
      </div>

      {/* ── KPI row ────────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-px bg-slate-700/20 border-b border-slate-700/30">
        {[
          { label: "Confidence",   value: `${fmt1(c.confidence)}%`,         ok: c.confidence >= 60 },
          { label: "Opp. Score",   value: `${fmt1(c.opportunity_score)}%`,  ok: c.opportunity_score >= 60 },
          { label: "R:R",          value: `${fmt2(c.sizing.rr_ratio)}×`,    ok: c.sizing.rr_ratio >= 2 },
          { label: "Trade Quality",value: `${fmt1(c.trade_quality_score)}%`,ok: c.trade_quality_score >= 50 },
        ].map(({ label, value, ok }) => (
          <div key={label} className="bg-slate-800/60 px-3 py-2">
            <div className="text-xs text-slate-500">{label}</div>
            <div className={`text-sm font-bold ${ok ? "text-emerald-400" : "text-red-400"}`}>{value}</div>
          </div>
        ))}
      </div>

      {/* ── Sizing row ─────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-px bg-slate-700/20 border-b border-slate-700/30">
        {[
          { label: "Position Size", value: `${c.sizing.quantity} shares` },
          { label: "Capital Req.",  value: fmtCur(c.sizing.position_value) },
          { label: "Stop Loss",     value: fmtCur(c.sizing.stop_loss) },
          { label: "Target",        value: fmtCur(c.sizing.target_price) },
        ].map(({ label, value }) => (
          <div key={label} className="bg-slate-800/60 px-3 py-2">
            <div className="text-xs text-slate-500">{label}</div>
            <div className="text-sm font-semibold text-slate-200">{value}</div>
          </div>
        ))}
      </div>

      <div className="p-4 space-y-3">
        {/* ── Section 13: Decision Explainer ──────────────────────────────── */}
        <div className="flex gap-2 text-sm text-slate-400 bg-slate-700/20 rounded-lg px-3 py-2.5">
          <Info className="w-4 h-4 text-blue-400 shrink-0 mt-0.5" />
          <span className="italic">{explainer}</span>
        </div>

        {/* ── Section 2: Expected Opportunity (rejected only) ─────────────── */}
        {!c.eligible && (
          <div className="rounded-lg border border-amber-700/30 bg-amber-900/10 overflow-hidden">
            <button
              onClick={() => setOppOpen(o => !o)}
              className="flex items-center justify-between w-full px-3 py-2 text-sm text-amber-300 hover:bg-amber-900/20"
            >
              <span className="flex items-center gap-2 font-medium">
                <TrendingUp className="w-4 h-4" />
                Expected Opportunity (if this had passed)
              </span>
              {oppOpen ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
            </button>
            {oppOpen && (
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-px bg-amber-900/20 border-t border-amber-700/20">
                {[
                  { label: "Expected Return",    value: fmtPct(opp.expectedReturnPct) },
                  { label: "Expected Profit",    value: fmtCur(opp.expectedProfitINR) },
                  { label: "Capital Required",   value: fmtCur(opp.capitalRequired) },
                  { label: "Risk Amount",        value: fmtCur(opp.riskAmount) },
                ].map(({ label, value }) => (
                  <div key={label} className="bg-amber-950/30 px-3 py-2">
                    <div className="text-xs text-amber-500/70">{label}</div>
                    <div className="text-sm font-bold text-amber-300">{value}</div>
                  </div>
                ))}
              </div>
            )}
            {!oppOpen && (
              <div className="px-3 pb-2 text-xs text-amber-500/60">
                Advisory only — potential opportunity missed by this rejection.
              </div>
            )}
          </div>
        )}

        {/* ── Section 4: AI Risk Recommendations ─────────────────────────── */}
        {recommendations.length > 0 && (
          <div className="rounded-lg border border-blue-700/30 bg-blue-900/10 overflow-hidden">
            <button
              onClick={() => setRecoOpen(o => !o)}
              className="flex items-center justify-between w-full px-3 py-2 text-sm text-blue-300 hover:bg-blue-900/20"
            >
              <span className="flex items-center gap-2 font-medium">
                <Lightbulb className="w-4 h-4" />
                AI Risk Recommendations ({recommendations.length})
              </span>
              {recoOpen ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
            </button>
            {recoOpen && (
              <div className="px-3 pb-3 space-y-2 border-t border-blue-700/20 pt-2">
                {recommendations.map(({ gate: g, text }) => (
                  <div key={g.gate} className="flex gap-2">
                    <AlertTriangle className="w-3.5 h-3.5 text-amber-400 shrink-0 mt-0.5" />
                    <div>
                      <span className="text-xs font-semibold text-blue-300">{g.label}: </span>
                      <span className="text-xs text-slate-400">{text}</span>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* ── Gate results with Section 1 pass hints ──────────────────────── */}
        <div className="rounded-lg border border-slate-700/40 overflow-hidden">
          <button
            onClick={() => setGatesOpen(o => !o)}
            className="flex items-center justify-between w-full px-3 py-2 text-xs text-slate-400 hover:bg-slate-700/20"
          >
            <span>Gates: {passedGates.length} passed · {failedGates.length} failed</span>
            {gatesOpen ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </button>
          {gatesOpen && (
            <div className="border-t border-slate-700/30 divide-y divide-slate-700/20">
              {/* Failed gates first */}
              {failedGates.map(g => {
                const th    = parseThreshold(g.reason);
                const hint  = generatePassHint(g);
                return (
                  <div key={g.gate} className="px-3 py-2 bg-red-950/10">
                    <div className="flex items-start gap-2">
                      <XCircle className="w-3.5 h-3.5 text-red-400 shrink-0 mt-0.5" />
                      <div className="flex-1 min-w-0">
                        <button
                          onClick={() => onGateClick?.(g.gate)}
                          className="text-xs font-semibold text-red-300 hover:text-red-200 text-left"
                        >
                          {g.label} {g.is_global && <span className="text-slate-500">(global)</span>}
                        </button>
                        {/* Threshold breakdown */}
                        {th.actual && th.threshold && (
                          <div className="flex gap-3 mt-0.5 text-xs text-slate-500">
                            <span>Actual: <span className="text-red-400 font-mono">{th.actual}</span></span>
                            <span>Required: <span className="text-slate-400 font-mono">{th.threshold}</span></span>
                            {th.diff && <span>Gap: <span className="text-amber-400 font-mono">{th.diff}</span></span>}
                          </div>
                        )}
                        <div className="text-xs text-slate-500 mt-0.5">{g.reason}</div>
                        {/* Section 1: Pass hint */}
                        {hint && (
                          <div className="mt-1 flex items-center gap-1.5 text-xs text-teal-400 bg-teal-900/20 rounded px-2 py-1">
                            <TrendingUp className="w-3 h-3 shrink-0" />
                            {hint}
                          </div>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })}
              {/* Passed gates */}
              {passedGates.map(g => (
                <div key={g.gate} className="px-3 py-1.5 flex items-center gap-2">
                  <CheckCircle2 className="w-3.5 h-3.5 text-emerald-500 shrink-0" />
                  <button
                    onClick={() => onGateClick?.(g.gate)}
                    className="text-xs text-slate-400 hover:text-slate-300 text-left"
                  >
                    {g.label}
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Risk score factors (Section 12 breakdown) */}
        {rs.failedFactors.length > 0 && (
          <div className="text-xs text-slate-500 flex flex-wrap gap-1">
            <span>Risk factors:</span>
            {rs.failedFactors.map(f => (
              <span key={f} className="text-red-400/80 bg-red-900/20 px-1.5 py-0.5 rounded">{f}</span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
