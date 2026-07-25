/**
 * ProgressGauge — arc gauge for capacity / utilisation display.
 * Adapted from OmniRoute design system.
 */
import { cn } from "@/lib/utils";
import type { Tone } from "@/lib/theme";
import { toneRgb } from "@/lib/theme";

interface ProgressGaugeProps {
  value: number;       // 0–100
  tone?: Tone;
  size?: number;       // svg diameter in px
  thickness?: number;
  label?: string;
  sublabel?: string;
  className?: string;
}

export function ProgressGauge({
  value,
  tone = "primary",
  size = 96,
  thickness = 10,
  label,
  sublabel,
  className,
}: ProgressGaugeProps) {
  const clamp = Math.min(100, Math.max(0, value));
  const r = (size - thickness) / 2;
  const cx = size / 2;
  const cy = size / 2;
  // Arc spans 240° (−120° to +120° from bottom) — standard gauge convention
  const arcDeg = 240;
  const arcRad = (arcDeg * Math.PI) / 180;
  const circumference = 2 * Math.PI * r;
  const trackDash = (arcDeg / 360) * circumference;
  const fillDash = (clamp / 100) * trackDash;
  const startOffset = circumference * (1 - arcDeg / 360) / 2 + circumference * 0.25;

  return (
    <div className={cn("inline-flex flex-col items-center gap-1", className)}>
      <div className="relative" style={{ width: size, height: size }}>
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ transform: "rotate(-210deg)" }}>
          {/* track */}
          <circle
            cx={cx} cy={cy} r={r}
            fill="none"
            stroke="hsl(var(--border))"
            strokeWidth={thickness}
            strokeDasharray={`${trackDash} ${circumference - trackDash}`}
            strokeDashoffset={-startOffset + circumference}
            strokeLinecap="round"
          />
          {/* fill */}
          <circle
            cx={cx} cy={cy} r={r}
            fill="none"
            stroke={toneRgb(tone)}
            strokeWidth={thickness}
            strokeDasharray={`${fillDash} ${circumference - fillDash}`}
            strokeDashoffset={-startOffset + circumference}
            strokeLinecap="round"
            className="transition-all duration-700"
          />
        </svg>
        <div className="absolute inset-0 flex flex-col items-center justify-center">
          <span className="font-mono text-[15px] font-semibold tabular-nums text-foreground">
            {clamp}%
          </span>
        </div>
      </div>
      {label && (
        <p className="text-[11px] font-medium text-foreground">{label}</p>
      )}
      {sublabel && (
        <p className="text-[10px] text-muted-foreground">{sublabel}</p>
      )}
    </div>
  );
}
