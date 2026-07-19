// ─────────────────────────────────────────────────────────────────────────────
// Batch 7D — DocManagement Upload Script
// Paste this into the browser console while logged in at intraday-india-ai.replit.app
// ─────────────────────────────────────────────────────────────────────────────

(async () => {
  const BATCH_ID = 4; // Batch 7D

  const FILES = [
    {
      displayName: "Batch 7D — Reference Package",
      documentType: "execution_package",
      description: "All 30 execution source + test files, database references, operational files, pyproject.toml, and the Kimi context document.",
      fetchUrl: "https://a3de3c76-67b7-4b05-a636-a7f541f5dc54-00-3ny3sf2me2oab.pike.replit.dev/api/download/batch7d-reference-package.zip",
      filename: "batch7d_reference_package.zip",
      mimeType: "application/zip",
    },
    {
      displayName: "Batch 7D — Kimi Context Document",
      documentType: "reference_file",
      description: "Concise design brief for Kimi: merged state, in-memory→DB gap table, key contracts, 7D scope boundaries, and open design questions.",
      fetchUrl: "https://a3de3c76-67b7-4b05-a636-a7f541f5dc54-00-3ny3sf2me2oab.pike.replit.dev/api/download/batch7d-kimi-context.md",
      filename: "BATCH_7D_KIMI_CONTEXT.md",
      mimeType: "text/markdown",
    },
  ];

  async function uploadOne(f) {
    console.log(`⬆ Fetching: ${f.filename} …`);
    const fileResp = await fetch(f.fetchUrl);
    if (!fileResp.ok) throw new Error(`Failed to fetch file: ${fileResp.status}`);
    const blob = await fileResp.blob();
    console.log(`  ✓ Fetched ${(blob.size / 1024).toFixed(1)} KB`);

    const form = new FormData();
    form.append("displayName", f.displayName);
    form.append("batchId",     String(BATCH_ID));
    form.append("documentType", f.documentType);
    form.append("description", f.description);
    form.append("file", new File([blob], f.filename, { type: f.mimeType }));

    console.log(`  → POSTing to /api/admin/documents …`);
    const resp = await fetch("/api/admin/documents", {
      method: "POST",
      body: form,
      // browser sends session cookie automatically — no auth header needed
    });

    const body = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      console.error(`  ✗ ${resp.status}: ${JSON.stringify(body)}`);
      return { ok: false, status: resp.status, body };
    }
    console.log(`  ✓ Created! id=${body.id ?? "?"} — "${f.displayName}"`);
    return { ok: true, body };
  }

  console.group("📦 Batch 7D Upload");
  const results = [];
  for (const f of FILES) {
    try {
      results.push(await uploadOne(f));
    } catch (err) {
      console.error(`  ✗ Exception: ${err.message}`);
      results.push({ ok: false, error: err.message });
    }
  }
  console.groupEnd();

  const ok = results.filter(r => r.ok).length;
  console.log(`\n✅ ${ok}/${FILES.length} documents uploaded.`);
  if (ok < FILES.length) {
    console.warn("Some uploads failed — check the errors above.");
    console.warn("If you see 401, make sure you are logged in as Admin first.");
    console.warn("If you see 500, the field names may differ — try the fallback below.");
  }
  return results;
})();
