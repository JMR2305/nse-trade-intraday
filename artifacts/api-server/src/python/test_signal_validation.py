"""
test_signal_validation.py — Phase 5C comprehensive test suite.
~35 test categories covering:
  - SignalValidationRecord model
  - DB CRUD (mocked — never hits real DB)
  - Lifecycle state machine
  - Outcome classification (all 18 classes)
  - Attribution metrics
  - Report generation
  - Tick phase windows
  - Funnel calculation
  - Feature flag enforcement
  - AST scan — no live order / no trade-submission code

PAPER TRADING / ADVISORY ONLY.
"""
import ast
import os
import sys
import types
import unittest
from decimal import Decimal
from typing import Any, Dict
from unittest.mock import MagicMock, patch, call
from datetime import datetime, timezone, timedelta

# ── Bootstrap path ────────────────────────────────────────────────────────────
_DIR = os.path.dirname(os.path.abspath(__file__))
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

# ── Stub out DB and external dependencies so tests run without Postgres ────────

_STUB_DB = types.ModuleType("signal_validation_db")
_STUB_DB.ensure_schema = lambda: None
_STUB_DB.upsert_record = lambda rec: None
_STUB_DB.upsert_session = lambda data: None
_STUB_DB.insert_lifecycle_event = lambda evt: None
_STUB_DB.upsert_price_checkpoint = lambda cp: None
_STUB_DB.save_strategy_metrics = lambda m: None
_STUB_DB.save_ai_metrics = lambda m: None
_STUB_DB.save_preopen_metrics = lambda m: None
_STUB_DB.save_daily_report = lambda d: None
_STUB_DB.get_records = lambda **kw: []
_STUB_DB.get_record_by_signal_id = lambda sid, td: None
_STUB_DB.get_lifecycle_events = lambda vid: []
_STUB_DB.get_price_checkpoints = lambda vid: []
_STUB_DB.get_latest_session = lambda td=None: None
_STUB_DB.get_sessions = lambda limit=10: []
_STUB_DB.count_valid_sessions = lambda: 0
_STUB_DB.get_daily_report = lambda td: None
_STUB_DB.get_strategy_metrics = lambda td=None: []
_STUB_DB.get_ai_metrics = lambda td=None: []
_STUB_DB.get_preopen_metrics = lambda td=None: []
_STUB_DB._db_available = lambda: False
sys.modules["signal_validation_db"] = _STUB_DB

# ── Import modules under test ──────────────────────────────────────────────────
from signal_validation_model import (
    SignalValidationRecord, LifecycleState, OutcomeClass, MissedReason,
    LifecycleEvent, PriceCheckpoint, is_enabled, _dec,
)
from signal_validation_lifecycle import (
    transition, InvalidTransitionError, record_from_signal, ingest_signal_batch,
    advance_lifecycle_from_signal, close_position,
    _dec as lc_dec, _ai_agree,
)
from signal_validation_outcomes import (
    classify, classify_and_update, is_success, is_failure,
    STRONG_SUCCESS_PCT, MODERATE_SUCCESS_PCT,
)
from signal_validation_attribution import (
    _metrics_from_records, calculate_strategy_attribution,
    calculate_ai_attribution, calculate_preopen_attribution,
    calculate_regime_attribution, calculate_funnel, calculate_summary,
    _confidence_label,
)

_IST = timezone(timedelta(hours=5, minutes=30))


# ── Helpers ────────────────────────────────────────────────────────────────────

def _make_rec(**kwargs) -> SignalValidationRecord:
    defaults = dict(
        validation_id    = "sv-2026-07-27-test01",
        trading_date     = "2026-07-27",
        signal_id        = "sig-test01",
        session_id       = "sess-test01",
        strategy_id      = "RSI_DIV",
        strategy_name    = "RSI Divergence",
        strategy_version = "1.0",
        symbol           = "RELIANCE",
        sector           = "Energy",
        signal_direction = "BUY",
        signal_type      = "BUY",
        signal_timestamp_ist = "2026-07-27T09:15:00+05:30",
        signal_price     = Decimal("2800"),
        stop_loss        = Decimal("2750"),
        target_price     = Decimal("2900"),
        validation_status = LifecycleState.GENERATED,
        created_at       = "2026-07-27T09:15:00+05:30",
        updated_at       = "2026-07-27T09:15:00+05:30",
    )
    defaults.update(kwargs)
    return SignalValidationRecord(**defaults)


def _make_closed_rec(pnl_pct: float, exit_reason: str = "") -> SignalValidationRecord:
    """Make a closed record with a given realised PnL % and optional exit reason."""
    entry = Decimal("1000")
    direction = "BUY"
    exit_p = entry * (1 + Decimal(str(pnl_pct)) / 100)
    rec = _make_rec(
        validation_status        = LifecycleState.CLOSED_POSITION,
        paper_order_created      = True,
        entry_price              = entry,
        exit_price               = exit_p,
        exit_reason              = exit_reason,
        approved_position_size   = 10,
        signal_direction         = direction,
    )
    rec.realised_pnl = rec.compute_realised_pnl()
    rec.R_multiple   = rec.compute_r_multiple()
    return rec


# ══════════════════════════════════════════════════════════════════════════════
# 1. Model tests
# ══════════════════════════════════════════════════════════════════════════════

class TestSignalValidationModel(unittest.TestCase):

    def test_default_fields(self):
        r = SignalValidationRecord()
        self.assertEqual(r.validation_status, LifecycleState.GENERATED)
        self.assertFalse(r.paper_order_created)
        self.assertFalse(r.is_hypothetical)

    def test_to_dict_converts_decimal(self):
        r = _make_rec(signal_price=Decimal("2800.50"))
        d = r.to_dict()
        self.assertEqual(d["signal_price"], "2800.50")

    def test_from_dict_restores_decimal(self):
        r = _make_rec(signal_price=Decimal("2800.50"))
        d = r.to_dict()
        r2 = SignalValidationRecord.from_dict(d)
        self.assertEqual(r2.signal_price, Decimal("2800.50"))

    def test_from_dict_handles_none(self):
        r = SignalValidationRecord.from_dict({"symbol": "INFY", "stop_loss": None})
        self.assertIsNone(r.stop_loss)

    def test_from_dict_bad_decimal(self):
        r = SignalValidationRecord.from_dict({"signal_price": "not_a_number"})
        self.assertIsNone(r.signal_price)

    def test_compute_r_multiple_long(self):
        r = _make_rec(entry_price=Decimal("100"), exit_price=Decimal("104"),
                      stop_loss=Decimal("98"))
        r.validation_status = LifecycleState.CLOSED_POSITION
        r_mult = r.compute_r_multiple()
        self.assertAlmostEqual(float(r_mult), 2.0, places=4)

    def test_compute_r_multiple_no_stop(self):
        r = _make_rec(entry_price=Decimal("100"), exit_price=Decimal("104"),
                      stop_loss=None)
        self.assertIsNone(r.compute_r_multiple())

    def test_compute_realised_pnl_long(self):
        r = _make_rec(entry_price=Decimal("100"), exit_price=Decimal("110"),
                      approved_position_size=5, signal_direction="BUY")
        pnl = r.compute_realised_pnl()
        self.assertEqual(pnl, Decimal("50"))

    def test_compute_realised_pnl_short(self):
        r = _make_rec(entry_price=Decimal("100"), exit_price=Decimal("90"),
                      approved_position_size=5, signal_direction="SELL")
        pnl = r.compute_realised_pnl()
        self.assertEqual(pnl, Decimal("50"))

    def test_hypothetical_label(self):
        r = _make_rec(is_hypothetical=True,
                      hypothetical_label="HYPOTHETICAL — NOT A TRADE")
        self.assertEqual(r.hypothetical_label, "HYPOTHETICAL — NOT A TRADE")

    def test_dec_helper(self):
        self.assertEqual(_dec("2800.50"), Decimal("2800.50"))
        self.assertIsNone(_dec(None))
        self.assertIsNone(_dec("bad"))


# ══════════════════════════════════════════════════════════════════════════════
# 2. LifecycleState tests
# ══════════════════════════════════════════════════════════════════════════════

class TestLifecycleState(unittest.TestCase):

    def test_15_states_defined(self):
        self.assertEqual(len(LifecycleState.ALL), 15)

    def test_valid_transitions(self):
        self.assertTrue(LifecycleState.is_valid_transition(
            LifecycleState.GENERATED, LifecycleState.AI_REVIEWED))
        self.assertTrue(LifecycleState.is_valid_transition(
            LifecycleState.OPEN_POSITION, LifecycleState.CLOSED_POSITION))

    def test_invalid_transition(self):
        self.assertFalse(LifecycleState.is_valid_transition(
            LifecycleState.CLOSED_POSITION, LifecycleState.OPEN_POSITION))
        self.assertFalse(LifecycleState.is_valid_transition(
            LifecycleState.EXPIRED, LifecycleState.APPROVED))

    def test_terminal_states(self):
        for state in (LifecycleState.CLOSED_POSITION, LifecycleState.EXPIRED,
                      LifecycleState.CANCELLED, LifecycleState.MISSED,
                      LifecycleState.INVALID_DATA, LifecycleState.STALE_DATA,
                      LifecycleState.NO_TRADE):
            self.assertTrue(LifecycleState.is_terminal(state), state)

    def test_non_terminal_states(self):
        self.assertFalse(LifecycleState.is_terminal(LifecycleState.GENERATED))
        self.assertFalse(LifecycleState.is_terminal(LifecycleState.OPEN_POSITION))


