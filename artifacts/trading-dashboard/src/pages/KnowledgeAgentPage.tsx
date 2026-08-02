/**
 * KnowledgeAgentPage.tsx — Phase 10D
 * Knowledge Agent — searchable long-term knowledge base for ApexQuant AI.
 *
 * READ-ONLY · ADVISORY-ONLY
 */
import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import {
  BookOpen, Search, Database, Lightbulb, Shield,
  AlertTriangle, Activity, Target, Clock, ChevronDown, ChevronUp,
} from "lucide-react";

const REFETCH = 60_000;
const q = (path: string) => ({
  queryKey:  ["knowledge-agent", path],
  queryFn:   () => apiJson("learning-layer/" + path),
  refetchInterval: REFETCH,
  retry: 1,
  staleTime: 30_000,
});

function KpiCard({ label, value, sub, color = "text-foreground" }: {
  label: string; value: any; sub?: string; color?: string;
}) {
  return (
    <div className="bg-card rounded-xl border border-border p-4 flex flex-col gap-1">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className={`text-2xl font-bold ${color}`}>{value ?? "—"}</p>
      {sub && <p className="text-xs text-muted-foreground">{sub}</p>}
    </div>
  );
}

function SectionHeader({ icon: Icon, title }: { icon: any; title: string }) {
  return (
    <div className="flex items-center gap-2 mb-3">
      <Icon className="w-4 h-4 text-teal-400" />
      <h2 className="font-semibold text-sm tracking-wide uppercase text-muted-foreground">{title}</h2>
    </div>
  );
}

function EntryTypeChip({ type }: { type: string }) {
  const map: Record<string, string> = {
    TRADE:               "border-emerald-500/40 text-emerald-400",
    RECOMMENDATION:      "border-violet-500/40 text-violet-400",
    RESEARCH:            "border-blue-500/40 text-blue-400",
    TIMELINE_EVENT:      "border-teal-500/40 text-teal-400",
    DECISION_EXPLANATION:"border-amber-500/40 text-amber-400",
    ANNOTATION:          "border-slate-500/40 text-slate-300",
  };
  return (
    <Badge variant="outline" className={`text-xs ${map[type] ?? "border-border text-muted-foreground"}`}>
      {type.replace(/_/g, " ")}
    </Badge>
  );
}

function EntryCard({ entry }: { entry: any }) {
  const [exp, setExp] = useState(false);
  return (
    <div className="bg-card rounded-lg border border-border p-4">
      <div className="flex items-start justify-between gap-2 mb-1">
        <p className="text-sm font-medium leading-snug">{entry.title}</p>
        <EntryTypeChip type={entry.type} />
      </div>
      {exp && (
        <p className="text-xs text-muted-foreground mt-2 mb-2">{entry.content}</p>
      )}
      <div className="flex items-center justify-between mt-2">
        <div className="flex flex-wrap gap-1">
          {(entry.tags ?? []).slice(0, 4).map((t: string, i: number) => (
            <Badge key={i} variant="outline" className="text-[10px]">{t}</Badge>
          ))}
        </div>
        <button onClick={() => setExp(!exp)} className="text-xs text-muted-foreground hover:text-foreground flex items-center gap-1">
          {exp ? <ChevronUp className="w-3 h-3" /> : <ChevronDown className="w-3 h-3" />}
          {exp ? "Less" : "More"}
        </button>
      </div>
    </div>
  );
}

