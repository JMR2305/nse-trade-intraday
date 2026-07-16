/**
 * freshness_audit.mjs — Phase 19C production-verification audit.
 *
 * Visits every registered dashboard route, verifies the DataFreshnessBar is
 * actually rendered (not just imported), extracts the displayed scan_id /
 * timestamps / provider / status, captures a screenshot per page, and writes:
 *   <out>/freshness_report.json
 *   <out>/freshness_report.csv
 *   <out>/screenshots/<page>.png
 *
 * Usage: node freshness_audit.mjs <output_dir> [baseUrl]
 * Prints a JSON summary to stdout.
 */

import puppeteer from "puppeteer-core";
import { execSync } from "child_process";
import fs from "fs";
import path from "path";

const OUT_DIR = process.argv[2];
const BASE = process.argv[3] || "http://localhost:80/trading-dashboard";
if (!OUT_DIR) {
  console.log(JSON.stringify({ error: "usage: node freshness_audit.mjs <output_dir> [baseUrl]" }));
  process.exit(1);
}
const SHOT_DIR = path.join(OUT_DIR, "screenshots");
const ROW_DIR = path.join(OUT_DIR, "rows");
fs.mkdirSync(SHOT_DIR, { recursive: true });
fs.mkdirSync(ROW_DIR, { recursive: true });

