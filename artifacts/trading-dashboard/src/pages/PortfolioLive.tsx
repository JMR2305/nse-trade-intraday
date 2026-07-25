import { useEffect, useRef, useState, useCallback } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { apiJson, API_BASE } from "@/lib/api";
import DataFreshnessBar from "@/components/DataFreshnessBar";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  TrendingUp,
  TrendingDown,
  Wallet,
  BarChart2,
  AlertTriangle,
  CheckCircle2,
  RefreshCcw,
  Activity,
  DollarSign,
  PieChart,
  ShieldAlert,
  Settings,
  ChevronDown,
  ChevronRight,
  Pencil,
  X,
  Check,
  RotateCcw,
} from "lucide-react";

// ── Types ─────────────────────────────────────────────────────────────────────

interface OpenPosition {
  symbol: string;
  quantity: number;
  avg_entry_price: number;
  last_price: number;
  market_value: number;
  unrealised_pnl: number;
  unrealised_pnl_pct: number;
  side: string;
  strategy_id?: string | null;
  sector?: string | null;
  opened_at?: string | null;
  /** Added by portfolio_snapshot.py: position market_value as % of equity */
  exposure_pct?: number;
}

interface SectorExposure {
  sector: string;
  total_value: number;
  exposure_pct: number;
  limit_pct: number;
  ratio: number;
  position_count: number;
}

interface ExposureWarning {
  kind: "instrument" | "sector";
  name: string;
  exposure_pct: number;
  limit_pct: number;
  ratio: number;
  severity: "WARNING" | "CRITICAL";
}

interface PortfolioSnapshot {
  status: string;
  paper_mode: boolean;
  snapshotted_at: string;
  equity: number;
  cash: number;
  buying_power: number;
  invested_value: number;
  initial_capital: number;
  unrealised_pnl: number;
  realised_pnl_today: number;
  total_pnl: number;
  peak_equity: number;
  drawdown_amount: number;
  drawdown_pct: number;
  open_positions: OpenPosition[];
  open_position_count: number;
  closed_positions_today: number;
  // Exposure additions
  instrument_limit_pct?: number;
  sector_limit_pct?: number;
  /** true when limits came from PortfolioConfig; false means hardcoded defaults were used */
  limits_from_config?: boolean;
  sector_exposures?: SectorExposure[];
  exposure_warnings?: ExposureWarning[];
}

interface PortfolioHealth {
  status: string;
  initialized: boolean;
  paper_mode: boolean;
  auto_paper_enabled: boolean;
  liveness: boolean;
  readiness: boolean;
  degraded: boolean;
  failure_reason?: string | null;
  unresolved_discrepancies: number;
  /** true when PortfolioConfig loaded successfully; false = hardcoded defaults in use */
  limits_from_config?: boolean;
  /** human-readable list of active degraded reasons */
  degraded_reasons?: string[];
  state_freshness_s?: number | null;
  /**
   * true when at least one email transport (Resend or SMTP) is configured.
   * When false and limits_from_config is also false, the config-defaults
   * PERFORMANCE_ALERT was stored in-app but email delivery was silently skipped.
   */
  email_transport_configured?: boolean;
  checked_at: string;
}

interface PortfolioConfigValues {
  // Identity
  portfolio_id: string;
  enabled: boolean;
  base_currency: string;
  paper_mode: boolean;
  // Capital
  initial_capital: number;
  cash_reserve_pct: number;
  // Exposure limits (fractions 0–1)
  max_portfolio_exposure_pct: number;
  max_instrument_exposure_pct: number;
  max_sector_exposure_pct: number;
  max_strategy_exposure_pct: number;
  // Position / order counts
  max_open_positions: number;
  max_pending_orders: number;
  // Loss / drawdown caps
  max_daily_loss_pct: number;
  max_drawdown_pct: number;
  max_capital_per_strategy_pct: number;
  // Position sizing
  min_order_value: number;
  max_order_value: number;
  default_risk_per_trade_pct: number;
  use_ai_confidence_sizing: boolean;
  ai_confidence_min: number;
  // Staleness thresholds (seconds)
  stale_state_threshold_s: number;
  stale_broker_threshold_s: number;
  stale_price_threshold_s: number;
  // Intervals (seconds)
  reconciliation_interval_s: number;
  snapshot_interval_s: number;
  allocation_ttl_s: number;
}

interface PortfolioConfigResponse {
  loaded: boolean;
  limits_from_config: boolean;
  config: Partial<PortfolioConfigValues>;
  error?: string | null;
  fetched_at: string;
  /** Current session-level overrides (field → numeric value) */
  overrides?: Partial<Record<string, number>>;
  /** Fields currently overridden in this session */
  overridden_fields?: string[];
}

interface PatchConfigResponse {
  ok: boolean;
  overrides: Record<string, number>;
  overridden_fields: string[];
  applied: string[];
}

interface PatchConfigError {
  error: string;
  field_errors?: Record<string, string>;
}

// ── Editable-field type definitions ──────────────────────────────────────────

type FieldKind = "pct" | "int" | "money";

/** Fields the operator may change at runtime (must match MUTABLE_FIELDS in portfolio.ts). */
const MUTABLE_FIELD_KINDS: Record<string, FieldKind> = {
  max_open_positions:           "int",
  max_pending_orders:           "int",
  max_daily_loss_pct:           "pct",
  max_drawdown_pct:             "pct",
  max_capital_per_strategy_pct: "pct",
  min_order_value:              "money",
  max_order_value:              "money",
  max_instrument_exposure_pct:  "pct",
  max_sector_exposure_pct:      "pct",
  max_strategy_exposure_pct:    "pct",
  max_portfolio_exposure_pct:   "pct",
  cash_reserve_pct:             "pct",
  default_risk_per_trade_pct:   "pct",
};

/** For pct fields the API stores fractions (0–1). UI shows / inputs percentages (0–100). */
function toDisplayValue(fieldKind: FieldKind, raw: number | undefined): string {
  if (raw === undefined) return "";
  if (fieldKind === "pct") return (raw * 100).toFixed(2);
  if (fieldKind === "int") return String(Math.round(raw));
  return String(raw);
}

/** Parse UI input back to the fraction / number the API expects. */
function toApiValue(fieldKind: FieldKind, input: string): number | null {
  const n = Number(input.trim());
  if (!Number.isFinite(n)) return null;
  if (fieldKind === "pct") return n / 100;
  if (fieldKind === "int") {
    if (!Number.isInteger(n)) return null;
    return n;
  }
  return n;
}

