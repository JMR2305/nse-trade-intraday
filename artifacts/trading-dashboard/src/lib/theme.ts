/**
 * Semantic tone system — maps named tones to Tailwind class fragments.
 * Used by Badge, MetricCard, Chart primitives and other omni components.
 * Tones map to the platform's primary/accent/semantic color tokens.
 */

export type Tone =
  | "primary"
  | "secondary"
  | "accent"
  | "success"
  | "warning"
  | "danger"
  | "info"
  | "faint";

export const toneText: Record<Tone, string> = {
  primary:   "text-primary",
  secondary: "text-secondary",
  accent:    "text-accent",
  success:   "text-omni-success",
  warning:   "text-omni-warning",
  danger:    "text-omni-danger",
  info:      "text-omni-info",
  faint:     "text-muted-foreground",
};

export const toneBg: Record<Tone, string> = {
  primary:   "bg-primary",
  secondary: "bg-secondary",
  accent:    "bg-accent",
  success:   "bg-omni-success",
  warning:   "bg-omni-warning",
  danger:    "bg-omni-danger",
  info:      "bg-omni-info",
  faint:     "bg-muted",
};

export const toneSoftBg: Record<Tone, string> = {
  primary:   "bg-primary/10",
  secondary: "bg-secondary/10",
  accent:    "bg-accent/10",
  success:   "bg-omni-success/12",
  warning:   "bg-omni-warning/12",
  danger:    "bg-omni-danger/12",
  info:      "bg-omni-info/12",
  faint:     "bg-muted/60",
};

export const toneRing: Record<Tone, string> = {
  primary:   "ring-primary/40",
  secondary: "ring-secondary/40",
  accent:    "ring-accent/40",
  success:   "ring-omni-success/40",
  warning:   "ring-omni-warning/40",
  danger:    "ring-omni-danger/40",
  info:      "ring-omni-info/40",
  faint:     "ring-border",
};

/** Resolve a tone to a CSS rgb() string for use in SVG fill/stroke. */
export function toneRgb(tone: Tone): string {
  const map: Record<Tone, string> = {
    primary:   "hsl(var(--primary))",
    secondary: "hsl(var(--secondary))",
    accent:    "hsl(var(--accent))",
    success:   "rgb(var(--omni-success))",
    warning:   "rgb(var(--omni-warning))",
    danger:    "rgb(var(--omni-danger))",
    info:      "rgb(var(--omni-info))",
    faint:     "hsl(var(--muted-foreground))",
  };
  return map[tone];
}

export function toneRgbSoft(tone: Tone, alpha = 0.15): string {
  return toneRgb(tone).replace(/^rgb\(([^)]+)\)$/, `rgb($1 / ${alpha})`);
}
