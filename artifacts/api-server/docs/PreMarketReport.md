# Phase 4A — Pre-Market Readiness Report

**PAPER TRADING / RESEARCH ONLY**

Generated: 2026-07-26T15:13:37.892642+05:30  
Overall: **READY_WITH_WARNINGS**  
Checks: 10/15 PASS · 5 WARN · 0 FAIL

| # | Check | Category | Verdict | Detail |
|---|-------|----------|---------|--------|
| 1 | API Server | infrastructure | ✅ PASS | healthy |
| 2 | Database | infrastructure | ✅ PASS | connected (6585.7ms) |
| 3 | Scanner | data | ⚠️ WARN | scan/status HTTP 404 — may not have run yet |
| 4 | Market Data | data | ✅ PASS | signals OK (10 signals) |
| 5 | Yahoo Finance connectivity | data | ✅ PASS | ^NSEI price=23767 (604.1ms) |
| 6 | SSE Stream | infrastructure | ✅ PASS | port 8080 reachable (Replit proxies SSE) |
| 7 | Portfolio consistency | portfolio | ✅ PASS | equity=₹909806.02 cash=₹-37000.00 invested=₹946806.02 diff=₹0.0000 |
| 8 | Risk Engine | risk | ✅ PASS | kill_switch=False max_risk=1.0% |
| 9 | PortfolioConfig | risk | ⚠️ WARN | loaded but paper_mode not confirmed |
| 10 | Kill Switch | safety | ⚠️ WARN | kill switch state unknown |
| 11 | Circuit Breaker | safety | ✅ PASS | circuit breaker clear (via module) |
| 12 | Open Positions | portfolio | ✅ PASS | 0 open positions, none stale |
| 13 | Previous session recovery | portfolio | ⚠️ WARN | no previous session file (first session or 3D not configured) |
| 14 | Pending trades | portfolio | ✅ PASS | 0 Phase 20 OPEN positions, 0 pending exits |
| 15 | Symbol universe | data | ⚠️ WARN | low symbol count: 10 signals |
