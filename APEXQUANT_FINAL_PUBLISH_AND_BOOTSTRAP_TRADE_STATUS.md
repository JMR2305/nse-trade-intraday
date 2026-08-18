# ApexQuant AI — Daily Trade Summary
**Date:** Tuesday, 2026-08-18 (NSE session)
**Generated:** 2026-08-18 ~15:45 IST (post-close)

---

## 1. Publish Status

| Item | Status |
|---|---|
| `_build_row` NameError fix | ✅ In workspace (50/50 tests pass) |
| `create_paper_entry` try-except fallback | ✅ In workspace |
| `deploy-build.sh` image-size cleanup | ✅ In workspace |
| Previous deploy (04:23 UTC old build) | ⚠️ Still serving production |
| New deploy triggered today | ❌ Not clicked before market close |

**Root cause of missed deploy:** The 08:23 UTC deploy attempt failed because `exports/` bloated the container image to 3.2 GB. The deploy-build.sh fix was applied in the workspace during today's session. All workflows are healthy and the workspace is ready to publish. Market closed at 15:30 IST before Publish was clicked.

**Next action:** Click Publish at market open tomorrow (2026-08-19, 09:15 IST) before the first scan.

---

## 2. Build Image Size

| Metric | Before fix | After fix (workspace) |
|---|---|---|
| Estimated image size | ~3.2 GB | ~2.1 GB |
| Layer push time | ~7 min 40 s | ~2 min (est.) |
| Cloud Run startup budget | 300 s | 300 s |
| Deploy outcome | ❌ Promote timeout | ✅ Expected to pass |

Directories now stripped in `scripts/deploy-build.sh` Step 5:
`exports/`, `reports/`, `verification/`, `screenshots/`, `**/.mypy_cache`, `**/__pycache__`

---

## 3. Health Check (Dev Server)

| Service | Status |
|---|---|
| API server (port 8080) | ✅ Running |
| Trading dashboard | ✅ Running |
| Document hub | ✅ Running |
| Project video | ✅ Running |
| Expo mobile | ✅ Running |

All workflows restarted and confirmed clean after port-conflict crash at ~09:45 IST.

---

## 4. Today's Scan Coverage

| Metric | Value |
|---|---|
| Total scans completed | 77 |
| Scans skipped (busy / lock held) | 3 |
| First scan | 09:16 IST |
| Last scan | 15:27 IST |
| Universe size | 51 symbols (50 data, 1 unavailable: LTIM) |
| Symbols evaluated per scan | ~49–50 |

---

## 5. Signal Distribution (All 77 Scans Combined)

| Decision | Count | % of all decisions |
|---|---|---|
| IGNORE | 2,292 | 60.3% |
| WATCH | 1,508 | 39.7% |
| BUY / STRONG BUY | **0** | **0.0%** |

**Max confidence seen today:** 78.3% (HDFCBANK — WATCH all session)
**Bootstrap-eligible symbols across all scans:** 0

---

## 6. Bootstrap Loop Result

| Check | Result |
|---|---|
| KV claims fired | Yes (atomic, deduplicated per scan) |
| `BOOTSTRAP_SCAN_CLAIMED` events | Fired every scan |
| Bootstrap-eligible candidates found | **0** |
| `BOOTSTRAP_PAPER_TRADE_APPROVED` events | **0** |
| `ORDER_EXECUTED` events | **0** |
| NameError from `_build_row` | Not triggered (no eligible candidates reached executor) |

**Why no bootstrap trade fired today:**
The scanner issued 0 BUY signals across 77 scans. Bootstrap eligibility requires a BUY or STRONG_BUY decision. The top candidates (HDFCBANK 78.3%, DRREDDY 64.7%) remained in WATCH state all session — the AI decision engine evaluated the current regime (Ranging/sideways) and momentum conditions as insufficient to issue a BUY.

The `_build_row` fix is confirmed in the workspace. It was not the blocker today — no candidates reached the executor.

---