export default function KnowledgeAgentPage() {
  const snapQ = useQuery(q("knowledge/snapshot"));
  const snap: any = snapQ.data ?? {};
  const lessons  = snap.lessons_library ?? {};
  const patterns = (snap.patterns ?? []).filter((p: any) => p.pattern_id !== "BASELINE_OBSERVATION");
  const entries  = snap.entries_sample ?? [];

  const [activeTab, setActiveTab] = useState<"overview"|"lessons"|"entries">("overview");

  const tabs = [
    { id: "overview", label: "Overview" },
    { id: "lessons",  label: "Lessons Library" },
    { id: "entries",  label: "Entry Sample" },
  ];

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <BookOpen className="w-6 h-6 text-blue-400" />
          <div>
            <h1 className="text-xl font-bold">Knowledge Agent</h1>
            <p className="text-sm text-muted-foreground">
              Searchable long-term knowledge base · Advisory only
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="text-xs border-blue-500/50 text-blue-400">READ-ONLY</Badge>
          <Badge variant="outline" className="text-xs border-amber-500/50 text-amber-400">ADVISORY</Badge>
        </div>
      </div>

      {/* Safety notice */}
      <Alert className="border-blue-500/30 bg-blue-500/10">
        <Shield className="h-4 w-4 text-blue-400" />
        <AlertDescription className="text-xs text-blue-300">
          Knowledge base is read-only. No automated model updates or strategy changes.
          All insights require operator review before adoption.
        </AlertDescription>
      </Alert>

      {/* KPI row */}
      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-3">
        <KpiCard label="Knowledge Base Size"   value={snap.knowledge_base_size ?? "—"}    color="text-blue-400" />
        <KpiCard label="Trades Learned"         value={snap.trades_learned ?? "—"} />
        <KpiCard label="Recs Analysed"          value={snap.recommendations_analysed ?? "—"} />
        <KpiCard label="Patterns Identified"    value={snap.patterns_identified ?? "—"}    color="text-violet-400" />
        <KpiCard label="Learning Health"        value={snap.learning_health ?? "—"} />
        <KpiCard label="Indexing Latency"       value={snap.indexing_latency_ms != null ? `${snap.indexing_latency_ms.toFixed(0)} ms` : "—"} />
      </div>

      {/* Tabs */}
      <div className="flex gap-1 border-b border-border">
        {tabs.map(t => (
          <button
            key={t.id}
            onClick={() => setActiveTab(t.id as any)}
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === t.id
                ? "border-b-2 border-blue-400 text-blue-400"
                : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab: Overview */}
      {activeTab === "overview" && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {/* Patterns */}
          <div className="bg-card rounded-xl border border-border p-5">
            <SectionHeader icon={Activity} title={`Patterns (${patterns.length})`} />
            {patterns.length === 0 ? (
              <p className="text-sm text-muted-foreground">No patterns identified yet.</p>
            ) : (
              <div className="space-y-3">
                {patterns.map((p: any) => (
                  <div key={p.pattern_id} className="py-2 border-b border-border/50 last:border-0">
                    <div className="flex items-start justify-between">
                      <p className="text-sm font-medium">{p.name}</p>
                      <span className="text-xs font-mono text-muted-foreground">{(p.confidence * 100).toFixed(0)}%</span>
                    </div>
                    <p className="text-xs text-muted-foreground mt-1">{p.advisory}</p>
                    <Badge variant="outline" className="text-[10px] mt-1">{p.category}</Badge>
                  </div>
                ))}
              </div>
            )}
          </div>

          {/* What to review + monitor */}
          <div className="space-y-4">
            <div className="bg-card rounded-xl border border-border p-5">
              <SectionHeader icon={Target} title="What to Review" />
              {(lessons.what_to_review ?? []).length === 0 ? (
                <p className="text-sm text-muted-foreground">No review items.</p>
              ) : (
                <ul className="space-y-2">
                  {(lessons.what_to_review ?? []).map((item: string, i: number) => (
                    <li key={i} className="text-sm text-muted-foreground flex items-start gap-2">
                      <span className="mt-1 w-1.5 h-1.5 rounded-full bg-amber-400 flex-shrink-0" />
                      {item}
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div className="bg-card rounded-xl border border-border p-5">
              <SectionHeader icon={Clock} title="What to Monitor" />
              {(lessons.what_to_monitor ?? []).length === 0 ? (
                <p className="text-sm text-muted-foreground">No monitoring alerts.</p>
              ) : (
                <ul className="space-y-2">
                  {(lessons.what_to_monitor ?? []).map((item: string, i: number) => (
                    <li key={i} className="text-sm text-muted-foreground flex items-start gap-2">
                      <span className="mt-1 w-1.5 h-1.5 rounded-full bg-teal-400 flex-shrink-0" />
                      {item}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Tab: Lessons Library */}
      {activeTab === "lessons" && (
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
          {[
            { key: "what_worked",    label: "What Worked",         color: "bg-emerald-400" },
            { key: "what_failed",    label: "What Failed",         color: "bg-red-400" },
            { key: "what_to_review", label: "What to Review",      color: "bg-amber-400" },
            { key: "what_to_monitor",label: "What to Monitor",     color: "bg-teal-400" },
            { key: "open_questions", label: "Open Research Questions", color: "bg-violet-400" },
          ].map(({ key, label, color }) => (
            <div key={key} className="bg-card rounded-xl border border-border p-5">
              <div className="flex items-center gap-2 mb-3">
                <span className={`w-2 h-2 rounded-full ${color}`} />
                <h3 className="font-semibold text-sm">{label}</h3>
              </div>
              {(lessons[key] ?? []).length === 0 ? (
                <p className="text-sm text-muted-foreground">No items in this category.</p>
              ) : (
                <ul className="space-y-2">
                  {(lessons[key] ?? []).map((item: string, i: number) => (
                    <li key={i} className="text-sm text-muted-foreground flex items-start gap-2">
                      <span className={`mt-1 w-1.5 h-1.5 rounded-full ${color} flex-shrink-0`} />
                      {item}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Tab: Entry Sample */}
      {activeTab === "entries" && (
        <div>
          {entries.length === 0 ? (
            <p className="text-sm text-muted-foreground">No entries indexed yet. Complete some paper trades to populate the knowledge base.</p>
          ) : (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
              {entries.map((e: any) => <EntryCard key={e.entry_id} entry={e} />)}
            </div>
          )}
        </div>
      )}

      <p className="text-xs text-muted-foreground text-right">
        Updated {snap.generated_at ?? "—"} · READ-ONLY · ADVISORY-ONLY
      </p>
    </div>
  );
}
