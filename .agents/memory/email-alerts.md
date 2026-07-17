---
name: Email alert delivery
description: Opt-in email delivery of critical trading notifications (losing streak, circuit breaker)
---

Critical notification kinds (PERFORMANCE_ALERT, CIRCUIT_BREAKER_TRIPPED) are emailed best-effort from the central `add_notification` hook, not from each alert producer.

**Why:** hooking the single storage chokepoint guarantees every producer (perf alerts, circuit breaker, future rules) gets email for free, and the never-raises wrapper keeps a broken provider from breaking the scheduler tick or notification storage.

**How to apply:**
- Transport resolves at send time from env: RESEND_API_KEY (Resend HTTP API) preferred, else SMTP_* secrets, else logged NOT_CONFIGURED. No provider key is stored in settings.
- Opt-in lives in Phase 20 settings (`email_alerts_enabled` + `email_alert_address`); both are excluded from the reproducibility config hash (meta, not behaviour).
- New outbound channels (e.g. Telegram) should mirror this pattern: settings toggle, kind filter constant, never-raises send, hook after `_with_db` in add_notification.
- No Replit-managed email connection exists in this account; user skipped providing RESEND_API_KEY (July 2026), so delivery stays gracefully unconfigured until a secret is added.
