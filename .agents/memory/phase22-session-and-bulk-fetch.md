---
name: Phase 22 session expiry & bulk fetch
description: Zerodha token daily-expiry semantics and the bulk yfinance download fix for 900s scans
---

- Kite tokens expire at the next 06:00 IST after creation. All expiry checks are fail-safe: missing/unparseable `created_at` or a present-but-malformed `ZERODHA_TOKEN_TIMESTAMP` counts as EXPIRED (never trusted). `kite_token_store.load()` filters expired tokens by default.
- **Why:** a stale trusted token silently degrades the provider to Yahoo fallback while the UI claims connectivity; fail-open expiry parsing was flagged as a blocker in review.
- Dev and prod Postgres are separate — the durable token store means the user must log in via the *published* app once daily for prod sessions; a dev login never carries over.
- Long-scan root cause was 50 serial yfinance calls (0.25s throttle + 2s/4s retry backoff) → 770–990s. Fix: one multi-ticker `yf.download(group_by="ticker", threads=True)` with per-symbol retry fallback only for stragglers (~28–35s for 50 symbols). Fallback provenance is an explicit `via_fallback` flag on the fetch result — never infer it from retry counts.
- **Test isolation:** the token store is DB-durable; any test touching it must stub `_db_load`/`_db_save` (file-path patching alone leaks stub tokens into the real dev DB and pollutes other suites). Gate tests must also patch `scan_state_store.load_latest_snapshot`, or they read the real dev snapshot and fail environmentally.
