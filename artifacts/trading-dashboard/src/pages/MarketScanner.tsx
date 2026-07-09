import React, { useState } from "react";
import {
  useGetMarketScan,
  getGetMarketScanQueryKey,
} from "@workspace/api-client-react";
import { EvidenceBody } from "@/components/HistoricalEvidence";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { formatTime } from "@/lib/format";
import {
  RefreshCcw, Flame, TrendingUp, TrendingDown, Eye, Ban,
  Star, LayoutGrid, ListOrdered, Building2, History,
} from "lucide-react";

// ── Config maps ───────────────────────────────────────────────────────────────

const ACTION_CONFIG: Record<string, { color: string; bg: string; icon: React.ReactNode }> = {
  "STRONG BUY": { color: "text-emerald-400", bg: "bg-emerald-500/10 border-emerald-500/30", icon: <Flame className="h-3.5 w-3.5" /> },
  "BUY":        { color: "text-green-400",   bg: "bg-green-500/10 border-green-500/30",     icon: <TrendingUp className="h-3.5 w-3.5" /> },
  "WATCH":      { color: "text-yellow-400",  bg: "bg-yellow-500/10 border-yellow-500/30",   icon: <Eye className="h-3.5 w-3.5" /> },
  "IGNORE":     { color: "text-muted-foreground", bg: "bg-muted/20 border-border/30",       icon: <Ban className="h-3.5 w-3.5" /> },
};

const HEAT_COLOR: Record<string, string> = {
  GREEN:  "bg-emerald-500",
  YELLOW: "bg-yellow-500",
  RED:    "bg-red-500",
};

const STRENGTH_COLOR: Record<string, string> = {
  STRONG:  "text-emerald-400",
  NEUTRAL: "text-yellow-400",
  WEAK:    "text-red-400",
};

// ── Sub-components ────────────────────────────────────────────────────────────

function SummaryCard({
  label, value, sub, color,
}: { label: string; value: string | number; sub?: string; color?: string }) {
  return (
    <Card className="bg-card/50 backdrop-blur border-border/50">
      <CardContent className="p-4">
        <div className="text-xs font-mono uppercase text-muted-foreground tracking-wider mb-1">{label}</div>
        <div className={`text-2xl font-bold font-mono ${color ?? ""}`}>{value}</div>
        {sub && <div className="text-xs text-muted-foreground mt-1 font-mono">{sub}</div>}
      </CardContent>
    </Card>
  );
}

function HeatTile({
  stock, score, heat, action,
}: { stock: string; score: number; heat: string; action: string }) {
  return (
    <div
      className={`rounded-md border border-border/30 p-2.5 flex flex-col gap-1 hover:scale-[1.03] transition-transform cursor-default ${HEAT_COLOR[heat] ?? "bg-muted"}/10`}
      title={`${stock} · ${action} · score ${score.toFixed(0)}`}
    >
      <div className="flex items-center justify-between">
        <span className="font-mono font-bold text-xs truncate">{stock}</span>
        <span className={`h-2 w-2 rounded-full ${HEAT_COLOR[heat] ?? "bg-muted"}`} />
      </div>
      <span className="text-xs font-mono text-muted-foreground">{score.toFixed(0)}</span>
    </div>
  );
}

function RankRow({ item, rank }: { item: any; rank: number }) {
  const cfg = ACTION_CONFIG[item.final_action] ?? ACTION_CONFIG["IGNORE"];
  const [open, setOpen] = useState(false);
  return (
    <>
    <tr
      className="border-b border-border/30 hover:bg-muted/10 transition-colors cursor-pointer"
      onClick={() => setOpen((o) => !o)}
      data-testid={`row-scan-${item.stock}`}
    >
      <td className="py-2 px-3 text-xs font-mono text-muted-foreground">{rank}</td>
      <td className="py-2 px-3">
        <div className="font-mono font-bold text-sm">{item.stock}</div>
        <div className="text-[10px] text-muted-foreground font-mono">{item.sector}</div>
      </td>
      <td className="py-2 px-3 text-xs font-mono text-muted-foreground">{item.best_strategy_name}</td>
      <td className="py-2 px-3 text-sm font-mono">₹{item.price.toLocaleString("en-IN", { maximumFractionDigits: 0 })}</td>
      <td className="py-2 px-3">
        <div className="flex items-center gap-1.5">
          <div className="w-14 h-1.5 bg-muted rounded-full overflow-hidden">
            <div className="h-full rounded-full bg-primary" style={{ width: `${item.opportunity_score}%` }} />
          </div>
          <span className="text-xs font-mono w-8">{item.opportunity_score.toFixed(0)}</span>
        </div>
      </td>
      <td className="py-2 px-3 text-xs font-mono text-muted-foreground">{item.trade_quality.toFixed(0)}</td>
      <td className="py-2 px-3 text-xs font-mono text-muted-foreground">{item.confidence.toFixed(0)}%</td>
      <td className="py-2 px-3 text-xs font-mono text-muted-foreground">{item.rr_ratio.toFixed(1)}:1</td>
      <td className="py-2 px-3">
        <Badge variant="outline" className={`font-mono text-[10px] gap-1 ${cfg.bg} ${cfg.color}`}>
          {cfg.icon}
          {item.final_action}
        </Badge>
      </td>
    </tr>
    {open && (
      <tr className="border-b border-border/30 bg-zinc-900/40">
        <td colSpan={9} className="py-3 px-4">
          <div className="flex items-center gap-1.5 text-xs font-mono text-primary/80 uppercase tracking-wider mb-2">
            <History className="h-3.5 w-3.5" />
            Historical Evidence — {item.stock}
          </div>
          <EvidenceBody symbol={item.stock} />
        </td>
      </tr>
    )}
    </>
  );
}

