import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  History, TrendingUp, TrendingDown, Activity, ChevronDown, ChevronUp,
  ArrowRight, Minus,
} from "lucide-react";

// ── Types ─────────────────────────────────────────────────────────────────────

interface SnapshotSignal {
  stock?: string;
  symbol?: string;
  signal?: string;
  confidence?: number;
  price?: number;
}

interface Snapshot {
  scan_id: string;
  snapshot_ts: string;
  signals: SnapshotSignal[];
  market_context: { regime?: string; breadth_label?: string } & Record<string, unknown>;
}

// ── Config ────────────────────────────────────────────────────────────────────

const SIGNAL_STYLE: Record<string, string> = {
  STRONG_BUY:  "bg-emerald-500/20 text-emerald-400 border-emerald-500/50",
  BUY:         "bg-green-500/20 text-green-400 border-green-500/50",
  WATCH:       "bg-yellow-500/20 text-yellow-400 border-yellow-500/50",
  SELL:        "bg-red-500/20 text-red-400 border-red-500/50",
  STRONG_SELL: "bg-rose-500/20 text-rose-400 border-rose-500/50",
  NO_TRADE:    "bg-muted/50 text-muted-foreground border-border",
};

const LIMIT_OPTIONS = [10, 30, 60];

function symOf(s: SnapshotSignal): string {
  return String(s.stock ?? s.symbol ?? "").toUpperCase();
}

function SignalPill({ signal }: { signal?: string }) {
  const key = String(signal ?? "NO_TRADE").toUpperCase();
  const style = SIGNAL_STYLE[key] ?? SIGNAL_STYLE.NO_TRADE;
  const Icon = key.includes("BUY") ? TrendingUp : key.includes("SELL") ? TrendingDown : Activity;
  return (
    <Badge variant="outline" className={`gap-1 font-mono text-[10px] font-bold ${style}`}>
      <Icon className="h-3 w-3" />
      {key.replace("_", " ")}
    </Badge>
  );
}

function fmtTs(ts: string): string {
  try {
    return new Date(ts).toLocaleString("en-IN", {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone: "Asia/Kolkata",
    });
  } catch {
    return ts;
  }
}

// ── Snapshot row ──────────────────────────────────────────────────────────────

