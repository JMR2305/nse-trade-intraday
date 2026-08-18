---
name: Publish image 8 GiB limit
description: Why publishes fail with oversized images or promote-step timeouts, and how the image is kept small.
---

# Publish image 8 GiB limit

**Rule:** the publish (Autoscale) image = workspace snapshot *after* the deploy build + nix layers. Non-app bloat ships by default: `.git`, `.cache/{uv,pip,pnpm}`, `.pythonlibs`, `.local/share/pnpm`, `.local/state`. Cleaning the dev workspace alone is NOT enough — the deploy build refills caches (`uv sync`, `pnpm install`) and adds `.venv`.

**Why:** two consecutive publishes failed with "image size is over the limit of 8 GiB" (Aug 2026). First fix cleaned the dev workspace (8.8→4.7 GiB) — the next publish still failed because the build re-added ~4 GiB.

**CRITICAL:** never delete `.cache/replit` from the image — it holds the module environment (`.cache/replit/env/latest` = PATH to node/pnpm/python). Wholesale `rm -rf .cache` made every publish fail at "Creating Autoscale service" with `exec: "node": executable file not found in $PATH` (5 consecutive failures Aug 9–10, 2026). Strip caches with `find .cache -mindepth 1 -maxdepth 1 ! -name replit -exec rm -rf {} +` in both deploy-build.sh Step 5 and `[deployment.postBuild]`.

## 2026-08-18 promote-step timeout (new failure mode)

**Root cause:** Even below 8 GiB, a large Repl layer causes the Cloud Run **promote step** to time out (300 s). The 08:23 UTC build failed because the Repl layer push took 7 m 40 s (workspace was ~3.2 G after cleanup), and the container was so slow to unpack+start that Cloud Run's startup probe hit the window limit before `/api/healthz` could return 200.

**What grew:** `exports/` — user-generated CSV/PDF/ZIP downloads that accumulate at the workspace root. It was ~1 GB at the time of the failure. Nothing in `deploy-build.sh` was stripping it, so every publish included it.

**Fix applied:** `deploy-build.sh` Step 5 now also strips:
- `exports/` (user-generated output, ~1 GB, grows unboundedly)
- `reports/` (generated markdown/PDF reports, ~2.5 MB)
- `verification/` (generated verification artefacts, ~1.1 MB)
- `screenshots/` (dev screenshots, ~0.75 MB)
- `**/.mypy_cache` (mypy type-check cache, ~30 MB)
- `**/__pycache__` outside `.venv` (Python bytecode, ~31 MB; regenerated on first use)

**Symptom signature of promote-step timeout:**
- Build log shows all artifacts compiled successfully
- Build log shows "Created Repl layer" after **>5 min** push time (normal is <2 min)
- Last build log line: "Creating Autoscale service"
- Build fails exactly 300 s later (Cloud Run startup probe window)
- Runtime logs (from current production) show: `waiting for runnable artifact ports`, `/api returned status 500` (because metasidecar hadn't forwarded to api-server yet)

**How to apply:**
- `scripts/deploy-build.sh` Step 5 strips `.git`, `.cache`, `.pythonlibs`, `.local/state`, `exports/`, `reports/`, `verification/`, `screenshots/`, `.mypy_cache`, `__pycache__`; `[deployment.postBuild]` in `.replit` prunes+removes the pnpm store and `.cache`. Keep those steps when editing either file.
- Production Python runs from `.venv` (built in deploy-build.sh); `.pythonlibs` is dev-only and rebuilt at runtime container start — never rely on it in prod.
- Dev-side guard: `scripts/check-workspace-size.sh` (registered as the `image-size` validation workflow) warns at 7 GiB and prints the safe cleanup recipe: clear `.cache/{uv,pip,pnpm}`, `pnpm store prune`, `git lfs prune`, `git gc --prune=now` — verified safe while workflows run (pnpm hardlinks survive store pruning).
- `cargo`/`rustc`/`postgresql` were removed from `[nix].packages` (Aug 2026) — leftover build-time deps (~1.5–2 GiB nix layer); all Python deps use prebuilt wheels (psycopg2-binary), and `postgresql` duplicated the postgresql-16 module. Do not re-add Rust unless something genuinely needs it.
- **`uninstallSystemDependencies` can report success yet leave `.replit` unchanged** — always re-read `[nix].packages` after calling it. The reliable path is `verifyAndReplaceDotReplit` (temp file MUST be inside the workspace root, not /tmp). This silent no-op is why the first cargo/rustc removal never took effect and two more publishes failed.
- A build that pushes an *uncached* nix layer can also die with a silent ~20-min push timeout (no size error in logs) — after a nix package change, a failed push with no error line may just need a retry.
- Next lever if the limit is hit again: drop unused artifacts (project-video, mockup-sandbox build outputs) from the image in deploy-build.sh Step 5.
