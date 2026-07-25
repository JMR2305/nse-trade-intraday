/**
 * BrandHeader — reusable branded header strip.
 *
 * Renders the ApexQuant AI lockup alongside the PAPER TRADING badge
 * and an optional AI Advisory Active status pill.
 *
 * Intended for splash / loading / login / offline screens where a
 * standalone header is needed outside the main AppLayout.
 */
import { cn } from "@/lib/utils";
import { BrandLogo } from "./BrandLogo";
import { PaperTradingBadge } from "./PaperTradingBadge";

interface BrandHeaderProps {
  className?: string;
  logoSize?: number;
  showBadge?: boolean;
  showAiStatus?: boolean;
  /** Use white variant (for dark/navy backgrounds). */
  white?: boolean;
  compact?: boolean;
}

export function BrandHeader({
  className,
  logoSize = 32,
  showBadge = true,
  showAiStatus = false,
  white = false,
  compact = false,
}: BrandHeaderProps) {
  return (
    <div className={cn("flex flex-col items-center gap-3", className)}>
      <BrandLogo size={logoSize} white={white} />

      <div className="flex items-center gap-2">
        {showBadge && <PaperTradingBadge compact={compact} />}

        {showAiStatus && (
          <span
            className={cn(
              "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[10px] font-bold uppercase tracking-widest leading-none",
              white
                ? "border-teal-400/40 bg-teal-900/30 text-teal-300"
                : "border-[#129C8C]/30 bg-[#129C8C]/8 text-[#129C8C]",
            )}
          >
            <span className="h-1.5 w-1.5 rounded-full bg-[#129C8C] animate-[pulse-soft_2.8s_ease-in-out_infinite]" />
            AI Advisory Active
          </span>
        )}
      </div>
    </div>
  );
}
