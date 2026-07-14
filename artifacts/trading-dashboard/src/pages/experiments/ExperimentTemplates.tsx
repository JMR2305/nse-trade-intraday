/**
 * ExperimentTemplates.tsx — Phase 4.1 Research Factory: Template Gallery.
 *
 * Provides ready-to-run templates for 5 market condition regimes and
 * 3 parameter sweeps.  Users can preview, edit, and queue experiments
 * from templates without starting from scratch.
 *
 * Paper trading and research only — no auto-promotion, no live orders.
 */
import { useState } from "react";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select, SelectContent, SelectItem, SelectTrigger, SelectValue,
} from "@/components/ui/select";
import { Loader2, AlertTriangle, Eye, Play, Package, CheckCircle2 } from "lucide-react";
import { cn } from "@/lib/utils";
import { useToast } from "@/hooks/use-toast";

/* eslint-disable @typescript-eslint/no-explicit-any */

import { apiJson } from "@/lib/api";

// ── Types ──────────────────────────────────────────────────────────────────

export interface WFConfig {
  train_years: number;
  test_months: number;
  step_months: number;
  start_date: string;
  end_date: string;
  universe_size: number;
  intrabar_rule: string;
  max_holding_days: number;
  min_confidence_execute: number;
}

interface TemplateVariant {
  name: string;
  label: string;
  config: WFConfig;
}

interface TemplateDef {
  id: string;
  family: string;
  familyLabel: string;
  name: string;
  emoji: string;
  description: string;
  regime?: string;
  isSweep?: boolean;
  singleConfig?: WFConfig;
  variants?: TemplateVariant[];
  sweepParam?: string;
  expectedExperiments?: number;
}

export interface ExistingExperiment {
  id: string;
  name: string;
  status: string;
  config_hash?: string;
  canonical_config?: WFConfig;
  config_summary?: any;
}

// ── Canonical key (client-side duplicate detection) ────────────────────────

export function canonicalKey(cfg: Partial<WFConfig>): string {
  return JSON.stringify({
    train_years: cfg.train_years ?? 1,
    test_months: cfg.test_months ?? 3,
    step_months: cfg.step_months ?? 3,
    start_date: cfg.start_date ?? "",
    end_date: cfg.end_date ?? "",
    universe_size: cfg.universe_size ?? 0,
    intrabar_rule: cfg.intrabar_rule ?? "conservative",
    max_holding_days: cfg.max_holding_days ?? 20,
    min_confidence_execute: cfg.min_confidence_execute ?? 55,
  });
}

// ── Base config used by all sweep templates ────────────────────────────────

const BASE_SWEEP: WFConfig = {
  train_years: 1, test_months: 3, step_months: 3,
  start_date: "", end_date: "",
  universe_size: 0, intrabar_rule: "conservative",
  max_holding_days: 20, min_confidence_execute: 55,
};

// ── Template definitions ───────────────────────────────────────────────────

