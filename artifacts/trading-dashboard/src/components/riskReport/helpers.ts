/** Helpers, constants, and computation functions for Risk Decision Report V2 */
import type { Gate, Candidate, SimSettings } from "./types";

// ── Gate weights for Risk Score (Section 12) ─────────────────────────────────
export const GATE_WEIGHTS: Record<string, number> = {
  scan_fresh: 3, snapshot_consistency: 3, provider_zerodha: 3,
  no_fallback_data: 3, market_open: 3, entry_circuit_breaker: 3,
  min_confidence: 2.5, min_risk_reward: 2.5,
  min_trade_quality: 2, min_opportunity_score: 2,
  quote_available: 2, strategy_regime_eligible: 2, recommendation_buy: 2,
  valid_stop_loss: 1.5, position_size: 1.5, sufficient_cash: 1.5,
  per_stock_cap: 1, sector_cap: 1, portfolio_deployed_cap: 1,
  daily_loss_limit: 1, daily_trade_limit: 1, no_open_duplicate: 1, cooldown: 0.5,
};

// ── Risk Score ─────────────────────────────────────────────────────────────────
export function riskScoreLevel(score: number) {
  if (score >= 90) return { level: "Very Low",   color: "text-emerald-400", bg: "bg-emerald-900/20 border-emerald-700/40" };
  if (score >= 75) return { level: "Low",         color: "text-teal-400",   bg: "bg-teal-900/20 border-teal-700/40" };
  if (score >= 55) return { level: "Moderate",    color: "text-yellow-400", bg: "bg-yellow-900/20 border-yellow-700/40" };
  if (score >= 35) return { level: "High",        color: "text-orange-400", bg: "bg-orange-900/20 border-orange-700/40" };
  return              { level: "Very High",    color: "text-red-400",    bg: "bg-red-900/20 border-red-700/40" };
}

export function computeRiskScore(candidate: Candidate) {
  let totalW = 0, passedW = 0;
  const failedFactors: string[] = [];
  for (const g of candidate.gates) {
    const w = GATE_WEIGHTS[g.gate] ?? 1;
    totalW += w;
    if (g.passed) passedW += w; else failedFactors.push(g.label);
  }
  const score = totalW > 0 ? Math.round((passedW / totalW) * 100) : 0;
  return { score, failedFactors, ...riskScoreLevel(score) };
}

// ── Severity badge (Section 3) ────────────────────────────────────────────────
export type Severity = "near-pass" | "moderate" | "poor-quality";
export function getSeverity(c: Candidate): Severity {
  const n = c.gates.filter(g => !g.passed && !g.is_global).length;
  if (n <= 1) return "near-pass";
  if (n <= 3) return "moderate";
  return "poor-quality";
}
export const SEVERITY_CONFIG: Record<Severity, { label: string; color: string; bg: string }> = {
  "near-pass":    { label: "NEAR PASS",    color: "text-teal-300",   bg: "bg-teal-900/30 border border-teal-700/50" },
  "moderate":     { label: "MODERATE",     color: "text-amber-300",  bg: "bg-amber-900/30 border border-amber-700/50" },
  "poor-quality": { label: "POOR QUALITY", color: "text-red-300",    bg: "bg-red-900/30 border border-red-700/50" },
};

