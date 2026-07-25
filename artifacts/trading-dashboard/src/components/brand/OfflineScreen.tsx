/**
 * OfflineScreen — shown when the ApexQuant AI API server is unreachable.
 *
 * Displays:
 *   • ApexQuant AI logo + PAPER TRADING badge
 *   • Clear "temporarily unavailable" message
 *   • Retry button (full page reload)
 *   • Optional "Continue with cached data" link
 *   • Collapsed technical detail
 */
import { RefreshCw, WifiOff } from "lucide-react";
import { BrandHeader } from "@/components/brand/BrandHeader";
import { Button } from "@/components/ui/button";

interface OfflineScreenProps {
  allowDemoFallback?: boolean;
  onDemoFallback?: () => void;
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
      <BrandHeader
        logoSize={44}
        showBadge
        showAiStatus={false}
        className="mb-10"
      />

      {/* ── Icon ── */}
      <div className="mb-6 grid h-16 w-16 place-items-center rounded-2xl border border-border bg-card shadow-card">
        <WifiOff className="h-8 w-8 text-muted-foreground/50" />
      </div>

      {/* ── Heading ── */}
      <h1 className="mb-2 text-[22px] font-semibold text-[#17395F] dark:text-[#F7F4ED]">
        Services Temporarily Unavailable
      </h1>
      <p className="mb-8 max-w-sm text-[14px] leading-relaxed text-muted-foreground">
        ApexQuant AI trading services are temporarily unavailable. Your paper
        positions and strategy settings are safe — no live capital is at risk.
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

      {/* ── Technical detail ── */}
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
        ApexQuant AI · AI-Powered NSE Trading Platform · Paper Mode Only
      </p>
    </div>
  );
}
