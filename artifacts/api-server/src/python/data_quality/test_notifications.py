"""
data_quality/test_notifications.py — Task #256
Unit tests for critical data quality notifications.

Tests cover:
  - _add_notification shim is called for each unique CRITICAL issue
  - dedup suppresses repeat notifications within 30 minutes
  - notification fires again after the 30-minute window expires
  - no notification when no CRITICAL issues exist
  - _add_notification failure does not raise to the caller
  - correct kind, title, body, severity, and context are passed
  - DATA_QUALITY_CRITICAL is in email_alerts.EMAIL_KINDS
  - get_summary() calls _emit_critical_notifications
"""

import importlib
import time
import unittest
from unittest.mock import MagicMock, patch, call

PATCH_NOTIFY = "data_quality.shared_services._add_notification"


def _reload_ss():
    """Reload shared_services so the module-level dedup cache is fresh."""
    import data_quality.shared_services as ss
    ss._NOTIF_DEDUP.clear()
    return ss


def _make_domain(issues: list[dict]) -> dict:
    return {
        "available":      True,
        "score":          50.0,
        "checks_run":     len(issues) + 2,
        "checks_passed":  2,
        "critical_count": sum(1 for i in issues if i.get("severity") == "CRITICAL"),
        "warning_count":  sum(1 for i in issues if i.get("severity") == "WARNING"),
        "issues":         issues,
    }


def _blank_domain():
    return {
        "available": False, "score": 0, "issues": [],
        "critical_count": 0, "warning_count": 0,
        "checks_run": 0, "checks_passed": 0,
    }


def _critical(check, field, symbol="", message="Critical data issue"):
    return {
        "severity": "CRITICAL",
        "check":    check,
        "field":    field,
        "symbol":   symbol,
        "message":  message,
    }


def _warning(check, field):
    return {"severity": "WARNING", "check": check, "field": field}