// ── Threshold parsing ──────────────────────────────────────────────────────────
export function parseThreshold(reason: string): {
  actual?: string; threshold?: string;
  diff?: string; direction?: "increase" | "decrease";
  actualNum?: number; thresholdNum?: number;
} {
  // "X vs minimum Y"  (confidence, scores, R:R)
  const vsMin = reason.match(/([\d.]+)\s+vs\s+minimum\s+([\d.]+)/i);
  if (vsMin) {
    const a = parseFloat(vsMin[1]), t = parseFloat(vsMin[2]);
    const isRR  = /R:R/i.test(reason);
    const isPct = !isRR && /confidence|score/i.test(reason);
    const suffix = isRR ? "×" : isPct ? "%" : "";
    return { actual: vsMin[1] + suffix, threshold: vsMin[2] + suffix,
      actualNum: a, thresholdNum: t,
      diff: Math.abs(t - a).toFixed(isRR ? 2 : 1) + suffix,
      direction: a < t ? "increase" : "decrease" };
  }
  // "X% (cap Y%)"  (exposure caps)
  const vsCap = reason.match(/([\d.]+)%\s+\(cap\s+([\d.]+)%\)/i);
  if (vsCap) {
    const a = parseFloat(vsCap[1]), t = parseFloat(vsCap[2]);
    return { actual: vsCap[1] + "%", threshold: vsCap[2] + "%",
      actualNum: a, thresholdNum: t,
      diff: Math.abs(a - t).toFixed(1) + "%", direction: "decrease" };
  }
  return {};
}

// ── Section 1: Pass hint ───────────────────────────────────────────────────────
export function generatePassHint(gate: Gate): string | null {
  const { diff, direction, threshold, actual } = parseThreshold(gate.reason);
  if (!diff || !direction || !threshold || !actual) return null;
  return `If ${gate.label} ${direction}d by ${diff}, this gate would PASS.`;
}

// ── Section 2: Expected opportunity ───────────────────────────────────────────
export function computeExpectedOpportunity(c: Candidate) {
  const { entry_price, target_price, quantity, position_value, risk_amount } = c.sizing;
  return {
    expectedReturnPct: entry_price > 0 ? (target_price - entry_price) / entry_price * 100 : 0,
    expectedProfitINR: quantity * (target_price - entry_price),
    capitalRequired:   position_value,
    riskAmount:        risk_amount,
  };
}

// ── Section 13: Decision explainer ────────────────────────────────────────────
export function generateDecisionExplainer(c: Candidate): string {
  if (c.eligible) return "All risk gates passed. This candidate is eligible for a paper trade entry.";
  const failedGlobal = c.gates.filter(g => !g.passed && g.is_global);
  const failedLocal  = c.gates.filter(g => !g.passed && !g.is_global);
  if (failedLocal.length === 0 && failedGlobal.length > 0) {
    return `This trade was blocked by a session-level rule (${failedGlobal.map(g => g.label).join(", ")}), which applies to all candidates regardless of individual scores.`;
  }
  const parts = failedLocal.map(g => {
    const { actual, threshold } = parseThreshold(g.reason);
    const over = /cap|exposure|limit/i.test(g.label);
    if (actual && threshold)
      return `the ${g.label} (${actual}) ${over ? "exceeded" : "was below"} the required threshold of ${threshold}`;
    return `the ${g.label} check failed`;
  });
  let sentence = "";
  if (parts.length === 1) sentence = `This trade failed because ${parts[0]}.`;
  else { const last = parts.pop()!; sentence = `This trade failed because ${parts.join(", ")} and ${last}.`; }
  if (failedGlobal.length > 0)
    sentence += ` Additionally, a session-level gate (${failedGlobal.map(g => g.label).join(", ")}) was also failing.`;
  sentence += ` ${c.gates.filter(g => g.passed).length} of ${c.gates.length} gates passed.`;
  return sentence;
}

// ── Section 7: Simulator ──────────────────────────────────────────────────────
export function simulateCandidate(c: Candidate, sim: SimSettings): boolean {
  for (const gate of c.gates) {
    if (gate.is_global) { if (!gate.passed) return false; continue; }
    let passes = gate.passed;
    switch (gate.gate) {
      case "min_confidence":        passes = c.confidence          >= sim.minConfidence;   break;
      case "min_opportunity_score": passes = c.opportunity_score   >= sim.minOpportunity;  break;
      case "min_risk_reward":       passes = c.sizing.rr_ratio     >= sim.minRR;           break;
      case "min_trade_quality":     passes = c.trade_quality_score >= sim.minTradeQuality; break;
      case "sector_cap":    { const { actualNum } = parseThreshold(gate.reason); if (actualNum !== undefined) passes = actualNum <= sim.sectorCap;   break; }
      case "per_stock_cap": { const { actualNum } = parseThreshold(gate.reason); if (actualNum !== undefined) passes = actualNum <= sim.perStockCap; break; }
    }
    if (!passes) return false;
  }
  return true;
}

