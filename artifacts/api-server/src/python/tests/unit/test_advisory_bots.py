"""Safety-first unit tests for the Phase 2B advisory multi-bot layer."""

from __future__ import annotations

import ast
from datetime import datetime, timezone
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import phase24_store
from advisory_bots.audit_bot import persist_advisory_run
from advisory_bots.contracts import ADVISORY_DECISIONS, PROHIBITED_OUTPUT_KEYS
from advisory_bots.data_quality_bot import check_symbol_quality
from advisory_bots.decision_bot import combine_scores
from advisory_bots.orchestrator import run_advisory_analysis
from advisory_bots.regime_bot import classify_regime
from advisory_bots.risk_gate_bot import AdvisoryRiskLimits, evaluate_risk
from advisory_bots.strategies import evaluate_strategies
from advisory_bots.supervisor_bot import supervise
from advisory_bots.universe_bot import CUSTOM_UNIVERSE, validate_universe


def _settings(**overrides):
    base = {
        "initial_capital": 100000,
        "active_intraday_universe": CUSTOM_UNIVERSE,
        "auto_paper_entries": False,
        "bootstrap_paper_enabled": False,
        "auto_paper_exits": True,
    }
    base.update(overrides)
    return base


def _active_rows():
    symbols = [
        "BANKBARODA", "BANKINDIA", "CANBK", "FEDERALBNK", "IDFCFIRSTB",
        "KTKBANK", "MAHABANK", "PNB", "UNIONBANK", "COALINDIA", "GAIL",
        "HUDCO", "IRCON", "IRFC", "MRPL", "NBCC", "NMDC", "NTPC", "PFC",
        "RECLTD", "RVNL", "SAIL", "WIPRO",
    ]
    return [
        {
            "symbol": symbol,
            "is_active": True,
            "allowed_universe": CUSTOM_UNIVERSE,
            "ohlcv_available": True,
        }
        for symbol in symbols
    ] + [
        {"symbol": "IOB", "is_active": False, "allowed_universe": CUSTOM_UNIVERSE},
        {"symbol": "UCOBANK", "is_active": False, "allowed_universe": CUSTOM_UNIVERSE},
    ]


def _market_data(**overrides):
    base = {
        "current_price": 100.0,
        "close": 100.0,
        "vwap": 99.5,
        "volume": 1_000_000,
        "volume_ratio": 1.5,
        "ema_fast": 99.0,
        "ema_slow": 97.0,
        "pullback_confirmed": True,
        "orb_high": 99.5,
        "orb_low": 97.5,
        "opening_range_complete": True,
        "data_quality": "LIVE",
        "snapshot_ts": datetime.now(timezone.utc).isoformat(),
    }
    base.update(overrides)
    return base


class TestAdvisoryContractsAndIsolation(TestCase):
    def test_all_outputs_are_advisory_and_paper_only(self):
        health = validate_universe(_active_rows(), scan_id="scan-1")
        self.assertTrue(health["advisory_only"])
        self.assertTrue(health["paper_only"])
        self.assertIn(health["decision"], ADVISORY_DECISIONS)
        self.assertIsNotNone(health["timestamp"])

    def test_source_contains_no_execution_or_broker_imports(self):
        package = Path(__file__).parents[2] / "advisory_bots"
        forbidden_modules = {
            "phase20_executor", "phase20_scheduler", "phase20_exits",
            "paper_trader", "broker_client", "execution_agent",
        }
        forbidden_calls = {
            "execute_buy", "execute_sell", "place_order", "modify_order",
            "cancel_order", "run_auto_entries", "manage_open_positions",
            "update_settings",
        }
        imported = set()
        called = set()
        for path in package.glob("*.py"):
            tree = ast.parse(path.read_text(), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])
                elif isinstance(node, ast.Call):
                    if isinstance(node.func, ast.Name):
                        called.add(node.func.id)
                    elif isinstance(node.func, ast.Attribute):
                        called.add(node.func.attr)
        self.assertFalse(imported & forbidden_modules)
        self.assertFalse(called & forbidden_calls)

    def test_supervisor_blocks_executable_terms_and_order_fields(self):
        unsafe = {
            "advisory_only": True,
            "paper_only": True,
            "decision": "WATCH",
            "action": "EXECUTE",
        }
        result = supervise([unsafe], _settings(), universe_health=validate_universe(_active_rows()))
        self.assertEqual(result["decision"], "SUPERVISOR_BLOCKED")
        self.assertIn("prohibited output keys", result["reason"])

        unsafe_field = {
            "advisory_only": True,
            "paper_only": True,
            "decision": "WATCH",
            "order_payload": {"any": "value"},
        }
        result = supervise([unsafe_field], _settings(), universe_health=validate_universe(_active_rows()))
        self.assertEqual(result["decision"], "SUPERVISOR_BLOCKED")
        self.assertTrue(PROHIBITED_OUTPUT_KEYS)

    def test_supervisor_cannot_enable_auto_entries(self):
        result = supervise([], _settings(auto_paper_entries=True), universe_health=validate_universe(_active_rows()))
        self.assertEqual(result["decision"], "SUPERVISOR_BLOCKED")
        self.assertIn("auto_paper_entries is not false", result["reason"])


