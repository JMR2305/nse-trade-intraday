import { cn } from "@/lib/utils";

interface LogoProps {
  className?: string;
  /** Show the "Apex Global" wordmark beside the symbol. Default: true. */
  showWordmark?: boolean;
  /** Height (and proportional width) of the mountain symbol in px. Default: 28. */
  size?: number;
}

/**
 * Apex Global brand mark.
 *
 * The geometric mountain symbol is an SVG compound path:
 * one large mountain triangle with 4 thin triangular gaps radiating
 * from the apex — creating 5 distinct rising segments.
 *
 * Color tokens
 * ─────────────
 * Light mode : navy  #17395F  (brand primary)
 * Dark mode  : cream #F7F4ED  (readable on dark navy canvas)
 *
 * Both are applied via `currentColor` on the SVG so the wrapping
 * `className` can override with any Tailwind color utility.
 */
export function Logo({ className, showWordmark = true, size = 28 }: LogoProps) {
  // symbol proportions: viewBox "0 0 48 44" → aspect ≈ 1.09 : 1
  const symbolWidth = Math.round(size * 1.09);

  return (
    <div
      className={cn(
        "inline-flex items-center gap-2 select-none",
        "text-[#17395F] dark:text-[#F7F4ED]",
        className,
      )}
    >
      {/* ── Mountain mark ── */}
      <svg
        viewBox="0 0 48 44"
        width={symbolWidth}
        height={size}
        aria-hidden
        focusable="false"
      >
        {/*
          Compound path: mountain triangle M2,42 L24,2 L46,42 Z
          minus 4 thin radial gap triangles (evenodd rule cuts them out).
          Result: 5 solid navy segments separated by transparent slots.
        */}
        <path
          fill="currentColor"
          fillRule="evenodd"
          d="
            M 2,42 L 24,2 L 46,42 Z
            M 11,42 L 13,42 L 24,2 Z
            M 19,42 L 21,42 L 24,2 Z
            M 27,42 L 29,42 L 24,2 Z
            M 35,42 L 37,42 L 24,2 Z
          "
        />
      </svg>

      {/* ── Wordmark ── */}
      {showWordmark && (
        <span
          className="font-semibold tracking-[0.06em] leading-none uppercase whitespace-nowrap"
          style={{ fontSize: Math.max(11, Math.round(size * 0.5)) }}
        >
          Apex Global
        </span>
      )}
    </div>
  );
}

/**
 * Standalone symbol only — convenience alias for collapsed sidebar / icons.
 */
export function ApexSymbol({ size = 28, className }: { size?: number; className?: string }) {
  return <Logo showWordmark={false} size={size} className={className} />;
}
