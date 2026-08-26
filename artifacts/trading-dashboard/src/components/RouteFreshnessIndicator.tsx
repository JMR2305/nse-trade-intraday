import DataFreshnessBar from "@/components/DataFreshnessBar";

type RouteFreshnessVariant = "scan" | "historical" | "none";

interface RouteFreshnessConfig {
  variant: RouteFreshnessVariant;
  datasetLabel?: string;
}

/**
 * Pages that predate the shared freshness component can declare their data
 * semantics here. Page-local DataFreshnessBar instances remain the source of
 * truth where they already exist; this fills only the otherwise-uncovered
 * route-level gap.
 */
export const ROUTE_FRESHNESS: Readonly<Record<string, RouteFreshnessConfig>> = {
  "/simulation-lab": { variant: "historical", datasetLabel: "Simulation dataset" },
  "/validation-dashboard": { variant: "historical", datasetLabel: "Validation dataset" },
  "/optimization-lab": { variant: "historical", datasetLabel: "Optimisation dataset" },
  "/validation": { variant: "historical", datasetLabel: "Paper-trading validation dataset" },
  "/preopen-intelligence": { variant: "scan" },
  "/preopen-accuracy": { variant: "historical", datasetLabel: "Pre-open accuracy dataset" },
  "/signal-validation": { variant: "historical", datasetLabel: "Signal-validation dataset" },
  "/execution-quality": { variant: "historical", datasetLabel: "Execution-quality dataset" },
  "/portfolio-performance": { variant: "historical", datasetLabel: "Portfolio-performance dataset" },
  "/strategy-intelligence": { variant: "historical", datasetLabel: "Strategy-intelligence dataset" },
  "/ai-performance": { variant: "historical", datasetLabel: "AI-performance dataset" },
  "/executive-dashboard": { variant: "historical", datasetLabel: "Executive analytics dataset" },
  "/strategy-optimisation": { variant: "historical", datasetLabel: "Strategy-optimisation dataset" },
  "/operator-analytics": { variant: "historical", datasetLabel: "Operator analytics dataset" },
  "/system-readiness": { variant: "none" },
  "/operational-intelligence": { variant: "none" },
  "/ai-optimisation": { variant: "historical", datasetLabel: "AI-optimisation dataset" },
  "/risk-optimisation": { variant: "historical", datasetLabel: "Risk-optimisation dataset" },
  "/market-intelligence": { variant: "scan" },
  "/event-intelligence": { variant: "historical", datasetLabel: "Event-intelligence dataset" },
  "/macro-intelligence": { variant: "historical", datasetLabel: "Macro-intelligence dataset" },
  "/explainable-ai": { variant: "historical", datasetLabel: "Explainability dataset" },
  "/research-lab": { variant: "historical", datasetLabel: "Research dataset" },
  "/observability": { variant: "none" },
  "/paper-analytics": { variant: "historical", datasetLabel: "Paper-trading analytics dataset" },
  "/risk-validation": { variant: "historical", datasetLabel: "Risk-validation dataset" },
  "/risk-decision-report": { variant: "historical", datasetLabel: "Risk-decision dataset" },
  "/operations-center": { variant: "none" },
  "/security-center": { variant: "none" },
  "/performance-center": { variant: "none" },
  "/deployment-center": { variant: "none" },
  "/command-center": { variant: "scan" },
  "/live-command-center": { variant: "scan" },
  "/investigation-center": { variant: "historical", datasetLabel: "Pipeline backtest dataset" },
  "/workspace": { variant: "none" },
  "/trading-timeline": { variant: "historical", datasetLabel: "Trading timeline dataset" },
  "/executive-reports": { variant: "historical", datasetLabel: "Executive report dataset" },
  "/design-system": { variant: "none" },
  "/agent-operations": { variant: "none" },
  "/agent-ai-decision": { variant: "historical", datasetLabel: "AI-decision dataset" },
  "/agent-execution": { variant: "historical", datasetLabel: "Execution-agent dataset" },
  "/agent-learning": { variant: "historical", datasetLabel: "Learning-agent dataset" },
  "/agent-knowledge": { variant: "historical", datasetLabel: "Knowledge-agent dataset" },
  "/pattern-explorer": { variant: "historical", datasetLabel: "Pattern dataset" },
  "/lessons-library": { variant: "historical", datasetLabel: "Lessons dataset" },
  "/knowledge-search": { variant: "historical", datasetLabel: "Knowledge-search dataset" },
  "/trade-memory": { variant: "historical", datasetLabel: "Trade-memory dataset" },
  "/live-readiness": { variant: "scan" },
  "/collab-graph": { variant: "none" },
  "/decision-lineage": { variant: "none" },
  "/autonomous-ops": { variant: "none" },
  "/system-health": { variant: "none" },
  "/agent-comm-monitor": { variant: "none" },
  "/collab-alerts": { variant: "none" },
  "/scalability-dashboard": { variant: "none" },
  "/supervisor-extended": { variant: "none" },
  "/paper-trading-summary": { variant: "scan" },
  "/paper-trading-portfolio": { variant: "scan" },
  "/paper-trading-recommendations": { variant: "scan" },
  "/paper-trading-replay": { variant: "historical", datasetLabel: "Paper-trading replay dataset" },
  "/paper-trading-reports": { variant: "historical", datasetLabel: "Paper-trading report dataset" },
  "/paper-trading-timeline": { variant: "historical", datasetLabel: "Paper-trading timeline dataset" },
  "/ai-paper-trader": { variant: "scan" },
  "/paper-learning": { variant: "historical", datasetLabel: "Paper-learning dataset" },
  "/replay": { variant: "historical", datasetLabel: "Replay dataset" },
  "/ai-investigation": { variant: "historical", datasetLabel: "Investigation dataset" },
  "/ai-operations-centre": { variant: "scan" },
  "/ai-learning-center": { variant: "historical", datasetLabel: "AI-learning dataset" },
  "/institutional-analytics": { variant: "historical", datasetLabel: "Institutional analytics dataset" },
  "/advisory": { variant: "historical", datasetLabel: "Advisory dataset" },
  "/market-data-incidents": { variant: "historical", datasetLabel: "Market-data authority incident history" },
  "/custom-universe-management": { variant: "historical", datasetLabel: "Versioned universe revisions" },
};

export function RouteFreshnessIndicator({ path }: { path: string }) {
  const config = ROUTE_FRESHNESS[path];
  if (!config) return null;

  return (
    <div className="mb-4" data-testid="route-freshness-indicator">
      <DataFreshnessBar
        variant={config.variant}
        datasetLabel={config.datasetLabel}
      />
    </div>
  );
}