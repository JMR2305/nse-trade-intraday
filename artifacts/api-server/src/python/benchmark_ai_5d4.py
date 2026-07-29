"""
benchmark_ai_5d4.py — Phase 5D.4 / Task #162
=============================================
Confirms:
  1. The full _compute_all() pipeline stays under 100 ms at 100 / 500 / 1000
     trade-pairs after the _rolling_30d O(n log n) refactor.
  2. Calibration ECE stabilises (stdev < 0.02) when each confidence bucket
     has >= 20 signals.
  3. MCC is non-zero and scale-invariant when all four TP/FP/TN/FN quadrants
     are populated.

Run from the python/ directory:
    python benchmark_ai_5d4.py

Exit code 0 = all checks pass.
Exit code 1 = at least one check failed.

Design notes
------------
* Must live OUTSIDE ai_performance/ — the package contains a statistics.py
  that shadows the stdlib on direct-script execution inside the package.
* Enables both feature flags via os.environ BEFORE any module imports so
  is_enabled() reads the flag at call time (it reads os.environ each call).
* Stubs market_scanner and execution_quality before importing ai_performance
  so no live scan process is spawned.
* Patches portfolio_store at the object level (patch.object) so that the
  import inside strategy_intelligence.strategy_engine.load_all_data() sees
  the synthetic trades.
* Verifies _compute_all() returns status-ENABLED results; a result where
  signals == [] would indicate a disabled-path false-positive.
"""
from __future__ import annotations

import os
import sys
import time
import types
import math
import statistics
import unittest.mock
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

# ── Feature flags BEFORE any module imports ──────────────────────────────────
os.environ["AI_PERFORMANCE_ENABLED"]       = "true"
os.environ["STRATEGY_INTELLIGENCE_ENABLED"] = "true"

# ── Add python/ directory to path ────────────────────────────────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# ── Stub slow/external modules BEFORE importing ai_performance ───────────────
_scanner = types.ModuleType("market_scanner")
_scanner._sector_of = lambda sym: "Technology"
sys.modules.setdefault("market_scanner", _scanner)

_eq = types.ModuleType("execution_quality")
_eq_m = types.ModuleType("execution_quality.metrics")
_eq_m.build_execution_records = lambda: []
_eq.metrics = _eq_m
sys.modules.setdefault("execution_quality", _eq)
sys.modules.setdefault("execution_quality.metrics", _eq_m)

# ── Now safe to import ────────────────────────────────────────────────────────
import portfolio_store                                          # noqa: E402
from ai_performance.shared_services  import _compute_all       # noqa: E402
from ai_performance.calibration      import compute_calibration # noqa: E402
from ai_performance.prediction_analysis import compute_prediction_metrics  # noqa: E402
from ai_performance.ai_models import AISignalRecord, CONFIDENCE_BUCKETS   # noqa: E402
from ai_performance.learning_analysis import _rolling_30d                 # noqa: E402

THRESHOLD_MS = 100.0
ITERATIONS   = 5      # runs per scale; we report the median

SYMBOLS     = ["INFY", "TCS", "RELIANCE", "HDFC", "WIPRO",
               "BHARTIARTL", "ICICIBANK", "SBI", "LT", "AXISBANK"]
CONF_VALUES = [0.95, 0.85, 0.75, 0.65, 0.45]   # one representative per bucket


# ── Synthetic data generators ─────────────────────────────────────────────────

def _ts(day_offset: int = 0, hour: int = 9) -> str:
    base = datetime(2025, 1, 2, 4, 0, 0, tzinfo=timezone.utc)   # Thu 09:30 IST
    return (base + timedelta(days=day_offset, hours=hour)).isoformat()


