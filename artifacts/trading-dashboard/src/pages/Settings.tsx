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

/* eslint-disable @typescript-eslint/no-explicit-any */

export default function Settings() {
  const { toast } = useToast();
  const [generating, setGenerating] = useState(false);
  const [result, setResult] = useState<any>(null);

  const generate = async () => {
    setGenerating(true);
    setResult(null);
    try {
      const r = await fetch(`${API_BASE}/review-package/generate`, { method: "POST" });
      const d = await r.json();
      if (!r.ok || d.error) throw new Error(d.error ?? `HTTP ${r.status}`);
      setResult(d);
      // Auto-download the ZIP
      const dl = await fetch(`${API_BASE}/review-package/download`);
      if (dl.ok) {
        const blob = await dl.blob();
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = d.zip_name ?? "Phase10_Review_Package.zip";
        document.body.appendChild(a); a.click(); document.body.removeChild(a);
        URL.revokeObjectURL(url);
      }
      toast({ title: "Review package ready", description: `${d.file_count} files · ${d.total_size_human}` });
    } catch (e: any) {
      toast({ title: "Generation failed", description: e.message, variant: "destructive" });
    } finally {
      setGenerating(false);
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

      <Card className="border-zinc-800 bg-zinc-900/60">
        <CardHeader className="px-5 pb-2 pt-4">
          <h2 className="flex items-center gap-2 font-mono text-sm font-bold uppercase tracking-widest text-zinc-300">
            <Package className="h-4 w-4 text-primary" />Phase Review Package
          </h2>
        </CardHeader>
        <CardContent className="px-5 pb-5">
          <p className="mb-4 text-xs text-zinc-500">
            Builds a ZIP containing the implementation summary, UI &amp; metrics inventories,
            real 1920×1080 screenshots of every page, export artifacts, API endpoint list,
            feature matrix, live test results and an honest review summary — complete enough
            for an external technical review without extra screenshots. Takes 1–3 minutes
            (headless browser captures ~20 pages).
          </p>
          <Button onClick={generate} disabled={generating} className="gap-2">
            {generating
              ? <><Loader2 className="h-4 w-4 animate-spin" />Generating… (1–3 min)</>
              : <><FileArchive className="h-4 w-4" />Generate Review Package</>}
          </Button>

          {result && (
            <div className="mt-5 space-y-4 rounded-lg border border-zinc-800 bg-zinc-950/50 p-4 text-xs">
              <div className="flex flex-wrap items-center gap-4">
                <span className="flex items-center gap-1.5 text-emerald-400">
                  <CheckCircle2 className="h-4 w-4" />{result.zip_name}
                </span>
                <span className="text-zinc-400">Generation time: <b className="text-zinc-200">{result.generation_seconds}s</b></span>
                <span className="text-zinc-400">Total size: <b className="text-zinc-200">{result.total_size_human}</b></span>
                <span className="text-zinc-400">Screenshots: <b className="text-zinc-200">{result.screenshots}</b></span>
                <span className="text-zinc-400">Exports: <b className="text-zinc-200">{result.exports}</b></span>
                <Button size="sm" variant="outline" className="gap-1.5 text-xs"
                  onClick={async () => {
                    const dl = await fetch(`${API_BASE}/review-package/download`);
                    if (!dl.ok) return;
                    const blob = await dl.blob();
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement("a");
                    a.href = url; a.download = result.zip_name;
                    document.body.appendChild(a); a.click(); document.body.removeChild(a);
                    URL.revokeObjectURL(url);
                  }}>
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

              <details>
                <summary className="cursor-pointer text-zinc-400 hover:text-zinc-200">
                  Files included ({result.file_count})
                </summary>
                <div className="mt-2 max-h-64 overflow-y-auto rounded bg-zinc-900 p-3 text-[11px] leading-5 text-zinc-400">
                  {(result.files_included ?? []).map((f: string) => <div key={f}>{f}</div>)}
                </div>
              </details>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