/** Client-side validation — mirrors the backend rules for immediate feedback. */
function validateInput(fieldKind: FieldKind, input: string): string | null {
  const v = toApiValue(fieldKind, input);
  if (v === null)
    return fieldKind === "int" ? "Must be a whole number" : "Must be a number";
  if (fieldKind === "pct") {
    const displayPct = Number(input.trim());
    if (displayPct <= 0 || displayPct > 100)
      return "Must be between 0.01% and 100%";
  }
  if (fieldKind === "int" && v < 1) return "Must be at least 1";
  if (fieldKind === "money" && v <= 0) return "Must be positive";
  return null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const REFRESH_INTERVAL = 15_000; // 15 s
const WARNING_RATIO = 0.80;      // match backend _WARNING_RATIO

const rupee = (n: number | undefined | null) =>
  `₹${Number(n ?? 0).toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;

const pct = (n: number | undefined | null, digits = 2) => {
  if (n === undefined || n === null || Number.isNaN(n)) return "—";
  const v = Number(n);
  return `${v >= 0 ? "+" : ""}${v.toFixed(digits)}%`;
};

const pnlColor = (v: number | undefined | null) => {
  const n = Number(v ?? 0);
  if (n > 0) return "text-green-400";
  if (n < 0) return "text-red-400";
  return "text-muted-foreground";
};

/** Map an exposure ratio (0–1+) to Tailwind colour classes */
function exposureColor(ratio: number): { bar: string; text: string } {
  if (ratio >= 1.0) return { bar: "bg-red-500",    text: "text-red-400" };
  if (ratio >= 0.8) return { bar: "bg-yellow-500", text: "text-yellow-400" };
  return              { bar: "bg-green-500",        text: "text-green-400" };
}

const statusConfig: Record<string, { color: string; icon: typeof CheckCircle2; label: string }> = {
  HEALTHY:     { color: "text-green-400 border-green-500/40 bg-green-500/10",   icon: CheckCircle2,  label: "HEALTHY"     },
  READY:       { color: "text-green-400 border-green-500/40 bg-green-500/10",   icon: CheckCircle2,  label: "READY"       },
  DEGRADED:    { color: "text-yellow-400 border-yellow-500/40 bg-yellow-500/10", icon: AlertTriangle, label: "DEGRADED"    },
  HALTED:      { color: "text-red-400 border-red-500/40 bg-red-500/10",         icon: AlertTriangle, label: "HALTED"      },
  DOWN:        { color: "text-red-400 border-red-500/40 bg-red-500/10",         icon: AlertTriangle, label: "DOWN"        },
  UNREACHABLE: { color: "text-red-400 border-red-500/40 bg-red-500/10",         icon: AlertTriangle, label: "UNREACHABLE" },
  UNKNOWN:     { color: "text-slate-400 border-slate-500/40 bg-slate-500/10",   icon: Activity,      label: "UNKNOWN"     },
  DISABLED:    { color: "text-slate-400 border-slate-500/40 bg-slate-500/10",   icon: Activity,      label: "DISABLED"    },
};

// ── Components ────────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const cfg = statusConfig[status] ?? statusConfig.UNKNOWN;
  const Icon = cfg.icon;
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded border px-2.5 py-1 text-xs font-mono font-bold ${cfg.color}`}
      data-testid="badge-portfolio-status"
    >
      <Icon className="h-3 w-3" />
      {cfg.label}
    </span>
  );
}

function StatCard({
  label,
  value,
  sub,
  valueClass,
  icon: Icon,
}: {
  label: string;
  value: string;
  sub?: string;
  valueClass?: string;
  icon?: typeof DollarSign;
}) {
  return (
    <Card className="bg-card/50 backdrop-blur border-border/50">
      <CardContent className="p-4 space-y-1">
        <div className="flex items-center gap-1.5 text-xs font-mono uppercase text-muted-foreground tracking-wider">
          {Icon && <Icon className="h-3 w-3" />}
          {label}
        </div>
        <div className={`text-xl font-bold font-mono ${valueClass ?? ""}`}>{value}</div>
        {sub && <div className="text-xs text-muted-foreground">{sub}</div>}
      </CardContent>
    </Card>
  );
}

function DrawdownBar({ pct: drawdownPct }: { pct: number }) {
  const w = Math.max(0, Math.min(100, drawdownPct));
  const color =
    w < 5 ? "bg-green-500" :
    w < 10 ? "bg-yellow-500" :
    "bg-red-500";
  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-2 rounded-full bg-border/60 overflow-hidden">
        <div className={`h-full rounded-full transition-all ${color}`} style={{ width: `${w}%` }} />
      </div>
      <span className={`text-xs font-mono ${w >= 10 ? "text-red-400" : w >= 5 ? "text-yellow-400" : "text-green-400"}`}>
        {w.toFixed(1)}%
      </span>
    </div>
  );
}

/** Compact horizontal bar showing how much of a limit is consumed. */
function ExposureBar({
  exposurePct,
  limitPct,
  label,
}: {
  exposurePct: number;
  limitPct: number;
  label?: string;
}) {
  const ratio = limitPct > 0 ? exposurePct / limitPct : 0;
  const fillW = Math.min(100, ratio * 100);
  const { bar, text } = exposureColor(ratio);
  return (
    <div className="flex items-center gap-1.5 min-w-[90px]" title={`${exposurePct.toFixed(1)}% of equity / limit ${limitPct.toFixed(0)}%`}>
      <div className="flex-1 h-1.5 rounded-full bg-border/60 overflow-hidden">
        <div
          className={`h-full rounded-full transition-all ${bar}`}
          style={{ width: `${fillW}%` }}
        />
      </div>
      <span className={`text-xs font-mono tabular-nums ${text}`}>
        {label ?? `${exposurePct.toFixed(1)}%`}
      </span>
    </div>
  );
}

function PositionRow({
  pos,
  instrumentLimitPct,
}: {
  pos: OpenPosition;
  instrumentLimitPct: number;
}) {
  const upnl = pos.unrealised_pnl;
  const expPct = pos.exposure_pct ?? 0;
  return (
    <tr
      className="border-b border-border/40 hover:bg-accent/20 transition-colors"
      data-testid={`row-position-${pos.symbol}`}
    >
      <td className="px-3 py-2.5 font-mono font-bold text-sm">{pos.symbol}</td>
      <td className="px-3 py-2.5 text-muted-foreground text-xs">{pos.sector ?? "—"}</td>
      <td className="px-3 py-2.5 font-mono text-right text-sm">{pos.quantity}</td>
      <td className="px-3 py-2.5 font-mono text-right text-sm">{rupee(pos.avg_entry_price)}</td>
      <td className="px-3 py-2.5 font-mono text-right text-sm">{rupee(pos.last_price)}</td>
      <td className="px-3 py-2.5 font-mono text-right text-sm">{rupee(pos.market_value)}</td>
      <td className={`px-3 py-2.5 font-mono text-right text-sm ${pnlColor(upnl)}`}>
        {upnl >= 0 ? "+" : ""}
        {rupee(upnl)}
      </td>
      <td className={`px-3 py-2.5 font-mono text-right text-sm ${pnlColor(upnl)}`}>
        {pct(pos.unrealised_pnl_pct)}
      </td>
      <td className="px-3 py-2.5 text-xs text-muted-foreground">{pos.strategy_id ?? "—"}</td>
      {/* Exposure bar column */}
      <td className="px-3 py-2.5 min-w-[120px]" data-testid={`exposure-bar-${pos.symbol}`}>
        <ExposureBar exposurePct={expPct} limitPct={instrumentLimitPct} />
      </td>
    </tr>
  );
}

