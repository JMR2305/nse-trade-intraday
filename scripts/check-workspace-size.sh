#!/usr/bin/env bash
# Guard: keep the publish image under the 8 GiB deployment limit.
#
# The 2026-08-09 publish failed with "image size is over the limit of 8 GiB".
# Most of the bloat was NOT app code — package caches, the pnpm store, and
# git objects/LFS all get baked into the publish image. This check fails
# when the workspace approaches the limit so the problem surfaces before a
# publish attempt, not during one.
#
# Safe cleanup recipe (verified 2026-08-10 — dashboard + api-server kept
# responding afterwards):
#   rm -rf .cache/uv .cache/pip .cache/pnpm
#   pnpm store prune
#   git lfs prune
#   git gc --prune=now
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
WARN_GIB=7   # flag when workspace approaches the 8 GiB image limit

used_kib=$(du -sk "$ROOT" 2>/dev/null | cut -f1)
used_gib=$(awk "BEGIN {printf \"%.1f\", $used_kib / 1048576}")

echo "Workspace size: ${used_gib} GiB (publish image limit: 8 GiB, warn at ${WARN_GIB} GiB)"

# Show the usual bloat suspects so the report is actionable.
echo "Largest non-app contributors:"
du -sh "$ROOT/.git" "$ROOT/.cache" "$ROOT/.local/share/pnpm" 2>/dev/null | sort -rh || true

if awk "BEGIN {exit !($used_kib >= $WARN_GIB * 1048576)}"; then
  cat >&2 <<'EOF'

WARNING: workspace is approaching the 8 GiB publish image limit.
Run the safe cleanup recipe before publishing:

  rm -rf .cache/uv .cache/pip .cache/pnpm
  pnpm store prune
  git lfs prune
  git gc --prune=now

Then re-run this check and verify workflows still respond
(trading-dashboard page + /api/operational-intelligence/report).
EOF
  exit 1
fi

echo "OK: comfortably under the limit."
