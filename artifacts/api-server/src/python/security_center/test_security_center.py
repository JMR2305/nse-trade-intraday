"""
test_security_center.py — Phase 8.6
Unit tests for the Security & Compliance Centre.

Tests cover:
  - Feature flag gate
  - Secret validation (presence / missing / weak)
  - Session validation
  - Authentication checks
  - Configuration audit
  - API security checks
  - Dependency audit
  - Alert aggregation
  - Compliance scoring
  - Audit log
  - API command wrappers
  - Export (JSON + CSV)
  - Snapshot interface
  - Grade / risk helpers

READ-ONLY. ADVISORY-ONLY.
Tests never expose secret values, write to env, or modify config.
"""
from __future__ import annotations

import os
import pytest
from unittest.mock import patch, MagicMock

MOD = "security_center.shared_services"

# ── Shared stubs ───────────────────────────────────────────────────────────────

def _secrets_ok():
    return {"available": True, "score": 80, "missing_count": 0,
            "weak_count": 0, "critical_missing": 0, "checks": [], "alerts": []}

def _secrets_bad():
    return {"available": True, "score": 40, "missing_count": 2,
            "weak_count": 1, "critical_missing": 1, "checks": [],
            "alerts": [{"alert_id": "x", "severity": "CRITICAL", "category": "secrets",
                        "title": "Missing secret", "detail": "SESSION_SECRET missing"}]}

def _sessions_ok():
    return {"available": True, "score": 100, "alerts": [],
            "session_secret_present": True, "session_secret_strong": True}

def _sessions_bad():
    return {"available": True, "score": 40, "alerts": [
        {"alert_id": "sess_secret_missing", "severity": "CRITICAL",
         "category": "sessions", "title": "SESSION_SECRET not configured", "detail": "..."}
    ], "session_secret_present": False, "session_secret_strong": False}

def _cfg_ok():
    return {"available": True, "score": 85, "ok_count": 6, "missing_count": 1,
            "invalid_count": 0, "checks": [], "alerts": []}

def _api_ok():
    return {"available": True, "score": 90, "ok_count": 7, "warning_count": 1,
            "checks": [], "alerts": [], "https_enabled": True, "node_env": "production"}

def _deps_ok():
    return {"available": True, "score": 100, "advisory_count": 0,
            "python_advisories": [], "python_package_count": 45, "node_package_count": 120, "alerts": []}

def _deps_bad():
    return {"available": True, "score": 80, "advisory_count": 2,
            "python_advisories": [
                {"package": "urllib3", "installed": "1.25.0",
                 "vulnerable_below": "1.26.5", "advisory": "CVE test"}
            ], "python_package_count": 45, "node_package_count": 120,
            "alerts": [{"alert_id": "dep_urllib3", "severity": "WARNING",
                        "category": "dependencies", "title": "Dependency Advisory: urllib3",
                        "detail": "v1.25.0 — CVE test"}]}

def _auth_ok():
    return {"available": True, "score": 100, "alerts": [],
            "zerodha_mode_enabled": False, "zerodha_key_present": True,
            "zerodha_secret_present": True}

_ALL_LOADERS = {
    "_validate_secrets":  _secrets_ok,
    "_validate_sessions": _sessions_ok,
    "_check_auth":        _auth_ok,
    "_audit_config":      _cfg_ok,
    "_check_api_security":_api_ok,
    "_audit_dependencies":_deps_ok,
}


# ── Feature flag ───────────────────────────────────────────────────────────────