class TestUniverseAndQuality(TestCase):
    def test_reads_only_exact_custom_universe(self):
        health = validate_universe(_active_rows(), scan_id="scan-1")
        self.assertTrue(health["healthy"])
        self.assertEqual(health["active_count"], 23)
        self.assertEqual(health["active_universe"], CUSTOM_UNIVERSE)
        self.assertIn("IOB", health["inactive_symbols"])
        self.assertIn("UCOBANK", health["inactive_symbols"])

    def test_empty_or_legacy_universe_blocks_without_nifty_fallback(self):
        empty = validate_universe([])
        self.assertEqual(empty["decision"], "SUPERVISOR_BLOCKED")
        self.assertEqual(empty["active_count"], 0)
        self.assertFalse(empty["nifty_fallback_detected"])

        legacy_rows = _active_rows()
        legacy_rows[0]["allowed_universe"] = "NIFTY_50"
        blocked = validate_universe(legacy_rows)
        self.assertEqual(blocked["decision"], "SUPERVISOR_BLOCKED")
        self.assertIn("active_rows_not_custom_universe", blocked["reason"])

        missing_label_rows = _active_rows()
        missing_label_rows[0]["allowed_universe"] = None
        missing_label = validate_universe(missing_label_rows)
        self.assertEqual(missing_label["decision"], "SUPERVISOR_BLOCKED")
        self.assertIn("active_rows_not_custom_universe", missing_label["reason"])

    def test_bad_data_blocks_scoring(self):
        quality = check_symbol_quality(
            "WIPRO",
            _market_data(volume=None),
            master_row={"ohlcv_available": True},
        )
        self.assertEqual(quality["decision"], "BLOCKED_DATA_QUALITY")
        self.assertEqual(quality["score"], 0)

        final = combine_scores(
            "WIPRO",
            [],
            {"decision": "CANDIDATE", "risk_flags": []},
            quality,
            classify_regime({"trend_strength": 0.8}),
        )
        self.assertEqual(final["decision"], "BLOCKED_DATA_QUALITY")
        self.assertEqual(final["score"], 0)

        malformed = check_symbol_quality(
            "WIPRO",
            _market_data(data_quality="GARBAGE", current_price="not-a-number"),
            master_row={"ohlcv_available": True},
        )
        self.assertEqual(malformed["decision"], "BLOCKED_DATA_QUALITY")
        self.assertEqual(malformed["score"], 0)


class TestStrategiesAndRisk(TestCase):
    def test_strategies_return_scores_only(self):
        outputs = evaluate_strategies(
            "WIPRO",
            _market_data(),
            {"regime": "TRENDING"},
        )
        self.assertEqual(len(outputs), 3)
        for output in outputs:
            self.assertIn(output["decision"], ADVISORY_DECISIONS)
            self.assertTrue(output["advisory_only"])
            self.assertTrue(output["paper_only"])
            self.assertGreaterEqual(output["score"], 0)
            self.assertLessEqual(output["score"], 100)
            self.assertFalse(set(output) & PROHIBITED_OUTPUT_KEYS)

    def test_missing_intraday_evidence_never_infers_setup(self):
        outputs = evaluate_strategies("WIPRO", {"current_price": 100.0}, {"regime": "TRENDING"})
        self.assertTrue(all(output["score"] == 0 for output in outputs))
        self.assertTrue(
            all(output["decision"] in {"INSUFFICIENT_CONTEXT", "WATCH"} for output in outputs)
        )

    def test_risk_gate_uses_one_lakh_limits_and_only_advisory_verdict(self):
        allowed = evaluate_risk(
            "WIPRO",
            {"score": 80, "notional_value": 25_000, "risk_amount": 1_000, "daily_loss_to_date": 3_000},
            _settings(),
        )
        self.assertEqual(allowed["decision"], "CANDIDATE")
        self.assertEqual(allowed["capital_basis"], 100_000)
        self.assertEqual(allowed["per_stock_cap"], 25_000)
        self.assertEqual(allowed["risk_per_idea"], 1_000)
        self.assertEqual(allowed["daily_loss_limit"], 3_000)
        self.assertEqual(allowed["risk_verdict"], "ALLOWED_ADVISORY")
        self.assertFalse(set(allowed) & PROHIBITED_OUTPUT_KEYS)

        rejected = evaluate_risk(
            "WIPRO",
            {"score": 80, "notional_value": 25_001, "risk_amount": 1_001, "daily_loss_to_date": 3_001},
            _settings(),
        )
        self.assertEqual(rejected["decision"], "REJECTED")
        self.assertIn("PER_STOCK_CAP_EXCEEDED", rejected["risk_flags"])
        self.assertIn("RISK_PER_IDEA_EXCEEDED", rejected["risk_flags"])
        self.assertIn("DAILY_LOSS_LIMIT_EXCEEDED", rejected["risk_flags"])

    def test_risk_gate_rejects_config_mismatch(self):
        rejected = evaluate_risk("WIPRO", {"score": 80}, _settings(initial_capital=50_000))
        self.assertEqual(rejected["decision"], "REJECTED")
        self.assertIn("CONFIG_MISMATCH", rejected["reason"])
        self.assertEqual(AdvisoryRiskLimits().capital, 100_000)

    def test_risk_gate_rejects_missing_risk_evidence(self):
        rejected = evaluate_risk("WIPRO", {"score": 80}, _settings())
        self.assertEqual(rejected["decision"], "REJECTED")
        self.assertIn("RISK_EVIDENCE_MISSING", rejected["risk_flags"])


