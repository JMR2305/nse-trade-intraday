import { pgTable, integer, doublePrecision, jsonb, text, timestamp, bigserial, boolean } from "drizzle-orm/pg-core";
import { createInsertSchema } from "drizzle-zod";
import { z } from "zod/v4";

// ── Paper Trading: Portfolio State ────────────────────────────────────────────
// Single-row table (id always = 1) holding cash balance, open positions,
// and the P&L history time-series. Managed by portfolio_store.py in Python.

export const paperPortfolioTable = pgTable("paper_portfolio", {
  id:         integer("id").primaryKey(),
  cash:       doublePrecision("cash").notNull(),
  positions:  jsonb("positions").notNull().$type<Record<string, { quantity: number; avg_price: number }>>(),
  pnlHistory: jsonb("pnl_history").notNull().$type<Array<{ timestamp: string; value: number }>>(),
  updatedAt:  timestamp("updated_at", { withTimezone: true }).defaultNow(),
});

// ── Paper Trading: Individual Trades ─────────────────────────────────────────
// One row per BUY or SELL execution. `metadata` carries all extended fields
// (AI decision context, indicators at entry, friction costs, etc.).

export const paperTradesTable = pgTable("paper_trades", {
  id:        text("id").primaryKey(),
  symbol:    text("symbol").notNull(),
  action:    text("action").notNull(),
  quantity:  integer("quantity").notNull(),
  price:     doublePrecision("price").notNull(),
  total:     doublePrecision("total").notNull(),
  tradeTs:   timestamp("trade_ts", { withTimezone: true }).notNull(),
  reason:    text("reason").default(""),
  metadata:  jsonb("metadata").notNull().$type<Record<string, unknown>>(),
  createdAt: timestamp("created_at", { withTimezone: true }).defaultNow(),
});

// ── Signals Cache ─────────────────────────────────────────────────────────────
// Stores the latest intelligence scan outputs (signals, AI decisions,
// opportunity scan, market context) keyed by a short string label.
// Managed by signals_store.py in Python.

export const signalsCacheTable = pgTable("signals_cache", {
  key:       text("key").primaryKey(),
  payload:   jsonb("payload").notNull().$type<unknown>(),
  updatedAt: timestamp("updated_at", { withTimezone: true }).defaultNow(),
});

// ── Signal Snapshots (append-only history) ────────────────────────────────────
// One row per intelligence scan. Never updated after insert — lets traders
// review how BUY/SELL recommendations evolved across scans.
// Managed by signals_store.py in Python (auto-created there).

export const signalSnapshotsTable = pgTable("signal_snapshots", {
  id:              bigserial("id", { mode: "number" }).primaryKey(),
  scanId:          text("scan_id").notNull(),
  canonicalScanId: text("canonical_scan_id"),
  snapshotTs:      timestamp("snapshot_ts", { withTimezone: true }).notNull().defaultNow(),
  signals:         jsonb("signals").notNull().$type<unknown[]>(),
  marketContext:   jsonb("market_context").notNull().$type<Record<string, unknown>>(),
});

// ── Push Notification Subscriptions ──────────────────────────────────────────
// One row per mobile device (Expo push token). The scan scheduler dispatches
// a push when a fresh scan produces BUY/SELL signals whose confidence meets
// the subscriber's own threshold. last_notified_key stores the signals-cache
// updated_at that was last evaluated, so each scan is only considered once.

export const pushSubscriptionsTable = pgTable("push_subscriptions", {
  token:           text("token").primaryKey(),
  minConfidence:   doublePrecision("min_confidence").notNull().default(70),
  enabled:         boolean("enabled").notNull().default(true),
  lastNotifiedKey: text("last_notified_key"),
  createdAt:       timestamp("created_at", { withTimezone: true }).defaultNow(),
  updatedAt:       timestamp("updated_at", { withTimezone: true }).defaultNow(),
});

// ── Insert schemas / types ────────────────────────────────────────────────────

export const insertPaperTradeSchema = createInsertSchema(paperTradesTable).omit({ createdAt: true });
export type InsertPaperTrade = z.infer<typeof insertPaperTradeSchema>;
export type PaperTrade = typeof paperTradesTable.$inferSelect;
export type PaperPortfolio = typeof paperPortfolioTable.$inferSelect;
export type SignalsCache = typeof signalsCacheTable.$inferSelect;
export type SignalSnapshot = typeof signalSnapshotsTable.$inferSelect;
export type PushSubscription = typeof pushSubscriptionsTable.$inferSelect;
