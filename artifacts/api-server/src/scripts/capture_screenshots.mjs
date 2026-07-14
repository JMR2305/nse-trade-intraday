/**
 * capture_screenshots.mjs — captures 1920x1080 PNG screenshots of every
 * dashboard page for the Phase Review Package.
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
fs.mkdirSync(OUT_DIR, { recursive: true });

const BASE = "http://localhost:80/trading-dashboard";

// Every real, registered route (from App.tsx) is captured.
const PAGES = [
  ["trade_decisions", "/"],
  ["portfolio_manager", "/portfolio-manager"],
  ["dashboard", "/dashboard"],
  ["market", "/market"],
  ["market_scanner", "/market-scanner"],
  ["market_replay", "/market-replay"],
  ["signals", "/signals"],
  ["ai_decision", "/ai-decision"],
  ["trade_replay", "/trade-replay"],
  ["all_trades", "/trades"],
  ["watchlist", "/watchlist"],
  ["backtest", "/backtest"],
  ["validate", "/validate"],
  ["strategy_lab", "/strategy-lab"],
  ["optimizer", "/optimizer"],
  ["paper_basket_test", "/paper-basket-test"],
  ["trade_intelligence", "/trade-intelligence"],
  ["historical_knowledge", "/historical-knowledge"],
  ["learning_insights", "/learning-insights"],
  ["learning_review", "/learning-review"],
  ["pattern_quality", "/pattern-quality"],
  ["feature_importance", "/feature-importance"],
  ["walk_forward", "/walk-forward"],
  ["research_factory_experiments", "/experiments"],
  ["research_intelligence", "/research-intelligence"],
  ["strategy_evolution", "/strategy-evolution"],
  ["live_data_health", "/live-data-health"],
  ["broker_execution", "/broker-execution"],
  ["ai_copilot", "/ai-copilot"],
  ["notifications", "/notifications"],
  ["performance_analytics", "/performance-analytics"],
  ["settings", "/settings"],
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
      try {
        await page.goto(url, { waitUntil: "domcontentloaded", timeout: 20000 });
        await new Promise((r) => setTimeout(r, 3000)); // let data load & charts animate in
        const file = path.join(OUT_DIR, `${name}.png`);
        await page.screenshot({ path: file, type: "png" });
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