export const TEMPLATE_FAMILIES: TemplateDef[] = [
  // ── Market Conditions ──────────────────────────────────────────────────
  {
    id: "bull_market", family: "market_conditions", familyLabel: "Market Conditions",
    name: "Bull Market",
    emoji: "📈", description: "Post-recovery bull cycle — Apr 2023 to Dec 2025",
    regime: "Trending up · momentum bias · breakouts dominate",
    singleConfig: { ...BASE_SWEEP, start_date: "2023-04-01", end_date: "2025-12-31" },
  },
  {
    id: "bear_market", family: "market_conditions", familyLabel: "Market Conditions",
    name: "Bear Market",
    emoji: "📉", description: "Post-peak bear cycle — Oct 2021 to Mar 2023",
    regime: "Trending down · mean-reversion · tight stops critical",
    singleConfig: { ...BASE_SWEEP, start_date: "2021-10-01", end_date: "2023-03-31" },
  },
  {
    id: "sideways",    family: "market_conditions", familyLabel: "Market Conditions",
    name: "Sideways / Range-Bound",
    emoji: "↔️", description: "Slow grind sideways — Jul 2019 to Sep 2021",
    regime: "No clear trend · chop risk high · signal degradation expected",
    singleConfig: { ...BASE_SWEEP, start_date: "2019-07-01", end_date: "2021-09-30" },
  },
  {
    id: "high_volatility", family: "market_conditions", familyLabel: "Market Conditions",
    name: "High Volatility",
    emoji: "🌊", description: "COVID crash & recovery — Jan 2020 to Dec 2020",
    regime: "Extreme vol · whipsaw risk · short test windows",
    singleConfig: { ...BASE_SWEEP, start_date: "2020-01-01", end_date: "2020-12-31", test_months: 2, step_months: 2 },
  },
  {
    id: "low_volatility", family: "market_conditions", familyLabel: "Market Conditions",
    name: "Low Volatility",
    emoji: "😴", description: "Pre-COVID calm — Jan 2017 to Jun 2019",
    regime: "Low vol · signal quality higher · drawdowns shallow",
    singleConfig: { ...BASE_SWEEP, start_date: "2017-01-01", end_date: "2019-06-30" },
  },
  // ── Parameter Sweeps ──────────────────────────────────────────────────
  {
    id: "confidence_sweep", family: "confidence_sweep", familyLabel: "Confidence Sweep",
    name: "Confidence Threshold Sweep",
    emoji: "🎯", description: "Compare 4 confidence cut-offs on full available history",
    isSweep: true, sweepParam: "min_confidence_execute",
    expectedExperiments: 4,
    variants: [
      { name: "Conf 55%", label: "55% threshold", config: { ...BASE_SWEEP, min_confidence_execute: 55 } },
      { name: "Conf 60%", label: "60% threshold", config: { ...BASE_SWEEP, min_confidence_execute: 60 } },
      { name: "Conf 65%", label: "65% threshold", config: { ...BASE_SWEEP, min_confidence_execute: 65 } },
      { name: "Conf 70%", label: "70% threshold", config: { ...BASE_SWEEP, min_confidence_execute: 70 } },
    ],
  },
  {
    id: "holding_sweep", family: "holding_sweep", familyLabel: "Holding-Period Sweep",
    name: "Max Holding-Period Sweep",
    emoji: "⏱️", description: "Compare 4 holding limits on full available history",
    isSweep: true, sweepParam: "max_holding_days",
    expectedExperiments: 4,
    variants: [
      { name: "Hold 10d", label: "10 trading days", config: { ...BASE_SWEEP, max_holding_days: 10 } },
      { name: "Hold 15d", label: "15 trading days", config: { ...BASE_SWEEP, max_holding_days: 15 } },
      { name: "Hold 20d", label: "20 trading days", config: { ...BASE_SWEEP, max_holding_days: 20 } },
      { name: "Hold 30d", label: "30 trading days", config: { ...BASE_SWEEP, max_holding_days: 30 } },
    ],
  },
  {
    id: "window_sweep", family: "window_sweep", familyLabel: "Train/Test Sweep",
    name: "Training/Test Window Sweep",
    emoji: "🪟", description: "Compare 3 walk-forward window sizes on full available history",
    isSweep: true, sweepParam: "train_years / test_months",
    expectedExperiments: 3,
    variants: [
      { name: "1yr / 3mo", label: "1yr train, 3mo test, 3mo step", config: { ...BASE_SWEEP, train_years: 1, test_months: 3, step_months: 3 } },
      { name: "2yr / 3mo", label: "2yr train, 3mo test (recommended for PASS verdict)", config: { ...BASE_SWEEP, train_years: 2, test_months: 3, step_months: 3 } },
      { name: "1yr / 6mo", label: "1yr train, 6mo test, 6mo step (fewer but larger windows)", config: { ...BASE_SWEEP, train_years: 1, test_months: 6, step_months: 6 } },
    ],
  },
];

// ── Config editor (inline, reusable) ──────────────────────────────────────

