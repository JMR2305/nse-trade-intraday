/**
 * RiskDecisionReportPage.tsx
 *
 * Risk Agent Decision Report — shows every candidate evaluated in the last
 * entry eligibility run, with per-gate pass/fail results, exact thresholds,
 * and a gate-pressure analysis revealing which rules filter most opportunities.
 *
 * READ-ONLY · ADVISORY-ONLY · PAPER TRADING / RESEARCH ONLY.
 */
import React, { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  ShieldAlert, CheckCircle2, XCircle, RefreshCw,
  AlertTriangle, Info, ChevronDown, ChevronRight,
  BarChart3, Target, TrendingUp, Activity,
  Layers, DollarSign, Clock, Filter,
} from "lucide-react";
import { apiJson } from "@/lib/api";

// ── Types ─────────────────────────────────────────────────────────────────────

interface Gate {
  gate:      string;
  label:     string;
  passed:    boolean;
  reason:    string;
  is_global: boolean;
}

interface Sizing {
  quantity:       number;
  entry_price:    number;
  stop_loss:      number;
  target_price:   number;
  position_value: number;
  risk_amount:    number;
  rr_ratio:       number;
}

interface Candidate {
  symbol:                 string;
  sector:                 string;
  recommendation:         string;
  eligible:               boolean;
  failed_gates:           string[];
  gates:                  Gate[];
  sizing:                 Sizing;
  confidence:             number;
  opportunity_score:      number;
  trade_quality_score:    number;
  strategy_id?:           string;
  strategy_name?:         string;
  regime?:                string;
  expected_holding_days?: number;
}

interface GatePressure {
  gate_id:     string;
  label:       string;
  is_global:   boolean;
  blocked:     number;
  blocked_pct: number;
}

interface Report {
  available:      boolean;
  reason?:        string;
  evaluated_at?:  string;
  scan_id?:       string;
  snapshot_ts?:   string;
  market_state?:  string;
  global_gates?:  Gate[];
  global_pass?:   boolean;
  candidates?:    Candidate[];
  total_count?:   number;
  eligible_count?:number;
  blocked_count?: number;
  gate_pressure?: GatePressure[];
  top_blockers?:  string[];
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const fmt1 = (n: number | null | undefined) => Number(n ?? 0).toFixed(1);
const fmtCur = (n: number | null | undefined) =>
  `₹${Number(n ?? 0).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
const fmtPct = (n: number | null | undefined) => `${Number(n ?? 0).toFixed(1)}%`;

function tsLabel(iso?: string) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("en-IN", {
      timeZone: "Asia/Kolkata",
      hour12: false,
      month: "short", day: "numeric",
      hour: "2-digit", minute: "2-digit",
    });
  } catch { return iso; }
}

function confColor(v: number) {
  if (v >= 80) return "text-emerald-400";
  if (v >= 65) return "text-teal-400";
  if (v >= 50) return "text-yellow-400";
  return "text-red-400";
}

function pressureBar(pct: number) {
  if (pct >= 80) return "bg-red-500";
  if (pct >= 50) return "bg-amber-500";
  if (pct >= 25) return "bg-yellow-500";
  return "bg-teal-500";
}

// Parse the threshold value from reason strings like "Confidence 72.0 vs minimum 75.0"
function parseThreshold(reason: string): { actual?: string; threshold?: string } {
  // Pattern: "X Y vs minimum Z" or "X Y (cap Z%)" or "X Y vs limit Z"
  const vsMin = reason.match(/(\d[\d.]*)\s+vs\s+minimum\s+([\d.]+)/i);
  if (vsMin) return { actual: vsMin[1], threshold: vsMin[2] };
  const vsCap = reason.match(/(\d[\d.]*%?)\s+\(cap\s+([\d.]+%?)\)/i);
  if (vsCap) return { actual: vsCap[1], threshold: vsCap[2] };
  const vsLimit = reason.match(/(\d[\d.]*)\s+vs\s+limit\s+([-\d.₹]+)/i);
  if (vsLimit) return { actual: vsLimit[1], threshold: vsLimit[2] };
  return {};
}

// ── UI primitives ─────────────────────────────────────────────────────────────

function Card({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-slate-800/60 border border-slate-700/50 rounded-xl p-4 ${className ?? ""}`}>
      {children}
    </div>
  );
}

