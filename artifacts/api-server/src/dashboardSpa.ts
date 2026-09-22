import express, { type Express, type NextFunction } from "express";
import path from "node:path";

const DASHBOARD_BASE_PATH = "/trading-dashboard";
const DASHBOARD_ROUTE = /^\/trading-dashboard(?:\/.*)?$/;

export function dashboardDistPath(): string {
  return path.resolve(
    process.cwd(),
    "artifacts/trading-dashboard/dist/public",
  );
}

export function mountDashboardSpa(
  app: Express,
  dashboardDist = dashboardDistPath(),
): void {
  app.use(DASHBOARD_BASE_PATH, express.static(dashboardDist));

  app.get(DASHBOARD_ROUTE, (_req, res, next: NextFunction) => {
    res.sendFile(path.join(dashboardDist, "index.html"), (error) => {
      if (!error) return;
      const fileError = error as Error & { code?: string; status?: number };
      if (fileError.status === 404 || fileError.code === "ENOENT") {
        next();
        return;
      }
      next(error);
    });
  });
}
