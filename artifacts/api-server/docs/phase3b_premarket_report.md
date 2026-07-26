# Pre-Market Readiness Report

**PAPER TRADING / RESEARCH ONLY**

Generated: 2026-07-26T14:34:32.253875+05:30  
Overall: **READY_WITH_WARNINGS**  
Checks: 8/12 PASS · 4 WARN · 0 FAIL

| # | Check | Category | Verdict | Detail |
|---|-------|----------|---------|--------|
| 1 | API health | infrastructure | ✅ PASS | status=200 healthy |
| 2 | database readiness | infrastructure | ✅ PASS | database reachable, 670.1ms |
| 3 | scanner readiness | data | ⚠️ WARN | scan/status HTTP 404 — scanner may not have run yet |
| 4 | data provider readiness | data | ✅ PASS | signals endpoint OK; 10 signals |
| 5 | symbol universe | data | ⚠️ WARN | low symbol count: 10 signals returned |
| 6 | paper portfolio state | safety | ✅ PASS | paper_mode=True cash=₹-7000 |
| 7 | kill switch state | safety | ⚠️ WARN | kill switch state unknown |
| 8 | circuit breaker state | safety | ⚠️ WARN | circuit breaker endpoint unavailable; health/ready OK |
| 9 | RC-8 risk configuration | risk | ✅ PASS | PortfolioConfig loaded via pydantic |
| 10 | SSE connectivity | infrastructure | ✅ PASS | SSE port reachable (TCP); /stream-health not exposed |
| 11 | no stale previous-session orders | portfolio | ✅ PASS | 0 open positions, none stale |
| 12 | no duplicate scanner lock | infrastructure | ✅ PASS | scan/status HTTP 404 — lock status unknown (non-blocking) |
