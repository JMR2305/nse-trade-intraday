/**
 * SmartDashboard.ts — Phase 9.4
 * Pure time-of-day logic that adapts the dashboard to market session.
 * NO API calls. NO business logic. Reads Date only.
 */

export type MarketSession =
  | "pre-open"     // 09:00 – 09:15
  | "market-open"  // 09:15 – 09:30
  | "market-hours" // 09:30 – 15:25
  | "closing"      // 15:25 – 15:30
  | "after-market" // 15:30 – 20:00
  | "off-hours";   // 20:00 – 09:00

export interface SessionInfo {
  session: MarketSession;
  label: string;
  emoji: string;
  color: string;
  /** Widget ids that should be highlighted for this session */
  highlightWidgets: string[];
  /** Banner message shown on dashboard */
  banner?: string;
}

export function getMarketSession(now?: Date): SessionInfo {
  const d = now ?? new Date();
  // IST offset: UTC+5:30
  const utcMinutes = d.getUTCHours() * 60 + d.getUTCMinutes();
  const istMinutes = (utcMinutes + 330) % 1440; // wrap at midnight

  if (istMinutes >= 540 && istMinutes < 555) {
    // 09:00 – 09:15 IST
    return {
      session: "pre-open",
      label: "Pre-Open Session",
      emoji: "🌅",
      color: "#F59E0B",
      highlightWidgets: ["pre-open", "watchlist", "market-overview", "alerts"],
      banner: "Pre-open session active — IEP prices and order book available",
    };
  }
  if (istMinutes >= 555 && istMinutes < 570) {
    // 09:15 – 09:30 IST
    return {
      session: "market-open",
      label: "Market Opening",
      emoji: "🔔",
      color: "#10B981",
      highlightWidgets: ["execution", "alerts", "market-overview", "watchlist", "today-pnl"],
      banner: "Market opening — first 15 minutes of trading",
    };
  }
  if (istMinutes >= 570 && istMinutes < 925) {
    // 09:30 – 15:25 IST
    return {
      session: "market-hours",
      label: "Market Hours",
      emoji: "📈",
      color: "#3B82F6",
      highlightWidgets: ["portfolio", "today-pnl", "risk-summary", "ai-summary", "alerts", "watchlist"],
      banner: undefined,
    };
  }
  if (istMinutes >= 925 && istMinutes < 930) {
    // 15:25 – 15:30 IST
    return {
      session: "closing",
      label: "Closing Session",
      emoji: "🔔",
      color: "#EF4444",
      highlightWidgets: ["performance", "trading-timeline", "today-pnl", "portfolio"],
      banner: "Market closing in 5 minutes",
    };
  }
  if (istMinutes >= 930 && istMinutes < 1200) {
    // 15:30 – 20:00 IST
    return {
      session: "after-market",
      label: "After Market",
      emoji: "🌙",
      color: "#8B5CF6",
      highlightWidgets: ["performance", "research-feed", "ai-daily-briefing", "learning"],
      banner: "Market closed — review and research mode",
    };
  }
  // Off hours
  return {
    session: "off-hours",
    label: "Off Hours",
    emoji: "😴",
    color: "#6B7280",
    highlightWidgets: ["research-feed", "ai-daily-briefing", "learning", "system-health"],
    banner: undefined,
  };
}

/** Convenience: returns just the highlighted widget ids for now */
export function getHighlightedWidgets(): string[] {
  return getMarketSession().highlightWidgets;
}
