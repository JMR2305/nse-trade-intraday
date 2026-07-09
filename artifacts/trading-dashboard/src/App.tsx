import { Switch, Route, Router as WouterRouter } from "wouter";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Toaster } from "@/components/ui/toaster";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ThemeProvider } from "@/components/theme-provider";
import NotFound from "@/pages/not-found";
import { AppLayout } from "@/components/layout/AppLayout";
import Dashboard from "@/pages/Dashboard";
import MarketOverview from "@/pages/MarketOverview";
import Signals from "@/pages/Signals";
import Trades from "@/pages/Trades";
import Watchlist from "@/pages/Watchlist";
import AiDecision from "@/pages/AiDecision";
import TradeReplay from "@/pages/TradeReplay";
import Backtest from "@/pages/Backtest";
import Validate from "@/pages/Validate";
import StrategyLab from "@/pages/StrategyLab";
import Optimizer from "@/pages/Optimizer";
import MarketScanner from "@/pages/MarketScanner";
import MarketReplay from "@/pages/MarketReplay";

const queryClient = new QueryClient();

function Router() {
  return (
    <AppLayout>
      <Switch>
        <Route path="/" component={Dashboard} />
        <Route path="/market" component={MarketOverview} />
        <Route path="/market-scanner" component={MarketScanner} />
        <Route path="/market-replay" component={MarketReplay} />
        <Route path="/signals" component={Signals} />
        <Route path="/ai-decision" component={AiDecision} />
        <Route path="/trade-replay" component={TradeReplay} />
        <Route path="/trades" component={Trades} />
        <Route path="/watchlist" component={Watchlist} />
        <Route path="/backtest" component={Backtest} />
        <Route path="/validate" component={Validate} />
        <Route path="/strategy-lab" component={StrategyLab} />
        <Route path="/optimizer" component={Optimizer} />
        <Route component={NotFound} />
      </Switch>
    </AppLayout>
  );
}

function App() {
  return (
    <ThemeProvider defaultTheme="dark" storageKey="vite-ui-theme">
      <QueryClientProvider client={queryClient}>
        <TooltipProvider>
          <WouterRouter base={import.meta.env.BASE_URL.replace(/\/$/, "")}>
            <Router />
          </WouterRouter>
          <Toaster />
        </TooltipProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}

export default App;