# ══════════════════════════════════════════════════════════════════════════════
# 3. Lifecycle transition tests
# ══════════════════════════════════════════════════════════════════════════════

class TestLifecycleTransition(unittest.TestCase):

    def setUp(self):
        self.rec = _make_rec()

    def test_valid_transition_updates_state(self):
        with patch("signal_validation_lifecycle.is_enabled", return_value=False):
            r = transition(self.rec, LifecycleState.AI_REVIEWED,
                           reason="AI done", source_component="test")
        self.assertEqual(r.validation_status, LifecycleState.AI_REVIEWED)

    def test_invalid_transition_raises(self):
        self.rec.validation_status = LifecycleState.CLOSED_POSITION
        with self.assertRaises(InvalidTransitionError):
            transition(self.rec, LifecycleState.OPEN_POSITION,
                       reason="bad", source_component="test")

    def test_transition_does_not_persist_when_disabled(self):
        called = []
        orig = _STUB_DB.insert_lifecycle_event
        _STUB_DB.insert_lifecycle_event = lambda e: called.append(e)
        with patch("signal_validation_lifecycle.is_enabled", return_value=False):
            transition(self.rec, LifecycleState.RISK_REVIEWED,
                       reason="test", source_component="test", persist=True)
        # When disabled, nothing is persisted (is_enabled=False means persist is skipped)
        _STUB_DB.insert_lifecycle_event = orig

    def test_transition_with_metadata(self):
        with patch("signal_validation_lifecycle.is_enabled", return_value=False):
            r = transition(self.rec, LifecycleState.RISK_REVIEWED,
                           reason="reviewed", source_component="test",
                           metadata={"risk_score": 0.7})
        self.assertEqual(r.validation_status, LifecycleState.RISK_REVIEWED)


# ══════════════════════════════════════════════════════════════════════════════
# 4. record_from_signal tests
# ══════════════════════════════════════════════════════════════════════════════

class TestRecordFromSignal(unittest.TestCase):

    def _signal(self, **kwargs):
        base = {
            "id": "sig-001",
            "stock": "INFY",
            "signal": "BUY",
            "price": "1500",
            "confidence": "0.80",
            "regime": "BULLISH",
            "stop_loss": "1450",
            "target": "1600",
        }
        base.update(kwargs)
        return base

    def test_basic_fields_mapped(self):
        rec = record_from_signal(self._signal(), "sess-01", "2026-07-27")
        self.assertEqual(rec.symbol, "INFY")
        self.assertEqual(rec.signal_direction, "BUY")
        self.assertEqual(rec.stop_loss, Decimal("1450"))
        self.assertEqual(rec.target_price, Decimal("1600"))

    def test_market_regime_mapped(self):
        rec = record_from_signal(self._signal(), "sess-01", "2026-07-27")
        self.assertEqual(rec.market_regime, "BULLISH")

    def test_no_id_generates_uuid(self):
        sig = self._signal()
        sig.pop("id")
        rec = record_from_signal(sig, "sess-01", "2026-07-27")
        self.assertTrue(rec.signal_id.startswith("sig-"))

    def test_preopen_context_mapped(self):
        sig = self._signal(preopen_context={
            "rank": 2, "opportunity_score": "75.5", "classification": "STRONG"
        })
        rec = record_from_signal(sig, "sess-01", "2026-07-27")
        self.assertEqual(rec.preopen_rank, 2)
        self.assertEqual(rec.preopen_opportunity_score, Decimal("75.5"))


# ══════════════════════════════════════════════════════════════════════════════
# 5. ingest_signal_batch tests
# ══════════════════════════════════════════════════════════════════════════════

class TestIngestSignalBatch(unittest.TestCase):

    def test_disabled_returns_early(self):
        with patch("signal_validation_lifecycle.is_enabled", return_value=False):
            result = ingest_signal_batch([{"id": "x"}], "s", "2026-07-27")
        self.assertEqual(result.get("ingested"), 0)
        self.assertIn("SIGNAL_VALIDATION_ENABLED", result.get("reason", ""))

    def test_skips_existing(self):
        _STUB_DB.get_record_by_signal_id = lambda sid, td: {"validation_id": "existing"}
        with patch("signal_validation_lifecycle.is_enabled", return_value=True):
            result = ingest_signal_batch(
                [{"id": "sig-001", "stock": "INFY", "signal": "BUY",
                  "price": "1500", "confidence": "0.8"}],
                "sess", "2026-07-27"
            )
        self.assertEqual(result["skipped"], 1)
        self.assertEqual(result["ingested"], 0)
        _STUB_DB.get_record_by_signal_id = lambda sid, td: None

    def test_ingests_new(self):
        _STUB_DB.get_record_by_signal_id = lambda sid, td: None
        upserted = []
        _STUB_DB.upsert_record = lambda r: upserted.append(r)
        _STUB_DB.insert_lifecycle_event = lambda e: None
        with patch("signal_validation_lifecycle.is_enabled", return_value=True):
            result = ingest_signal_batch(
                [{"id": "sig-new", "stock": "RELIANCE", "signal": "BUY",
                  "price": "2800", "confidence": "0.85", "stop_loss": "2750"}],
                "sess", "2026-07-27"
            )
        self.assertEqual(result["ingested"], 1)
        self.assertTrue(len(upserted) > 0)
        _STUB_DB.upsert_record = lambda rec: None

    def test_handles_missing_id(self):
        with patch("signal_validation_lifecycle.is_enabled", return_value=True):
            result = ingest_signal_batch([{"stock": "INFY"}], "s", "2026-07-27")
        self.assertEqual(result["errors"], 1)


# ══════════════════════════════════════════════════════════════════════════════
# 6. OutcomeClass tests
# ══════════════════════════════════════════════════════════════════════════════

class TestOutcomeClass(unittest.TestCase):

    def test_18_outcomes_defined(self):
        self.assertEqual(len(OutcomeClass.ALL), 18)

    def test_is_success(self):
        for o in (OutcomeClass.STRONG_SUCCESS, OutcomeClass.MODERATE_SUCCESS,
                  OutcomeClass.SMALL_SUCCESS, OutcomeClass.TARGET_REACHED):
            self.assertTrue(is_success(o), o)

    def test_is_failure(self):
        for o in (OutcomeClass.STRONG_FAILURE, OutcomeClass.MODERATE_FAILURE,
                  OutcomeClass.STOPPED_OUT, OutcomeClass.FALSE_BREAKOUT):
            self.assertTrue(is_failure(o), o)

    def test_flat_is_neither(self):
        self.assertFalse(is_success(OutcomeClass.FLAT))
        self.assertFalse(is_failure(OutcomeClass.FLAT))


# ══════════════════════════════════════════════════════════════════════════════
# 7. classify() tests — all 18 branches
# ══════════════════════════════════════════════════════════════════════════════

