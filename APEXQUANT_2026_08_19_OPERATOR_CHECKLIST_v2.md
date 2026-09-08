# ApexQuant AI — Operator Checklist v2
## 2026-08-19 (Wednesday) — Pre-Market + Intraday + EOD
**Production URL:** https://nse-trade-intraday.replit.app  
**Mode:** PAPER ONLY — no live orders  

> ⚠️ **READY WITH WARNINGS is only confirmed after the 09:00–09:10 IST checks below all pass.**  
> Do not assume the overnight state carries over. Kite sessions expire and must be re-verified fresh every morning before the first scan fires.

---

## BEFORE MARKET OPEN — 09:00–09:10 IST (MANDATORY)

All 6 checks must pass before the first scan at ~09:15 IST.

- [ ] **1. Health check**  
  `GET https://nse-trade-intraday.replit.app/api/healthz`  
  ✅ Expected: `{"status":"ok"}`  
  ❌ If fails: restart API server workflow; check logs

- [ ] **2. Kite session — RE-VERIFY EVERY MORNING**  
  `GET /api/phase20/bootstrap-status` → `kite_session_verified: true`  
  ✅ Expected: `true`  
  ❌ If `false`: **re-authenticate Kite immediately** before the first scan — without a live Kite session the LTP overlay is off and all bootstrap entries are blocked  
  > ⚠️ The `kite_session_verified: true` reading from the prior evening (20:45 IST) does **not** carry over. Zerodha sessions expire daily. Always re-check at 09:00–09:10 IST.

- [ ] **3. No overnight carry**  
  `GET /api/phase20/positions` → `[]`  
  ✅ Expected: empty array (DRREDDY was closed 2026-08-18 18:01 IST — no carry)  
  ❌ If unexpected position found: investigate before first scan; do not let it carry silently

- [ ] **4. Circuit breaker clear**  
  `GET /api/phase20/circuit-breaker` → `tripped: false`  
  ❌ If tripped: review losses in AI Paper Trader before resuming

- [ ] **5. Bootstrap cap confirmed**  
  `GET /api/phase20/bootstrap-status` → `bootstrap_max_order_value: 15000`  
  ✅ Expected: `15000` (₹15,000 cap, confirmed in production build)  
  ❌ If wrong value: code issue — do not trade, escalate

- [ ] **6. EOD square-off is live**  
  `GET /api/phase20/eod-status` → `squareoff_time_ist: "15:20 IST"`  
  ✅ Expected: `"15:20 IST"` (unconditional square-off confirmed working)  
  ❌ If missing or wrong: EOD fix not live — republish before trading

- [ ] **7. Live orders disabled** *(no action — hardcoded constant)*  
  `LIVE_EXECUTION_ENABLED = false` is in code, not a setting. No check needed.

---

### Pre-Market Verdict Gate

```
All 6 checks pass → ✅ READY WITH WARNINGS — proceed to market open
Any check fails   → ⛔ BLOCKED — fix the failed check before first scan
```

---

## AFTER FIRST SCAN (~09:15–09:25 IST)

- [ ] **8. First scan completed**  
  `GET /api/live-data/scan/status` → new `scan_id` different from yesterday's, `status: SUCCESS`  
  Expect: **50 symbols analysed** (LTIM still missing — normal, pre-existing provider issue)  
  Expect: scan count begins at 1 and increments every 5 minutes toward ~75 by end of session

- [ ] **9. Mission Control active**  
  Open `/mission-control` → scan counter incrementing, no ERROR state

- [ ] **10. Watch for BOOTSTRAP_AUTO trade**  
  Open `/ai-paper-trader` → Auto Paper section  
  Top candidates: **HDFCBANK** (conf ~78%), **HDFCLIFE** (conf ~73%), **DRREDDY** (conf ~65%, now re-eligible)  
  A trade fires when any candidate receives a WATCH/BUY signal at or above the bootstrap confidence threshold

---

## DURING MARKET (09:25–15:15 IST)

- [ ] **11. Scans running every 5 minutes**  
  By end of session (~15:30 IST) expect ~75 total scans  
  Mission Control scan count should be incrementing steadily throughout the day

- [ ] **12. LTIM warning — expected, not blocking**  
  ⚠️ LTIM.NS will show as missing. Pre-existing provider issue. 50/51 symbols still evaluated normally.

