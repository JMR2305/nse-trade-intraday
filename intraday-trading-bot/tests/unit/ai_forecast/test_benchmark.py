from __future__ import annotations

from decimal import Decimal
from datetime import datetime

import pytest

from ai_forecast.benchmark import BenchmarkEntry, BenchmarkReport, ForecastBenchmark
from ai_forecast.kronos_adapter import ForecastResult


class TestForecastBenchmark:
    def test_record_and_evaluate(self) -> None:
        bench = ForecastBenchmark()
        bench.record_forecast("INFY", "UP", Decimal("0.70"), datetime.utcnow().isoformat())
        bench.evaluate("INFY", "UP", datetime.utcnow().isoformat())
        report = bench.generate_report()
        assert report.total_predictions == 1
        assert report.correct_predictions == 1
        assert report.accuracy == Decimal("1")

    def test_evaluate_mismatch(self) -> None:
        bench = ForecastBenchmark()
        bench.record_forecast("INFY", "UP", Decimal("0.70"), datetime.utcnow().isoformat())
        bench.evaluate("INFY", "DOWN", datetime.utcnow().isoformat())
        report = bench.generate_report()
        assert report.total_predictions == 1
        assert report.correct_predictions == 0
        assert report.accuracy == Decimal("0")

    def test_no_pending_ignores_evaluate(self) -> None:
        bench = ForecastBenchmark()
        bench.evaluate("INFY", "UP", datetime.utcnow().isoformat())
        report = bench.generate_report()
        assert report.total_predictions == 0

    def test_multiple_predictions(self) -> None:
        bench = ForecastBenchmark()
        bench.record_forecast("INFY", "UP", Decimal("0.60"), datetime.utcnow().isoformat())
        bench.evaluate("INFY", "UP", datetime.utcnow().isoformat())
        bench.record_forecast("TCS", "DOWN", Decimal("0.55"), datetime.utcnow().isoformat())
        bench.evaluate("TCS", "DOWN", datetime.utcnow().isoformat())
        bench.record_forecast("INFY", "UP", Decimal("0.65"), datetime.utcnow().isoformat())
        bench.evaluate("INFY", "DOWN", datetime.utcnow().isoformat())
        report = bench.generate_report()
        assert report.total_predictions == 3
        assert report.correct_predictions == 2
        assert report.accuracy == Decimal("0.6667")

    def test_by_instrument_breakdown(self) -> None:
        bench = ForecastBenchmark()
        bench.record_forecast("INFY", "UP", Decimal("0.60"), datetime.utcnow().isoformat())
        bench.evaluate("INFY", "UP", datetime.utcnow().isoformat())
        bench.record_forecast("TCS", "DOWN", Decimal("0.55"), datetime.utcnow().isoformat())
        bench.evaluate("TCS", "UP", datetime.utcnow().isoformat())
        report = bench.generate_report()
        assert report.by_instrument["INFY"]["total"] == 1
        assert report.by_instrument["INFY"]["correct"] == 1
        assert report.by_instrument["TCS"]["total"] == 1
        assert report.by_instrument["TCS"]["correct"] == 0

    def test_by_direction_breakdown(self) -> None:
        bench = ForecastBenchmark()
        bench.record_forecast("INFY", "UP", Decimal("0.60"), datetime.utcnow().isoformat())
        bench.evaluate("INFY", "UP", datetime.utcnow().isoformat())
        bench.record_forecast("TCS", "DOWN", Decimal("0.55"), datetime.utcnow().isoformat())
        bench.evaluate("TCS", "DOWN", datetime.utcnow().isoformat())
        report = bench.generate_report()
        assert report.by_direction["UP"]["total"] == 1
        assert report.by_direction["DOWN"]["total"] == 1

    def test_avg_confidence(self) -> None:
        bench = ForecastBenchmark()
        bench.record_forecast("INFY", "UP", Decimal("0.60"), datetime.utcnow().isoformat())
        bench.evaluate("INFY", "UP", datetime.utcnow().isoformat())
        bench.record_forecast("INFY", "UP", Decimal("0.80"), datetime.utcnow().isoformat())
        bench.evaluate("INFY", "UP", datetime.utcnow().isoformat())
        report = bench.generate_report()
        assert report.avg_confidence == Decimal("0.7")

    def test_accuracy_threshold_alert(self) -> None:
        bench = ForecastBenchmark(accuracy_threshold=0.6)
        bench.record_forecast("INFY", "UP", Decimal("0.70"), datetime.utcnow().isoformat())
        bench.evaluate("INFY", "DOWN", datetime.utcnow().isoformat())
        report = bench.generate_report()
        assert report.accuracy == Decimal("0")

    def test_clear_removes_all(self) -> None:
        bench = ForecastBenchmark()
        bench.record_forecast("INFY", "UP", Decimal("0.70"), datetime.utcnow().isoformat())
        bench.evaluate("INFY", "UP", datetime.utcnow().isoformat())
        bench.clear()
        report = bench.generate_report()
        assert report.total_predictions == 0
        assert report.correct_predictions == 0

    def test_empty_report(self) -> None:
        bench = ForecastBenchmark()
        report = bench.generate_report()
        assert report.total_predictions == 0
        assert report.correct_predictions == 0
        assert report.accuracy == Decimal("0")
        assert report.avg_confidence == Decimal("0")

    def test_report_period(self) -> None:
        bench = ForecastBenchmark()
        report = bench.generate_report(period="weekly")
        assert report.report_period == "weekly"
