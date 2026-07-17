---
name: Push notification alerts
description: Design of the high-confidence signal push alert pipeline (Expo push + push_subscriptions table)
---

- Advisory only: push dispatch is fire-and-forget after scans (scheduler tick + manual /live-data/scan/run) and must never block or influence the trading pipeline.
- Dedupe: per-token `last_notified_key` stores the signals_cache (key='signals') `updated_at` ISO string; each snapshot is evaluated once per token, even if no signals matched.
- Token hygiene: Expo tickets with `DeviceNotRegistered` delete the row; token format validated with `/^Expo(nent)?PushToken\[[A-Za-z0-9_-]+\]$/`.
- Cold start: `ensurePushSubscriptionsTable()` runs CREATE TABLE IF NOT EXISTS lazily (drizzle-kit push needs a TTY, so fresh prod DBs rely on this bootstrap).
- Mobile: registration is always user-initiated from Alerts screen (toggle starts OFF); launch only silently re-registers when previously enabled and permission still granted. Android Expo Go SDK53+ can't get remote push tokens — failures surface as an alert, never crash.

**Why:** research-only system; notifications are informational and safety rules forbid any automatic trading coupling.
**How to apply:** any new notification trigger should call `dispatchSignalPushNotifications()` (or a sibling) fire-and-forget with errors swallowed, and reuse the same dedupe key discipline.
