import { useState } from "react";
import {
  useGetPredictiveIntelligence,
  getGetPredictiveIntelligenceQueryKey,
} from "@workspace/api-client-react";
import { History, Loader2, ChevronDown, ChevronRight, AlertTriangle } from "lucide-react";
import { cn } from "@/lib/utils";

const LEVEL_STYLES: Record<string, string> = {
  HIGH: "text-emerald-400 border-emerald-400/40 bg-emerald-400/10",
  MEDIUM: "text-warn border-warn bg-warn-surface",
  LOW: "text-orange-400 border-orange-400/40 bg-orange-400/10",
  INSUFFICIENT: "text-zinc-500 border-zinc-700 bg-zinc-800/40",
};

const fmtPct = (v: number | null | undefined, sign = false) =>
  v === null || v === undefined ? "—" : `${sign && v > 0 ? "+" : ""}${v.toFixed(1)}%`;

function Metric({ label, value, valueClass }: { label: string; value: string; valueClass?: string }) {
  return (
    <div className="bg-zinc-800/50 rounded-md p-2">
      <div className="text-[10px] text-muted-foreground font-mono mb-0.5 uppercase tracking-wide">{label}</div>
      <div className={cn("text-sm font-mono font-bold", valueClass ?? "text-foreground")}>{value}</div>
    </div>
  );
}

export function EvidenceBody({ symbol }: { symbol: string }) {
  const { data, isLoading, isError } = useGetPredictiveIntelligence(symbol, {
    query: {
      queryKey: getGetPredictiveIntelligenceQueryKey(symbol),
      staleTime: 5 * 60 * 1000,
    },
  });

  if (isLoading) {
    return (
      <div className="flex items-center gap-2 text-xs font-mono text-muted-foreground py-2">
        <Loader2 className="h-3.5 w-3.5 animate-spin" />
        Comparing with historical trades…
      </div>
    );
  }
  if (isError || !data) {
    return (
      <div className="text-xs font-mono text-red-400 py-2">
        Could not load historical evidence.
      </div>
    );
  }

  const ev = data.evidence;
  const clr = (v: number | null | undefined) =>
    v === null || v === undefined ? undefined : v > 0 ? "text-emerald-400" : v < 0 ? "text-red-400" : undefined;

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-2">
        <Metric label="Similar Trades" value={String(ev.matches)} />
        <Metric label="Win Rate" value={ev.win_rate != null ? `${ev.win_rate.toFixed(0)}%` : "—"}
          valueClass={ev.win_rate != null ? (ev.win_rate >= 60 ? "text-emerald-400" : ev.win_rate < 45 ? "text-red-400" : undefined) : undefined} />
        <Metric label="Avg Return" value={fmtPct(ev.average_return, true)} valueClass={clr(ev.average_return)} />
        <Metric label="Expected Value" value={fmtPct(ev.expected_value, true)} valueClass={clr(ev.expected_value)} />
        <Metric label="Profit Factor" value={ev.profit_factor != null ? ev.profit_factor.toFixed(2) : "—"} valueClass={clr((ev.profit_factor ?? 0) - 1)} />
        <div className="bg-zinc-800/50 rounded-md p-2">
          <div className="text-[10px] text-muted-foreground font-mono mb-0.5 uppercase tracking-wide">Evidence</div>
          <span className={cn("inline-flex font-mono text-[11px] font-bold px-1.5 py-0.5 rounded border", LEVEL_STYLES[ev.confidence_level] ?? LEVEL_STYLES.INSUFFICIENT)}>
            {ev.confidence_level}
          </span>
        </div>
      </div>

      {data.adjustment !== 0 && data.base_confidence != null && (
        <div className="text-xs font-mono text-muted-foreground">
          Signal confidence adjusted by{" "}
          <span className={data.adjustment > 0 ? "text-emerald-400" : "text-red-400"}>
            {data.adjustment > 0 ? "+" : ""}{data.adjustment}
          </span>{" "}
          → <span className="text-foreground">{data.adjusted_confidence?.toFixed(0)}%</span>{" "}
          (base {data.base_confidence.toFixed(0)}%)
        </div>
      )}

      {data.warnings.map((w) => (
        <div key={w} className="flex items-center gap-1.5 text-xs font-mono text-orange-400">
          <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
          {w}
        </div>
      ))}
    </div>
  );
}

export default function HistoricalEvidence({ symbol, defaultOpen = false }: { symbol: string; defaultOpen?: boolean }) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="border-t border-zinc-800 pt-3">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 text-xs font-mono text-primary/80 uppercase tracking-wider hover:text-primary"
        data-testid={`button-evidence-${symbol}`}
      >
        {open ? <ChevronDown className="h-3.5 w-3.5" /> : <ChevronRight className="h-3.5 w-3.5" />}
        <History className="h-3.5 w-3.5" />
        Historical Evidence
      </button>
      {open && <div className="mt-3"><EvidenceBody symbol={symbol} /></div>}
    </div>
  );
}
