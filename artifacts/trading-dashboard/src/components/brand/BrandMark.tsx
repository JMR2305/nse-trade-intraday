/**
 * BrandMark — ApexQuant AI geometric mark.
 *
 * SVG structure:
 *  • Two navy triangle "legs" forming the Apex "A" frame
 *  • Three rising bar-chart bars inside the A (navy, currentColor)
 *  • Teal trend line with arrow breaking through the upper-right frame
 *
 * Color strategy:
 *  • A frame + bars : fill="currentColor"
 *    → navy #17395F in light mode (wrapper class text-[#17395F])
 *    → cream #F7F4ED in dark mode  (wrapper class dark:text-[#F7F4ED])
 *  • Trend line + arrow: hardcoded teal #129C8C (readable on both bg)
 */
import { cn } from "@/lib/utils";

interface BrandMarkProps {
  size?: number;
  className?: string;
  /** Override color of the A frame / bars (defaults to theme-adaptive navy/cream). */
  color?: string;
  /** Override teal accent color. */
  accentColor?: string;
}

export function BrandMark({
  size = 32,
  className,
  color,
  accentColor = "#129C8C",
}: BrandMarkProps) {
  // viewBox is 60×56 → width : height ≈ 1.071
  const w = Math.round(size * 1.071);

  return (
    <svg
      viewBox="0 0 60 56"
      width={w}
      height={size}
      aria-hidden
      focusable="false"
      className={cn("shrink-0", className)}
      style={color ? { color } : undefined}
    >
      {/* ── A frame: left leg (triangle) ── */}
      <path fill="currentColor" d="M3,54 L16,54 L30,4 Z" />

      {/* ── A frame: right leg (triangle) ── */}
      <path fill="currentColor" d="M57,54 L44,54 L30,4 Z" />

      {/* ── Rising bar chart bars (navy, inside the A) ── */}
      <rect fill="currentColor" x="20" y="44" width="4" height="10" rx="0.5" />
      <rect fill="currentColor" x="26" y="36" width="4" height="18" rx="0.5" />
      <rect fill="currentColor" x="32" y="28" width="4" height="26" rx="0.5" />

      {/* ── Teal trend line (goes through bars and breaks out upper-right) ── */}
      <polyline
        points="20,50 26,38 32,30 43,18"
        fill="none"
        stroke={accentColor}
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {/* Arrow head at (43,18) pointing NE — polygon computed for the line direction */}
      <polygon points="43,18 42,24 37,20" fill={accentColor} />
    </svg>
  );
}
