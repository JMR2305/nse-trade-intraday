/**
 * AppLayout — ApexQuant AI platform shell.
 *
 * Preserved from original:
 *  - All navigation items, groups and hrefs (wouter routing)
 *  - useReconciliationBadge (badge on Broker & Execution)
 *  - LiveMarketTicker, StaleScanBanner, CopilotPanel
 *  - useTheme / theme toggle
 *  - Mobile sidebar drawer
 *
 * New in this revision:
 *  - Warm cream / dark-navy theme via updated CSS vars
 *  - Collapsible desktop sidebar (icon-only collapsed mode)
 *  - Glassmorphism top-bar
 *  - Rounded active-indicator (left accent bar + tinted bg)
 *  - Logo component instead of text + icon
 *  - Ambient background mesh on main canvas
 */
import React, { useState } from "react";
import { Link, useLocation } from "wouter";
import { useReconciliationBadge } from "@/hooks/useReconciliationBadge";
import {
  BarChart3,
  Activity,
  History,
  Eye,
  Moon,
  Sun,
  Globe2,
  Brain,
  GraduationCap,
  RotateCcw,
  FlaskConical,
  ShieldCheck,
  GitCompare,
  Settings2,
  Radar,
  Clock,
  Layers,
  Database,
  BookOpenText,
  Dna,
  Gauge,
  Route,
  Target,
  Briefcase,
  TestTubes,
  Wifi,
  ShieldAlert,
  Bot,
  Bell,
  Microscope,
  Radio,
  Sunrise,
  Menu,
  X,
  PieChart,
  ChevronLeft,
  Search,
  TrendingUp,
  Zap,
} from "lucide-react";
import { useTheme } from "@/components/theme-provider";
import { Button } from "@/components/ui/button";
import CopilotPanel from "@/components/CopilotPanel";
import LiveMarketTicker from "@/components/LiveMarketTicker";
import { StaleScanBanner } from "@/components/Phase15SystemHealth";
import { Logo } from "@/components/brand/Logo";
import { cn } from "@/lib/utils";

interface AppLayoutProps {
  children: React.ReactNode;
}

// ── Navigation tree ────────────────────────────────────────────────
// Primary groups mirror the operator workflow: Operations → Trading →
// Risk → Analytics → AI & System.  Secondary / research pages are kept
// in two trailing groups so nothing is removed — just reorganised.

