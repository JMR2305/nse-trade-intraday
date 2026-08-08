"""Phase 23.9 — export engine + final acceptance report tests.

Unit-level: export formats are exercised with injected data so no
database, ledger or live store is touched.
"""
import base64
import json
import unittest

import phase239_reports as p239


CERT = {
    "ok": True,
    "cert_id": "CERT-abc123",
    "created_at": "2026-08-08T10:00:00.000Z",
    "certification_pct": 62.5,
    "verdict": "NOT_READY",
    "blockers": ["data: WARN"],
    "domains": {
        "data": {"verdict": "WARN", "weight": 0.15, "score_pct": 50.0,
                 "checks_total": 4, "checks_failed": 0, "checks_warned": 1},
        "portfolio": {"verdict": "PASS", "weight": 0.20, "score_pct": 100.0,
                      "checks_total": 5, "checks_failed": 0,
                      "checks_warned": 0},
    },
}

LOGS = {"ok": True, "items": [
    {"cert_id": "CERT-abc123", "created_at": "2026-08-08T10:00:00.000Z",
     "certification_pct": 62.5, "verdict": "NOT_READY",
     "domains": {"data": "WARN", "portfolio": "PASS"}},
]}

SIMS = {"ok": True, "runs": [
    {"sim_id": "SIM-1", "created_at": "2026-08-01", "label": "base",
     "base_run_id": "RUN-1",
     "result": {"verdict": "PASS", "pnl": 120.5, "trades_kept": 8,
                "metrics": {"trades": 8, "win_rate": 62.5,
                            "max_drawdown_pct": 3.1}}},
]}

COMPARE = {"ok": True, "rows": [
    {"sim_id": "SIM-1", "ok": True, "label": "base", "trades": 8,
     "win_rate": 62.5, "pnl": 120.5, "sharpe": 1.1, "sortino": 1.4,
     "max_drawdown_pct": 3.1, "profit_factor": 1.8, "expectancy": 0.9,
     "verdict": "PASS"},
    {"sim_id": "SIM-404", "ok": False, "error": "not found"},
]}


class TestExportFormats(unittest.TestCase):
    def test_unknown_report_and_format_rejected(self):
        self.assertFalse(p239.export_report("nope", "json")["ok"])
        self.assertFalse(p239.export_report("certification", "docx")["ok"])

    def test_json_export(self):
        r = p239.export_report("certification", "json", data=CERT)
        self.assertTrue(r["ok"])
        self.assertEqual(r["content_type"], "application/json")
        self.assertTrue(r["filename"].endswith(".json"))
        parsed = json.loads(r["content"])
        self.assertEqual(parsed["cert_id"], "CERT-abc123")

    def test_csv_export(self):
        r = p239.export_report("certification", "csv", data=CERT)
        self.assertTrue(r["ok"])
        self.assertEqual(r["content_type"], "text/csv")
        self.assertIn("domain,verdict,weight", r["content"])
        self.assertIn("portfolio,PASS", r["content"])
        self.assertIn("PAPER TRADING / RESEARCH ONLY", r["content"])

    def test_markdown_export(self):
        r = p239.export_report("certification", "md", data=CERT)
        self.assertTrue(r["ok"])
        self.assertEqual(r["content_type"], "text/markdown")
        self.assertIn("**Verdict: NOT_READY**", r["content"])
        self.assertIn("| domain | verdict |", r["content"])
        self.assertIn("- data: WARN", r["content"])

    def test_pdf_export(self):
        r = p239.export_report("certification", "pdf", data=CERT)
        self.assertTrue(r["ok"])
        self.assertEqual(r["content_type"], "application/pdf")
        raw = base64.b64decode(r["content_b64"])
        self.assertTrue(raw.startswith(b"%PDF"))

    def test_validation_logs_csv(self):
        r = p239.export_report("validation_logs", "csv", data=LOGS)
        self.assertTrue(r["ok"])
        self.assertIn("CERT-abc123", r["content"])
        self.assertIn("data", r["content"])  # domain column

    def test_simulation_exports_all_formats(self):
        for fmt in ("json", "csv", "md", "pdf"):
            r = p239.export_report("simulation", fmt, data=SIMS)
            self.assertTrue(r["ok"], f"simulation {fmt} failed: {r}")

    def test_comparison_includes_error_rows(self):
        r = p239.export_report("comparison", "csv", data=COMPARE)
        self.assertTrue(r["ok"])
        self.assertIn("ERROR: not found", r["content"])
        self.assertIn("SIM-1", r["content"])

    def test_error_payload_propagates(self):
        r = p239.export_report("certification", "json",
                               data={"ok": False, "error": "No runs yet"})
        self.assertFalse(r["ok"])
        self.assertIn("No runs yet", r["error"])


class TestAcceptanceReport(unittest.TestCase):
    def test_real_static_audit_passes(self):
        """The actual codebase must pass the canonical-architecture audit."""
        rep = p239.acceptance_report(runtime=[])  # static-only, no DB
        systems = {s["system"]: s for s in rep["systems"]}
        for name in ("Simulation Lab", "Validation Engine",
                     "Certification Engine", "Mission Control", "Replay",
                     "Backtest", "Learning Engine", "Optimization Lab"):
            self.assertIn(name, systems)
            self.assertEqual(systems[name]["verdict"], "PASS",
                             f"{name} failed: {systems[name]['checks']}")
        self.assertEqual(rep["verdict"], "ACCEPTED")
        self.assertTrue(rep["accepted"])

    def test_failed_check_blocks_acceptance(self):
        bad = [{"system": "X", "module": "x.py", "verdict": "FAIL",
                "checks": [{"check": "c", "status": "FAIL", "detail": "d"}]}]
        rep = p239.acceptance_report(module_audits=bad, runtime=[])
        self.assertEqual(rep["verdict"], "NOT_ACCEPTED")
        self.assertEqual(rep["checks_failed"], 1)

    def test_warn_reduces_score_but_not_acceptance(self):
        ok = [{"system": "X", "module": "x.py", "verdict": "PASS",
               "checks": [{"check": "c", "status": "PASS", "detail": "d"}]}]
        rt = [{"check": "snap", "status": "WARN", "detail": "no snapshot"}]
        rep = p239.acceptance_report(module_audits=ok, runtime=rt)
        self.assertEqual(rep["verdict"], "ACCEPTED")
        self.assertLess(rep["score_pct"], 100.0)

    def test_acceptance_exportable(self):
        rep = p239.acceptance_report(
            module_audits=[{"system": "X", "module": "x.py",
                            "verdict": "PASS",
                            "checks": [{"check": "c", "status": "PASS",
                                        "detail": "d"}]}],
            runtime=[])
        for fmt in ("json", "csv", "md", "pdf"):
            r = p239.export_report("acceptance", fmt, data=rep)
            self.assertTrue(r["ok"], f"acceptance {fmt} failed: {r}")


if __name__ == "__main__":
    unittest.main()
