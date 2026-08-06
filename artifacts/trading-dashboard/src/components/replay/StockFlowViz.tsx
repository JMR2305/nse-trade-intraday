/**
 * StockFlowViz — V5.0
 * Animated stock chips flowing through pipeline stages during replay.
 * Accepted chips flow downward (teal); rejected chips fly sideways (red).
 */
import React, { useEffect, useState, useRef, useCallback } from "react";

interface StageCfg {
  id: string;
  label: string;
}

interface StageData {
  id: string;
  stocks_in: number;
  stocks_out: number;
  rejected: number;
  rejected_symbols: string[];
  stocks: string[];
}

interface FlowChip {
  id: string;
  symbol: string;
  type: "pass" | "reject";
  stageIdx: number;
  offsetX: number; // % horizontal jitter within lane
}

const CHIP_LIFETIME_MS = 2200;
const MAX_CHIPS        = 10;
const CHIP_COLORS = {
  pass:   { bg: "bg-teal-500", text: "text-white",      border: "border-teal-400" },
  reject: { bg: "bg-red-500",  text: "text-white",      border: "border-red-400" },
};

interface Props {
  pipelineCfg: StageCfg[];
  stageById: Record<string, StageData>;
  activeStageIdx: number;
  replayState: "idle" | "playing" | "paused" | "complete";
}

