import React from "react";
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
  RotateCcw,
  FlaskConical,
  ShieldCheck,
  GitCompare,
  Settings2,
  Radar,
  Clock,
  Layers,
} from "lucide-react";
import { useTheme } from "@/components/theme-provider";
import { Button } from "@/components/ui/button";

interface AppLayoutProps {
  children: React.ReactNode;
}

export function AppLayout({ children }: AppLayoutProps) {
  const [location] = useLocation();
  const { theme, setTheme } = useTheme();

  const navGroups = [
    {
      label: "Overview",
      items: [
        { href: "/",               label: "Dashboard",      icon: BarChart3 },
        { href: "/market",         label: "Market",         icon: Globe2    },
        { href: "/market-scanner", label: "Market Scanner", icon: Radar     },
        { href: "/market-replay",  label: "Market Replay",  icon: Clock     },
      ],
    },
    {
      label: "Signals",
      items: [
        { href: "/signals",     label: "Signals",     icon: Activity },
        { href: "/ai-decision", label: "AI Decision", icon: Brain    },
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
      ],
    },
  ];

  return (
    <div className="flex h-screen w-full bg-background overflow-hidden text-foreground selection:bg-primary selection:text-primary-foreground">
      {/* Sidebar */}
      <aside className="w-64 flex-shrink-0 border-r border-border bg-sidebar flex flex-col justify-between">
        <div>
          <div className="h-16 flex items-center px-6 border-b border-border">
            <Terminal className="h-5 w-5 mr-3 text-primary" />
            <span className="font-mono font-bold tracking-tight text-lg text-sidebar-foreground">
              NSE TRADER
            </span>
          </div>
          <nav className="p-4 space-y-5">
            {navGroups.map((group) => (
              <div key={group.label}>
                <div className="px-3 mb-1.5 text-xs font-mono text-sidebar-foreground/30 uppercase tracking-widest">
                  {group.label}
                </div>
                <div className="space-y-0.5">
                  {group.items.map((item) => {
                    const Icon = item.icon;
                    const isActive = location === item.href;
                    return (
                      <Link
                        key={item.href}
                        href={item.href}
                        className={`flex items-center gap-3 px-3 py-2 rounded-md transition-colors font-medium text-sm ${
                          isActive
                            ? "bg-sidebar-accent text-sidebar-accent-foreground"
                            : "text-sidebar-foreground/70 hover:bg-sidebar-accent/50 hover:text-sidebar-foreground"
                        }`}
                        data-testid={`link-nav-${item.label.toLowerCase().replace(/\s/g, "-")}`}
                      >
                        <Icon className="h-4 w-4" />
                        {item.label}
                      </Link>
                    );
                  })}
                </div>
              </div>
            ))}
          </nav>
        </div>
        <div className="p-4 border-t border-border flex justify-between items-center">
          <div className="text-xs text-sidebar-foreground/50 font-mono">
            v0.5 - ACTIVE
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
      </aside>

      {/* Main Content */}
      <main className="flex-1 flex flex-col min-w-0 overflow-hidden bg-background relative">
        <div className="absolute inset-0 pointer-events-none bg-[radial-gradient(ellipse_at_top,_var(--tw-gradient-stops))] from-primary/5 via-background to-background" />
        <div className="flex-1 overflow-auto p-6 lg:p-8 z-10 relative">
          {children}
        </div>
      </main>
    </div>
  );
}
