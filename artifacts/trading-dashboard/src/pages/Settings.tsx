/**
 * Settings.tsx — application settings & tools.
 * Currently hosts the Phase Review Package generator: builds a ZIP with
 * implementation docs, metrics, real page screenshots, exports and an honest
 * review summary, then downloads it.
 */

import { useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import {
  Settings as SettingsIcon, Package, Loader2, Download, AlertTriangle,
  CheckCircle2, FileArchive,
} from "lucide-react";
import { API_BASE } from "@/lib/api";
import { useToast } from "@/hooks/use-toast";
import DataFreshnessBar from "@/components/DataFreshnessBar";
import Phase20Settings from "@/components/Phase20Settings";

/* eslint-disable @typescript-eslint/no-explicit-any */

export default function Settings() {
  const { toast } = useToast();
  const [generating, setGenerating] = useState(false);
  const [stage, setStage] = useState<string>("");
  const [elapsed, setElapsed] = useState<number | null>(null);
  const [result, setResult] = useState<any>(null);

  const downloadZip = async (zipName: string) => {
    const dl = await fetch(`${API_BASE}/review-package/download`);
    if (!dl.ok) return;
    const blob = await dl.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = zipName;
    document.body.appendChild(a); a.click(); document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const generate = async () => {
    setGenerating(true);
    setResult(null);
    setStage("Starting…");
    setElapsed(null);
    try {
      // Start the background job (returns immediately), then poll status.
      // The job itself takes 2-5 min — far longer than the request timeout.
      const r = await fetch(`${API_BASE}/review-package/generate`, { method: "POST" });
      const d = await r.json();
      if (!r.ok || d.error) throw new Error(d.error ?? `HTTP ${r.status}`);

      for (;;) {
        await new Promise((ok) => setTimeout(ok, 4000));
        let s: any;
        try {
          const sr = await fetch(`${API_BASE}/review-package/status`);
          s = await sr.json();
        } catch {
          continue; // transient network blip — keep polling
        }
        if (s.status === "running") {
          setStage(s.stage ?? "Working…");
          setElapsed(s.elapsed_seconds ?? null);
          continue;
        }
        if (s.status === "error") throw new Error(s.error ?? "Generation failed");
        if (s.status === "done" && s.result) {
          setResult(s.result);
          await downloadZip(s.result.zip_name ?? "Review_Package.zip");
          toast({
            title: "Review package ready",
            description: `${s.result.file_count} files · ${s.result.total_size_human}`,
          });
          break;
        }
        throw new Error("Generation job is no longer running.");
      }
    } catch (e: any) {
      toast({ title: "Generation failed", description: e.message, variant: "destructive" });
    } finally {
      setGenerating(false);
      setStage("");
      setElapsed(null);
    }
  };

  return (
    <div className="space-y-6 font-mono">
      <div className="flex items-center gap-3">
        <SettingsIcon className="h-5 w-5 text-primary" />
        <h1 className="text-xl font-bold text-foreground">Settings</h1>
        <Badge variant="outline" className="text-[10px] text-amber-400 border-amber-700">
          PAPER / LIVE DATA VALIDATION
        </Badge>
      </div>

      <DataFreshnessBar variant="none" />

      <Phase20Settings />

      <Card className="border-zinc-800 bg-zinc-900/60">
        <CardHeader className="px-5 pb-2 pt-4">
          <h2 className="flex items-center gap-2 font-mono text-sm font-bold uppercase tracking-widest text-zinc-300">
            <Package className="h-4 w-4 text-primary" />Phase Review Package
          </h2>
        </CardHeader>
        <CardContent className="px-5 pb-5">
          <p className="mb-4 text-xs text-zinc-500">
            Builds Phase19_Review_Package.zip: full-page screenshots of every registered page,
            9 CSV exports (opportunities, signals, portfolio, performance, AI performance,
            notifications, learning, trade history, risk analytics), 13 JSON exports
            (scan snapshot, AI decisions, dashboard/portfolio/learning summaries, diagnostics,
            production readiness, Phase 16 validation, Phase 17 QA last run and release
            dashboard, Phase 18 notebook entries, evidence tracker and weekly review),
            implementation &amp; readiness reports, feature matrix (including Phase 19 Kite
            Connect and mobile sidebar rows) and live test results — always reflects the
            latest application changes. Takes 2–5 minutes (headless browser captures every
            page, full-page).
          </p>
          <Button onClick={generate} disabled={generating} className="gap-2">
            {generating
              ? <><Loader2 className="h-4 w-4 animate-spin" />Generating… (2–5 min)</>
              : <><FileArchive className="h-4 w-4" />Generate Review Package</>}
          </Button>
          {generating && (
            <p className="mt-3 text-xs text-zinc-400">
              {stage}{elapsed != null ? ` — ${elapsed}s elapsed` : ""}
            </p>
          )}

          {result && (
            <div className="mt-5 space-y-4 rounded-lg border border-zinc-800 bg-zinc-950/50 p-4 text-xs">
              <div className="grid gap-1.5 sm:grid-cols-2">
                <span className="flex items-center gap-1.5 text-emerald-400">
                  <CheckCircle2 className="h-4 w-4" />
                  Screenshots Generated ({result.screenshot_count ?? 0} pages)
                </span>
                <span className="flex items-center gap-1.5 text-emerald-400">
                  <CheckCircle2 className="h-4 w-4" />
                  Reports Generated ({(result.reports ?? []).length} reports)
                </span>
                <span className="flex items-center gap-1.5 text-emerald-400">
                  <CheckCircle2 className="h-4 w-4" />CSV Generated ({result.csv_count ?? 0} files)
                </span>
                <span className="flex items-center gap-1.5 text-emerald-400">
                  <CheckCircle2 className="h-4 w-4" />JSON Generated ({result.json_count ?? 0} files)
                </span>
                <span className="flex items-center gap-1.5 text-emerald-400">
                  <CheckCircle2 className="h-4 w-4" />ZIP Ready for Download — {result.zip_name}
                </span>
              </div>
              <div className="flex flex-wrap items-center gap-4 border-t border-zinc-800 pt-3">
                <span className="text-zinc-400">Generation time: <b className="text-zinc-200">{result.generation_seconds}s</b></span>
                <span className="text-zinc-400">Total files: <b className="text-zinc-200">{result.file_count}</b></span>
                <span className="text-zinc-400">ZIP size: <b className="text-zinc-200">{result.total_size_human}</b></span>
                <Button size="sm" variant="outline" className="gap-1.5 text-xs"
                  onClick={() => downloadZip(result.zip_name ?? "Review_Package.zip")}>
                  <Download className="h-3.5 w-3.5" />Download again
                </Button>
              </div>

              {(result.warnings ?? []).length > 0 && (
                <div className="rounded border border-amber-900/50 bg-amber-950/20 p-3">
                  <div className="mb-1 flex items-center gap-1.5 font-bold text-amber-400">
                    <AlertTriangle className="h-3.5 w-3.5" />Warnings
                  </div>
                  <ul className="list-inside list-disc space-y-0.5 text-amber-200/80">
                    {result.warnings.map((w: string, i: number) => <li key={i}>{w}</li>)}
                  </ul>
                </div>
              )}

              {(result.reports ?? []).length > 0 && (
                <details>
                  <summary className="cursor-pointer text-zinc-400 hover:text-zinc-200">
                    Reports included ({(result.reports ?? []).length})
                  </summary>
                  <div className="mt-2 max-h-64 overflow-y-auto rounded bg-zinc-900 p-3 text-[11px] leading-5 text-zinc-400">
                    {(result.reports ?? []).map((f: string) => <div key={f}>{f}</div>)}
                  </div>
                </details>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