function Badge({ pass }: { pass: boolean }) {
  return pass ? (
    <span className="inline-flex items-center gap-1 text-xs font-semibold text-emerald-400 bg-emerald-900/30 border border-emerald-700/40 rounded-full px-2 py-0.5">
      <CheckCircle2 className="w-3 h-3" /> PASS
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 text-xs font-semibold text-red-400 bg-red-900/30 border border-red-700/40 rounded-full px-2 py-0.5">
      <XCircle className="w-3 h-3" /> FAIL
    </span>
  );
}

function VerdictBadge({ eligible }: { eligible: boolean }) {
  return eligible ? (
    <span className="inline-flex items-center gap-1.5 text-sm font-bold text-emerald-300 bg-emerald-900/30 border border-emerald-700/40 rounded-lg px-3 py-1.5">
      <CheckCircle2 className="w-4 h-4" /> APPROVED
    </span>
  ) : (
    <span className="inline-flex items-center gap-1.5 text-sm font-bold text-red-300 bg-red-900/30 border border-red-700/40 rounded-lg px-3 py-1.5">
      <XCircle className="w-4 h-4" /> REJECTED
    </span>
  );
}

// ── Gate Row ──────────────────────────────────────────────────────────────────

function GateRow({ gate }: { gate: Gate }) {
  const { actual, threshold } = parseThreshold(gate.reason);
  const hasThreshold = actual !== undefined && threshold !== undefined;

  return (
    <div className={`flex items-start gap-3 py-2.5 border-b border-slate-700/30 last:border-0 ${
      gate.is_global ? "opacity-60" : ""
    }`}>
      <div className="mt-0.5 flex-shrink-0">
        {gate.passed
          ? <CheckCircle2 className="w-4 h-4 text-emerald-400" />
          : <XCircle className="w-4 h-4 text-red-400" />
        }
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 flex-wrap">
          <span className={`text-xs font-semibold ${gate.passed ? "text-slate-300" : "text-red-300"}`}>
            {gate.label}
          </span>
          {gate.is_global && (
            <span className="text-[10px] text-slate-500 bg-slate-700/50 rounded px-1.5 py-0.5">global</span>
          )}
        </div>
        {hasThreshold && !gate.passed ? (
          <div className="flex items-center gap-3 mt-1">
            <span className="text-xs text-red-400 font-mono">Actual: <strong>{actual}</strong></span>
            <span className="text-xs text-slate-500">·</span>
            <span className="text-xs text-slate-400 font-mono">Required: <strong>{threshold}</strong></span>
          </div>
        ) : (
          <p className="text-xs text-slate-500 mt-0.5 leading-relaxed">{gate.reason}</p>
        )}
      </div>
      <div className="flex-shrink-0 mt-0.5">
        <Badge pass={gate.passed} />
      </div>
    </div>
  );
}

// ── Candidate Card ────────────────────────────────────────────────────────────