const navGroups = [
  {
    label: "Operations",
    items: [
      { href: "/dashboard",        label: "Dashboard",        icon: BarChart3   },
      { href: "/",                 label: "Trade Decisions",  icon: Target      },
      { href: "/market-scanner",      label: "Market Scanner",      icon: Radar    },
      { href: "/preopen-intelligence", label: "Pre-Open Intelligence", icon: Sunrise },
      { href: "/live-data-health",  label: "Live Data Health",  icon: Wifi       },
    ],
  },
  {
    label: "Trading",
    items: [
      { href: "/signals",          label: "Signals",          icon: Activity    },
      { href: "/signal-history",   label: "Signal History",   icon: History     },
      { href: "/portfolio-live",   label: "Portfolio",        icon: PieChart    },
      { href: "/broker-execution", label: "Broker & Execution",icon: ShieldAlert },
    ],
  },
  {
    label: "Risk",
    items: [
      { href: "/portfolio-risk",    label: "Portfolio Risk",    icon: ShieldCheck },
      { href: "/portfolio-manager", label: "Portfolio Manager", icon: Briefcase   },
    ],
  },
  {
    label: "Analytics",
    items: [
      { href: "/portfolio-performance",   label: "Portfolio Performance",  icon: TrendingUp },
      { href: "/strategy-intelligence",  label: "Strategy Intelligence",  icon: Zap        },
      { href: "/performance-analytics", label: "Performance Analytics", icon: BarChart3 },
      { href: "/preopen-accuracy",      label: "Pre-Open Accuracy",     icon: Target    },
      { href: "/signal-validation",     label: "Signal Validation",     icon: Activity  },
      { href: "/execution-quality",     label: "Execution Quality",     icon: Gauge     },
      { href: "/market-replay",         label: "Market Replay",         icon: Clock     },
    ],
  },
  {
    label: "AI & System",
    items: [
      { href: "/ai-decision",   label: "AI Decision",  icon: Brain    },
      { href: "/ai-copilot",    label: "AI Copilot",   icon: Bot      },
      { href: "/notifications", label: "Notifications", icon: Bell     },
    ],
  },
  {
    label: "Research",
    items: [
      { href: "/trade-replay",          label: "Trade Replay",            icon: RotateCcw     },
      { href: "/trades",                label: "All Trades",              icon: History       },
      { href: "/watchlist",             label: "Watchlist",               icon: Eye           },
      { href: "/backtest",              label: "Backtest",                icon: FlaskConical  },
      { href: "/validate",              label: "Validate",                icon: ShieldCheck   },
      { href: "/strategy-lab",          label: "Strategy Lab",            icon: GitCompare    },
      { href: "/optimizer",             label: "Optimizer",               icon: Settings2     },
      { href: "/paper-basket-test",     label: "Paper Basket Test",       icon: Layers        },
      { href: "/trade-intelligence",    label: "Trade Intelligence",      icon: Database      },
      { href: "/historical-knowledge",  label: "Historical Knowledge",    icon: BookOpenText  },
      { href: "/learning-insights",     label: "Learning Insights",       icon: Brain         },
      { href: "/learning-review",       label: "Learning Review",         icon: GraduationCap },
      { href: "/pattern-quality",       label: "Pattern Quality",         icon: Gauge         },
      { href: "/feature-importance",    label: "Feature Importance",      icon: BarChart3     },
      { href: "/walk-forward",          label: "Walk-Forward Validation", icon: Route         },
      { href: "/experiments",           label: "Research Factory",        icon: TestTubes     },
      { href: "/research-intelligence", label: "Research Intelligence",   icon: Brain         },
      { href: "/strategy-evolution",    label: "Strategy Evolution",      icon: Dna           },
      { href: "/phase12",               label: "Phase 12 Intelligence",   icon: Microscope    },
      { href: "/phase13",               label: "Phase 13 · Inst. AI",    icon: Microscope    },
      { href: "/learning",              label: "Learning & Governance",   icon: GraduationCap },
    ],
  },
  {
    label: "System Tools",
    items: [
      { href: "/phase4a-session",   label: "Phase 4A Operations",     icon: Activity    },
      { href: "/operator-status",   label: "Operator Status",         icon: ShieldCheck },
      { href: "/automation",        label: "Automation Health",       icon: Gauge       },
      { href: "/kite-connect",      label: "Kite Connect",            icon: Radio       },
      { href: "/market",            label: "Market Overview",         icon: Globe2      },
      { href: "/research-notebook", label: "Research Notebook",       icon: BookOpenText},
      { href: "/validation",        label: "Paper Trading Validation",icon: ShieldCheck },
      { href: "/system-validation", label: "System Validation",       icon: ShieldCheck },
      { href: "/risk",              label: "Risk Management",         icon: ShieldCheck },
      { href: "/settings",          label: "Settings",                icon: Settings2   },
    ],
  },
];

// ── Component ──────────────────────────────────────────────────────