function SnapshotRow({ snap, prev }: { snap: Snapshot; prev?: Snapshot }) {
  const [open, setOpen] = useState(false);

  const prevBySym = useMemo(() => {
    const m = new Map<string, string>();
    for (const s of prev?.signals ?? []) m.set(symOf(s), String(s.signal ?? "NO_TRADE").toUpperCase());
    return m;
  }, [prev]);

  const signals = Array.isArray(snap.signals) ? snap.signals : [];
  const counts = useMemo(() => {
    const c = { buy: 0, sell: 0, watch: 0, none: 0 };
    for (const s of signals) {
      const sig = String(s.signal ?? "").toUpperCase();
      if (sig.includes("BUY")) c.buy++;
      else if (sig.includes("SELL")) c.sell++;
      else if (sig === "WATCH") c.watch++;
      else c.none++;
    }
    return c;
  }, [signals]);

  const changes = useMemo(() => {
    if (!prev) return [];
    const out: Array<{ sym: string; from: string; to: string }> = [];
    for (const s of signals) {
      const sym = symOf(s);
      const now = String(s.signal ?? "NO_TRADE").toUpperCase();
      const before = prevBySym.get(sym);
      if (before !== undefined && before !== now) out.push({ sym, from: before, to: now });
    }
    return out;
  }, [signals, prev, prevBySym]);

  const regime = snap.market_context?.regime;

  return (
    <Card>
      <CardHeader
        className="cursor-pointer py-3"
        onClick={() => setOpen(o => !o)}
        data-testid={`row-snapshot-${snap.scan_id}`}
      >
        <div className="flex flex-wrap items-center gap-3">
          <History className="h-4 w-4 text-primary shrink-0" />
          <span className="font-mono text-sm">{fmtTs(snap.snapshot_ts)}</span>
          {regime && (
            <Badge variant="outline" className="text-[10px] font-mono">{String(regime)}</Badge>
          )}
          <span className="text-xs font-mono text-muted-foreground">
            <span className="text-green-400">{counts.buy} BUY</span>
            {" · "}
            <span className="text-red-400">{counts.sell} SELL</span>
            {" · "}
            <span className="text-yellow-400">{counts.watch} WATCH</span>
            {" · "}
            {counts.none} NO TRADE
          </span>
          {prev && (
            <Badge
              variant="outline"
              className={`text-[10px] font-mono ${changes.length ? "text-orange-400 border-orange-500/50" : "text-muted-foreground"}`}
            >
              {changes.length ? `${changes.length} changed vs previous` : "no changes"}
            </Badge>
          )}
          <span className="ml-auto text-muted-foreground">
            {open ? <ChevronUp className="h-4 w-4" /> : <ChevronDown className="h-4 w-4" />}
          </span>
        </div>
      </CardHeader>
      {open && (
        <CardContent className="pt-0 space-y-4">
          {changes.length > 0 && (
            <div>
              <div className="text-xs font-semibold text-muted-foreground mb-2">
                Changes since previous scan
              </div>
              <div className="flex flex-wrap gap-2">
                {changes.map(c => (
                  <div key={c.sym} className="flex items-center gap-1.5 rounded-md border border-border px-2 py-1">
                    <span className="font-mono text-xs font-bold">{c.sym}</span>
                    <SignalPill signal={c.from} />
                    <ArrowRight className="h-3 w-3 text-muted-foreground" />
                    <SignalPill signal={c.to} />
                  </div>
                ))}
              </div>
            </div>
          )}
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground border-b border-border">
                  <th className="py-1.5 pr-4">Symbol</th>
                  <th className="py-1.5 pr-4">Signal</th>
                  <th className="py-1.5 pr-4">Confidence</th>
                  <th className="py-1.5 pr-4">Price</th>
                </tr>
              </thead>
              <tbody>
                {signals.map(s => {
                  const sym = symOf(s);
                  return (
                    <tr key={sym} className="border-b border-border/50">
                      <td className="py-1.5 pr-4 font-mono font-bold">{sym}</td>
                      <td className="py-1.5 pr-4"><SignalPill signal={s.signal} /></td>
                      <td className="py-1.5 pr-4 font-mono text-xs">
                        {typeof s.confidence === "number" ? Math.round(s.confidence) : "—"}
                      </td>
                      <td className="py-1.5 pr-4 font-mono text-xs">
                        {typeof s.price === "number" ? `₹${s.price.toFixed(2)}` : "—"}
                      </td>
                    </tr>
                  );
                })}
                {signals.length === 0 && (
                  <tr><td colSpan={4} className="py-3 text-center text-muted-foreground text-xs">No signals in this snapshot</td></tr>
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      )}
    </Card>
  );
}

// ── Symbol timeline matrix ────────────────────────────────────────────────────

function TimelineMatrix({ snapshots }: { snapshots: Snapshot[] }) {
  // Oldest → newest, left to right
  const ordered = useMemo(() => [...snapshots].reverse(), [snapshots]);
  const symbols = useMemo(() => {
    const set = new Set<string>();
    for (const snap of ordered) for (const s of snap.signals ?? []) set.add(symOf(s));
    return Array.from(set).sort();
  }, [ordered]);

  if (symbols.length === 0) return null;

  const cellColor = (sig?: string) => {
    const k = String(sig ?? "").toUpperCase();
    if (k === "STRONG_BUY") return "bg-emerald-500";
    if (k === "BUY") return "bg-green-500";
    if (k === "WATCH") return "bg-yellow-500";
    if (k === "SELL") return "bg-red-500";
    if (k === "STRONG_SELL") return "bg-rose-600";
    return "bg-muted";
  };

  return (
    <Card>
      <CardHeader className="py-3">
        <CardTitle className="text-sm flex items-center gap-2">
          <Activity className="h-4 w-4 text-primary" />
          Recommendation timeline (oldest → newest)
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="overflow-x-auto">
          <table className="text-xs">
            <tbody>
              {symbols.map(sym => (
                <tr key={sym}>
                  <td className="pr-3 py-0.5 font-mono font-bold whitespace-nowrap">{sym}</td>
                  {ordered.map(snap => {
                    const sig = (snap.signals ?? []).find(s => symOf(s) === sym);
                    return (
                      <td key={snap.scan_id} className="px-0.5 py-0.5">
                        <div
                          className={`w-4 h-4 rounded-sm ${sig ? cellColor(sig.signal) : "bg-transparent border border-border/40"}`}
                          title={`${sym} · ${fmtTs(snap.snapshot_ts)} · ${sig ? String(sig.signal ?? "NO_TRADE") : "not scanned"}`}
                        />
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex flex-wrap gap-3 mt-3 text-[10px] font-mono text-muted-foreground">
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-sm bg-emerald-500 inline-block" />STRONG BUY</span>
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-sm bg-green-500 inline-block" />BUY</span>
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-sm bg-yellow-500 inline-block" />WATCH</span>
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-sm bg-red-500 inline-block" />SELL</span>
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-sm bg-rose-600 inline-block" />STRONG SELL</span>
          <span className="flex items-center gap-1"><span className="w-3 h-3 rounded-sm bg-muted inline-block" />NO TRADE</span>
        </div>
      </CardContent>
    </Card>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function SignalHistory() {
  const [limit, setLimit] = useState(30);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");

  const params = new URLSearchParams({ limit: String(limit) });
  if (from) params.set("from", from);
  if (to) params.set("to", to);

  const { data, isLoading, error } = useQuery<{ snapshots: Snapshot[] }>({
    queryKey: ["signal-history", limit, from, to],
    queryFn: () => apiJson(`/signal-history?${params.toString()}`),
    refetchInterval: 60_000,
  });

  const snapshots = data?.snapshots ?? [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <h1 className="text-xl font-bold flex items-center gap-2">
          <History className="h-5 w-5 text-primary" />
          Signal History
        </h1>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          {LIMIT_OPTIONS.map(n => (
            <Button
              key={n}
              size="sm"
              variant={limit === n ? "default" : "outline"}
              onClick={() => setLimit(n)}
              data-testid={`button-limit-${n}`}
            >
              Last {n}
            </Button>
          ))}
          <input
            type="date"
            value={from}
            onChange={e => setFrom(e.target.value)}
            className="h-8 rounded-md border border-border bg-background px-2 text-xs font-mono"
            data-testid="input-from-date"
          />
          <Minus className="h-3 w-3 text-muted-foreground" />
          <input
            type="date"
            value={to}
            onChange={e => setTo(e.target.value)}
            className="h-8 rounded-md border border-border bg-background px-2 text-xs font-mono"
            data-testid="input-to-date"
          />
          {(from || to) && (
            <Button size="sm" variant="ghost" onClick={() => { setFrom(""); setTo(""); }}>
              Clear
            </Button>
          )}
        </div>
      </div>

      <p className="text-sm text-muted-foreground">
        Every intelligence scan is saved as an immutable snapshot so you can review how
        BUY / SELL recommendations changed over time.
      </p>

      {isLoading && (
        <Card><CardContent className="py-8 text-center text-muted-foreground text-sm">Loading signal history…</CardContent></Card>
      )}
      {error != null && (
        <Card><CardContent className="py-8 text-center text-red-400 text-sm">
          Failed to load signal history: {error instanceof Error ? error.message : String(error)}
        </CardContent></Card>
      )}
      {!isLoading && !error && snapshots.length === 0 && (
        <Card><CardContent className="py-8 text-center text-muted-foreground text-sm">
          No snapshots yet. History starts accumulating from the next intelligence scan.
        </CardContent></Card>
      )}

      {snapshots.length > 1 && <TimelineMatrix snapshots={snapshots} />}

      <div className="space-y-2">
        {snapshots.map((snap, i) => (
          <SnapshotRow key={snap.scan_id} snap={snap} prev={snapshots[i + 1]} />
        ))}
      </div>
    </div>
  );
}
