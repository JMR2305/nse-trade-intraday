import { defineConfig } from "drizzle-kit";
import path from "path";
import fs from "fs";

if (!process.env.DATABASE_URL) {
  throw new Error("DATABASE_URL, ensure the database is provisioned");
}

// Defense-in-depth: even if someone runs `drizzle-kit push` directly, restrict
// drizzle's view to the tables it actually manages so it can never propose
// dropping the Python-managed production tables (scheduler state, settings,
// Kite tokens, evidence, scan runs, locks, ...).
const registry = JSON.parse(
  fs.readFileSync(path.join(__dirname, "protected-tables.json"), "utf8"),
);

export default defineConfig({
  // Relative paths: drizzle-kit mis-joins absolute `out` paths when reading
  // existing snapshots (".//home/..."). safe-migrate always runs with
  // cwd = lib/db, so relative paths are stable.
  schema: "./src/schema/index.ts",
  out: "./migrations",
  dialect: "postgresql",
  dbCredentials: {
    url: process.env.DATABASE_URL,
  },
  tablesFilter: registry.drizzleManaged,
});
