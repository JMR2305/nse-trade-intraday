/**
 * BrandLogo — ApexQuant AI full lockup.
 * Mark + "ApexQuant" (navy) + " AI" (teal) wordmark.
 */
import { cn } from "@/lib/utils";
import { BrandMark } from "./BrandMark";

interface BrandLogoProps {
  size?: number;
  className?: string;
  showWordmark?: boolean;
  /** Force white variant for dark/navy backgrounds (overrides theme detection). */
  white?: boolean;
}

export function BrandLogo({
  size = 28,
  className,
  showWordmark = true,
  white = false,
}: BrandLogoProps) {
  const fontSize = Math.max(11, Math.round(size * 0.5));

  return (
    <div
      className={cn(
        "inline-flex items-center gap-2 select-none",
        white
          ? "text-white"
          : "text-[#17395F] dark:text-[#F7F4ED]",
        className,
      )}
    >
      <BrandMark size={size} accentColor={white ? "#4ECDC4" : "#129C8C"} />

      {showWordmark && (
        <span
          className="font-semibold leading-none whitespace-nowrap"
          style={{ fontSize, letterSpacing: "0.01em" }}
        >
          ApexQuant{" "}
          <span style={{ color: white ? "#4ECDC4" : "#129C8C" }}>AI</span>
        </span>
      )}
    </div>
  );
}
