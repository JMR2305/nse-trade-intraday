/**
 * ResearchExportPanel.tsx — Research Package & ChatGPT Report export UI.
 *
 * READ-ONLY — never changes live trading state, portfolio, or decisions.
 * Gathers existing analysis results and packages them for offline review.
 */
import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Package, FileText, Download, Loader2, CheckCircle2,
  AlertCircle, ChevronDown, ChevronRight,
} from "lucide-react";
import { cn } from "@/lib/utils";

import { API_BASE } from "@/lib/api";

type GenStatus = "idle" | "generating" | "done" | "error";

interface GenResult {
  filename?: string;
  size_kb?: number;
  generated_at?: string;
  git_commit?: string;
  verdict?: string;
  ev_verdict?: string;
  validation_available?: boolean;
  error?: string;
}

async function callGenerate(endpoint: string): Promise<GenResult> {
  const res = await fetch(`${API_BASE}/${endpoint}`, { method: "POST" });
  const body = await res.json();
  if (!res.ok || body.error) throw new Error(body.error || `HTTP ${res.status}`);
  return body;
}

async function downloadBlob(url: string, filename: string): Promise<void> {
  const res = await fetch(url);
  if (!res.ok) {
    let msg = `Download failed (HTTP ${res.status})`;
    try { const b = await res.json(); if (b.error) msg = b.error; } catch { /* ignore */ }
    throw new Error(msg);
  }
  const blob = await res.blob();
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(href);
}

function StatusIcon({ status }: { status: GenStatus }) {
  if (status === "generating")
    return <Loader2 className="h-4 w-4 animate-spin text-violet-400" />;
  if (status === "done")
    return <CheckCircle2 className="h-4 w-4 text-emerald-400" />;
  if (status === "error")
    return <AlertCircle className="h-4 w-4 text-red-400" />;
  return null;
}