function ConfigEditor({ cfg, onChange, title }: {
  cfg: WFConfig; onChange: (c: WFConfig) => void; title?: string;
}) {
  function set<K extends keyof WFConfig>(k: K, v: WFConfig[K]) {
    onChange({ ...cfg, [k]: v });
  }
  return (
    <div className="space-y-3 p-3 rounded-md border border-zinc-700 bg-zinc-900/50">
      {title && <p className="text-[11px] font-mono font-semibold text-zinc-300">{title}</p>}
      <div className="grid grid-cols-3 gap-2">
        <div>
          <Label className="text-[10px] font-mono text-zinc-400">TRAINING</Label>
          <Select value={String(cfg.train_years)} onValueChange={v => set("train_years", Number(v))}>
            <SelectTrigger className="h-7 font-mono text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              {[1,2,3].map(n => <SelectItem key={n} value={String(n)}>{n} year{n>1?"s":""}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div>
          <Label className="text-[10px] font-mono text-zinc-400">TEST</Label>
          <Select value={String(cfg.test_months)} onValueChange={v => set("test_months", Number(v))}>
            <SelectTrigger className="h-7 font-mono text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              {[1,2,3,6].map(n => <SelectItem key={n} value={String(n)}>{n} month{n>1?"s":""}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
        <div>
          <Label className="text-[10px] font-mono text-zinc-400">STEP</Label>
          <Select value={String(cfg.step_months)} onValueChange={v => set("step_months", Number(v))}>
            <SelectTrigger className="h-7 font-mono text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              {[1,2,3,6].map(n => <SelectItem key={n} value={String(n)}>{n} month{n>1?"s":""}</SelectItem>)}
            </SelectContent>
          </Select>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <Label className="text-[10px] font-mono text-zinc-400">START (YYYY-MM-DD)</Label>
          <Input className="h-7 font-mono text-xs" value={cfg.start_date}
            onChange={e => set("start_date", e.target.value)} placeholder="leave blank = all history" />
        </div>
        <div>
          <Label className="text-[10px] font-mono text-zinc-400">END (YYYY-MM-DD)</Label>
          <Input className="h-7 font-mono text-xs" value={cfg.end_date}
            onChange={e => set("end_date", e.target.value)} placeholder="leave blank = today" />
        </div>
      </div>
      <div className="grid grid-cols-3 gap-2">
        <div>
          <Label className="text-[10px] font-mono text-zinc-400">MAX HOLD (days)</Label>
          <Input className="h-7 font-mono text-xs" value={cfg.max_holding_days}
            onChange={e => set("max_holding_days", Number(e.target.value))} />
        </div>
        <div>
          <Label className="text-[10px] font-mono text-zinc-400">CONF %</Label>
          <Input className="h-7 font-mono text-xs" value={cfg.min_confidence_execute}
            onChange={e => set("min_confidence_execute", Number(e.target.value))} />
        </div>
        <div>
          <Label className="text-[10px] font-mono text-zinc-400">INTRABAR</Label>
          <Select value={cfg.intrabar_rule} onValueChange={v => set("intrabar_rule", v)}>
            <SelectTrigger className="h-7 font-mono text-xs"><SelectValue /></SelectTrigger>
            <SelectContent>
              <SelectItem value="conservative">Conservative</SelectItem>
              <SelectItem value="optimistic">Optimistic</SelectItem>
            </SelectContent>
          </Select>
        </div>
      </div>
    </div>
  );
}

// ── Duplicate check helper ─────────────────────────────────────────────────

function findDuplicates(cfg: WFConfig, existing: ExistingExperiment[]): ExistingExperiment[] {
  const key = canonicalKey(cfg);
  return existing.filter(e => {
    if (e.canonical_config) return canonicalKey(e.canonical_config) === key;
    if (e.config_summary) return canonicalKey(e.config_summary) === key;
    return false;
  });
}

// ── Preview modal ──────────────────────────────────────────────────────────