/** Banner listing all near-limit warnings, shown above the positions table. */
function ExposureWarningBanner({ warnings }: { warnings: ExposureWarning[] }) {
  if (warnings.length === 0) return null;
  const hasCritical = warnings.some((w) => w.severity === "CRITICAL");
  const borderCls = hasCritical
    ? "border-red-500/40 bg-red-500/10"
    : "border-yellow-500/40 bg-yellow-500/10";
  const textCls = hasCritical ? "text-red-400" : "text-yellow-400";
  const iconCls = hasCritical ? "text-red-400" : "text-yellow-400";

  return (
    <div
      className={`flex items-start gap-3 rounded-md border p-3 ${borderCls}`}
      data-testid="banner-exposure-warnings"
    >
      <ShieldAlert className={`h-4 w-4 flex-shrink-0 mt-0.5 ${iconCls}`} />
      <div className="space-y-1 min-w-0">
        <p className={`font-mono font-bold text-xs ${textCls}`}>
          {hasCritical ? "EXPOSURE LIMIT BREACHED" : "EXPOSURE LIMIT WARNING"}
          {" "}— {warnings.length} issue{warnings.length !== 1 ? "s" : ""}
        </p>
        <ul className="space-y-0.5">
          {warnings.map((w, i) => {
            const { text } = exposureColor(w.ratio);
            return (
              <li key={i} className={`text-xs font-mono ${text}`}>
                {w.kind === "instrument" ? "Stock" : "Sector"} <span className="font-bold">{w.name}</span>
                {" "}— {w.exposure_pct.toFixed(1)}% of equity (limit {w.limit_pct.toFixed(0)}%,{" "}
                {(w.ratio * 100).toFixed(0)}% consumed)
              </li>
            );
          })}
        </ul>
      </div>
    </div>
  );
}