class TestFeatureFlag:
    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("SECURITY_CENTER_ENABLED", raising=False)
        from security_center.models import is_enabled
        assert is_enabled() is False

    def test_enabled_true(self, monkeypatch):
        monkeypatch.setenv("SECURITY_CENTER_ENABLED", "true")
        from security_center.models import is_enabled
        assert is_enabled() is True

    def test_enabled_1(self, monkeypatch):
        monkeypatch.setenv("SECURITY_CENTER_ENABLED", "1")
        from security_center.models import is_enabled
        assert is_enabled() is True

    def test_disabled_returns_status(self, monkeypatch):
        monkeypatch.delenv("SECURITY_CENTER_ENABLED", raising=False)
        from security_center.shared_services import get_summary
        r = get_summary()
        assert r["status"] == "DISABLED"
        assert r["available"] is False

    def test_all_endpoints_disabled_when_flag_off(self, monkeypatch):
        monkeypatch.delenv("SECURITY_CENTER_ENABLED", raising=False)
        from security_center.shared_services import (
            get_auth, get_sessions, get_secrets, get_config,
            get_api_security, get_dependencies, get_audit_log,
            get_compliance, get_alerts, get_security_snapshot,
        )
        for fn in [get_auth, get_sessions, get_secrets, get_config,
                   get_api_security, get_dependencies, get_audit_log,
                   get_compliance, get_alerts, get_security_snapshot]:
            r = fn()
            assert r["available"] is False, f"{fn.__name__} should be disabled"


# ── Secret validation ──────────────────────────────────────────────────────────

class TestSecretValidation:
    def setup_method(self): os.environ["SECURITY_CENTER_ENABLED"] = "true"
    def teardown_method(self): os.environ.pop("SECURITY_CENTER_ENABLED", None)

    def test_secret_present_when_set(self, monkeypatch):
        monkeypatch.setenv("SESSION_SECRET", "a" * 40)
        from security_center.shared_services import _check_secret
        from security_center.models import REQUIRED_SECRETS
        ss = next(s for s in REQUIRED_SECRETS if s["name"] == "SESSION_SECRET")
        result = _check_secret(ss)
        assert result.presence == "PRESENT"

    def test_secret_missing_when_not_set(self, monkeypatch):
        monkeypatch.delenv("SESSION_SECRET", raising=False)
        from security_center.shared_services import _check_secret
        from security_center.models import REQUIRED_SECRETS
        ss = next(s for s in REQUIRED_SECRETS if s["name"] == "SESSION_SECRET")
        result = _check_secret(ss)
        assert result.presence == "MISSING"

    def test_secret_weak_when_too_short(self, monkeypatch):
        monkeypatch.setenv("SESSION_SECRET", "short")
        from security_center.shared_services import _check_secret
        from security_center.models import REQUIRED_SECRETS
        ss = next(s for s in REQUIRED_SECRETS if s["name"] == "SESSION_SECRET")
        result = _check_secret(ss)
        assert result.presence == "WEAK"

    def test_secret_value_never_in_detail(self, monkeypatch):
        secret_val = "ThisIsMyRealSecret1234567890abc"
        monkeypatch.setenv("SESSION_SECRET", secret_val)
        from security_center.shared_services import _check_secret, _validate_secrets
        from security_center.models import REQUIRED_SECRETS
        ss = next(s for s in REQUIRED_SECRETS if s["name"] == "SESSION_SECRET")
        check = _check_secret(ss)
        assert secret_val not in check.detail
        full = _validate_secrets()
        for c in full.get("checks", []):
            assert secret_val not in str(c)

    def test_validate_secrets_keys(self):
        from security_center.shared_services import _validate_secrets
        r = _validate_secrets()
        for k in ("checks", "present_count", "missing_count", "weak_count", "score", "alerts"):
            assert k in r

    def test_validate_secrets_advisory_only(self):
        from security_center.shared_services import _validate_secrets
        r = _validate_secrets()
        assert r["advisory_only"] is True
        assert r["read_only"] is True

    def test_all_secrets_checked(self):
        from security_center.shared_services import _validate_secrets
        from security_center.models import REQUIRED_SECRETS
        r = _validate_secrets()
        assert len(r["checks"]) == len(REQUIRED_SECRETS)

    def test_missing_secret_generates_alert(self, monkeypatch):
        monkeypatch.delenv("SESSION_SECRET", raising=False)
        from security_center.shared_services import _validate_secrets
        r = _validate_secrets()
        alert_ids = [a["alert_id"] for a in r["alerts"]]
        assert any("session_secret" in aid for aid in alert_ids)


# ── Session validation ─────────────────────────────────────────────────────────