export function AppLayout({ children }: AppLayoutProps) {
  const [location] = useLocation();
  const { theme, setTheme } = useTheme();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const reconciliationBadgeCount = useReconciliationBadge();

  // ── Sidebar nav content (shared by desktop + mobile drawer) ──

  const SidebarNav = ({ onNav }: { onNav?: () => void }) => (
    <nav className="flex-1 overflow-y-auto px-2 py-3 min-h-0">
      {navGroups.map((group) => (
        <div key={group.label} className="mb-4">
          {!collapsed && (
            <p className="mb-1.5 px-3 text-[10px] font-semibold uppercase tracking-[0.13em] text-muted-foreground/60 select-none">
              {group.label}
            </p>
          )}
          <ul className="space-y-0.5">
            {group.items.map((item) => {
              const Icon = item.icon;
              const isActive = location === item.href;
              const isBroker = item.href === "/broker-execution";
              const badgeCount = isBroker ? reconciliationBadgeCount : 0;

              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    onClick={onNav}
                    data-testid={`link-nav-${item.label.toLowerCase().replace(/\s/g, "-")}`}
                    className={cn(
                      "group relative flex w-full items-center gap-3 rounded-xl px-3 py-2 text-[13px] font-medium transition-all duration-150",
                      collapsed ? "justify-center px-0" : "",
                      isActive
                        ? "text-foreground"
                        : "text-muted-foreground/80 hover:text-foreground hover:bg-sidebar-accent/60",
                    )}
                  >
                    {/* Active indicator: left accent bar + tinted bg */}
                    {isActive && (
                      <>
                        <span className="absolute left-0 top-1/2 h-5 w-1 -translate-y-1/2 rounded-r-full bg-primary" />
                        <span className="absolute inset-0 rounded-xl bg-primary/8 ring-1 ring-inset ring-primary/15" />
                      </>
                    )}

                    <Icon
                      className={cn(
                        "relative h-[17px] w-[17px] shrink-0",
                        isActive ? "text-primary" : "text-muted-foreground/70 group-hover:text-foreground",
                      )}
                    />

                    {!collapsed && (
                      <span className="relative flex-1 truncate">{item.label}</span>
                    )}

                    {/* Reconciliation badge */}
                    {!collapsed && badgeCount > 0 && (
                      <span
                        className="relative ml-auto shrink-0 inline-flex items-center justify-center h-4 min-w-[1rem] rounded-full bg-red-500 text-[10px] font-bold text-white leading-none px-1"
                        data-testid="badge-reconciliation-count"
                      >
                        {badgeCount > 99 ? "99+" : badgeCount}
                      </span>
                    )}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}
    </nav>
  );

  // ── Desktop sidebar ──

  const DesktopSidebar = () => (
    <aside
      className={cn(
        "glass-strong relative z-30 hidden md:flex h-full flex-col border-r border-border/60 transition-[width] duration-300 ease-in-out",
        collapsed ? "w-[68px]" : "w-[240px]",
      )}
    >
      {/* Header: logo + collapse toggle */}
      <div className={cn(
        "flex h-14 shrink-0 items-center border-b border-border/60 px-4",
        collapsed ? "justify-center" : "justify-between",
      )}>
        <Logo showWordmark={!collapsed} size={26} />

        <button
          onClick={() => setCollapsed((c) => !c)}
          className={cn(
            "grid h-7 w-7 place-items-center rounded-lg text-muted-foreground/60 hover:bg-sidebar-accent hover:text-foreground transition",
            collapsed
              ? "absolute -right-3.5 top-5 z-50 border border-border bg-background shadow-sm"
              : "",
          )}
          aria-label="Toggle sidebar"
        >
          <ChevronLeft
            className={cn(
              "h-4 w-4 transition-transform duration-300",
              collapsed && "rotate-180",
            )}
          />
        </button>
      </div>

      {/* Nav */}
      <SidebarNav />

      {/* Footer: engine version + theme toggle */}
      <div className={cn(
        "flex shrink-0 items-center gap-2 border-t border-border/60 px-4 py-3",
        collapsed ? "justify-center" : "justify-between",
      )}>
        {!collapsed && (
          <span
            className="text-[10px] text-muted-foreground/50 font-mono truncate"
            data-testid="text-engine-version"
          >
            ApexQuant AI
          </span>
        )}
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 shrink-0 text-muted-foreground/70 hover:text-foreground"
          onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          data-testid="button-toggle-theme"
        >
          {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </Button>
      </div>
    </aside>
  );

  // ── Mobile sidebar drawer ──

  const MobileDrawer = () => (
    <>
      {mobileOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          {/* Backdrop */}
          <div
            className="absolute inset-0 bg-foreground/20 backdrop-blur-sm"
            onClick={() => setMobileOpen(false)}
          />

          {/* Drawer panel */}
          <aside className="absolute left-0 top-0 h-full w-[240px] flex flex-col border-r border-border/60 bg-sidebar shadow-pop animate-[fade-in-up_0.2s_ease-out_both]">
            <div className="flex h-14 shrink-0 items-center justify-between border-b border-border/60 px-4">
              <Logo showWordmark size={26} />
              <button
                onClick={() => setMobileOpen(false)}
                className="grid h-7 w-7 place-items-center rounded-lg text-muted-foreground/60 hover:bg-sidebar-accent hover:text-foreground transition"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            <SidebarNav onNav={() => setMobileOpen(false)} />

            <div className="flex shrink-0 items-center justify-between border-t border-border/60 px-4 py-3">
              <span className="text-[10px] text-muted-foreground/50 font-mono" data-testid="text-engine-version">
                ApexQuant AI
              </span>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8 text-muted-foreground/70"
                onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
                data-testid="button-toggle-theme"
              >
                {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
              </Button>
            </div>
          </aside>
        </div>
      )}
    </>
  );

  // ── Root layout ──

  return (
    <div className="flex h-screen w-full overflow-hidden bg-background text-foreground selection:bg-primary/15 selection:text-foreground">
      {/* Ambient background layers */}
      <div className="pointer-events-none absolute inset-0 -z-10 bg-mesh" />
      <div className="pointer-events-none absolute inset-0 -z-10 opacity-40 bg-grid-faint [background-size:56px_56px]" />

      {/* Desktop sidebar */}
      <DesktopSidebar />

      {/* Mobile drawer */}
      <MobileDrawer />

      {/* ── Main column ── */}
      <div className="flex min-w-0 flex-1 flex-col overflow-hidden">

        {/* Mobile top bar */}
        <div className="flex md:hidden h-12 shrink-0 items-center gap-2 border-b border-border/60 bg-background/80 backdrop-blur-sm px-4 z-20">
          <button
            onClick={() => setMobileOpen(true)}
            className="grid h-8 w-8 place-items-center rounded-lg border border-border bg-card text-muted-foreground hover:text-foreground transition"
          >
            <Menu className="h-4 w-4" />
          </button>
          <Logo showWordmark size={22} />

          {/* PAPER TRADING badge — always visible on mobile */}
          <span className="shrink-0 inline-flex items-center rounded-full border border-warn px-2 py-0.5 text-[9px] font-bold uppercase tracking-widest bg-warn-surface text-warn">
            Paper
          </span>

          <div className="ml-auto flex items-center gap-1">
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8 text-muted-foreground/70"
              onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
              data-testid="button-toggle-theme"
            >
              {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
            </Button>
          </div>
        </div>

        {/* Top bar — desktop: search + status pills */}
        <header className="glass-strong hidden md:flex h-13 shrink-0 items-center gap-3 border-b border-border/60 px-5 z-20">
          {/* Search */}
          <div className="relative flex-1 max-w-xs">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground/50" />
            <input
              placeholder="Search pages, symbols, strategies…"
              className="h-8 w-full rounded-lg border border-border bg-card/60 pl-8 pr-3 text-[12px] text-foreground placeholder:text-muted-foreground/50 focus:border-primary focus:outline-none focus:ring-1 focus:ring-primary/30 transition"
            />
          </div>

          <div className="flex-1" />

          {/* Market status */}
          <div className="hidden lg:flex items-center gap-2 rounded-lg border border-border bg-card/60 px-2.5 py-1">
            <span className="h-1.5 w-1.5 rounded-full bg-green-500 animate-[pulse-soft_2.8s_ease-in-out_infinite]" />
            <span className="text-[11px] font-medium text-muted-foreground">NSE</span>
            <span className="text-[11px] text-muted-foreground/40">·</span>
            <span className="text-[11px] font-semibold text-green-600 dark:text-green-400">OPEN</span>
          </div>

          {/* AI status */}
          <div className="hidden xl:flex items-center gap-1.5 rounded-lg border border-primary/20 bg-primary/8 px-2.5 py-1">
            <span className="h-1.5 w-1.5 rounded-full bg-primary animate-[pulse-soft_2.8s_ease-in-out_infinite]" />
            <span className="text-[11px] font-medium text-primary">AI Advisory Active</span>
          </div>

          {/* Theme toggle */}
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 text-muted-foreground/70 hover:text-foreground"
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            data-testid="button-toggle-theme"
          >
            {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
          </Button>
        </header>

        {/* Live tickers and banners */}
        <LiveMarketTicker />
        <StaleScanBanner />

        {/* Page content */}
        <main className="flex-1 overflow-y-auto p-4 md:p-6 lg:p-8 relative z-10">
          <div className="mx-auto max-w-[1440px]">
            {children}
          </div>
        </main>

        {/* AI Copilot panel */}
        <CopilotPanel />
      </div>
    </div>
  );
}
