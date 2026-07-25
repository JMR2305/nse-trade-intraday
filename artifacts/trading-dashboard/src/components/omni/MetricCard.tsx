/**
 * MetricCard — compact KPI tile from the OmniRoute design system.
 * Self-contained; uses only shadcn CSS vars so it works in both light/dark.
 */
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { TrendingDown, TrendingUp } from "lucide-react";

interface MetricCardProps {
  label: string;
  value: string | number;
  delta?: string;
  deltaUp?: boolean;
  icon?: ReactNode;
  iconBg?: string;   // Tailwind bg class e.g. "bg-primary/10"
  iconColor?: string; // Tailwind text class e.g. "text-primary"
  children?: ReactNode;
  className?: string;
  hover?: boolean;
}

export function MetricCard({
  label,
  value,
  delta,
  deltaUp,
  icon,
  iconBg = "bg-primary/10",
  iconColor = "text-primary",
  children,
  className,
  hover = true,
}: MetricCardProps) {
  return (
    <div
      className={cn(
        "rounded-2xl border border-border bg-card p-5 shadow-sm transition-all duration-200",
        hover && "hover:shadow-md hover:-translate-y-px",
        className,
      )}
    >
      <div className="flex items-start justify-between gap-2">
        {icon && (
          <span
            className={cn(
              "grid h-10 w-10 shrink-0 place-items-center rounded-xl ring-1",
              iconBg,
              iconColor,
              // subtle ring inferred from bg color at 30% opacity — handled via ring class
            )}
          >
            {icon}
          </span>
        )}
        {delta !== undefined && (
          <span
            className={cn(
              "ml-auto inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-medium",
              deltaUp
                ? "bg-green-500/10 text-green-600 dark:text-green-400"
                : "bg-red-500/10 text-red-600 dark:text-red-400",
            )}
          >
            {deltaUp ? (
              <TrendingUp className="h-3 w-3" />
            ) : (
              <TrendingDown className="h-3 w-3" />
            )}
            {delta}
          </span>
        )}
      </div>

      <p className="mt-3 text-[11px] uppercase tracking-wider text-muted-foreground">
        {label}
      </p>
      <p className="font-mono text-2xl font-semibold tabular-nums text-foreground">
        {value}
      </p>

      {children && <div className="mt-3">{children}</div>}
    </div>
  );
}