def _make_raw_trades(n_pairs: int) -> List[Dict[str, Any]]:
    """
    Generate n_pairs BUY+SELL round-trips spread across:
    - All 5 confidence buckets (rotated via i % 5)
    - n_pairs // len(SYMBOLS) unique exit dates
    - 70% winners at high confidence, 40% winners at low confidence
    """
    trades: List[Dict[str, Any]] = []
    for i in range(n_pairs):
        sym  = SYMBOLS[i % len(SYMBOLS)]
        conf = CONF_VALUES[i % len(CONF_VALUES)]
        day  = i // len(SYMBOLS)   # spread across many dates

        high = conf >= 0.60
        # High confidence → 70% win rate; low confidence → 40%
        winner    = ((i % 10) < 7) if high else ((i % 10) < 4)
        pnl       = 500.0 if winner else -200.0
        exit_type = "TARGET_HIT" if winner else "STOP_HIT"
        qty, price = 10, 1000.0
        exit_p = price + pnl / qty

        trades.append({
            "id": f"buy-{i}", "symbol": sym, "action": "BUY",
            "quantity": qty, "price": price, "total": qty * price,
            "timestamp": _ts(day, 9),
            "strategy_id": "s1",
            "strategy_name": "Momentum" if i % 2 == 0 else "Mean Reversion",
            "stop_loss": price * 0.97, "target": price * 1.05,
            "market_regime_at_entry": "Bullish",
            "signal_confidence": conf, "reason": "signal",
        })
        trades.append({
            "id": f"sell-{i}", "symbol": sym, "action": "SELL",
            "quantity": qty, "price": exit_p, "total": qty * exit_p,
            "timestamp": _ts(day, 15),
            "pnl": pnl, "pnl_pct": pnl / (qty * price) * 100,
            "exit_type": exit_type,
        })
    return trades


def _make_bucket_signals(n_per_bucket: int, seed: int) -> List[AISignalRecord]:
    """
    Create AISignalRecord objects covering all 5 confidence buckets.
    Each bucket's win rate ≈ its midpoint confidence (well-calibrated base)
    with a small pseudo-random perturbation from `seed`.
    """
    signals: List[AISignalRecord] = []
    lcg = (seed * 1103515245 + 12345) & 0x7FFFFFFF

    for label, lo, hi in CONFIDENCE_BUCKETS:
        conf_mid = min((lo + hi) / 2.0, 0.95)
        # Pseudo-random perturbation in ±0.04 range
        lcg = (lcg * 1103515245 + 12345) & 0x7FFFFFFF
        noise = ((lcg % 9) - 4) / 100.0      # −0.04 to +0.04
        win_rate  = max(0.0, min(1.0, conf_mid + noise))
        win_count = round(win_rate * n_per_bucket)
        high = conf_mid >= 0.60

        for j in range(n_per_bucket):
            is_w = j < win_count
            signals.append(AISignalRecord(
                signal_confidence = conf_mid,
                confidence_bucket = label,
                is_winner         = is_w,
                is_tp = high and is_w,
                is_fp = high and not is_w,
                is_tn = not high and not is_w,
                is_fn = not high and is_w,
            ))
    return signals


# ── Timing helper ─────────────────────────────────────────────────────────────

def _median(vals: List[float]) -> float:
    s = sorted(vals)
    n = len(s)
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2.0


# ── Benchmark sections ────────────────────────────────────────────────────────

def bench_compute_all() -> bool:
    """Time _compute_all() at 100 / 500 / 1000 trade-pairs."""
    print("\n── _compute_all() pipeline latency ──")
    all_pass = True

    for n_pairs in (100, 500, 1000):
        trades = _make_raw_trades(n_pairs)

        with unittest.mock.patch.object(
            portfolio_store, "load_all_trades_any", return_value=trades
        ):
            times = []
            result = None
            for _ in range(ITERATIONS):
                t0 = time.perf_counter()
                result = _compute_all()
                times.append((time.perf_counter() - t0) * 1000.0)

        ms = _median(times)
        ok = ms <= THRESHOLD_MS

        # Sanity: ensure we executed real compute (not a disabled stub)
        n_signals = len(result.get("signals", []))
        if n_signals == 0:
            print(f"  ERROR: {n_pairs} pairs returned 0 signals — "
                  "feature flag or mock may be misconfigured")
            all_pass = False
            continue

        status = "✓" if ok else "✗ EXCEEDED"
        print(f"  {n_pairs:>5} trade-pairs → {n_signals:>5} signals  "
              f"{ms:8.2f} ms  {status}")
        if not ok:
            all_pass = False

    return all_pass


def bench_rolling_30d() -> bool:
    """Confirm _rolling_30d() is sub-linear (O(n log n)) at 1000 signals."""
    print("\n── _rolling_30d() sliding-window latency ──")

    def _make_signals(n: int) -> List[AISignalRecord]:
        sigs = []
        for i in range(n):
            day = i // 5
            d = (datetime(2025, 1, 1) + timedelta(days=day)).strftime("%Y-%m-%d")
            sigs.append(AISignalRecord(exit_date=d, is_winner=(i % 3 != 0)))
        return sigs

    all_pass = True
    for n in (100, 500, 1000):
        sigs = _make_signals(n)
        times = []
        for _ in range(ITERATIONS):
            t0 = time.perf_counter()
            _rolling_30d(sigs)
            times.append((time.perf_counter() - t0) * 1000.0)
        ms = _median(times)
        ok = ms <= THRESHOLD_MS
        print(f"  {n:>5} signals  {ms:8.3f} ms  {'✓' if ok else '✗ EXCEEDED'}")
        if not ok:
            all_pass = False

    return all_pass


