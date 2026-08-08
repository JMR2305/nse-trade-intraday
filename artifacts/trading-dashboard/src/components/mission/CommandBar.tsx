/**
 * CommandBar.tsx — Phase 25C Mission Control operator command bar.
 *
 * Every action calls an EXISTING control endpoint (or is pure navigation) —
 * no new backend logic:
 *   Start Scan       → POST /live-data/scan/run       (fire-and-forget; scanner polls)
 *   Pause AI         → POST /risk/kill-switch/trigger (CONFIRM — halts paper trading)
 *   Resume AI        → POST /risk/kill-switch/resume  {acknowledge:true}
 *   Emergency Stop   → POST /live-data/scan/abort + /risk/kill-switch/trigger (CONFIRM)
 *   Replay Today     → navigate /replay
 *   Run Backtest     → scroll to the Backtest widget on this page
 *   Generate Report  → POST /phase17/reports, then link to Executive Reports
 *   Open Investigation → navigate /investigation-center
 *   Open Learning Center → navigate /ai-learning-center
 *
 * Destructive / impactful actions (Emergency Stop, Pause AI) require an
 * explicit confirmation dialog. Success/failure feedback is shown inline.
 * PAPER TRADING / RESEARCH ONLY.
 */
import { useCallback, useState } from "react";
import { useLocation } from "wouter";
import { useQueryClient } from "@tanstack/react-query";
import { apiJson } from "@/lib/api";
import {
  Play, PauseCircle, PlayCircle, OctagonX, Film, FlaskConical,
  FileBarChart2, Microscope, GraduationCap, Loader2, CheckCircle2, XCircle,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

type Tone = "default" | "danger" | "warn";

interface ActionDef {
  id: string;
  label: string;
  icon: LucideIcon;
  tone: Tone;
  /** Confirmation copy — presence means the action needs explicit confirm */
  confirm?: { title: string; body: string; confirmLabel: string };
  run: () => Promise<string> | string; // resolves to a success message
}

interface Feedback { kind: "ok" | "err" | "busy"; actionId: string; message: string }

export function CommandBar() {
  const [, navigate] = useLocation();
  const queryClient = useQueryClient();
  const [pendingConfirm, setPendingConfirm] = useState<ActionDef | null>(null);
  const [feedback, setFeedback] = useState<Feedback | null>(null);

  const invalidateControls = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["mc", "scan-status"] });
    void queryClient.invalidateQueries({ queryKey: ["mc", "pipeline-summary"] });
    void queryClient.invalidateQueries({ queryKey: ["mc", "ledger"] });
  }, [queryClient]);

  const scrollToBacktest = useCallback(() => {
    const el = document.querySelector('[data-testid="mc-backtest"]');
    if (el) { el.scrollIntoView({ behavior: "smooth", block: "center" }); return "Backtest launcher in view — configure and run below."; }
    return "Backtest widget not found on this page.";
  }, []);

  const actions: ActionDef[] = [
    {
      id: "start-scan", label: "Start Scan", icon: Play, tone: "default",
      run: async () => {
        const r = await apiJson<{ started?: boolean; status?: string; error?: string }>(
          "/live-data/scan/run", { method: "POST" }, 20_000);
        if (r?.started === false || r?.error) throw new Error(r?.error ?? "Scan did not start");
        invalidateControls();
        return "Scan started — Live Scanner panel tracks progress.";
      },
    },
    {
      id: "pause-ai", label: "Pause AI", icon: PauseCircle, tone: "warn",
      confirm: {
        title: "Pause AI trading?",
        body: "This triggers the risk kill switch: all paper trading halts until you explicitly resume. Scans keep running but no orders will be placed.",
        confirmLabel: "Pause AI",
      },
      run: async () => {
        await apiJson("/risk/kill-switch/trigger", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ reason: "Paused from Mission Control command bar" }),
        }, 20_000);
        invalidateControls();
        return "AI paused — kill switch active. Use Resume AI to re-enable.";
      },
    },
    {
      id: "resume-ai", label: "Resume AI", icon: PlayCircle, tone: "default",
      run: async () => {
        await apiJson("/risk/kill-switch/resume", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ acknowledge: true }),
        }, 20_000);
        invalidateControls();
        return "AI resumed — kill switch released.";
      },
    },
    {
      id: "emergency-stop", label: "Emergency Stop", icon: OctagonX, tone: "danger",
      confirm: {
        title: "EMERGENCY STOP?",
        body: "Aborts any in-flight scan AND triggers the risk kill switch, halting all paper trading immediately. Resume requires explicit acknowledgement.",
        confirmLabel: "STOP EVERYTHING",
      },
      run: async () => {
        const results = await Promise.allSettled([
          apiJson("/live-data/scan/abort", { method: "POST" }, 15_000),
          apiJson("/risk/kill-switch/trigger", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ reason: "EMERGENCY STOP from Mission Control" }),
          }, 20_000),
        ]);
        const failed = results.filter((r) => r.status === "rejected");
        invalidateControls();
        if (failed.length === results.length) throw new Error("Emergency stop failed — both control calls errored.");
        if (failed.length > 0) return "Partial stop: one control call failed — verify kill-switch status on the Risk page.";
        return "Emergency stop complete — scan aborted, kill switch active.";
      },
    },
    { id: "replay-today", label: "Replay Today", icon: Film, tone: "default",
      run: () => { navigate("/replay"); return "Opening Replay Mode…"; } },
    { id: "run-backtest", label: "Run Backtest", icon: FlaskConical, tone: "default",
      run: scrollToBacktest },
    {
      id: "generate-report", label: "Generate Report", icon: FileBarChart2, tone: "default",
      run: async () => {
        await apiJson("/phase17/reports", { method: "POST" }, 130_000);
        return "Session report generated — view it under Executive Reports.";
      },
    },
    { id: "open-investigation", label: "Investigation", icon: Microscope, tone: "default",
      run: () => { navigate("/investigation-center"); return "Opening Investigation Center…"; } },
    { id: "open-learning", label: "Learning Center", icon: GraduationCap, tone: "default",
      run: () => { navigate("/ai-learning-center"); return "Opening AI Learning Center…"; } },
  ];

  const execute = useCallback(async (a: ActionDef) => {
    setFeedback({ kind: "busy", actionId: a.id, message: `${a.label}…` });
    try {
      const msg = await a.run();
      setFeedback({ kind: "ok", actionId: a.id, message: msg });
    } catch (e) {
      setFeedback({ kind: "err", actionId: a.id, message: e instanceof Error ? e.message : String(e) });
    }
  }, []);

  const onClick = (a: ActionDef) => {
    if (a.confirm) { setPendingConfirm(a); return; }
    void execute(a);
  };

  const toneClass = (t: Tone) =>
    t === "danger"
      ? "border-red-500/40 text-red-300 hover:bg-red-500/10"
      : t === "warn"
        ? "border-amber-500/40 text-amber-300 hover:bg-amber-500/10"
        : "border-border text-muted-foreground hover:text-foreground hover:bg-muted/40";

  const busy = feedback?.kind === "busy";

  return (
    <div className="bg-card border border-border rounded-xl px-3 py-2" data-testid="mc-command-bar">
      <div className="flex flex-wrap items-center gap-1.5">
        <span className="text-[9px] font-semibold uppercase tracking-wider text-muted-foreground/50 mr-1">Commands</span>
        {actions.map((a) => {
          const Icon = a.icon;
          const isBusy = busy && feedback?.actionId === a.id;
          return (
            <button
              key={a.id}
              data-testid={`mc-cmd-${a.id}`}
              disabled={busy}
              onClick={() => onClick(a)}
              className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-[11px] font-medium transition-colors disabled:opacity-50 ${toneClass(a.tone)}`}
            >
              {isBusy ? <Loader2 className="w-3 h-3 animate-spin" /> : <Icon className="w-3 h-3" />}
              {a.label}
            </button>
          );
        })}
      </div>

      {/* Inline feedback */}
      {feedback && feedback.kind !== "busy" && (
        <div
          data-testid="mc-cmd-feedback"
          className={`mt-1.5 flex items-center gap-1.5 text-[11px] ${feedback.kind === "ok" ? "text-emerald-400" : "text-red-400"}`}
        >
          {feedback.kind === "ok" ? <CheckCircle2 className="w-3 h-3 shrink-0" /> : <XCircle className="w-3 h-3 shrink-0" />}
          <span className="min-w-0 break-words">{feedback.message}</span>
          <button className="ml-auto text-muted-foreground/50 hover:text-muted-foreground text-[10px]" onClick={() => setFeedback(null)}>
            dismiss
          </button>
        </div>
      )}

      {/* Confirmation dialog for impactful actions */}
      {pendingConfirm && (
        <div className="fixed inset-0 z-[300] flex items-center justify-center" data-testid="mc-cmd-confirm">
          <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={() => setPendingConfirm(null)} />
          <div className="relative w-full max-w-sm mx-4 bg-card border border-border rounded-2xl p-4 shadow-2xl">
            <p className={`text-sm font-semibold mb-1.5 ${pendingConfirm.tone === "danger" ? "text-red-400" : "text-amber-300"}`}>
              {pendingConfirm.confirm!.title}
            </p>
            <p className="text-xs text-muted-foreground mb-4">{pendingConfirm.confirm!.body}</p>
            <div className="flex justify-end gap-2">
              <button
                data-testid="mc-cmd-cancel"
                onClick={() => setPendingConfirm(null)}
                className="rounded-lg border border-border px-3 py-1.5 text-xs text-muted-foreground hover:text-foreground"
              >
                Cancel
              </button>
              <button
                data-testid="mc-cmd-confirm-btn"
                onClick={() => { const a = pendingConfirm; setPendingConfirm(null); void execute(a); }}
                className={`rounded-lg px-3 py-1.5 text-xs font-semibold ${
                  pendingConfirm.tone === "danger"
                    ? "bg-red-600 text-white hover:bg-red-500"
                    : "bg-amber-600 text-white hover:bg-amber-500"
                }`}
              >
                {pendingConfirm.confirm!.confirmLabel}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
