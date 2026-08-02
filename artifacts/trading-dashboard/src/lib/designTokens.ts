/**
 * designTokens.ts — Phase 9.7
 * Single source of truth for all ApexQuant AI design values.
 *
 * Import from here wherever a colour, spacing, typography, or semantic
 * value is needed. Never hard-code hex strings in component files.
 */

// ─── Agent colours (mirrors AgentConfig.ts — kept in sync here) ────────────────
export const AGENT_COLORS = {
  "market-data":        "#3B82F6",   // blue
  research:             "#10B981",   // green
  "market-intelligence":"#8B5CF6",   // purple
  monitoring:           "#F97316",   // orange
  strategy:             "#EF4444",   // red
  risk:                 "#F59E0B",   // amber
  ai:                   "#6366F1",   // indigo
  execution:            "#14B8A6",   // teal
  learning:             "#06B6D4",   // cyan
  operations:           "#6B7280",   // grey
} as const;

export type AgentId = keyof typeof AGENT_COLORS;

// ─── Semantic status colours ───────────────────────────────────────────────────
export const STATUS_COLORS = {
  success:   "#10B981",
  warning:   "#F59E0B",
  error:     "#EF4444",
  critical:  "#EF4444",
  info:      "#3B82F6",
  neutral:   "#6B7280",
  live:      "#10B981",
  stale:     "#F59E0B",
  offline:   "#EF4444",
  unknown:   "#6B7280",
  disabled:  "#374151",
} as const;

export type StatusKey = keyof typeof STATUS_COLORS;

// ─── Financial / P&L colours ──────────────────────────────────────────────────
export const PNL_COLORS = {
  positive: "#10B981",
  negative: "#EF4444",
  neutral:  "#6B7280",
  zero:     "#9CA3AF",
} as const;

// ─── Alert severity colours ────────────────────────────────────────────────────
export const SEVERITY_COLORS: Record<string, string> = {
  critical: "#EF4444",
  high:     "#F97316",
  medium:   "#F59E0B",
  low:      "#3B82F6",
  info:     "#6B7280",
};

export const SEVERITY_BG: Record<string, string> = {
  critical: "rgba(239,68,68,0.12)",
  high:     "rgba(249,115,22,0.12)",
  medium:   "rgba(245,158,11,0.12)",
  low:      "rgba(59,130,246,0.12)",
  info:     "rgba(107,114,128,0.12)",
};

export const SEVERITY_BORDER: Record<string, string> = {
  critical: "rgba(239,68,68,0.30)",
  high:     "rgba(249,115,22,0.30)",
  medium:   "rgba(245,158,11,0.30)",
  low:      "rgba(59,130,246,0.30)",
  info:     "rgba(107,114,128,0.30)",
};

// ─── Surface / background colours ─────────────────────────────────────────────
export const SURFACE = {
  page:      "#0f1420",   // page background
  card:      "#1a1f2e",   // default card background
  cardHover: "#1f2535",   // card hover
  border:    "#2d3348",   // standard border
  borderSub: "#1e2538",   // subtle border
  overlay:   "rgba(0,0,0,0.6)",
} as const;

// ─── Text colours ──────────────────────────────────────────────────────────────
export const TEXT = {
  primary:   "#F9FAFB",
  secondary: "#D1D5DB",
  tertiary:  "#9CA3AF",
  muted:     "#6B7280",
  disabled:  "#4B5563",
  link:      "#60A5FA",
} as const;

// ─── Typography scale (px) ────────────────────────────────────────────────────
export const FONT_SIZE = {
  "2xs": 10,
  xs:    11,
  sm:    12,
  base:  13,
  md:    14,
  lg:    16,
  xl:    18,
  "2xl": 22,
  "3xl": 28,
  "4xl": 36,
} as const;

export const FONT_WEIGHT = {
  normal:    400,
  medium:    500,
  semibold:  600,
  bold:      700,
} as const;

export const LINE_HEIGHT = {
  tight:  1.2,
  normal: 1.5,
  relaxed:1.7,
} as const;

// ─── Spacing scale (px) ───────────────────────────────────────────────────────
export const SPACE = {
  1:  4,
  2:  8,
  3:  12,
  4:  16,
  5:  20,
  6:  24,
  8:  32,
  10: 40,
  12: 48,
} as const;

// ─── Border radius ─────────────────────────────────────────────────────────────
export const RADIUS = {
  sm:   4,
  md:   6,
  lg:   8,
  xl:   12,
  "2xl":16,
  full: 9999,
} as const;

// ─── Score colouring helpers ───────────────────────────────────────────────────
export function scoreColor(score: number): string {
  if (score >= 80) return STATUS_COLORS.success;
  if (score >= 60) return STATUS_COLORS.warning;
  if (score >= 40) return "#F97316";
  return STATUS_COLORS.error;
}

export function scoreBg(score: number): string {
  if (score >= 80) return "rgba(16,185,129,0.12)";
  if (score >= 60) return "rgba(245,158,11,0.12)";
  if (score >= 40) return "rgba(249,115,22,0.12)";
  return "rgba(239,68,68,0.12)";
}

export function pnlColor(value: number): string {
  if (value > 0) return PNL_COLORS.positive;
  if (value < 0) return PNL_COLORS.negative;
  return PNL_COLORS.zero;
}

// ─── Chart palette (for Recharts) ─────────────────────────────────────────────
export const CHART_COLORS = [
  "#6366F1", "#10B981", "#F59E0B", "#3B82F6",
  "#EF4444", "#8B5CF6", "#06B6D4", "#F97316",
  "#14B8A6", "#EC4899",
];

// ─── Z-index scale ─────────────────────────────────────────────────────────────
export const Z = {
  base:    0,
  card:    10,
  overlay: 100,
  modal:   200,
  toast:   300,
} as const;

// ─── Transition durations ──────────────────────────────────────────────────────
export const TRANSITION = {
  fast:   "150ms ease",
  normal: "200ms ease",
  slow:   "300ms ease",
} as const;

// ─── Breakpoints (px) ─────────────────────────────────────────────────────────
export const BP = {
  sm:  640,
  md:  768,
  lg:  1024,
  xl:  1280,
  "2xl": 1536,
} as const;
