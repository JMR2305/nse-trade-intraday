/**
 * CopilotPanel.tsx — Phase 9: Collapsible AI Copilot panel, accessible on every page.
 * Summarizes market regime, sentiment, portfolio health, risks, best opportunity,
 * stocks to avoid, and highest-confidence trade. Voice-ready text included.
 */

import { useState, useEffect, useCallback } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Bot, X, RefreshCw, Loader2, TrendingUp, TrendingDown,
  AlertTriangle, Wallet, Target, Ban, Volume2, Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { API_BASE } from "@/lib/api";
import { Link } from "wouter";

/* eslint-disable @typescript-eslint/no-explicit-any */

const REGIME_COLOR: Record<string, string> = {
  TRENDING_UP: "text-emerald-400", BULLISH: "text-emerald-400",
  SIDEWAYS: "text-warn", NEUTRAL: "text-warn",
  TRENDING_DOWN: "text-red-400", BEARISH: "text-red-400",
  VOLATILE: "text-orange-400",
};

const RISK_COLOR: Record<string, string> = {
  LOW: "text-emerald-400", MEDIUM: "text-warn", HIGH: "text-red-400",
};

export default function CopilotPanel() {
  const [open, setOpen] = useState<boolean>(() => {
    try { return localStorage.getItem("copilot_panel_open") === "1"; }
    catch { return false; }
  });
  useEffect(() => {
    try { localStorage.setItem("copilot_panel_open", open ? "1" : "0"); }
    catch { /* ignore */ }
  }, [open]);
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [unread, setUnread] = useState(0);

  const load = useCallback(async () => {
    setLoading(true); setError(null);
    try {
      const [sResp, aResp] = await Promise.all([
        fetch(`${API_BASE}/copilot/summary`),
        fetch(`${API_BASE}/copilot/alerts?limit=1`),
      ]);
      const s = JSON.parse(await sResp.text());
      if (!sResp.ok || s.error) throw new Error(s.error ?? `HTTP ${sResp.status}`);
      setData(s);
      try {
        const a = JSON.parse(await aResp.text());
        setUnread(a.unread_count ?? 0);
      } catch { /* non-fatal */ }
    } catch (e: any) {
      setError(e.message ?? "Failed to load copilot summary");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (open && !data && !loading) load();
  }, [open, data, loading, load]);

  // Poll unread count lightly even when closed
  useEffect(() => {
    const tick = async () => {
      try {
        const r = await fetch(`${API_BASE}/copilot/alerts?limit=1`);
        const a = JSON.parse(await r.text());
        setUnread(a.unread_count ?? 0);
      } catch { /* ignore */ }
    };
    tick();
    const id = setInterval(tick, 120000);
    return () => clearInterval(id);
  }, []);

  const mkt = data?.market ?? {};
  const pm  = data?.portfolio ?? {};
  const best = data?.best_opportunity;
  const hct  = data?.highest_confidence_trade;

  return (
    <>
      {/* Floating toggle button — visible on every page */}
      <button
        onClick={() => setOpen(v => !v)}
        className={cn(
          "fixed bottom-5 right-5 z-50 flex items-center gap-2 rounded-full border px-4 py-2.5",
          "font-mono text-xs font-bold shadow-lg transition-all",
          open
            ? "bg-zinc-800 border-zinc-600 text-zinc-300"
            : "bg-primary/90 border-primary text-primary-foreground hover:bg-primary"
        )}
        aria-label="Toggle AI Copilot"
      >
        <Bot className="h-4 w-4" />
        AI Copilot
        {unread > 0 && !open && (
          <span className="ml-1 rounded-full bg-red-500 text-white text-[10px] px-1.5 py-0.5 leading-none">
            {unread}
          </span>
        )}
      </button>

      {/* Panel */}
      {open && (
        <div className="fixed bottom-20 right-5 z-50 w-[380px] max-h-[75vh] overflow-y-auto rounded-lg border border-zinc-700 bg-zinc-950/98 shadow-2xl font-mono backdrop-blur">
          <div className="sticky top-0 flex items-center justify-between border-b border-zinc-800 bg-zinc-950 px-4 py-3">
            <div className="flex items-center gap-2">
              <Sparkles className="h-4 w-4 text-primary" />
              <span className="text-sm font-bold text-zinc-200">Today's Summary</span>
              <Badge variant="outline" className="text-[9px] text-warn border-warn">
                RESEARCH
              </Badge>
            </div>
            <div className="flex items-center gap-1">
              <Button size="icon" variant="ghost" className="h-7 w-7" onClick={load} disabled={loading}>
                {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
              </Button>
              <Button size="icon" variant="ghost" className="h-7 w-7" onClick={() => setOpen(false)}>
                <X className="h-3.5 w-3.5" />
              </Button>
            </div>
          </div>

          <div className="p-4 space-y-4 text-xs">
            {loading && !data && (
              <div className="flex items-center justify-center gap-2 py-8 text-zinc-500">
                <Loader2 className="h-4 w-4 animate-spin" />Analyzing market…
              </div>
            )}
            {error && (
              <div className="rounded-md border border-red-800 bg-red-950/30 p-3 text-red-300">
                <AlertTriangle className="mr-1 inline h-3.5 w-3.5" />{error}
              </div>
            )}

            {data && (
              <>
                {/* Market */}
                <div className="grid grid-cols-2 gap-2">
                  <div className="rounded-md border border-zinc-800 bg-zinc-900/60 p-2.5">
                    <div className="text-[10px] text-zinc-500 mb-1">Market Regime</div>
                    <div className={cn("font-bold", REGIME_COLOR[mkt.regime] ?? "text-zinc-200")}>
                      {String(mkt.regime ?? "—").replace(/_/g, " ")}
                    </div>
                  </div>
                  <div className="rounded-md border border-zinc-800 bg-zinc-900/60 p-2.5">
                    <div className="text-[10px] text-zinc-500 mb-1">Sentiment</div>
                    <div className={cn("font-bold", REGIME_COLOR[mkt.sentiment] ?? "text-zinc-200")}>
                      {String(mkt.sentiment ?? "—").replace(/_/g, " ")}
                    </div>
                  </div>
                  <div className="rounded-md border border-zinc-800 bg-zinc-900/60 p-2.5">
                    <div className="text-[10px] text-zinc-500 mb-1">VIX</div>
                    <div className="font-bold text-zinc-200">
                      {mkt.vix ?? "—"} <span className="text-[10px] text-zinc-500">({mkt.vix_category ?? "—"})</span>
                    </div>
                  </div>
                  <div className="rounded-md border border-zinc-800 bg-zinc-900/60 p-2.5">
                    <div className="text-[10px] text-zinc-500 mb-1">Portfolio Risk</div>
                    <div className={cn("font-bold", RISK_COLOR[pm.risk_level] ?? "text-zinc-200")}>
                      {pm.risk_level ?? "—"}
                    </div>
                  </div>
                </div>

                {/* Best opportunity */}
                {best && (
                  <div className="rounded-md border border-emerald-900/50 bg-emerald-950/20 p-3">
                    <div className="mb-1 flex items-center gap-1.5 text-[10px] text-emerald-500">
                      <Target className="h-3 w-3" />BEST OPPORTUNITY
                    </div>
                    <div className="flex items-baseline justify-between">
                      <span className="text-sm font-bold text-emerald-300">{best.symbol}</span>
                      <span className="text-emerald-400">Confidence {Math.round(best.confidence ?? 0)}</span>
                    </div>
                    <div className="mt-0.5 text-[10px] text-zinc-500">
                      {best.action} · Score {best.opportunity_score} · {best.strategy}
                    </div>
                  </div>
                )}

                {/* Highest confidence trade */}
                {hct && hct.symbol !== best?.symbol && (
                  <div className="rounded-md border border-sky-900/50 bg-sky-950/20 p-3">
                    <div className="mb-1 flex items-center gap-1.5 text-[10px] text-sky-500">
                      <TrendingUp className="h-3 w-3" />HIGHEST CONFIDENCE
                    </div>
                    <div className="flex items-baseline justify-between">
                      <span className="text-sm font-bold text-sky-300">{hct.symbol}</span>
                      <span className="text-sky-400">{Math.round(hct.confidence ?? 0)}</span>
                    </div>
                    <div className="mt-0.5 text-[10px] text-zinc-500">{hct.action} · R/R {hct.rr_ratio}</div>
                  </div>
                )}

                {/* Avoid */}
                {data.avoid?.length > 0 && (
                  <div className="rounded-md border border-red-900/40 bg-red-950/10 p-3">
                    <div className="mb-1.5 flex items-center gap-1.5 text-[10px] text-red-500">
                      <Ban className="h-3 w-3" />AVOID
                    </div>
                    {data.avoid.slice(0, 3).map((a: any) => (
                      <div key={a.symbol} className="flex items-baseline justify-between py-0.5">
                        <span className="font-bold text-red-300">{a.symbol}</span>
                        <span className="text-right text-[10px] text-zinc-500">{a.reason}</span>
                      </div>
                    ))}
                  </div>
                )}

                {/* Portfolio */}
                <div className="grid grid-cols-2 gap-2">
                  <div className="rounded-md border border-zinc-800 bg-zinc-900/60 p-2.5">
                    <div className="mb-1 flex items-center gap-1 text-[10px] text-zinc-500">
                      <Wallet className="h-3 w-3" />Cash
                    </div>
                    <div className="font-bold text-zinc-200">₹{Math.round(pm.cash ?? 0).toLocaleString("en-IN")}</div>
                  </div>
                  <div className="rounded-md border border-zinc-800 bg-zinc-900/60 p-2.5">
                    <div className="text-[10px] text-zinc-500 mb-1">Open Positions</div>
                    <div className="font-bold text-zinc-200">{pm.open_positions ?? 0}</div>
                  </div>
                </div>

                {/* Risks */}
                {data.risks?.length > 0 && (
                  <div>
                    <div className="mb-1.5 flex items-center gap-1.5 text-[10px] text-zinc-500">
                      <AlertTriangle className="h-3 w-3" />OPEN RISKS
                    </div>
                    {data.risks.slice(0, 4).map((r: string, i: number) => (
                      <div key={i} className="py-0.5 text-[10px] text-zinc-400">• {r}</div>
                    ))}
                  </div>
                )}

                {/* Voice-ready summary */}
                <div className="rounded-md border border-zinc-800 bg-zinc-900/40 p-3">
                  <div className="mb-1 flex items-center gap-1.5 text-[10px] text-zinc-500">
                    <Volume2 className="h-3 w-3" />VOICE-READY SUMMARY
                  </div>
                  <p className="text-[10px] leading-relaxed text-zinc-400 italic">"{data.voice_text}"</p>
                </div>

                <div className="flex gap-2">
                  <Link href="/ai-copilot" onClick={() => setOpen(false)}
                    className="flex-1 rounded-md border border-zinc-700 bg-zinc-900 py-1.5 text-center text-[10px] text-zinc-300 hover:border-zinc-500">
                    Full Copilot →
                  </Link>
                  <Link href="/notifications" onClick={() => setOpen(false)}
                    className="flex-1 rounded-md border border-zinc-700 bg-zinc-900 py-1.5 text-center text-[10px] text-zinc-300 hover:border-zinc-500">
                    Notifications{unread > 0 ? ` (${unread})` : ""} →
                  </Link>
                </div>

                <div className="text-[9px] text-zinc-600 text-center">
                  {data.label} · Scan {data.scan_id} · {data.snapshot_ts}
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </>
  );
}