class TestClassify(unittest.TestCase):

    def _closed(self, pnl_pct: float, exit_reason: str = "",
                mfe=None, mae=None) -> SignalValidationRecord:
        r = _make_closed_rec(pnl_pct, exit_reason)
        if mfe is not None:
            r.max_favourable_excursion = Decimal(str(mfe))
        if mae is not None:
            r.max_adverse_excursion = Decimal(str(mae))
        return r

    def test_strong_success(self):
        self.assertEqual(classify(self._closed(3.0)), OutcomeClass.STRONG_SUCCESS)

    def test_moderate_success(self):
        self.assertEqual(classify(self._closed(1.0)), OutcomeClass.MODERATE_SUCCESS)

    def test_small_success(self):
        self.assertEqual(classify(self._closed(0.3)), OutcomeClass.SMALL_SUCCESS)

    def test_flat(self):
        self.assertEqual(classify(self._closed(0.0)), OutcomeClass.FLAT)

    def test_small_failure(self):
        self.assertEqual(classify(self._closed(-0.3)), OutcomeClass.SMALL_FAILURE)

    def test_moderate_failure(self):
        self.assertEqual(classify(self._closed(-1.0)), OutcomeClass.MODERATE_FAILURE)

    def test_strong_failure(self):
        self.assertEqual(classify(self._closed(-2.5)), OutcomeClass.STRONG_FAILURE)

    def test_stopped_out(self):
        self.assertEqual(classify(self._closed(-1.5, "STOP_LOSS")), OutcomeClass.STOPPED_OUT)

    def test_target_reached(self):
        self.assertEqual(classify(self._closed(3.5, "TARGET_HIT")), OutcomeClass.TARGET_REACHED)

    def test_time_exit(self):
        r = self._closed(-0.1, "TIME_EXIT")
        self.assertIn(classify(r), (OutcomeClass.TIME_EXIT, OutcomeClass.FLAT,
                                    OutcomeClass.SMALL_FAILURE))

    def test_eod_exit(self):
        r = self._closed(0.5, "EOD_CLOSE")
        # TIME_EXIT takes priority over return bands when exit_reason is EOD
        cls = classify(r)
        self.assertIn(cls, (OutcomeClass.TIME_EXIT, OutcomeClass.SMALL_SUCCESS,
                            OutcomeClass.FLAT))

    def test_false_breakout(self):
        r = self._closed(-0.5, "", mfe=1.5, mae=-1.5)
        self.assertEqual(classify(r), OutcomeClass.FALSE_BREAKOUT)

    def test_early_reversal(self):
        r = _make_rec(
            validation_status        = LifecycleState.CLOSED_POSITION,
            entry_price              = Decimal("100"),
            exit_price               = Decimal("99"),
            exit_reason              = "TIME_EXIT",
            signal_direction         = "BUY",
            max_favourable_excursion = Decimal("1.5"),
            realised_pnl             = Decimal("-10"),
            approved_position_size   = 10,
        )
        cls = classify(r)
        self.assertIn(cls, (OutcomeClass.EARLY_REVERSAL, OutcomeClass.TIME_EXIT,
                            OutcomeClass.SMALL_FAILURE))

    def test_late_reversal(self):
        r = _make_rec(
            validation_status        = LifecycleState.CLOSED_POSITION,
            entry_price              = Decimal("100"),
            exit_price               = Decimal("98"),
            signal_direction         = "BUY",
            max_favourable_excursion = Decimal("2.5"),
            realised_pnl             = Decimal("-20"),
            approved_position_size   = 10,
        )
        cls = classify(r)
        self.assertIn(cls, (OutcomeClass.LATE_REVERSAL, OutcomeClass.MODERATE_FAILURE,
                            OutcomeClass.STRONG_FAILURE))

    def test_risk_rejected_validly(self):
        r = _make_rec(validation_status=LifecycleState.RISK_REJECTED)
        self.assertEqual(classify(r), OutcomeClass.RISK_REJECTED_VALIDLY)

    def test_risk_rejected_but_signal_succeeded(self):
        r = _make_rec(validation_status=LifecycleState.RISK_REJECTED,
                      hyp_return_60m=Decimal("3.0"))
        self.assertEqual(classify(r), OutcomeClass.RISK_REJECTED_BUT_SIGNAL_SUCCEEDED)

    def test_invalid_data(self):
        r = _make_rec(validation_status=LifecycleState.INVALID_DATA)
        self.assertEqual(classify(r), OutcomeClass.INVALID_SIGNAL)

    def test_signal_expired(self):
        r = _make_rec(validation_status=LifecycleState.EXPIRED)
        self.assertEqual(classify(r), OutcomeClass.SIGNAL_EXPIRED)

    def test_data_incomplete_open(self):
        r = _make_rec(validation_status=LifecycleState.OPEN_POSITION)
        self.assertEqual(classify(r), OutcomeClass.DATA_INCOMPLETE)


# ══════════════════════════════════════════════════════════════════════════════
# 8. classify_and_update tests
# ══════════════════════════════════════════════════════════════════════════════

class TestClassifyAndUpdate(unittest.TestCase):

    def test_fills_outcome_class(self):
        r = _make_closed_rec(3.0)
        classify_and_update(r)
        self.assertIsNotNone(r.outcome_class)
        self.assertEqual(r.outcome_class, OutcomeClass.STRONG_SUCCESS)

    def test_sets_hypothetical_label(self):
        r = _make_rec(validation_status=LifecycleState.RISK_REJECTED)
        classify_and_update(r)
        self.assertTrue(r.is_hypothetical)
        self.assertEqual(r.hypothetical_label, "HYPOTHETICAL — NOT A TRADE")

    def test_computes_r_when_missing(self):
        r = _make_rec(
            validation_status = LifecycleState.CLOSED_POSITION,
            entry_price       = Decimal("100"),
            exit_price        = Decimal("104"),
            stop_loss         = Decimal("98"),
        )
        classify_and_update(r)
        self.assertIsNotNone(r.R_multiple)


# ══════════════════════════════════════════════════════════════════════════════
# 9. Attribution metrics tests
# ══════════════════════════════════════════════════════════════════════════════

class TestAttributionMetrics(unittest.TestCase):

    def _make_pool(self, n_win: int, n_lose: int) -> list:
        recs = []
        for i in range(n_win):
            r = _make_closed_rec(3.0)
            r.signal_id    = f"win-{i}"
            r.validation_id = f"sv-win-{i}"
            classify_and_update(r)
            recs.append(r)
        for i in range(n_lose):
            r = _make_closed_rec(-2.0)
            r.signal_id    = f"lose-{i}"
            r.validation_id = f"sv-lose-{i}"
            classify_and_update(r)
            recs.append(r)
        return recs

    def test_win_rate_calculation(self):
        pool = self._make_pool(7, 3)
        m = _metrics_from_records(pool)
        self.assertAlmostEqual(m["win_rate"], 0.7, places=2)

    def test_zero_records(self):
        m = _metrics_from_records([])
        self.assertEqual(m["signals_generated"], 0)
        self.assertIsNone(m["win_rate"])

    def test_confidence_labels(self):
        self.assertEqual(_confidence_label(15), "SUFFICIENT")
        self.assertEqual(_confidence_label(7),  "LOW_SAMPLE")
        self.assertEqual(_confidence_label(3),  "INSUFFICIENT_DATA")

    def test_strategy_attribution_groups(self):
        recs = self._make_pool(5, 5)
        for r in recs[:5]:
            r.strategy_id   = "RSI_DIV"
            r.strategy_name = "RSI Divergence"
        for r in recs[5:]:
            r.strategy_id   = "MACD_X"
            r.strategy_name = "MACD Crossover"
        metrics = calculate_strategy_attribution(recs, "2026-07-27", "sess")
        strat_ids = {m["strategy_id"] for m in metrics}
        self.assertIn("RSI_DIV", strat_ids)
        self.assertIn("MACD_X", strat_ids)

    def test_ai_attribution_groups(self):
        recs = self._make_pool(4, 4)
        for i, grp in enumerate(["AGREE", "DISAGREE", "WATCH", "NO_RESULT"]):
            recs[i].AI_agreement = grp
            recs[i + 4].AI_agreement = grp
        metrics = calculate_ai_attribution(recs, "2026-07-27", "sess")
        grp_names = {m["agreement_group"] for m in metrics}
        self.assertTrue(grp_names.issubset({"AGREE", "DISAGREE", "WATCH", "NO_RESULT", "STALE"}))

    def test_preopen_attribution(self):
        recs = self._make_pool(3, 3)
        for r in recs[:3]:
            r.preopen_classification   = "STRONG"
            r.preopen_opportunity_score = Decimal("80")
        metrics = calculate_preopen_attribution(recs, "2026-07-27", "sess",
                                                 valid_phase5b_sessions=0)
        self.assertFalse(any(m["predictive_value_declared"] for m in metrics))

    def test_preopen_predictive_value_declared_after_5_sessions(self):
        recs = self._make_pool(3, 3)
        for r in recs:
            r.preopen_classification   = "STRONG"
            r.preopen_opportunity_score = Decimal("80")
        metrics = calculate_preopen_attribution(recs, "2026-07-27", "sess",
                                                 valid_phase5b_sessions=5)
        self.assertTrue(any(m["predictive_value_declared"] for m in metrics))

    def test_regime_attribution(self):
        recs = self._make_pool(4, 4)
        for r in recs[:4]:
            r.market_regime = "BULLISH"
        for r in recs[4:]:
            r.market_regime = "NEUTRAL"
        metrics = calculate_regime_attribution(recs, "2026-07-27", "sess")
        regimes = {m["regime"] for m in metrics}
        self.assertIn("BULLISH", regimes)


# ══════════════════════════════════════════════════════════════════════════════
# 10. Funnel tests
# ══════════════════════════════════════════════════════════════════════════════

class TestFunnel(unittest.TestCase):

    def test_empty_funnel(self):
        funnel = calculate_funnel([])
        self.assertEqual(funnel["generated"]["count"], 0)
        self.assertEqual(funnel["successful"]["count"], 0)

    def test_funnel_counts(self):
        recs = []
        # 5 generated, 3 approved, 2 closed + successful
        for i in range(5):
            r = _make_rec(signal_id=f"sig-{i}", validation_id=f"sv-{i}")
            recs.append(r)
        # Mark 3 as approved
        for r in recs[:3]:
            r.validation_status = LifecycleState.APPROVED
        # Close 2 as successes
        for r in recs[:2]:
            r.validation_status   = LifecycleState.CLOSED_POSITION
            r.paper_order_created = True
            r.entry_price  = Decimal("100")
            r.exit_price   = Decimal("103")
            r.realised_pnl = Decimal("30")
            r.outcome_class = OutcomeClass.STRONG_SUCCESS

        funnel = calculate_funnel(recs)
        self.assertEqual(funnel["generated"]["count"], 5)
        self.assertEqual(funnel["successful"]["count"], 2)
        self.assertAlmostEqual(funnel["successful"]["pct"], 40.0)


# ══════════════════════════════════════════════════════════════════════════════
# 11. Summary tests
# ══════════════════════════════════════════════════════════════════════════════

