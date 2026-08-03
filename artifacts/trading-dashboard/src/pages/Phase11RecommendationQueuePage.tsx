/**
 * Phase11RecommendationQueuePage — Pending Trade Opportunities
 * Displays AI-generated BUY recommendations with confidence, risk,
 * expected return, entry, stop loss, target, and reasoning.
 * PAPER ONLY — advisory display only. No orders placed here.
 */
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Card, CardContent } from "@/components/ui/card";
import {
  TrendingUp, RefreshCw, Target, ShieldAlert, Clock, BookOpen,
  Zap, Info,
} from "lucide-react";

interface Recommendation {
  symbol: string; action: string; confidence: number; risk_level: string;
  expected_return: number; estimated_holding: string;
  entry: number; stop_loss: number; target: number;
  reasoning: string; strategy: string;
}

interface RecommendationQueue {
  items: Recommendation[];
  count: number;
  advisory_only: boolean;
  paper_only: boolean;
  as_of: string;
}

function fmt(n: number, d = 0) {
  if (n == null || isNaN(n)) return "—";
  return new Intl.NumberFormat("en-IN", { minimumFractionDigits: d, maximumFractionDigits: d }).format(n);
}

function RiskBadge({ level }: { level: string }) {
  const cls = level === "LOW"
    ? "bg-emerald-900/50 text-emerald-300 border-emerald-700/50"
    : level === "HIGH"
    ? "bg-rose-900/50 text-rose-300 border-rose-700/50"
    : "bg-amber-900/50 text-amber-300 border-amber-700/50";
  return <Badge className={`text-xs ${cls}`}>{level} RISK</Badge>;
}

