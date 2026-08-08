import type { NextFunction, Request, Response } from "express";

/**
 * Lightweight in-process API request-duration tracker.
 *
 * Records the duration of every /api request in a fixed-size ring buffer and
 * exposes rolling p50/p95/avg over the most recent samples. This backs the
 * "API Response" figure on the Live Session Monitor, replacing the scan
 * provider latency which measured something else entirely.
 */

const CAPACITY = 1000;
const buffer = new Float64Array(CAPACITY);
let count = 0; // total samples ever recorded
let index = 0; // next write position

export function requestMetricsMiddleware(
  req: Request,
  res: Response,
  next: NextFunction,
): void {
  const start = process.hrtime.bigint();
  res.on("finish", () => {
    const ms = Number(process.hrtime.bigint() - start) / 1e6;
    buffer[index] = ms;
    index = (index + 1) % CAPACITY;
    count += 1;
  });
  next();
}

export interface RequestMetricsSummary {
  sample_count: number;
  window_size: number;
  p50_ms: number | null;
  p95_ms: number | null;
  avg_ms: number | null;
}

export function getRequestMetrics(): RequestMetricsSummary {
  const n = Math.min(count, CAPACITY);
  if (n === 0) {
    return { sample_count: 0, window_size: CAPACITY, p50_ms: null, p95_ms: null, avg_ms: null };
  }
  const samples = Array.from(buffer.subarray(0, n)).sort((a, b) => a - b);
  const pct = (p: number) => samples[Math.min(n - 1, Math.floor((p / 100) * n))]!;
  const avg = samples.reduce((s, v) => s + v, 0) / n;
  return {
    sample_count: count,
    window_size: CAPACITY,
    p50_ms: Math.round(pct(50) * 10) / 10,
    p95_ms: Math.round(pct(95) * 10) / 10,
    avg_ms: Math.round(avg * 10) / 10,
  };
}