class TestSessionValidation:
    def setup_method(self): os.environ["SECURITY_CENTER_ENABLED"] = "true"
    def teardown_method(self): os.environ.pop("SECURITY_CENTER_ENABLED", None)

    def test_session_keys(self, monkeypatch):
        monkeypatch.setenv("SESSION_SECRET", "x" * 40)
        from security_center.shared_services import _validate_sessions
        r = _validate_sessions()
        for k in ("session_secret_present", "session_secret_strong", "score", "alerts", "advisory_only"):
            assert k in r

    def test_session_present_when_set(self, monkeypatch):
        monkeypatch.setenv("SESSION_SECRET", "strongsecretvalue1234567890!@#$XY")
        from security_center.shared_services import _validate_sessions
        r = _validate_sessions()
        assert r["session_secret_present"] is True
        assert r["session_secret_strong"] is True
        assert r["score"] == 100.0

    def test_session_missing_alert(self, monkeypatch):
        monkeypatch.delenv("SESSION_SECRET", raising=False)
        from security_center.shared_services import _validate_sessions
        r = _validate_sessions()
        assert r["session_secret_present"] is False
        assert len(r["alerts"]) > 0
        assert r["score"] < 60

    def test_session_weak_alert(self, monkeypatch):
        monkeypatch.setenv("SESSION_SECRET", "tooshort")
        from security_center.shared_services import _validate_sessions
        r = _validate_sessions()
        assert r["session_secret_strong"] is False

    def test_session_advisory_only(self, monkeypatch):
        monkeypatch.setenv("SESSION_SECRET", "x" * 40)
        from security_center.shared_services import _validate_sessions
        r = _validate_sessions()
        assert r["advisory_only"] is True


# ── Authentication check ───────────────────────────────────────────────────────

class TestAuthCheck:
    def setup_method(self): os.environ["SECURITY_CENTER_ENABLED"] = "true"
    def teardown_method(self): os.environ.pop("SECURITY_CENTER_ENABLED", None)

    def test_auth_keys(self):
        loaders = {"_load_observability": lambda: {"system_status": "HEALTHY", "available": True}}
        with patch.multiple(MOD, **loaders):
            from security_center.shared_services import _check_auth
            r = _check_auth()
        for k in ("zerodha_mode_enabled", "zerodha_key_present", "score", "alerts", "advisory_only"):
            assert k in r

    def test_auth_alert_when_zerodha_mode_missing_key(self, monkeypatch):
        monkeypatch.setenv("ZERODHA_ENABLED", "true")
        monkeypatch.delenv("ZERODHA_API_KEY", raising=False)
        loaders = {"_load_observability": lambda: {"system_status": "HEALTHY", "available": True}}
        with patch.multiple(MOD, **loaders):
            from security_center.shared_services import _check_auth
            r = _check_auth()
        assert len(r["alerts"]) > 0
        assert r["score"] < 100
        monkeypatch.delenv("ZERODHA_ENABLED", raising=False)

    def test_auth_ok_when_not_live(self, monkeypatch):
        monkeypatch.delenv("ZERODHA_ENABLED", raising=False)
        loaders = {"_load_observability": lambda: {"system_status": "HEALTHY", "available": True}}
        with patch.multiple(MOD, **loaders):
            from security_center.shared_services import _check_auth
            r = _check_auth()
        assert r["zerodha_mode_enabled"] is False
        assert r["score"] == 100.0

    def test_auth_advisory_only(self):
        loaders = {"_load_observability": lambda: {"available": False}}
        with patch.multiple(MOD, **loaders):
            from security_center.shared_services import _check_auth
            r = _check_auth()
        assert r["advisory_only"] is True


# ── Configuration audit ────────────────────────────────────────────────────────