class TestAuditIsolation(TestCase):
    def _scan_items(self):
        return [
            {"symbol": row["symbol"], **_market_data()}
            for row in _active_rows()
            if row["is_active"]
        ]

    def test_manual_orchestrator_does_not_persist_by_default(self):
        run = run_advisory_analysis(
            scan_id="scan-manual",
            universe_rows=_active_rows(),
            scan_items=self._scan_items(),
            settings=_settings(),
            market_context={"trend_strength": 0.8},
        )
        self.assertTrue(run["manual_invocation_only"])
        self.assertFalse(run["scheduler_integration"])
        self.assertNotIn("audit", run)
        self.assertEqual(run["supervisor"]["supervisor_verdict"], "APPROVED_FOR_ADVISORY_RECORD")

    def test_audit_writer_targets_only_advisory_tables(self):
        run = run_advisory_analysis(
            scan_id="scan-audit",
            universe_rows=_active_rows(),
            scan_items=self._scan_items(),
            settings=_settings(),
            market_context={"trend_strength": 0.8},
        )
        calls = []

        def writer(table, record):
            calls.append((table, record["symbol"]))
            return True

        audit = persist_advisory_run(run, settings=_settings(), writer=writer)
        self.assertTrue(audit["persisted"])
        self.assertTrue(calls)
        self.assertTrue(all(table in phase24_store.ADVISORY_TABLES for table, _ in calls))
        self.assertNotIn("phase20_paper_trades", {table for table, _ in calls})

    def test_forged_approved_run_cannot_write_a_partial_or_executable_record(self):
        run = run_advisory_analysis(
            scan_id="scan-forged",
            universe_rows=_active_rows(),
            scan_items=self._scan_items(),
            settings=_settings(),
            market_context={"trend_strength": 0.8},
        )
        run["decisions"][0]["action"] = "EXECUTE"
        calls = []

        def writer(table, record):
            calls.append((table, record))
            return True

        result = persist_advisory_run(run, settings=_settings(), writer=writer)
        self.assertFalse(result["persisted"])
        self.assertEqual(calls, [])

    def test_forged_contract_valid_supervisor_cannot_override_blocked_universe(self):
        run = run_advisory_analysis(
            scan_id="scan-forged-universe",
            universe_rows=_active_rows(),
            scan_items=self._scan_items(),
            settings=_settings(),
            market_context={"trend_strength": 0.8},
        )
        run["universe_health"]["healthy"] = False
        run["universe_health"]["active_count"] = 22
        run["universe_health"]["nifty_fallback_detected"] = True
        run["supervisor"] = {
            "advisory_only": True,
            "paper_only": True,
            "decision": "WATCH",
            "supervisor_verdict": "APPROVED_FOR_ADVISORY_RECORD",
            "output_count": len(
                [run["universe_health"], run["regime"], *run["quality_outputs"],
                 *run["strategy_outputs"], *run["risk_outputs"], *run["decisions"]]
            ),
            "violations": [],
        }
        calls = []

        result = persist_advisory_run(
            run,
            settings=_settings(),
            writer=lambda table, record: calls.append((table, record)) or True,
        )
        self.assertFalse(result["persisted"])
        self.assertEqual(calls, [])
        self.assertEqual(result["supervisor"]["decision"], "SUPERVISOR_BLOCKED")

    def test_advisory_store_is_append_only_and_allow_list_enforced(self):
        health = validate_universe(_active_rows(), scan_id="scan-store")
        with self.subTest("allow-list"):
            with self.assertRaises(ValueError):
                phase24_store.insert_advisory_record("phase20_paper_trades", health)

        from tempfile import TemporaryDirectory

        with TemporaryDirectory() as tmp:
            files = {
                table: str(Path(tmp) / f"{table}.json")
                for table in phase24_store.ADVISORY_TABLES
            }
            with patch.object(phase24_store, "db_available", return_value=False), patch.object(
                phase24_store, "_ADVISORY_FILES", files
            ):
                self.assertTrue(phase24_store.insert_advisory_record("advisory_universe_health", health))
                changed = dict(health)
                changed["reason"] = "attempted overwrite"
                self.assertFalse(phase24_store.insert_advisory_record("advisory_universe_health", changed))
                rows = phase24_store.list_advisory_records("advisory_universe_health")

        self.assertEqual(len(rows), 1)
        self.assertNotEqual(rows[0]["reason"], "attempted overwrite")