- [ ] **13. If BOOTSTRAP_AUTO trade fires:**  
  Check `/ai-paper-trader` for new row with `trigger_source: BOOTSTRAP_AUTO`  
  Verify: `fill_model: bootstrap_paper`, `qty ≥ 1`, `notional ≤ ₹15,000`  
  Verify: trade_id starts with `P20-` (no live broker order)

- [ ] **14. If circuit breaker trips:**  
  Stop. Review losses in Operator Analytics.  
  Use resume button with exact confirmation text:  
  *"I have manually reviewed the circuit breaker event and approve resuming automatic paper entries."*

---

## PRE-CLOSE (15:15–15:30 IST)

- [ ] **15. MARKET_CLOSE_EXIT fires at 15:20 IST**  
  Any OPEN positions should show `exit_rule: MARKET_CLOSE_EXIT` at/after 15:20 IST  
  Visible in AI Paper Trader → open positions list  
  This is unconditional — does not require `square_off_before_close=true`

- [ ] **16. All positions closed by 15:30 IST**  
  `GET /api/phase20/positions` → `[]` before market close

---

## MARKET CLOSE & POST-CLOSE (15:30–16:00 IST)

- [ ] **17. POST_CLOSE_FORCE_EXIT safety net runs**  
  Wait 5–10 min after 15:30 IST:  
  `GET /api/phase20/eod-status` → `eod_ran_today: true`, `blocked_events: []`

- [ ] **18. Final position check**  
  `GET /api/phase20/positions` → `[]`

- [ ] **19. Realized P&L check**  
  Open `/ai-paper-trader` → review today's closed trades and P&L

- [ ] **20. No blocked exit events**  
  `GET /api/phase20/eod-status` → `blocked_events: []`  
  ⚠️ If blocked events exist: use bypass endpoint → `POST /api/phase20/force-eod-close`

---

## IF SOMETHING GOES WRONG

| Symptom | Fix |
|---------|-----|
| Health check fails | Restart API server workflow; check logs |
| `kite_session_verified: false` | Re-authenticate Kite; restart API server workflow |
| Circuit breaker tripped | Review losses; use manual resume with confirmation text |
| Position not closed at 15:20 | Wait for POST_CLOSE_FORCE_EXIT; or use `POST /api/phase20/force-eod-close` |
| `MARKET_CLOSE_EXIT_BLOCKED` event | `curl -X POST https://nse-trade-intraday.replit.app/api/phase20/force-eod-close` |
| No scans running | Check scan lock; restart API server workflow |
| Bootstrap not firing | Confirm Kite verified, `bootstrap_paper_enabled=true`, CB clear |
| `bootstrap_max_order_value` ≠ 15000 | Code/build issue — do not trade, republish |

---

## QUICK REFERENCE

| Endpoint | Purpose |
|----------|---------|
| `GET /api/healthz` | System health |
| `GET /api/phase20/bootstrap-status` | Kite session, bootstrap cap, eligibility |
| `GET /api/phase20/positions` | Open positions (expect `[]` pre-market) |
| `GET /api/phase20/circuit-breaker` | CB state |
| `GET /api/phase20/eod-status` | EOD square-off result |
| `GET /api/live-data/scan/status` | Latest scan (expect ~75 scans by session end) |
| `POST /api/phase20/force-eod-close` | Emergency position close bypass |

---

## SESSION STARTING STATE (2026-08-19 pre-market)

| Item | Status going in |
|------|----------------|
| Open positions | ✅ NONE (`[]` confirmed 20:45 IST 2026-08-18) |
| DRREDDY P20-3468fb2a24 | ✅ CLOSED (POST_CLOSE_FORCE_EXIT, ₹0 P&L) |
| Bootstrap trades closed | 1 / 20 (DRREDDY now re-eligible) |
| Circuit breaker | ✅ Clear |
| EOD ran yesterday | ✅ `eod_ran_today: true`, `blocked_events: []` |
| Cash | ≈ ₹49,999.98 |
| Kite (evening) | ✅ Verified at 20:45 IST — **re-verify at 09:00 IST** |
| Bootstrap cap | ✅ ₹15,000 confirmed in production |
| Production build | ✅ Second publish live and working |

---

**Expected scans for 2026-08-19:** ~75 (5-min cadence, 09:15–15:30 IST = 375 min)  
**Previous session (2026-08-18):** 77 scans — normal and near-expected

---

*Generated: 2026-08-18 20:45 IST | PAPER TRADING ONLY | v2 — scan count corrected to ~75/session; Kite re-verification made mandatory*