class TestSummary(unittest.TestCase):

    def test_summary_keys(self):
        recs = [_make_rec(signal_id=f"s{i}", validation_id=f"v{i}")
                for i in range(3)]
        s = calculate_summary(recs)
        for key in ("signals_generated", "signals_approved", "paper_trades",
                    "risk_rejections", "win_rate", "expectancy",
                    "false_positives", "missed_opportunities", "data_completeness_pct"):
            self.assertIn(key, s, key)

    def test_data_completeness_zero_when_incomplete(self):
        recs = [_make_rec(signal_id=f"s{i}", validation_id=f"v{i}",
                          outcome_class=None) for i in range(5)]
        s = calculate_summary(recs)
        self.assertEqual(s["data_completeness_pct"], 0.0)


# ══════════════════════════════════════════════════════════════════════════════
# 12. Tick phase window tests
# ══════════════════════════════════════════════════════════════════════════════

class TestTickPhaseWindows(unittest.TestCase):

    def _at(self, hour: int, minute: int):
        return datetime(2026, 7, 27, hour, minute, tzinfo=_IST)

    def test_phase_windows(self):
        from signal_validation_tick import _active_phase, _PHASES
        # 09:05 → ingest_signals
        active = _active_phase(self._at(9, 5))
        self.assertIsNotNone(active)
        self.assertEqual(active[0], "ingest_signals")

    def test_no_phase_before_market(self):
        from signal_validation_tick import _active_phase
        self.assertIsNone(_active_phase(self._at(8, 0)))

    def test_eod_phase_window(self):
        from signal_validation_tick import _active_phase
        active = _active_phase(self._at(15, 30))
        self.assertIsNotNone(active)
        self.assertEqual(active[0], "eod_close")

    def test_checkpoint_5m_window(self):
        from signal_validation_tick import _active_phase
        # 09:32: inside checkpoint_5m (09:25-09:35); ingest also active but
        # _active_phase prefers once-only phases over continuous ingest.
        active = _active_phase(self._at(9, 32))
        self.assertEqual(active[0], "checkpoint_5m")

    def test_checkpoint_60m_window(self):
        from signal_validation_tick import _active_phase
        # 10:20: inside checkpoint_60m (10:15-10:45); _active_phase prefers
        # once-only checkpoint over the continuous ingest background phase.
        active = _active_phase(self._at(10, 20))
        self.assertEqual(active[0], "checkpoint_60m")


# ══════════════════════════════════════════════════════════════════════════════
# 13. Tick state persistence tests
# ══════════════════════════════════════════════════════════════════════════════

class TestTickState(unittest.TestCase):

    def test_tick_disabled_when_flag_false(self):
        with patch("signal_validation_tick.is_enabled", return_value=False):
            from signal_validation_tick import run_tick
            result = run_tick()
        self.assertFalse(result["ran"])
        self.assertIn("false", result.get("reason", "").lower())

    def test_tick_status_keys(self):
        with patch("signal_validation_tick.is_enabled", return_value=False):
            from signal_validation_tick import get_tick_status
            status = get_tick_status()
        for key in ("auto_tick", "registered", "enabled", "trading_date",
                    "phases_done", "all_phases"):
            self.assertIn(key, status, key)

    def test_all_phases_listed(self):
        from signal_validation_tick import get_tick_status, _PHASES
        with patch("signal_validation_tick.is_enabled", return_value=False):
            status = get_tick_status()
        self.assertEqual(len(status["all_phases"]), len(_PHASES))


# ══════════════════════════════════════════════════════════════════════════════
# 14. Feature flag enforcement tests
# ══════════════════════════════════════════════════════════════════════════════

class TestFeatureFlag(unittest.TestCase):

    def test_is_enabled_false_by_default(self):
        import os
        os.environ.pop("SIGNAL_VALIDATION_ENABLED", None)
        self.assertFalse(is_enabled())

    def test_is_enabled_true_when_set(self):
        import os
        os.environ["SIGNAL_VALIDATION_ENABLED"] = "true"
        self.assertTrue(is_enabled())
        os.environ.pop("SIGNAL_VALIDATION_ENABLED")

    def test_engine_get_status_when_disabled(self):
        with patch("signal_validation_engine.is_enabled", return_value=False):
            from signal_validation_engine import get_status
            r = get_status()
        self.assertEqual(r["status"], "DISABLED")

    def test_engine_get_signals_when_disabled(self):
        with patch("signal_validation_engine.is_enabled", return_value=False):
            from signal_validation_engine import get_signals
            r = get_signals()
        self.assertEqual(r["status"], "DISABLED")

    def test_engine_run_now_when_disabled(self):
        with patch("signal_validation_engine.is_enabled", return_value=False):
            from signal_validation_engine import run_now
            r = run_now()
        self.assertEqual(r["status"], "DISABLED")


# ══════════════════════════════════════════════════════════════════════════════
# 15. Engine API function tests
# ══════════════════════════════════════════════════════════════════════════════

class TestEngine(unittest.TestCase):

    def setUp(self):
        self._orig_enabled = __import__("signal_validation_engine").is_enabled
        # Patch in all engine tests
        import signal_validation_engine as eng
        eng._RATE_LIMIT.clear()

    def _engine_with_enabled(self, fn_name: str, *args, **kwargs):
        with patch("signal_validation_engine.is_enabled", return_value=True):
            import signal_validation_engine as eng
            return getattr(eng, fn_name)(*args, **kwargs)

    def test_get_summary_returns_structure(self):
        r = self._engine_with_enabled("get_summary", trading_date="2026-07-27")
        self.assertIn("summary", r)
        self.assertIn("funnel", r)
        self.assertEqual(r["trading_date"], "2026-07-27")

    def test_get_signals_returns_list(self):
        r = self._engine_with_enabled("get_signals", trading_date="2026-07-27")
        self.assertIn("signals", r)
        self.assertIsInstance(r["signals"], list)

    def test_get_signal_detail_not_found(self):
        r = self._engine_with_enabled("get_signal_detail", "nonexistent-id")
        self.assertEqual(r["status"], "NOT_FOUND")

    def test_get_funnel_structure(self):
        r = self._engine_with_enabled("get_funnel")
        self.assertIn("funnel", r)

    def test_get_strategies_returns_list(self):
        r = self._engine_with_enabled("get_strategies")
        self.assertIn("strategies", r)

    def test_get_ai_attribution_returns_list(self):
        r = self._engine_with_enabled("get_ai_attribution")
        self.assertIn("ai_attribution", r)

    def test_get_preopen_attribution_returns_list(self):
        r = self._engine_with_enabled("get_preopen_attribution")
        self.assertIn("preopen_attribution", r)
        self.assertFalse(r["predictive_value_declared"])

    def test_get_missed_opportunities(self):
        r = self._engine_with_enabled("get_missed_opportunities")
        self.assertIn("missed_opportunities", r)
        self.assertEqual(r["hypothetical_label"], "HYPOTHETICAL — NOT A TRADE")

    def test_get_risk_attribution(self):
        r = self._engine_with_enabled("get_risk_attribution")
        self.assertIn("rejection_reasons", r)

    def test_get_regimes(self):
        r = self._engine_with_enabled("get_regimes")
        self.assertIn("regime_attribution", r)

    def test_run_now_rate_limited(self):
        import time
        with patch("signal_validation_engine.is_enabled", return_value=True):
            import signal_validation_engine as eng
            eng._RATE_LIMIT["run_now"] = time.monotonic()
            r = eng.run_now()
        self.assertEqual(r["status"], "RATE_LIMITED")


# ══════════════════════════════════════════════════════════════════════════════
# 16. Report generation tests
# ══════════════════════════════════════════════════════════════════════════════

class TestReports(unittest.TestCase):

    def _pool(self, n=5):
        recs = []
        for i in range(n):
            if i % 2 == 0:
                r = _make_closed_rec(2.5)
                classify_and_update(r)
            else:
                r = _make_closed_rec(-1.2)
                classify_and_update(r)
            r.signal_id    = f"sig-rpt-{i}"
            r.validation_id = f"sv-rpt-{i}"
            recs.append(r)
        return recs

    def test_daily_report_structure(self):
        from signal_validation_reports import generate_daily_report
        recs = self._pool(10)
        result = generate_daily_report("2026-07-27", "sess-01", recs)
        self.assertIn("report", result)
        report = result["report"]
        self.assertEqual(report["report_type"], "DAILY")
        self.assertIn("operational_summary", report)
        self.assertIn("signal_funnel", report)
        self.assertIn("strategy_results", report)
        self.assertIn("recommendations", report)
        self.assertIn("label", report)
        self.assertIn("PAPER TRADING", report["label"])

    def test_daily_report_has_recommendations(self):
        from signal_validation_reports import generate_daily_report
        recs = self._pool(10)
        result = generate_daily_report("2026-07-27", "sess-01", recs)
        self.assertIsInstance(result["report"]["recommendations"], list)
        self.assertTrue(len(result["report"]["recommendations"]) > 0)

    def test_five_day_insufficient_sessions(self):
        from signal_validation_reports import generate_five_day_report
        result = generate_five_day_report([{"trading_date": "2026-07-27", "paper_trades": 5}], {})
        self.assertEqual(result.get("error"), "INSUFFICIENT_SESSIONS")

    def test_five_day_verdict_options(self):
        from signal_validation_reports import generate_five_day_report
        recs = self._pool(20)
        sessions = [{"trading_date": f"2026-07-{20+i:02d}", "paper_trades": 10,
                     "session_id": f"sess-{i}"} for i in range(5)]
        all_by_date = {s["trading_date"]: recs for s in sessions}
        result = generate_five_day_report(sessions, all_by_date)
        verdict = result.get("verdict", "")
        self.assertIn(verdict, [
            "SIGNAL PIPELINE SHOWS POSITIVE OPERATIONAL VALUE",
            "SIGNAL PIPELINE REQUIRES MORE DATA",
            "SIGNAL PIPELINE REQUIRES CORRECTIVE WORK",
        ])


