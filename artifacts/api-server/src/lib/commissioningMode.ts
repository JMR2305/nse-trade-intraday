import type { IRouter } from "express";

type RouterModule = { default: IRouter };
type ScanSchedulerModule = { startScanScheduler: () => void };
type BacktestSchedulerModule = { startBacktestScheduler: () => void };

interface RouterLoaders {
  normal: () => Promise<RouterModule>;
  commissioning: () => Promise<RouterModule>;
}

interface SchedulerLoaders {
  scan: () => Promise<ScanSchedulerModule>;
  backtest: () => Promise<BacktestSchedulerModule>;
}

const defaultRouterLoaders: RouterLoaders = {
  normal: () => import("../routes/index.js"),
  commissioning: () => import("../routes/commissioning.js"),
};

const defaultSchedulerLoaders: SchedulerLoaders = {
  scan: () => import("./scanScheduler.js"),
  backtest: () => import("./backtestScheduler.js"),
};

export function healthOnlyNoSchedulers(
  env: NodeJS.ProcessEnv = process.env,
): boolean {
  const raw = env["HEALTH_ONLY_NO_SCHEDULERS"];
  if (raw === undefined || raw === "false") return false;
  if (raw === "true") return true;
  throw new Error(
    "HEALTH_ONLY_NO_SCHEDULERS must be exactly true or false",
  );
}

export async function loadRouterForMode(
  healthOnly: boolean | undefined,
  loaders: RouterLoaders = defaultRouterLoaders,
): Promise<IRouter> {
  const loaded = healthOnly
    ? await loaders.commissioning()
    : await loaders.normal();
  return loaded.default;
}

export async function startSchedulersForMode(
  healthOnly: boolean | undefined,
  loaders: SchedulerLoaders = defaultSchedulerLoaders,
): Promise<void> {
  if (healthOnly) return;
  const [scan, backtest] = await Promise.all([
    loaders.scan(),
    loaders.backtest(),
  ]);
  scan.startScanScheduler();
  backtest.startBacktestScheduler();
}