export function extractThresholds(candidates: Candidate[]): SimSettings {
  const s: SimSettings = { minConfidence: 60, minOpportunity: 60, minRR: 2.0, minTradeQuality: 50, sectorCap: 40, perStockCap: 20 };
  const map: Record<string, keyof SimSettings> = {
    min_confidence: "minConfidence", min_opportunity_score: "minOpportunity",
    min_risk_reward: "minRR", min_trade_quality: "minTradeQuality",
    sector_cap: "sectorCap", per_stock_cap: "perStockCap",
  };
  for (const c of candidates) {
    for (const g of c.gates) {
      const key = map[g.gate];
      if (key) { const { thresholdNum } = parseThreshold(g.reason); if (thresholdNum !== undefined) (s as unknown as Record<string, number>)[key] = thresholdNum; }
    }
  }
  return s;
}

// ── Gate descriptions / recommendations (Sections 4, 10) ─────────────────────
export const GATE_DESCRIPTIONS: Record<string, { purpose: string; impact: string }> = {
  min_confidence:          { purpose: "Ensures AI model confidence meets the minimum level.",                                   impact: "Low-confidence signals have historically underperformed." },
  min_opportunity_score:   { purpose: "Validates the composite opportunity score.",                                            impact: "Aggregates multiple alpha signals. Low scores indicate limited edge." },
  min_risk_reward:         { purpose: "Confirms potential reward justifies the risk.",                                         impact: "Minimum R:R ensures profitable trades offset losing ones over time." },
  min_trade_quality:       { purpose: "Measures technical setup quality including volume, trend, and pattern.",                impact: "High-quality setups show stronger follow-through." },
  sector_cap:              { purpose: "Prevents excessive concentration in a single sector.",                                  impact: "Sector concentration amplifies risk from sector-specific events." },
  per_stock_cap:           { purpose: "Limits portfolio weight of any single stock.",                                          impact: "Position concentration is a leading cause of severe drawdowns." },
  portfolio_deployed_cap:  { purpose: "Maintains minimum cash reserves by capping total deployed capital.",                   impact: "Cash reserves allow capturing new opportunities." },
  daily_loss_limit:        { purpose: "Halts new entries if daily realised losses exceed a threshold.",                        impact: "Prevents runaway losses on down days. Resets at session open." },
  daily_trade_limit:       { purpose: "Caps the number of paper trades per day.",                                             impact: "Limits overtrading." },
  no_open_duplicate:       { purpose: "Blocks opening a second position where one is already open.",                          impact: "Duplicate positions double exposure without additional edge." },
  cooldown:                { purpose: "Enforces a minimum wait between consecutive trades in the same symbol.",               impact: "Prevents churning." },
  quote_available:         { purpose: "Requires a live or near-live price quote.",                                            impact: "Stale quotes result in entries at incorrect prices." },
  strategy_regime_eligible:{ purpose: "Checks current market regime is compatible with the selected strategy.",               impact: "Strategies have regime-specific edges." },
  recommendation_buy:      { purpose: "Only BUY / STRONG BUY signals are eligible.",                                         impact: "WATCH / IGNORE are not intended for execution." },
  valid_stop_loss:         { purpose: "Requires a valid stop-loss price below the entry price.",                              impact: "Without a defined stop, risk cannot be sized correctly." },
  position_size:           { purpose: "Confirms risk budget and cash can size at least one share.",                           impact: "Zero-share position means no trade is possible." },
  sufficient_cash:         { purpose: "Verifies available cash covers the full position value.",                              impact: "Insufficient cash prevents order fulfillment." },
  scan_fresh:              { purpose: "Requires scan data no older than 90 minutes.",                                         impact: "Stale scans mean signals may not reflect current market." },
  snapshot_consistency:    { purpose: "Validates evaluation uses the same scan snapshot as durable metadata.",                impact: "Inconsistency could result in evaluating mismatched data." },
  provider_zerodha:        { purpose: "Requires Zerodha or live-quality data provider.",                                      impact: "Mock or delayed data produces inaccurate signals." },
  no_fallback_data:        { purpose: "Blocks when provider is mock, fallback, or unconfigured.",                             impact: "Fallback providers deliver synthetic data." },
  market_open:             { purpose: "Permits entries only during active NSE trading hours.",                                 impact: "After-hours entries execute at next open at unpredictable prices." },
  entry_circuit_breaker:   { purpose: "Pauses entries when a losing streak or negative expectancy is detected.",              impact: "Forces manual review before resuming." },
};