class TestEmitCriticalNotifications(unittest.TestCase):

    def setUp(self):
        self.ss = _reload_ss()

    # ── Basic firing ──────────────────────────────────────────────────────────

    def test_add_notification_called_for_critical_issue(self):
        """A single CRITICAL issue triggers one _add_notification call."""
        mock_add = MagicMock()
        with patch("data_quality.shared_services.time.monotonic", return_value=1000.0), \
             patch(PATCH_NOTIFY, mock_add):
            domains = {
                "market": _make_domain([_critical("NEG_PRICE", "close", "RELIANCE")])
            }
            self.ss._emit_critical_notifications(domains)
        mock_add.assert_called_once()

    def test_add_notification_not_called_for_warning(self):
        """WARNING-level issues do not trigger a notification."""
        mock_add = MagicMock()
        with patch("data_quality.shared_services.time.monotonic", return_value=1000.0), \
             patch(PATCH_NOTIFY, mock_add):
            domains = {"market": _make_domain([_warning("STALE_DATA", "close")])}
            self.ss._emit_critical_notifications(domains)
        mock_add.assert_not_called()

    def test_no_notification_when_no_issues(self):
        """Empty issues list → no notification at all."""
        mock_add = MagicMock()
        with patch("data_quality.shared_services.time.monotonic", return_value=1000.0), \
             patch(PATCH_NOTIFY, mock_add):
            domains = {"market": _make_domain([])}
            self.ss._emit_critical_notifications(domains)
        mock_add.assert_not_called()

    def test_multiple_critical_issues_fire_individually(self):
        """Two distinct CRITICAL issues in one domain each get their own notification."""
        mock_add = MagicMock()
        with patch("data_quality.shared_services.time.monotonic", return_value=1000.0), \
             patch(PATCH_NOTIFY, mock_add):
            domains = {
                "market": _make_domain([
                    _critical("NEG_PRICE",  "close", "RELIANCE"),
                    _critical("OHLC_INVERT", "high",  "TCS"),
                ])
            }
            self.ss._emit_critical_notifications(domains)
        self.assertEqual(mock_add.call_count, 2)

    def test_critical_issues_across_multiple_domains(self):
        """CRITICAL issues across different domains each fire."""
        mock_add = MagicMock()
        with patch("data_quality.shared_services.time.monotonic", return_value=1000.0), \
             patch(PATCH_NOTIFY, mock_add):
            domains = {
                "market":    _make_domain([_critical("NEG_PRICE", "close")]),
                "portfolio": _make_domain([_critical("NEG_CAPITAL", "capital")]),
            }
            self.ss._emit_critical_notifications(domains)
        self.assertEqual(mock_add.call_count, 2)

    # ── Notification shape ─────────────────────────────────────────────────────

    def test_notification_kind_is_data_quality_critical(self):
        """Notification kind must be DATA_QUALITY_CRITICAL."""
        mock_add = MagicMock()
        with patch("data_quality.shared_services.time.monotonic", return_value=1000.0), \
             patch(PATCH_NOTIFY, mock_add):
            domains = {"market": _make_domain([_critical("NEG_PRICE", "close")])}
            self.ss._emit_critical_notifications(domains)
        kind = mock_add.call_args.kwargs.get("kind")
        self.assertEqual(kind, "DATA_QUALITY_CRITICAL")

    def test_notification_severity_is_critical(self):
        """Notification severity must be 'CRITICAL'."""
        mock_add = MagicMock()
        with patch("data_quality.shared_services.time.monotonic", return_value=1000.0), \
             patch(PATCH_NOTIFY, mock_add):
            domains = {"portfolio": _make_domain([_critical("NEG_CAPITAL", "capital")])}
            self.ss._emit_critical_notifications(domains)
        self.assertEqual(mock_add.call_args.kwargs.get("severity"), "CRITICAL")

    def test_notification_title_contains_check_name(self):
        """Notification title includes the check name."""
        mock_add = MagicMock()
        with patch("data_quality.shared_services.time.monotonic", return_value=1000.0), \
             patch(PATCH_NOTIFY, mock_add):
            domains = {"market": _make_domain([_critical("NEG_PRICE", "close")])}
            self.ss._emit_critical_notifications(domains)
        self.assertIn("NEG_PRICE", mock_add.call_args.kwargs.get("title", ""))

    def test_notification_body_contains_domain(self):
        """Notification body includes the domain name."""
        mock_add = MagicMock()
        with patch("data_quality.shared_services.time.monotonic", return_value=1000.0), \
             patch(PATCH_NOTIFY, mock_add):
            domains = {"portfolio": _make_domain([_critical("NEG_CAPITAL", "capital")])}
            self.ss._emit_critical_notifications(domains)
        self.assertIn("portfolio", mock_add.call_args.kwargs.get("body", ""))

    def test_notification_body_contains_symbol_when_present(self):
        """Notification body includes the symbol when non-empty."""
        mock_add = MagicMock()
        with patch("data_quality.shared_services.time.monotonic", return_value=1000.0), \
             patch(PATCH_NOTIFY, mock_add):
            domains = {"market": _make_domain([_critical("NEG_PRICE", "close", "RELIANCE")])}
            self.ss._emit_critical_notifications(domains)
        self.assertIn("RELIANCE", mock_add.call_args.kwargs.get("body", ""))

    def test_notification_context_has_advisory_only(self):
        """Context dict always contains advisory_only: True."""
        mock_add = MagicMock()
        with patch("data_quality.shared_services.time.monotonic", return_value=1000.0), \
             patch(PATCH_NOTIFY, mock_add):
            domains = {"market": _make_domain([_critical("NEG_PRICE", "close")])}
            self.ss._emit_critical_notifications(domains)
        ctx = mock_add.call_args.kwargs.get("context", {})
        self.assertTrue(ctx.get("advisory_only"))

    def test_notification_context_has_domain_and_check(self):
        """Context dict includes domain, check, field, and symbol."""
        mock_add = MagicMock()
        with patch("data_quality.shared_services.time.monotonic", return_value=1000.0), \
             patch(PATCH_NOTIFY, mock_add):
            domains = {"ai": _make_domain([_critical("MODEL_DEGRADED", "accuracy", "AI")])}
            self.ss._emit_critical_notifications(domains)
        ctx = mock_add.call_args.kwargs.get("context", {})
        self.assertEqual(ctx.get("domain"), "ai")
        self.assertEqual(ctx.get("check"),  "MODEL_DEGRADED")

    def test_notification_context_has_field_and_symbol(self):
        """Context includes the field and symbol from the issue."""
        mock_add = MagicMock()
        with patch("data_quality.shared_services.time.monotonic", return_value=1000.0), \
             patch(PATCH_NOTIFY, mock_add):
            domains = {"market": _make_domain([_critical("NEG_PRICE", "close", "INFY")])}
            self.ss._emit_critical_notifications(domains)
        ctx = mock_add.call_args.kwargs.get("context", {})
        self.assertEqual(ctx.get("field"),  "close")
        self.assertEqual(ctx.get("symbol"), "INFY")

    # ── Deduplication ──────────────────────────────────────────────────────────

    def test_dedup_suppresses_second_call_within_30_minutes(self):
        """Same check+domain+field+symbol does not fire twice within 30 minutes."""
        mock_add = MagicMock()
        issue = _critical("NEG_PRICE", "close", "RELIANCE")
        domains = {"market": _make_domain([issue])}

        with patch(PATCH_NOTIFY, mock_add):
            with patch("data_quality.shared_services.time.monotonic", return_value=1000.0):
                self.ss._emit_critical_notifications(domains)
            # Second call within the 30-minute window (only 60s later)
            with patch("data_quality.shared_services.time.monotonic", return_value=1060.0):
                self.ss._emit_critical_notifications(domains)

        self.assertEqual(mock_add.call_count, 1)

    def test_dedup_fires_again_after_ttl_expires(self):
        """After the 30-minute window, the same issue fires a second notification."""
        mock_add = MagicMock()
        issue = _critical("NEG_PRICE", "close", "RELIANCE")
        domains = {"market": _make_domain([issue])}

        with patch(PATCH_NOTIFY, mock_add):
            with patch("data_quality.shared_services.time.monotonic", return_value=1000.0):
                self.ss._emit_critical_notifications(domains)
            # Second call after TTL elapsed (1800 + 1 = 1801s later)
            with patch("data_quality.shared_services.time.monotonic", return_value=2801.0):
                self.ss._emit_critical_notifications(domains)

        self.assertEqual(mock_add.call_count, 2)

    def test_dedup_boundary_exactly_at_ttl(self):
        """At exactly 1800s, the window is no longer < TTL, so the notification fires again."""
        mock_add = MagicMock()
        issue = _critical("NEG_PRICE", "close")
        domains = {"market": _make_domain([issue])}

        with patch(PATCH_NOTIFY, mock_add):
            with patch("data_quality.shared_services.time.monotonic", return_value=1000.0):
                self.ss._emit_critical_notifications(domains)
            # Exactly at TTL: now - last_sent == 1800, and 1800 < 1800 is False → fires
            with patch("data_quality.shared_services.time.monotonic", return_value=2800.0):
                self.ss._emit_critical_notifications(domains)

        self.assertEqual(mock_add.call_count, 2)

    def test_dedup_keys_are_independent_per_symbol(self):
        """Different symbols for the same check each get their own notification."""
        mock_add = MagicMock()
        domains = {
            "market": _make_domain([
                _critical("NEG_PRICE", "close", "RELIANCE"),
                _critical("NEG_PRICE", "close", "TCS"),
            ])
        }
        with patch("data_quality.shared_services.time.monotonic", return_value=1000.0), \
             patch(PATCH_NOTIFY, mock_add):
            self.ss._emit_critical_notifications(domains)
        self.assertEqual(mock_add.call_count, 2)

    def test_dedup_keys_are_independent_per_domain(self):
        """Same check in two different domains both fire."""
        mock_add = MagicMock()
        domains = {
            "market":    _make_domain([_critical("STALE_FEED", "timestamp")]),
            "portfolio": _make_domain([_critical("STALE_FEED", "timestamp")]),
        }
        with patch("data_quality.shared_services.time.monotonic", return_value=1000.0), \
             patch(PATCH_NOTIFY, mock_add):
            self.ss._emit_critical_notifications(domains)
        self.assertEqual(mock_add.call_count, 2)

    def test_dedup_cache_updated_after_successful_notification(self):
        """After firing, the dedup cache records the timestamp."""
        mock_add = MagicMock()
        issue = _critical("NEG_PRICE", "close")
        domains = {"market": _make_domain([issue])}

        with patch("data_quality.shared_services.time.monotonic", return_value=5000.0), \
             patch(PATCH_NOTIFY, mock_add):
            self.ss._emit_critical_notifications(domains)

        key = "market|NEG_PRICE|close|"
        self.assertIn(key, self.ss._NOTIF_DEDUP)
        self.assertAlmostEqual(self.ss._NOTIF_DEDUP[key], 5000.0)

    def test_dedup_cache_not_updated_when_notification_fails(self):
        """When _add_notification raises, the dedup key is NOT stored so it fires again."""
        def always_fail(**kw):
            raise RuntimeError("DB is down")

        issue = _critical("NEG_PRICE", "close")
        domains = {"market": _make_domain([issue])}

        with patch("data_quality.shared_services.time.monotonic", return_value=1000.0), \
             patch(PATCH_NOTIFY, side_effect=always_fail):
            self.ss._emit_critical_notifications(domains)

        key = "market|NEG_PRICE|close|"
        self.assertNotIn(key, self.ss._NOTIF_DEDUP)

    # ── Resilience ────────────────────────────────────────────────────────────

    def test_notification_failure_does_not_raise(self):
        """Even if _add_notification raises, _emit_critical_notifications never raises."""
        def boom(**kw):
            raise RuntimeError("DB is down")

        with patch("data_quality.shared_services.time.monotonic", return_value=1000.0), \
             patch(PATCH_NOTIFY, side_effect=boom):
            domains = {"market": _make_domain([_critical("NEG_PRICE", "close")])}
            self.ss._emit_critical_notifications(domains)   # must not raise

    def test_second_issue_fires_even_if_first_notification_fails(self):
        """A notification failure for issue A should not block issue B."""
        call_count = 0

        def partial_fail(**kw):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("first one fails")

        domains = {
            "market": _make_domain([
                _critical("NEG_PRICE",  "close", "RELIANCE"),
                _critical("OHLC_INVERT", "high",  "TCS"),
            ])
        }
        with patch("data_quality.shared_services.time.monotonic", return_value=1000.0), \
             patch(PATCH_NOTIFY, side_effect=partial_fail):
            self.ss._emit_critical_notifications(domains)

        self.assertEqual(call_count, 2)

    def test_mixed_severities_only_critical_notifies(self):
        """Only CRITICAL issues fire; WARNING and INFO are ignored."""
        mock_add = MagicMock()
        domains = {
            "market": _make_domain([
                _critical("NEG_PRICE",  "close"),
                _warning( "STALE_DATA", "timestamp"),
                {"severity": "INFO", "check": "INFO_CHECK", "field": "x"},
            ])
        }
        with patch("data_quality.shared_services.time.monotonic", return_value=1000.0), \
             patch(PATCH_NOTIFY, mock_add):
            self.ss._emit_critical_notifications(domains)
        self.assertEqual(mock_add.call_count, 1)

    # ── Integration with get_summary ──────────────────────────────────────────

    def test_get_summary_calls_emit_when_critical_issues_exist(self):
        """get_summary() triggers notification emit (patching the emit function)."""
        mock_emit = MagicMock()
        blank = _blank_domain()
        market_domain = _make_domain([_critical("NEG_PRICE", "close")])

        with patch("data_quality.models.is_enabled", return_value=True), \
             patch("data_quality.shared_services._load_market",    return_value=market_domain), \
             patch("data_quality.shared_services._load_preopen",   return_value={**blank}), \
             patch("data_quality.shared_services._load_paper",     return_value={**blank}), \
             patch("data_quality.shared_services._load_portfolio",  return_value={**blank}), \
             patch("data_quality.shared_services._load_ai",        return_value={**blank}), \
             patch("data_quality.shared_services._load_signals",   return_value={**blank}), \
             patch("data_quality.shared_services._load_config",    return_value={**blank}), \
             patch("data_quality.shared_services._emit_critical_notifications", mock_emit):
            self.ss.get_summary()

        mock_emit.assert_called_once()

    def test_get_summary_passes_domains_dict_to_emit(self):
        """get_summary() passes the full domains dict to _emit_critical_notifications."""
        captured = {}

        def capture_emit(domains):
            captured.update(domains)

        blank = _blank_domain()
        market_domain = _make_domain([_critical("NEG_PRICE", "close")])

        with patch("data_quality.models.is_enabled", return_value=True), \
             patch("data_quality.shared_services._load_market",    return_value=market_domain), \
             patch("data_quality.shared_services._load_preopen",   return_value={**blank}), \
             patch("data_quality.shared_services._load_paper",     return_value={**blank}), \
             patch("data_quality.shared_services._load_portfolio",  return_value={**blank}), \
             patch("data_quality.shared_services._load_ai",        return_value={**blank}), \
             patch("data_quality.shared_services._load_signals",   return_value={**blank}), \
             patch("data_quality.shared_services._load_config",    return_value={**blank}), \
             patch("data_quality.shared_services._emit_critical_notifications",
                   side_effect=capture_emit):
            self.ss.get_summary()

        self.assertIn("market", captured)

    def test_get_summary_emit_failure_does_not_raise(self):
        """If _emit_critical_notifications raises, get_summary() still returns normally."""
        def boom(domains):
            raise RuntimeError("notification system is down")

        blank = _blank_domain()

        with patch("data_quality.models.is_enabled", return_value=True), \
             patch("data_quality.shared_services._load_market",    return_value={**blank}), \
             patch("data_quality.shared_services._load_preopen",   return_value={**blank}), \
             patch("data_quality.shared_services._load_paper",     return_value={**blank}), \
             patch("data_quality.shared_services._load_portfolio",  return_value={**blank}), \
             patch("data_quality.shared_services._load_ai",        return_value={**blank}), \
             patch("data_quality.shared_services._load_signals",   return_value={**blank}), \
             patch("data_quality.shared_services._load_config",    return_value={**blank}), \
             patch("data_quality.shared_services._emit_critical_notifications",
                   side_effect=boom):
            result = self.ss.get_summary()   # must not raise

        self.assertEqual(result.get("status"), "ENABLED")

    # ── Email kind registration ───────────────────────────────────────────────

    def test_data_quality_critical_in_email_kinds(self):
        """DATA_QUALITY_CRITICAL must appear in email_alerts.EMAIL_KINDS."""
        import email_alerts
        self.assertIn("DATA_QUALITY_CRITICAL", email_alerts.EMAIL_KINDS)

    def test_data_quality_critical_constant_value(self):
        """The constant equals the string 'DATA_QUALITY_CRITICAL'."""
        from data_quality.models import DATA_QUALITY_CRITICAL as KIND
        self.assertEqual(KIND, "DATA_QUALITY_CRITICAL")

    # ── TTL constant ──────────────────────────────────────────────────────────

    def test_notif_ttl_is_30_minutes(self):
        """The dedup TTL must be exactly 1800 seconds (30 minutes)."""
        self.assertEqual(self.ss._NOTIF_TTL_SECONDS, 1800)


if __name__ == "__main__":
    unittest.main()