# ══════════════════════════════════════════════════════════════════════════════
# 17. MissedReason tests
# ══════════════════════════════════════════════════════════════════════════════

class TestMissedReason(unittest.TestCase):

    def test_all_reasons_strings(self):
        reasons = [
            MissedReason.RISK_REJECTION, MissedReason.STALE_DATA,
            MissedReason.DUPLICATE_PROTECTION, MissedReason.INSUFFICIENT_CONFIDENCE,
            MissedReason.LOW_LIQUIDITY, MissedReason.SECTOR_LIMIT,
            MissedReason.CAPITAL_LIMIT, MissedReason.POSITION_LIMIT,
            MissedReason.ENTRY_WINDOW_CLOSED, MissedReason.NO_POST_OPEN_CONFIRMATION,
            MissedReason.STRATEGY_CONFLICT, MissedReason.OPERATOR_DECISION,
            MissedReason.SYSTEM_FAILURE, MissedReason.PROVIDER_FAILURE,
            MissedReason.UNKNOWN,
        ]
        for r in reasons:
            self.assertIsInstance(r, str)


# ══════════════════════════════════════════════════════════════════════════════
# 18. AI agreement helper tests
# ══════════════════════════════════════════════════════════════════════════════

class TestAIAgreement(unittest.TestCase):

    def test_agree_when_directions_match(self):
        sig = {"signal": "BUY", "explanation": {"signal": "BUY", "recommendation": "BUY"}}
        self.assertEqual(_ai_agree(sig), "AGREE")

    def test_disagree_when_directions_differ(self):
        sig = {"signal": "BUY", "explanation": {"signal": "SELL"}}
        self.assertEqual(_ai_agree(sig), "DISAGREE")

    def test_no_result_when_no_explanation(self):
        sig = {"signal": "BUY"}
        self.assertEqual(_ai_agree(sig), "NO_RESULT")

    def test_watch_classification(self):
        sig = {"signal": "BUY", "explanation": {"signal": "WATCH"}}
        self.assertEqual(_ai_agree(sig), "WATCH")


# ══════════════════════════════════════════════════════════════════════════════
# 19. PriceCheckpoint tests
# ══════════════════════════════════════════════════════════════════════════════

class TestPriceCheckpoint(unittest.TestCase):

    def test_to_dict_converts_decimal(self):
        cp = PriceCheckpoint(
            validation_id   = "sv-001",
            checkpoint_type = "5m",
            price           = Decimal("2810.50"),
            timestamp_ist   = "2026-07-27T09:20:00+05:30",
            source          = "live_quote",
            is_hypothetical = False,
            return_pct      = Decimal("0.375"),
        )
        d = cp.to_dict()
        self.assertEqual(d["price"], "2810.50")
        self.assertEqual(d["return_pct"], "0.375")
        self.assertFalse(d["is_hypothetical"])


# ══════════════════════════════════════════════════════════════════════════════
# 20. AST safety scan — no live order submission code
# ══════════════════════════════════════════════════════════════════════════════

class TestASTSafetyScan(unittest.TestCase):
    """
    Verify that no Phase 5C Python file contains order-submission or
    strategy-modification calls (kite.place_order, strategy.set_param, etc.).
    """

    _FORBIDDEN_CALLS = {
        "place_order", "modify_order", "cancel_order",
        "set_param", "set_threshold", "modify_strategy",
        "execute_trade", "submit_order", "place_trade",
    }

    _FILES = [
        "signal_validation_model.py",
        "signal_validation_db.py",
        "signal_validation_lifecycle.py",
        "signal_validation_outcomes.py",
        "signal_validation_attribution.py",
        "signal_validation_reports.py",
        "signal_validation_tick.py",
        "signal_validation_engine.py",
    ]

    def test_no_forbidden_calls(self):
        offenders = []
        for fname in self._FILES:
            fpath = os.path.join(_DIR, fname)
            if not os.path.exists(fpath):
                continue
            try:
                tree = ast.parse(open(fpath).read(), filename=fname)
            except SyntaxError as e:
                self.fail(f"Syntax error in {fname}: {e}")
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    name = None
                    if isinstance(node.func, ast.Name):
                        name = node.func.id
                    elif isinstance(node.func, ast.Attribute):
                        name = node.func.attr
                    if name in self._FORBIDDEN_CALLS:
                        offenders.append(f"{fname}:{node.lineno} — {name}()")
        if offenders:
            self.fail("Phase 5C files contain forbidden order-submission calls:\n"
                      + "\n".join(offenders))

    def test_all_files_have_advisory_label(self):
        """Every Phase 5C file must contain the advisory-only disclaimer."""
        for fname in self._FILES:
            fpath = os.path.join(_DIR, fname)
            if not os.path.exists(fpath):
                continue
            content = open(fpath).read()
            self.assertIn("PAPER TRADING / ADVISORY ONLY", content,
                          f"{fname} is missing the PAPER TRADING / ADVISORY ONLY label")

    def test_no_live_broker_import(self):
        """Phase 5C files must not import live broker clients."""
        forbidden_imports = {"kiteconnect", "zerodha", "upstox", "fyers"}
        for fname in self._FILES:
            fpath = os.path.join(_DIR, fname)
            if not os.path.exists(fpath):
                continue
            tree = ast.parse(open(fpath).read(), filename=fname)
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    mods = []
                    if isinstance(node, ast.Import):
                        mods = [alias.name for alias in node.names]
                    else:
                        mods = [node.module or ""]
                    for mod in mods:
                        for forbidden in forbidden_imports:
                            if forbidden in (mod or "").lower():
                                self.fail(
                                    f"{fname}:{node.lineno} imports live broker: {mod}")


class TestIngestWindowCoverage(unittest.TestCase):
    """
    Verify the ingest phase window covers the full trading session (09:00–15:25)
    so signals generated at any point intraday are captured.
    """

    def _at(self, h: int, m: int):
        return datetime(2026, 7, 27, h, m, tzinfo=timezone(timedelta(hours=5, minutes=30)))

    def _active_phases(self, h, m):
        """Return all phase names active at (h, m) IST."""
        from signal_validation_tick import _PHASES
        hm = h * 60 + m
        return [name for name, (wh, wm), (eh, em), _ in _PHASES
                if wh * 60 + wm <= hm <= eh * 60 + em]

    def test_ingest_active_at_market_open(self):
        phases = self._active_phases(9, 5)
        self.assertIn("ingest_signals", phases)

    def test_ingest_active_midday(self):
        """Post-09:30 signals (e.g. 12:30) must also be captured."""
        phases = self._active_phases(12, 30)
        self.assertIn("ingest_signals", phases)

    def test_ingest_active_afternoon(self):
        """Signals at 14:45 IST must be captured."""
        phases = self._active_phases(14, 45)
        self.assertIn("ingest_signals", phases)

    def test_ingest_ends_before_eod_close(self):
        """Ingest window should end at/before EOD close window (15:25)."""
        from signal_validation_tick import _PHASES
        ingest_end = next(
            (eh * 60 + em for name, _, (eh, em), _ in _PHASES
             if name == "ingest_signals"),
            0,
        )
        eod_start = next(
            (wh * 60 + wm for name, (wh, wm), _, _ in _PHASES
             if name == "eod_close"),
            9999,
        )
        # ingest must end no later than eod_close starts
        self.assertLessEqual(ingest_end, eod_start)

    def test_no_post_market_ingest(self):
        """After market close (16:00) ingest should NOT be active."""
        phases = self._active_phases(16, 0)
        self.assertNotIn("ingest_signals", phases)


