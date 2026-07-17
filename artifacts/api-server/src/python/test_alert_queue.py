"""
Unit tests for alert_queue.py — Priority 4 (#41) durable email alert queue.

All tests use mocked email delivery (no real email, no network). The queue
table is the real dev alert_deliveries table; every test row uses the
AQTEST title prefix and is removed in setUp/tearDown.
"""

import unittest
from unittest import mock

import alert_queue
import email_alerts
import phase20_store

SETTINGS_ON = {"email_alerts_enabled": True,
               "email_alert_address": "trader@example.com"}
PREFIX = "AQTEST "


def _cleanup():
    if not alert_queue._db_available():
        return
    conn = alert_queue._connect()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM alert_deliveries WHERE title LIKE %s",
                        (PREFIX + "%",))
        conn.commit()
    finally:
        conn.close()


@unittest.skipUnless(alert_queue._db_available(), "requires dev database")
class TestAlertQueue(unittest.TestCase):
    def setUp(self):
        _cleanup()
        self.settings_patch = mock.patch.object(
            phase20_store, "get_settings", return_value=dict(SETTINGS_ON))
        self.settings_patch.start()

    def tearDown(self):
        self.settings_patch.stop()
        _cleanup()

    def _rows(self):
        conn = alert_queue._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT status, attempts, dead_letter, last_error,
                           destination, critical, max_attempts,
                           next_attempt_at, expires_at, delivered_at
                    FROM alert_deliveries WHERE title LIKE %s
                    ORDER BY id
                    """, (PREFIX + "%",))
                cols = [d[0] for d in cur.description]
                return [dict(zip(cols, r)) for r in cur.fetchall()]
        finally:
            conn.close()

    # ── Enqueue gating ───────────────────────────────────────────────────

    def test_non_email_kind_not_queued(self):
        r = alert_queue.enqueue_email_alert("SCAN_COMPLETE", PREFIX + "t")
        self.assertFalse(r["queued"])
        self.assertEqual(r["reason"], "KIND_NOT_EMAILED")

    def test_disabled_not_queued(self):
        with mock.patch.object(phase20_store, "get_settings",
                               return_value={"email_alerts_enabled": False,
                                             "email_alert_address": "a@b.co"}):
            r = alert_queue.enqueue_email_alert("PERFORMANCE_ALERT", PREFIX + "t")
        self.assertFalse(r["queued"])
        self.assertEqual(r["reason"], "DISABLED")

    def test_no_address_not_queued(self):
        with mock.patch.object(phase20_store, "get_settings",
                               return_value={"email_alerts_enabled": True,
                                             "email_alert_address": ""}):
            r = alert_queue.enqueue_email_alert("PERFORMANCE_ALERT", PREFIX + "t")
        self.assertFalse(r["queued"])
        self.assertEqual(r["reason"], "NO_ADDRESS")

    # ── Enqueue behaviour ────────────────────────────────────────────────

    def test_enqueue_masks_recipient_and_is_idempotent(self):
        r1 = alert_queue.enqueue_email_alert(
            "PERFORMANCE_ALERT", PREFIX + "losing streak", "3 losses", "WARN")
        self.assertTrue(r1["queued"])
        r2 = alert_queue.enqueue_email_alert(
            "PERFORMANCE_ALERT", PREFIX + "losing streak", "3 losses", "WARN")
        self.assertFalse(r2["queued"])
        self.assertEqual(r2["reason"], "DUPLICATE")
        rows = self._rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["destination"], "t***@example.com")
        self.assertNotIn("trader@example.com", str(rows[0]))
        self.assertFalse(rows[0]["critical"])
        self.assertIsNotNone(rows[0]["expires_at"])  # non-critical → TTL

    def test_critical_gets_more_attempts_and_no_expiry(self):
        alert_queue.enqueue_email_alert(
            "CIRCUIT_BREAKER_TRIPPED", PREFIX + "breaker", "tripped", "CRITICAL")
        row = self._rows()[0]
        self.assertTrue(row["critical"])
        self.assertEqual(row["max_attempts"], alert_queue.CRITICAL_MAX_ATTEMPTS)
        self.assertIsNone(row["expires_at"])

    # ── Processing ───────────────────────────────────────────────────────

    def test_success_marks_delivered(self):
        alert_queue.enqueue_email_alert(
            "PERFORMANCE_ALERT", PREFIX + "ok", "body", "WARN")
        with mock.patch.object(email_alerts, "_deliver",
                               return_value={"sent": True, "provider": "RESEND",
                                             "id": "msg-1"}) as d:
            counters = alert_queue.process_email_queue()
        self.assertEqual(counters["delivered"], 1)
        d.assert_called_once()
        row = self._rows()[0]
        self.assertEqual(row["status"], "DELIVERED")
        self.assertEqual(row["attempts"], 1)
        self.assertIsNotNone(row["delivered_at"])

    def test_transient_failure_schedules_retry_with_backoff(self):
        alert_queue.enqueue_email_alert(
            "PERFORMANCE_ALERT", PREFIX + "flaky", "body", "WARN")
        with mock.patch.object(email_alerts, "_deliver",
                               side_effect=ConnectionError("provider down")):
            counters = alert_queue.process_email_queue()
        self.assertEqual(counters["retried"], 1)
        row = self._rows()[0]
        self.assertEqual(row["status"], "RETRY_SCHEDULED")
        self.assertEqual(row["attempts"], 1)
        self.assertIn("provider down", row["last_error"])
        self.assertIsNotNone(row["next_attempt_at"])
        # Not due yet → a second pass must not re-attempt.
        with mock.patch.object(email_alerts, "_deliver") as d:
            alert_queue.process_email_queue()
        d.assert_not_called()

    def test_permanent_failure_fails_immediately(self):
        alert_queue.enqueue_email_alert(
            "PERFORMANCE_ALERT", PREFIX + "perm", "body", "WARN")
        with mock.patch.object(email_alerts, "_deliver",
                               return_value={"sent": False,
                                             "reason": "NOT_CONFIGURED"}):
            counters = alert_queue.process_email_queue()
        self.assertEqual(counters["failed"], 1)
        row = self._rows()[0]
        self.assertEqual(row["status"], "FAILED")
        self.assertFalse(row["dead_letter"])

    def test_exhausted_attempts_dead_letter(self):
        alert_queue.enqueue_email_alert(
            "PERFORMANCE_ALERT", PREFIX + "dead", "body", "WARN")
        conn = alert_queue._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE alert_deliveries
                    SET attempts = max_attempts - 1, next_attempt_at = now()
                    WHERE title LIKE %s
                    """, (PREFIX + "%",))
            conn.commit()
        finally:
            conn.close()
        with mock.patch.object(email_alerts, "_deliver",
                               side_effect=ConnectionError("still down")):
            counters = alert_queue.process_email_queue()
        self.assertEqual(counters["failed"], 1)
        row = self._rows()[0]
        self.assertEqual(row["status"], "FAILED")
        self.assertTrue(row["dead_letter"])

    def test_non_critical_expires(self):
        alert_queue.enqueue_email_alert(
            "PERFORMANCE_ALERT", PREFIX + "old", "body", "WARN")
        conn = alert_queue._connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE alert_deliveries
                    SET expires_at = now() - interval '1 hour'
                    WHERE title LIKE %s
                    """, (PREFIX + "%",))
            conn.commit()
        finally:
            conn.close()
        with mock.patch.object(email_alerts, "_deliver") as d:
            counters = alert_queue.process_email_queue()
        self.assertEqual(counters["expired"], 1)
        d.assert_not_called()
        self.assertEqual(self._rows()[0]["status"], "EXPIRED")

    def test_settings_changed_to_disabled_is_permanent(self):
        alert_queue.enqueue_email_alert(
            "PERFORMANCE_ALERT", PREFIX + "later off", "body", "WARN")
        with mock.patch.object(phase20_store, "get_settings",
                               return_value={"email_alerts_enabled": False}):
            with mock.patch.object(email_alerts, "_deliver") as d:
                counters = alert_queue.process_email_queue()
        d.assert_not_called()
        self.assertEqual(counters["failed"], 1)
        self.assertEqual(self._rows()[0]["status"], "FAILED")

    # ── Read-only views ──────────────────────────────────────────────────

    def test_list_and_stats(self):
        alert_queue.enqueue_email_alert(
            "PERFORMANCE_ALERT", PREFIX + "view", "body", "WARN")
        listed = alert_queue.list_deliveries(channel="email", status="QUEUED",
                                             limit=200)
        self.assertTrue(listed["available"])
        titles = [d["title"] for d in listed["deliveries"]]
        self.assertIn(PREFIX + "view", titles)
        stats = alert_queue.queue_stats()
        self.assertTrue(stats["available"])
        self.assertGreaterEqual(
            stats["counts"].get("email", {}).get("QUEUED", 0), 1)

    def test_backoff_schedule(self):
        self.assertEqual(alert_queue.backoff_seconds(1), 60)
        self.assertEqual(alert_queue.backoff_seconds(2), 300)
        self.assertEqual(alert_queue.backoff_seconds(6), 21600)
        self.assertEqual(alert_queue.backoff_seconds(99), 21600)

    def test_mask_email(self):
        self.assertEqual(alert_queue.mask_email("trader@example.com"),
                         "t***@example.com")
        self.assertEqual(alert_queue.mask_email("nope"), "***")

    def test_process_never_raises_on_bad_db(self):
        with mock.patch.object(alert_queue, "_connect",
                               side_effect=RuntimeError("db down")):
            out = alert_queue.process_email_queue()
        self.assertIn("skipped", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