class TestConfigAudit:
    def setup_method(self): os.environ["SECURITY_CENTER_ENABLED"] = "true"
    def teardown_method(self): os.environ.pop("SECURITY_CENTER_ENABLED", None)

    def test_config_keys(self):
        from security_center.shared_services import _audit_config
        r = _audit_config()
        for k in ("checks", "ok_count", "missing_count", "invalid_count", "score", "alerts"):
            assert k in r

    def test_config_checks_all_required(self):
        from security_center.shared_services import _audit_config
        from security_center.models import REQUIRED_CONFIG
        r = _audit_config()
        assert len(r["checks"]) == len(REQUIRED_CONFIG)

    def test_config_score_range(self):
        from security_center.shared_services import _audit_config
        r = _audit_config()
        assert 0 <= r["score"] <= 100

    def test_config_advisory_only(self):
        from security_center.shared_services import _audit_config
        r = _audit_config()
        assert r["advisory_only"] is True
        assert r["read_only"] is True

    def test_config_missing_generates_alert(self, monkeypatch):
        monkeypatch.delenv("PORT", raising=False)
        from security_center.shared_services import _audit_config
        r = _audit_config()
        alert_cats = [a["category"] for a in r["alerts"]]
        assert "configuration" in alert_cats


# ── API security check ─────────────────────────────────────────────────────────

class TestApiSecurity:
    def setup_method(self): os.environ["SECURITY_CENTER_ENABLED"] = "true"
    def teardown_method(self): os.environ.pop("SECURITY_CENTER_ENABLED", None)

    def test_api_sec_keys(self):
        loaders = {"_load_observability": lambda: {"system_status": "HEALTHY", "available": True}}
        with patch.multiple(MOD, **loaders):
            from security_center.shared_services import _check_api_security
            r = _check_api_security()
        for k in ("checks", "ok_count", "https_enabled", "score", "alerts", "advisory_only"):
            assert k in r

    def test_api_sec_checks_list(self):
        loaders = {"_load_observability": lambda: {"available": False}}
        with patch.multiple(MOD, **loaders):
            from security_center.shared_services import _check_api_security
            r = _check_api_security()
        assert isinstance(r["checks"], list)
        assert len(r["checks"]) > 0

    def test_api_sec_advisory_only(self):
        loaders = {"_load_observability": lambda: {"available": False}}
        with patch.multiple(MOD, **loaders):
            from security_center.shared_services import _check_api_security
            r = _check_api_security()
        assert r["advisory_only"] is True

    def test_api_sec_score_range(self):
        loaders = {"_load_observability": lambda: {"system_status": "HEALTHY", "available": True}}
        with patch.multiple(MOD, **loaders):
            from security_center.shared_services import _check_api_security
            r = _check_api_security()
        assert 0 <= r["score"] <= 100

    def test_missing_session_secret_raises_critical(self, monkeypatch):
        monkeypatch.delenv("SESSION_SECRET", raising=False)
        loaders = {"_load_observability": lambda: {"available": False}}
        with patch.multiple(MOD, **loaders):
            from security_center.shared_services import _check_api_security
            r = _check_api_security()
        critical = [c for c in r["checks"] if c["check"] == "session_secret" and c["status"] == "CRITICAL"]
        assert len(critical) == 1


# ── Dependency audit ───────────────────────────────────────────────────────────

class TestDependencyAudit:
    def setup_method(self): os.environ["SECURITY_CENTER_ENABLED"] = "true"
    def teardown_method(self): os.environ.pop("SECURITY_CENTER_ENABLED", None)

    def test_dep_keys(self):
        with patch.multiple(MOD, _audit_python_deps=lambda: ([], [])):
            from security_center.shared_services import _audit_dependencies
            r = _audit_dependencies()
        for k in ("python_package_count", "advisory_count", "score", "alerts", "advisory_only"):
            assert k in r

    def test_dep_advisory_only(self):
        with patch.multiple(MOD, _audit_python_deps=lambda: ([], [])):
            from security_center.shared_services import _audit_dependencies
            r = _audit_dependencies()
        assert r["advisory_only"] is True
        assert "do not auto-update" in r.get("note", "").lower()

    def test_dep_advisory_generates_alert(self):
        advisories = [{"package": "urllib3", "installed": "1.25.0",
                       "vulnerable_below": "1.26.5", "advisory": "Test",
                       "severity": "WARNING"}]
        with patch.multiple(MOD, _audit_python_deps=lambda: ([{"name": "urllib3", "version": "1.25.0"}], advisories)):
            from security_center.shared_services import _audit_dependencies
            r = _audit_dependencies()
        assert r["advisory_count"] >= 1
        assert len(r["alerts"]) >= 1

    def test_dep_score_decreases_with_advisories(self):
        advisories = [{"package": "x", "installed": "1.0", "vulnerable_below": "2.0",
                       "advisory": "Test", "severity": "WARNING"} for _ in range(3)]
        with patch.multiple(MOD, _audit_python_deps=lambda: ([], advisories)):
            from security_center.shared_services import _audit_dependencies
            r = _audit_dependencies()
        assert r["score"] < 100

    def test_version_comparison(self):
        from security_center.shared_services import _version_below
        assert _version_below("1.25.0", "1.26.5") is True
        assert _version_below("1.27.0", "1.26.5") is False
        assert _version_below("2.0.0", "1.26.5") is False