const PAGES = [
  ["TradeDecisions", "/"],
  ["PortfolioManager", "/portfolio-manager"],
  ["Dashboard", "/dashboard"],
  ["Market", "/market"],
  ["MarketScanner", "/market-scanner"],
  ["MarketReplay", "/market-replay"],
  ["Signals", "/signals"],
  ["AIDecision", "/ai-decision"],
  ["TradeReplay", "/trade-replay"],
  ["AllTrades", "/trades"],
  ["Watchlist", "/watchlist"],
  ["Backtest", "/backtest"],
  ["Validate", "/validate"],
  ["StrategyLab", "/strategy-lab"],
  ["Optimizer", "/optimizer"],
  ["PaperBasketTest", "/paper-basket-test"],
  ["TradeIntelligence", "/trade-intelligence"],
  ["HistoricalKnowledge", "/historical-knowledge"],
  ["LearningInsights", "/learning-insights"],
  ["LearningReview", "/learning-review"],
  ["PatternQuality", "/pattern-quality"],
  ["FeatureImportance", "/feature-importance"],
  ["WalkForwardValidation", "/walk-forward"],
  ["ResearchFactory", "/experiments"],
  ["ResearchIntelligence", "/research-intelligence"],
  ["StrategyEvolution", "/strategy-evolution"],
  ["LiveDataHealth", "/live-data-health"],
  ["BrokerExecution", "/broker-execution"],
  ["AICopilot", "/ai-copilot"],
  ["Notifications", "/notifications"],
  ["PerformanceAnalytics", "/performance-analytics"],
  ["Settings", "/settings"],
  ["RiskManagement", "/risk"],
  ["PortfolioRiskAnalytics", "/portfolio-risk"],
  ["Phase12Intelligence", "/phase12"],
  ["Phase13InstitutionalAI", "/phase13"],
  ["LearningGovernance", "/learning"],
  ["PaperTradingValidation", "/validation"],
  ["SystemValidation", "/system-validation"],
  ["ResearchNotebook", "/research-notebook"],
  ["KiteConnect", "/kite-connect"],
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
  const rows = [];
  try {
    let page = await browser.newPage();
    await page.setViewport({ width: 1440, height: 900 });
    for (const [name, route] of PAGES) {
      // Recover from crashed/detached tabs by re-opening a fresh page.
      if (page.isClosed() || page.mainFrame().detached) {
        page = await browser.newPage();
        await page.setViewport({ width: 1440, height: 900 });
      }
      const rowFile = path.join(ROW_DIR, `${name}.json`);
      if (fs.existsSync(rowFile)) {
        rows.push(JSON.parse(fs.readFileSync(rowFile, "utf8")));
        continue;
      }
      const url = `${BASE}${route}`;
      const row = {
        page_name: name,
        route,
        freshness_component_type: "MISSING",
        scan_id: null,
        scan_timestamp: null,
        quote_timestamp: null,
        provider: null,
        status: null,
        consistent: null,
        verified_at: new Date().toISOString(),
      };
      try {
        await page.goto(url, { waitUntil: "domcontentloaded", timeout: 25000 });
        // Pages poll forever — never use networkidle. Wait for the bar itself
        // (slow pages sit on a loading spinner for up to ~60s first).
        await page
          .waitForSelector('[data-testid="data-freshness-bar"]', { timeout: 60000 })
          .catch(() => undefined);
        await new Promise((r) => setTimeout(r, 1500));
        const info = await page.evaluate(() => {
          const bar = document.querySelector('[data-testid="data-freshness-bar"]');
          if (!bar) return null;
          const text = bar.textContent || "";
          const rect = bar.getBoundingClientRect();
          const visible = rect.width > 0 && rect.height > 0;
          // Expand the detail panel if the toggle exists.
          const btn = bar.querySelector('[data-testid="button-freshness-toggle"]');
          let detail = "";
          if (btn) {
            btn.click();
            detail = bar.textContent || "";
            btn.click();
          }
          return { text, detail, visible };
        });
        if (info && info.visible) {
          const t = info.detail || info.text;
          if (/No live dataset used on this page/.test(t)) {
            row.freshness_component_type = "NoLiveDataset";
            row.status = "N/A";
          } else if (/HISTORICAL/.test(info.text)) {
            row.freshness_component_type = "HistoricalDatasetFreshness";
            row.status = "HISTORICAL";
            const upd = t.match(/Updated:\s*([^L]+?)(?:Latest|Sample|$)/);
            row.scan_timestamp = upd ? upd[1].trim() : null;
          } else {
            row.freshness_component_type = "DataFreshnessBar";
            const id = t.match(/Scan ID:\s*([a-f0-9]+)/i) || info.text.match(/ID:\s*([a-f0-9]+)/i);
            row.scan_id = id ? id[1] : null;
            const scan = info.text.match(/Scan:\s*([^Q|]+?)(?:Quotes|Age)/);
            row.scan_timestamp = scan ? scan[1].trim() : null;
            const quote = info.text.match(/Quotes:\s*(.+?)Age/);
            row.quote_timestamp = quote ? quote[1].trim() : null;
            const prov = t.match(/Provider:\s*([^\n]+?)(?:Coverage|$)/);
            row.provider = prov ? prov[1].trim() : null;
            const st = info.text.match(/Data:\s*(\w+)/);
            row.status = st ? st[1] : null;
          }
        }
        await page.screenshot({ path: path.join(SHOT_DIR, `${name}.png`), type: "png" });
      } catch (e) {
        row.status = `ERROR: ${String(e).slice(0, 120)}`;
        try {
          await page.close().catch(() => undefined);
        } finally {
          page = await browser.newPage();
          await page.setViewport({ width: 1440, height: 900 });
        }
      }
      fs.writeFileSync(rowFile, JSON.stringify(row));
      rows.push(row);
    }
  } finally {
    await browser.close();
  }

  // scan_id consistency across all live scan pages
  const ids = [...new Set(rows.filter((r) => r.scan_id).map((r) => r.scan_id.slice(0, 8)))];
  const consistent = ids.length <= 1;
  for (const r of rows) {
    if (r.freshness_component_type === "DataFreshnessBar") r.consistent = consistent;
  }

  fs.writeFileSync(path.join(OUT_DIR, "freshness_report.json"), JSON.stringify({ shared_scan_ids: ids, consistent, pages: rows }, null, 2));
  const headers = ["page_name", "route", "freshness_component_type", "scan_id", "scan_timestamp", "quote_timestamp", "provider", "status", "consistent", "verified_at"];
  const csv = [headers.join(",")].concat(
    rows.map((r) => headers.map((h) => JSON.stringify(r[h] ?? "")).join(",")),
  ).join("\n");
  fs.writeFileSync(path.join(OUT_DIR, "freshness_report.csv"), csv);

  const missing = rows.filter((r) => r.freshness_component_type === "MISSING");
  console.log(JSON.stringify({
    audited: rows.length,
    missing: missing.map((m) => m.page_name),
    shared_scan_ids: ids,
    consistent,
    report: path.join(OUT_DIR, "freshness_report.json"),
  }));
};

main().catch((e) => {
  console.log(JSON.stringify({ error: String(e).slice(0, 300) }));
  process.exit(1);
});