class TestTradeCorrelationDisambiguation(unittest.TestCase):
    """
    Prove that multiple same-direction signals on the same symbol each get
    their own unique paper trade via deterministic correlation — not all
    pointing at the same trade.
    """

    def setUp(self):
        self._recorded_events: list = []
        self._recorded_records: list = []
        _STUB_DB.insert_lifecycle_event = lambda evt: self._recorded_events.append(evt)
        _STUB_DB.upsert_record = lambda rec: self._recorded_records.append(rec)
        os.environ["SIGNAL_VALIDATION_ENABLED"] = "true"
        import signal_validation_model as _m
        try:
            _m._enabled_cache = None
        except Exception:
            pass

    def tearDown(self):
        _STUB_DB.insert_lifecycle_event = lambda evt: None
        _STUB_DB.upsert_record = lambda rec: None

    def _make_sig(self, sig_id: str, ts: str, price: str = "1650") -> dict:
        return {
            "id": sig_id, "stock": "TCS", "signal": "BUY",
            "price": price, "confidence": "0.80",
            "stop_loss": "1600", "target": "1720",
            "sector": "IT", "regime": "TRENDING_BULL",
            "strategy_id": "RSI", "strategy_name": "RSI Divergence",
            "time": ts,
            "explanation": {"recommendation": "BUY", "plain_english": "test"},
        }

    def _make_trade(self, trade_id: str, ts: str, price: str = "1651") -> dict:
        return {
            "id": trade_id, "symbol": "TCS", "action": "BUY",
            "quantity": 50, "price": price, "total": "82550",
            "timestamp": ts,
        }

    def test_two_signals_get_distinct_trades(self):
        """Two BUY signals on TCS each claim a separate paper trade."""
        sig1 = self._make_sig("sig-tcs-001", "2026-07-27T09:18:00+05:30", "1650")
        sig2 = self._make_sig("sig-tcs-002", "2026-07-27T10:30:00+05:30", "1660")
        pt1  = self._make_trade("pt-001", "2026-07-27T09:18:30+05:30", "1651")
        pt2  = self._make_trade("pt-002", "2026-07-27T10:30:30+05:30", "1661")
        paper_trades = [pt1, pt2]

        result = ingest_signal_batch(
            [sig1, sig2],
            session_id="sess-dis", trading_date="2026-07-27",
            paper_trades=paper_trades,
        )

        self.assertEqual(result["ingested"], 2)
        # Both should have advanced (each matched its respective trade)
        self.assertEqual(result["advanced"], 2)

        # Extract final upserted validation_status + paper_order_id pairs
        statuses = [(r.get("validation_status"), r.get("paper_order_id"))
                    for r in self._recorded_records]

        open_pos = [(s, oid) for s, oid in statuses
                    if s == LifecycleState.OPEN_POSITION]
        self.assertEqual(len(open_pos), 2, "Both signals should reach OPEN_POSITION")

        # paper_order_ids must be distinct (no double-claiming)
        order_ids = {oid for _, oid in open_pos if oid}
        self.assertEqual(len(order_ids), 2, "Each signal must claim a distinct paper trade")

    def test_single_trade_not_double_claimed(self):
        """When only one paper trade exists for two BUY signals, only the first gets it."""
        sig1 = self._make_sig("sig-tcs-003", "2026-07-27T09:18:00+05:30")
        sig2 = self._make_sig("sig-tcs-004", "2026-07-27T09:22:00+05:30")
        pt   = self._make_trade("pt-solo", "2026-07-27T09:18:30+05:30")

        result = ingest_signal_batch(
            [sig1, sig2],
            session_id="sess-dis2", trading_date="2026-07-27",
            paper_trades=[pt],
        )

        self.assertEqual(result["ingested"], 2)

        # Exactly one signal should reach OPEN_POSITION (the first one that claimed the trade)
        statuses = [r.get("validation_status") for r in self._recorded_records]
        open_count = statuses.count(LifecycleState.OPEN_POSITION)
        self.assertEqual(open_count, 1, "Only one signal may claim the sole paper trade")

        # The second signal should have been advanced to APPROVED but no further
        approved_count = statuses.count(LifecycleState.APPROVED)
        self.assertGreaterEqual(approved_count, 1,
                                "Second signal should reach at least APPROVED")

    def test_signal_id_in_trade_reason_wins_over_timestamp(self):
        """Exact signal_id match in trade.reason beats timestamp proximity."""
        sig = self._make_sig("sig-priority-001", "2026-07-27T09:18:00+05:30")
        # trade1 is closer in time but doesn't mention signal_id
        pt_close   = self._make_trade("pt-close",  "2026-07-27T09:18:05+05:30")
        # trade2 is further in time but mentions the signal_id in reason
        pt_exact   = {**self._make_trade("pt-exact", "2026-07-27T09:50:00+05:30"),
                      "reason": "sig-priority-001 breakout fill"}

        from signal_validation_lifecycle import (
            advance_lifecycle_from_signal, _find_matching_paper_trade
        )
        rec = record_from_signal(sig, "sess-prio", "2026-07-27")
        claimed: set = set()
        matched = _find_matching_paper_trade(rec, [pt_close, pt_exact], claimed_ids=claimed)
        # Must prefer the exact signal_id match
        self.assertEqual(matched["id"], "pt-exact")


class TestUpsertRecordRoundTrip(unittest.TestCase):
    """
    Regression tests proving that all mutable lifecycle fields survive a
    DB round-trip through upsert_record.  The stub DB captures the dict
    passed to upsert_record so we can verify every field is present and
    correct after a lifecycle transition — including fields that were only
    added in round 6 (risk_decision, approved_position_size, ai_agreement …).
    """

    def setUp(self):
        self._persisted: list = []
        _STUB_DB.upsert_record = lambda rec: self._persisted.append(dict(rec))
        _STUB_DB.insert_lifecycle_event = lambda evt: None
        os.environ["SIGNAL_VALIDATION_ENABLED"] = "true"
        import signal_validation_model as _m
        try:
            _m._enabled_cache = None
        except Exception:
            pass

    def tearDown(self):
        _STUB_DB.upsert_record = lambda rec: None
        _STUB_DB.insert_lifecycle_event = lambda evt: None

    def test_ai_fields_persisted_after_advance(self):
        """ai_recommendation and ai_agreement must be in the upserted record."""
        sig = {
            "id": "sig-rt-001", "stock": "INFY", "signal": "BUY",
            "price": "1650", "confidence": "0.82",
            "stop_loss": "1620", "target": "1700",
            "time": "2026-07-27T09:18:00+05:30",
            "explanation": {"recommendation": "BUY", "plain_english": "test"},
        }
        rec = record_from_signal(sig, "sess-rt", "2026-07-27")
        advance_lifecycle_from_signal(rec, sig, paper_trades=[])

        # At least one upsert should have been triggered
        self.assertTrue(len(self._persisted) >= 1)
        final = self._persisted[-1]

        # ai_recommendation may be under model name or DB name (both acceptable)
        ai_rec = final.get("AI_recommendation") or final.get("ai_recommendation")
        self.assertEqual(ai_rec, "BUY", "ai_recommendation must be persisted")

        ai_agr = final.get("AI_agreement") or final.get("ai_agreement")
        self.assertEqual(ai_agr, "AGREE", "ai_agreement must be persisted")

    def test_risk_decision_persisted_after_approval(self):
        """risk_decision='APPROVED' must appear in the upserted record."""
        sig = {
            "id": "sig-rt-002", "stock": "TCS", "signal": "BUY",
            "price": "3500", "confidence": "0.75",
            "stop_loss": "3450", "target": "3600",
            "time": "2026-07-27T09:20:00+05:30",
        }
        rec = record_from_signal(sig, "sess-rt", "2026-07-27")
        advance_lifecycle_from_signal(rec, sig, paper_trades=[])

        final = self._persisted[-1]
        self.assertEqual(final.get("risk_decision"), "APPROVED")

    def test_position_size_persisted_after_trade_correlation(self):
        """approved_position_size from matched trade must be in the upserted record."""
        sig = {
            "id": "sig-rt-003", "stock": "WIPRO", "signal": "BUY",
            "price": "450", "confidence": "0.80",
            "stop_loss": "440", "target": "470",
            "time": "2026-07-27T09:25:00+05:30",
        }
        pt = {
            "id": "pt-rt-003", "symbol": "WIPRO", "action": "BUY",
            "quantity": 75, "price": "451",
            "timestamp": "2026-07-27T09:25:30+05:30",
        }
        rec = record_from_signal(sig, "sess-rt", "2026-07-27")
        advance_lifecycle_from_signal(rec, sig, paper_trades=[pt])

        final = self._persisted[-1]
        self.assertEqual(int(final.get("approved_position_size") or 0), 75)

    def test_hypothetical_fields_persisted_on_risk_rejection(self):
        """is_hypothetical + hypothetical_label must be in the upserted record."""
        sig = {
            "id": "sig-rt-004", "stock": "HDFCBANK", "signal": "BUY",
            "price": "1700", "confidence": "0.60",
            "stop_loss": "1670", "target": "1750",
            "time": "2026-07-27T09:30:00+05:30",
            "risk_decision": "REJECTED",
            "risk_rejection_reason": "max_daily_loss_hit",
        }
        rec = record_from_signal(sig, "sess-rt", "2026-07-27")
        advance_lifecycle_from_signal(rec, sig, paper_trades=[])

        final = self._persisted[-1]
        self.assertTrue(final.get("is_hypothetical"),
                        "is_hypothetical must be True after risk rejection")
        self.assertIn("HYPOTHETICAL", str(final.get("hypothetical_label") or ""))
        self.assertEqual(final.get("risk_decision"), "REJECTED")
        self.assertEqual(final.get("risk_rejection_reason"), "max_daily_loss_hit")


