import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // Exclude compiled output and node_modules from test discovery.
    // The dist/ directory mirrors src/ so compiled *.test.js files would
    // otherwise be double-counted alongside the TypeScript source tests.
    exclude: [
      "**/dist/**",
      "**/node_modules/**",
    ],
  },
});
