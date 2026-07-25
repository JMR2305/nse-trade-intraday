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

  // TypeScript errors must be visible — do NOT set ignoreBuildErrors.
  // (Removed from original V0 config intentionally.)
};

export default nextConfig;
