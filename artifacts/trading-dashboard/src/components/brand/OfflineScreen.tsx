/**
 * OfflineScreen — shown when the Apex Global API server is unreachable.
 *
 * Displays:
 *   • Apex Global symbol + wordmark
 *   • PAPER TRADING mode badge
 *   • Clear "temporarily unavailable" message
 *   • Retry button (full page reload)
 *   • Optional "Continue without live data" link
 */
import { RefreshCw, WifiOff } from "lucide-react";
import { Logo } from "@/components/brand/Logo";
import { Button } from "@/components/ui/button";

interface OfflineScreenProps {
  /** If true, show a "Continue with demo data" option. */
  allowDemoFallback?: boolean;
  onDemoFallback?: () => void;
  /** Error detail, shown collapsed. */
  detail?: string;
}

export function OfflineScreen({
  allowDemoFallback = false,
  onDemoFallback,
  detail,
}: OfflineScreenProps) {
  return (
    <div className="fixed inset-0 z-50 flex flex-col items-center justify-center bg-[#F7F4ED] dark:bg-[#0E1626] px-6 text-center">

      {/* ── Brand ── */}
      <Logo size={40} className="mb-4" />

      {/* Paper Trading mode badge */}
      <span className="mb-8 inline-flex items-center gap-1.5 rounded-full border border-amber-400/40 bg-amber-50 dark:bg-amber-900/20 px-3 py-1 text-[11px] font-semibold uppercase tracking-widest text-amber-700 dark:text-amber-400">
        Paper Trading
      </span>

      {/* ── Icon ── */}
      <div className="mb-6 grid h-16 w-16 place-items-center rounded-2xl border border-border bg-card shadow-card">
        <WifiOff className="h-8 w-8 text-muted-foreground/50" />
      </div>

      {/* ── Heading ── */}
      <h1 className="mb-2 text-[22px] font-semibold text-[#17395F] dark:text-[#F7F4ED]">
        Services Temporarily Unavailable
      </h1>
      <p className="mb-8 max-w-sm text-[14px] leading-relaxed text-muted-foreground">
        Apex Global trading services are temporarily unavailable. Your paper positions
        and strategy settings are safe — no live capital is at risk.
      </p>

      {/* ── Actions ── */}
      <div className="flex flex-col items-center gap-3 w-full max-w-xs">
        <Button
          className="w-full gap-2 bg-[#17395F] hover:bg-[#1f4a7a] text-white dark:bg-[#F7F4ED] dark:text-[#17395F] dark:hover:bg-white"
          onClick={() => window.location.reload()}
        >
          <RefreshCw className="h-4 w-4" />
          Retry Connection
        </Button>

        {allowDemoFallback && onDemoFallback && (
          <button
            className="text-[13px] text-muted-foreground underline underline-offset-2 hover:text-foreground transition"
            onClick={onDemoFallback}
          >
            Continue with cached data
          </button>
        )}
      </div>

      {/* ── Collapsed error detail ── */}
      {detail && (
        <details className="mt-8 max-w-sm text-left">
          <summary className="cursor-pointer text-[12px] text-muted-foreground/60 hover:text-muted-foreground">
            Technical details
          </summary>
          <pre className="mt-2 rounded-lg border border-border bg-card p-3 text-[11px] text-muted-foreground whitespace-pre-wrap break-words">
            {detail}
          </pre>
        </details>
      )}

      {/* ── Footer ── */}
      <p className="absolute bottom-6 text-[11px] text-muted-foreground/40 tracking-wide">
        Apex Global · AI-Powered NSE Trading Platform · Paper Mode Only
      </p>
    </div>
  );
}