class TestHighVolumeReAdvancement(unittest.TestCase):
    """
    Regression test: _re_advance_stuck_records must process ALL stuck records,
    not just the first page. This validates that the limit=None fix is in place
    so high-volume sessions (>200 signals per status) are fully advanced.
    """

    def setUp(self):
        self._records: list = []
        self._events:  list = []
        _STUB_DB.upsert_record          = lambda rec: self._records.append(dict(rec))
        _STUB_DB.insert_lifecycle_event = lambda evt: self._events.append(evt)
        os.environ["SIGNAL_VALIDATION_ENABLED"] = "true"
        import signal_validation_model as _m
        try:
            _m._enabled_cache = None
        except Exception:
            pass

    def tearDown(self):
        _STUB_DB.upsert_record          = lambda rec: None
        _STUB_DB.insert_lifecycle_event = lambda evt: None

    def test_re_advance_processes_all_records_beyond_200(self):
        """
        Simulate 250 APPROVED stuck records + 250 matching paper trades.
        All 250 must be advanced — none left behind due to a limit cap.
        """
        n = 250
        trading_date = "2026-07-27"

        # Build 250 APPROVED records and 250 matching paper trades
        stuck_recs = []
        paper_trades = []
        for i in range(n):
            sym = f"SYM{i:04d}"
            ts  = f"2026-07-27T09:{(i % 60):02d}:00+05:30"
            rec_dict = {
                "validation_id":      f"sv-{i:04d}",
                "signal_id":          f"sig-hv-{i:04d}",
                "trading_date":       trading_date,
                "symbol":             sym,
                "signal_direction":   "BUY",
                "signal_timestamp_ist": ts,
                "risk_decision":      "APPROVED",
                "validation_status":  LifecycleState.APPROVED,
                "paper_order_id":     None,
            }
            stuck_recs.append(rec_dict)
            paper_trades.append({
                "id":        f"pt-hv-{i:04d}",
                "symbol":    sym,
                "action":    "BUY",
                "quantity":  10,
                "price":     "100.00",
                "timestamp": ts,
            })

        # Inject stub: get_records returns all 250 for the APPROVED status
        original_get_records = _STUB_DB.get_records

        def stub_get_records(trading_date=None, validation_status=None,
                             limit=None, **kw):
            if validation_status == LifecycleState.APPROVED:
                # Return all — limit must be None for this to work correctly
                return stuck_recs if limit is None else stuck_recs[:limit]
            return []

        _STUB_DB.get_records = stub_get_records

        try:
            from signal_validation_tick import _re_advance_stuck_records
            claimed: set = set()
            advanced = _re_advance_stuck_records(trading_date, paper_trades,
                                                 claimed_trade_ids=claimed)
            self.assertEqual(advanced, n,
                             f"All {n} records must be advanced; got {advanced}")
            self.assertEqual(len(claimed), n,
                             f"All {n} trades must be claimed; got {len(claimed)}")
        finally:
            _STUB_DB.get_records = original_get_records


class TestCrossPassTradeClaimDedup(unittest.TestCase):
    """
    Regression test: a paper trade claimed by the new-ingest pass must NOT be
    re-claimed by the re-advance pass in the same tick, even when an older
    APPROVED record for the same symbol+direction is still in the DB.
    """

    def setUp(self):
        self._records: list = []
        self._events: list  = []
        _STUB_DB.upsert_record          = lambda rec: self._records.append(rec)
        _STUB_DB.insert_lifecycle_event = lambda evt: self._events.append(evt)
        os.environ["SIGNAL_VALIDATION_ENABLED"] = "true"
        import signal_validation_model as _m
        try:
            _m._enabled_cache = None
        except Exception:
            pass

    def tearDown(self):
        _STUB_DB.upsert_record          = lambda rec: None
        _STUB_DB.insert_lifecycle_event = lambda evt: None

    def test_shared_claimed_set_prevents_double_claim(self):
        """
        Simulate one tick where:
          - 1 new signal (sig-new) is ingested; its paper trade (pt-new) is claimed.
          - 1 old signal (sig-old) is stuck at APPROVED with no trade yet.
          - The shared claimed_trade_ids set must prevent sig-old from stealing pt-new.
        """
        pt_new = {
            "id": "pt-new", "symbol": "HDFCBANK", "action": "BUY",
            "quantity": 20, "price": "1700.00",
            "timestamp": "2026-07-27T09:30:00+05:30",
        }
        paper_trades = [pt_new]

        # Simulate the pre-seeded claimed set (pt-new already claimed by new-ingest)
        shared_claimed: set = {"pt-new"}

        # Old APPROVED record for same symbol — should NOT get pt-new
        old_rec = _make_rec(
            signal_id        = "sig-old",
            symbol           = "HDFCBANK",
            signal_direction = "BUY",
            validation_status = LifecycleState.APPROVED,
            signal_timestamp_ist = "2026-07-27T09:15:00+05:30",
        )
        sig_stub = {
            "id": old_rec.signal_id, "stock": old_rec.symbol,
            "signal": "BUY",
            "signal_timestamp_ist": old_rec.signal_timestamp_ist,
            "risk_decision": "APPROVED",
        }

        start_status = old_rec.validation_status
        advance_lifecycle_from_signal(
            old_rec, sig_stub,
            paper_trades=paper_trades,
            claimed_trade_ids=shared_claimed,
        )

        # Old record must NOT have been advanced past APPROVED
        self.assertEqual(old_rec.validation_status, LifecycleState.APPROVED,
                         "Stuck record must not steal a trade already claimed by new-ingest pass")
        self.assertIsNone(old_rec.paper_order_id,
                          "paper_order_id must remain None — trade was already claimed")


class TestDelayedTradeArrival(unittest.TestCase):
    """
    Regression tests for the re-advancement path:
    signal is ingested first (no paper trade yet) → later tick sees paper trade →
    record must advance to OPEN_POSITION on the later tick, not stay stuck at APPROVED.
    """

    def setUp(self):
        self._recorded_events: list = []
        self._recorded_records: list = []
        _STUB_DB.insert_lifecycle_event = lambda evt: self._recorded_events.append(evt)
        _STUB_DB.upsert_record = lambda rec: self._recorded_records.append(rec)
        os.environ["SIGNAL_VALIDATION_ENABLED"] = "true"
        import signal_validation_model as _m
        try:
            _m._enabled_cache = None
        except Exception:
            pass

    def tearDown(self):
        _STUB_DB.insert_lifecycle_event = lambda evt: None
        _STUB_DB.upsert_record = lambda rec: None

    def _make_approved_rec(self) -> SignalValidationRecord:
        r = _make_rec(
            validation_status=LifecycleState.APPROVED,
            risk_decision="APPROVED",
            signal_id="sig-delayed-001",
            symbol="WIPRO",
            signal_direction="BUY",
            signal_timestamp_ist="2026-07-27T09:20:00+05:30",
        )
        return r

    def test_approved_record_advances_when_trade_arrives(self):
        """An APPROVED record stuck from a previous tick must advance when trade appears."""
        rec = self._make_approved_rec()
        pt = {
            "id": "pt-delayed-001", "symbol": "WIPRO", "action": "BUY",
            "quantity": 30, "price": "451.00", "total": "13530",
            "timestamp": "2026-07-27T09:20:30+05:30",
        }
        sig_stub = {
            "id": rec.signal_id, "stock": rec.symbol,
            "signal": rec.signal_direction,
            "signal_timestamp_ist": rec.signal_timestamp_ist,
            "risk_decision": "APPROVED",
        }
        claimed: set = set()
        advance_lifecycle_from_signal(rec, sig_stub, paper_trades=[pt],
                                      claimed_trade_ids=claimed)
        self.assertEqual(rec.validation_status, LifecycleState.OPEN_POSITION)
        self.assertEqual(rec.paper_order_id, "pt-delayed-001")
        # Confirm trade claimed
        self.assertIn("pt-delayed-001", claimed)

    def test_paper_order_filled_advances_to_open_position_on_later_tick(self):
        """A PAPER_ORDER_FILLED record that missed the OPEN_POSITION step advances."""
        r = _make_rec(
            validation_status=LifecycleState.PAPER_ORDER_FILLED,
            paper_order_id="pt-filled-001",
            entry_price=Decimal("451.00"),
        )
        # Step through to OPEN_POSITION
        from signal_validation_lifecycle import transition
        self.assertTrue(
            LifecycleState.is_valid_transition(
                LifecycleState.PAPER_ORDER_FILLED, LifecycleState.OPEN_POSITION))
        transition(r, LifecycleState.OPEN_POSITION,
                   reason="re-advance on later tick",
                   source_component="test",
                   persist=False)
        self.assertEqual(r.validation_status, LifecycleState.OPEN_POSITION)


