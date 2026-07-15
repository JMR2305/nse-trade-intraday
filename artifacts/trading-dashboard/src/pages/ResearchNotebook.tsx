/**
 * ResearchNotebook.tsx — Phase 18: Research Notebook, Daily Validation
 * Workflow & Evidence Accumulation.
 *
 * Permanent daily research journal: one entry per IST trading date, created
 * automatically after the first successful scan, updated intraday, finalized
 * after market close. Includes decision journal, daily checklist, notes,
 * search, weekly/monthly reviews, evidence tracker, issue log and exports.
 *
 * PAPER TRADING / RESEARCH ONLY. Notes never alter trading logic. All values
 * derive from stored platform data — missing data shows "Insufficient Data".
 */
import { useState, useEffect, useCallback } from "react";
import { Link } from "wouter";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Loader2, RefreshCw, Download, NotebookPen, CheckCircle2, XCircle,
  AlertTriangle, Search, Bug, TrendingUp, CalendarDays, Lock, Unlock,
  ClipboardCheck, LineChart,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { API_BASE } from "@/lib/api";
import { useToast } from "@/hooks/use-toast";

/* eslint-disable @typescript-eslint/no-explicit-any */

async function safeJson(path: string, init?: RequestInit): Promise<any> {
  const resp = await fetch(`${API_BASE}${path}`, init);
  const text = await resp.text();
  if (!text.trim()) throw new Error(`Empty response from ${path} (HTTP ${resp.status})`);
  let data: any;
  try { data = JSON.parse(text); } catch { throw new Error(`Invalid JSON from ${path}`); }
  if (!resp.ok) throw new Error(String(data?.error ?? `HTTP ${resp.status}`));
  return data;
}

const post = (path: string, body: any) =>
  safeJson(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

function StatusBadge({ status }: { status: string }) {
  const cls =
    status === "PASS" ? "text-emerald-400 border-emerald-700" :
    status === "FAIL" ? "text-red-400 border-red-700" :
    status === "WARNING" || status === "WARN" ? "text-amber-400 border-amber-700" :
    "text-zinc-400 border-zinc-700";
  const Icon = status === "PASS" ? CheckCircle2 : status === "FAIL" ? XCircle : AlertTriangle;
  return (
    <Badge variant="outline" className={cn("gap-1 font-mono text-[10px]", cls)}>
      <Icon className="h-3 w-3" /> {status}
    </Badge>
  );
}

function Stat({ label, value, cls }: { label: string; value: any; cls?: string }) {
  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/50 p-2">
      <div className="text-[10px] uppercase tracking-wide text-zinc-500">{label}</div>
      <div className={cn("text-sm font-mono break-words", cls ?? "text-zinc-200")}>
        {value === null || value === undefined ? "Not Available" : String(value)}
      </div>
    </div>
  );
}

const TABS = ["Today", "History", "Reviews", "Evidence", "Issues", "Search"] as const;
type Tab = typeof TABS[number];

const DECISION_BADGE: Record<string, string> = {
  "PAPER TRADE TAKEN": "text-emerald-400 border-emerald-700",
  "POSITION EXITED": "text-sky-400 border-sky-700",
  "SKIPPED": "text-amber-400 border-amber-700",
  "WATCHED": "text-zinc-300 border-zinc-600",
  "REJECTED BY RISK": "text-red-400 border-red-700",
  "REJECTED BY DATA QUALITY": "text-red-300 border-red-800",
  "NO ACTION": "text-zinc-500 border-zinc-700",
};

