/** @type {import('next').NextConfig} */

// BASE_PATH is injected by the Replit artifact system (e.g. "/trading-document-hub/").
// Next.js basePath must NOT have a trailing slash.
const rawBasePath = process.env.BASE_PATH ?? '';
const basePath = rawBasePath.replace(/\/$/, '');

const nextConfig = {
  // Route all app paths under the artifact prefix so the Replit proxy routes correctly.
  basePath,

  // Serve static assets from the same prefix.
  assetPrefix: basePath || undefined,

  images: {
    // Disable Next.js image optimisation — not needed for a document hub with
    // mostly static thumbnails, and avoids server-side sharp dependency in dev.
    unoptimized: true,
  },

  // Static export for Replit autoscale deployment.
  // The Replit artifact system expects pre-built static files at dist/public/.
  // Next.js exports to out/ by default; the build script moves it to dist/public/.
  output: 'export',

  // Trailing slashes make each page exportable as page/index.html, which
  // works correctly with Replit's static file server.
  trailingSlash: true,

  // TypeScript errors must be visible — do NOT set ignoreBuildErrors.
  // (Removed from original V0 config intentionally.)
  //
  // NOTE: Next.js 16.2.11 turbopack mis-infers the workspace root in pnpm
  // monorepos (it walks up to find pnpm-workspace.yaml and then cannot
  // resolve next/package.json from the app/ subdirectory).  The dev and
  // build scripts use --webpack to sidestep this until upstream fixes it.
};

export default nextConfig;
