/**
 * PaperTradingBadge — always-visible mode indicator.
 * Renders a compact amber pill labelled PAPER or PAPER TRADING.
 */
import { cn } from "@/lib/utils";

interface PaperTradingBadgeProps {
  compact?: boolean;       // "PAPER" vs "PAPER TRADING"
  className?: string;
}

export function PaperTradingBadge({ compact = false, className }: PaperTradingBadgeProps) {
  return (
    <span
      className={cn(
        "inline-flex items-center shrink-0 rounded-full border",
        "border-warn bg-warn-surface",
        "font-bold uppercase tracking-widest leading-none",
        "text-warn",
        compact
          ? "px-1.5 py-0.5 text-[8px]"
          : "px-2.5 py-1 text-[10px]",
        className,
      )}
    >
      {compact ? "PAPER" : "PAPER TRADING"}
    </span>
  );
}
