/**
 * KnowledgeSearchPage.tsx — Phase 10D
 * Knowledge Search — natural-language search over the ApexQuant AI knowledge base.
 *
 * READ-ONLY · ADVISORY-ONLY
 */
import { useState, useCallback } from "react";
import { apiJson } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Search, Shield, Clock, AlertTriangle, BookOpen } from "lucide-react";

const EXAMPLE_QUERIES = [
  "Show all successful banking breakouts",
  "Show every recommendation above 80% confidence",
  "Which strategy performs best during high volatility",
  "Show similar market conditions",
  "Momentum trades with positive outcome",
];

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
    <Badge variant="outline" className={`text-[10px] ${map[type] ?? "border-border text-muted-foreground"}`}>
      {type.replace(/_/g, " ")}
    </Badge>
  );
}

function ResultCard({ result }: { result: any }) {
  const pct = Math.round((result.relevance_score ?? 0) * 100);
  const scoreColor = pct >= 70 ? "text-emerald-400" : pct >= 40 ? "text-amber-400" : "text-muted-foreground";
  return (
    <div className="bg-card rounded-lg border border-border p-4 hover:border-blue-500/40 transition-colors">
      <div className="flex items-start justify-between gap-2 mb-2">
        <p className="text-sm font-medium leading-snug flex-1">{result.title}</p>
        <div className="flex items-center gap-2 flex-shrink-0">
          <span className={`text-xs font-mono ${scoreColor}`}>{pct}%</span>
          <EntryTypeChip type={result.type} />
        </div>
      </div>
      <p className="text-xs text-muted-foreground mb-3 line-clamp-2">{result.content}</p>
      <div className="flex items-center justify-between">
        <div className="flex flex-wrap gap-1">
          {(result.tags ?? []).slice(0, 3).map((t: string, i: number) => (
            <Badge key={i} variant="outline" className="text-[10px]">{t}</Badge>
          ))}
        </div>
        <span className="text-[10px] text-muted-foreground font-mono">
          {result.timestamp?.slice(0, 10) ?? ""}
        </span>
      </div>
    </div>
  );
}

export default function KnowledgeSearchPage() {
  const [query, setQuery]       = useState("");
  const [loading, setLoading]   = useState(false);
  const [results, setResults]   = useState<any[]>([]);
  const [searched, setSearched] = useState(false);
  const [latency, setLatency]   = useState<number | null>(null);
  const [error, setError]       = useState<string | null>(null);

  const doSearch = useCallback(async (q: string) => {
    if (!q.trim()) return;
    setLoading(true);
    setError(null);
    const t0 = Date.now();
    try {
      const data: any = await apiJson(`learning-layer/knowledge/search?q=${encodeURIComponent(q.trim())}`);
      setResults(data.results ?? []);
      setLatency(Date.now() - t0);
      setSearched(true);
    } catch (e: any) {
      setError(e.message ?? "Search failed");
    } finally {
      setLoading(false);
    }
  }, []);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") doSearch(query);
  };

  return (
    <div className="p-6 space-y-6 max-w-4xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Search className="w-6 h-6 text-blue-400" />
          <div>
            <h1 className="text-xl font-bold">Knowledge Search</h1>
            <p className="text-sm text-muted-foreground">Natural-language search over the ApexQuant AI knowledge base</p>
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
          Search results are read-only advisory information from the knowledge base.
          No automated actions are triggered by search queries.
        </AlertDescription>
      </Alert>

      {/* Search box */}
      <div className="bg-card rounded-xl border border-border p-5">
        <div className="flex items-center gap-3">
          <Search className="w-4 h-4 text-muted-foreground flex-shrink-0" />
          <input
            className="flex-1 bg-transparent text-sm outline-none placeholder:text-muted-foreground"
            placeholder="e.g. Show all successful banking breakouts..."
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
          />
          <button
            onClick={() => doSearch(query)}
            disabled={loading || !query.trim()}
            className="px-4 py-1.5 rounded-lg bg-blue-600 text-white text-sm font-medium disabled:opacity-50 hover:bg-blue-700 transition-colors"
          >
            {loading ? "Searching…" : "Search"}
          </button>
        </div>

        {/* Example queries */}
        <div className="mt-4 flex flex-wrap gap-2">
          {EXAMPLE_QUERIES.map((eq, i) => (
            <button
              key={i}
              onClick={() => { setQuery(eq); doSearch(eq); }}
              className="text-xs border border-border rounded-full px-3 py-1 text-muted-foreground hover:text-foreground hover:border-blue-500/50 transition-colors"
            >
              {eq}
            </button>
          ))}
        </div>
      </div>

      {/* Error */}
      {error && (
        <Alert className="border-red-500/30 bg-red-500/10">
          <AlertTriangle className="h-4 w-4 text-red-400" />
          <AlertDescription className="text-xs text-red-300">{error}</AlertDescription>
        </Alert>
      )}

      {/* Results */}
      {searched && !loading && (
        <div>
          <div className="flex items-center justify-between mb-3">
            <p className="text-sm font-medium">
              {results.length} result{results.length !== 1 ? "s" : ""}{" "}
              <span className="text-muted-foreground">for "{query}"</span>
            </p>
            {latency != null && (
              <div className="flex items-center gap-1 text-xs text-muted-foreground">
                <Clock className="w-3 h-3" />
                {latency}ms
              </div>
            )}
          </div>
          {results.length === 0 ? (
            <div className="bg-card rounded-xl border border-border p-8 text-center">
              <BookOpen className="w-8 h-8 text-muted-foreground mx-auto mb-3" />
              <p className="text-sm text-muted-foreground">
                No results found. Try a different query or complete more paper trades to populate the knowledge base.
              </p>
            </div>
          ) : (
            <div className="space-y-3">
              {results.map((r: any, i: number) => <ResultCard key={r.entry_id ?? i} result={r} />)}
            </div>
          )}
        </div>
      )}

      {!searched && !loading && (
        <div className="bg-card rounded-xl border border-border p-8 text-center">
          <Search className="w-8 h-8 text-muted-foreground mx-auto mb-3" />
          <p className="text-sm text-muted-foreground">
            Enter a natural-language query above to search the knowledge base.
            Try clicking one of the example queries to get started.
          </p>
        </div>
      )}
    </div>
  );
}