/** Sector exposure summary cards. */
function SectorExposureSection({
  sectorExposures,
  sectorLimitPct,
  limitsFromConfig,
}: {
  sectorExposures: SectorExposure[];
  sectorLimitPct: number;
  limitsFromConfig: boolean;
}) {
  if (sectorExposures.length === 0) return null;
  return (
    <Card className="bg-card/50 border-border/50">
      <CardHeader className="pb-2 pt-4 px-4">
        <CardTitle className="text-sm font-mono uppercase tracking-widest text-muted-foreground flex items-center gap-2">
          <BarChart2 className="h-3.5 w-3.5" />
          Sector Exposure
          <span className="ml-auto text-xs font-normal text-muted-foreground">
            Limit: {sectorLimitPct.toFixed(0)}% per sector
            {!limitsFromConfig && (
              <span
                className="ml-1 text-yellow-500/80"
                title="Falling back to hardcoded defaults — PortfolioConfig could not be loaded"
              >
                (default)
              </span>
            )}
          </span>
        </CardTitle>
      </CardHeader>
      <CardContent className="p-4 pt-0 grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {sectorExposures.map((se) => {
          const { text } = exposureColor(se.ratio);
          return (
            <div
              key={se.sector}
              className="rounded-md border border-border/40 bg-background/40 p-3 space-y-2"
              data-testid={`sector-exposure-${se.sector}`}
            >
              <div className="flex items-center justify-between">
                <span className="text-xs font-mono font-bold text-foreground truncate">
                  {se.sector}
                </span>
                <span className="text-xs text-muted-foreground font-mono ml-2 flex-shrink-0">
                  {se.position_count} pos
                </span>
              </div>
              <ExposureBar exposurePct={se.exposure_pct} limitPct={sectorLimitPct} />
              <div className="flex justify-between text-xs font-mono text-muted-foreground">
                <span>{rupee(se.total_value)}</span>
                <span className={text}>{se.exposure_pct.toFixed(1)}% of equity</span>
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

// ── Active Configuration Section (editable) ───────────────────────────────────

/** True only when the API has responded and PortfolioConfig failed to load. */
function isDefaultsOnly(configResponse: PortfolioConfigResponse | undefined): boolean {
  return configResponse !== undefined && !configResponse.loaded;
}

/**
 * Single editable config row.
 * Mutable fields show a pencil icon on hover and an inline text input when editing.
 * Non-mutable fields are always read-only.
 */
function ConfigRow({
  label,
  field,
  displayValue,
  rawValue,
  fieldKind,
  isOverridden,
  isEditing,
  onStartEdit,
  onSave,
  onCancel,
  isSaving,
  saveError,
  usingDefaults,
}: {
  label: string;
  field: string | null; // null = not editable
  displayValue: string;
  rawValue?: number;
  fieldKind?: FieldKind;
  isOverridden: boolean;
  isEditing: boolean;
  onStartEdit: () => void;
  onSave: (apiValue: number) => void;
  onCancel: () => void;
  isSaving: boolean;
  saveError: string | null;
  usingDefaults: boolean;
}) {
  const [inputValue, setInputValue] = useState("");
  const [localError, setLocalError] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const mutable = field !== null && fieldKind !== undefined;

  // Populate input with current value when editing starts
  useEffect(() => {
    if (isEditing && fieldKind !== undefined && rawValue !== undefined) {
      const display = toDisplayValue(fieldKind, rawValue);
      setInputValue(display);
      setLocalError(null);
      // Focus next tick (after DOM renders)
      setTimeout(() => inputRef.current?.focus(), 10);
    }
  }, [isEditing, fieldKind, rawValue]);

  const handleSave = useCallback(() => {
    if (!fieldKind) return;
    const validationError = validateInput(fieldKind, inputValue);
    if (validationError) {
      setLocalError(validationError);
      return;
    }
    const apiValue = toApiValue(fieldKind, inputValue);
    if (apiValue === null) {
      setLocalError("Invalid value");
      return;
    }
    setLocalError(null);
    onSave(apiValue);
  }, [fieldKind, inputValue, onSave]);

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Enter") handleSave();
    if (e.key === "Escape") {
      setLocalError(null);
      onCancel();
    }
  };

  const errorToShow = saveError || localError;

  return (
    <div className="space-y-0.5 group" data-testid={field ? `config-field-${field}` : undefined}>
      <div className="text-xs font-mono uppercase tracking-wider text-muted-foreground flex items-center gap-1">
        {label}
        {isOverridden && (
          <span
            className="inline-flex items-center gap-0.5 rounded border border-blue-500/50 bg-blue-500/10 px-1 py-px text-[9px] font-mono uppercase tracking-wide text-blue-400 leading-none"
            data-testid={`badge-override-${field}`}
            title="Session override — resets when server restarts"
          >
            session
          </span>
        )}
      </div>

      {isEditing ? (
        <div className="space-y-1">
          <div className="flex items-center gap-1">
            <input
              ref={inputRef}
              type={fieldKind === "int" ? "number" : "text"}
              step={fieldKind === "int" ? 1 : undefined}
              value={inputValue}
              onChange={(e) => {
                setInputValue(e.target.value);
                setLocalError(null);
              }}
              onKeyDown={handleKeyDown}
              disabled={isSaving}
              className={`w-full rounded border px-2 py-1 text-sm font-mono bg-background focus:outline-none focus:ring-1 focus:ring-primary/50 ${
                errorToShow
                  ? "border-red-500/70 focus:ring-red-500/50"
                  : "border-border/70"
              } disabled:opacity-50`}
              data-testid={`input-config-${field}`}
              aria-label={`Edit ${label}`}
            />
            <button
              onClick={handleSave}
              disabled={isSaving}
              className="flex-shrink-0 rounded border border-green-500/40 bg-green-500/10 p-1 text-green-400 hover:bg-green-500/20 disabled:opacity-50"
              title="Save"
              data-testid={`button-save-${field}`}
            >
              {isSaving ? (
                <RefreshCcw className="h-3 w-3 animate-spin" />
              ) : (
                <Check className="h-3 w-3" />
              )}
            </button>
            <button
              onClick={() => { setLocalError(null); onCancel(); }}
              disabled={isSaving}
              className="flex-shrink-0 rounded border border-border/40 bg-card p-1 text-muted-foreground hover:text-foreground disabled:opacity-50"
              title="Cancel"
              data-testid={`button-cancel-${field}`}
            >
              <X className="h-3 w-3" />
            </button>
          </div>
          {errorToShow && (
            <p className="text-xs text-red-400 font-mono" data-testid={`error-config-${field}`}>
              {errorToShow}
            </p>
          )}
          {fieldKind === "pct" && (
            <p className="text-[10px] text-muted-foreground font-mono">Enter a percentage, e.g. 20 for 20%</p>
          )}
        </div>
      ) : (
        <div className="flex items-center gap-1.5 min-h-[28px]">
          <span className={`text-sm font-mono font-bold tabular-nums ${isOverridden ? "text-blue-300" : "text-foreground"}`}>
            {displayValue}
            {usingDefaults && !isOverridden && (
              <span className="ml-1 text-yellow-500/70 font-normal text-xs">(dflt)</span>
            )}
          </span>
          {mutable && !isEditing && (
            <button
              onClick={onStartEdit}
              className="opacity-0 group-hover:opacity-100 transition-opacity rounded p-0.5 text-muted-foreground hover:text-foreground hover:bg-accent/50"
              title={`Edit ${label}`}
              data-testid={`button-edit-${field}`}
            >
              <Pencil className="h-3 w-3" />
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function ActiveConfigSection({
  configResponse,
  isLoading,
  onRefetch,
}: {
  configResponse: PortfolioConfigResponse | undefined;
  isLoading: boolean;
  onRefetch: () => void;
}) {
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [editingField, setEditingField] = useState<string | null>(null);
  const [fieldSaveError, setFieldSaveError] = useState<string | null>(null);

  const cfg = configResponse?.config ?? {};
  const overriddenFields = new Set<string>(configResponse?.overridden_fields ?? []);
  const usingDefaults = isDefaultsOnly(configResponse);

  // PATCH mutation — saves a single field override.
  // Uses raw fetch instead of apiJson so we can capture field_errors from 422 responses.
  const patchMutation = useMutation<PatchConfigResponse, PatchConfigError, Record<string, number>>({
    mutationFn: async (body) => {
      const url = `${API_BASE}/portfolio/config`;
      const res = await fetch(url, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      let data: any;
      try {
        data = await res.json();
      } catch {
        throw { error: `HTTP ${res.status}: invalid JSON response` } satisfies PatchConfigError;
      }
      if (!res.ok) {
        throw { error: data?.error ?? `HTTP ${res.status}`, field_errors: data?.field_errors } satisfies PatchConfigError;
      }
      return data as PatchConfigResponse;
    },
    onSuccess: () => {
      setEditingField(null);
      setFieldSaveError(null);
      // Invalidate so the GET re-fetches with the fresh overrides
      queryClient.invalidateQueries({ queryKey: ["portfolio-config"] });
      onRefetch();
    },
    onError: (err) => {
      // Try to pull a helpful message from field_errors first
      const fieldErr = editingField && err.field_errors?.[editingField];
      setFieldSaveError(fieldErr || err.error || "Save failed");
    },
  });

  // DELETE mutation — clears all overrides
  const clearMutation = useMutation<{ ok: boolean }, Error>({
    mutationFn: () =>
      apiJson("/portfolio/config/overrides", { method: "DELETE" }) as Promise<{ ok: boolean }>,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["portfolio-config"] });
      onRefetch();
    },
  });

  const handleStartEdit = useCallback((field: string) => {
    setEditingField(field);
    setFieldSaveError(null);
    patchMutation.reset();
  }, [patchMutation]);

  const handleSave = useCallback((field: string, apiValue: number) => {
    setFieldSaveError(null);
    patchMutation.mutate({ [field]: apiValue });
  }, [patchMutation]);

  const handleCancel = useCallback(() => {
    setEditingField(null);
    setFieldSaveError(null);
    patchMutation.reset();
  }, [patchMutation]);

  const pctFmt = (v: number | undefined) =>
    v !== undefined ? `${(v * 100).toFixed(1)}%` : "—";
  const moneyFmt = (v: number | undefined) =>
    v !== undefined
      ? `₹${Number(v).toLocaleString("en-IN", { minimumFractionDigits: 0 })}`
      : "—";
  const numFmt = (v: number | undefined) =>
    v !== undefined ? String(v) : "—";
  const secFmt = (v: number | undefined) =>
    v !== undefined ? `${v}s` : "—";
  const boolFmt = (v: boolean | undefined) =>
    v === undefined ? "—" : v ? "YES" : "NO";

  interface RowDef {
    label: string;
    group: string;
    field: string | null;
    displayValue: string;
    rawValue?: number;
    fieldKind?: FieldKind;
  }

  const rows: RowDef[] = [
    // Positions & Orders
    { group: "Positions & Orders", label: "Max Open Positions",     field: "max_open_positions",           displayValue: numFmt(cfg.max_open_positions),           rawValue: cfg.max_open_positions,           fieldKind: "int"   },
    { group: "Positions & Orders", label: "Max Pending Orders",     field: "max_pending_orders",           displayValue: numFmt(cfg.max_pending_orders),           rawValue: cfg.max_pending_orders,           fieldKind: "int"   },
    // Loss & Drawdown
    { group: "Loss & Drawdown",    label: "Daily Loss Cap",         field: "max_daily_loss_pct",           displayValue: pctFmt(cfg.max_daily_loss_pct),           rawValue: cfg.max_daily_loss_pct,           fieldKind: "pct"   },
    { group: "Loss & Drawdown",    label: "Drawdown Halt",          field: "max_drawdown_pct",             displayValue: pctFmt(cfg.max_drawdown_pct),             rawValue: cfg.max_drawdown_pct,             fieldKind: "pct"   },
    { group: "Loss & Drawdown",    label: "Max Capital / Strategy", field: "max_capital_per_strategy_pct", displayValue: pctFmt(cfg.max_capital_per_strategy_pct), rawValue: cfg.max_capital_per_strategy_pct, fieldKind: "pct"   },
    // Order Sizing
    { group: "Order Sizing",       label: "Min Order Size",         field: "min_order_value",              displayValue: moneyFmt(cfg.min_order_value),            rawValue: cfg.min_order_value,              fieldKind: "money" },
    { group: "Order Sizing",       label: "Max Order Size",         field: "max_order_value",              displayValue: moneyFmt(cfg.max_order_value),            rawValue: cfg.max_order_value,              fieldKind: "money" },
    { group: "Order Sizing",       label: "Risk per Trade",         field: "default_risk_per_trade_pct",   displayValue: pctFmt(cfg.default_risk_per_trade_pct),   rawValue: cfg.default_risk_per_trade_pct,   fieldKind: "pct"   },
    { group: "Order Sizing",       label: "AI Confidence Sizing",   field: null,                           displayValue: boolFmt(cfg.use_ai_confidence_sizing) },
    { group: "Order Sizing",       label: "AI Confidence Min",      field: null,                           displayValue: pctFmt(cfg.ai_confidence_min) },
    // Exposure Limits
    { group: "Exposure Limits",    label: "Instrument Limit",       field: "max_instrument_exposure_pct",  displayValue: pctFmt(cfg.max_instrument_exposure_pct),  rawValue: cfg.max_instrument_exposure_pct,  fieldKind: "pct"   },
    { group: "Exposure Limits",    label: "Sector Limit",           field: "max_sector_exposure_pct",      displayValue: pctFmt(cfg.max_sector_exposure_pct),      rawValue: cfg.max_sector_exposure_pct,      fieldKind: "pct"   },
    { group: "Exposure Limits",    label: "Strategy Limit",         field: "max_strategy_exposure_pct",    displayValue: pctFmt(cfg.max_strategy_exposure_pct),    rawValue: cfg.max_strategy_exposure_pct,    fieldKind: "pct"   },
    { group: "Exposure Limits",    label: "Portfolio Limit",        field: "max_portfolio_exposure_pct",   displayValue: pctFmt(cfg.max_portfolio_exposure_pct),   rawValue: cfg.max_portfolio_exposure_pct,   fieldKind: "pct"   },
    { group: "Exposure Limits",    label: "Cash Reserve",           field: "cash_reserve_pct",             displayValue: pctFmt(cfg.cash_reserve_pct),             rawValue: cfg.cash_reserve_pct,             fieldKind: "pct"   },
    // Capital (read-only)
    { group: "Capital",            label: "Initial Capital",        field: null,                           displayValue: moneyFmt(cfg.initial_capital) },
    // Staleness & Intervals (read-only)
    { group: "Staleness & Intervals", label: "Stale State",         field: null,                           displayValue: secFmt(cfg.stale_state_threshold_s) },
    { group: "Staleness & Intervals", label: "Stale Broker",        field: null,                           displayValue: secFmt(cfg.stale_broker_threshold_s) },
    { group: "Staleness & Intervals", label: "Stale Price",         field: null,                           displayValue: secFmt(cfg.stale_price_threshold_s) },
    { group: "Staleness & Intervals", label: "Reconciliation",      field: null,                           displayValue: secFmt(cfg.reconciliation_interval_s) },
    { group: "Staleness & Intervals", label: "Snapshot Interval",   field: null,                           displayValue: secFmt(cfg.snapshot_interval_s) },
    { group: "Staleness & Intervals", label: "Allocation TTL",      field: null,                           displayValue: secFmt(cfg.allocation_ttl_s) },
  ];

  const groups = Array.from(new Set(rows.map((r) => r.group)));
  const hasOverrides = overriddenFields.size > 0;

  return (
    <Card className="bg-card/50 border-border/50" data-testid="section-active-config">
      <CardHeader className="pb-0 pt-4 px-4">
        <CardTitle
          className="text-sm font-mono uppercase tracking-widest text-muted-foreground flex items-center gap-2 cursor-pointer select-none"
          onClick={() => setOpen((o) => !o)}
          data-testid="toggle-active-config"
        >
          {open ? (
            <ChevronDown className="h-3.5 w-3.5" />
          ) : (
            <ChevronRight className="h-3.5 w-3.5" />
          )}
          <Settings className="h-3.5 w-3.5" />
          Active Configuration
          {isLoading && (
            <span className="ml-2 text-xs font-normal text-muted-foreground normal-case">Loading…</span>
          )}
          {!isLoading && usingDefaults && (
            <>
              <span className="ml-1 text-yellow-500/80 text-xs font-normal">(default)</span>
              <span className="ml-auto flex items-center gap-1 text-yellow-400 text-xs font-normal normal-case">
                <AlertTriangle className="h-3 w-3" />
                Using hardcoded defaults
              </span>
            </>
          )}
          {!isLoading && hasOverrides && (
            <span className="ml-auto flex items-center gap-1 text-blue-400 text-xs font-normal normal-case">
              <Activity className="h-3 w-3" />
              {overriddenFields.size} session override{overriddenFields.size !== 1 ? "s" : ""}
            </span>
          )}
        </CardTitle>
      </CardHeader>
      {open && (
        <CardContent className="p-4 pt-3 space-y-4">
          {/* Default-fallback warning — only shown after a confirmed load failure */}
          {usingDefaults && (
            <div className="flex items-start gap-2 rounded border border-yellow-500/40 bg-yellow-500/10 px-3 py-2">
              <AlertTriangle className="h-3.5 w-3.5 text-yellow-400 flex-shrink-0 mt-0.5" />
              <p className="text-xs font-mono text-yellow-400">
                PortfolioConfig failed to load — values shown are hardcoded defaults, not live config.
                {configResponse?.error && (
                  <span className="block text-muted-foreground mt-0.5 truncate" title={configResponse.error}>
                    {configResponse.error.slice(0, 160)}
                  </span>
                )}
              </p>
            </div>
          )}

          {/* Session-override info banner */}
          {hasOverrides && (
            <div
              className="flex items-start gap-2 rounded border border-blue-500/40 bg-blue-500/10 px-3 py-2"
              data-testid="banner-session-overrides"
            >
              <Activity className="h-3.5 w-3.5 text-blue-400 flex-shrink-0 mt-0.5" />
              <div className="flex-1 min-w-0">
                <p className="text-xs font-mono text-blue-400">
                  {overriddenFields.size} field{overriddenFields.size !== 1 ? "s" : ""} overridden
                  this session — resets when the server restarts.
                  Values marked <span className="font-bold">session</span> are active in-memory overrides.
                </p>
              </div>
              <button
                onClick={() => clearMutation.mutate()}
                disabled={clearMutation.isPending}
                className="flex-shrink-0 flex items-center gap-1 rounded border border-blue-500/40 bg-blue-500/10 px-2 py-1 text-xs font-mono text-blue-400 hover:bg-blue-500/20 disabled:opacity-50"
                title="Clear all session overrides"
                data-testid="button-clear-overrides"
              >
                {clearMutation.isPending ? (
                  <RefreshCcw className="h-3 w-3 animate-spin" />
                ) : (
                  <RotateCcw className="h-3 w-3" />
                )}
                Reset all
              </button>
            </div>
          )}

          {/* Edit tip — only shown when no field is being edited */}
          {!editingField && !usingDefaults && (
            <p className="text-xs text-muted-foreground font-mono">
              <Pencil className="h-3 w-3 inline mr-1 opacity-60" />
              Hover a limit row and click the pencil icon to edit it live. Overrides persist until the server restarts.
            </p>
          )}

          {/* Grouped rows */}
          {groups.map((group) => {
            const groupRows = rows.filter((r) => r.group === group);
            return (
              <div key={group}>
                <div className="text-xs font-mono uppercase tracking-widest text-muted-foreground/60 mb-2 border-b border-border/30 pb-1">
                  {group}
                </div>
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-x-6 gap-y-3">
                  {groupRows.map(({ label, field, displayValue, rawValue, fieldKind }) => {
                    const isOverridden = field !== null && overriddenFields.has(field);
                    const isEditing = editingField === field;
                    const isSaving = patchMutation.isPending && isEditing;
                    const saveError = isEditing ? fieldSaveError : null;
                    return (
                      <ConfigRow
                        key={label}
                        label={label}
                        field={field}
                        displayValue={displayValue}
                        rawValue={rawValue}
                        fieldKind={fieldKind}
                        isOverridden={isOverridden}
                        isEditing={isEditing}
                        onStartEdit={() => field && handleStartEdit(field)}
                        onSave={(v) => field && handleSave(field, v)}
                        onCancel={handleCancel}
                        isSaving={isSaving}
                        saveError={saveError}
                        usingDefaults={usingDefaults}
                      />
                    );
                  })}
                </div>
              </div>
            );
          })}

          {/* Footer */}
          {configResponse && (
            <div className="text-xs font-mono text-muted-foreground pt-1 border-t border-border/30 flex flex-wrap gap-x-4">
              <span>
                Fetched:{" "}
                {new Date(configResponse.fetched_at).toLocaleTimeString("en-IN", {
                  hour: "2-digit",
                  minute: "2-digit",
                  second: "2-digit",
                })}
              </span>
              {cfg.portfolio_id && (
                <span>Portfolio: <span className="text-foreground">{cfg.portfolio_id}</span></span>
              )}
              {cfg.base_currency && (
                <span>Currency: <span className="text-foreground">{cfg.base_currency}</span></span>
              )}
              {cfg.enabled !== undefined && (
                <span>
                  Enabled:{" "}
                  <span className={cfg.enabled ? "text-green-400" : "text-red-400"}>
                    {cfg.enabled ? "YES" : "NO"}
                  </span>
                </span>
              )}
            </div>
          )}
        </CardContent>
      )}
    </Card>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function PortfolioLive() {
  const queryClient = useQueryClient();

  const snapshotQuery = useQuery<PortfolioSnapshot>({
    queryKey: ["portfolio-snapshot"],
    queryFn: () => apiJson("/portfolio/snapshot"),
    refetchInterval: REFRESH_INTERVAL,
    staleTime: REFRESH_INTERVAL / 2,
  });

  const healthQuery = useQuery<PortfolioHealth>({
    queryKey: ["portfolio-health"],
    queryFn: () => apiJson("/portfolio/health"),
    refetchInterval: REFRESH_INTERVAL,
    staleTime: REFRESH_INTERVAL / 2,
  });

  const configQuery = useQuery<PortfolioConfigResponse>({
    queryKey: ["portfolio-config"],
    queryFn: () => apiJson("/portfolio/config"),
    // Align with health/snapshot cadence so limit changes after an API restart
    // are visible within one REFRESH_INTERVAL cycle, not up to 4 minutes later.
    refetchInterval: REFRESH_INTERVAL,
    staleTime: REFRESH_INTERVAL / 2,
  });

  const handleConfigRefetch = useCallback(() => {
    configQuery.refetch();
  }, [configQuery]);

  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  useEffect(() => {
    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
    };
  }, []);

  const snap = snapshotQuery.data;
  const health = healthQuery.data;

  // ── Recovery invalidation ──────────────────────────────────────────────────
  //
  // When the health endpoint transitions from an outage status (UNREACHABLE,
  // UNKNOWN, DOWN, HALTED) back to HEALTHY, immediately invalidate both the
  // snapshot and config queries so operators see fresh data right away instead
  // of waiting up to 15 s for the next automatic poll cycle.
  const prevHealthStatusRef = useRef<string | undefined>(undefined);
  useEffect(() => {
    const currentStatus = health?.status;
    const prevStatus = prevHealthStatusRef.current;
    const wasOutage =
      prevStatus === "UNREACHABLE" ||
      prevStatus === "UNKNOWN" ||
      prevStatus === "DOWN" ||
      prevStatus === "HALTED";
    if (wasOutage && currentStatus === "HEALTHY") {
      queryClient.invalidateQueries({ queryKey: ["portfolio-snapshot"] });
      queryClient.invalidateQueries({ queryKey: ["portfolio-config"] });
    }
    prevHealthStatusRef.current = currentStatus;
  }, [health?.status, queryClient]);

  const isLoading = snapshotQuery.isLoading && !snap;
  const isFetching = snapshotQuery.isFetching || healthQuery.isFetching || configQuery.isFetching;
  const error = snapshotQuery.error as Error | null;

  // When BOTH queries fail simultaneously (e.g. full server outage), suppress the
  // individual banners and show a single consolidated "API server unreachable" banner
  // so operators receive one clear action-point instead of two conflicting messages.
  const bothFailed = snapshotQuery.isError && healthQuery.isError;

  // When the health endpoint is completely unreachable (network error / server down),
  // show UNREACHABLE so operators see a clear signal instead of an endless loading spinner.
  const overallStatus =
    healthQuery.isError && !health
      ? "UNREACHABLE"
      : health?.status ?? snap?.status ?? "UNKNOWN";
  const isAlert =
    overallStatus === "DEGRADED" ||
    overallStatus === "HALTED" ||
    overallStatus === "DOWN" ||
    overallStatus === "UNREACHABLE";

  const instrumentLimitPct = snap?.instrument_limit_pct ?? 20.0;
  const sectorLimitPct = snap?.sector_limit_pct ?? 35.0;
  const sectorExposures = snap?.sector_exposures ?? [];
  const exposureWarnings = snap?.exposure_warnings ?? [];
  /** true when at least one warning has severity === "CRITICAL" */
  const hasCriticalWarning = exposureWarnings.some((w) => w.severity === "CRITICAL");
  /** true = limits came from PortfolioConfig; false = hardcoded defaults were used */
  const limitsFromConfig = snap?.limits_from_config ?? true;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center gap-4">
          <div className="h-8 w-8 border-4 border-primary border-t-transparent rounded-full animate-spin" />
          <p className="text-muted-foreground font-mono text-sm">LOADING PORTFOLIO…</p>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6 overflow-y-auto h-full" data-testid="page-portfolio-live">
      <DataFreshnessBar variant="scan" />
      {/* ── Header ─────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-2xl font-bold font-mono flex items-center gap-2">
            <PieChart className="h-6 w-6 text-primary" />
            PORTFOLIO
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Live equity, positions, and P&amp;L — paper trading only.
            Refreshes every {REFRESH_INTERVAL / 1000}s.
          </p>
        </div>
        <div className="flex items-center gap-3">
          <StatusBadge status={overallStatus} />
          <button
            onClick={() => {
              snapshotQuery.refetch();
              healthQuery.refetch();
              configQuery.refetch();
            }}
            disabled={isFetching}
            className="flex items-center gap-2 rounded-md border border-border bg-card px-3 py-1.5 text-sm font-mono hover:bg-accent disabled:opacity-50"
            data-testid="button-refresh-portfolio"
          >
            <RefreshCcw className={`h-4 w-4 ${isFetching ? "animate-spin" : ""}`} />
            {isFetching ? "REFRESHING…" : "REFRESH"}
          </button>
        </div>
      </div>

      {/* Snapshot timestamp */}
      {snap?.snapshotted_at && (
        <div className="text-xs font-mono text-muted-foreground" data-testid="text-snapshot-ts">
          Snapshot:{" "}
          {new Date(snap.snapshotted_at).toLocaleTimeString("en-IN", {
            hour: "2-digit",
            minute: "2-digit",
            second: "2-digit",
          })}
          {snap.paper_mode && (
            <span className="ml-2 rounded border border-blue-500/40 bg-blue-500/10 px-1.5 py-0.5 text-blue-400">
              PAPER
            </span>
          )}
        </div>
      )}

      {/* ── Consolidated banner — both snapshot AND health failed (full outage) ── */}
      {bothFailed && (
        <div
          className="flex items-start gap-3 rounded-md border border-red-500/40 bg-red-500/10 p-4"
          data-testid="banner-server-unreachable"
        >
          <AlertTriangle className="h-5 w-5 text-red-400 flex-shrink-0 mt-0.5" />
          <div>
            <p className="font-mono font-bold text-red-400 text-sm">
              API server unreachable
            </p>
            <p className="text-xs text-muted-foreground font-mono mt-1">
              Both the portfolio snapshot and the health endpoint could not be reached.
              Check that the API server is running — the dashboard will retry every{" "}
              {REFRESH_INTERVAL / 1000}s.
            </p>
          </div>
        </div>
      )}

      {/* ── Alert banner for DEGRADED / HALTED (only when not a full outage) ── */}
      {!bothFailed && isAlert && (
        <div
          className="flex items-start gap-3 rounded-md border border-red-500/40 bg-red-500/10 p-4"
          data-testid="banner-portfolio-alert"
        >
          <AlertTriangle className="h-5 w-5 text-red-400 flex-shrink-0 mt-0.5" />
          <div>
            <p className="font-mono font-bold text-red-400 text-sm">
              Portfolio status: {overallStatus}
            </p>
            {health?.failure_reason && (
              <p className="text-sm text-muted-foreground mt-1">{health.failure_reason}</p>
            )}
            {(health?.unresolved_discrepancies ?? 0) > 0 && (
              <p className="text-sm text-muted-foreground mt-1">
                {health!.unresolved_discrepancies} unresolved reconciliation discrepanc
                {health!.unresolved_discrepancies === 1 ? "y" : "ies"} — check Automation Health.
              </p>
            )}
          </div>
        </div>
      )}

      {/* Error banner — snapshot fetch failed (only when health is still reachable) */}
      {!bothFailed && error && !snap && (
        <div
          className="flex items-start gap-3 rounded-md border border-yellow-500/40 bg-yellow-500/10 p-4"
          data-testid="banner-snapshot-error"
        >
          <AlertTriangle className="h-5 w-5 text-yellow-400 flex-shrink-0" />
          <p className="text-sm text-yellow-400">{error.message}</p>
        </div>
      )}

      {/* ── Summary stat cards ──────────────────────────────────────────── */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
        <StatCard
          label="Equity"
          value={rupee(snap?.equity)}
          sub={snap ? `started at ${rupee(snap.initial_capital)}` : undefined}
          icon={DollarSign}
        />
        <StatCard
          label="Cash / Buying Power"
          value={rupee(snap?.cash)}
          sub={`invested ${rupee(snap?.invested_value)}`}
          icon={Wallet}
        />
        <StatCard
          label="Unrealised P&L"
          value={snap ? `${snap.unrealised_pnl >= 0 ? "+" : ""}${rupee(snap.unrealised_pnl)}` : "—"}
          valueClass={pnlColor(snap?.unrealised_pnl)}
          sub={snap ? pct(snap.unrealised_pnl / Math.max(snap.invested_value, 1) * 100) + " of invested" : undefined}
          icon={snap && snap.unrealised_pnl >= 0 ? TrendingUp : TrendingDown}
        />
        <StatCard
          label="Realised P&L Today"
          value={snap ? `${snap.realised_pnl_today >= 0 ? "+" : ""}${rupee(snap.realised_pnl_today)}` : "—"}
          valueClass={pnlColor(snap?.realised_pnl_today)}
          sub={snap ? `${snap.closed_positions_today} position${snap.closed_positions_today !== 1 ? "s" : ""} closed` : undefined}
          icon={BarChart2}
        />
        <StatCard
          label="Drawdown"
          value={snap ? `-${rupee(snap.drawdown_amount)}` : "—"}
          sub={snap ? `${snap.drawdown_pct.toFixed(1)}% from peak ${rupee(snap.peak_equity)}` : undefined}
          valueClass={
            (snap?.drawdown_pct ?? 0) >= 10
              ? "text-red-400"
              : (snap?.drawdown_pct ?? 0) >= 5
              ? "text-yellow-400"
              : "text-green-400"
          }
          icon={TrendingDown}
        />
      </div>

      {/* ── Drawdown visual bar ─────────────────────────────────────────── */}
      {snap && (
        <Card className="bg-card/50 border-border/50">
          <CardContent className="p-4 space-y-2">
            <div className="flex items-center justify-between text-xs font-mono text-muted-foreground uppercase tracking-wider">
              <span>Drawdown from Peak</span>
              <span>
                {rupee(snap.equity)} / {rupee(snap.peak_equity)} peak
              </span>
            </div>
            <DrawdownBar pct={snap.drawdown_pct} />
          </CardContent>
        </Card>
      )}

      {/* ── Open Positions ──────────────────────────────────────────────── */}
      <Card className="bg-card/50 border-border/50">
        <CardHeader className="pb-2 pt-4 px-4">
          <CardTitle className="text-sm font-mono uppercase tracking-widest text-muted-foreground flex items-center justify-between">
            <span>Open Positions</span>
            <span className="flex items-center gap-2">
              {exposureWarnings.length > 0 && (
                <span
                  className={`inline-flex items-center gap-1 rounded border px-2 py-0.5 text-xs font-mono ${
                    hasCriticalWarning
                      ? "border-red-500/40 bg-red-500/10 text-red-400"
                      : "border-yellow-500/40 bg-yellow-500/10 text-yellow-400"
                  }`}
                  data-testid="badge-exposure-warnings-count"
                >
                  <ShieldAlert className="h-3 w-3" />
                  {exposureWarnings.length} limit warning{exposureWarnings.length !== 1 ? "s" : ""}
                </span>
              )}
              <span className="text-foreground font-bold" data-testid="count-open-positions">
                {snap?.open_position_count ?? 0}
              </span>
            </span>
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {/* Exposure warning banner — inside the card, above the table */}
          {exposureWarnings.length > 0 && (
            <div className="px-4 pt-3">
              <ExposureWarningBanner warnings={exposureWarnings} />
            </div>
          )}
          {!snap || snap.open_positions.length === 0 ? (
            <div className="px-4 py-8 text-center text-sm text-muted-foreground font-mono">
              NO OPEN POSITIONS
            </div>
          ) : (
            <div className="overflow-x-auto mt-3">
              <table className="w-full text-sm" data-testid="table-positions">
                <thead>
                  <tr className="border-b border-border/60 text-xs font-mono text-muted-foreground uppercase">
                    <th className="px-3 py-2 text-left">Symbol</th>
                    <th className="px-3 py-2 text-left">Sector</th>
                    <th className="px-3 py-2 text-right">Qty</th>
                    <th className="px-3 py-2 text-right">Avg Price</th>
                    <th className="px-3 py-2 text-right">LTP</th>
                    <th className="px-3 py-2 text-right">Market Value</th>
                    <th className="px-3 py-2 text-right">Unreal. P&L</th>
                    <th className="px-3 py-2 text-right">P&L %</th>
                    <th className="px-3 py-2 text-left">Strategy</th>
                    <th className="px-3 py-2 text-left" title={`Single-stock limit: ${instrumentLimitPct.toFixed(0)}% of equity${!limitsFromConfig ? " (hardcoded default)" : ""}`}>
                      Exposure / Limit
                      {!limitsFromConfig && (
                        <span className="ml-1 text-yellow-500/70 font-normal normal-case">(default)</span>
                      )}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {snap.open_positions.map((pos) => (
                    <PositionRow
                      key={pos.symbol}
                      pos={pos}
                      instrumentLimitPct={instrumentLimitPct}
                    />
                  ))}
                </tbody>
                <tfoot>
                  <tr className="border-t border-border/60 bg-card/30 font-mono text-sm">
                    <td className="px-3 py-2.5 text-muted-foreground font-bold" colSpan={5}>
                      TOTAL
                    </td>
                    <td className="px-3 py-2.5 text-right font-bold">
                      {rupee(snap.invested_value)}
                    </td>
                    <td
                      className={`px-3 py-2.5 text-right font-bold ${pnlColor(snap.unrealised_pnl)}`}
                    >
                      {snap.unrealised_pnl >= 0 ? "+" : ""}
                      {rupee(snap.unrealised_pnl)}
                    </td>
                    <td className="px-3 py-2.5 text-right" />
                    <td className="px-3 py-2.5" />
                    <td className="px-3 py-2.5" />
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
        </CardContent>
      </Card>

      {/* ── Sector Exposure ─────────────────────────────────────────────── */}
      {sectorExposures.length > 0 && (
        <SectorExposureSection
          sectorExposures={sectorExposures}
          sectorLimitPct={sectorLimitPct}
          limitsFromConfig={limitsFromConfig}
        />
      )}

      {/* ── Active Configuration ────────────────────────────────────────── */}
      <ActiveConfigSection
        configResponse={configQuery.data}
        isLoading={configQuery.isLoading && !configQuery.data}
        onRefetch={handleConfigRefetch}
      />

      {/* ── Health details ──────────────────────────────────────────────── */}
      <Card className="bg-card/50 border-border/50">
        <CardHeader className="pb-2 pt-4 px-4">
          <CardTitle className="text-sm font-mono uppercase tracking-widest text-muted-foreground">
            Portfolio Health
          </CardTitle>
        </CardHeader>
        <CardContent className="p-4 pt-0">
          {healthQuery.isError && !health ? (
            <div
              className="flex items-start gap-3 rounded-md border border-red-500/40 bg-red-500/10 p-4"
              data-testid="banner-health-unreachable"
            >
              <AlertTriangle className="h-5 w-5 text-red-400 flex-shrink-0 mt-0.5" />
              <div>
                <p className="font-mono font-bold text-red-400 text-sm">
                  API server unreachable
                </p>
                <p className="text-xs text-muted-foreground font-mono mt-1">
                  {(healthQuery.error as Error)?.message ?? "Could not connect to the portfolio health endpoint."}
                  {" "}— last checked at{" "}
                  {new Date().toLocaleTimeString("en-IN", {
                    hour: "2-digit",
                    minute: "2-digit",
                    second: "2-digit",
                  })}
                </p>
                <p className="text-xs text-muted-foreground font-mono mt-1">
                  The dashboard will retry automatically every {REFRESH_INTERVAL / 1000}s.
                </p>
              </div>
            </div>
          ) : !health ? (
            <p className="text-sm text-muted-foreground font-mono">Loading health…</p>
          ) : (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
              {(
                [
                  ["Initialized",         health.initialized],
                  ["Liveness",            health.liveness],
                  ["Readiness",           health.readiness],
                  ["Auto-Paper Enabled",  health.auto_paper_enabled],
                ] as [string, boolean][]
              ).map(([label, val]) => (
                <div key={label} className="flex items-center gap-2">
                  <span
                    className={`h-2 w-2 rounded-full flex-shrink-0 ${val ? "bg-green-500" : "bg-red-500"}`}
                  />
                  <span className="text-xs text-muted-foreground font-mono">{label}</span>
                  <span className={`text-xs font-mono ml-auto ${val ? "text-green-400" : "text-red-400"}`}>
                    {val ? "YES" : "NO"}
                  </span>
                </div>
              ))}
              {/* Degraded reason rows — one per entry */}
              {(health.degraded_reasons ?? []).length > 0 && (
                <div className="col-span-2 md:col-span-4 space-y-1">
                  {(health.degraded_reasons!).map((reason, i) => (
                    <div key={i} className="flex items-start gap-2">
                      <AlertTriangle className="h-3.5 w-3.5 text-yellow-400 flex-shrink-0 mt-0.5" />
                      <span className="text-xs text-yellow-400 font-mono">{reason}</span>
                    </div>
                  ))}
                </div>
              )}
              {/* Fallback for old API responses that don't include degraded_reasons */}
              {(health.degraded_reasons == null) && health.unresolved_discrepancies > 0 && (
                <div className="flex items-center gap-2 col-span-2 md:col-span-4">
                  <AlertTriangle className="h-3.5 w-3.5 text-yellow-400 flex-shrink-0" />
                  <span className="text-xs text-yellow-400 font-mono">
                    {health.unresolved_discrepancies} unresolved discrepanc
                    {health.unresolved_discrepancies === 1 ? "y" : "ies"}
                  </span>
                </div>
              )}
              {/* Config-limits indicator (explicit flag for old API responses) */}
              {(health.degraded_reasons == null) && health.limits_from_config === false && (
                <div className="flex items-start gap-2 col-span-2 md:col-span-4">
                  <AlertTriangle className="h-3.5 w-3.5 text-yellow-400 flex-shrink-0 mt-0.5" />
                  <span className="text-xs text-yellow-400 font-mono">
                    Exposure limits using hardcoded defaults — check PortfolioConfig import
                  </span>
                </div>
              )}
              {/* Email transport hint — shown when the config-defaults alert fired
                  but no email transport is configured, so the operator knows the
                  alert was only stored in-app and email delivery was silently skipped. */}
              {health.limits_from_config === false && health.email_transport_configured === false && (
                <div
                  className="col-span-2 md:col-span-4 flex items-start gap-2 rounded border border-orange-500/40 bg-orange-500/10 px-3 py-2"
                  data-testid="banner-email-transport-unconfigured"
                >
                  <AlertTriangle className="h-3.5 w-3.5 text-orange-400 flex-shrink-0 mt-0.5" />
                  <p className="text-xs font-mono text-orange-400">
                    <span className="font-bold">Email delivery not configured</span> — the config-defaults alert
                    was stored in-app but no email transport (RESEND_API_KEY or SMTP_HOST) is set, so no
                    email was sent. Add a transport secret to enable email alerts.
                  </p>
                </div>
              )}
              {health.state_freshness_s != null && (
                <div className="col-span-2 md:col-span-4 text-xs text-muted-foreground font-mono">
                  State age: {health.state_freshness_s.toFixed(0)}s
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
