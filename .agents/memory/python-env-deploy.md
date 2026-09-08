---
name: Python env & publish builds
description: Why uv installs can hit read-only /nix/store and how publish builds treat pyproject deps
---

# Python environment quirks (uv + .pythonlibs)

- `.pythonlibs` must be a valid venv: it needs `.pythonlibs/pyvenv.cfg` (home = nix python bin dir). If that file is missing, `sys.prefix` resolves to the read-only nix store and every `uv add`/`uv sync` fails with "Permission denied (os error 13)" — in dev AND in publish builds.
- **Why:** July 2026 publish build failed exactly this way; recreating `pyvenv.cfg` plus `uv cache clean` (uv caches interpreter probes, so stale cache keeps the wrong prefix) fixed it.
- **How to apply:** If uv tries to write into `/nix/store/...`, check for `pyvenv.cfg` first, then clear the uv cache, then retry.
- Publish builds run `uv lock` + `uv sync`, which **prunes** any installed package not listed in root `pyproject.toml`. All runtime Python deps (kiteconnect, yfinance, pandas, numpy, openpyxl, reportlab) must be declared there or prod loses them.
- Artifact production builds run after the root pre-build hook, but the root cleanup removes `.git` to fit the publish-image limit. Preserve the verified commit in `.apexquant-source-commit` before cleanup; identity resolution must use env → Git → this handoff and still reject unknown or generic identities.
- **Why:** Otherwise the root build can succeed and the later API artifact build fails once it cannot resolve the exact source commit.
- **How to apply:** Keep the handoff file non-secret and generated only during publish; do not bypass the identity check with a generic build ID.
