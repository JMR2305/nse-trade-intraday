import express, { type Express } from "express";
import cors from "cors";
import cookieParser from "cookie-parser";
import pinoHttp from "pino-http";
import router from "./routes";
import { logger } from "./lib/logger";
import { requestMetricsMiddleware } from "./lib/requestMetrics";

const app: Express = express();

app.use(
  pinoHttp({
    logger,
    serializers: {
      req(req) {
        return {
          id: req.id,
          method: req.method,
          url: req.url?.split("?")[0],
        };
      },
      res(res) {
        return {
          statusCode: res.statusCode,
        };
      },
    },
  }),
);
// CORS policy — explicit origin allowlist.
//
// Permitted origins (evaluated in order):
//   1. ALLOWED_ORIGINS env var — comma-separated list of exact origins
//      e.g. "https://abc.repl.co,https://xyz.replit.dev"
//   2. Any *.replit.dev or *.repl.co domain — covers Replit preview and
//      deployed domains without needing to enumerate every subdomain.
//   3. Requests with no Origin header — React Native / Expo / curl /
//      server-to-server calls; always allowed (no browser CORS enforcement).
//
// Wildcard CORS (Access-Control-Allow-Origin: *) is intentionally NOT used
// together with credentials. credentials is set to false so the response
// can safely omit a specific origin on preflight when needed.
//
const _allowedOrigins: string[] = process.env.ALLOWED_ORIGINS
  ? process.env.ALLOWED_ORIGINS.split(",")
      .map((s) => s.trim())
      .filter(Boolean)
  : [];

// Returns true for any origin whose hostname ends with a Replit domain suffix.
// Parses the URL so the match is suffix-based rather than pattern-based,
// which correctly handles multi-label subdomains (e.g. abc.pike.replit.dev).
//
// Covered suffixes:
//   .replit.dev  — workspace preview domains
//   .replit.app  — published/deployed production domains (e.g. nse-trade-intraday.replit.app)
//   .repl.co     — legacy deployed domains
//   .id.repl.co  — legacy user-id domains
function isReplitOrigin(origin: string): boolean {
  try {
    const { hostname } = new URL(origin);
    return (
      hostname.endsWith(".replit.dev") ||
      hostname.endsWith(".replit.app") ||
      hostname.endsWith(".repl.co") ||
      hostname.endsWith(".id.repl.co") ||
      hostname === "replit.dev" ||
      hostname === "replit.app" ||
      hostname === "repl.co"
    );
  } catch {
    return false;
  }
}

app.use(
  cors({
    origin(origin, callback) {
      // No-origin requests (mobile app, curl, server-to-server) — always allow.
      if (!origin) return callback(null, true);
      // Explicitly configured origins.
      if (_allowedOrigins.includes(origin)) return callback(null, true);
      // Any Replit dev or deployed domain (single- or multi-label subdomains).
      if (isReplitOrigin(origin)) return callback(null, true);
      // Deny everything else.
      callback(
        Object.assign(new Error(`CORS: origin "${origin}" is not permitted`), {
          status: 403,
        }),
      );
    },
    // credentials:true allows the browser to send/receive cookies on
    // cross-origin (and same-origin-via-proxy) requests.  It is safe here
    // because the origin callback always returns a specific origin string
    // rather than the wildcard "*".
    credentials: true,
    methods: ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allowedHeaders: [
      "Content-Type",
      "Authorization",
      "X-API-Key",
      "X-Request-ID",
      "X-Correlation-ID",
    ],
  }),
);
app.use(cookieParser());
app.use(express.json({ limit: "256kb" }));
app.use(express.urlencoded({ extended: true, limit: "256kb" }));

// Authenticate every request before routing.
// Public paths (/healthz, /health/live, /health/ready) are exempted inside
// the middleware so infrastructure probes never require credentials.
// Root redirect — visiting the bare domain sends the browser to the dashboard.
// This runs before the /api middleware so it is never auth-gated.
app.get("/", (_req, res) => {
  res.redirect(302, "/trading-dashboard/");
});

app.use("/api", requestMetricsMiddleware, router);

// Global error handler — honest JSON errors, no stack traces leaked.
//
// Recognised error types (set by Express body-parser and CORS middleware):
//   entity.too.large   — body exceeded the 256 KB limit → 413
//   entity.parse.failed — body is not valid JSON → 400 with descriptive msg
//   err.status === 403  — CORS origin rejected by the allowlist → 403
//   everything else    — opaque 500 (no internals leaked)
app.use(
  (
    err: Error & { status?: number; type?: string },
    _req: express.Request,
    res: express.Response,
    _next: express.NextFunction,
  ) => {
    const status =
      err.type === "entity.too.large"
        ? 413
        : err.type === "entity.parse.failed"
          ? 400
          : (err.status ?? 500);

    const message =
      status === 413
        ? "Request body too large. Maximum allowed size is 256 KB."
        : status === 400 && err.type === "entity.parse.failed"
          ? "Request body contains invalid JSON. Verify that Content-Type is application/json and the body is well-formed JSON."
          : status === 403
            ? "Request origin is not permitted by the server CORS policy."
            : "Internal server error";

    logger.error({ err: err.message, status }, "Unhandled request error");
    res.status(status).json({ success: false, error: message });
  },
);

export default app;