export const GATE_RECOMMENDATIONS: Record<string, string> = {
  min_confidence:          "The AI model's confidence in this signal is below the required threshold. The signal may improve on the next scan if market conditions clarify.",
  min_opportunity_score:   "The composite opportunity score is below the minimum required. Only high-quality setups enter the pipeline.",
  min_risk_reward:         "The risk-to-reward ratio is below the policy minimum. A tighter stop-loss or higher target price could improve this ratio.",
  min_trade_quality:       "The technical quality score is below the required level. Waiting for a cleaner technical setup may help.",
  sector_cap:              "This sector already has significant portfolio exposure. This gate may clear automatically as other sector positions close.",
  per_stock_cap:           "Adding this position would create excessive concentration in a single stock. This gate clears when existing positions are reduced.",
  portfolio_deployed_cap:  "The portfolio has reached its maximum deployed capital limit. This clears as existing positions close.",
  daily_loss_limit:        "Daily loss protection has been activated. No new entries are permitted until the daily loss limit resets.",
  daily_trade_limit:       "The maximum number of paper trades for today has been reached. This limit resets daily.",
  no_open_duplicate:       "An open position already exists for this symbol. A duplicate trade in the same direction is not permitted.",
  cooldown:                "This symbol is in a cooldown period following a recent trade.",
  market_open:             "The market is not currently open. Entries are only permitted during active trading hours.",
  entry_circuit_breaker:   "The circuit breaker has been triggered. Manual review is required before new entries can resume.",
  valid_stop_loss:         "The stop-loss price is invalid relative to the entry price. A valid stop must be set below entry with a meaningful buffer.",
  position_size:           "The calculated position size is zero — stop distance too narrow or available cash insufficient.",
  sufficient_cash:         "Available cash is insufficient to fund this position at the calculated size.",
  quote_available:         "A live or near-live price quote is not available. Paper entries require real-time data.",
  strategy_regime_eligible:"The strategy's regime requirements are not met by current market conditions.",
  recommendation_buy:      "The scanner did not issue a BUY or STRONG BUY signal for this symbol.",
  scan_fresh:              "The market scan data has become stale. A fresh scan is needed.",
  snapshot_consistency:    "There is a mismatch between the scan snapshot and the durable metadata store.",
  provider_zerodha:        "Neither Zerodha nor any live-quality data provider is connected.",
  no_fallback_data:        "The active data provider is a mock or fallback.",
};

// ── Formatting helpers ─────────────────────────────────────────────────────────
export const fmt1 = (n: number | null | undefined) => Number(n ?? 0).toFixed(1);
export const fmt2 = (n: number | null | undefined) => Number(n ?? 0).toFixed(2);
export const fmtCur = (n: number | null | undefined) =>
  `₹${Number(n ?? 0).toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
export const fmtPct = (n: number | null | undefined) => `${Number(n ?? 0).toFixed(1)}%`;
export function tsLabel(iso?: string) {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString("en-IN", {
      timeZone: "Asia/Kolkata", hour12: false,
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    });
  } catch { return iso; }
}
