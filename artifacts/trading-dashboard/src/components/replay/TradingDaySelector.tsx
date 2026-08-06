/**
 * TradingDaySelector — V5.0
 * Enhanced session picker: prev/next arrows, Latest shortcut, Refresh, metadata grid.
 */
import React, { useState } from "react";
import {
  ChevronLeft, ChevronRight, RefreshCw, Zap,
  Calendar, Clock, BarChart2, TrendingUp, Activity, CheckCircle2,
} from "lucide-react";

export interface TradingSession {
  scan_id: string;
  snapshot_ts: string;
  status: string;
  is_latest: boolean;
  buy_signals: number | null;
  universe_size: number | null;
  paper_orders?: number | null;
}

interface Props {
  sessions: TradingSession[];
  selectedScanId: string;
  onSelect: (scanId: string) => void;
  onRefresh: () => void;
  durationS?: number | null;
  universeSize?: number | null;
}

function fmtDate(ts: string | undefined): string {
  if (!ts) return "—";
  try {
    return new Date(ts).toLocaleDateString("en-IN", {
      timeZone: "Asia/Kolkata",
      weekday: "short", year: "numeric", month: "short", day: "numeric",
    });
  } catch { return ts; }
}

function fmtDuration(s: number | null | undefined): string {
  if (s == null) return "—";
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  const rem = Math.round(s % 60);
  return `${m}m ${rem}s`;
}

function statusStyle(status: string): string {
  const s = status.toUpperCase();
  if (s === "SUCCESS" || s === "COMPLETE") return "text-emerald-400 bg-emerald-900/20 border border-emerald-700/40";
  if (s === "PARTIAL")                     return "text-amber-400 bg-amber-900/20 border border-amber-700/40";
  if (s === "FAILED" || s === "ERROR")     return "text-red-400 bg-red-900/20 border border-red-700/40";
  return "text-slate-400 bg-slate-800/40 border border-slate-700/40";
}

export function TradingDaySelector({
  sessions,
  selectedScanId,
  onSelect,
  onRefresh,
  durationS,
  universeSize,
}: Props) {
  const [refreshing, setRefreshing] = useState(false);

  const currentIdx = sessions.findIndex(s => s.scan_id === selectedScanId);
  const current    = currentIdx >= 0 ? sessions[currentIdx] : sessions[0];
  const hasPrev    = currentIdx > 0;
  const hasNext    = currentIdx >= 0 && currentIdx < sessions.length - 1;
  const latestId   = sessions.find(s => s.is_latest)?.scan_id ?? sessions[0]?.scan_id;
  const isLatest   = current?.is_latest ?? false;

  function handleRefresh() {
    setRefreshing(true);
    onRefresh();
    setTimeout(() => setRefreshing(false), 1500);
  }

  const meta: { label: string; value: string; icon: typeof Calendar; badge?: boolean }[] = [
    { label: "Trading Date",    value: fmtDate(current?.snapshot_ts),                              icon: Calendar },
    { label: "Market",         value: "NSE",                                                       icon: Activity },
    { label: "Replay Duration", value: fmtDuration(durationS),                                    icon: Clock },
    { label: "Universe Size",   value: (universeSize ?? current?.universe_size ?? "—").toString(), icon: BarChart2 },
    { label: "Trades",          value: (current?.paper_orders ?? "—").toString(),                  icon: TrendingUp },
    { label: "Status",          value: current?.status ?? "—",                                     icon: CheckCircle2, badge: true },
  ];

  return (
    <div className="space-y-3">
      {/* ── Navigation row ── */}
      <div className="flex items-center gap-2 flex-wrap">
        <button
          onClick={() => hasPrev && onSelect(sessions[currentIdx - 1].scan_id)}
          disabled={!hasPrev}
          className="flex items-center gap-1 px-3 py-2 bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-lg text-sm text-slate-300 disabled:opacity-30 transition-all"
          title="Previous trading day"
        >
          <ChevronLeft size={14} /> Prev
        </button>

        <select
          value={selectedScanId}
          onChange={e => onSelect(e.target.value)}
          className="flex-1 min-w-48 bg-slate-800 border border-slate-600 rounded-lg px-3 py-2 text-sm text-slate-200 hover:border-teal-500 focus:border-teal-500 focus:outline-none transition-colors"
        >
          {sessions.length === 0 && (
            <option value="latest">Loading sessions…</option>
          )}
          {sessions.map(s => (
            <option key={s.scan_id} value={s.scan_id}>
              {fmtDate(s.snapshot_ts)}{s.is_latest ? " (Latest)" : ""}
              {s.buy_signals != null ? ` — ${s.buy_signals} BUY` : ""}
              {s.universe_size != null ? ` · ${s.universe_size} symbols` : ""}
            </option>
          ))}
        </select>

        <button
          onClick={() => hasNext && onSelect(sessions[currentIdx + 1].scan_id)}
          disabled={!hasNext}
          className="flex items-center gap-1 px-3 py-2 bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-lg text-sm text-slate-300 disabled:opacity-30 transition-all"
          title="Next trading day"
        >
          Next <ChevronRight size={14} />
        </button>

        {!isLatest && latestId && (
          <button
            onClick={() => onSelect(latestId)}
            className="flex items-center gap-1.5 px-3 py-2 bg-teal-700 hover:bg-teal-600 border border-teal-600 rounded-lg text-sm text-white font-semibold transition-all"
          >
            <Zap size={13} /> Latest
          </button>
        )}
        {isLatest && (
          <span className="flex items-center gap-1.5 px-3 py-2 bg-teal-900/30 border border-teal-700/40 rounded-lg text-xs text-teal-400 font-medium">
            <Zap size={12} /> Latest Session
          </span>
        )}

        <button
          onClick={handleRefresh}
          className={`p-2 bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-lg text-slate-400 hover:text-teal-400 transition-all ${refreshing ? "animate-spin text-teal-400" : ""}`}
          title="Refresh sessions"
        >
          <RefreshCw size={14} />
        </button>

        {sessions.length > 0 && (
          <span className="text-xs text-slate-600 ml-auto">
            {/* If selectedScanId is "latest" alias, currentIdx is -1; show as #1 */}
            {Math.max(1, currentIdx + 1)} / {sessions.length} sessions
          </span>
        )}
      </div>

      {/* ── Metadata grid ── */}
      {current && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
          {meta.map(({ label, value, icon: Icon, badge }) => (
            <div key={label} className="bg-slate-800/50 border border-slate-700/40 rounded-lg px-3 py-2 flex items-start gap-2">
              <Icon size={12} className="text-slate-500 mt-0.5 flex-shrink-0" />
              <div className="min-w-0">
                <div className="text-xs text-slate-600 leading-none mb-1">{label}</div>
                {badge ? (
                  <span className={`inline-flex items-center px-1.5 py-0.5 rounded text-xs font-bold ${statusStyle(value)}`}>
                    {value}
                  </span>
                ) : (
                  <div className="text-xs font-semibold text-slate-300 truncate">{value}</div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
