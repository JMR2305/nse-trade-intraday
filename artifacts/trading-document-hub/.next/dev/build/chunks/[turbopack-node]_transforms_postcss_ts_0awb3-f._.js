module.exports = [
"[turbopack-node]/transforms/postcss.ts { CONFIG => \"[project]/artifacts/trading-document-hub/postcss.config.mjs [postcss] (ecmascript)\" } [postcss] (ecmascript, async loader)", ((__turbopack_context__) => {

__turbopack_context__.v((parentImport) => {
    return Promise.all([
  "chunks/node_modules__pnpm_0i35aoj._.js",
  "chunks/[root-of-the-server]__10s.5pl._.js"
].map((chunk) => __turbopack_context__.l(chunk))).then(() => {
        return parentImport("[turbopack-node]/transforms/postcss.ts { CONFIG => \"[project]/artifacts/trading-document-hub/postcss.config.mjs [postcss] (ecmascript)\" } [postcss] (ecmascript)");
    });
});
}),
];