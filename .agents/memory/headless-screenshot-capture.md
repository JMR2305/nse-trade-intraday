---
name: Headless screenshot capture of dashboard pages
description: How to reliably capture the trading-dashboard pages with puppeteer-core + nix chromium
---

- Dashboard pages poll APIs continuously, so puppeteer `waitUntil: "networkidle2"` never settles and each page burns its full timeout. Use `waitUntil: "domcontentloaded"` + a fixed ~3s render delay instead.
- **Why:** live-data pages keep the network busy forever; a 20-page capture went from >8 min of timeouts to ~2 min.
- **How to apply:** any headless capture of this app (review packages, reports). Chromium comes from nix (`which chromium`) + puppeteer-core with `--no-sandbox`; target `http://localhost:80/trading-dashboard<route>`.
- Full review-package generation takes ~4-5 min for 32 pages; agent shell commands cap at 2 min, so run curl in background and poll files — note background subshells may be reaped between shell sessions, losing the curl response (server-side work still completes).