function ConfBar({ value }: { value: number }) {
  const c = Math.min(100, Math.max(0, value));
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 bg-slate-800 rounded-full overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${c >= 75 ? "bg-emerald-500" : c >= 55 ? "bg-amber-500" : "bg-rose-500"}`}
          style={{ width: `${c}%` }}
        />
      </div>
      <span className={`text-sm font-bold font-mono tabular-nums ${c >= 75 ? "text-emerald-400" : c >= 55 ? "text-amber-400" : "text-rose-400"}`}>
        {fmt(c, 0)}%
      </span>
    </div>
  );
}

function RecCard({ rec, rank }: { rec: Recommendation; rank: number }) {
  const rr = rec.entry > 0 && rec.stop_loss > 0
    ? (rec.target - rec.entry) / (rec.entry - rec.stop_loss)
    : null;

  return (
    <Card className="bg-slate-900/60 border-slate-800/40 hover:border-teal-700/40 transition-all">
      <CardContent className="p-5">
        <div className="flex items-start justify-between gap-3 mb-4">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-full bg-teal-900/50 border border-teal-700/50 flex items-center justify-center text-teal-300 font-bold text-sm">
              {rank}
            </div>
            <div>
              <h3 className="text-xl font-bold text-slate-100">{rec.symbol}</h3>
              <p className="text-sm text-slate-500">{rec.strategy || rec.action}</p>
            </div>
          </div>
          <div className="flex flex-col items-end gap-1.5">
            <Badge className="bg-emerald-900/50 text-emerald-300 border-emerald-700/50 font-bold">
              {rec.action.replace(/_/g, " ")}
            </Badge>
            <RiskBadge level={rec.risk_level} />
          </div>
        </div>

        {/* Confidence */}
        <div className="mb-4">
          <p className="text-xs text-slate-500 mb-1">AI Confidence</p>
          <ConfBar value={rec.confidence} />
        </div>

        {/* Price levels */}
        <div className="grid grid-cols-3 gap-3 mb-4">
          <div className="bg-slate-800/40 rounded-lg p-3 text-center">
            <p className="text-xs text-slate-500 mb-1">Entry</p>
            <p className="font-mono font-bold text-slate-200 text-sm">₹{fmt(rec.entry)}</p>
          </div>
          <div className="bg-rose-950/20 border border-rose-800/20 rounded-lg p-3 text-center">
            <p className="text-xs text-rose-500 mb-1">Stop Loss</p>
            <p className="font-mono font-bold text-rose-400 text-sm">₹{fmt(rec.stop_loss)}</p>
          </div>
          <div className="bg-emerald-950/20 border border-emerald-800/20 rounded-lg p-3 text-center">
            <p className="text-xs text-emerald-500 mb-1">Target</p>
            <p className="font-mono font-bold text-emerald-400 text-sm">₹{fmt(rec.target)}</p>
          </div>
        </div>

        {/* Metrics row */}
        <div className="flex flex-wrap gap-3 mb-4 text-sm">
          <div className="flex items-center gap-1.5 bg-slate-800/40 rounded-lg px-3 py-1.5">
            <TrendingUp className="w-3.5 h-3.5 text-emerald-400" />
            <span className="text-slate-400">Expected:</span>
            <span className="text-emerald-400 font-bold">+{fmt(Number(rec.expected_return), 1)}%</span>
          </div>
          {rr !== null && (
            <div className="flex items-center gap-1.5 bg-slate-800/40 rounded-lg px-3 py-1.5">
              <Target className="w-3.5 h-3.5 text-teal-400" />
              <span className="text-slate-400">R:R</span>
              <span className="text-teal-400 font-bold">{rr.toFixed(1)}x</span>
            </div>
          )}
          <div className="flex items-center gap-1.5 bg-slate-800/40 rounded-lg px-3 py-1.5">
            <Clock className="w-3.5 h-3.5 text-slate-400" />
            <span className="text-slate-400">{rec.estimated_holding || "Intraday"}</span>
          </div>
        </div>

        {/* Reasoning */}
        {rec.reasoning && (
          <div className="bg-slate-800/30 rounded-lg p-3">
            <p className="text-xs text-slate-500 font-semibold mb-1 flex items-center gap-1">
              <BookOpen className="w-3 h-3" /> Reasoning
            </p>
            <p className="text-sm text-slate-300 leading-relaxed">{rec.reasoning}</p>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export default function Phase11RecommendationQueuePage() {
  const q = useQuery({
    queryKey: ["phase11", "recommendations"],
    queryFn:  () => apiJson<RecommendationQueue>("/phase11/recommendations"),
    refetchInterval: 120_000,
    staleTime: 60_000,
  });

  const items = q.data?.items ?? [];

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-4 md:p-6">
      <div className="max-w-5xl mx-auto space-y-6">
        {/* Header */}
        <div className="flex flex-wrap items-center gap-3">
          <Zap className="w-6 h-6 text-teal-400 shrink-0" />
          <div>
            <h1 className="text-2xl font-bold">Recommendation Queue</h1>
            <p className="text-slate-500 text-sm">
              {q.data?.count ?? 0} pending opportunit{(q.data?.count ?? 0) !== 1 ? "ies" : "y"} ·
              sorted by AI confidence
            </p>
          </div>
          <div className="ml-auto flex gap-2 items-center">
            <Badge className="bg-teal-900/50 text-teal-300 border-teal-700/50">PAPER ONLY</Badge>
            <Badge className="bg-amber-900/50 text-amber-300 border-amber-700/50">ADVISORY</Badge>
            <Button variant="ghost" size="sm" onClick={() => q.refetch()} className="text-slate-500 hover:text-slate-200">
              <RefreshCw className={`w-4 h-4 ${q.isFetching ? "animate-spin" : ""}`} />
            </Button>
          </div>
        </div>

        {/* Advisory notice */}
        <div className="bg-amber-950/20 border border-amber-800/30 rounded-xl p-3 flex gap-2">
          <Info className="w-4 h-4 text-amber-400 shrink-0 mt-0.5" />
          <p className="text-sm text-amber-200">
            These are AI-generated research recommendations for paper trading validation only.
            No real money. No live orders. For performance analysis purposes.
          </p>
        </div>

        {/* Content */}
        {q.isLoading ? (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {[1,2,3,4].map(i => <Skeleton key={i} className="h-64 rounded-xl" />)}
          </div>
        ) : items.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20 text-slate-500 gap-3">
            <ShieldAlert className="w-12 h-12 opacity-30" />
            <p className="text-lg font-semibold">No recommendations at this time</p>
            <p className="text-sm text-center max-w-md">
              The AI is waiting for a high-confidence opportunity. A scan must complete
              before recommendations appear. Check back during market hours.
            </p>
            <Button variant="outline" size="sm" onClick={() => q.refetch()} className="mt-2">
              <RefreshCw className="w-3 h-3 mr-2" /> Check again
            </Button>
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {items.map((rec, i) => (
              <RecCard key={rec.symbol} rec={rec} rank={i + 1} />
            ))}
          </div>
        )}

        {/* Last updated */}
        {q.data?.as_of && (
          <p className="text-xs text-slate-600 text-center">
            Updated {new Date(q.data.as_of).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })} IST
          </p>
        )}
      </div>
    </div>
  );
}
