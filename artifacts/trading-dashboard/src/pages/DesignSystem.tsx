/**
 * DesignSystem.tsx — Phase 9.7
 * Design System Gallery — showcases every DS component with live examples.
 *
 * READ-ONLY · UI ONLY
 * This page documents the ApexQuant AI shared component library.
 */

import React, { useState } from "react";
import {
  Palette, TrendingUp, Shield, Bot, Settings, Brain, Zap,
  Activity, BarChart3, CheckCircle2, AlertTriangle, Info, Download,
  Eye, Star, Cpu, Globe, Target, Lightbulb, RefreshCw,
  FileBarChart2, Clock, Search,
} from "lucide-react";
import {
  PageHeader,
  KpiCard,
  MetricTile,
  AgentBadge,
  AlertCard,
  SectionHeader,
  EmptyState,
  ErrorState,
  HealthCard,
  RecommendationCard,
  StatCard,
  StatusBadge,
  SummaryCard,
  DataTable,
  TableColumn,
} from "@/components/ds";
import {
  KpiCardSkeleton,
  CardSkeleton,
  TableSkeleton,
} from "@/components/ds/LoadingSkeleton";
import { AGENT_COLORS, CHART_COLORS, STATUS_COLORS, SURFACE, TEXT, FONT_SIZE, FONT_WEIGHT } from "@/lib/designTokens";

// ─── Sample data ────────────────────────────────────────────────────────────────

type TradeRow = { symbol: string; entry: number; exit: number; pnl: number; status: string };

const SAMPLE_TRADES: TradeRow[] = [
  { symbol: "RELIANCE", entry: 2800.0, exit: 2845.5, pnl: 45.5,  status: "closed" },
  { symbol: "TCS",      entry: 3950.0, exit: 3920.0, pnl: -30.0, status: "closed" },
  { symbol: "HDFCBANK", entry: 1680.0, exit: 1710.0, pnl: 30.0,  status: "closed" },
  { symbol: "INFY",     entry: 1540.0, exit: 1555.0, pnl: 15.0,  status: "open"   },
  { symbol: "ICICIBANK",entry: 1050.0, exit: 1060.0, pnl: 10.0,  status: "closed" },
];

const TRADE_COLUMNS: TableColumn<TradeRow>[] = [
  { key: "symbol", label: "Symbol",   sortable: true, width: 120 },
  { key: "entry",  label: "Entry",    sortable: true, render: (v) => `₹${Number(v).toFixed(2)}` },
  { key: "exit",   label: "Exit",     sortable: true, render: (v) => `₹${Number(v).toFixed(2)}` },
  {
    key: "pnl", label: "P&L", sortable: true,
    render: (v) => (
      <span style={{ color: Number(v) >= 0 ? "#10B981" : "#EF4444", fontWeight: 600 }}>
        {Number(v) >= 0 ? "+" : ""}₹{Number(v).toFixed(2)}
      </span>
    ),
  },
  {
    key: "status", label: "Status",
    render: (v) => <StatusBadge variant={String(v) === "open" ? "live" : "success"} label={String(v)} />,
  },
];

// ─── Section wrapper ────────────────────────────────────────────────────────────

function Section({ title, id, children }: { title: string; id: string; children: React.ReactNode }) {
  return (
    <section id={id} style={{ marginBottom: 48 }}>
      <div style={{
        fontSize:      FONT_SIZE.xs,
        fontWeight:    FONT_WEIGHT.semibold,
        color:         TEXT.muted,
        textTransform: "uppercase",
        letterSpacing: "0.08em",
        marginBottom:  16,
        paddingBottom: 8,
        borderBottom:  `1px solid ${SURFACE.border}`,
      }}>
        {title}
      </div>
      {children}
    </section>
  );
}

function Row({ children, gap = 12 }: { children: React.ReactNode; gap?: number }) {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap, marginBottom: 16 }}>
      {children}
    </div>
  );
}

function CodeChip({ children }: { children: string }) {
  return (
    <code style={{
      fontSize:     FONT_SIZE.xs,
      color:        "#A78BFA",
      background:   "rgba(167,139,250,0.10)",
      border:       "1px solid rgba(167,139,250,0.20)",
      borderRadius: 4,
      padding:      "1px 6px",
      fontFamily:   "monospace",
    }}>
      {children}
    </code>
  );
}

// ─── Main page ──────────────────────────────────────────────────────────────────

