/**
 * LessonsLibraryPage.tsx — Phase 10D
 * Lessons Library — automatically generated advisory lessons from completed sessions.
 *
 * READ-ONLY · ADVISORY-ONLY
 */
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Lightbulb, Shield, CheckCircle2, XCircle, Search, Eye, HelpCircle } from "lucide-react";

const q = (path: string) => ({
  queryKey:  ["lessons-library", path],
  queryFn:   () => apiJson("learning-layer/" + path),
  refetchInterval: 60_000,
  retry: 1,
  staleTime: 30_000,
});

const CATEGORIES = [
  {
    key:   "what_worked",
    label: "What Worked",
    icon:  CheckCircle2,
    color: "text-emerald-400",
    dot:   "bg-emerald-400",
    border:"border-emerald-500/30",
    bg:    "bg-emerald-500/5",
  },
  {
    key:   "what_failed",
    label: "What Failed",
    icon:  XCircle,
    color: "text-red-400",
    dot:   "bg-red-400",
    border:"border-red-500/30",
    bg:    "bg-red-500/5",
  },
  {
    key:   "what_to_review",
    label: "Review Required",
    icon:  Search,
    color: "text-amber-400",
    dot:   "bg-amber-400",
    border:"border-amber-500/30",
    bg:    "bg-amber-500/5",
  },
  {
    key:   "what_to_monitor",
    label: "Monitor Closely",
    icon:  Eye,
    color: "text-teal-400",
    dot:   "bg-teal-400",
    border:"border-teal-500/30",
    bg:    "bg-teal-500/5",
  },
  {
    key:   "open_questions",
    label: "Open Research Questions",
    icon:  HelpCircle,
    color: "text-violet-400",
    dot:   "bg-violet-400",
    border:"border-violet-500/30",
    bg:    "bg-violet-500/5",
  },
] as const;

export default function LessonsLibraryPage() {
  const lessonsQ = useQuery(q("knowledge/lessons"));
  const data: any    = lessonsQ.data ?? {};
  const lessons: any = data.lessons_library ?? {};

  const totalItems = CATEGORIES.reduce((acc, c) => acc + (lessons[c.key]?.length ?? 0), 0);

  return (
    <div className="p-6 space-y-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Lightbulb className="w-6 h-6 text-amber-400" />
          <div>
            <h1 className="text-xl font-bold">Lessons Library</h1>
            <p className="text-sm text-muted-foreground">
              Automatically generated lessons from completed trading sessions
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="text-xs border-amber-500/50 text-amber-400">READ-ONLY</Badge>
          <Badge variant="outline" className="text-xs border-amber-500/50 text-amber-400">ADVISORY</Badge>
          <Badge className="text-xs bg-amber-600">{totalItems} Lessons</Badge>
        </div>
      </div>

      <Alert className="border-amber-500/30 bg-amber-500/10">
        <Shield className="h-4 w-4 text-amber-400" />
        <AlertDescription className="text-xs text-amber-300">
          All lessons are advisory observations generated from paper trading history.
          Operator review is required before any operational changes.
          {data.trades_analysed != null && ` Based on ${data.trades_analysed} completed trade${data.trades_analysed !== 1 ? "s" : ""}.`}
        </AlertDescription>
      </Alert>

      {totalItems === 0 ? (
        <div className="bg-card rounded-xl border border-border p-8 text-center">
          <Lightbulb className="w-8 h-8 text-muted-foreground mx-auto mb-3" />
          <p className="text-sm text-muted-foreground">
            No lessons generated yet. Complete paper trades to populate the lessons library.
          </p>
        </div>
      ) : (
        <div className="space-y-4">
          {CATEGORIES.map(({ key, label, icon: Icon, color, dot, border, bg }) => {
            const items: string[] = lessons[key] ?? [];
            return (
              <div key={key} className={`rounded-xl border p-5 ${border} ${bg}`}>
                <div className="flex items-center gap-2 mb-4">
                  <Icon className={`w-4 h-4 ${color}`} />
                  <h2 className={`font-semibold text-sm ${color}`}>{label}</h2>
                  <Badge variant="outline" className={`text-[10px] ml-auto ${color}`}>
                    {items.length} item{items.length !== 1 ? "s" : ""}
                  </Badge>
                </div>
                {items.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No items in this category.</p>
                ) : (
                  <ul className="space-y-2.5">
                    {items.map((item, i) => (
                      <li key={i} className="flex items-start gap-3 text-sm text-muted-foreground">
                        <span className={`mt-1.5 w-1.5 h-1.5 rounded-full ${dot} flex-shrink-0`} />
                        <span>{item}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            );
          })}
        </div>
      )}

      <p className="text-xs text-muted-foreground text-right">
        Generated {lessons.generated_at ?? "—"} · READ-ONLY · ADVISORY-ONLY · No automated changes
      </p>
    </div>
  );
}
