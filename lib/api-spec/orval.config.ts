import { defineConfig, InputTransformerFn } from "orval";
import path from "path";

const root = path.resolve(__dirname, "..", "..");
const apiClientReactSrc = path.resolve(root, "lib", "api-client-react", "src");
const apiZodSrc = path.resolve(root, "lib", "api-zod", "src");

// Our exports make assumptions about the title of the API being "Api" (i.e. generated output is `api.ts`).
const titleTransformer: InputTransformerFn = (config) => {
  config.info ??= {};
  config.info.title = "Api";

  return config;
};

export default defineConfig({
  "api-client-react": {
    input: {
      target: "./openapi.yaml",
      override: {
        transformer: titleTransformer,
      },
    },
    output: {
      // Root cause fix: orval's split mode writes a barrel index.ts at the
      // workspace root that is OUTSIDE the clean:true zone (which only wipes
      // the target subfolder).  On every subsequent codegen run orval APPENDS
      // new export lines to that barrel instead of overwriting it, producing
      // duplicate exports and TS2308 "ambiguous re-export" errors.
      //
      // Fix: set workspace to src/generated/ (the same folder that was
      // previously named by `target: "generated"`).  All generated files
      // (api.ts, api.schemas.ts, split operation files) land in the same
      // place as before.  The orval-written barrel index.ts now also lands
      // inside src/generated/ — well within the clean:true zone — so it is
      // wiped and rewritten cleanly on every run.  The manually-maintained
      // src/index.ts (which re-exports generated files plus custom-fetch
      // helpers) sits outside workspace and is never touched by orval.
      workspace: path.resolve(apiClientReactSrc, "generated"),
      target: ".",
      client: "react-query",
      mode: "split",
      baseUrl: "/api",
      clean: true,
      prettier: true,
      override: {
        fetch: {
          includeHttpResponseReturnType: false,
        },
        mutator: {
          path: path.resolve(apiClientReactSrc, "custom-fetch.ts"),
          name: "customFetch",
        },
      },
    },
  },
  zod: {
    input: {
      target: "./openapi.yaml",
      override: {
        transformer: titleTransformer,
      },
    },
    output: {
      // Same root cause fix as api-client-react above.
      // schemas.path is relative to workspace; "types" resolves to
      // src/generated/types/ — the same location as before.
      //
      // indexFiles: false is also required for the zod output specifically.
      // orval generates two overlapping export namespaces for each schema:
      //   - api.ts:          export const BuildHistoricalKnowledgeBody = zod.object(...)
      //   - types/*.ts:      export type  BuildHistoricalKnowledgeBody = { ... }
      // The barrel index.ts re-exports both (`export * from './api'` and
      // `export * from './types'`), which triggers TS2308 "already exported"
      // errors.  Disabling the barrel prevents the conflict.  The manually-
      // maintained src/index.ts already exports only from `./generated/api`
      // (the Zod schemas), which is all consumers need.
      workspace: path.resolve(apiZodSrc, "generated"),
      client: "zod",
      target: ".",
      schemas: { path: "types", type: "typescript" },
      mode: "split",
      clean: true,
      prettier: true,
      indexFiles: false,
      override: {
        zod: {
          coerce: {
            query: ['boolean', 'number', 'string'],
            param: ['boolean', 'number', 'string'],
            body: ['bigint', 'date'],
            response: ['bigint', 'date'],
          },
        },
        useDates: true,
        useBigInt: true,
      },
    },
  },
});