function CandidateCard({ c }: { c: Candidate }) {
  const [open, setOpen] = useState(!c.eligible);

  const perSymbolGates = c.gates.filter(g => !g.is_global);
  const failedCount    = c.gates.filter(g => !g.passed).length;

  return (
    <Card className="overflow-hidden">
      {/* Header row */}
      <button
        className="w-full flex items-center justify-between gap-3 text-left"
        onClick={() => setOpen(o => !o)}
      >
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-10 h-10 rounded-lg bg-slate-700/60 border border-slate-600/50 flex items-center justify-center flex-shrink-0">
            <span className="text-sm font-bold text-slate-200">{c.symbol.slice(0, 3)}</span>
          </div>
          <div className="min-w-0">
            <p className="text-sm font-bold text-slate-100 truncate">{c.symbol}</p>
            <p className="text-xs text-slate-500 truncate">
              {c.strategy_name || c.strategy_id || "—"} · {c.sector}
              {c.regime ? ` · ${c.regime}` : ""}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3 flex-shrink-0">
          {!c.eligible && (
            <span className="hidden sm:flex items-center gap-1 text-xs text-red-400">
              <XCircle className="w-3 h-3" />
              {failedCount} gate{failedCount !== 1 ? "s" : ""} failed
            </span>
          )}
          <VerdictBadge eligible={c.eligible} />
          {open
            ? <ChevronDown className="w-4 h-4 text-slate-500" />
            : <ChevronRight className="w-4 h-4 text-slate-500" />
          }
        </div>
      </button>

      {/* KPI row — always visible */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-3">
        {[
          {
            icon: <Activity className="w-3 h-3" />,
            label: "Confidence",
            value: `${fmt1(c.confidence)}%`,
            color: confColor(c.confidence),
          },
          {
            icon: <Target className="w-3 h-3" />,
            label: "Opportunity",
            value: fmt1(c.opportunity_score),
            color: c.opportunity_score >= 70 ? "text-emerald-400" : c.opportunity_score >= 55 ? "text-yellow-400" : "text-red-400",
          },
          {
            icon: <TrendingUp className="w-3 h-3" />,
            label: "Risk / Reward",
            value: `${fmt1(c.sizing.rr_ratio)}×`,
            color: c.sizing.rr_ratio >= 2 ? "text-emerald-400" : c.sizing.rr_ratio >= 1.5 ? "text-yellow-400" : "text-red-400",
          },
          {
            icon: <BarChart3 className="w-3 h-3" />,
            label: "Trade Quality",
            value: fmt1(c.trade_quality_score),
            color: c.trade_quality_score >= 70 ? "text-emerald-400" : c.trade_quality_score >= 55 ? "text-yellow-400" : "text-red-400",
          },
        ].map(({ icon, label, value, color }) => (
          <div key={label} className="bg-slate-700/30 rounded-lg p-2.5">
            <div className="flex items-center gap-1 text-slate-500 mb-1">
              {icon}
              <span className="text-[10px]">{label}</span>
            </div>
            <p className={`text-base font-bold ${color}`}>{value}</p>
          </div>
        ))}
      </div>

      {/* Sizing row — always visible */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 mt-2">
        {[
          { label: "Position Size", value: `${c.sizing.quantity} sh` },
          { label: "Capital Required", value: fmtCur(c.sizing.position_value) },
          { label: "Stop Loss", value: fmtCur(c.sizing.stop_loss) },
          { label: "Target", value: fmtCur(c.sizing.target_price) },
        ].map(({ label, value }) => (
          <div key={label} className="bg-slate-700/20 rounded-lg px-2.5 py-2">
            <p className="text-[10px] text-slate-500 mb-0.5">{label}</p>
            <p className="text-xs font-semibold text-slate-300">{value}</p>
          </div>
        ))}
      </div>

      {/* Sector / exposure row */}
      <div className="flex flex-wrap gap-4 mt-2 px-0.5">
        <div>
          <span className="text-[10px] text-slate-500">Sector</span>
          <p className="text-xs text-slate-300 font-medium">{c.sector || "—"}</p>
        </div>
        <div>
          <span className="text-[10px] text-slate-500">Entry Price</span>
          <p className="text-xs text-slate-300 font-medium">{fmtCur(c.sizing.entry_price)}</p>
        </div>
        <div>
          <span className="text-[10px] text-slate-500">Risk Amount</span>
          <p className="text-xs text-slate-300 font-medium">{fmtCur(c.sizing.risk_amount)}</p>
        </div>
        {c.expected_holding_days != null && (
          <div>
            <span className="text-[10px] text-slate-500">Expected Hold</span>
            <p className="text-xs text-slate-300 font-medium">{c.expected_holding_days}d</p>
          </div>
        )}
      </div>

      {/* Expandable gate detail */}
      {open && (
        <div className="mt-4 border-t border-slate-700/50 pt-4">
          <p className="text-xs font-semibold text-slate-400 uppercase tracking-wide mb-2">
            Gate Results
          </p>
          <div>
            {perSymbolGates.map(g => (
              <GateRow key={g.gate} gate={g} />
            ))}
          </div>
          {/* Final verdict */}
          <div className={`mt-3 rounded-lg px-3 py-2.5 flex items-center gap-2 ${
            c.eligible
              ? "bg-emerald-900/20 border border-emerald-700/30"
              : "bg-red-900/20 border border-red-700/30"
          }`}>
            {c.eligible
              ? <CheckCircle2 className="w-4 h-4 text-emerald-400 flex-shrink-0" />
              : <XCircle      className="w-4 h-4 text-red-400 flex-shrink-0" />
            }
            <div>
              <p className={`text-xs font-bold ${c.eligible ? "text-emerald-300" : "text-red-300"}`}>
                Final Decision: {c.eligible ? "APPROVED" : "REJECTED"}
              </p>
              {!c.eligible && c.failed_gates.length > 0 && (
                <p className="text-[11px] text-slate-400 mt-0.5">
                  Failed: {c.failed_gates.join(", ")}
                </p>
              )}
            </div>
          </div>
        </div>
      )}
    </Card>
  );
}

// ── Gate Pressure Chart ───────────────────────────────────────────────────────

function GatePressurePanel({ pressure, total }: { pressure: GatePressure[]; total: number }) {
  if (!pressure.length) return null;
  return (
    <Card>
      <div className="flex items-center gap-2 mb-3">
        <Filter className="w-4 h-4 text-amber-400" />
        <h3 className="text-sm font-semibold text-slate-200">Gate Pressure</h3>
        <span className="text-xs text-slate-500">— which rules filter the most opportunities</span>
      </div>
      <div className="space-y-2">
        {pressure.map(g => (
          <div key={g.gate_id} className="flex items-center gap-3">
            <div className="w-36 flex-shrink-0">
              <p className="text-xs text-slate-300 truncate">{g.label}</p>
              {g.is_global && (
                <span className="text-[10px] text-slate-600">global</span>
              )}
            </div>
            <div className="flex-1 bg-slate-700/40 rounded-full h-2 overflow-hidden">
              <div
                className={`h-full rounded-full ${pressureBar(g.blocked_pct)}`}
                style={{ width: `${g.blocked_pct}%` }}
              />
            </div>
            <div className="w-20 text-right flex-shrink-0">
              <span className="text-xs font-semibold text-slate-300">
                {g.blocked}/{total}
              </span>
              <span className="text-[10px] text-slate-500 ml-1">
                ({fmtPct(g.blocked_pct)})
              </span>
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

// ── Global Gates Panel ────────────────────────────────────────────────────────

function GlobalGatesPanel({ gates }: { gates: Gate[] }) {
  const failed = gates.filter(g => !g.passed);
  if (!failed.length) return null;
  return (
    <div className="bg-amber-900/20 border border-amber-700/30 rounded-xl p-4">
      <div className="flex items-center gap-2 mb-3">
        <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0" />
        <p className="text-sm font-semibold text-amber-300">
          {failed.length} Global Gate{failed.length !== 1 ? "s" : ""} Failed
        </p>
        <span className="text-xs text-amber-500">— all candidates blocked regardless of individual scores</span>
      </div>
      <div className="space-y-0">
        {failed.map(g => (
          <GateRow key={g.gate} gate={g} />
        ))}
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

type FilterMode = "all" | "rejected" | "approved";

export default function RiskDecisionReportPage() {
  const [filter, setFilter] = useState<FilterMode>("rejected");
  const [search, setSearch] = useState("");

  const { data, isLoading, error, refetch, isRefetching } = useQuery<Report>({
    queryKey: ["risk-decision-report"],
    queryFn: () => apiJson("phase15/risk-decision-report"),
    staleTime: 60_000,
    retry: 1,
  });

  // ── Loading / error states ─────────────────────────────────────────────────
  if (isLoading) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <div className="flex items-center gap-3 text-slate-400">
          <RefreshCw className="w-5 h-5 animate-spin" />
          <span>Loading Risk Decision Report…</span>
        </div>
      </div>
    );
  }

  if (error || !data?.available) {
    return (
      <div className="min-h-screen bg-slate-900 p-6">
        <div className="max-w-2xl mx-auto mt-20">
          <Card className="text-center py-10">
            <ShieldAlert className="w-10 h-10 text-amber-500 mx-auto mb-3" />
            <p className="text-slate-200 font-semibold mb-1">No Evaluation Available</p>
            <p className="text-slate-500 text-sm">
              {data?.reason || (error instanceof Error ? error.message : "Run a scan first to populate the Risk Decision Report.")}
            </p>
            <button
              onClick={() => refetch()}
              className="mt-4 text-xs bg-slate-700 hover:bg-slate-600 text-slate-200 rounded-lg px-4 py-2 transition-colors"
            >
              Retry
            </button>
          </Card>
        </div>
      </div>
    );
  }

  const candidates = data.candidates ?? [];
  const filtered = candidates
    .filter(c => filter === "all" || (filter === "rejected" ? !c.eligible : c.eligible))
    .filter(c => !search || c.symbol.toLowerCase().includes(search.toLowerCase())
      || (c.strategy_name ?? "").toLowerCase().includes(search.toLowerCase()));

  const rejectedCount  = candidates.filter(c => !c.eligible).length;
  const approvedCount  = candidates.filter(c => c.eligible).length;
  const globalFailed   = (data.global_gates ?? []).filter(g => !g.passed);

  return (
    <div className="min-h-screen bg-slate-900 text-slate-100">
      <div className="max-w-5xl mx-auto px-4 py-6 space-y-6">

        {/* Page header */}
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-amber-500/20 border border-amber-500/30 flex items-center justify-center">
              <ShieldAlert className="w-5 h-5 text-amber-400" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-slate-100">Risk Decision Report</h1>
              <p className="text-xs text-slate-500">
                Last evaluation: {tsLabel(data.evaluated_at)}
                {data.market_state ? ` · Market ${data.market_state}` : ""}
                {data.scan_id ? ` · Scan ${data.scan_id.slice(0, 16)}` : ""}
              </p>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <div className="flex items-center gap-2 bg-teal-900/20 border border-teal-700/30 rounded-lg px-3 py-1.5 text-xs text-teal-300">
              <Info className="w-3 h-3 flex-shrink-0" />
              <span>ADVISORY-ONLY · PAPER TRADING</span>
            </div>
            <button
              onClick={() => refetch()}
              disabled={isRefetching}
              className="flex items-center gap-1.5 text-xs bg-slate-700 hover:bg-slate-600 disabled:opacity-50 text-slate-200 rounded-lg px-3 py-1.5 transition-colors"
            >
              <RefreshCw className={`w-3 h-3 ${isRefetching ? "animate-spin" : ""}`} />
              Refresh
            </button>
          </div>
        </div>

        {/* Summary KPI bar */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            {
              icon: <Layers className="w-4 h-4 text-slate-400" />,
              label: "Candidates",
              value: String(candidates.length),
              color: "text-slate-200",
            },
            {
              icon: <XCircle className="w-4 h-4 text-red-400" />,
              label: "Rejected",
              value: String(rejectedCount),
              color: "text-red-400",
            },
            {
              icon: <CheckCircle2 className="w-4 h-4 text-emerald-400" />,
              label: "Approved",
              value: String(approvedCount),
              color: "text-emerald-400",
            },
            {
              icon: <ShieldAlert className="w-4 h-4 text-amber-400" />,
              label: "Global Gates Failed",
              value: String(globalFailed.length),
              color: globalFailed.length > 0 ? "text-amber-400" : "text-emerald-400",
            },
          ].map(({ icon, label, value, color }) => (
            <Card key={label} className="flex items-center gap-3 py-3">
              {icon}
              <div>
                <p className="text-[10px] text-slate-500">{label}</p>
                <p className={`text-lg font-bold ${color}`}>{value}</p>
              </div>
            </Card>
          ))}
        </div>

        {/* Top blockers summary */}
        {data.top_blockers && data.top_blockers.length > 0 && (
          <div className="flex items-center gap-2 bg-slate-800/40 border border-slate-700/30 rounded-xl px-4 py-3 flex-wrap">
            <AlertTriangle className="w-4 h-4 text-amber-400 flex-shrink-0" />
            <span className="text-xs text-slate-400">Top rejection reasons:</span>
            {data.top_blockers.map(b => (
              <span key={b} className="text-xs font-semibold text-amber-300 bg-amber-900/20 border border-amber-700/30 rounded-full px-2.5 py-0.5">
                {b}
              </span>
            ))}
          </div>
        )}

        {/* Global gates warning */}
        {globalFailed.length > 0 && (
          <GlobalGatesPanel gates={data.global_gates ?? []} />
        )}

        {/* Gate pressure */}
        {data.gate_pressure && data.gate_pressure.length > 0 && (
          <GatePressurePanel
            pressure={data.gate_pressure.filter(g => !g.is_global)}
            total={candidates.length}
          />
        )}

        {/* Candidate list controls */}
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex rounded-lg overflow-hidden border border-slate-700/50">
            {(["all", "rejected", "approved"] as FilterMode[]).map(mode => (
              <button
                key={mode}
                onClick={() => setFilter(mode)}
                className={`px-3 py-1.5 text-xs font-medium capitalize transition-colors ${
                  filter === mode
                    ? "bg-amber-500/20 text-amber-300 border-r border-slate-700/50"
                    : "bg-slate-800/60 text-slate-400 hover:text-slate-300 border-r border-slate-700/50 last:border-0"
                }`}
              >
                {mode === "all" ? `All (${candidates.length})` :
                 mode === "rejected" ? `Rejected (${rejectedCount})` :
                 `Approved (${approvedCount})`}
              </button>
            ))}
          </div>
          <input
            type="text"
            placeholder="Search symbol or strategy…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="flex-1 min-w-40 bg-slate-800/60 border border-slate-700/50 rounded-lg px-3 py-1.5 text-xs text-slate-200 placeholder-slate-600 outline-none focus:border-amber-500/50"
          />
          <span className="text-xs text-slate-500">{filtered.length} shown</span>
        </div>

        {/* Candidate cards */}
        {filtered.length === 0 ? (
          <Card className="py-12 text-center">
            <DollarSign className="w-8 h-8 text-slate-600 mx-auto mb-3" />
            <p className="text-slate-400 text-sm">No candidates match the current filter.</p>
          </Card>
        ) : (
          <div className="space-y-4">
            {filtered.map(c => (
              <CandidateCard key={c.symbol} c={c} />
            ))}
          </div>
        )}

        {/* Footer */}
        <p className="text-center text-[10px] text-slate-600 pb-4">
          Risk Decision Report · PAPER TRADING / RESEARCH ONLY · Evaluation ID {data.scan_id?.slice(0, 24) ?? "—"}
        </p>
      </div>
    </div>
  );
}