## 7. First BOOTSTRAP_AUTO Trade

**Status: Not created today.**
**Next attempt: Wednesday 2026-08-19, after Publish + first scheduled scan (~09:20 IST).**

---

## 8. Open Positions (End of Day)

All 4 positions remain in `EXIT_PENDING / STALE_DATA_SAFETY`. Task #807 (force-close fix) was **merged** today but is not yet deployed to production.

| trade_id | Symbol | Fill Price | Qty | Stop | Target | Age | Updated |
|---|---|---|---|---|---|---|---|
| P20-acad172b74 | TRENT | ₹3,082.42 | 3 | ₹2,931.53 | ₹3,370.34 | 337 h | 2026-08-14 |
| P20-a205b1ef09 | DIVISLAB | ₹8,370.04 | 1 | ₹7,982.41 | ₹9,482.77 | 337 h | 2026-08-14 |
| P20-83aa1be8f9 | GRASIM | ₹3,223.63 | 3 | ₹3,085.54 | ₹3,618.58 | 316 h | 2026-08-14 |
| P20-4a5f909738 | BAJFINANCE | ₹1,100.05 | 8 | ₹1,037.67 | ₹1,280.59 | 270 h | 2026-08-14 |

**exit_price:** NULL for all 4 (exit not stamped)
**realized_pnl:** NULL for all 4

After tomorrow's Publish, the force-close exit engine (Task #807) will stamp exit_price at the last-known live price and close these positions.

---

## 9. Portfolio State (End of Day)

| Metric | Value |
|---|---|
| Cash balance | ₹50,000.00 |
| Open positions value | ₹0 (4 positions stuck in EXIT_PENDING, not yet reconciled) |
| Total realized P&L today | ₹0 |
| Total unrealized P&L today | ₹0 |
| pnl_history entries | 1 (reset at 03:30 IST on server start) |

---

## 10. Trades Opened Today

**None.** No new paper trades were created today.

---

## 11. Trades Closed Today

**None.** No exits were completed today. The Task #807 force-close fix is merged but awaits production deploy.

---

## 12. Live Broker Confirmation

Live execution remains disabled. `LIVE_EXECUTION_ENABLED` defaults `false`.
No Kite API order calls were made. All logic is paper-only.

---

## 13. Tasks Merged Today

| Task | Description | Status |
|---|---|---|
| #807 | Force-close stale EXIT_PENDING positions | ✅ Merged |
| #808 | Stop `exports/` from bloating deploys | ✅ Merged |
| #809 | Bootstrap eligibility change banner on Mission Control | ✅ Merged |

---

## 14. Next Steps for 2026-08-19

**Before market open (by 09:15 IST):**
1. **Click Publish** — deploys `_build_row` fix + fallback loop + image-size cleanup + Task #807 force-close + Task #808 exports cleanup
2. Verify `/api/healthz` returns 200 on production URL
3. Confirm production build timestamp is post-Publish

**After first scan (~09:20–09:25 IST):**
4. Check `phase20_paper_trades` — the 4 EXIT_PENDING positions should be force-closed with `exit_price` stamped
5. Check `pipeline_events` for `PAPER_TRADE_FORCE_CLOSED` events (one per position)
6. Portfolio cash should reflect the 4 closed trades' realized P&L
7. Bootstrap loop: if any symbol issues BUY/STRONG_BUY → `BOOTSTRAP_PAPER_TRADE_APPROVED` + `ORDER_EXECUTED` events fire → first BOOTSTRAP_AUTO trade created

**Monitoring:**
- Watch Mission Control → Auto Paper panel for bootstrap eligibility banner
- Any `bootstrap_eligible=true` symbol in the next scan → executor will attempt entry
- Confirm `trigger_source=BOOTSTRAP_AUTO` and `fill_model=bootstrap_paper` on the new row

---

*Report generated from live DB queries against the development database (reflecting production pipeline state).*
*Production URL: https://nse-trade-intraday.replit.app*