export function StockFlowViz({ pipelineCfg, stageById, activeStageIdx, replayState }: Props) {
  const [chips, setChips] = useState<FlowChip[]>([]);
  const [animated, setAnimated] = useState<Set<string>>(new Set());
  const cleanupRef = useRef<ReturnType<typeof setTimeout>[]>([]);

  const spawnChips = useCallback((stageIdx: number) => {
    const cfg = pipelineCfg[stageIdx];
    if (!cfg) return;
    const sd = stageById[cfg.id];
    if (!sd) return;

    const passSymbols   = (sd.stocks ?? []).slice(0, 4);
    const rejectSymbols = (sd.rejected_symbols ?? []).slice(0, 2);
    const now = Date.now();

    const newChips: FlowChip[] = [
      ...passSymbols.map((sym, i) => ({
        id: `${now}-p-${i}`,
        symbol: sym,
        type: "pass" as const,
        stageIdx,
        offsetX: 10 + (i % 3) * 28,
      })),
      ...rejectSymbols.map((sym, i) => ({
        id: `${now}-r-${i}`,
        symbol: sym,
        type: "reject" as const,
        stageIdx,
        offsetX: 8 + (i % 2) * 40,
      })),
    ];

    if (newChips.length === 0) return;

    setChips(prev => {
      const combined = [...prev, ...newChips];
      return combined.slice(-MAX_CHIPS);
    });

    // Trigger transition after one frame
    const rafId = requestAnimationFrame(() => {
      setAnimated(prev => {
        const next = new Set(prev);
        newChips.forEach(c => next.add(c.id));
        return next;
      });
    });

    // Remove after lifetime
    const t = setTimeout(() => {
      setChips(prev => prev.filter(c => !newChips.find(nc => nc.id === c.id)));
      setAnimated(prev => {
        const next = new Set(prev);
        newChips.forEach(c => next.delete(c.id));
        return next;
      });
      cancelAnimationFrame(rafId);
    }, CHIP_LIFETIME_MS);

    cleanupRef.current.push(t);
  }, [pipelineCfg, stageById]);

  useEffect(() => {
    if (replayState === "playing" && activeStageIdx >= 0) {
      spawnChips(activeStageIdx);
    }
    if (replayState === "idle") {
      setChips([]); setAnimated(new Set());
    }
  }, [activeStageIdx, replayState]); // eslint-disable-line

  useEffect(() => {
    return () => { cleanupRef.current.forEach(clearTimeout); };
  }, []);

  const STAGE_H_PCT = 100 / pipelineCfg.length; // height % per stage zone

  return (
    <div className="bg-slate-900/60 border border-slate-700/40 rounded-xl overflow-hidden h-full">
      <div className="px-3 py-2 border-b border-slate-800/60 flex items-center gap-2">
        <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Live Stock Flow</span>
        {replayState === "playing" && (
          <span className="ml-auto flex items-center gap-1 text-xs text-teal-400">
            <span className="w-1.5 h-1.5 bg-teal-400 rounded-full animate-ping" />
            Live
          </span>
        )}
      </div>

      {/* Stage lanes */}
      <div className="relative" style={{ height: `${pipelineCfg.length * 52}px` }}>

        {/* Keyframe styles */}
        <style>{`
          @keyframes chipFlowDown {
            0%   { transform: translateY(0px)  scale(1);    opacity: 1; }
            60%  { transform: translateY(38px) scale(0.95); opacity: 0.9; }
            100% { transform: translateY(52px) scale(0.9);  opacity: 0; }
          }
          @keyframes chipFlyOut {
            0%   { transform: translateX(0px)  scale(1);   opacity: 1; }
            40%  { transform: translateX(20px) scale(1.1); opacity: 0.8; }
            100% { transform: translateX(70px) scale(0.8); opacity: 0; }
          }
          .chip-pass   { animation: chipFlowDown ${CHIP_LIFETIME_MS}ms ease-out forwards; }
          .chip-reject { animation: chipFlyOut   ${Math.round(CHIP_LIFETIME_MS * 0.75)}ms ease-in  forwards; }
        `}</style>

        {/* Stage zone backgrounds */}
        {pipelineCfg.map((stage, i) => {
          const sd = stageById[stage.id];
          const isActive = i === activeStageIdx;
          const isPast   = i < activeStageIdx || replayState === "complete";
          return (
            <div
              key={stage.id}
              className={`absolute left-0 right-0 flex items-center border-b border-slate-800/40 px-2 transition-colors duration-300 ${
                isActive ? "bg-teal-900/15" : isPast ? "bg-slate-800/20" : ""
              }`}
              style={{ top: `${i * 52}px`, height: "52px" }}
            >
              {/* Stage label */}
              <div className="w-28 flex-shrink-0">
                <div className={`text-xs font-medium truncate ${isActive ? "text-teal-300" : isPast ? "text-slate-400" : "text-slate-600"}`}>
                  {stage.label}
                </div>
                {sd && isPast && (
                  <div className="text-xs text-slate-600 font-mono">
                    {sd.stocks_out}<span className="text-slate-700">/{sd.stocks_in}</span>
                    {sd.rejected > 0 && <span className="text-red-600 ml-1">-{sd.rejected}</span>}
                  </div>
                )}
              </div>

              {/* Mini acceptance bar */}
              {sd && sd.stocks_in > 0 && (
                <div className="flex-1 ml-2 h-1.5 bg-slate-800 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all duration-700 ${
                      isPast || isActive ? "bg-gradient-to-r from-teal-600 to-teal-400" : "bg-slate-700"
                    }`}
                    style={{ width: isPast || isActive ? `${(sd.stocks_out / sd.stocks_in) * 100}%` : "0%" }}
                  />
                </div>
              )}

              {/* Active pulse */}
              {isActive && (
                <div className="ml-2 w-2 h-2 rounded-full bg-teal-400 animate-ping flex-shrink-0" />
              )}
            </div>
          );
        })}

        {/* Flowing chips */}
        {chips.map(chip => {
          const colors = CHIP_COLORS[chip.type];
          const topPx  = chip.stageIdx * 52 + 16;
          return (
            <div
              key={chip.id}
              className={`absolute pointer-events-none px-1.5 py-0.5 rounded text-xs font-mono font-semibold border ${colors.bg} ${colors.text} ${colors.border} ${chip.type === "pass" ? "chip-pass" : "chip-reject"}`}
              style={{
                top:  `${topPx}px`,
                left: `${chip.offsetX + 28}%`,
                zIndex: 10,
                whiteSpace: "nowrap",
                fontSize: "10px",
              }}
            >
              {chip.symbol.length > 8 ? chip.symbol.slice(0, 7) + "…" : chip.symbol}
            </div>
          );
        })}
      </div>

      {/* Legend */}
      <div className="px-3 py-2 border-t border-slate-800/60 flex gap-4 text-xs text-slate-600">
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-teal-500" />Passed</span>
        <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red-500" />Rejected</span>
      </div>
    </div>
  );
}
