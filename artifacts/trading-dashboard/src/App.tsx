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
import SignalHistory from "@/pages/SignalHistory";
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
import PaperBasketTest from "@/pages/PaperBasketTest";
import TradeIntelligence from "@/pages/TradeIntelligence";
import HistoricalKnowledge from "@/pages/HistoricalKnowledge";
import LearningInsights from "@/pages/LearningInsights";
import LearningReview from "@/pages/LearningReview";
import PatternQuality from "@/pages/PatternQuality";
import FeatureImportance from "@/pages/FeatureImportance";
import WalkForwardValidation from "@/pages/WalkForwardValidation";
import TradeDecisions from "@/pages/TradeDecisions";
import PortfolioManager from "@/pages/PortfolioManager";
import PortfolioLive from "@/pages/PortfolioLive";
import ExperimentManager from "@/pages/ExperimentManager";
import ResearchIntelligence from "@/pages/ResearchIntelligence";
import StrategyEvolution from "@/pages/StrategyEvolution";
import LiveDataHealth from "@/pages/LiveDataHealth";
import BrokerExecution from "@/pages/BrokerExecution";
import AiCopilot from "@/pages/AiCopilot";
import Notifications from "@/pages/Notifications";
import PerformanceAnalytics from "@/pages/PerformanceAnalytics";
import Settings from "@/pages/Settings";
import RiskManagement from "@/pages/RiskManagement";
import PaperTradingValidation from "@/pages/PaperTradingValidation";
import SystemValidation from "@/pages/SystemValidation";
import ResearchNotebook from "@/pages/ResearchNotebook";
import KiteConnect from "@/pages/KiteConnect";
import PortfolioRiskAnalytics from "@/pages/PortfolioRiskAnalytics";
import Phase12Intelligence from "@/pages/Phase12Intelligence";
import Phase13Intelligence from "@/pages/Phase13Intelligence";
import LearningGovernance from "@/pages/LearningGovernance";
import AutomationHealth from "@/pages/AutomationHealth";
import OperatorStatus from "@/pages/OperatorStatus";
import Phase4ASession from "@/pages/Phase4ASession";
import PreOpenIntelligence from "@/pages/PreOpenIntelligence";
import PreOpenAccuracy from "@/pages/PreOpenAccuracy";
import SignalValidationPage from "@/pages/SignalValidationPage";
import ExecutionQualityPage from "@/pages/ExecutionQualityPage";
import PortfolioPerformance from "@/pages/PortfolioPerformance";
import StrategyIntelligence from "@/pages/StrategyIntelligence";
import AIPerformanceIntelligence from "@/pages/AIPerformanceIntelligence";
import ExecutiveDashboard from "@/pages/ExecutiveDashboard";
import StrategyOptimisation from "@/pages/StrategyOptimisation";
import AIOptimisation from "@/pages/AIOptimisation";
import RiskOptimisation from "@/pages/RiskOptimisation";
import LiveReadiness from "@/pages/LiveReadiness";
import MarketIntelligenceHub from "@/pages/MarketIntelligenceHub";
import EventIntelligence from "@/pages/EventIntelligence";
import MacroIntelligence from "@/pages/MacroIntelligence";
import { ConnectivityPanel } from "@/components/ConnectivityPanel";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // GET queries: one automatic retry on transient network failures.
      // This matches the mobile React Query config.
      retry: 1,
      staleTime: 30_000,
    },
    mutations: {
      // Mutations are never retried automatically.
      // Order-confirm calls in particular must never be silently replayed.
      retry: 0,
    },
  },
});

function Router() {
  return (
    <AppLayout>
      <Switch>
        <Route path="/" component={TradeDecisions} />
        <Route path="/portfolio-manager" component={PortfolioManager} />
        <Route path="/portfolio-live" component={PortfolioLive} />
        <Route path="/dashboard" component={Dashboard} />
        <Route path="/market" component={MarketOverview} />
        <Route path="/market-scanner" component={MarketScanner} />
        <Route path="/market-replay" component={MarketReplay} />
        <Route path="/signals" component={Signals} />
        <Route path="/signal-history" component={SignalHistory} />
        <Route path="/ai-decision" component={AiDecision} />
        <Route path="/trade-replay" component={TradeReplay} />
        <Route path="/trades" component={Trades} />
        <Route path="/watchlist" component={Watchlist} />
        <Route path="/backtest" component={Backtest} />
        <Route path="/validate" component={Validate} />
        <Route path="/strategy-lab" component={StrategyLab} />
        <Route path="/optimizer" component={Optimizer} />
        <Route path="/paper-basket-test" component={PaperBasketTest} />
        <Route path="/trade-intelligence" component={TradeIntelligence} />
        <Route path="/historical-knowledge" component={HistoricalKnowledge} />
        <Route path="/learning-insights" component={LearningInsights} />
        <Route path="/learning-review" component={LearningReview} />
        <Route path="/pattern-quality" component={PatternQuality} />
        <Route path="/feature-importance" component={FeatureImportance} />
        <Route path="/walk-forward" component={WalkForwardValidation} />
        <Route path="/experiments" component={ExperimentManager} />
        <Route path="/research-intelligence" component={ResearchIntelligence} />
        <Route path="/strategy-evolution" component={StrategyEvolution} />
        <Route path="/live-data-health" component={LiveDataHealth} />
        <Route path="/broker-execution" component={BrokerExecution} />
        <Route path="/ai-copilot" component={AiCopilot} />
        <Route path="/notifications" component={Notifications} />
        <Route path="/performance-analytics" component={PerformanceAnalytics} />
        <Route path="/settings" component={Settings} />
        <Route path="/risk" component={RiskManagement} />
        <Route path="/portfolio-risk" component={PortfolioRiskAnalytics} />
        <Route path="/phase12" component={Phase12Intelligence} />
        <Route path="/phase13" component={Phase13Intelligence} />
        <Route path="/learning" component={LearningGovernance} />
        <Route path="/automation" component={AutomationHealth} />
        <Route path="/validation" component={PaperTradingValidation} />
        <Route path="/system-validation" component={SystemValidation} />
        <Route path="/research-notebook" component={ResearchNotebook} />
        <Route path="/kite-connect" component={KiteConnect} />
        <Route path="/operator-status" component={OperatorStatus} />
        <Route path="/phase4a-session" component={Phase4ASession} />
        <Route path="/preopen-intelligence" component={PreOpenIntelligence} />
        <Route path="/preopen-accuracy" component={PreOpenAccuracy} />
        <Route path="/signal-validation" component={SignalValidationPage} />
        <Route path="/execution-quality" component={ExecutionQualityPage} />
        <Route path="/portfolio-performance" component={PortfolioPerformance} />
        <Route path="/strategy-intelligence" component={StrategyIntelligence} />
        <Route path="/ai-performance" component={AIPerformanceIntelligence} />
        <Route path="/executive-dashboard" component={ExecutiveDashboard} />
        <Route path="/strategy-optimisation" component={StrategyOptimisation} />
        <Route path="/ai-optimisation" component={AIOptimisation} />
        <Route path="/risk-optimisation" component={RiskOptimisation} />
        <Route path="/market-intelligence" component={MarketIntelligenceHub} />
        <Route path="/event-intelligence" component={EventIntelligence} />
        <Route path="/macro-intelligence" component={MacroIntelligence} />
        <Route path="/live-readiness" component={LiveReadiness} />
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
          <ConnectivityPanel />
        </TooltipProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}

export default App;
