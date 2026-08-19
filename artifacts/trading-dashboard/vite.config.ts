import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";
import runtimeErrorOverlay from "@replit/vite-plugin-runtime-error-modal";

const rawPort = process.env.PORT;

if (!rawPort) {
  throw new Error(
    "PORT environment variable is required but was not provided.",
  );
}

const port = Number(rawPort);

if (Number.isNaN(port) || port <= 0) {
  throw new Error(`Invalid PORT value: "${rawPort}"`);
}

const basePath = process.env.BASE_PATH;

if (!basePath) {
  throw new Error(
    "BASE_PATH environment variable is required but was not provided.",
  );
}

// Keep a visible build marker in the browser bundle. Static production builds
// receive APEXQUANT_BUILD_ID from the artifact build environment; it must be
// baked into the Vite bundle because static assets have no runtime env access.
// A missing production value remains visibly actionable instead of falsely
// claiming that a published bundle is a development build.
const buildId =
  process.env.APEXQUANT_BUILD_ID ??
  process.env.REPLIT_DEPLOYMENT ??
  process.env.REPLIT_DEPLOYMENT_ID ??
  process.env.BUILD_ID ??
  (process.env.NODE_ENV === "production" ? "production-unidentified" : "development");

export default defineConfig({
  base: basePath,
  define: {
    "import.meta.env.VITE_BUILD_ID": JSON.stringify(buildId),
  },
  plugins: [
    react(),
    tailwindcss(),
    runtimeErrorOverlay(),
    ...(process.env.NODE_ENV !== "production" &&
    process.env.REPL_ID !== undefined
      ? [
          await import("@replit/vite-plugin-cartographer").then((m) =>
            m.cartographer({
              root: path.resolve(import.meta.dirname, ".."),
            }),
          ),
          await import("@replit/vite-plugin-dev-banner").then((m) =>
            m.devBanner(),
          ),
        ]
      : []),
  ],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "src"),
      "@assets": path.resolve(import.meta.dirname, "..", "..", "attached_assets"),
    },
    dedupe: ["react", "react-dom"],
  },
  root: path.resolve(import.meta.dirname),
  build: {
    outDir: path.resolve(import.meta.dirname, "dist/public"),
    emptyOutDir: true,
  },
  server: {
    port,
    strictPort: true,
    host: "0.0.0.0",
    allowedHosts: true,
    fs: {
      strict: true,
    },
  },
  preview: {
    port,
    host: "0.0.0.0",
    allowedHosts: true,
  },
  test: {
    // globals:true exposes afterEach/beforeEach on globalThis so that
    // @testing-library/react v16 auto-cleanup fires correctly in every test file.
    globals: true,
    // Exclude Playwright E2E specs — those run via `pnpm test:e2e`, not Vitest.
    exclude: ["**/e2e/**", "**/node_modules/**", "**/dist/**"],
  },
});
