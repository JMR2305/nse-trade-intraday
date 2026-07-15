import React, { useState } from "react";
import { Link, useLocation } from "wouter";
import {
  BarChart3,
  Activity,
  History,
  Eye,
  Terminal,
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
  Menu,
  X,
} from "lucide-react";
import { useTheme } from "@/components/theme-provider";
import { Button } from "@/components/ui/button";
import CopilotPanel from "@/components/CopilotPanel";
import LiveMarketTicker from "@/components/LiveMarketTicker";
import { StaleScanBanner } from "@/components/Phase15SystemHealth";

interface AppLayoutProps {
  children: React.ReactNode;
}

export function AppLayout({ children }: AppLayoutProps) {
  const [location] = useLocation();
  const { theme, setTheme } = useTheme();
  const [sidebarOpen, setSidebarOpen] = useState(false);

  const navGroups = [
    {
      label: "Overview",
      items: [
        { href: "/",               label: "Trade Decisions", icon: Target    },
        { href: "/portfolio-manager", label: "Portfolio Manager", icon: Briefcase },
        { href: "/dashboard",      label: "Dashboard",      icon: BarChart3 },
        { href: "/performance-analytics", label: "Performance Analytics", icon: BarChart3 },
        { href: "/portfolio-risk", label: "Portfolio Risk Analytics", icon: ShieldCheck },
        { href: "/market",          label: "Market",          icon: Globe2    },
        { href: "/market-scanner",  label: "Market Scanner",  icon: Radar     },
        { href: "/market-replay",   label: "Market Replay",   icon: Clock     },
        { href: "/live-data-health",  label: "Live Data Health",  icon: Wifi        },
        { href: "/broker-execution",  label: "Broker & Execution", icon: ShieldAlert },
      ],
    },
    {
      label: "Signals",
      items: [
        { href: "/signals",     label: "Signals",     icon: Activity },
        { href: "/ai-decision", label: "AI Decision", icon: Brain    },
        { href: "/ai-copilot",   label: "AI Copilot",    icon: Bot  },
        { href: "/notifications", label: "Notifications", icon: Bell },
      ],
    },
    {
      label: "Trades",
      items: [
        { href: "/trade-replay", label: "Trade Replay", icon: RotateCcw   },
        { href: "/trades",       label: "All Trades",   icon: History     },
        { href: "/watchlist",    label: "Watchlist",    icon: Eye         },
        { href: "/backtest",     label: "Backtest",     icon: FlaskConical },
        { href: "/validate",     label: "Validate",     icon: ShieldCheck  },
        { href: "/strategy-lab", label: "Strategy Lab",  icon: GitCompare   },
        { href: "/optimizer",    label: "Optimizer",     icon: Settings2    },
        { href: "/paper-basket-test", label: "Paper Basket Test", icon: Layers },
        { href: "/trade-intelligence", label: "Trade Intelligence", icon: Database },
        { href: "/historical-knowledge", label: "Historical Knowledge", icon: BookOpenText },
        { href: "/learning-insights", label: "Learning Insights", icon: Brain },
        { href: "/learning-review", label: "Learning Review", icon: GraduationCap },
        { href: "/pattern-quality", label: "Pattern Quality", icon: Gauge },
        { href: "/feature-importance", label: "Feature Importance", icon: BarChart3 },
        { href: "/walk-forward", label: "Walk-Forward Validation", icon: Route },
        { href: "/experiments",  label: "Research Factory",        icon: TestTubes },
        { href: "/research-intelligence", label: "Research Intelligence", icon: Brain },
        { href: "/strategy-evolution", label: "Strategy Evolution", icon: Dna },
        { href: "/phase12", label: "Phase 12 Intelligence", icon: Microscope },
        { href: "/phase13", label: "Phase 13 · Inst. AI", icon: Microscope },
        { href: "/learning", label: "Learning & Governance", icon: GraduationCap },
      ],
    },
    {
      label: "System",
      items: [
        { href: "/research-notebook", label: "Research Notebook", icon: BookOpenText },
        { href: "/kite-connect", label: "Kite Connect", icon: Radio },
        { href: "/validation", label: "Paper Trading Validation", icon: ShieldCheck },
        { href: "/system-validation", label: "System Validation", icon: ShieldCheck },
        { href: "/risk", label: "Risk Management", icon: ShieldCheck },
        { href: "/settings", label: "Settings", icon: Settings2 },
      ],
    },
  ];

  const navContent = (
    <>
      <div className="flex-1 overflow-y-auto min-h-0">
        <nav className="p-3 space-y-3">
          {navGroups.map((group) => (
            <div key={group.label}>
              <div className="px-3 mb-1 text-xs font-mono text-sidebar-foreground/30 uppercase tracking-widest">
                {group.label}
              </div>
              <div className="space-y-0">
                {group.items.map((item) => {
                  const Icon = item.icon;
                  const isActive = location === item.href;
                  return (
                    <Link
                      key={item.href}
                      href={item.href}
                      onClick={() => setSidebarOpen(false)}
                      className={`flex items-center gap-3 px-3 py-1.5 rounded-md transition-colors font-medium text-sm ${
                        isActive
                          ? "bg-sidebar-accent text-sidebar-accent-foreground"
                          : "text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground"
                      }`}
                      data-testid={`link-nav-${item.label.toLowerCase().replace(/\s/g, "-")}`}
                    >
                      <Icon className="h-4 w-4 flex-shrink-0" />
                      <span className="truncate">{item.label}</span>
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>
      </div>
      <div className="px-4 py-2 border-t border-border flex justify-between items-center flex-shrink-0">
        <div className="text-xs text-sidebar-foreground/50 font-mono" data-testid="text-engine-version">
          Research Engine v1.0
        </div>
        <Button
          variant="ghost"
          size="icon"
          className="h-8 w-8 text-sidebar-foreground/70"
          onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
          data-testid="button-toggle-theme"
        >
          {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </Button>
      </div>
    </>
  );

  return (
    <div className="flex h-screen w-full bg-background overflow-hidden text-foreground selection:bg-primary selection:text-primary-foreground">
      {/* Mobile overlay */}
      {sidebarOpen && (
        <div
          className="fixed inset-0 z-40 bg-black/50 md:hidden"
          onClick={() => setSidebarOpen(false)}
        />
      )}

      {/* Sidebar — hidden on mobile, slide-in when open */}
      <aside
        className={`fixed md:relative z-50 md:z-auto h-full w-64 flex-shrink-0 border-r border-border bg-sidebar flex flex-col transition-transform duration-200
          ${sidebarOpen ? "translate-x-0" : "-translate-x-full md:translate-x-0"}`}
      >
        <div className="h-12 flex items-center px-4 md:px-6 border-b border-border flex-shrink-0 gap-2">
          <Terminal className="h-5 w-5 text-primary flex-shrink-0" />
          <span className="font-mono font-bold tracking-tight text-lg text-sidebar-foreground flex-1 truncate">
            NSE TRADER
          </span>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 text-sidebar-foreground/70 md:hidden flex-shrink-0"
            onClick={() => setSidebarOpen(false)}
          >
            <X className="h-4 w-4" />
          </Button>
        </div>
        {navContent}
      </aside>

      {/* Main Content */}
      <main className="flex-1 flex flex-col min-w-0 overflow-hidden bg-background relative">
        <div className="absolute inset-0 pointer-events-none bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-primary/5 via-background to-background" />
        {/* Mobile header bar with hamburger */}
        <div className="md:hidden flex items-center gap-3 px-4 h-12 border-b border-border bg-background/80 backdrop-blur-sm flex-shrink-0 z-10 relative">
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={() => setSidebarOpen(true)}
          >
            <Menu className="h-5 w-5" />
          </Button>
          <Terminal className="h-4 w-4 text-primary" />
          <span className="font-mono font-bold text-sm">NSE TRADER</span>
        </div>
        <LiveMarketTicker />
        <StaleScanBanner />
        <div className="flex-1 overflow-auto p-4 md:p-6 lg:p-8 z-10 relative">
          {children}
        </div>
        <CopilotPanel />
      </main>
    </div>
  );
}