function PreviewModal({ template, existing, onClose, onQueued }: {
  template: TemplateDef;
  existing: ExistingExperiment[];
  onClose: () => void;
  onQueued: () => void;
}) {
  const { toast } = useToast();
  const isSweep = template.isSweep && template.variants;

  // Single experiment state
  const [singleConfig, setSingleConfig] = useState<WFConfig>(
    template.singleConfig ?? BASE_SWEEP
  );
  const [singleName, setSingleName] = useState(
    `${template.name} — ${new Date().toLocaleDateString("en-IN", { month: "short", year: "numeric" })}`
  );

  // Sweep state
  const [variants, setVariants] = useState<TemplateVariant[]>(
    template.variants ? template.variants.map(v => ({ ...v })) : []
  );
  const [batchName, setBatchName] = useState(
    `${template.name} Batch — ${new Date().toLocaleDateString("en-IN", { month: "short", year: "numeric" })}`
  );

  const [submitting, setSubmitting] = useState(false);
  const [dupWarning, setDupWarning] = useState<{ configs: WFConfig[]; names: string[]; onConfirm: () => void } | null>(null);

  function updateVariant(idx: number, cfg: WFConfig) {
    setVariants(vs => vs.map((v, i) => i === idx ? { ...v, config: cfg } : v));
  }

  // Single-experiment duplicates
  const singleDups = findDuplicates(singleConfig, existing);

  async function queueSingle(force = false) {
    if (!force && singleDups.length > 0) {
      setDupWarning({
        configs: [singleConfig],
        names: [singleName],
        onConfirm: () => { setDupWarning(null); queueSingle(true); },
      });
      return;
    }
    setSubmitting(true);
    try {
      const data = await apiJson("/experiments", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...singleConfig,
          name: singleName,
          template_id: template.id,
          template_family: template.family,
        }),
      });
      const expId = data?.experiment?.id || data?.id || "";
      toast({ title: "Experiment queued", description: `"${singleName}"${expId ? ` (${expId})` : ""} added to queue.` });
      onQueued();
      onClose();
    } catch (e) {
      toast({ title: "Failed", description: String(e), variant: "destructive" });
    } finally {
      setSubmitting(false);
    }
  }

  async function queueBatch(force = false) {
    const batchId = `batch_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    // Duplicate check across all variants
    if (!force) {
      const dupConfigs: WFConfig[] = [];
      const dupNames: string[] = [];
      variants.forEach(v => {
        const dups = findDuplicates(v.config, existing);
        if (dups.length > 0) { dupConfigs.push(v.config); dupNames.push(v.name); }
      });
      if (dupConfigs.length > 0) {
        setDupWarning({ configs: dupConfigs, names: dupNames, onConfirm: () => { setDupWarning(null); queueBatch(true); } });
        return;
      }
    }
    setSubmitting(true);
    try {
      await Promise.all(
        variants.map((v, idx) =>
          apiJson("/experiments", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              ...v.config,
              name: v.name,
              description: v.label,
              batch_id: batchId,
              batch_name: batchName,
              batch_index: idx,
              template_id: template.id,
              template_family: template.family,
            }),
          })
        )
      );
      toast({
        title: "Batch queued",
        description: `${variants.length} experiments added as batch "${batchName}".`,
      });
      onQueued();
      onClose();
    } catch (e) {
      toast({ title: "Batch queue failed", description: String(e), variant: "destructive" });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
      <div className="w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-lg border border-zinc-700 bg-zinc-900 shadow-2xl">
        <div className="sticky top-0 bg-zinc-900 border-b border-zinc-800 px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-lg">{template.emoji}</span>
            <div>
              <h3 className="text-sm font-mono font-bold">{template.name}</h3>
              <p className="text-[10px] font-mono text-zinc-500">{template.description}</p>
            </div>
          </div>
          <button className="text-zinc-400 hover:text-zinc-200 text-lg leading-none" onClick={onClose}>✕</button>
        </div>

        <div className="p-4 space-y-4">
          {/* Duplicate warning */}
          {dupWarning && (
            <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3 space-y-2">
              <div className="flex items-start gap-2">
                <AlertTriangle className="h-4 w-4 text-amber-400 flex-shrink-0 mt-0.5" />
                <div className="text-xs font-mono text-amber-300">
                  <span className="font-semibold">Duplicate configuration detected</span>
                  <p className="text-zinc-400 mt-0.5">
                    {dupWarning.names.join(", ")} — an experiment with the same effective config already exists.
                    Queue anyway?
                  </p>
                </div>
              </div>
              <div className="flex gap-2">
                <Button size="sm" variant="outline" className="font-mono text-xs h-7"
                  onClick={() => setDupWarning(null)}>Cancel</Button>
                <Button size="sm" className="font-mono text-xs h-7 bg-amber-600 hover:bg-amber-500 text-white"
                  onClick={dupWarning.onConfirm}>Queue anyway</Button>
              </div>
            </div>
          )}

          {/* Research-only banner */}
          <p className="text-[10px] font-mono text-amber-400 border border-amber-500/30 rounded px-2 py-1.5 bg-amber-500/5">
            ⚠ Research only — results are out-of-sample historical performance.
            No auto-promotion. No live orders affected.
          </p>

          {/* Single experiment */}
          {!isSweep && template.singleConfig && (
            <>
              {template.regime && (
                <p className="text-[10px] font-mono text-zinc-500">
                  Regime context: {template.regime}
                </p>
              )}
              <div>
                <Label className="text-[10px] font-mono text-zinc-400 mb-1 block">EXPERIMENT NAME</Label>
                <Input className="h-8 font-mono text-xs" value={singleName}
                  onChange={e => setSingleName(e.target.value)} />
              </div>
              <ConfigEditor cfg={singleConfig} onChange={setSingleConfig} title="Walk-Forward Config (editable)" />
              {singleDups.length > 0 && (
                <p className="text-[10px] font-mono text-amber-400">
                  ⚠ Duplicate: "{singleDups[0].name}" ({singleDups[0].status}) has the same config.
                </p>
              )}
              <Button className="w-full font-mono text-xs h-9 bg-emerald-600 hover:bg-emerald-500 text-white"
                onClick={() => queueSingle()} disabled={submitting || !singleName.trim()}>
                {submitting
                  ? <><Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />Queuing…</>
                  : <><Play className="h-3.5 w-3.5 mr-1.5" />Queue Experiment</>}
              </Button>
            </>
          )}

          {/* Sweep batch */}
          {isSweep && (
            <>
              <div>
                <Label className="text-[10px] font-mono text-zinc-400 mb-1 block">BATCH NAME</Label>
                <Input className="h-8 font-mono text-xs" value={batchName}
                  onChange={e => setBatchName(e.target.value)} />
              </div>
              <p className="text-[10px] font-mono text-zinc-500">
                Sweeping: <span className="text-zinc-300">{template.sweepParam}</span> ·
                {" "}{variants.length} experiments queued sequentially as one batch.
                All other parameters held constant.
              </p>
              <div className="space-y-2">
                {variants.map((v, idx) => (
                  <ConfigEditor key={idx} cfg={v.config} onChange={cfg => updateVariant(idx, cfg)}
                    title={`Variant ${idx + 1}: ${v.name} — ${v.label}`} />
                ))}
              </div>
              <Button className="w-full font-mono text-xs h-9 bg-violet-600 hover:bg-violet-500 text-white"
                onClick={() => queueBatch()} disabled={submitting || !batchName.trim()}>
                {submitting
                  ? <><Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />Queuing batch…</>
                  : <><Package className="h-3.5 w-3.5 mr-1.5" />Queue as Batch ({variants.length} experiments)</>}
              </Button>
            </>
          )}
        </div>
      </div>
    </div>
  );
}

// ── TemplateCard ───────────────────────────────────────────────────────────

function TemplateCard({ template, existing, onQueued }: {
  template: TemplateDef;
  existing: ExistingExperiment[];
  onQueued: () => void;
}) {
  const [modalOpen, setModalOpen] = useState(false);

  // Count how many variants already have experiments
  const alreadyQueued = template.isSweep && template.variants
    ? template.variants.filter(v => findDuplicates(v.config, existing).length > 0).length
    : (template.singleConfig && findDuplicates(template.singleConfig, existing).length > 0 ? 1 : 0);
  const totalVariants = template.isSweep ? (template.variants?.length ?? 0) : 1;
  const allDone = alreadyQueued === totalVariants && totalVariants > 0;

  return (
    <>
      <div
        className={cn(
          "rounded-md border p-3 flex flex-col gap-2 cursor-pointer transition-colors hover:border-zinc-500 hover:bg-zinc-800/40",
          allDone ? "border-emerald-700/40 bg-emerald-900/10" : "border-zinc-700 bg-zinc-800/20"
        )}
        onClick={() => setModalOpen(true)}
      >
        <div className="flex items-start justify-between">
          <div>
            <div className="flex items-center gap-1.5">
              <span className="text-base leading-none">{template.emoji}</span>
              <span className="text-xs font-mono font-semibold">{template.name}</span>
              {allDone && <CheckCircle2 className="h-3.5 w-3.5 text-emerald-400" />}
            </div>
            <p className="text-[10px] font-mono text-zinc-500 mt-1">{template.description}</p>
          </div>
          {template.isSweep && (
            <Badge variant="outline" className="text-[9px] font-mono text-violet-300 border-violet-600 flex-shrink-0">
              {template.expectedExperiments} exp
            </Badge>
          )}
        </div>
        {template.singleConfig && (
          <p className="text-[10px] font-mono text-zinc-600">
            {template.singleConfig.train_years}yr train · {template.singleConfig.test_months}mo test
            {template.singleConfig.start_date ? ` · ${template.singleConfig.start_date.slice(0,7)}–${(template.singleConfig.end_date||"now").slice(0,7)}` : " · all history"}
          </p>
        )}
        {template.regime && (
          <p className="text-[10px] font-mono text-zinc-600 italic">{template.regime}</p>
        )}
        {alreadyQueued > 0 && !allDone && (
          <p className="text-[10px] font-mono text-amber-400">
            ⚠ {alreadyQueued}/{totalVariants} already queued
          </p>
        )}
        <Button
          size="sm"
          variant="outline"
          className="h-7 font-mono text-[11px] w-full mt-auto"
          onClick={e => { e.stopPropagation(); setModalOpen(true); }}
        >
          <Eye className="h-3.5 w-3.5 mr-1.5" />
          Preview & Queue
        </Button>
      </div>
      {modalOpen && (
        <PreviewModal
          template={template}
          existing={existing}
          onClose={() => setModalOpen(false)}
          onQueued={onQueued}
        />
      )}
    </>
  );
}

// ── Main export ────────────────────────────────────────────────────────────

export function ExperimentTemplates({
  existing,
  onQueued,
}: {
  existing: ExistingExperiment[];
  onQueued: () => void;
}) {
  const marketConditions = TEMPLATE_FAMILIES.filter(t => t.family === "market_conditions");
  const sweeps = TEMPLATE_FAMILIES.filter(t => t.family !== "market_conditions");

  return (
    <div className="space-y-5">
      {/* Section: Market Conditions */}
      <div>
        <div className="flex items-center gap-2 mb-3">
          <span className="text-[11px] font-mono font-semibold text-zinc-300">MARKET CONDITION TEMPLATES</span>
          <span className="text-[10px] font-mono text-zinc-600">— constrained date range, otherwise standard config</span>
        </div>
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-2">
          {marketConditions.map(t => (
            <TemplateCard key={t.id} template={t} existing={existing} onQueued={onQueued} />
          ))}
        </div>
      </div>

      {/* Section: Sweeps */}
      <div>
        <div className="flex items-center gap-2 mb-3">
          <span className="text-[11px] font-mono font-semibold text-zinc-300">PARAMETER SWEEP TEMPLATES</span>
          <span className="text-[10px] font-mono text-zinc-600">— vary one parameter, hold all others constant, queue as batch</span>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
          {sweeps.map(t => (
            <TemplateCard key={t.id} template={t} existing={existing} onQueued={onQueued} />
          ))}
        </div>
      </div>

      <p className="text-[10px] font-mono text-zinc-600 border-t border-zinc-800 pt-2">
        All templates use NIFTY 50 universe · ₹5,000 paper capital · strict no-lookahead train/test splits ·
        results are research-only and do not affect live paper-trading strategy selection.
      </p>
    </div>
  );
}
