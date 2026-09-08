# ApexQuant AI — Operator Checklist
## 2026-08-19 (Wednesday) — Pre-Market + Intraday + EOD
**Production URL:** https://nse-trade-intraday.replit.app  
**Mode:** PAPER ONLY — no live orders  

---

## BEFORE MARKET OPEN (by 09:10 IST)

- [ ] **1. Health check**  
  `curl https://nse-trade-intraday.replit.app/api/healthz`  
  ✅ Expected: `{"status":"ok"}`

- [ ] **2. Kite session live**  
  `GET /api/phase20/bootstrap-status` → `kite_session_verified: true`  
  ⚠️ If false: re-authenticate Kite, restart API server workflow

- [ ] **3. No overnight carry**  
  `GET /api/phase20/positions` → `[]`  
  ✅ Expected: empty array (DRREDDY was closed 2026-08-18 18:01 IST)

- [ ] **4. Circuit breaker clear**  
  `GET /api/phase20/circuit-breaker` → `tripped: false`

- [ ] **5. Bootstrap settings confirmed**  
  `GET /api/phase20/bootstrap-status`  
  ✅ `bootstrap_paper_enabled: true`  
  ✅ `bootstrap_max_order_value: 15000`  
  ✅ `auto_paper_entries: true`  
  ✅ `closed_bootstrap_trades: 1` (DRREDDY — today DRREDDY is eligible again)

- [ ] **6. EOD square-off is live**  
  `GET /api/phase20/eod-status` → `squareoff_time_ist: "15:20 IST"`

- [ ] **7. Live orders still disabled**  
  *(No action needed — `LIVE_EXECUTION_ENABLED=false` is hardcoded)*

---

## AFTER FIRST SCAN (~09:20–09:25 IST)

- [ ] **8. First scan completed**  
  `GET /api/live-data/scan/status` → new `scan_id`, `status: SUCCESS`  
  Expect: 50–51 symbols analysed (LTIM may still be missing — that is normal)

- [ ] **9. Mission Control shows activity**  
  Open `/mission-control` → scan count ≥ 1, no ERROR state

- [ ] **10. Watch for BOOTSTRAP_AUTO trade**  
  Open `/ai-paper-trader` → Auto Paper section  
  Top candidates to watch: **HDFCBANK** (conf ~78%), **HDFCLIFE** (conf ~73%), **DRREDDY** (conf ~65%)  
  A trade fires if any of these crosses the bootstrap confidence threshold with a WATCH/BUY signal

---

## DURING MARKET (09:25–15:15 IST)

- [ ] **11. Scans running every 5 minutes**  
  Mission Control → scan count increments steadily

- [ ] **12. LTIM warning visible but not blocking**  
  ⚠️ LTIM.NS will show as missing — pre-existing provider issue, expected

- [ ] **13. If BOOTSTRAP_AUTO trade fires:**  
  Check `/ai-paper-trader` for new row with `trigger_source: BOOTSTRAP_AUTO`  
  Verify: `fill_model: bootstrap_paper`, `qty ≥ 1`, `notional ≤ ₹15,000`  
  Verify: no Kite order placed (trade_id starts with `P20-`)

- [ ] **14. If circuit breaker trips:**  
  Stop and review losses in Operator Analytics  
  Use resume button with exact text:  
  *"I have manually reviewed the circuit breaker event and approve resuming automatic paper entries."*

---

## PRE-CLOSE (15:15–15:30 IST)

- [ ] **15. MARKET_CLOSE_EXIT fires at 15:20 IST**  
  Any OPEN positions should show `exit_rule: MARKET_CLOSE_EXIT` at/after 15:20  
  Visible in AI Paper Trader → open positions list

- [ ] **16. All positions closed by 15:30 IST**  
  `GET /api/phase20/positions` → `[]` before market close

---

## MARKET CLOSE & POST-CLOSE (15:30–16:00 IST)

- [ ] **17. POST_CLOSE_FORCE_EXIT safety net runs**  
  Wait 5–10 min after 15:30 IST, then:  
  `GET /api/phase20/eod-status` → `eod_ran_today: true`, `blocked_events: []`

- [ ] **18. Final position check**  
  `GET /api/phase20/positions` → `[]`

- [ ] **19. Realize P&L check**  
  Open `/ai-paper-trader` → review today's closed trades and realized P&L

- [ ] **20. No MARKET_CLOSE_EXIT_BLOCKED events**  
  `GET /api/phase20/eod-status` → `blocked_events: []`  
  ⚠️ If blocked events exist: use `POST /api/phase20/force-eod-close` to retry

---

## IF SOMETHING GOES WRONG

| Symptom | Fix |
|---------|-----|
| Health check fails | Restart API server workflow; check logs |
| Kite session expired | Re-authenticate; restart API server |
| Circuit breaker tripped | Review losses; use manual resume with confirmation text |
| Position not closed at 15:20 | Wait for POST_CLOSE_FORCE_EXIT at 15:30+; or use `POST /api/phase20/force-eod-close` |
| MARKET_CLOSE_EXIT_BLOCKED | Use bypass endpoint: `curl -X POST https://nse-trade-intraday.replit.app/api/phase20/force-eod-close` |
| No scans running | Check scan lock; restart API server workflow |
| Bootstrap not firing | Verify `bootstrap_paper_enabled=true`, `kite_session_verified=true`, CB clear |

---

## QUICK REFERENCE

| Endpoint | Purpose |
|----------|---------|
| `/api/healthz` | System health |
| `/api/phase20/positions` | Open positions (expect `[]` pre-market) |
| `/api/phase20/eod-status` | EOD square-off result |
| `/api/phase20/bootstrap-status` | Bootstrap readiness |
| `/api/phase20/circuit-breaker` | CB state |
| `/api/live-data/scan/status` | Latest scan |
| `POST /api/phase20/force-eod-close` | Emergency position close bypass |

---

## CURRENT STATE GOING INTO TOMORROW

| Item | Status |
|------|--------|
| Open positions | ✅ **NONE** |
| DRREDDY P20-3468fb2a24 | ✅ CLOSED (POST_CLOSE_FORCE_EXIT, ₹0 P&L) |
| Bootstrap trades closed | 1 / 20 |
| Circuit breaker | ✅ Clear |
| EOD ran today | ✅ `eod_ran_today: true` |
| Cash | ≈ ₹49,999.98 |
| Kite verified | ✅ |
| Production health | ✅ 200 OK |

**VERDICT: ✅ READY WITH WARNINGS — No blockers for 2026-08-19**  
*(Warnings: LTIM missing — pre-existing provider issue, non-blocking)*

---

*Generated: 2026-08-18 20:45 IST | PAPER TRADING ONLY*