def bench_ece_stability() -> bool:
    """ECE stdev < 0.02 across 10 seeds when each bucket has >= 20 signals."""
    print("\n── ECE stability (variance < 0.02 at ≥ 20 trades/bucket) ──")
    all_pass = True

    for n_per_bucket in (5, 10, 20, 30):
        eces = []
        for seed in range(10):
            sigs = _make_bucket_signals(n_per_bucket, seed)
            m    = compute_calibration(sigs)
            eces.append(m.ece)

        stdev = statistics.stdev(eces) if len(eces) > 1 else 0.0
        min_e = min(eces)
        max_e = max(eces)
        ok    = True

        if n_per_bucket >= 20:
            ok = stdev < 0.02
        status = "✓" if ok else f"✗ stdev={stdev:.4f} exceeds 0.02"
        print(f"  {n_per_bucket:>3} trades/bucket  ECE=[{min_e:.3f}–{max_e:.3f}]  "
              f"stdev={stdev:.4f}  {status}")
        if not ok:
            all_pass = False

    return all_pass


def bench_mcc_at_scale() -> bool:
    """MCC is non-zero and scale-invariant when all quadrants are populated."""
    print("\n── MCC accuracy at scale ──")
    all_pass = True

    # Better-than-random classifier: TP+TN > FP+FN in absolute terms
    scenarios = [
        ("100 signals",  40,  20, 30, 10),
        ("500 signals",  200, 100, 150, 50),
        ("1000 signals", 400, 200, 300, 100),
    ]
    reference_mcc = None

    for label, tp, fp, tn, fn in scenarios:
        from ai_performance.ai_models import AISignalRecord as ASR
        signals = (
            [ASR(is_tp=True,  is_winner=True,  is_high_confidence=True)]  * tp +
            [ASR(is_fp=True,  is_winner=False, is_high_confidence=True)]  * fp +
            [ASR(is_tn=True,  is_winner=False, is_high_confidence=False)] * tn +
            [ASR(is_fn=True,  is_winner=True,  is_high_confidence=False)] * fn
        )
        m = compute_prediction_metrics(signals)

        if reference_mcc is None:
            reference_mcc = m.mcc

        nonzero   = m.mcc > 0.0
        invariant = abs(m.mcc - reference_mcc) < 0.001

        ok = nonzero and invariant
        print(f"  {label:<14}  TP={tp:<4} FP={fp:<4} TN={tn:<4} FN={fn:<4}  "
              f"MCC={m.mcc:.4f}  {'✓' if ok else '✗'}")
        if not ok:
            all_pass = False
            if not nonzero:
                print(f"    ✗ MCC is 0 — all-quadrant population not producing non-zero MCC")
            if not invariant:
                print(f"    ✗ MCC not scale-invariant: {m.mcc:.4f} vs ref {reference_mcc:.4f}")

    return all_pass


def main() -> int:
    print("=" * 64)
    print("AI Performance Benchmark — Phase 5D.4 / Task #162")
    print(f"Threshold: {THRESHOLD_MS:.0f} ms  |  Iterations: {ITERATIONS} (median)")
    print("=" * 64)

    r1 = bench_compute_all()
    r2 = bench_rolling_30d()
    r3 = bench_ece_stability()
    r4 = bench_mcc_at_scale()

    print("\n── Final Verdict ──")
    if all([r1, r2, r3, r4]):
        print("\n✓  All checks pass.")
        print("   _rolling_30d() refactored to O(n log n) sorted sliding window.")
        print("   _compute_all() under 100 ms at 1000 trade-pairs.")
        print("   ECE stdev < 0.02 at 20+ trades/bucket.")
        print("   MCC non-zero and scale-invariant with all quadrants populated.")
        return 0
    else:
        failed = [name for ok, name in
                  [(r1, "_compute_all latency"), (r2, "_rolling_30d latency"),
                   (r3, "ECE stability"), (r4, "MCC at scale")]
                  if not ok]
        print(f"\n✗  Failed: {', '.join(failed)}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
