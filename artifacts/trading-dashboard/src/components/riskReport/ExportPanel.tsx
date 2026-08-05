/** Section 14 — Export: CSV, JSON, PDF (all browser-native) */
import { Download, FileText, FileJson, Printer, CheckCircle2 } from "lucide-react";
import type { Report, Candidate } from "./types";

interface Props {
  report: Report;
}

function candidateRows(candidates: Candidate[]) {
  const allGates = Array.from(new Set(candidates.flatMap(c => c.gates.map(g => g.gate))));
  const header = [
    "symbol", "sector", "eligible", "recommendation", "failed_gate_count",
    "confidence", "opportunity_score", "trade_quality_score", "rr_ratio",
    "entry_price", "stop_loss", "target_price", "position_value", "risk_amount", "quantity",
    "strategy_name", "regime",
    ...allGates.map(gid => `gate_${gid}`),
    ...allGates.map(gid => `gate_reason_${gid}`),
  ];

  const rows = candidates.map(c => {
    const gateMap: Record<string, boolean> = {};
    const reasonMap: Record<string, string> = {};
    for (const g of c.gates) { gateMap[g.gate] = g.passed; reasonMap[g.gate] = g.reason; }
    return [
      c.symbol, c.sector, c.eligible ? "TRUE" : "FALSE", c.recommendation,
      c.gates.filter(g => !g.passed).length,
      c.confidence, c.opportunity_score, c.trade_quality_score, c.sizing.rr_ratio,
      c.sizing.entry_price, c.sizing.stop_loss, c.sizing.target_price,
      c.sizing.position_value, c.sizing.risk_amount, c.sizing.quantity,
      c.strategy_name ?? "", c.regime ?? "",
      ...allGates.map(gid => (gateMap[gid] ? "PASS" : "FAIL")),
      ...allGates.map(gid => `"${(reasonMap[gid] ?? "").replace(/"/g, '""')}"`),
    ];
  });

  return { header, rows };
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a   = document.createElement("a");
  a.href    = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

function exportCSV(report: Report) {
  const candidates = report.candidates ?? [];
  const { header, rows } = candidateRows(candidates);
  const lines = [header.join(","), ...rows.map(r => r.join(","))].join("\n");
  const ts = (report.evaluated_at ?? new Date().toISOString()).slice(0, 16).replace(/[T:]/g, "-");
  downloadBlob(new Blob([lines], { type: "text/csv" }), `risk-report-${ts}.csv`);
}

function exportJSON(report: Report) {
  const ts = (report.evaluated_at ?? new Date().toISOString()).slice(0, 16).replace(/[T:]/g, "-");
  downloadBlob(
    new Blob([JSON.stringify(report, null, 2)], { type: "application/json" }),
    `risk-report-${ts}.json`
  );
}

function exportPDF() {
  window.print();
}

export function ExportPanel({ report }: Props) {
  const candidates = report.candidates ?? [];
  const blocked    = candidates.filter(c => !c.eligible);
  const eligible   = candidates.filter(c => c.eligible);
  const { header, rows } = candidateRows(candidates);

  return (
    <div className="space-y-6">
      {/* What's included */}
      <div className="bg-slate-800/40 border border-slate-700/40 rounded-xl p-4 space-y-3">
        <h3 className="text-sm font-semibold text-slate-300">Export Contents</h3>
        <div className="grid sm:grid-cols-2 gap-3 text-xs text-slate-400">
          <div className="space-y-1">
            <div className="font-semibold text-slate-300 mb-1">Candidates ({candidates.length})</div>
            {[
              `${eligible.length} eligible · ${blocked.length} rejected`,
              "All gate pass / fail verdicts",
              "Gate failure reasons",
              "Confidence, R:R, opportunity, trade quality scores",
              "Entry, stop, target prices",
              "Position size and capital required",
              "Strategy and regime",
            ].map(item => (
              <div key={item} className="flex items-center gap-1.5">
                <CheckCircle2 className="w-3 h-3 text-emerald-500 shrink-0" />
                {item}
              </div>
            ))}
          </div>
          <div className="space-y-1">
            <div className="font-semibold text-slate-300 mb-1">Gate Analysis ({report.gate_pressure?.length ?? 0} gates)</div>
            {[
              "Today blocked count + percentage",
              "7-day and 30-day blocked counts",
              "Trend direction",
              "Top blockers",
              `Scan ID: ${report.scan_id ?? "—"}`,
              `Evaluated: ${report.evaluated_at?.slice(0, 16) ?? "—"} IST`,
            ].map(item => (
              <div key={item} className="flex items-center gap-1.5">
                <CheckCircle2 className="w-3 h-3 text-emerald-500 shrink-0" />
                {item}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* CSV preview */}
      <div className="bg-slate-900/60 border border-slate-700/40 rounded-xl p-4 space-y-2">
        <div className="text-xs text-slate-500 font-semibold">CSV Preview ({header.length} columns, {rows.length} data rows)</div>
        <div className="overflow-x-auto">
          <pre className="text-xs text-slate-500 font-mono whitespace-pre leading-relaxed max-h-24 overflow-hidden">
            {header.slice(0, 12).join(",")}
            {"\n"}
            {rows.slice(0, 2).map(r => r.slice(0, 12).join(",")).join("\n")}
            {rows.length > 2 && "\n…"}
          </pre>
        </div>
      </div>

      {/* Export buttons */}
      <div className="grid sm:grid-cols-3 gap-3">
        <button
          onClick={() => exportCSV(report)}
          className="flex items-center justify-center gap-2 bg-emerald-800/30 hover:bg-emerald-800/50 border border-emerald-700/50 text-emerald-300 rounded-xl px-4 py-4 text-sm font-medium transition"
        >
          <FileText className="w-5 h-5" />
          <div>
            <div>Export CSV</div>
            <div className="text-xs text-emerald-500/70 font-normal mt-0.5">{candidates.length} rows · {header.length} cols</div>
          </div>
          <Download className="w-4 h-4 ml-auto" />
        </button>

        <button
          onClick={() => exportJSON(report)}
          className="flex items-center justify-center gap-2 bg-blue-800/30 hover:bg-blue-800/50 border border-blue-700/50 text-blue-300 rounded-xl px-4 py-4 text-sm font-medium transition"
        >
          <FileJson className="w-5 h-5" />
          <div>
            <div>Export JSON</div>
            <div className="text-xs text-blue-500/70 font-normal mt-0.5">Full report object</div>
          </div>
          <Download className="w-4 h-4 ml-auto" />
        </button>

        <button
          onClick={exportPDF}
          className="flex items-center justify-center gap-2 bg-purple-800/30 hover:bg-purple-800/50 border border-purple-700/50 text-purple-300 rounded-xl px-4 py-4 text-sm font-medium transition"
        >
          <Printer className="w-5 h-5" />
          <div>
            <div>Export PDF</div>
            <div className="text-xs text-purple-500/70 font-normal mt-0.5">Print-optimised layout</div>
          </div>
        </button>
      </div>

      <div className="text-xs text-slate-600 text-center">
        All exports use the currently loaded report data. No additional API calls are made.
      </div>
    </div>
  );
}