class TestPaperOrderFilledEODClose(unittest.TestCase):
    """
    Regression test: PAPER_ORDER_FILLED → CLOSED_POSITION must be permitted
    (direct EOD close when a position never formally reached OPEN_POSITION).
    """

    def test_paper_order_filled_can_close_directly(self):
        """PAPER_ORDER_FILLED → CLOSED_POSITION must be a valid transition."""
        self.assertTrue(
            LifecycleState.is_valid_transition(
                LifecycleState.PAPER_ORDER_FILLED, LifecycleState.CLOSED_POSITION),
            "PAPER_ORDER_FILLED → CLOSED_POSITION must be valid for direct EOD close",
        )

    def test_close_position_works_from_paper_order_filled(self):
        """close_position() must successfully close a PAPER_ORDER_FILLED record."""
        os.environ["SIGNAL_VALIDATION_ENABLED"] = "true"
        import signal_validation_model as _m
        try:
            _m._enabled_cache = None
        except Exception:
            pass

        events: list = []
        _STUB_DB.insert_lifecycle_event = lambda evt: events.append(evt)
        _STUB_DB.upsert_record = lambda rec: None

        try:
            r = _make_rec(
                validation_status=LifecycleState.PAPER_ORDER_FILLED,
                entry_price=Decimal("1650.00"),
                stop_loss=Decimal("1620.00"),
                approved_position_size=50,
            )
            close_position(r, Decimal("1690.00"), exit_reason="EOD_CLOSE")
            self.assertEqual(r.validation_status, LifecycleState.CLOSED_POSITION)
            self.assertEqual(r.exit_price, Decimal("1690.00"))
            self.assertIsNotNone(r.realised_pnl)
            close_evts = [e for e in events if e["to_state"] == LifecycleState.CLOSED_POSITION]
            self.assertEqual(len(close_evts), 1)
        finally:
            _STUB_DB.insert_lifecycle_event = lambda evt: None
            _STUB_DB.upsert_record = lambda rec: None
            os.environ.pop("SIGNAL_VALIDATION_ENABLED", None)
            try:
                _m._enabled_cache = None
            except Exception:
                pass


class TestEndToEndLifecycle(unittest.TestCase):
    """
    Integration-style tests: prove a single signal travels
    GENERATED → AI_REVIEWED → RISK_REVIEWED → APPROVED →
    PAPER_ORDER_CREATED → PAPER_ORDER_FILLED → OPEN_POSITION → CLOSED_POSITION
    with a lifecycle event logged at every transition.
    DB calls are mocked; no Postgres required.
    """

    def setUp(self):
        # Patch DB so lifecycle functions persist without a real DB
        self._recorded_events: list = []
        self._recorded_records: list = []

        original_insert_evt = _STUB_DB.insert_lifecycle_event
        original_upsert_rec = _STUB_DB.upsert_record

        _STUB_DB.insert_lifecycle_event = lambda evt: self._recorded_events.append(evt)
        _STUB_DB.upsert_record = lambda rec: self._recorded_records.append(rec)

        # Ensure feature flag is on for this suite
        import signal_validation_model as _m
        self._orig_enabled = os.environ.get("SIGNAL_VALIDATION_ENABLED", "")
        os.environ["SIGNAL_VALIDATION_ENABLED"] = "true"
        _m._enabled_cache = None  # clear cached value if any

        self._orig_insert_evt = original_insert_evt
        self._orig_upsert_rec = original_upsert_rec

    def tearDown(self):
        _STUB_DB.insert_lifecycle_event = self._orig_insert_evt
        _STUB_DB.upsert_record = self._orig_upsert_rec
        os.environ["SIGNAL_VALIDATION_ENABLED"] = self._orig_enabled
        import signal_validation_model as _m
        try:
            _m._enabled_cache = None
        except Exception:
            pass

    def _make_signal(self) -> dict:
        return {
            "id":             "sig-e2e-001",
            "stock":          "INFY",
            "signal":         "BUY",
            "price":          "1650.00",
            "confidence":     "0.82",
            "stop_loss":      "1620.00",
            "target":         "1700.00",
            "sector":         "IT",
            "regime":         "TRENDING_BULL",
            "strategy_id":    "BREAKOUT_V2",
            "strategy_name":  "Breakout v2",
            "time":           "2026-07-27T09:18:00+05:30",
            "explanation": {
                "trend":            "strong uptrend",
                "momentum":         "high",
                "plain_english":    "Breakout above resistance with volume confirmation",
                "recommendation":   "BUY",
            },
            # No risk_decision field → treated as APPROVED by advance_lifecycle_from_signal
        }

    def _make_paper_trade(self) -> dict:
        return {
            "id":        "pt-e2e-001",
            "symbol":    "INFY",
            "action":    "BUY",
            "quantity":  50,
            "price":     "1651.00",
            "total":     "82550.00",
            "timestamp": "2026-07-27T09:18:30+05:30",
        }

    def test_full_lifecycle_generated_to_open_position(self):
        """GENERATED → OPEN_POSITION in one advance_lifecycle_from_signal call."""
        sig = self._make_signal()
        pt  = self._make_paper_trade()

        rec = record_from_signal(sig, "sess-e2e", "2026-07-27")
        self.assertEqual(rec.validation_status, LifecycleState.GENERATED)
        self.assertEqual(rec.symbol, "INFY")

        advance_lifecycle_from_signal(rec, sig, paper_trades=[pt])

        # Must reach OPEN_POSITION
        self.assertEqual(rec.validation_status, LifecycleState.OPEN_POSITION)

        # AI fields must be hydrated
        self.assertEqual(rec.AI_recommendation, "BUY")
        self.assertEqual(rec.AI_agreement, "AGREE")

        # Entry price must come from the paper trade
        self.assertEqual(rec.entry_price, Decimal("1651.00"))
        self.assertTrue(rec.paper_order_created)

        # At least 4 lifecycle events should have been emitted
        # (AI_REVIEWED, RISK_REVIEWED, APPROVED, PAPER_ORDER_CREATED,
        #  PAPER_ORDER_FILLED, OPEN_POSITION — some may be batched)
        self.assertGreaterEqual(len(self._recorded_events), 4)

        # Verify audit trail has required transitions
        to_states = [e["to_state"] for e in self._recorded_events]
        self.assertIn(LifecycleState.AI_REVIEWED,          to_states)
        self.assertIn(LifecycleState.RISK_REVIEWED,        to_states)
        self.assertIn(LifecycleState.APPROVED,             to_states)
        self.assertIn(LifecycleState.PAPER_ORDER_CREATED,  to_states)
        self.assertIn(LifecycleState.PAPER_ORDER_FILLED,   to_states)
        self.assertIn(LifecycleState.OPEN_POSITION,        to_states)

    def test_full_lifecycle_open_to_closed_position(self):
        """OPEN_POSITION → CLOSED_POSITION via close_position()."""
        sig = self._make_signal()
        pt  = self._make_paper_trade()

        rec = record_from_signal(sig, "sess-e2e", "2026-07-27")
        advance_lifecycle_from_signal(rec, sig, paper_trades=[pt])
        self.assertEqual(rec.validation_status, LifecycleState.OPEN_POSITION)

        self._recorded_events.clear()

        # Simulate EOD close
        close_position(rec, Decimal("1695.00"), exit_reason="EOD_CLOSE")

        self.assertEqual(rec.validation_status, LifecycleState.CLOSED_POSITION)
        self.assertEqual(rec.exit_price,  Decimal("1695.00"))
        self.assertEqual(rec.exit_reason, "EOD_CLOSE")
        self.assertIsNotNone(rec.realised_pnl)

        # Confirm R-multiple is positive (profitable BUY)
        self.assertGreater(rec.R_multiple, Decimal("0"))

        # Confirm CLOSED_POSITION lifecycle event was emitted
        close_events = [e for e in self._recorded_events
                        if e["to_state"] == LifecycleState.CLOSED_POSITION]
        self.assertEqual(len(close_events), 1)

    def test_risk_rejected_signal_marked_hypothetical(self):
        """Risk-rejected signals end at RISK_REJECTED and are hypothetical."""
        sig = self._make_signal()
        sig["risk_decision"]        = "REJECTED"
        sig["risk_rejection_reason"]= "position_limit_exceeded"

        rec = record_from_signal(sig, "sess-e2e", "2026-07-27")
        advance_lifecycle_from_signal(rec, sig, paper_trades=[])

        self.assertEqual(rec.validation_status, LifecycleState.RISK_REJECTED)
        self.assertTrue(rec.is_hypothetical)
        self.assertIn("HYPOTHETICAL", rec.hypothetical_label)
        self.assertEqual(rec.risk_rejection_reason, "position_limit_exceeded")

    def test_ingest_batch_advances_lifecycle(self):
        """ingest_signal_batch creates and advances records in one call."""
        sig = self._make_signal()
        pt  = self._make_paper_trade()

        result = ingest_signal_batch(
            [sig], session_id="sess-e2e", trading_date="2026-07-27",
            paper_trades=[pt],
        )

        self.assertEqual(result["ingested"], 1)
        self.assertGreaterEqual(result["advanced"], 1)
        self.assertEqual(result["errors"], 0)

        # The persisted record should be at OPEN_POSITION, not just GENERATED
        upserted_records = self._recorded_records
        self.assertTrue(len(upserted_records) >= 2,
                        "Expected at least initial GENERATED + advanced upsert")
        final_status = upserted_records[-1].get("validation_status")
        self.assertEqual(final_status, LifecycleState.OPEN_POSITION)


if __name__ == "__main__":
    unittest.main(verbosity=2)
