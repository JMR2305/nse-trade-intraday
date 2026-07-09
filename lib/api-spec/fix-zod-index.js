/**
 * Post-processes lib/api-zod/src/index.ts after orval codegen.
 *
 * Problem: orval v8 generates duplicate export * lines (double + single quotes)
 * AND exports both zod const validators (./generated/api) and TypeScript type
 * aliases (./generated/types) under the same names, causing TS2308 ambiguity.
 *
 * Fix: keep only the ./generated/api export (zod validators).
 * TypeScript types are already available from @workspace/api-client-react.
 */
const fs   = require("fs");
const path = require("path");

const target = path.resolve(__dirname, "..", "api-zod", "src", "index.ts");

if (!fs.existsSync(target)) {
  process.exit(0);
}

// Keep only the api validator export, deduplicated
const content = `export * from "./generated/api";\n`;
fs.writeFileSync(target, content, "utf8");
console.log("[fix-zod-index] Rewrote", target, "— validators only");