function IncludesList({ items }: { items: string[] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="mt-2">
      <button
        className="flex items-center gap-1 text-[10px] font-mono text-muted-foreground hover:text-zinc-300 transition-colors"
        onClick={() => setOpen(!open)}
      >
        {open ? <ChevronDown className="h-3 w-3" /> : <ChevronRight className="h-3 w-3" />}
        {open ? "Hide" : "Show"} what's included ({items.length} items)
      </button>
      {open && (
        <ul className="mt-1.5 space-y-0.5 pl-3">
          {items.map((item) => (
            <li key={item} className="text-[10px] font-mono text-zinc-400 flex items-center gap-1.5">
              <span className="w-1 h-1 rounded-full bg-zinc-600 flex-shrink-0" />
              {item}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const PACKAGE_CONTENTS = [
  "executive_summary.md — high-level narrative",
  "chatgpt_report.md — single-file ChatGPT briefing",
  "metadata/run_metadata.json — timestamp, git commit, seed",
  "metadata/config_snapshot.json — full ValidationConfig",
  "reports/wf_report.csv — walk-forward summary",
  "reports/wf_windows.csv — per-window metrics",
  "reports/wf_evidence_report.csv — Phase 3A.5 evidence",
  "trades/wf_trades.csv — all OOS simulated trades",
  "trades/wf_evidence_trades.csv — evidence-tagged trades",
  "calibration/wf_calibration.csv — reliability bands",
  "costs/wf_costs.csv — execution cost breakdown",
  "configuration/parameters.json — all parameters",
  "README.md — package guide",
];

const CHATGPT_CONTENTS = [
  "System context and capital/universe description",
  "Walk-forward verdict and evidence quality verdict",
  "Full model performance table (return, Sharpe, drawdown…)",
  "Model comparison: Base vs Full vs Gated",
  "Confidence calibration (Brier, ECE, log loss)",
  "Market regime coverage breakdown",
  "Strategy and sector performance tables",
  "Per-window results table",
  "Concentration and small-sample warnings",
  "Before vs After comparison (vs previous package)",
  "Configuration snapshot (JSON)",
  "Known limitations list",
  "Live behaviour change statement (always 'No')",
  "Suggested ChatGPT questions",
];

export default function ResearchExportPanel() {
  const [pkgStatus, setPkgStatus] = useState<GenStatus>("idle");
  const [pkgResult, setPkgResult] = useState<GenResult | null>(null);
  const [pkgError, setPkgError] = useState<string>("");

  const [rptStatus, setRptStatus] = useState<GenStatus>("idle");
  const [rptResult, setRptResult] = useState<GenResult | null>(null);
  const [rptError, setRptError] = useState<string>("");

  async function handleGeneratePackage() {
    setPkgStatus("generating");
    setPkgError("");
    try {
      const result = await callGenerate("research-package/generate");
      setPkgResult(result);
      setPkgStatus("done");
      // auto-download
      await downloadBlob(
        `${API_BASE}/research-package/download`,
        result.filename ?? "research_package.zip",
      );
    } catch (e) {
      setPkgError(e instanceof Error ? e.message : String(e));
      setPkgStatus("error");
    }
  }

  async function handleGenerateChatGPT() {
    setRptStatus("generating");
    setRptError("");
    try {
      const result = await callGenerate("chatgpt-report/generate");
      setRptResult(result);
      setRptStatus("done");
      // auto-download
      await downloadBlob(
        `${API_BASE}/chatgpt-report/download`,
        "chatgpt_report.md",
      );
    } catch (e) {
      setRptError(e instanceof Error ? e.message : String(e));
      setRptStatus("error");
    }
  }

  async function handleRedownloadPackage() {
    try {
      await downloadBlob(
        `${API_BASE}/research-package/download`,
        pkgResult?.filename ?? "research_package.zip",
      );
    } catch (e) {
      setPkgError(e instanceof Error ? e.message : String(e));
    }
  }

  async function handleRedownloadChatGPT() {
    try {
      await downloadBlob(`${API_BASE}/chatgpt-report/download`, "chatgpt_report.md");
    } catch (e) {
      setRptError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <Card>
      <CardHeader className="py-3">
        <CardTitle className="text-sm font-mono flex items-center gap-2 flex-wrap">
          <Package className="h-4 w-4 text-sky-400" />
          Research Export
          <Badge variant="outline" className="text-[10px] font-mono text-sky-300 border-sky-500/40">
            READ-ONLY
          </Badge>
        </CardTitle>
      </CardHeader>
      <CardContent className="pt-0">
        <p className="text-[11px] font-mono text-muted-foreground mb-4">
          Package all available analysis results into a single download — 
          instead of uploading 15 screenshots to ChatGPT.
        </p>

        <div className="grid md:grid-cols-2 gap-4">
          {/* ── Research Package (ZIP) ─────────────────────────────────── */}
          <div className={cn(
            "rounded-md border p-4 space-y-3 transition-colors",
            pkgStatus === "done" ? "border-emerald-500/30 bg-emerald-500/5"
              : pkgStatus === "error" ? "border-red-500/30 bg-red-500/5"
              : "border-zinc-700 bg-zinc-800/30",
          )}>
            <div className="flex items-center gap-2">
              <Package className="h-4 w-4 text-sky-400 flex-shrink-0" />
              <span className="text-xs font-mono font-semibold text-zinc-200">
                Research Package (ZIP)
              </span>
              <StatusIcon status={pkgStatus} />
            </div>

            <p className="text-[11px] font-mono text-zinc-400 leading-relaxed">
              Timestamped ZIP with executive summary, walk-forward reports, trade
              history, calibration data, configuration snapshot, and metadata.
              Organised into labelled folders for easy reference.
            </p>

            <IncludesList items={PACKAGE_CONTENTS} />

            {pkgStatus === "done" && pkgResult && (
              <div className="text-[10px] font-mono text-emerald-400 space-y-0.5">
                <div>✓ {pkgResult.filename}</div>
                <div>✓ {pkgResult.size_kb} KB · {pkgResult.generated_at}</div>
                {pkgResult.git_commit && pkgResult.git_commit !== "unavailable" && (
                  <div>✓ commit {pkgResult.git_commit}</div>
                )}
                {!pkgResult.validation_available && (
                  <div className="text-amber-400 mt-1">
                    ⚠ No validation result — run a walk-forward first for full data
                  </div>
                )}
              </div>
            )}

            {pkgStatus === "error" && pkgError && (
              <div className="text-[10px] font-mono text-red-400 bg-red-500/10 border border-red-500/30 rounded px-2 py-1.5">
                {pkgError}
              </div>
            )}

            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                className="font-mono text-xs bg-sky-600 hover:bg-sky-500 text-white"
                onClick={handleGeneratePackage}
                disabled={pkgStatus === "generating"}
                data-testid="button-generate-research-package"
              >
                {pkgStatus === "generating"
                  ? <><Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" /> Generating…</>
                  : <><Package className="h-3.5 w-3.5 mr-1.5" /> Generate & Download</>
                }
              </Button>
              {pkgStatus === "done" && (
                <Button
                  size="sm"
                  variant="outline"
                  className="font-mono text-xs"
                  onClick={handleRedownloadPackage}
                >
                  <Download className="h-3.5 w-3.5 mr-1.5" /> Re-download
                </Button>
              )}
            </div>
          </div>

          {/* ── ChatGPT Report (Markdown) ──────────────────────────────── */}
          <div className={cn(
            "rounded-md border p-4 space-y-3 transition-colors",
            rptStatus === "done" ? "border-emerald-500/30 bg-emerald-500/5"
              : rptStatus === "error" ? "border-red-500/30 bg-red-500/5"
              : "border-zinc-700 bg-zinc-800/30",
          )}>
            <div className="flex items-center gap-2">
              <FileText className="h-4 w-4 text-violet-400 flex-shrink-0" />
              <span className="text-xs font-mono font-semibold text-zinc-200">
                ChatGPT Report (.md)
              </span>
              <StatusIcon status={rptStatus} />
            </div>

            <p className="text-[11px] font-mono text-zinc-400 leading-relaxed">
              Single markdown file with full system context, all key tables, before/after
              comparison, known limitations, and suggested questions — ready to upload
              directly to ChatGPT.
            </p>

            <IncludesList items={CHATGPT_CONTENTS} />

            {rptStatus === "done" && rptResult && (
              <div className="text-[10px] font-mono text-emerald-400 space-y-0.5">
                <div>✓ chatgpt_report.md · {rptResult.size_kb} KB</div>
                <div>✓ {rptResult.generated_at}</div>
                {!rptResult.validation_available && (
                  <div className="text-amber-400 mt-1">
                    ⚠ No validation result — metrics sections will be limited
                  </div>
                )}
              </div>
            )}

            {rptStatus === "error" && rptError && (
              <div className="text-[10px] font-mono text-red-400 bg-red-500/10 border border-red-500/30 rounded px-2 py-1.5">
                {rptError}
              </div>
            )}

            <div className="flex flex-wrap gap-2">
              <Button
                size="sm"
                className="font-mono text-xs bg-violet-600 hover:bg-violet-500 text-white"
                onClick={handleGenerateChatGPT}
                disabled={rptStatus === "generating"}
                data-testid="button-generate-chatgpt-report"
              >
                {rptStatus === "generating"
                  ? <><Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" /> Generating…</>
                  : <><FileText className="h-3.5 w-3.5 mr-1.5" /> Generate & Download</>
                }
              </Button>
              {rptStatus === "done" && (
                <Button
                  size="sm"
                  variant="outline"
                  className="font-mono text-xs"
                  onClick={handleRedownloadChatGPT}
                >
                  <Download className="h-3.5 w-3.5 mr-1.5" /> Re-download
                </Button>
              )}
            </div>
          </div>
        </div>

        {/* ── Safety note ──────────────────────────────────────────────── */}
        <p className="mt-4 text-[10px] font-mono text-muted-foreground border-t border-zinc-800 pt-3">
          Read-only export — no live trading state, portfolio positions, or model weights
          are changed by generating these reports.
          Historical performance does not guarantee future results.
        </p>
      </CardContent>
    </Card>
  );
}
