/**
 * LiveMarketTicker — Phase 11: live index strip (NIFTY / BANKNIFTY / INDIA VIX)
 * powered by the SSE stream. Honest values only — shows "Unavailable" when
 * data is missing, never fabricated numbers. PAPER / RESEARCH ONLY.
 */
import { useLiveStream, type LiveQuote } from "@/hooks/useLiveStream";
import { cn } from "@/lib/utils";
import { Wifi, WifiOff, RefreshCw } from "lucide-react";

const INDICES: { key: string; label: string }[] = [
  { key: "NIFTY", label: "NIFTY 50" },
  { key: "BANKNIFTY", label: "BANK NIFTY" },
  { key: "INDIAVIX", label: "INDIA VIX" },
];

const STATE_CLS: Record<string, string> = {
  OPEN: "text-emerald-400 border-emerald-700",
  PRE_OPEN: "text-sky-400 border-sky-700",
  POST_CLOSE: "text-amber-400 border-amber-700",
  CLOSED: "text-zinc-400 border-zinc-600",
  WEEKEND: "text-zinc-400 border-zinc-600",
  HOLIDAY: "text-violet-400 border-violet-700",
};

function QuoteChip({ label, q }: { label: string; q: LiveQuote | undefined }) {
  if (!q || q.ltp == null) {
    return (
      <div className="flex items-baseline gap-1.5 font-mono text-[10px]">
        <span className="text-zinc-500">{label}</span>
        <span className="text-zinc-600">Unavailable</span>
      </div>
    );
  }
  const up = (q.change ?? 0) >= 0;
  return (
    <div className="flex items-baseline gap-1.5 font-mono text-[10px]" title={`source: ${q.source ?? "?"} · ${q.fetch_ts ?? ""}${q.from_cache ? ` · cached ${q.cache_age_s}s` : ""}`}>
      <span className="text-zinc-500">{label}</span>
      <span className="text-zinc-100 font-semibold">{q.ltp.toLocaleString("en-IN", { maximumFractionDigits: 2 })}</span>
      {q.change_pct != null && (
        <span className={cn("font-medium", up ? "text-emerald-400" : "text-red-400")}>
          {up ? "▲" : "▼"} {Math.abs(q.change_pct).toFixed(2)}%
        </span>
      )}
    </div>
  );
}

export default function LiveMarketTicker() {
  const { connection, quotes, market } = useLiveStream();

  return (
    <div
      className="h-8 flex items-center gap-4 px-4 border-b border-border bg-background/80 backdrop-blur flex-shrink-0 overflow-x-auto"
      data-testid="live-market-ticker"
    >
      {/* Connection state */}
      <div className="flex items-center gap-1 font-mono text-[9px]" data-testid="stream-connection-status">
        {connection === "connected"
          ? <Wifi className="h-3 w-3 text-emerald-400" />
          : connection === "reconnecting"
            ? <RefreshCw className="h-3 w-3 text-amber-400 animate-spin" />
            : <WifiOff className="h-3 w-3 text-red-400" />}
        <span className={cn(
          connection === "connected" ? "text-emerald-400"
            : connection === "reconnecting" ? "text-amber-400" : "text-red-400",
        )}>
          {/* Use canonical DataStatus vocabulary: LIVE when connected, DELAYED when
              reconnecting (data may be slightly behind), UNAVAILABLE when offline.
              "LIVE STREAM" is suppressed — it must never appear when the feed is down. */}
          {connection === "connected"
            ? "LIVE"
            : connection === "reconnecting"
            ? "DELAYED"
            : "UNAVAILABLE"}
        </span>
      </div>

      {/* Market state */}
      {market?.state && (
        <span
          className={cn("font-mono text-[9px] border rounded px-1.5 py-0.5",
            STATE_CLS[market.state] ?? "text-zinc-400 border-zinc-600")}
          title={market.next_transition
            ? `Next: ${market.next_transition.event} at ${market.next_transition.at_ist}`
            : undefined}
          data-testid="market-state-badge"
        >
          MARKET {market.state.replace("_", " ")}
          {market.holiday_today ? ` — ${market.holiday_today}` : ""}
        </span>
      )}

      {INDICES.map(({ key, label }) => (
        <QuoteChip key={key} label={label} q={quotes[key]} />
      ))}

      <span className="ml-auto font-mono text-[9px] text-amber-500/80 whitespace-nowrap">
        PAPER / RESEARCH ONLY
      </span>
    </div>
  );
}