# ── Alert aggregation ──────────────────────────────────────────────────────────

class TestAlertAggregation:
    def setup_method(self): os.environ["SECURITY_CENTER_ENABLED"] = "true"
    def teardown_method(self): os.environ.pop("SECURITY_CENTER_ENABLED", None)

    def test_alerts_keys(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from security_center.shared_services import get_alerts
            r = get_alerts()
        for k in ("all", "critical", "warnings", "info", "critical_count", "warning_count", "total"):
            assert k in r

    def test_alerts_counts_consistent(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from security_center.shared_services import get_alerts
            r = get_alerts()
        assert r["critical_count"] == len(r["critical"])
        assert r["warning_count"]  == len(r["warnings"])

    def test_alerts_critical_from_bad_secrets(self):
        loaders = {**_ALL_LOADERS, "_validate_secrets": _secrets_bad, "_validate_sessions": _sessions_bad}
        with patch.multiple(MOD, **loaders):
            from security_center.shared_services import get_alerts
            r = get_alerts()
        assert r["critical_count"] >= 1

    def test_alerts_advisory_only(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from security_center.shared_services import get_alerts
            r = get_alerts()
        assert r["advisory_only"] is True

    def test_dep_advisories_become_warnings(self):
        loaders = {**_ALL_LOADERS, "_audit_dependencies": _deps_bad}
        with patch.multiple(MOD, **loaders):
            from security_center.shared_services import get_alerts
            r = get_alerts()
        assert r["warning_count"] >= 1


# ── Compliance scoring ─────────────────────────────────────────────────────────

class TestComplianceScore:
    def setup_method(self): os.environ["SECURITY_CENTER_ENABLED"] = "true"
    def teardown_method(self): os.environ.pop("SECURITY_CENTER_ENABLED", None)

    def test_compliance_keys(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from security_center.shared_services import get_compliance
            r = get_compliance()
        for k in ("security_score", "session_score", "config_score", "api_score",
                  "dependency_score", "overall_score", "grade", "risk_level"):
            assert k in r

    def test_compliance_score_range(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from security_center.shared_services import get_compliance
            r = get_compliance()
        assert 0 <= r["overall_score"] <= 100

    def test_compliance_grade_valid(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from security_center.shared_services import get_compliance
            r = get_compliance()
        assert r["grade"] in ("A+", "A", "B", "C", "D")

    def test_compliance_risk_level_valid(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from security_center.shared_services import get_compliance
            r = get_compliance()
        assert r["risk_level"] in ("LOW", "MEDIUM", "HIGH", "CRITICAL")

    def test_compliance_advisory_only(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from security_center.shared_services import get_compliance
            r = get_compliance()
        assert r["advisory_only"] is True

    def test_compliance_score_decreases_with_issues(self):
        bad_loaders = {**_ALL_LOADERS,
                       "_validate_secrets": _secrets_bad,
                       "_validate_sessions": _sessions_bad}
        with patch.multiple(MOD, **_ALL_LOADERS):
            from security_center.shared_services import get_compliance
            good = get_compliance()
        with patch.multiple(MOD, **bad_loaders):
            from security_center.shared_services import get_compliance
            bad  = get_compliance()
        assert bad["overall_score"] < good["overall_score"]


# ── Summary ────────────────────────────────────────────────────────────────────

class TestSummary:
    def setup_method(self): os.environ["SECURITY_CENTER_ENABLED"] = "true"
    def teardown_method(self): os.environ.pop("SECURITY_CENTER_ENABLED", None)

    def test_summary_keys(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from security_center.shared_services import get_summary
            r = get_summary()
        required = ["security_score", "grade", "risk_level", "security_status",
                    "critical_alerts", "warning_alerts", "missing_secrets",
                    "weak_secrets", "config_issues", "dep_advisories",
                    "generated_at", "available", "advisory_only", "read_only"]
        for k in required:
            assert k in r, f"Missing key: {k}"

    def test_summary_advisory_only(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from security_center.shared_services import get_summary
            r = get_summary()
        assert r["advisory_only"] is True
        assert r["read_only"] is True

    def test_summary_grade_valid(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from security_center.shared_services import get_summary
            r = get_summary()
        assert r["grade"] in ("A+", "A", "B", "C", "D")

    def test_summary_security_status_valid(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from security_center.shared_services import get_summary
            r = get_summary()
        assert r["security_status"] in ("SECURE", "DEGRADED", "AT_RISK", "UNKNOWN")


# ── Audit log ──────────────────────────────────────────────────────────────────

class TestAuditLog:
    def setup_method(self): os.environ["SECURITY_CENTER_ENABLED"] = "true"
    def teardown_method(self): os.environ.pop("SECURITY_CENTER_ENABLED", None)

    def test_audit_keys(self):
        loaders = {"_load_scan_runs": lambda limit=20: [],
                   "_load_notifications": lambda limit=30: []}
        with patch.multiple(MOD, **loaders):
            from security_center.shared_services import get_audit_log
            r = get_audit_log()
        assert "events" in r
        assert "total" in r

    def test_audit_has_platform_event(self):
        loaders = {"_load_scan_runs": lambda limit=20: [],
                   "_load_notifications": lambda limit=30: []}
        with patch.multiple(MOD, **loaders):
            from security_center.shared_services import get_audit_log
            r = get_audit_log()
        cats = [e["category"] for e in r["events"]]
        assert "SECURITY" in cats

    def test_audit_with_scan_runs(self):
        loaders = {
            "_load_scan_runs": lambda limit=20: [
                {"run_id": "r1", "status": "SUCCESS", "started_at": "2024-01-15T10:00:00",
                 "duration_seconds": 45, "symbols_scanned": 50}
            ],
            "_load_notifications": lambda limit=30: [],
        }
        with patch.multiple(MOD, **loaders):
            from security_center.shared_services import get_audit_log
            r = get_audit_log()
        sched = [e for e in r["events"] if e["category"] == "SCHEDULER"]
        assert len(sched) >= 1

    def test_audit_advisory_only(self):
        loaders = {"_load_scan_runs": lambda limit=20: [],
                   "_load_notifications": lambda limit=30: []}
        with patch.multiple(MOD, **loaders):
            from security_center.shared_services import get_audit_log
            r = get_audit_log()
        assert r["advisory_only"] is True


# ── Export ─────────────────────────────────────────────────────────────────────

class TestExport:
    def setup_method(self): os.environ["SECURITY_CENTER_ENABLED"] = "true"
    def teardown_method(self): os.environ.pop("SECURITY_CENTER_ENABLED", None)

    def test_export_json_keys(self):
        audit_loaders = {"_load_scan_runs": lambda limit=20: [],
                         "_load_notifications": lambda limit=30: []}
        with patch.multiple(MOD, **{**_ALL_LOADERS, **audit_loaders}):
            from security_center.shared_services import export_json
            r = export_json()
        for k in ("summary", "auth", "sessions", "secrets", "config",
                  "api_security", "dependencies", "audit_log", "compliance",
                  "alerts", "exported_at"):
            assert k in r

    def test_export_json_advisory_only(self):
        audit_loaders = {"_load_scan_runs": lambda limit=20: [],
                         "_load_notifications": lambda limit=30: []}
        with patch.multiple(MOD, **{**_ALL_LOADERS, **audit_loaders}):
            from security_center.shared_services import export_json
            r = export_json()
        assert r["advisory_only"] is True
        assert r["read_only"] is True

    def test_export_csv_has_csv_key(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from security_center.shared_services import export_csv
            r = export_csv()
        assert "csv" in r
        assert "security_score" in r["csv"]
        assert "generated_at" in r["csv"]

    def test_export_csv_format(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from security_center.shared_services import export_csv
            r = export_csv()
        lines = r["csv"].strip().split("\n")
        assert lines[0] == "metric,value"
        assert len(lines) > 10


# ── Snapshot interface ─────────────────────────────────────────────────────────

class TestSnapshot:
    def setup_method(self): os.environ["SECURITY_CENTER_ENABLED"] = "true"
    def teardown_method(self): os.environ.pop("SECURITY_CENTER_ENABLED", None)

    def test_snapshot_keys(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from security_center.shared_services import get_security_snapshot
            r = get_security_snapshot()
        for k in ("available", "advisory_only", "read_only", "security_score",
                  "grade", "risk_level", "missing_secrets", "generated_at"):
            assert k in r

    def test_snapshot_available(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from security_center.shared_services import get_security_snapshot
            r = get_security_snapshot()
        assert r["available"] is True

    def test_snapshot_advisory_only(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from security_center.shared_services import get_security_snapshot
            r = get_security_snapshot()
        assert r["advisory_only"] is True
        assert r["read_only"] is True


# ── API commands ───────────────────────────────────────────────────────────────

class TestApiCommands:
    def setup_method(self): os.environ["SECURITY_CENTER_ENABLED"] = "true"
    def teardown_method(self): os.environ.pop("SECURITY_CENTER_ENABLED", None)

    def test_all_commands_return_dicts(self):
        audit_loaders = {"_load_scan_runs": lambda limit=20: [],
                         "_load_notifications": lambda limit=30: []}
        with patch.multiple(MOD, **{**_ALL_LOADERS, **audit_loaders}):
            from security_center.api import (
                cmd_summary, cmd_auth, cmd_sessions, cmd_secrets,
                cmd_config, cmd_api, cmd_dependencies, cmd_audit,
                cmd_compliance, cmd_alerts, cmd_snapshot,
                cmd_export_json, cmd_export_csv,
            )
            for fn in [cmd_summary, cmd_auth, cmd_sessions, cmd_secrets,
                       cmd_config, cmd_api, cmd_dependencies, cmd_audit,
                       cmd_compliance, cmd_alerts, cmd_snapshot,
                       cmd_export_json, cmd_export_csv]:
                r = fn()
                assert isinstance(r, dict), f"{fn.__name__} should return dict"

    def test_cmd_snapshot_available(self):
        with patch.multiple(MOD, **_ALL_LOADERS):
            from security_center.api import cmd_snapshot
            r = cmd_snapshot()
        assert r["available"] is True


# ── Grade / risk helpers ───────────────────────────────────────────────────────

class TestGradeHelpers:
    def test_grade_a_plus(self):
        from security_center.models import sec_grade
        assert sec_grade(95) == "A+"

    def test_grade_a(self):
        from security_center.models import sec_grade
        assert sec_grade(85) == "A"

    def test_grade_b(self):
        from security_center.models import sec_grade
        assert sec_grade(70) == "B"

    def test_grade_c(self):
        from security_center.models import sec_grade
        assert sec_grade(55) == "C"

    def test_grade_d(self):
        from security_center.models import sec_grade
        assert sec_grade(40) == "D"

    def test_risk_low(self):
        from security_center.models import risk_level
        assert risk_level(85) == "LOW"

    def test_risk_medium(self):
        from security_center.models import risk_level
        assert risk_level(65) == "MEDIUM"

    def test_risk_high(self):
        from security_center.models import risk_level
        assert risk_level(45) == "HIGH"

    def test_risk_critical(self):
        from security_center.models import risk_level
        assert risk_level(30) == "CRITICAL"

    def test_required_secrets_structure(self):
        from security_center.models import REQUIRED_SECRETS
        assert len(REQUIRED_SECRETS) >= 3
        for s in REQUIRED_SECRETS:
            assert "name" in s and "category" in s and "critical" in s

    def test_required_config_structure(self):
        from security_center.models import REQUIRED_CONFIG
        assert len(REQUIRED_CONFIG) >= 4
        for c in REQUIRED_CONFIG:
            assert "name" in c and "description" in c
