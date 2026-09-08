// Isolated GET-only Task976 ZB5 shadow runtime; application routes are not imported.
import { spawn } from "node:child_process";
import { writeFileSync } from "node:fs";
import { createServer } from "node:http";
import { join } from "node:path";
import { monitorEventLoopDelay } from "node:perf_hooks";

function nextLagState(currentMs, longestMs, elapsedMs, lagMs) {
  const current = lagMs > 250 ? currentMs + elapsedMs : 0;
  return { current_ms: current, longest_ms: Math.max(longestMs, current) };
}
if (process.argv[2] === "--lag-sequence") {
  const sequence = JSON.parse(process.argv[3] ?? "[]");
  let state = { current_ms: 0, longest_ms: 0 };
  for (const [elapsedMs, lagMs] of sequence) {
    state = nextLagState(state.current_ms, state.longest_ms, elapsedMs, lagMs);
  }
  process.stdout.write(JSON.stringify(state));
  process.exit(0);
}

const port = Number(process.env.PORT);
const evidenceFile = process.env.TASK976_ZB5_NODE_EVIDENCE;
const pythonDir = process.env.TASK976_ZB5_PYTHON_DIR;
const pythonBin = process.env.TASK976_ZB5_PYTHON_BIN;
if (port !== 19776 || !evidenceFile || !pythonDir || !pythonBin) {
  throw new Error("exact ZB5 shadow configuration required");
}
const routes = new Map([
  ["/api/ops-centre/platform", "ops_centre_platform"],
  ["/api/portfolio/snapshot", "portfolio_snapshot"],
  ["/api/phase20/ledger", "phase20_ledger"],
  ["/api/universe/custom/status", "universe_custom_status"],
  ["/api/universe/custom/symbols", "universe_custom_symbols"],
]);
const delay = monitorEventLoopDelay({ resolution: 10 }); delay.enable();
const began = process.hrtime.bigint(); const beganCpu = process.cpuUsage();
let peakRss = 0; let peakHeap = 0; let activeChildren = 0; let maxActiveChildren = 0;
const children = new Set();
let lastSample = Date.now(); let sustainedLagMs = 0; let currentLagRunMs = 0;
const sampler = setInterval(() => {
  const m = process.memoryUsage(); peakRss = Math.max(peakRss, m.rss);
  peakHeap = Math.max(peakHeap, m.heapUsed);
  const now = Date.now(); const elapsed = now - lastSample;
  const lag = Math.max(0, elapsed - 50);
  const state = nextLagState(currentLagRunMs, sustainedLagMs, elapsed, lag);
  currentLagRunMs = state.current_ms; sustainedLagMs = state.longest_ms; lastSample = now;
}, 50);

function invoke(command) {
  return new Promise((resolve, reject) => {
    activeChildren += 1; maxActiveChildren = Math.max(maxActiveChildren, activeChildren);
    const child = spawn(pythonBin, [join(pythonDir, "main.py"), command],
      { cwd: pythonDir, env: process.env, stdio: ["ignore", "pipe", "ignore"] });
    children.add(child);
    let output = ""; const timer = setTimeout(() => child.kill("SIGTERM"), 5000);
    child.stdout.on("data", chunk => { output += chunk.toString(); });
    child.on("error", reject);
    child.on("close", code => {
      clearTimeout(timer); activeChildren -= 1; children.delete(child);
      if (code !== 0) return reject(new Error("shadow subprocess failed"));
      try { resolve(JSON.parse(output.trim().split(/\r?\n/).at(-1))); }
      catch { reject(new Error("invalid shadow response")); }
    });
  });
}
const server = createServer(async (request, response) => {
  response.setHeader("content-type", "application/json");
  if (request.method !== "GET") {
    response.writeHead(405).end(JSON.stringify({ error: "method blocked" })); return;
  }
  const path = new URL(request.url, "http://127.0.0.1").pathname;
  if (path === "/api/healthz") {
    response.writeHead(200).end(JSON.stringify({ ok: true, shadow: true })); return;
  }
  const command = routes.get(path);
  if (!command) {
    response.writeHead(404).end(JSON.stringify({ error: "route blocked" })); return;
  }
  try { response.writeHead(200).end(JSON.stringify(await invoke(command))); }
  catch { response.writeHead(500).end(JSON.stringify({ error: "shadow read failed" })); }
});
server.listen(port, "127.0.0.1");

function writeEvidence() {
  const cpu = process.cpuUsage(beganCpu); const ms = value => value / 1e6;
  writeFileSync(evidenceFile, JSON.stringify({
    elapsed_ms: Number(process.hrtime.bigint() - began) / 1e6,
    peak_rss_bytes: peakRss, peak_heap_bytes: peakHeap,
    cpu_user_ms: cpu.user / 1000, cpu_system_ms: cpu.system / 1000,
    event_loop_p50_ms: ms(delay.percentile(50)), event_loop_p95_ms: ms(delay.percentile(95)),
    event_loop_p99_ms: ms(delay.percentile(99)), event_loop_max_ms: ms(delay.max),
    active_children: activeChildren, max_active_children: maxActiveChildren,
    sustained_lag_ms: sustainedLagMs,
  }), { mode: 0o600 });
}
process.on("SIGUSR2", writeEvidence);
function stop() {
  clearInterval(sampler);
  for (const child of children) child.kill("SIGTERM");
  const hard = setTimeout(() => { for (const child of children) child.kill("SIGKILL"); }, 2000);
  const poll = setInterval(() => {
    if (children.size === 0) {
      clearTimeout(hard); clearInterval(poll); server.close(() => process.exit(0));
    }
  }, 25);
  hard.unref();
}
process.on("SIGTERM", stop); process.on("SIGINT", stop);
process.on("exit", () => { try { writeEvidence(); } catch {} });
