/**
 * Lightweight SVG chart primitives — no recharts dependency.
 * Adapted from the OmniRoute design system for use in NSE Trader panels.
 */
import { useId } from "react";
import { toneRgb, toneRgbSoft, type Tone } from "@/lib/theme";
import { cn } from "@/lib/utils";

// ── helpers ──────────────────────────────────────────────────────

function buildPath(data: number[], w: number, h: number, pad = 6): string {
  if (data.length === 0) return "";
  const min = Math.min(...data);
  const max = Math.max(...data);
  const range = max - min || 1;
  const stepX = (w - pad * 2) / Math.max(1, data.length - 1);
  return data
    .map((d, i) => {
      const x = pad + i * stepX;
      const y = pad + (h - pad * 2) * (1 - (d - min) / range);
      return `${i === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    })
    .join(" ");
}

function buildArea(data: number[], w: number, h: number, pad = 6): string {
  const line = buildPath(data, w, h, pad);
  if (!line) return "";
  const stepX = (w - pad * 2) / Math.max(1, data.length - 1);
  const baseY = h - pad;
  const startX = pad;
  const endX = pad + (data.length - 1) * stepX;
  return `${line} L ${endX.toFixed(2)} ${baseY} L ${startX.toFixed(2)} ${baseY} Z`;
}

// ── AreaChart ────────────────────────────────────────────────────

interface AreaChartProps {
  data: number[];
  tone?: Tone;
  labels?: string[];
  showAxis?: boolean;
  height?: number;
  className?: string;
}

export function AreaChart({
  data,
  tone = "primary",
  labels,
  showAxis = true,
  height = 180,
  className,
}: AreaChartProps) {
  const uid = useId().replace(/:/g, "");
  const w = 640;
  const h = height;
  const linePath = buildPath(data, w, h, 16);
  const areaPath = buildArea(data, w, h, 16);
  const max = Math.max(...data);
  const min = Math.min(...data);

  return (
    <div className={cn("w-full", className)}>
      <svg
        viewBox={`0 0 ${w} ${h}`}
        className="w-full"
        preserveAspectRatio="none"
        style={{ height }}
      >
        <defs>
          <linearGradient id={`area-${uid}`} x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%"   stopColor={toneRgbSoft(tone, 0.4)} />
            <stop offset="100%" stopColor={toneRgbSoft(tone, 0)} />
          </linearGradient>
          <linearGradient id={`line-${uid}`} x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%"   stopColor={toneRgb(tone)} />
            <stop offset="100%" stopColor={toneRgb("accent")} />
          </linearGradient>
        </defs>
        {showAxis &&
          [0.25, 0.5, 0.75].map((p) => (
            <line
              key={p}
              x1="16" x2={w - 16}
              y1={16 + (h - 32) * p} y2={16 + (h - 32) * p}
              stroke="hsl(var(--border))"
              strokeDasharray="3 5"
              strokeWidth="1"
              opacity="0.5"
            />
          ))}
        {areaPath && <path d={areaPath} fill={`url(#area-${uid})`} />}
        {linePath && (
          <path
            d={linePath}
            fill="none"
            stroke={`url(#line-${uid})`}
            strokeWidth="2.5"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
        )}
        {data.length > 0 && (() => {
          const stepX = (w - 32) / Math.max(1, data.length - 1);
          const x = 16 + (data.length - 1) * stepX;
          const y =
            16 +
            (h - 32) *
              (1 - (data[data.length - 1] - min) / (max - min || 1));
          return (
            <circle
              cx={x}
              cy={y}
              r="4"
              fill={toneRgb(tone)}
              className="animate-pulse"
            />
          );
        })()}
      </svg>
      {labels && (
        <div className="mt-2 flex justify-between px-1 text-[11px] text-muted-foreground">
          {labels.map((l) => <span key={l}>{l}</span>)}
        </div>
      )}
    </div>
  );
}

// ── Sparkline ────────────────────────────────────────────────────

interface SparklineProps {
  data: number[];
  tone?: Tone;
  width?: number;
  height?: number;
  className?: string;
}

export function Sparkline({
  data,
  tone = "primary",
  width = 80,
  height = 32,
  className,
}: SparklineProps) {
  const linePath = buildPath(data, width, height, 4);
  const isPositive =
    data.length > 1 && data[data.length - 1] >= data[0];

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      className={cn("shrink-0 overflow-visible", className)}
    >
      {linePath && (
        <path
          d={linePath}
          fill="none"
          stroke={isPositive ? toneRgb("success") : toneRgb("danger")}
          strokeWidth="1.8"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      )}
    </svg>
  );
}

// ── BarChart ─────────────────────────────────────────────────────

interface BarChartProps {
  data: Array<{ label: string; value: number; tone?: Tone }>;
  height?: number;
  showValues?: boolean;
  className?: string;
}

export function BarChart({
  data,
  height = 160,
  showValues = true,
  className,
}: BarChartProps) {
  const max = Math.max(...data.map((d) => d.value), 1);
  return (
    <div className={cn("w-full", className)}>
      <div
        className="flex items-end gap-1.5"
        style={{ height }}
      >
        {data.map((d) => {
          const pct = (d.value / max) * 100;
          const tone = d.tone ?? "primary";
          return (
            <div
              key={d.label}
              className="group relative flex flex-1 flex-col items-center gap-1"
            >
              {showValues && (
                <span className="text-[10px] tabular-nums text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity">
                  {d.value}
                </span>
              )}
              <div
                className="w-full rounded-t-md transition-all duration-500"
                style={{
                  height: `${pct}%`,
                  background: toneRgb(tone),
                  opacity: 0.85,
                }}
              />
            </div>
          );
        })}
      </div>
      <div className="mt-1 flex gap-1.5">
        {data.map((d) => (
          <span
            key={d.label}
            className="flex-1 truncate text-center text-[10px] text-muted-foreground"
          >
            {d.label}
          </span>
        ))}
      </div>
    </div>
  );
}

// ── DonutChart ───────────────────────────────────────────────────

interface DonutSlice {
  label: string;
  value: number;
  tone?: Tone;
}

interface DonutChartProps {
  data: DonutSlice[];
  size?: number;
  thickness?: number;
  className?: string;
}

export function DonutChart({
  data,
  size = 120,
  thickness = 20,
  className,
}: DonutChartProps) {
  const total = data.reduce((s, d) => s + d.value, 0) || 1;
  const r = (size - thickness) / 2;
  const cx = size / 2;
  const cy = size / 2;
  const circumference = 2 * Math.PI * r;

  let offset = -0.25 * circumference; // start at 12 o'clock
  const slices = data.map((d) => {
    const dash = (d.value / total) * circumference;
    const gap = circumference - dash;
    const currentOffset = offset;
    offset -= dash;
    return { ...d, dash, gap, offset: currentOffset };
  });

  return (
    <div className={cn("relative inline-flex items-center justify-center", className)}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
        {/* Track */}
        <circle
          cx={cx} cy={cy} r={r}
          fill="none"
          stroke="hsl(var(--border))"
          strokeWidth={thickness}
        />
        {slices.map((s, i) => (
          <circle
            key={i}
            cx={cx} cy={cy} r={r}
            fill="none"
            stroke={toneRgb(s.tone ?? "primary")}
            strokeWidth={thickness}
            strokeDasharray={`${s.dash} ${s.gap}`}
            strokeDashoffset={s.offset}
            strokeLinecap="round"
          />
        ))}
      </svg>
      <span className="absolute font-mono text-[11px] font-semibold tabular-nums text-foreground">
        {data[0]?.value ?? 0}%
      </span>
    </div>
  );
}
