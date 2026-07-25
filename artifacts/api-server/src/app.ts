import express, { type Express } from "express";
import cors from "cors";
import pinoHttp from "pino-http";
import router from "./routes";
import { logger } from "./lib/logger";

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
// CORS policy: open to all origins (cors() default).
// Rationale: the API runs inside Replit's mTLS-secured proxy; all external traffic
// is already TLS-terminated and origin-validated by the platform. Scoping to the
// Replit dev domain would block Expo's bundler origin and add operational friction
// with no meaningful security gain in this paper-trading research environment.
// Re-evaluate before any live-trading deployment.
app.use(cors());
app.use(express.json({ limit: "256kb" }));
app.use(express.urlencoded({ extended: true, limit: "256kb" }));

app.use("/api", router);

// Global error handler — honest JSON errors, no stack traces leaked.
app.use(
  (
    err: Error & { status?: number; type?: string },
    _req: express.Request,
    res: express.Response,
    _next: express.NextFunction,
  ) => {
    const status = err.status ?? (err.type === "entity.too.large" ? 413 : 500);
    logger.error({ err: err.message, status }, "Unhandled request error");
    res.status(status).json({
      success: false,
      error: status === 413 ? "Request body too large" : "Internal server error",
    });
  },
);

export default app;