// ── Main page ─────────────────────────────────────────────────────────────────

export default function MarketScanner() {
  const { data, isLoading, refetch, isFetching } = useGetMarketScan({
    query: {
      queryKey: getGetMarketScanQueryKey(),
      refetchInterval: 10 * 60 * 1000,
    },
  });

  if (isLoading && !data) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-4">
          <div className="h-8 w-8 border-4 border-primary border-t-transparent rounded-full animate-spin" />
          <p className="text-muted-foreground font-mono text-sm">SCANNING NIFTY 50 UNIVERSE...</p>
          <p className="text-muted-foreground/60 text-xs">Running validated strategies across 50 stocks — may take ~20-30s</p>
        </div>
      </div>
    );
  }

  const summary = data?.summary;
  const items = data?.items ?? [];
  const sectors = data?.sectors ?? [];
  const watchlist = data?.watchlist ?? [];
  const watchlistItems = watchlist
    .map((sym) => items.find((it) => it.stock === sym))
    .filter((it): it is NonNullable<typeof it> => Boolean(it));

  return (
    <div className="space-y-5 max-w-7xl mx-auto">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Market Scanner</h1>
          <p className="text-muted-foreground text-sm mt-0.5">
            NIFTY 50 universe scan · best strategy per stock · opportunity ranking — paper trading only
          </p>
        </div>
        <div className="flex items-center gap-3">
          {data?.scanned_at && (
            <span className="text-xs text-muted-foreground font-mono">
              Last scan: {formatTime(data.scanned_at)}
            </span>
          )}
          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="flex items-center gap-2 text-xs font-mono px-3 py-1.5 rounded border border-border hover:bg-muted/40 transition-colors text-muted-foreground hover:text-foreground disabled:opacity-50"
          >
            <RefreshCcw className={`h-3 w-3 ${isFetching ? "animate-spin" : ""}`} />
            Rescan
          </button>
        </div>
      </div>

      {/* Dashboard summary */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-4">
        <SummaryCard label="Universe" value={summary?.total_scanned ?? 0} sub="stocks scanned" />
        <SummaryCard label="Strong Buy" value={summary?.strong_buy_count ?? 0} color="text-emerald-400" />
        <SummaryCard label="Buy" value={summary?.buy_count ?? 0} color="text-green-400" />
        <SummaryCard label="Watch" value={summary?.watch_count ?? 0} color="text-yellow-400" />
        <SummaryCard label="Ignore" value={summary?.ignore_count ?? 0} color="text-muted-foreground" />
      </div>

      <div className="grid md:grid-cols-3 gap-4">
        <Card className="bg-card/50 backdrop-blur border-border/50">
          <CardContent className="p-4">
            <div className="text-xs font-mono uppercase text-muted-foreground tracking-wider mb-1">Best Opportunity</div>
            <div className="text-xl font-bold font-mono text-emerald-400">{summary?.best_stock ?? "—"}</div>
            <div className="text-xs text-muted-foreground font-mono mt-1">score {(summary?.best_stock_score ?? 0).toFixed(0)}</div>
          </CardContent>
        </Card>
        <Card className="bg-card/50 backdrop-blur border-border/50">
          <CardContent className="p-4">
            <div className="text-xs font-mono uppercase text-muted-foreground tracking-wider mb-1">Strongest Sector</div>
            <div className="text-xl font-bold font-mono text-emerald-400">{summary?.strongest_sector ?? "—"}</div>
          </CardContent>
        </Card>
        <Card className="bg-card/50 backdrop-blur border-border/50">
          <CardContent className="p-4">
            <div className="text-xs font-mono uppercase text-muted-foreground tracking-wider mb-1">Weakest Sector</div>
            <div className="text-xl font-bold font-mono text-red-400">{summary?.weakest_sector ?? "—"}</div>
          </CardContent>
        </Card>
      </div>

      {/* Dynamic AI Watchlist */}
      <Card className="bg-card/50 backdrop-blur border-border/50">
        <CardHeader className="py-3 px-4 border-b border-border/50">
          <CardTitle className="font-mono text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-2">
            <Star className="h-3.5 w-3.5 text-primary" />
            Dynamic AI Watchlist — Top 10
          </CardTitle>
        </CardHeader>
        <CardContent className="p-3">
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            {watchlistItems.map((it) => {
              const cfg = ACTION_CONFIG[it.final_action] ?? ACTION_CONFIG["IGNORE"];
              return (
                <div key={it.stock} className={`rounded-md border p-3 flex flex-col gap-1 ${cfg.bg}`}>
                  <div className="flex items-center justify-between">
                    <span className="font-mono font-bold text-sm">{it.stock}</span>
                    <span className={`h-2 w-2 rounded-full ${HEAT_COLOR[it.heat] ?? "bg-muted"}`} />
                  </div>
                  <span className="text-[10px] text-muted-foreground font-mono">{it.sector}</span>
                  <span className={`text-xs font-mono font-bold ${cfg.color}`}>{it.final_action}</span>
                  <span className="text-xs font-mono text-muted-foreground">score {it.opportunity_score.toFixed(0)}</span>
                </div>
              );
            })}
            {watchlistItems.length === 0 && (
              <div className="col-span-full py-6 text-center text-muted-foreground text-sm font-mono">
                No watchlist candidates yet
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      <div className="grid lg:grid-cols-3 gap-4">
        {/* Heat map */}
        <Card className="bg-card/50 backdrop-blur border-border/50 lg:col-span-2">
          <CardHeader className="py-3 px-4 border-b border-border/50">
            <CardTitle className="font-mono text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-2">
              <LayoutGrid className="h-3.5 w-3.5" />
              Universe Heat Map
            </CardTitle>
          </CardHeader>
          <CardContent className="p-3">
            <div className="grid grid-cols-4 sm:grid-cols-6 md:grid-cols-8 gap-2">
              {items.map((it) => (
                <HeatTile key={it.stock} stock={it.stock} score={it.opportunity_score} heat={it.heat} action={it.final_action} />
              ))}
            </div>
          </CardContent>
        </Card>

        {/* Sector strength */}
        <Card className="bg-card/50 backdrop-blur border-border/50">
          <CardHeader className="py-3 px-4 border-b border-border/50">
            <CardTitle className="font-mono text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-2">
              <Building2 className="h-3.5 w-3.5" />
              Sector Strength
            </CardTitle>
          </CardHeader>
          <CardContent className="p-2">
            {sectors.map((s) => (
              <div key={s.sector} className="flex items-center justify-between py-2 px-2 rounded hover:bg-muted/10">
                <div className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground font-mono w-4">{s.rank}</span>
                  <span className="font-mono text-sm font-bold">{s.sector}</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono text-muted-foreground">{s.stock_count} stk</span>
                  <span className={`text-xs font-mono font-bold ${STRENGTH_COLOR[s.strength_label] ?? "text-muted-foreground"}`}>
                    {s.avg_opportunity.toFixed(0)}
                  </span>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>
      </div>

      {/* Ranked opportunities table */}
      <Card className="bg-card/50 backdrop-blur border-border/50">
        <CardHeader className="py-3 px-4 border-b border-border/50">
          <CardTitle className="font-mono text-xs uppercase tracking-wider text-muted-foreground flex items-center gap-2">
            <ListOrdered className="h-3.5 w-3.5" />
            Ranked Opportunities
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0 overflow-x-auto">
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-border/50 text-[10px] uppercase tracking-wider text-muted-foreground font-mono">
                <th className="py-2 px-3">#</th>
                <th className="py-2 px-3">Stock</th>
                <th className="py-2 px-3">Strategy</th>
                <th className="py-2 px-3">Price</th>
                <th className="py-2 px-3">Opportunity</th>
                <th className="py-2 px-3">Trade Qual.</th>
                <th className="py-2 px-3">Confidence</th>
                <th className="py-2 px-3">R:R</th>
                <th className="py-2 px-3">Action</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <RankRow key={item.stock} item={item} rank={item.rank} />
              ))}
            </tbody>
          </table>
          {items.length === 0 && (
            <div className="py-8 text-center text-muted-foreground text-sm font-mono">
              Run a scan to see ranked opportunities
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
