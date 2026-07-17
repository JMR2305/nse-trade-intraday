"""
Unit tests for email_alerts.py — opt-in email delivery of critical alerts.

All tests are unit-level with mocked transports; no real email is ever sent
and no network calls are made.
"""

import os
import unittest
from unittest import mock

import email_alerts


SETTINGS_ON = {"email_alerts_enabled": True,
               "email_alert_address": "trader@example.com"}


class TestValidation(unittest.TestCase):
    def test_valid_addresses(self):
        self.assertTrue(email_alerts.valid_address("a@b.co"))
        self.assertTrue(email_alerts.valid_address("x.y+z@sub.domain.io"))

    def test_invalid_addresses(self):
        for bad in ("", "nope", "a@b", "a @b.co", None, 42):
            self.assertFalse(email_alerts.valid_address(bad), bad)


class TestMaybeSend(unittest.TestCase):
    def test_non_email_kind_skipped(self):
        r = email_alerts.maybe_send_alert_email(
            "SCAN_COMPLETE", "t", "b", settings=SETTINGS_ON)
        self.assertEqual(r["reason"], "KIND_NOT_EMAILED")

    def test_disabled_skipped(self):
        r = email_alerts.maybe_send_alert_email(
            "PERFORMANCE_ALERT", "t", "b",
            settings={"email_alerts_enabled": False,
                      "email_alert_address": "trader@example.com"})
        self.assertEqual(r["reason"], "DISABLED")

    def test_no_address_skipped(self):
        r = email_alerts.maybe_send_alert_email(
            "PERFORMANCE_ALERT", "t", "b",
            settings={"email_alerts_enabled": True, "email_alert_address": ""})
        self.assertEqual(r["reason"], "NO_ADDRESS")

    def test_sends_for_performance_alert(self):
        with mock.patch.object(email_alerts, "_deliver",
                               return_value={"sent": True, "provider": "RESEND"}) as d:
            r = email_alerts.maybe_send_alert_email(
                "PERFORMANCE_ALERT", "Losing streak", "3 losses",
                severity="WARN", settings=SETTINGS_ON)
        self.assertTrue(r["sent"])
        to, subject, text = d.call_args[0]
        self.assertEqual(to, "trader@example.com")
        self.assertIn("WARN", subject)
        self.assertIn("Losing streak", subject)
        self.assertIn("3 losses", text)

    def test_sends_for_circuit_breaker(self):
        with mock.patch.object(email_alerts, "_deliver",
                               return_value={"sent": True, "provider": "SMTP"}):
            r = email_alerts.maybe_send_alert_email(
                "CIRCUIT_BREAKER_TRIPPED", "Tripped", "b", settings=SETTINGS_ON)
        self.assertTrue(r["sent"])

    def test_delivery_failure_never_raises(self):
        with mock.patch.object(email_alerts, "_deliver",
                               side_effect=RuntimeError("provider down")):
            r = email_alerts.maybe_send_alert_email(
                "PERFORMANCE_ALERT", "t", "b", settings=SETTINGS_ON)
        self.assertFalse(r["sent"])
        self.assertEqual(r["reason"], "ERROR")
        self.assertIn("provider down", r["error"])


class TestTransportSelection(unittest.TestCase):
    def test_not_configured(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            status = email_alerts.provider_status()
            self.assertFalse(status["configured"])
            r = email_alerts._deliver("a@b.co", "s", "t")
            self.assertFalse(r["sent"])
            self.assertEqual(r["reason"], "NOT_CONFIGURED")

    def test_resend_preferred(self):
        with mock.patch.dict(os.environ, {"RESEND_API_KEY": "x",
                                          "SMTP_HOST": "h"}, clear=True):
            self.assertEqual(email_alerts.provider_status()["provider"], "RESEND")
            with mock.patch.object(email_alerts, "_send_via_resend",
                                   return_value={"sent": True, "provider": "RESEND"}) as m:
                r = email_alerts._deliver("a@b.co", "s", "t")
            self.assertTrue(m.called)
            self.assertEqual(r["provider"], "RESEND")

    def test_smtp_fallback(self):
        with mock.patch.dict(os.environ, {"SMTP_HOST": "h"}, clear=True):
            self.assertEqual(email_alerts.provider_status()["provider"], "SMTP")
            with mock.patch.object(email_alerts, "_send_via_smtp",
                                   return_value={"sent": True, "provider": "SMTP"}) as m:
                r = email_alerts._deliver("a@b.co", "s", "t")
            self.assertTrue(m.called)
            self.assertEqual(r["provider"], "SMTP")


class TestStoreIntegration(unittest.TestCase):
    """add_notification triggers email for critical kinds only, best-effort."""

    def test_add_notification_emails_critical_kind(self):
        import phase20_store as store
        with mock.patch.object(email_alerts, "maybe_send_alert_email",
                               return_value={"sent": True}) as m:
            with mock.patch.object(store, "_with_db", return_value=True):
                store.add_notification("PERFORMANCE_ALERT", "t", "b", "WARN")
        self.assertTrue(m.called)
        self.assertEqual(m.call_args[0][0], "PERFORMANCE_ALERT")

    def test_add_notification_skips_other_kinds(self):
        import phase20_store as store
        with mock.patch.object(email_alerts, "maybe_send_alert_email") as m:
            with mock.patch.object(store, "_with_db", return_value=True):
                store.add_notification("SCAN_COMPLETE", "t", "b")
        self.assertFalse(m.called)

    def test_add_notification_survives_email_crash(self):
        import phase20_store as store
        with mock.patch.object(email_alerts, "maybe_send_alert_email",
                               side_effect=RuntimeError("boom")):
            with mock.patch.object(store, "_with_db", return_value=True):
                store.add_notification("CIRCUIT_BREAKER_TRIPPED", "t", "b")
        # No exception → pass

    def test_settings_validation_rejects_bad_address(self):
        import phase20_store as store
        with self.assertRaises(ValueError):
            store._validate_patch({"email_alert_address": "not-an-email"},
                                  dict(store.DEFAULT_SETTINGS))

    def test_settings_validation_accepts_good_and_empty(self):
        import phase20_store as store
        clean = store._validate_patch(
            {"email_alert_address": " Trader@Example.com ",
             "email_alerts_enabled": True},
            dict(store.DEFAULT_SETTINGS))
        self.assertEqual(clean["email_alert_address"], "Trader@Example.com")
        self.assertTrue(clean["email_alerts_enabled"])
        clean2 = store._validate_patch({"email_alert_address": ""},
                                       dict(store.DEFAULT_SETTINGS))
        self.assertEqual(clean2["email_alert_address"], "")


if __name__ == "__main__":
    unittest.main()
