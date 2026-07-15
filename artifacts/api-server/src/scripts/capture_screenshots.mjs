/**
 * capture_screenshots.mjs — captures FULL-PAGE 1920px-wide PNG screenshots of
 * every registered dashboard page for the Phase Review Package.
 *
 * Usage: node capture_screenshots.mjs <output_dir>
 * Prints a JSON summary to stdout: { captured: [...], failed: [...] }
 */

import puppeteer from "puppeteer-core";
import { execSync } from "child_process";
import fs from "fs";
import path from "path";

const OUT_DIR = process.argv[2];
if (!OUT_DIR) {
  console.log(JSON.stringify({ error: "usage: node capture_screenshots.mjs <output_dir>" }));
  process.exit(1);
}
if (!process.env.RESUME) {
  fs.rmSync(OUT_DIR, { recursive: true, force: true });
}
fs.mkdirSync(OUT_DIR, { recursive: true });

const BASE = "http://localhost:80/trading-dashboard";

// Every real, registered route (from App.tsx). Ordered per the review spec;
// remaining real pages follow. Only pages that actually exist are captured.
const PAGES = [
  ["01_Dashboard", "/dashboard"],
  ["02_Market", "/market"],
  ["03_MarketScanner", "/market-scanner"],
  ["04_Signals", "/signals"],
  ["05_AIDecision", "/ai-decision"],
  ["06_PortfolioManager", "/portfolio-manager"],
  ["07_PortfolioRiskAnalytics", "/portfolio-risk"],
  ["08_AICopilot", "/ai-copilot"],
  ["09_NotificationCenter", "/notifications"],
  ["10_PerformanceAnalytics", "/performance-analytics"],
  ["11_LearningGovernance", "/learning"],
  ["12_LiveDataHealth", "/live-data-health"],
  ["13_BrokerExecution", "/broker-execution"],
  ["14_Settings", "/settings"],
  ["15_WalkForwardValidation", "/walk-forward"],
  ["16_StrategyLab", "/strategy-lab"],
  ["17_ResearchFactory", "/experiments"],
  ["18_TradeReplay", "/trade-replay"],
  ["19_HistoricalKnowledge", "/historical-knowledge"],
  ["20_StrategyEvolution", "/strategy-evolution"],
  ["21_PatternQuality", "/pattern-quality"],
  ["22_FeatureImportance", "/feature-importance"],
  ["23_TradeDecisions", "/"],
  ["24_MarketReplay", "/market-replay"],
  ["25_AllTrades", "/trades"],
  ["26_Watchlist", "/watchlist"],
  ["27_Backtest", "/backtest"],
  ["28_Validate", "/validate"],
  ["29_Optimizer", "/optimizer"],
  ["30_PaperBasketTest", "/paper-basket-test"],
  ["31_TradeIntelligence", "/trade-intelligence"],
  ["32_LearningInsights", "/learning-insights"],
  ["33_LearningReview", "/learning-review"],
  ["34_ResearchIntelligence", "/research-intelligence"],
  ["35_RiskManagement", "/risk"],
  ["36_Phase12Intelligence", "/phase12"],
  ["37_Phase13InstitutionalAI", "/phase13"],
  ["38_PaperTradingValidation", "/validation"],
  ["39_SystemValidation", "/system-validation"],
  ["40_ResearchNotebook", "/research-notebook"],
  ["41_KiteConnect", "/kite-connect"],
];

function chromiumPath() {
  try {
    return execSync("which chromium").toString().trim();
  } catch {
    return null;
  }
}

const main = async () => {
  const executablePath = chromiumPath();
  if (!executablePath) {
    console.log(JSON.stringify({ error: "chromium binary not found" }));
    process.exit(1);
  }
  const browser = await puppeteer.launch({
    executablePath,
    headless: true,
    args: ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"],
  });
  const captured = [];
  const failed = [];
  try {
    const page = await browser.newPage();
    await page.setViewport({ width: 1920, height: 1080 });
    for (const [name, route] of PAGES) {
      const url = `${BASE}${route}`;
      if (process.env.RESUME && fs.existsSync(path.join(OUT_DIR, `${name}.png`))) {
        captured.push({ page: name, route, file: path.join(OUT_DIR, `${name}.png`), skipped: true });
        continue;
      }
      try {
        await page.goto(url, { waitUntil: "domcontentloaded", timeout: 20000 });
        await new Promise((r) => setTimeout(r, 3000)); // let data load & charts animate in
        const file = path.join(OUT_DIR, `${name}.png`);
        await page.screenshot({ path: file, type: "png", fullPage: true });
        captured.push({ page: name, route, file });
      } catch (e) {
        failed.push({ page: name, route, error: String(e).slice(0, 200) });
      }
    }
  } finally {
    await browser.close();
  }
  console.log(JSON.stringify({ captured, failed }));
};

main().catch((e) => {
  console.log(JSON.stringify({ error: String(e).slice(0, 300) }));
  process.exit(1);
});