export default function ResearchNotebook() {
  const { toast } = useToast();
  const [tab, setTab] = useState<Tab>("Today");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [entry, setEntry] = useState<any>(null);
  const [entryDate, setEntryDate] = useState<string | null>(null);
  const [noEntryReason, setNoEntryReason] = useState<string | null>(null);
  const [entries, setEntries] = useState<any[]>([]);
  const [weekly, setWeekly] = useState<any>(null);
  const [monthly, setMonthly] = useState<any>(null);
  const [daily, setDaily] = useState<any>(null);
  const [evidence, setEvidence] = useState<any>(null);
  const [issues, setIssues] = useState<any>(null);
  const [noteText, setNoteText] = useState("");
  const [noteTags, setNoteTags] = useState("");
  const [lessons, setLessons] = useState("");
  const [searchQ, setSearchQ] = useState("");
  const [searchState, setSearchState] = useState("");
  const [searchSymbol, setSearchSymbol] = useState("");
  const [searchResults, setSearchResults] = useState<any>(null);
  const [issueDesc, setIssueDesc] = useState("");
  const [issueSev, setIssueSev] = useState("MEDIUM");

  const loadEntry = useCallback(async (date?: string) => {
    setLoading(true);
    setError(null);
    try {
      const r = date
        ? await safeJson(`/phase18/entry?date=${date}`)
        : await post("/phase18/ensure", {});
      const e = r.entry ?? null;
      setEntry(e);
      setEntryDate(e?.trading_date ?? date ?? null);
      setNoEntryReason(e ? null : (r.reason ?? "No entry available."));
      setLessons(e?.lessons_learned ?? "");
      const list = await safeJson("/phase18/entries");
      setEntries(list.entries ?? []);
    } catch (err: any) {
      setError(err?.message ?? "Failed to load notebook");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void loadEntry(); }, [loadEntry]);

  const loadReviews = useCallback(async () => {
    try {
      const [d, w, m] = await Promise.all([
        safeJson("/phase18/review/daily"),
        safeJson("/phase18/review/weekly"),
        safeJson("/phase18/review/monthly"),
      ]);
      setDaily(d); setWeekly(w); setMonthly(m);
    } catch (err: any) {
      toast({ title: "Failed to load reviews", description: err?.message, variant: "destructive" });
    }
  }, [toast]);

  const loadEvidence = useCallback(async () => {
    try { setEvidence(await safeJson("/phase18/evidence")); }
    catch (err: any) { toast({ title: "Failed to load evidence", description: err?.message, variant: "destructive" }); }
  }, [toast]);

  const loadIssues = useCallback(async () => {
    try { setIssues(await safeJson("/phase18/issues")); }
    catch (err: any) { toast({ title: "Failed to load issues", description: err?.message, variant: "destructive" }); }
  }, [toast]);

  useEffect(() => {
    if (tab === "Reviews" && !weekly) void loadReviews();
    if (tab === "Evidence" && !evidence) void loadEvidence();
    if (tab === "Issues" && !issues) void loadIssues();
  }, [tab, weekly, evidence, issues, loadReviews, loadEvidence, loadIssues]);

  const addNote = async () => {
    if (!noteText.trim() || !entryDate) return;
    setBusy(true);
    try {
      await post("/phase18/notes", {
        date_iso: entryDate, note_text: noteText,
        note_tags: noteTags.split(",").map((t) => t.trim()).filter(Boolean),
      });
      setNoteText(""); setNoteTags("");
      await loadEntry(entryDate);
      toast({ title: "Note saved" });
    } catch (err: any) {
      toast({ title: "Failed to save note", description: err?.message, variant: "destructive" });
    } finally { setBusy(false); }
  };

  const saveLessons = async () => {
    if (!entryDate) return;
    setBusy(true);
    try {
      await post("/phase18/notes", { date_iso: entryDate, lessons });
      toast({ title: "Lessons saved" });
    } catch (err: any) {
      toast({ title: "Failed to save", description: err?.message, variant: "destructive" });
    } finally { setBusy(false); }
  };

  const finalize = async () => {
    if (!entryDate) return;
    setBusy(true);
    try {
      await post("/phase18/finalize", { date: entryDate });
      await loadEntry(entryDate);
      toast({ title: "Day finalized", description: "End-of-day reconciliation stored." });
    } catch (err: any) {
      toast({ title: "Finalize failed", description: err?.message, variant: "destructive" });
    } finally { setBusy(false); }
  };

  const reopen = async () => {
    if (!entryDate) return;
    setBusy(true);
    try {
      await post("/phase18/reopen", { date: entryDate });
      await loadEntry(entryDate);
      toast({ title: "Day reopened for editing" });
    } catch (err: any) {
      toast({ title: "Reopen failed", description: err?.message, variant: "destructive" });
    } finally { setBusy(false); }
  };

  const markDecision = async (symbol: string, action: string) => {
    if (!entryDate) return;
    const reason = window.prompt(`Reason for "${action}" on ${symbol} (optional):`) ?? "";
    setBusy(true);
    try {
      await post("/phase18/decision", { date_iso: entryDate, symbol, user_action: action, reason });
      await loadEntry(entryDate);
    } catch (err: any) {
      toast({ title: "Failed to record decision", description: err?.message, variant: "destructive" });
    } finally { setBusy(false); }
  };

  const runSearch = async () => {
    setBusy(true);
    try {
      setSearchResults(await post("/phase18/search", {
        query: searchQ, decision_state: searchState, symbol: searchSymbol,
      }));
    } catch (err: any) {
      toast({ title: "Search failed", description: err?.message, variant: "destructive" });
    } finally { setBusy(false); }
  };

  const addIssue = async () => {
    if (!issueDesc.trim()) return;
    setBusy(true);
    try {
      await post("/phase18/issues", {
        description: issueDesc, severity: issueSev,
        scan_id: entry?.scan?.scan_id ?? "",
      });
      setIssueDesc("");
      await loadIssues();
      toast({ title: "Issue recorded" });
    } catch (err: any) {
      toast({ title: "Failed to add issue", description: err?.message, variant: "destructive" });
    } finally { setBusy(false); }
  };

  const setIssueStatus = async (issue_id: string, status: string) => {
    setBusy(true);
    try {
      await safeJson("/phase18/issues", {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ issue_id, status }),
      });
      await loadIssues();
    } catch (err: any) {
      toast({ title: "Failed to update issue", description: err?.message, variant: "destructive" });
    } finally { setBusy(false); }
  };

  const generateExports = async () => {
    setBusy(true);
    try {
      const r = await post("/phase18/exports", { scope: "all" });
      toast({
        title: "Exports generated",
        description: `Archive: ${r.archive?.zip_name} (${r.archive?.daily_entries} entries)`,
      });
    } catch (err: any) {
      toast({ title: "Export failed", description: err?.message, variant: "destructive" });
    } finally { setBusy(false); }
  };

  const finalized = entry?.state === "FINALIZED";

  return (
    <div className="p-6 space-y-4 max-w-[1200px] mx-auto">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold flex items-center gap-2">
            <NotebookPen className="h-6 w-6 text-primary" /> Research Notebook
          </h1>
          <p className="text-xs text-zinc-500 uppercase tracking-wide">
            Daily research journal &amp; evidence accumulation — Paper / Research only
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => void loadEntry(entryDate ?? undefined)} disabled={loading || busy}>
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />} Refresh
          </Button>
          <Button variant="outline" size="sm" onClick={generateExports} disabled={busy}>
            <Download className="h-4 w-4 mr-1" /> Generate Exports
          </Button>
          <a href={`${API_BASE}/phase18/exports/Research_Notebook_Archive.zip`}>
            <Button size="sm" variant="secondary"><Download className="h-4 w-4 mr-1" /> Archive ZIP</Button>
          </a>
        </div>
      </div>

      <div className="flex gap-1 border-b border-zinc-800">
        {TABS.map((t) => (
          <button key={t}
            className={cn("px-3 py-2 text-sm font-medium border-b-2 -mb-px",
              tab === t ? "border-primary text-primary" : "border-transparent text-zinc-400 hover:text-zinc-200")}
            onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </div>

      {error && (
        <Card className="border-red-800"><CardContent className="p-3 text-sm text-red-400">{error}</CardContent></Card>
      )}

      {/* ── TODAY / ENTRY ─────────────────────────────────────────────── */}
      {tab === "Today" && (
        <>
          {!entry && !loading && (
            <Card><CardContent className="p-4 text-sm text-zinc-400">
              {noEntryReason ?? "No entry."} A draft entry is created automatically after the first successful scan of the trading day.
            </CardContent></Card>
          )}
          {entry && (
            <div className="space-y-4">
              <Card>
                <CardHeader className="pb-2 flex-row items-center justify-between space-y-0">
                  <CardTitle className="text-base flex items-center gap-2">
                    <CalendarDays className="h-4 w-4" /> {entry.trading_date}
                    <Badge variant="outline" className={cn("font-mono text-[10px]",
                      finalized ? "text-emerald-400 border-emerald-700" : "text-amber-400 border-amber-700")}>
                      {entry.state}
                    </Badge>
                    {entry.scan?.historical_source && (
                      <Badge variant="outline" className="text-amber-400 border-amber-700 text-[10px]">
                        Historical source — not current scan
                      </Badge>
                    )}
                  </CardTitle>
                  {finalized ? (
                    <Button size="sm" variant="outline" onClick={reopen} disabled={busy}>
                      <Unlock className="h-4 w-4 mr-1" /> Reopen
                    </Button>
                  ) : (
                    <Button size="sm" onClick={finalize} disabled={busy}>
                      <Lock className="h-4 w-4 mr-1" /> Finalize Day
                    </Button>
                  )}
                </CardHeader>
                <CardContent className="grid grid-cols-2 md:grid-cols-4 gap-2">
                  <Stat label="Market Regime" value={entry.market?.market_regime} />
                  <Stat label="Market Status" value={entry.market_status?.state} />
                  <Stat label="NIFTY Trend" value={`${entry.market?.nifty_trend ?? "?"} (${entry.market?.nifty_change_pct ?? "?"}%)`} />
                  <Stat label="BANKNIFTY Trend" value={`${entry.market?.banknifty_trend ?? "?"} (${entry.market?.banknifty_change_pct ?? "?"}%)`} />
                  <Stat label="India VIX" value={`${entry.market?.india_vix ?? "?"} (${entry.market?.vix_category ?? "?"})`} />
                  <Stat label="Breadth" value={entry.market?.breadth_label} />
                  <Stat label="Strongest Sectors" value={(entry.market?.strongest_sectors ?? []).join(", ")} />
                  <Stat label="Weakest Sectors" value={(entry.market?.weakest_sectors ?? []).join(", ")} />
                  <Stat label="Scan ID" value={entry.scan?.scan_id} />
                  <Stat label="Snapshot" value={entry.scan?.snapshot_ts} />
                  <Stat label="Data Provider" value={entry.integrity?.data_provider} />
                  <Stat label="Data Quality" value={`${entry.data_quality?.status ?? "?"} · ${entry.data_quality?.symbol_errors ?? "?"} error(s)`} />
                </CardContent>
              </Card>

              {entry.eod && (
                <Card>
                  <CardHeader className="pb-2"><CardTitle className="text-base flex items-center gap-2">
                    <LineChart className="h-4 w-4" /> End of Day</CardTitle></CardHeader>
                  <CardContent className="space-y-2">
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                      <Stat label="Portfolio Value" value={entry.eod.portfolio_value} />
                      <Stat label="Daily P&L" value={entry.eod.daily_pnl}
                        cls={Number(entry.eod.daily_pnl) >= 0 ? "text-emerald-400" : "text-red-400"} />
                      <Stat label="Opened / Closed" value={`${entry.eod.trades_opened} / ${entry.eod.trades_closed}`} />
                      <Stat label="Stops / Targets Hit" value={`${entry.eod.stops_hit} / ${entry.eod.targets_hit}`} />
                    </div>
                    <p className="text-xs text-zinc-400">{entry.eod.final_summary}</p>
                  </CardContent>
                </Card>
              )}

              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-base flex items-center gap-2">
                  <ClipboardCheck className="h-4 w-4" /> Daily Validation Checklist</CardTitle></CardHeader>
                <CardContent className="grid md:grid-cols-3 gap-3">
                  {(["before_market", "during_market", "after_market"] as const).map((sec) => (
                    <div key={sec}>
                      <div className="text-xs font-semibold uppercase text-zinc-500 mb-1">
                        {sec.replace("_", " ")}
                      </div>
                      <div className="space-y-1">
                        {(entry.checklist?.[sec] ?? []).map((i: any) => (
                          <div key={i.item} className="flex items-center justify-between gap-2 text-xs border border-zinc-800 rounded p-1.5">
                            <span className="text-zinc-300" title={i.detail}>{i.item}</span>
                            <StatusBadge status={i.status} />
                          </div>
                        ))}
                      </div>
                    </div>
                  ))}
                </CardContent>
              </Card>

              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-base">
                  Trade Decision Journal ({entry.decisions?.length ?? 0})</CardTitle></CardHeader>
                <CardContent className="overflow-x-auto">
                  <table className="w-full text-xs">
                    <thead><tr className="text-zinc-500 text-left">
                      <th className="p-1">Symbol</th><th className="p-1">Signal</th>
                      <th className="p-1">State</th><th className="p-1">Conf</th>
                      <th className="p-1">Strategy</th><th className="p-1">Blocking</th>
                      <th className="p-1">User</th><th className="p-1">Outcome</th><th className="p-1"></th>
                    </tr></thead>
                    <tbody>
                      {(entry.decisions ?? []).map((r: any) => (
                        <tr key={r.symbol} className="border-t border-zinc-800/60">
                          <td className="p-1 font-mono">
                            <Link href="/trade-replay" className="hover:text-primary underline decoration-dotted">
                              {r.symbol}
                            </Link>
                          </td>
                          <td className="p-1">{r.raw_signal}</td>
                          <td className="p-1">
                            <Badge variant="outline" className={cn("text-[9px] font-mono",
                              DECISION_BADGE[r.decision_state] ?? "text-zinc-400 border-zinc-700")}>
                              {r.decision_state}
                            </Badge>
                          </td>
                          <td className="p-1 font-mono">{r.confidence ?? "-"}</td>
                          <td className="p-1">{r.strategy ?? "-"}</td>
                          <td className="p-1 text-amber-400">{r.blocking_rule ?? "-"}</td>
                          <td className="p-1" title={r.user_reason ?? ""}>{r.user_action ?? "-"}</td>
                          <td className={cn("p-1 font-mono",
                            r.outcome ? (Number(r.outcome.pnl) >= 0 ? "text-emerald-400" : "text-red-400") : "")}>
                            {r.outcome ? `₹${r.outcome.pnl} (${r.outcome.exit_type})` : "-"}
                          </td>
                          <td className="p-1">
                            {!finalized && (
                              <div className="flex gap-1">
                                <button className="text-[9px] text-emerald-500 hover:underline"
                                  onClick={() => void markDecision(r.symbol, "PAPER TRADE TAKEN")}>taken</button>
                                <button className="text-[9px] text-amber-500 hover:underline"
                                  onClick={() => void markDecision(r.symbol, "SKIPPED")}>skip</button>
                              </div>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </CardContent>
              </Card>

              <div className="grid md:grid-cols-2 gap-4">
                <Card>
                  <CardHeader className="pb-2"><CardTitle className="text-base">Notes ({entry.user_notes?.length ?? 0})</CardTitle></CardHeader>
                  <CardContent className="space-y-2">
                    <div className="max-h-52 overflow-y-auto space-y-1">
                      {(entry.user_notes ?? []).map((n: any) => (
                        <div key={n.id} className="text-xs border border-zinc-800 rounded p-2">
                          <span className="text-zinc-500">[{n.category}]</span> {n.text}
                          {(n.tags ?? []).length > 0 && (
                            <span className="ml-2 text-sky-400">{(n.tags ?? []).map((t: string) => `#${t}`).join(" ")}</span>
                          )}
                        </div>
                      ))}
                      {!entry.user_notes?.length && <p className="text-xs text-zinc-500">No notes yet.</p>}
                    </div>
                    <Textarea placeholder="Market observation, reason for taking/skipping, execution issue, idea to test…"
                      value={noteText} onChange={(e) => setNoteText(e.target.value)} rows={2} />
                    <div className="flex gap-2">
                      <Input placeholder="tags, comma separated" value={noteTags}
                        onChange={(e) => setNoteTags(e.target.value)} className="text-xs" />
                      <Button size="sm" onClick={addNote} disabled={busy || !noteText.trim()}>Add Note</Button>
                    </div>
                  </CardContent>
                </Card>
                <Card>
                  <CardHeader className="pb-2"><CardTitle className="text-base">Lessons Learned</CardTitle></CardHeader>
                  <CardContent className="space-y-2">
                    <Textarea placeholder="What was learned today…" value={lessons}
                      onChange={(e) => setLessons(e.target.value)} rows={6} />
                    <Button size="sm" onClick={saveLessons} disabled={busy}>Save Lessons</Button>
                    <p className="text-[10px] text-zinc-500">
                      Notes and lessons are journal records only — they never alter trading logic.
                    </p>
                  </CardContent>
                </Card>
              </div>
            </div>
          )}
        </>
      )}

      {/* ── HISTORY ───────────────────────────────────────────────────── */}
      {tab === "History" && (
        <Card>
          <CardHeader className="pb-2"><CardTitle className="text-base">Notebook History ({entries.length})</CardTitle></CardHeader>
          <CardContent className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead><tr className="text-zinc-500 text-left">
                <th className="p-1">Date</th><th className="p-1">State</th><th className="p-1">Regime</th>
                <th className="p-1">Scan</th><th className="p-1">Opened</th><th className="p-1">Closed</th>
                <th className="p-1">Notes</th><th className="p-1">Daily P&L</th><th className="p-1"></th>
              </tr></thead>
              <tbody>
                {entries.map((e) => (
                  <tr key={e.trading_date} className="border-t border-zinc-800/60">
                    <td className="p-1 font-mono">{e.trading_date}</td>
                    <td className="p-1"><StatusBadge status={e.state === "FINALIZED" ? "PASS" : "WARNING"} /></td>
                    <td className="p-1">{e.market_regime}</td>
                    <td className="p-1 font-mono">{e.scan_id}</td>
                    <td className="p-1">{e.trades_opened}</td>
                    <td className="p-1">{e.trades_closed}</td>
                    <td className="p-1">{e.notes}</td>
                    <td className="p-1 font-mono">{e.daily_pnl ?? "-"}</td>
                    <td className="p-1">
                      <button className="text-[10px] text-primary hover:underline"
                        onClick={() => { setTab("Today"); void loadEntry(e.trading_date); }}>
                        open
                      </button>
                    </td>
                  </tr>
                ))}
                {!entries.length && <tr><td className="p-2 text-zinc-500" colSpan={9}>No entries yet.</td></tr>}
              </tbody>
            </table>
          </CardContent>
        </Card>
      )}

      {/* ── REVIEWS ───────────────────────────────────────────────────── */}
      {tab === "Reviews" && (
        <div className="space-y-4">
          {!weekly && <Loader2 className="h-5 w-5 animate-spin text-zinc-500" />}
          {daily?.available && (
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-base">Daily Review — {daily.date}</CardTitle></CardHeader>
              <CardContent className="grid grid-cols-2 md:grid-cols-4 gap-2">
                <Stat label="Recommended" value={(daily.ai_recommended ?? []).join(", ") || "None"} />
                <Stat label="Taken" value={(daily.paper_trades_taken ?? []).join(", ") || "None"} />
                <Stat label="Skipped" value={(daily.skipped ?? []).join(", ") || "None"} />
                <Stat label="Confidence Alignment" value={daily.confidence_alignment} />
                <Stat label="What Worked" value={(daily.what_worked ?? []).join(", ") || "None"} />
                <Stat label="What Failed" value={(daily.what_failed ?? []).join(", ") || "None"} />
                <Stat label="Issues" value={(daily.risk_or_data_issues ?? []).join("; ")} />
                <Stat label="Watch Next Session" value={(daily.watch_next_session ?? []).join(", ")} />
              </CardContent>
            </Card>
          )}
          {weekly && (
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-base">
                Weekly Review — {weekly.week_start} → {weekly.week_end}</CardTitle></CardHeader>
              <CardContent className="space-y-3">
                <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                  <Stat label="Trading Days" value={weekly.trading_days_completed} />
                  <Stat label="Completed Trades" value={weekly.completed_paper_trades} />
                  <Stat label="Weekly P&L" value={weekly.weekly_pnl} />
                  <Stat label="Win Rate" value={weekly.win_rate} />
                  <Stat label="Profit Factor" value={weekly.profit_factor} />
                  <Stat label="Expectancy" value={weekly.expectancy} />
                  <Stat label="Max Drawdown" value={weekly.max_drawdown} />
                  <Stat label="QA Failures" value={weekly.qa_failures} />
                  <Stat label="Best Strategy" value={weekly.best_strategy} />
                  <Stat label="Worst Strategy" value={weekly.worst_strategy} />
                  <Stat label="Best Regime" value={weekly.best_regime} />
                  <Stat label="Data Quality Incidents" value={weekly.data_quality_incidents} />
                </div>
                <div className="text-xs text-zinc-400">
                  <div className="font-semibold text-zinc-300 mb-1">Research questions for next week</div>
                  <ul className="list-disc pl-4 space-y-0.5">
                    {(weekly.research_questions_next_week ?? []).map((q: string) => <li key={q}>{q}</li>)}
                  </ul>
                </div>
              </CardContent>
            </Card>
          )}
          {monthly && (
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-base">Monthly Review — {monthly.month}</CardTitle></CardHeader>
              <CardContent className="grid grid-cols-2 md:grid-cols-4 gap-2">
                <Stat label="Portfolio Value" value={monthly.portfolio_value} />
                <Stat label="Growth %" value={monthly.portfolio_growth_pct} />
                <Stat label="Trades Completed" value={monthly.paper_trades_completed} />
                <Stat label="Win Rate" value={monthly.win_rate} />
                <Stat label="Calib <50" value={monthly.confidence_calibration?.["<50"]} />
                <Stat label="Calib 50-70" value={monthly.confidence_calibration?.["50-70"]} />
                <Stat label="Calib >=70" value={monthly.confidence_calibration?.[">=70"]} />
                <Stat label="Stale Scan Days" value={monthly.data_provider_reliability?.stale_scan_days} />
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {/* ── EVIDENCE ──────────────────────────────────────────────────── */}
      {tab === "Evidence" && (
        <div className="space-y-4">
          {!evidence && <Loader2 className="h-5 w-5 animate-spin text-zinc-500" />}
          {evidence && (
            <>
              <Card>
                <CardHeader className="pb-2"><CardTitle className="text-base flex items-center gap-2">
                  <TrendingUp className="h-4 w-4" /> Evidence Accumulation Tracker</CardTitle></CardHeader>
                <CardContent className="space-y-3">
                  {Object.entries(evidence.progress ?? {}).map(([k, v]: [string, any]) => (
                    <div key={k}>
                      <div className="flex justify-between text-xs mb-1">
                        <span className="text-zinc-300">{k.replace(/_/g, " ")}</span>
                        <span className="font-mono text-zinc-400">
                          {v.value} / {v.target}{typeof v.pct === "number" ? ` (${v.pct}%)` : ""}
                        </span>
                      </div>
                      {typeof v.pct === "number" && (
                        <div className="h-1.5 rounded bg-zinc-800">
                          <div className="h-1.5 rounded bg-primary" style={{ width: `${Math.min(100, v.pct)}%` }} />
                        </div>
                      )}
                    </div>
                  ))}
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-2 pt-2">
                    <Stat label="Sessions" value={evidence.trading_sessions_completed} />
                    <Stat label="Completed Trades" value={evidence.completed_paper_trades} />
                    <Stat label="Regimes Covered" value={(evidence.market_regimes_covered ?? []).join(", ")} />
                    <Stat label="Successful QA Runs" value={evidence.successful_validation_runs} />
                    <Stat label="Critical QA Failures" value={evidence.critical_qa_failures} />
                    <Stat label="Stale Data Incidents" value={evidence.stale_data_incidents} />
                    <Stat label="Cross-Page Mismatch Days" value={evidence.cross_page_mismatch_days} />
                    <Stat label="Days Since Critical Issue" value={evidence.days_since_last_critical_issue} />
                  </div>
                  <p className="text-[10px] text-zinc-500">{evidence.readiness_note}</p>
                </CardContent>
              </Card>
            </>
          )}
        </div>
      )}

      {/* ── ISSUES ────────────────────────────────────────────────────── */}
      {tab === "Issues" && (
        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-2"><CardTitle className="text-base flex items-center gap-2">
              <Bug className="h-4 w-4" /> Record Issue</CardTitle></CardHeader>
            <CardContent className="flex flex-wrap gap-2 items-center">
              <Input placeholder="Describe the operational issue…" value={issueDesc}
                onChange={(e) => setIssueDesc(e.target.value)} className="flex-1 min-w-52 text-xs" />
              <select className="bg-zinc-900 border border-zinc-800 rounded text-xs p-2"
                value={issueSev} onChange={(e) => setIssueSev(e.target.value)}>
                {["CRITICAL", "HIGH", "MEDIUM", "LOW"].map((s) => <option key={s}>{s}</option>)}
              </select>
              <Button size="sm" onClick={addIssue} disabled={busy || !issueDesc.trim()}>Add</Button>
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2"><CardTitle className="text-base">
              Issue Log ({issues?.total ?? 0} total, {issues?.open_critical ?? 0} open critical)</CardTitle></CardHeader>
            <CardContent className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead><tr className="text-zinc-500 text-left">
                  <th className="p-1">ID</th><th className="p-1">Date</th><th className="p-1">Severity</th>
                  <th className="p-1">Description</th><th className="p-1">Status</th><th className="p-1">Set Status</th>
                </tr></thead>
                <tbody>
                  {(issues?.issues ?? []).map((i: any) => (
                    <tr key={i.issue_id} className="border-t border-zinc-800/60">
                      <td className="p-1 font-mono">{i.issue_id}</td>
                      <td className="p-1 font-mono">{i.date}</td>
                      <td className="p-1"><StatusBadge status={i.severity === "CRITICAL" || i.severity === "HIGH" ? "FAIL" : "WARNING"} /></td>
                      <td className="p-1 max-w-72 truncate" title={i.description}>{i.description}</td>
                      <td className="p-1 font-mono">{i.status}</td>
                      <td className="p-1">
                        <select className="bg-zinc-900 border border-zinc-800 rounded text-[10px] p-1"
                          value={i.status} onChange={(e) => void setIssueStatus(i.issue_id, e.target.value)}>
                          {["OPEN", "INVESTIGATING", "FIXED", "VERIFIED", "DEFERRED"].map((s) => <option key={s}>{s}</option>)}
                        </select>
                      </td>
                    </tr>
                  ))}
                  {!issues?.issues?.length && <tr><td className="p-2 text-zinc-500" colSpan={6}>No issues recorded.</td></tr>}
                </tbody>
              </table>
            </CardContent>
          </Card>
        </div>
      )}

      {/* ── SEARCH ────────────────────────────────────────────────────── */}
      {tab === "Search" && (
        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-2"><CardTitle className="text-base flex items-center gap-2">
              <Search className="h-4 w-4" /> Research Memory Search</CardTitle></CardHeader>
            <CardContent className="flex flex-wrap gap-2 items-center">
              <Input placeholder="free text (notes, decisions)…" value={searchQ}
                onChange={(e) => setSearchQ(e.target.value)} className="flex-1 min-w-40 text-xs" />
              <Input placeholder="symbol" value={searchSymbol}
                onChange={(e) => setSearchSymbol(e.target.value)} className="w-32 text-xs" />
              <select className="bg-zinc-900 border border-zinc-800 rounded text-xs p-2"
                value={searchState} onChange={(e) => setSearchState(e.target.value)}>
                <option value="">any state</option>
                {["PAPER TRADE TAKEN", "SKIPPED", "WATCHED", "REJECTED BY RISK",
                  "REJECTED BY DATA QUALITY", "NO ACTION", "POSITION EXITED"].map((s) => (
                  <option key={s} value={s}>{s}</option>
                ))}
              </select>
              <Button size="sm" onClick={runSearch} disabled={busy}>Search</Button>
            </CardContent>
          </Card>
          {searchResults && (
            <Card>
              <CardHeader className="pb-2"><CardTitle className="text-base">Results ({searchResults.count})</CardTitle></CardHeader>
              <CardContent className="space-y-1 max-h-96 overflow-y-auto">
                {(searchResults.results ?? []).map((r: any, idx: number) => (
                  <div key={idx} className="text-xs border border-zinc-800 rounded p-2 flex flex-wrap gap-2 items-center">
                    <Badge variant="outline" className="text-[9px]">{r.type}</Badge>
                    <span className="font-mono text-zinc-400">{r.notebook_date}</span>
                    <span className="font-mono text-zinc-600">scan {r.scan_id}</span>
                    {r.type === "decision" && (
                      <span>{r.decision?.symbol} · {r.decision?.decision_state} · conf {r.decision?.confidence ?? "-"}</span>
                    )}
                    {r.type === "note" && <span>{r.note?.text}</span>}
                  </div>
                ))}
                {!searchResults.results?.length && <p className="text-xs text-zinc-500">No matches.</p>}
              </CardContent>
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
