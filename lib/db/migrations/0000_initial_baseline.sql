CREATE TABLE "paper_portfolio" (
	"id" integer PRIMARY KEY NOT NULL,
	"cash" double precision NOT NULL,
	"positions" jsonb NOT NULL,
	"pnl_history" jsonb NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now()
);
--> statement-breakpoint
CREATE TABLE "paper_trades" (
	"id" text PRIMARY KEY NOT NULL,
	"symbol" text NOT NULL,
	"action" text NOT NULL,
	"quantity" integer NOT NULL,
	"price" double precision NOT NULL,
	"total" double precision NOT NULL,
	"trade_ts" timestamp with time zone NOT NULL,
	"reason" text DEFAULT '',
	"metadata" jsonb NOT NULL,
	"created_at" timestamp with time zone DEFAULT now()
);
--> statement-breakpoint
CREATE TABLE "push_subscriptions" (
	"token" text PRIMARY KEY NOT NULL,
	"min_confidence" double precision DEFAULT 70 NOT NULL,
	"enabled" boolean DEFAULT true NOT NULL,
	"last_notified_key" text,
	"created_at" timestamp with time zone DEFAULT now(),
	"updated_at" timestamp with time zone DEFAULT now()
);
--> statement-breakpoint
CREATE TABLE "signal_snapshots" (
	"id" bigserial PRIMARY KEY NOT NULL,
	"scan_id" text NOT NULL,
	"canonical_scan_id" text,
	"snapshot_ts" timestamp with time zone DEFAULT now() NOT NULL,
	"signals" jsonb NOT NULL,
	"market_context" jsonb NOT NULL
);
--> statement-breakpoint
CREATE TABLE "signals_cache" (
	"key" text PRIMARY KEY NOT NULL,
	"payload" jsonb NOT NULL,
	"updated_at" timestamp with time zone DEFAULT now()
);
