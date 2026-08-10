---
name: Publish image 8 GiB limit
description: Why publishes fail with "image size is over the limit of 8 GiB" and how the image is kept small.
---

# Publish image 8 GiB limit

**Rule:** the publish (Autoscale) image = workspace snapshot *after* the deploy build + nix layers. Non-app bloat ships by default: `.git`, `.cache/{uv,pip,pnpm}`, `.pythonlibs`, `.local/share/pnpm`, `.local/state`. Cleaning the dev workspace alone is NOT enough — the deploy build refills caches (`uv sync`, `pnpm install`) and adds `.venv`.

**Why:** two consecutive publishes failed with "image size is over the limit of 8 GiB" (Aug 2026). First fix cleaned the dev workspace (8.8→4.7 GiB) — the next publish still failed because the build re-added ~4 GiB.

**How to apply:**
- `scripts/deploy-build.sh` Step 5 strips `.git`, `.cache`, `.pythonlibs`, `.local/state` inside the image; `[deployment.postBuild]` in `.replit` prunes+removes the pnpm store and `.cache`. Keep those steps when editing either file.
- Production Python runs from `.venv` (built in deploy-build.sh); `.pythonlibs` is dev-only and rebuilt at runtime container start — never rely on it in prod.
- Dev-side guard: `scripts/check-workspace-size.sh` (registered as the `image-size` validation workflow) warns at 7 GiB and prints the safe cleanup recipe: clear `.cache/{uv,pip,pnpm}`, `pnpm store prune`, `git lfs prune`, `git gc --prune=now` — verified safe while workflows run (pnpm hardlinks survive store pruning).
- `cargo`/`rustc` were removed from `[nix].packages` (Aug 2026) — leftover build-time deps, ~1.5–2 GiB of nix layer; all Python deps use prebuilt wheels (psycopg2-binary, not source psycopg2). Do not re-add Rust unless something genuinely needs it.
- Next lever if the limit is hit again: audit remaining `[nix].packages` (e.g. `postgresql` duplicates the postgresql-16 module) or drop unused artifacts (project-video, mockup-sandbox build outputs) from the image in deploy-build.sh Step 5.
