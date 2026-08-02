/**
 * ExecutionAgentPage.tsx — Phase 10C
 * Execution Agent — Pre-execution validation, execution plans, paper orders.
 *
 * READ-ONLY · ADVISORY-ONLY
 * Paper execution by default. Live execution requires explicit flag + operator confirmation.
 * NEVER places autonomous live orders.
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import {
  Briefcase, RefreshCw, AlertTriangle, CheckCircle2, XCircle,
  Clock, Shield, Zap, Target, BarChart3, TrendingUp, ChevronDown, ChevronRight,
  ArrowUpCircle, AlertCircle,
} from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";

// ── Helpers ────────────────────────────────────────────────────────────────────
const MODE_STYLE: Record<string, { bg: string; text: string; label: string }> = {
  PAPER:     { bg: "bg-teal-600",  text: "text-white", label: "📄 PAPER" },
  SEMI_AUTO: { bg: "bg-amber-600", text: "text-white", label: "⚡ SEMI-AUTO" },
  LIVE:      { bg: "bg-red-700",   text: "text-white", label: "🔴 LIVE" },
};

const CHECK_CLR = (passed: boolean) =>
  passed ? "text-emerald-400" : "text-red-400";

// ── Paper Order Card ───────────────────────────────────────────────────────────
function PaperOrderCard({ order }: { order: any }) {
  const side = order.side === "BUY" ? "text-emerald-400" : "text-rose-400";
  return (
    <div className="border border-border rounded-xl p-4 space-y-2">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className={`text-sm font-bold ${side}`}>{order.side}</span>
          <span className="font-semibold">{order.symbol}</span>
          <span className="text-xs text-muted-foreground">× {order.qty}</span>
        </div>
        <div className="text-xs bg-teal-500/10 border border-teal-500/20 text-teal-300 px-2 py-0.5 rounded-full">
          {order.status}
        </div>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
        <div>
          <p className="text-muted-foreground">Entry</p>
          <p className="font-medium">₹{Number(order.price).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</p>
        </div>
        <div>
          <p className="text-muted-foreground">Stop Loss</p>
          <p className="font-medium text-rose-400">₹{Number(order.stop_loss).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</p>
        </div>
        <div>
          <p className="text-muted-foreground">Target</p>
          <p className="font-medium text-emerald-400">₹{Number(order.target).toLocaleString("en-IN", { minimumFractionDigits: 2 })}</p>
        </div>
        <div>
          <p className="text-muted-foreground">Est. Charges</p>
          <p className="font-medium">₹{Number(order.estimated_charges).toFixed(2)}</p>
        </div>
      </div>
      <div className="flex items-center gap-3 text-xs text-muted-foreground">
        <span>Confidence {Math.round(order.confidence * 100)}%</span>
        <span>·</span>
        <span>{order.decision_type?.replace("_", " ")}</span>
        <span>·</span>
        <span>{order.created_at}</span>
      </div>
      <p className="text-xs text-amber-400">📄 PAPER SIMULATION ONLY · Not a real order</p>
    </div>
  );
}

// ── Execution Queue Item ───────────────────────────────────────────────────────
function QueueItem({ item }: { item: any }) {
  const [open, setOpen] = useState(false);
  const plan = item.execution_plan ?? {};
  const charges = plan.estimated_charges ?? {};

  return (
    <div className="border border-border rounded-xl overflow-hidden">
      <button
        onClick={() => setOpen(!open)}
        className="w-full text-left px-4 py-3 flex items-center gap-3"
      >
        <Target className="w-4 h-4 text-teal-400 shrink-0" />
        <span className="font-semibold text-sm flex-1">{item.symbol}</span>
        <span className="text-xs text-muted-foreground">{item.decision_type?.replace("_", " ")}</span>
        <span className="text-xs text-muted-foreground">
          Score {Number(item.overall_score ?? 0).toFixed(0)}/100
        </span>
        <span className="text-xs px-2 py-0.5 rounded-full bg-teal-500/10 border border-teal-500/20 text-teal-300">
          {item.status}
        </span>
        {open ? <ChevronDown className="w-4 h-4 text-muted-foreground" />
               : <ChevronRight className="w-4 h-4 text-muted-foreground" />}
      </button>

      {open && (
        <div className="px-4 pb-4 border-t border-white/5 pt-3 space-y-4">
          {/* Execution Plan */}
          <div>
            <p className="text-xs font-semibold text-muted-foreground uppercase mb-2">Execution Plan (Advisory)</p>
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-3">
              {[
                { label: "Suggested Entry",   value: `₹${Number(plan.suggested_entry ?? 0).toFixed(2)}` },
                { label: "Stop Loss",         value: `₹${Number(plan.stop_loss ?? 0).toFixed(2)}`,        color: "text-rose-400" },
                { label: "Target 1",          value: `₹${Number(plan.target_1 ?? 0).toFixed(2)}`,         color: "text-emerald-400" },
                { label: "Target 2",          value: `₹${Number(plan.target_2 ?? 0).toFixed(2)}`,         color: "text-emerald-300" },
                { label: "Suggested Qty",     value: plan.suggested_qty ?? 0 },
                { label: "Position Value",    value: `₹${Number(plan.position_value ?? 0).toLocaleString("en-IN")}` },
                { label: "R/R Ratio",         value: plan.reward_risk_ratio ?? 0 },
                { label: "Expected Holding",  value: plan.expected_holding_time ?? "—" },
              ].map(({ label, value, color = "" }) => (
                <div key={label} className="bg-muted/30 rounded-lg p-2">
                  <p className="text-xs text-muted-foreground">{label}</p>
                  <p className={`text-sm font-medium ${color}`}>{value}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Charges */}
          <div>
            <p className="text-xs font-semibold text-muted-foreground uppercase mb-2">Estimated Charges</p>
            <div className="grid grid-cols-3 sm:grid-cols-7 gap-2">
              {["brokerage", "stt", "exchange_txn", "stamp_duty", "gst", "dp_charge", "total"].map((k) => (
                <div key={k} className={`rounded-lg p-2 ${k === "total" ? "bg-teal-500/10 border border-teal-500/20" : "bg-muted/20"}`}>
                  <p className="text-xs text-muted-foreground capitalize">{k.replace("_", " ")}</p>
                  <p className={`text-xs font-medium ${k === "total" ? "text-teal-400" : ""}`}>
                    ₹{Number(charges[k] ?? 0).toFixed(2)}
                  </p>
                </div>
              ))}
            </div>
            <p className="text-xs text-muted-foreground mt-1">
              ⚠ Advisory estimates only. Verify with broker before acting.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Validation Failures ────────────────────────────────────────────────────────
function ValidationFailureCard({ fail }: { fail: any }) {
  const failures: any[] = fail.failures ?? [];
  return (
    <div className="border border-rose-500/20 bg-rose-500/5 rounded-xl p-4 space-y-2">
      <div className="flex items-center gap-2">
        <XCircle className="w-4 h-4 text-rose-400" />
        <span className="font-semibold text-sm">{fail.symbol}</span>
        <span className="text-xs text-rose-300">{failures.length} check(s) failed</span>
      </div>
      <div className="space-y-1">
        {failures.map((f: any, i: number) => (
          <div key={i} className="flex items-start gap-2 text-xs">
            <XCircle className="w-3 h-3 text-rose-400 shrink-0 mt-0.5" />
            <div>
              <span className="font-medium capitalize">{f.check?.replace("_", " ")}</span>
              <span className="text-muted-foreground ml-2">{f.detail}</span>
              {f.remediation && (
                <p className="text-muted-foreground italic">→ {f.remediation}</p>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Main Page ──────────────────────────────────────────────────────────────────
export default function ExecutionAgentPage() {
  const { data, isLoading, error, refetch, isFetching } = useQuery({
    queryKey:  ["execution-agent", "snapshot"],
    queryFn:   () => apiJson("decision-layer/execution/snapshot"),
    refetchInterval: 60_000,
    retry: 1,
    staleTime: 30_000,
  });

  const snap = data as any;
  const queue: any[] = snap?.execution_queue ?? [];
  const papers: any[] = snap?.paper_orders ?? [];
  const failures: any[] = snap?.validation_failures ?? [];
  const mode = snap?.execution_mode ?? "PAPER";
  const modeStyle = MODE_STYLE[mode] ?? MODE_STYLE.PAPER;

  const [tab, setTab] = useState<"queue" | "papers" | "failures">("queue");

  return (
    <div className="max-w-7xl mx-auto px-4 py-6 space-y-5">

      {/* Header */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div className="p-2 rounded-xl bg-teal-500/10 border border-teal-500/20">
            <Briefcase className="w-6 h-6 text-teal-400" />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-bold">Execution Agent</h1>
              <span className={`text-xs font-bold px-2 py-0.5 rounded-full ${modeStyle.bg} ${modeStyle.text}`}>
                {modeStyle.label}
              </span>
            </div>
            <p className="text-xs text-muted-foreground">
              Phase 10C · Pre-execution validation · READ-ONLY · Paper execution by default
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

      {/* Safety banner */}
      <Alert className={`border-teal-500/20 bg-teal-500/5`}>
        <Shield className="w-4 h-4 text-teal-400" />
        <AlertDescription className="text-xs text-teal-200">
          <strong>Safety:</strong> No autonomous live order placement ever.
          Paper execution is simulated only. Live execution requires{" "}
          <code className="font-mono">LIVE_EXECUTION_ENABLED=true</code> AND explicit operator confirmation per order.
          {snap?.live_execution_enabled && (
            <span className="ml-2 text-red-300 font-bold">⚠ LIVE MODE ACTIVE — Operator confirmation required for every order.</span>
          )}
        </AlertDescription>
      </Alert>

      {isLoading && (
        <div className="space-y-3">
          {[...Array(3)].map((_, i) => <div key={i} className="bg-card border border-border rounded-xl p-4 animate-pulse h-20" />)}
        </div>
      )}

      {error && !isLoading && (
        <Alert className="border-red-500/20 bg-red-500/5">
          <AlertTriangle className="w-4 h-4 text-red-400" />
          <AlertDescription className="text-xs text-red-300">
            Failed to load Execution Agent snapshot. Ensure EXECUTION_AGENT_ENABLED=true.
          </AlertDescription>
        </Alert>
      )}

      {!isLoading && snap?.available && (
        <>
          {/* KPI bar */}
          <div className="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-6 gap-3">
            {[
              { label: "Execution Mode",    value: mode,                              color: "text-teal-400" },
              { label: "Queue Size",        value: queue.length,                      color: "text-indigo-400" },
              { label: "Paper Orders",      value: papers.length,                     color: "text-emerald-400" },
              { label: "Validation Failures", value: failures.length,                 color: "text-rose-400" },
              { label: "Candidates Eval'd", value: snap.actionable_evaluated ?? 0,    color: "text-blue-400" },
              { label: "Planning Latency",  value: `${snap.planning_latency_ms?.toFixed(0)}ms`, color: "text-amber-400" },
            ].map(({ label, value, color }) => (
              <div key={label} className="bg-card border border-border rounded-xl p-3 flex flex-col gap-1">
                <p className="text-xs text-muted-foreground">{label}</p>
                <p className={`text-lg font-bold ${color}`}>{value}</p>
              </div>
            ))}
          </div>

          {/* Tabs */}
          <div className="flex gap-2">
            {(["queue", "papers", "failures"] as const).map((t) => {
              const cnt = t === "queue" ? queue.length : t === "papers" ? papers.length : failures.length;
              return (
                <button
                  key={t}
                  onClick={() => setTab(t)}
                  className={`text-xs px-3 py-1.5 rounded-lg border transition-colors ${
                    tab === t
                      ? "bg-teal-600 border-teal-600 text-white"
                      : "border-border text-muted-foreground hover:border-teal-500"
                  }`}
                >
                  {t === "queue"    ? `Execution Queue (${cnt})` :
                   t === "papers"   ? `Paper Orders (${cnt})` :
                                      `Validation Failures (${cnt})`}
                </button>
              );
            })}
          </div>

          {/* Tab content */}
          <div className="space-y-3">
            {tab === "queue" && (
              queue.length === 0 ? (
                <div className="bg-card border border-border rounded-xl p-6 text-center text-muted-foreground text-sm">
                  No items in execution queue. All recommendations may have failed pre-execution checks.
                </div>
              ) : (
                queue.map((item: any, i: number) => <QueueItem key={i} item={item} />)
              )
            )}

            {tab === "papers" && (
              papers.length === 0 ? (
                <div className="bg-card border border-border rounded-xl p-6 text-center text-muted-foreground text-sm">
                  No paper orders generated yet.
                </div>
              ) : (
                papers.map((order: any, i: number) => <PaperOrderCard key={i} order={order} />)
              )
            )}

            {tab === "failures" && (
              failures.length === 0 ? (
                <div className="bg-card border border-border rounded-xl p-6 text-center text-muted-foreground text-sm">
                  No validation failures — all items passed pre-execution checks.
                </div>
              ) : (
                failures.map((f: any, i: number) => <ValidationFailureCard key={i} fail={f} />)
              )
            )}
          </div>

          <p className="text-xs text-center text-muted-foreground pb-2">
            READ-ONLY · ADVISORY-ONLY · Paper execution by default ·
            Live execution requires LIVE_EXECUTION_ENABLED=true + operator confirmation ·
            Not financial advice
          </p>
        </>
      )}
    </div>
  );
}
