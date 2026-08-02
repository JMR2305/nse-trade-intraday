/**
 * AiDecisionAgentPage.tsx — Phase 10C
 * AI Decision Agent — Ranked recommendations with full explainability.
 *
 * READ-ONLY · ADVISORY-ONLY · Never places orders.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import {
  Brain, ChevronDown, ChevronRight, RefreshCw, AlertTriangle,
  CheckCircle2, XCircle, Clock, Target, TrendingUp, TrendingDown,
  Minus, BarChart3, Shield, Zap, Eye,
} from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";

// ── Types ──────────────────────────────────────────────────────────────────────
interface Recommendation {
  symbol:          string;
  decision_type:   string;
  overall_score:   number;
  confidence:      number;
  priority:        number;
  expiry_at:       string;
  reward_risk_ratio: number;
  best_strategy:   string;
  scores:          Record<string, number>;
  explanation: {
    why_generated:        string;
    contributing_agents:  any[];
    supporting_signals:   string[];
    supporting_strategies: any[];
    risk_explanation:     string;
    confidence_explanation: string;
    conflicting_evidence: string[];
    expiry_reason:        string;
    natural_language_summary: string;
  };
}

// ── Colour helpers ─────────────────────────────────────────────────────────────
const DT_STYLE: Record<string, { bg: string; text: string; icon: any }> = {
  BUY_CANDIDATE:   { bg: "bg-emerald-500/10 border-emerald-500/30", text: "text-emerald-400", icon: TrendingUp    },
  ACCUMULATE:      { bg: "bg-teal-500/10 border-teal-500/30",       text: "text-teal-400",    icon: TrendingUp    },
  WATCH:           { bg: "bg-blue-500/10 border-blue-500/30",        text: "text-blue-400",    icon: Eye           },
  SELL_CANDIDATE:  { bg: "bg-rose-500/10 border-rose-500/30",        text: "text-rose-400",    icon: TrendingDown  },
  REDUCE_EXPOSURE: { bg: "bg-orange-500/10 border-orange-500/30",    text: "text-orange-400",  icon: AlertTriangle },
  AVOID:           { bg: "bg-red-500/10 border-red-500/30",          text: "text-red-400",     icon: XCircle       },
  NO_ACTION:       { bg: "bg-gray-500/10 border-gray-500/30",        text: "text-gray-400",    icon: Minus         },
};

const CONF_BAR = (c: number) =>
  c >= 0.8 ? "bg-emerald-500" : c >= 0.65 ? "bg-teal-500" : c >= 0.5 ? "bg-amber-500" : "bg-red-500";

const PRIO_LABEL: Record<number, string> = { 1: "URGENT", 2: "HIGH", 3: "MEDIUM", 4: "LOW", 5: "BACKGROUND" };
const PRIO_CLR:   Record<number, string> = {
  1: "text-red-400", 2: "text-orange-400", 3: "text-amber-400",
  4: "text-blue-400", 5: "text-gray-400",
};

// ── Score Bar ──────────────────────────────────────────────────────────────────
function ScoreBar({ label, value }: { label: string; value: number }) {
  const pct = Math.round(value);
  const clr = pct >= 70 ? "bg-emerald-500" : pct >= 50 ? "bg-amber-500" : "bg-red-500";
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="text-muted-foreground w-24 shrink-0 capitalize">{label.replace("_", " ")}</span>
      <div className="flex-1 bg-muted rounded-full h-1.5 overflow-hidden">
        <div className={`${clr} h-full rounded-full`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-muted-foreground w-8 text-right">{pct}</span>
    </div>
  );
}

// ── Recommendation Card ────────────────────────────────────────────────────────
function RecCard({ rec }: { rec: Recommendation }) {
  const [open, setOpen] = useState(false);
  const dt    = DT_STYLE[rec.decision_type] ?? DT_STYLE.NO_ACTION;
  const Icon  = dt.icon;
  const expl  = rec.explanation;
  const pct   = Math.round(rec.confidence * 100);

  return (
    <div className={`border rounded-xl overflow-hidden ${dt.bg}`}>
      {/* Header row */}
      <button
        onClick={() => setOpen(!open)}
        className="w-full text-left px-4 py-3 flex items-center gap-3"
      >
        <Icon className={`w-4 h-4 shrink-0 ${dt.text}`} />
        <span className="font-semibold text-sm flex-1">{rec.symbol}</span>

        {/* Decision badge */}
        <span className={`text-xs font-medium px-2 py-0.5 rounded-full border ${dt.bg} ${dt.text}`}>
          {rec.decision_type.replace("_", " ")}
        </span>

        {/* Score */}
        <span className="text-xs text-muted-foreground hidden sm:block">
          Score {rec.overall_score.toFixed(0)}/100
        </span>

        {/* Confidence bar */}
        <div className="w-20 hidden sm:flex items-center gap-1">
          <div className="flex-1 bg-muted rounded-full h-1.5">
            <div className={`${CONF_BAR(rec.confidence)} h-full rounded-full`}
              style={{ width: `${pct}%` }} />
          </div>
          <span className="text-xs text-muted-foreground w-7">{pct}%</span>
        </div>

        {/* Priority */}
        <span className={`text-xs font-medium hidden lg:block w-20 ${PRIO_CLR[rec.priority]}`}>
          P{rec.priority} {PRIO_LABEL[rec.priority]}
        </span>

        {open ? <ChevronDown className="w-4 h-4 text-muted-foreground" />
               : <ChevronRight className="w-4 h-4 text-muted-foreground" />}
      </button>

      {/* Expanded detail */}
      {open && (
        <div className="px-4 pb-4 space-y-4 border-t border-white/5 pt-3">

          {/* Natural language summary */}
          <p className="text-sm text-muted-foreground">{expl.natural_language_summary}</p>

          {/* Why generated */}
          <div>
            <p className="text-xs font-semibold text-muted-foreground uppercase mb-1">Why Generated</p>
            <p className="text-sm">{expl.why_generated}</p>
          </div>

          {/* Score breakdown */}
          <div>
            <p className="text-xs font-semibold text-muted-foreground uppercase mb-2">Score Breakdown</p>
            <div className="space-y-1.5">
              {Object.entries(rec.scores).map(([k, v]) => (
                <ScoreBar key={k} label={k} value={v} />
              ))}
            </div>
          </div>

          {/* Two-column: contributing agents + signals */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <p className="text-xs font-semibold text-muted-foreground uppercase mb-2">Contributing Agents</p>
              <div className="space-y-1">
                {expl.contributing_agents.map((ag: any) => (
                  <div key={ag.agent_id} className="flex items-center justify-between text-xs">
                    <span className="text-muted-foreground">{ag.name}</span>
                    <div className="flex items-center gap-1">
                      <span>{ag.score?.toFixed(0)}/100</span>
                      <span className="text-muted-foreground">({ag.weight_pct}%)</span>
                      {ag.influenced_decision && <CheckCircle2 className="w-3 h-3 text-emerald-400" />}
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <div>
              <p className="text-xs font-semibold text-muted-foreground uppercase mb-2">Supporting Signals</p>
              {expl.supporting_signals.length > 0 ? (
                <ul className="space-y-1">
                  {expl.supporting_signals.map((s, i) => (
                    <li key={i} className="text-xs text-muted-foreground">{s}</li>
                  ))}
                </ul>
              ) : (
                <p className="text-xs text-muted-foreground italic">No specific signals detected</p>
              )}
            </div>
          </div>

          {/* Supporting strategies */}
          {expl.supporting_strategies.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-muted-foreground uppercase mb-2">Supporting Strategies</p>
              <div className="flex flex-wrap gap-2">
                {expl.supporting_strategies.map((s: any) => (
                  <div key={s.strategy}
                    className="text-xs bg-violet-500/10 border border-violet-500/20 rounded-lg px-2 py-1">
                    <span className="text-violet-400 font-medium">{s.strategy}</span>
                    <span className="text-muted-foreground ml-1">{s.score?.toFixed(0)}/100</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Conflict resolution */}
          {expl.conflicting_evidence.length > 0 && (
            <div>
              <p className="text-xs font-semibold text-amber-400 uppercase mb-2">Conflicting Evidence</p>
              <div className="space-y-1">
                {expl.conflicting_evidence.map((c, i) => (
                  <div key={i} className="flex items-start gap-2 text-xs">
                    <AlertTriangle className="w-3 h-3 text-amber-400 shrink-0 mt-0.5" />
                    <p className="text-muted-foreground">{c}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Risk + Confidence explanations */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <p className="text-xs font-semibold text-muted-foreground uppercase mb-1">Risk Explanation</p>
              <p className="text-xs text-muted-foreground">{expl.risk_explanation}</p>
            </div>
            <div>
              <p className="text-xs font-semibold text-muted-foreground uppercase mb-1">Confidence Explanation</p>
              <p className="text-xs text-muted-foreground">{expl.confidence_explanation}</p>
            </div>
          </div>

          {/* Expiry */}
          <div className="flex items-center gap-2 text-xs text-muted-foreground border-t border-white/5 pt-2">
            <Clock className="w-3 h-3" />
            <span>Expires: {rec.expiry_at}</span>
            <span>·</span>
            <span>{expl.expiry_reason}</span>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Decision Counts Summary ────────────────────────────────────────────────────
function DecisionCountsBar({ counts }: { counts: Record<string, number> }) {
  const order = ["BUY_CANDIDATE", "ACCUMULATE", "WATCH", "SELL_CANDIDATE",
                  "REDUCE_EXPOSURE", "AVOID", "NO_ACTION"];
  const clrs: Record<string, string> = {
    BUY_CANDIDATE: "bg-emerald-500", ACCUMULATE: "bg-teal-500",
    WATCH: "bg-blue-500", SELL_CANDIDATE: "bg-rose-500",
    REDUCE_EXPOSURE: "bg-orange-500", AVOID: "bg-red-600", NO_ACTION: "bg-gray-600",
  };
  return (
    <div className="flex flex-wrap gap-2">
      {order.map((dt) => {
        const n = counts[dt] ?? 0;
        return (
          <div key={dt} className="flex items-center gap-1.5">
            <span className={`w-2.5 h-2.5 rounded-full ${clrs[dt]}`} />
            <span className="text-xs text-muted-foreground">{dt.replace("_", " ")}</span>
            <span className="text-xs font-medium">{n}</span>
          </div>
        );
      })}
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────────
export default function AiDecisionAgentPage() {
  const [filter, setFilter] = useState<string>("ALL");

  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey:  ["ai-decision-agent", "snapshot"],
    queryFn:   () => apiJson("decision-layer/ai-decision/snapshot"),
    refetchInterval: 60_000,
    retry: 1,
    staleTime: 30_000,
  });

  const snap = data as any;
  const recs: Recommendation[] = snap?.recommendations ?? [];
  const counts: Record<string, number> = snap?.decision_counts ?? {};

  const filtered = filter === "ALL" ? recs : recs.filter((r) => r.decision_type === filter);

  const DT_OPTIONS = [
    "ALL", "BUY_CANDIDATE", "ACCUMULATE", "WATCH",
    "SELL_CANDIDATE", "REDUCE_EXPOSURE", "AVOID", "NO_ACTION",
  ];

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 space-y-5">

      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-xl bg-indigo-500/10 border border-indigo-500/20">
            <Brain className="w-6 h-6 text-indigo-400" />
          </div>
          <div>
            <h1 className="text-xl font-bold">AI Decision Agent</h1>
            <p className="text-xs text-muted-foreground">
              Phase 10C · Explainable recommendations · READ-ONLY · ADVISORY-ONLY · Never places orders
            </p>
          </div>
        </div>
        <button
          onClick={() => refetch()}
          disabled={isFetching}
          className="flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground px-3 py-1.5 border border-border rounded-lg"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${isFetching ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>

      {/* Advisory banner */}
      <Alert className="border-indigo-500/20 bg-indigo-500/5">
        <Brain className="w-4 h-4 text-indigo-400" />
        <AlertDescription className="text-xs text-indigo-200">
          READ-ONLY · ADVISORY-ONLY — All recommendations are for informational purposes only.
          This agent evaluates candidates across 6 analytical dimensions and produces explainable
          ranked recommendations. It <strong>never</strong> places orders.
        </AlertDescription>
      </Alert>

      {/* Loading */}
      {isLoading && (
        <div className="space-y-3">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="bg-card border border-border rounded-xl p-4 animate-pulse h-20" />
          ))}
        </div>
      )}

      {/* Error */}
      {error && !isLoading && (
        <Alert className="border-red-500/20 bg-red-500/5">
          <AlertTriangle className="w-4 h-4 text-red-400" />
          <AlertDescription className="text-xs text-red-300">
            Failed to load AI Decision snapshot. Ensure AI_DECISION_AGENT_ENABLED=true.
          </AlertDescription>
        </Alert>
      )}

      {/* Content */}
      {!isLoading && snap?.available && (
        <>
          {/* KPI bar */}
          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3">
            {[
              { label: "Candidates",     value: snap.total_candidates     ?? 0, icon: Target,    color: "text-teal-400" },
              { label: "Recommendations",value: snap.total_recommendations ?? 0, icon: BarChart3, color: "text-indigo-400" },
              { label: "Pending",        value: snap.pending_recommendations ?? 0, icon: Clock,  color: "text-amber-400" },
              { label: "Avg Confidence", value: `${Math.round((snap.avg_confidence ?? 0) * 100)}%`, icon: Zap, color: "text-violet-400" },
              { label: "Market Regime",  value: snap.market_regime ?? "—", icon: TrendingUp,   color: "text-blue-400" },
              { label: "Risk Level",     value: snap.risk_level   ?? "—", icon: Shield,        color: "text-rose-400" },
            ].map(({ label, value, icon: Icon, color }) => (
              <div key={label} className="bg-card border border-border rounded-xl p-3 flex flex-col gap-1">
                <div className="flex items-center gap-1.5">
                  <Icon className={`w-3.5 h-3.5 ${color}`} />
                  <span className="text-xs text-muted-foreground">{label}</span>
                </div>
                <p className={`text-lg font-bold ${color}`}>{value}</p>
              </div>
            ))}
          </div>

          {/* Decision distribution */}
          <div className="bg-card border border-border rounded-xl p-4">
            <p className="text-xs font-semibold text-muted-foreground uppercase mb-2">Decision Distribution</p>
            <DecisionCountsBar counts={counts} />
            <p className="text-xs text-muted-foreground mt-2">
              Latency: {snap.decision_latency_ms?.toFixed(0)} ms ·
              Generated: {snap.generated_at}
            </p>
          </div>

          {/* Filter tabs */}
          <div className="flex flex-wrap gap-2">
            {DT_OPTIONS.map((opt) => (
              <button
                key={opt}
                onClick={() => setFilter(opt)}
                className={`text-xs px-3 py-1 rounded-full border transition-colors ${
                  filter === opt
                    ? "bg-indigo-600 border-indigo-600 text-white"
                    : "border-border text-muted-foreground hover:border-indigo-500"
                }`}
              >
                {opt === "ALL" ? `All (${recs.length})` : `${opt.replace("_", " ")} (${counts[opt] ?? 0})`}
              </button>
            ))}
          </div>

          {/* Recommendation cards */}
          <div className="space-y-2">
            {filtered.length === 0 ? (
              <div className="bg-card border border-border rounded-xl p-6 text-center text-muted-foreground text-sm">
                No recommendations match this filter.
              </div>
            ) : (
              filtered.map((rec) => <RecCard key={rec.symbol} rec={rec} />)
            )}
          </div>

          <p className="text-xs text-center text-muted-foreground pb-2">
            READ-ONLY · ADVISORY-ONLY · {recs.length} recommendations across{" "}
            {snap.total_candidates} candidates · Not financial advice
          </p>
        </>
      )}
    </div>
  );
}
