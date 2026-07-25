import { cn } from "@/lib/utils";

interface LogoProps {
  className?: string;
  showWordmark?: boolean;
  size?: number;
  wordmark?: string;
}

/**
 * NSE Trader brand mark.
 * Adapts the OmniRoute geometric path mark with the platform's
 * teal / emerald color tokens (uses CSS vars so it respects light/dark).
 */
export function Logo({
  className,
  showWordmark = true,
  size = 28,
  wordmark = "NSE TRADER",
}: LogoProps) {
  return (
    <div className={cn("flex items-center gap-2.5 select-none", className)}>
      <span
        className="relative inline-flex shrink-0"
        style={{ width: size, height: size }}
      >
        <svg
          viewBox="0 0 32 32"
          width={size}
          height={size}
          className="drop-shadow-[0_1px_2px_rgb(0_0_0/0.12)]"
          aria-hidden
        >
          <defs>
            <linearGradient id="logo-grad" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stopColor="hsl(var(--primary))" />
              <stop offset="100%" stopColor="hsl(175,100%,45%)" />
            </linearGradient>
          </defs>
          {/* Background tile */}
          <rect width="32" height="32" rx="8" fill="hsl(var(--background))" />
          <rect width="32" height="32" rx="8" fill="url(#logo-grad)" opacity="0.12" />
          {/* Chart-path mark — same geometry as OmniRoute */}
          <path
            d="M5 22 L12 12 L17 18 L22 11 L27 22"
            fill="none"
            stroke="url(#logo-grad)"
            strokeWidth="2.4"
            strokeLinecap="round"
            strokeLinejoin="round"
          />
          <circle cx="12" cy="12" r="1.8" fill="hsl(var(--primary))" />
          <circle cx="22" cy="11" r="1.8" fill="hsl(175,80%,40%)" />
          <circle cx="5"  cy="22" r="1.4" fill="hsl(var(--primary))" opacity="0.6" />
          <circle cx="27" cy="22" r="1.4" fill="hsl(175,80%,40%)" opacity="0.6" />
        </svg>
      </span>
      {showWordmark && (
        <span className="font-mono font-bold tracking-tight text-[14px] leading-none text-foreground truncate">
          {wordmark}
        </span>
      )}
    </div>
  );
}
