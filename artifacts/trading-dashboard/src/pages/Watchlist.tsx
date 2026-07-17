import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  useGetWatchlist,
  getGetWatchlistQueryKey,
  useAddToWatchlist,
  useRemoveFromWatchlist,
  useGetSymbols,
} from "@workspace/api-client-react";
import { useQueryClient } from "@tanstack/react-query";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Trash2, Plus, TrendingUp } from "lucide-react";
import { useToast } from "@/hooks/use-toast";
import DataFreshnessBar from "@/components/DataFreshnessBar";
import { API_BASE } from "@/lib/api";

// Priority 9 (#34): server-side search over the approved research universe
// by ticker, company name or alias. Only approved instruments are returned.
type SearchResult = {
  symbol: string;
  name: string;
  exchange: string;
  type: string;
  sector: string;
  match: "ticker" | "name" | "alias";
};

export default function Watchlist() {
  const [newSymbol, setNewSymbol] = useState("");
  const queryClient = useQueryClient();
  const { toast } = useToast();

  const [showSuggestions, setShowSuggestions] = useState(false);
  const [highlightIndex, setHighlightIndex] = useState(0);
  const [navigated, setNavigated] = useState(false);
  const blurTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  const { data, isLoading } = useGetWatchlist();
  const { data: symbolsData } = useGetSymbols();

  const addMutation = useAddToWatchlist();
  const removeMutation = useRemoveFromWatchlist();

  const allSymbols = symbolsData?.symbols ?? [];
  const watchlistSet = useMemo(() => new Set(data?.watchlist ?? []), [data]);

  // Debounced server-side search (ticker / company name / alias). An
  // AbortController + cleanup guard prevents stale out-of-order responses
  // from overwriting results for the current query.
  const [searchResults, setSearchResults] = useState<SearchResult[]>([]);
  useEffect(() => {
    const q = newSymbol.trim();
    if (!q) { setSearchResults([]); return; }
    const ctrl = new AbortController();
    let cancelled = false;
    const t = setTimeout(async () => {
      try {
        const r = await fetch(`${API_BASE}/symbols/search?q=${encodeURIComponent(q)}`,
          { signal: ctrl.signal });
        const d = await r.json();
        if (!cancelled && r.ok && Array.isArray(d.results)) setSearchResults(d.results);
        else if (!cancelled) setSearchResults([]);
      } catch {
        if (!cancelled) setSearchResults([]);
      }
    }, 200);
    return () => { cancelled = true; ctrl.abort(); clearTimeout(t); };
  }, [newSymbol]);

  const suggestions = useMemo(() => {
    const q = newSymbol.trim().toUpperCase();
    if (!q) {
      // No query yet: show the approved universe not already tracked.
      return allSymbols
        .filter((s) => !watchlistSet.has(s.symbol))
        .slice(0, 8)
        .map((s) => ({
          symbol: s.symbol, name: "", exchange: "NSE", type: "EQ",
          sector: s.sector, match: "ticker" as const,
        }));
    }
    return searchResults.filter((s) => !watchlistSet.has(s.symbol)).slice(0, 8);
  }, [newSymbol, allSymbols, watchlistSet, searchResults]);

  const submitSymbol = (raw: string) => {
    const symbol = raw.trim().toUpperCase();
    if (!symbol) return;

    if (data?.watchlist.includes(symbol)) {
      toast({
        title: "Already in watchlist",
        description: `${symbol} is already being tracked.`,
        variant: "destructive",
      });
      return;
    }

    if (allSymbols.length > 0 && !allSymbols.some((s) => s.symbol === symbol)) {
      toast({
        title: "Unknown symbol",
        description: `${symbol} is not a known NSE symbol. Pick one from the suggestions.`,
        variant: "destructive",
      });
      return;
    }

    setShowSuggestions(false);
    addMutation.mutate({ data: { symbol } }, {
      onSuccess: () => {
        setNewSymbol("");
        queryClient.invalidateQueries({ queryKey: getGetWatchlistQueryKey() });
        toast({
          title: "Added to watchlist",
          description: `${symbol} is now being tracked.`,
        });
      },
      onError: (err: unknown) => {
        const apiError = (err as { error?: string } | null)?.error;
        toast({
          title: "Failed to add",
          description: apiError || `Could not add ${symbol} to watchlist.`,
          variant: "destructive",
        });
      }
    });
  };

  const handleAdd = (e: React.FormEvent) => {
    e.preventDefault();
    // Explicit keyboard selection (arrow keys) counts as picking from the list.
    if (navigated && showSuggestions && suggestions[highlightIndex]) {
      submitSymbol(suggestions[highlightIndex].symbol);
      return;
    }
    const typed = newSymbol.trim().toUpperCase();
    // Exact ticker typed → add it directly.
    if (typed && allSymbols.some((s) => s.symbol === typed)) {
      submitSymbol(typed);
      return;
    }
    // Any search-derived match (company name / alias / partial) requires an
    // explicit pick — click or arrow-key selection. Never auto-add a fuzzy
    // match, even when there is only one, since async results can change
    // between keystrokes.
    if (suggestions.length >= 1) {
      setShowSuggestions(true);
      toast({
        title: suggestions.length === 1 ? "Confirm selection" : "Multiple matches",
        description: suggestions.length === 1
          ? `Did you mean ${suggestions[0].symbol} (${suggestions[0].name || suggestions[0].sector})? Pick it from the list to add.`
          : `"${typed}" matches ${suggestions.length} instruments — pick one from the list.`,
      });
      return;
    }
    submitSymbol(typed);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (!showSuggestions || suggestions.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setNavigated(true);
      setHighlightIndex((i) => (i + 1) % suggestions.length);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setNavigated(true);
      setHighlightIndex((i) => (i - 1 + suggestions.length) % suggestions.length);
    } else if (e.key === "Escape") {
      setShowSuggestions(false);
    }
  };

  const handleRemove = (symbol: string) => {
    removeMutation.mutate({ symbol }, {
      onSuccess: () => {
        queryClient.invalidateQueries({ queryKey: getGetWatchlistQueryKey() });
        toast({
          title: "Removed",
          description: `${symbol} removed from watchlist.`,
        });
      }
    });
  };

  const watchlist = data?.watchlist || [];

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Market Watchlist</h1>
        <p className="text-muted-foreground text-sm mt-1">Manage the NSE symbols your algorithm actively scans.</p>
      </div>

      <DataFreshnessBar variant="scan" />

      <Card className="bg-card/50 backdrop-blur border-border/50">
        <CardHeader>
          <CardTitle>Tracked Symbols</CardTitle>
          <CardDescription>
            Add NSE tickers (e.g. RELIANCE, TCS, INFY)
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          <form onSubmit={handleAdd} className="flex gap-3">
            <div className="relative max-w-xs w-full">
              <Input
                placeholder="Search ticker or company name..."
                value={newSymbol}
                onChange={(e) => {
                  setNewSymbol(e.target.value.toUpperCase());
                  setShowSuggestions(true);
                  setHighlightIndex(0);
                  setNavigated(false);
                }}
                onFocus={() => {
                  if (blurTimeout.current) clearTimeout(blurTimeout.current);
                  setShowSuggestions(true);
                }}
                onBlur={() => {
                  blurTimeout.current = setTimeout(() => setShowSuggestions(false), 150);
                }}
                onKeyDown={handleKeyDown}
                className="font-mono uppercase bg-background"
                disabled={addMutation.isPending}
                autoComplete="off"
                data-testid="input-symbol-search"
              />
              {showSuggestions && suggestions.length > 0 && (
                <div
                  className="absolute z-20 mt-1 w-full rounded-md border border-border bg-popover shadow-lg overflow-hidden"
                  data-testid="symbol-suggestions"
                >
                  {suggestions.map((s, i) => (
                    <button
                      key={s.symbol}
                      type="button"
                      className={`w-full flex items-center justify-between px-3 py-2 text-sm text-left transition-colors ${
                        i === highlightIndex ? "bg-muted" : "hover:bg-muted/60"
                      }`}
                      onMouseDown={(e) => e.preventDefault()}
                      onMouseEnter={() => setHighlightIndex(i)}
                      onClick={() => submitSymbol(s.symbol)}
                      data-testid={`suggestion-${s.symbol}`}
                    >
                      <span className="min-w-0">
                        <span className="font-mono font-semibold">{s.symbol}</span>
                        {s.name && (
                          <span className="ml-2 truncate text-xs text-muted-foreground">{s.name}</span>
                        )}
                      </span>
                      <span className="shrink-0 text-[10px] text-muted-foreground">
                        {s.exchange} · {s.type}{s.sector ? ` · ${s.sector}` : ""}
                      </span>
                    </button>
                  ))}
                </div>
              )}
              {showSuggestions && newSymbol.trim() && suggestions.length === 0 && allSymbols.length > 0 && (
                <div className="absolute z-20 mt-1 w-full rounded-md border border-border bg-popover shadow-lg px-3 py-2 text-sm text-muted-foreground">
                  No matching NSE symbols
                </div>
              )}
            </div>
            <Button type="submit" disabled={!newSymbol.trim() || addMutation.isPending} data-testid="button-add-symbol">
              <Plus className="h-4 w-4 mr-2" />
              Add Symbol
            </Button>
          </form>

          {isLoading && !data ? (
            <div className="py-8 text-center text-muted-foreground font-mono">LOADING WATCHLIST...</div>
          ) : watchlist.length > 0 ? (
            <div className="grid gap-3 grid-cols-1 sm:grid-cols-2 md:grid-cols-3">
              {watchlist.map((symbol) => (
                <div 
                  key={symbol} 
                  className="flex items-center justify-between p-3 rounded-lg border border-border/60 bg-muted/20 hover:bg-muted/40 transition-colors group"
                >
                  <div className="flex items-center gap-3">
                    <div className="h-8 w-8 rounded-md bg-primary/10 flex items-center justify-center text-primary">
                      <TrendingUp className="h-4 w-4" />
                    </div>
                    <span className="font-bold font-mono text-foreground">{symbol}</span>
                  </div>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8 text-muted-foreground opacity-0 group-hover:opacity-100 hover:text-destructive hover:bg-destructive/10 transition-all"
                    onClick={() => handleRemove(symbol)}
                    disabled={removeMutation.isPending}
                    title={`Remove ${symbol}`}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              ))}
            </div>
          ) : (
            <div className="py-12 text-center border border-dashed border-border rounded-lg bg-muted/10 flex flex-col items-center gap-3">
               <Eye className="h-6 w-6 text-muted-foreground/50" />
               <p className="font-mono text-sm text-muted-foreground">WATCHLIST EMPTY</p>
               <p className="text-xs text-muted-foreground/80">Add symbols to begin tracking signals.</p>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// Temporary local import to make the empty state work since Watchlist component doesn't import Eye at the top
import { Eye } from "lucide-react";