export default function DesignSystem() {
  const [showSkeleton, setShowSkeleton] = useState(false);
  const [showEmpty,    setShowEmpty]    = useState(false);
  const [showError,    setShowError]    = useState(false);

  return (
    <div style={{ padding: "20px 24px 64px", maxWidth: 1200, fontFamily: "inherit" }}>

      <PageHeader
        title="Design System"
        subtitle="ApexQuant AI shared component library · Phase 9.7"
        icon={Palette}
        agentId="operations"
        agentName="Operations Agent"
        status="live"
        readOnly
        breadcrumbs={[{ label: "Operations" }, { label: "Design System" }]}
        helpTitle="Design System Gallery"
        faqs={[
          { q: "How do I use these components?", a: "Import from `@/components/ds` (barrel export) or individual files. Design tokens are in `@/lib/designTokens`." },
          { q: "Where are the colour tokens?", a: "See `src/lib/designTokens.ts` — AGENT_COLORS, STATUS_COLORS, SEVERITY_COLORS, PNL_COLORS, SURFACE, TEXT." },
          { q: "Can I add new components?", a: "Yes — create a new file in `src/components/ds/` and re-export it from `src/components/ds/index.ts`." },
        ]}
      />

      {/* ─── Colour System ─────────────────────────────────────────────────── */}
      <Section title="Colour System" id="colours">
        <SectionHeader title="Agent Colours" subtitle="One colour per agent — consistent across every page" divider />
        <Row gap={8}>
          {Object.entries(AGENT_COLORS).map(([id, color]) => (
            <div
              key={id}
              style={{
                padding: "10px 14px", background: `${color}18`,
                border: `1px solid ${color}30`, borderRadius: 8,
                minWidth: 110, textAlign: "center",
              }}
            >
              <div style={{ width: 24, height: 24, borderRadius: "50%", background: color, margin: "0 auto 6px" }} />
              <div style={{ fontSize: FONT_SIZE.xs, color: TEXT.secondary, fontWeight: FONT_WEIGHT.medium }}>{id}</div>
              <div style={{ fontSize: FONT_SIZE["2xs"], color: TEXT.muted, marginTop: 2, fontFamily: "monospace" }}>{color}</div>
            </div>
          ))}
        </Row>

        <SectionHeader title="Chart Palette" subtitle="Recharts colour sequence" divider style={{ marginTop: 20 }} />
        <Row gap={6}>
          {CHART_COLORS.map((c, i) => (
            <div key={i} style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 4 }}>
              <div style={{ width: 32, height: 32, borderRadius: 6, background: c }} />
              <span style={{ fontSize: 9, color: TEXT.muted, fontFamily: "monospace" }}>{c}</span>
            </div>
          ))}
        </Row>

        <SectionHeader title="Status Colours" divider style={{ marginTop: 20 }} />
        <Row gap={8}>
          {Object.entries(STATUS_COLORS).map(([key, color]) => (
            <div key={key} style={{ display: "flex", alignItems: "center", gap: 6, padding: "5px 12px", background: `${color}15`, border: `1px solid ${color}30`, borderRadius: 6 }}>
              <div style={{ width: 8, height: 8, borderRadius: "50%", background: color }} />
              <span style={{ fontSize: FONT_SIZE.xs, color }}>{key}</span>
            </div>
          ))}
        </Row>
      </Section>

      {/* ─── Status Badge ──────────────────────────────────────────────────── */}
      <Section title="StatusBadge" id="status-badge">
        <div style={{ marginBottom: 8 }}><CodeChip>{`import { StatusBadge } from "@/components/ds"`}</CodeChip></div>
        <Row gap={8}>
          {(["live","stale","offline","success","warning","error","info","critical","high","medium","low"] as const).map(v => (
            <StatusBadge key={v} variant={v} />
          ))}
        </Row>
        <Row gap={8}>
          <StatusBadge variant="live"    size="xs" />
          <StatusBadge variant="live"    size="sm" />
          <StatusBadge variant="live"    size="md" />
          <StatusBadge variant="success" dot={false} label="No dot" />
        </Row>
      </Section>

      {/* ─── Agent Badge ───────────────────────────────────────────────────── */}
      <Section title="AgentBadge" id="agent-badge">
        <div style={{ marginBottom: 8 }}><CodeChip>{`import { AgentBadge } from "@/components/ds"`}</CodeChip></div>
        <Row gap={8}>
          {Object.entries(AGENT_COLORS).map(([id, color]) => (
            <AgentBadge key={id} agentId={id as any} agentName={id.replace("-", " ")} agentColor={color} />
          ))}
        </Row>
      </Section>

      {/* ─── KPI Card ──────────────────────────────────────────────────────── */}
      <Section title="KpiCard" id="kpi-card">
        <div style={{ marginBottom: 8 }}><CodeChip>{`import { KpiCard } from "@/components/ds"`}</CodeChip></div>
        <Row gap={10}>
          <KpiCard label="Platform Health"  value={87}   scoreMode icon={Activity}    iconColor="#10B981" description="Operational health score" />
          <KpiCard label="Risk Score"       value={42}   scoreMode icon={Shield}      iconColor="#F59E0B" />
          <KpiCard label="AI Score"         value={23}   scoreMode icon={Bot}         iconColor="#EF4444" />
          <KpiCard label="Win Rate"         value="68%"  icon={Target}   color="#3B82F6" />
          <KpiCard label="Realised P&L"     value="₹1,240" pnlMode pnlValue={1240} icon={TrendingUp} />
          <KpiCard label="Unrealised P&L"   value="₹-320" pnlMode pnlValue={-320} icon={TrendingUp} />
        </Row>
      </Section>

      {/* ─── Metric Tile ───────────────────────────────────────────────────── */}
      <Section title="MetricTile" id="metric-tile">
        <div style={{ marginBottom: 8 }}><CodeChip>{`import { MetricTile } from "@/components/ds"`}</CodeChip></div>
        <Row gap={8}>
          <MetricTile label="Open Positions" value="3"       icon={Eye} />
          <MetricTile label="Regime"         value="BULLISH" color="#10B981" />
          <MetricTile label="Session P&L"    value="₹920"   pnl />
          <MetricTile label="Loss"           value="₹-200"  pnl />
          <MetricTile label="Signals"        value="7"       icon={Zap} />
        </Row>
      </Section>

      {/* ─── Stat Card ─────────────────────────────────────────────────────── */}
      <Section title="StatCard" id="stat-card">
        <div style={{ marginBottom: 8 }}><CodeChip>{`import { StatCard } from "@/components/ds"`}</CodeChip></div>
        <Row gap={10}>
          <StatCard label="Win Rate"        value="68%"     change={4.2}  icon={Target}   iconColor="#10B981" />
          <StatCard label="Avg Trade P&L"   value="₹184"   change={-1.5} icon={TrendingUp} />
          <StatCard label="Total Trades"    value="12"      icon={BarChart3} iconColor="#6366F1" />
          <StatCard label="Max Drawdown"    value="₹-450"  change={-3.1} icon={Shield}    iconColor="#EF4444" />
        </Row>
      </Section>

      {/* ─── Health Card ───────────────────────────────────────────────────── */}
      <Section title="HealthCard" id="health-card">
        <div style={{ marginBottom: 8 }}><CodeChip>{`import { HealthCard } from "@/components/ds"`}</CodeChip></div>
        <Row gap={10}>
          <HealthCard label="API Server"   status="healthy"  score={92} details="All endpoints responding" icon={Cpu}   />
          <HealthCard label="Database"     status="degraded" score={61} details="High query latency"       icon={Brain} />
          <HealthCard label="Data Feed"    status="critical" score={18} details="Provider offline"         icon={Globe} />
          <HealthCard label="Scheduler"    status="unknown"             details="Status unknown"           icon={Clock} />
          <HealthCard label="AI Engine"    status="healthy"  score={88}                                   icon={Bot}   compact />
        </Row>
      </Section>

      {/* ─── Alert Card ────────────────────────────────────────────────────── */}
      <Section title="AlertCard" id="alert-card">
        <div style={{ marginBottom: 8 }}><CodeChip>{`import { AlertCard } from "@/components/ds"`}</CodeChip></div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <AlertCard severity="critical" title="Risk score critical: 0.0/100"       body="Platform risk score has dropped to critical. Review all open positions immediately." timestamp="12:26 IST" />
          <AlertCard severity="high"     title="Scan data stale — 55 minutes"       body="Live scan snapshot is older than the 90-minute threshold." />
          <AlertCard severity="medium"   title="Win rate declining"                  body="AI win rate has dropped below 60% over the last 10 trades." compact />
          <AlertCard severity="low"      title="Paper mode active"                  compact />
          <AlertCard severity="success"  title="EOD reconciliation complete"         compact />
          <AlertCard severity="info"     title="Market closed — session complete"   compact />
        </div>
      </Section>

      {/* ─── Recommendation Card ───────────────────────────────────────────── */}
      <Section title="RecommendationCard" id="recommendation-card">
        <div style={{ marginBottom: 8 }}><CodeChip>{`import { RecommendationCard } from "@/components/ds"`}</CodeChip></div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <RecommendationCard
            title="Review open positions before market close"
            description="3 positions remain open. Consider closing to avoid overnight risk exposure."
            priority="urgent"
            source="Risk Agent"
          />
          <RecommendationCard
            title="AI confidence trending down — review strategy"
            description="AI confidence has dropped from 72% to 54% over the last 6 trades. Check Strategy Intelligence."
            priority="high"
            source="AI Decision Agent"
            actionLabel="View Strategy Intelligence"
          />
          <RecommendationCard
            title="Run post-session learning review"
            description="Complete today's checklist and archive session data for learning governance."
            priority="low"
            source="Learning Agent"
          />
        </div>
      </Section>

      {/* ─── Summary Card ──────────────────────────────────────────────────── */}
      <Section title="SummaryCard" id="summary-card">
        <div style={{ marginBottom: 8 }}><CodeChip>{`import { SummaryCard } from "@/components/ds"`}</CodeChip></div>
        <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
          <SummaryCard
            title="Morning Brief Summary"
            text="Market regime: BULLISH. Platform readiness score: 87/100. 5 AI signals queued. No critical alerts — safe to proceed. Pre-open intelligence loaded and cached."
            accentColor="#F59E0B"
            highlights={["BULLISH", "87/100", "5 AI signals"]}
          />
          <SummaryCard
            title="EOD Executive Summary"
            text="End-of-Day: 12 total paper positions, 9 closed. Session realised P&L: ₹920. Win rate: 67%. Platform health: 87/100. Regime: BULLISH. 2 critical events during session."
            accentColor="#EF4444"
            icon={FileBarChart2}
            highlights={["₹920", "67%", "BULLISH"]}
          />
        </div>
      </Section>

      {/* ─── Section Header ────────────────────────────────────────────────── */}
      <Section title="SectionHeader" id="section-header">
        <div style={{ marginBottom: 8 }}><CodeChip>{`import { SectionHeader } from "@/components/ds"`}</CodeChip></div>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          <SectionHeader title="AI Signals" icon={Bot} iconColor="#6366F1" divider />
          <SectionHeader title="Risk Events" icon={Shield} iconColor="#EF4444" subtitle="Last 30 minutes" divider
            actions={<StatusBadge variant="warning" label="2 alerts" size="xs" />}
          />
          <SectionHeader title="Portfolio" icon={BarChart3} iconColor="#3B82F6" />
        </div>
      </Section>

      {/* ─── Empty State ───────────────────────────────────────────────────── */}
      <Section title="EmptyState" id="empty-state">
        <div style={{ marginBottom: 8 }}><CodeChip>{`import { EmptyState } from "@/components/ds"`}</CodeChip></div>
        <Row gap={16}>
          <button
            onClick={() => setShowEmpty(v => !v)}
            style={{ padding: "6px 14px", fontSize: FONT_SIZE.sm, borderRadius: 6, cursor: "pointer", background: SURFACE.card, border: `1px solid ${SURFACE.border}`, color: TEXT.secondary }}
          >
            {showEmpty ? "Hide" : "Show"} EmptyState
          </button>
        </Row>
        {showEmpty && (
          <div style={{ background: SURFACE.card, border: `1px solid ${SURFACE.border}`, borderRadius: 10 }}>
            <EmptyState
              icon={Search}
              iconColor="#6366F1"
              title="No paper trades yet"
              description="Paper trades will appear here once the AI begins generating signals and positions are opened."
              why="No scan has run in the current session, so no signals are available to trade."
              howItAppears="After a scan runs, AI signals generate paper trade entries that appear in this list."
              actions={[
                { label: "Go to Command Centre", href: "/command-center", primary: true },
                { label: "View AI Signals", href: "/signals" },
              ]}
              relatedPages={[{ label: "AI Decision", href: "/ai-decision" }, { label: "Portfolio", href: "/portfolio-live" }]}
            />
          </div>
        )}
      </Section>

      {/* ─── Error State ───────────────────────────────────────────────────── */}
      <Section title="ErrorState" id="error-state">
        <div style={{ marginBottom: 8 }}><CodeChip>{`import { ErrorState } from "@/components/ds"`}</CodeChip></div>
        <Row gap={8}>
          {(["network","permission","unavailable","offline"] as const).map(kind => (
            <button
              key={kind}
              onClick={() => setShowError(v => !v)}
              style={{ padding: "5px 12px", fontSize: FONT_SIZE.xs, borderRadius: 6, cursor: "pointer", background: SURFACE.card, border: `1px solid ${SURFACE.border}`, color: TEXT.secondary }}
            >
              {kind}
            </button>
          ))}
        </Row>
        {showError && (
          <div style={{ background: SURFACE.card, border: `1px solid ${SURFACE.border}`, borderRadius: 10 }}>
            <ErrorState
              kind="network"
              onRetry={() => setShowError(false)}
              diagnosticsHref="/observability"
              compact
            />
          </div>
        )}
      </Section>

      {/* ─── Loading Skeleton ──────────────────────────────────────────────── */}
      <Section title="LoadingSkeleton" id="loading-skeleton">
        <div style={{ marginBottom: 8 }}><CodeChip>{`import { Skeleton, KpiCardSkeleton, TableSkeleton, CardSkeleton } from "@/components/ds"`}</CodeChip></div>
        <Row gap={8}>
          <button
            onClick={() => setShowSkeleton(v => !v)}
            style={{ padding: "6px 14px", fontSize: FONT_SIZE.sm, borderRadius: 6, cursor: "pointer", background: SURFACE.card, border: `1px solid ${SURFACE.border}`, color: TEXT.secondary }}
          >
            {showSkeleton ? "Hide" : "Show"} Skeletons
          </button>
        </Row>
        {showSkeleton && (
          <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
            <div>
              <div style={{ fontSize: FONT_SIZE.xs, color: TEXT.muted, marginBottom: 8 }}>KpiCardSkeleton</div>
              <KpiCardSkeleton count={5} />
            </div>
            <div>
              <div style={{ fontSize: FONT_SIZE.xs, color: TEXT.muted, marginBottom: 8 }}>CardSkeleton</div>
              <div style={{ display: "flex", gap: 10 }}>
                <CardSkeleton lines={3} />
                <CardSkeleton lines={2} />
              </div>
            </div>
            <div>
              <div style={{ fontSize: FONT_SIZE.xs, color: TEXT.muted, marginBottom: 8 }}>TableSkeleton</div>
              <TableSkeleton rows={4} cols={5} />
            </div>
          </div>
        )}
      </Section>

      {/* ─── Data Table ────────────────────────────────────────────────────── */}
      <Section title="DataTable" id="data-table">
        <div style={{ marginBottom: 8 }}><CodeChip>{`import { DataTable } from "@/components/ds"`}</CodeChip></div>
        <DataTable
          columns={TRADE_COLUMNS}
          data={SAMPLE_TRADES}
          rowKey={(r) => r.symbol}
          pageSize={10}
          exportName="sample_trades"
        />
      </Section>

      {/* ─── Design Tokens ─────────────────────────────────────────────────── */}
      <Section title="Design Tokens Reference" id="tokens">
        <div style={{ marginBottom: 8 }}><CodeChip>{`import { AGENT_COLORS, STATUS_COLORS, SURFACE, TEXT, FONT_SIZE, FONT_WEIGHT, SPACE, RADIUS } from "@/lib/designTokens"`}</CodeChip></div>
        <div style={{ display: "flex", gap: 24, flexWrap: "wrap" }}>
          {[
            { label: "TEXT.primary",   value: TEXT.primary,   bg: SURFACE.card },
            { label: "TEXT.secondary", value: TEXT.secondary, bg: SURFACE.card },
            { label: "TEXT.muted",     value: TEXT.muted,     bg: SURFACE.card },
            { label: "SURFACE.page",   value: SURFACE.page,   bg: "#2d3348" },
            { label: "SURFACE.card",   value: SURFACE.card,   bg: "#2d3348" },
            { label: "SURFACE.border", value: SURFACE.border, bg: SURFACE.card },
          ].map(t => (
            <div key={t.label} style={{ background: t.bg, borderRadius: 6, padding: "8px 12px", minWidth: 140 }}>
              <div style={{ fontSize: FONT_SIZE.xs, color: TEXT.muted, marginBottom: 2 }}>{t.label}</div>
              <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                <div style={{ width: 14, height: 14, borderRadius: 3, background: t.value, border: "1px solid rgba(255,255,255,0.1)" }} />
                <code style={{ fontSize: FONT_SIZE.xs, color: TEXT.secondary, fontFamily: "monospace" }}>{t.value}</code>
              </div>
            </div>
          ))}
        </div>
      </Section>

    </div>
  );
}

