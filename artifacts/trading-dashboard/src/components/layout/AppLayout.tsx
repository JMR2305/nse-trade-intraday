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
} from "lucide-react";
import { useTheme } from "@/components/theme-provider";
import { Button } from "@/components/ui/button";

interface AppLayoutProps {
  children: React.ReactNode;
}

export function AppLayout({ children }: AppLayoutProps) {
  const [location] = useLocation();
  const { theme, setTheme } = useTheme();

  const navItems = [
    { href: "/", label: "Dashboard", icon: BarChart3 },
    { href: "/market", label: "Market", icon: Globe2 },
    { href: "/signals", label: "Signals", icon: Activity },
    { href: "/trades", label: "Trades", icon: History },
    { href: "/watchlist", label: "Watchlist", icon: Eye },
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
          <nav className="p-4 space-y-1">
            {navItems.map((item) => {
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
                  data-testid={`link-nav-${item.label.toLowerCase()}`}
                >
                  <Icon className="h-4 w-4" />
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </div>
        <div className="p-4 border-t border-border flex justify-between items-center">
           <div className="text-xs text-sidebar-foreground/50 font-mono">
             v1.0.4 - ACTIVE
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
