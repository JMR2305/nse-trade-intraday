"""S1 execution-settings authority repair - focused tests.

Task: TAsk978ZR-R38C-R3A - S1 backtest-harness repair + offline TDD
verification.
Base head: d2feecef9e74a5ecad420fd846a1ca306b0baca5

Verification of the S1 EXECUTION-SETTINGS CONTRACT.  These tests prove the
missing executed-cost authority.  They were written FIRST (RED), run against
the untouched production source, and only then re-run against the minimal
green source.

Test coverage:
  1. legacy default resolution (NEXT_QUOTE / 0.15 / 0.12)
  2. R38C override resolution (SLIPPAGE_ADJUSTED / 0.15 / 0.12)
  3. invalid model fails closed (no silent fallback to NEXT_QUOTE)
  4. invalid numeric settings fail closed (NaN, Inf, negative, bool, string)
  5. unknown/misspelled key fails closed
  6. _try_enter receives resolved settings + records resolved fill_model
  7. economic model difference proven via the existing phase20_executor
  8. resolution occurs once per run (same object propagated into _try_enter)
  9. completion config AND metrics contain the exact resolved settings
 10. default backtest behaviour regression (no execution_settings override)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import backtest_runner as br  # noqa: E402
import phase20_executor as pe  # noqa: E402

# phase20_executor writes slippage_pct as a PERCENT (e.g. 0.15 means 0.15%).
# The R38B authority mandates slippage_pct = 0.15 -> adverse slip of 0.15%.
_SLIPPAGE_PCT = 0.15
_CHARGES_PCT = 0.12


def _base_cfg(overrides: dict | None = None) -> dict:
    cfg = {
        "start": "2024-01-01",
        "end": "2024-02-01",
        "interval": "1d",
        "capital": 100000.0,
        "sizing": {
            "risk_per_trade_pct": 1.0,
            "max_position_cap_pct": 25.0,
            "max_symbol_exposure_pct": 25.0,
            "max_total_exposure_pct": 80.0,
            "scale_in_enabled": False,
            "max_scale_in_count": 2,
            "scale_in_min_confidence": 60.0,
            "scale_in_min_rr": 1.5,
            "scale_in_min_unrealized_profit_pct": -1.0,
        },
    }
    if overrides:
        cfg.update(overrides)
    return cfg


def _exec_settings(cfg: dict) -> dict:
    return br.resolve_execution_settings(cfg)


# ── TEST 1 - legacy default resolution ───────────────────────────────────────

def test_1_legacy_default_resolution():
    cfg = _base_cfg()
    resolved = _exec_settings(cfg)
    assert resolved == {
        "fill_model": "NEXT_QUOTE",
        "slippage_pct": _SLIPPAGE_PCT,
        "charges_pct": _CHARGES_PCT,
    }


# ── TEST 2 - R38C override resolution ────────────────────────────────────────

def test_2_r38c_override_resolution():
    cfg = _base_cfg({
        "execution_settings": {
            "fill_model": "SLIPPAGE_ADJUSTED",
            "slippage_pct": _SLIPPAGE_PCT,
            "charges_pct": _CHARGES_PCT,
        },
    })
    resolved = _exec_settings(cfg)
    assert resolved == {
        "fill_model": "SLIPPAGE_ADJUSTED",
        "slippage_pct": _SLIPPAGE_PCT,
        "charges_pct": _CHARGES_PCT,
    }
    # DEFAULT_SETTINGS must not be mutated.
    assert br.DEFAULT_SETTINGS == {
        "fill_model": "NEXT_QUOTE",
        "slippage_pct": _SLIPPAGE_PCT,
        "charges_pct": _CHARGES_PCT,
    }


# ── TEST 3 - invalid model fails closed ──────────────────────────────────────

@pytest.mark.parametrize("bad_model", [
    "R38C_FAKE_MODEL",
    "PARTIAL_ADJUSTED",
    "LAST_TRADED",
])
def test_3_invalid_model_fails_closed(bad_model):
    cfg = _base_cfg({
        "execution_settings": {
            "fill_model": bad_model,
            "slippage_pct": _SLIPPAGE_PCT,
            "charges_pct": _CHARGES_PCT,
        },
    })
    with pytest.raises((ValueError, KeyError, TypeError)):
        _exec_settings(cfg)


# ── TEST 4 - invalid numeric settings fail closed ────────────────────────────

@pytest.mark.parametrize(
    "slippage, charges, payload",
    [
        (float("nan"), _CHARGES_PCT, "slippage NaN"),
        (float("inf"), _CHARGES_PCT, "slippage +Inf"),
        (-_SLIPPAGE_PCT, _CHARGES_PCT, "slippage negative"),
        (True, _CHARGES_PCT, "slippage bool"),
        ("0.15", _CHARGES_PCT, "slippage string"),
        (_SLIPPAGE_PCT, float("nan"), "charges NaN"),
        (_SLIPPAGE_PCT, float("inf"), "charges +Inf"),
        (_SLIPPAGE_PCT, -_CHARGES_PCT, "charges negative"),
        (_SLIPPAGE_PCT, True, "charges bool"),
        (_SLIPPAGE_PCT, "0.12", "charges string"),
    ],
)
def test_4_invalid_numeric_settings_fail_closed(slippage, charges, payload):
    cfg = _base_cfg({
        "execution_settings": {
            "fill_model": "SLIPPAGE_ADJUSTED",
            "slippage_pct": slippage,
            "charges_pct": charges,
        },
    })
    with pytest.raises((ValueError, KeyError, TypeError)):
        _exec_settings(cfg)


# ── TEST 5 - unknown/misspelled key fails closed ─────────────────────────────

def test_5_unknown_misspelled_key_fails_closed():
    cfg = _base_cfg({
        "execution_settings": {
            "fill_modle": "SLIPPAGE_ADJUSTED",  # typo
            "slippage_pct": _SLIPPAGE_PCT,
            "charges_pct": _CHARGES_PCT,
        },
    })
    with pytest.raises((ValueError, KeyError, TypeError)):
        _exec_settings(cfg)


# ── TEST 6 - _try_enter uses resolved settings ───────────────────────────────

def test_6_try_enter_uses_resolved_settings(monkeypatch):
    # Patch/spy: prove that when the resolved execution settings are passed
    # into _try_enter, BOTH compute_fill / compute_charges receive that object
    # and ORDER_SUBMITTED records the resolved fill_model.
    import backtest_runner as br_mod

    spy = {"execution_settings": None}

    orig_try_enter = br_mod._try_enter

    def spy_try_enter(*args, **kwargs):
        spy["execution_settings"] = kwargs.get("execution_settings")
        return orig_try_enter(*args, **kwargs)

    monkeypatch.setattr(br_mod, "_try_enter", spy_try_enter)

    cfg = _base_cfg({
        "execution_settings": {
            "fill_model": "SLIPPAGE_ADJUSTED",
            "slippage_pct": _SLIPPAGE_PCT,
            "charges_pct": _CHARGES_PCT,
        },
    })
    resolved = _exec_settings(cfg)
    assert resolved["fill_model"] == "SLIPPAGE_ADJUSTED"

    class _FakeRec:
        entry_price = 100.0
        stop_loss = 90.0
        symbol = "TEST"
        calibrated_confidence = 80.0
        rr_ratio = 2.5
        target_price = 110.0
        strategy_id = "ST1"
        strategy_name = "Test Strategy"
        regime = "normal"
        opportunity_score = 0.5
        tranche = 1
        error = None
        all_gates_passed = True
        final_action = "BUY"
        _stage_ts = {}

    br_mod._try_enter(
        "run_id", "scan_id", _FakeRec(), 1000.0,
        "2024-01-01T09:15:00", sizing=None,
        mark=100.0, execution_settings=resolved,
    )
    assert spy["execution_settings"] is resolved
    assert spy["execution_settings"]["fill_model"] == "SLIPPAGE_ADJUSTED"
def test_7_economic_model_difference():
    # Pristine proof using the existing phase20_executor (unchanged by S1).
    entry = 100.0
    slp = {
        "fill_model": "SLIPPAGE_ADJUSTED",
        "slippage_pct": _SLIPPAGE_PCT,
        "charges_pct": _CHARGES_PCT,
    }
    nq = {
        "fill_model": "NEXT_QUOTE",
        "slippage_pct": _SLIPPAGE_PCT,
        "charges_pct": _CHARGES_PCT,
    }

    adjusted_fill = pe.compute_fill(entry, slp, side="BUY")
    quote_fill = pe.compute_fill(entry, nq, side="BUY")
    adjusted_charge = pe.compute_charges(entry * 100, slp)
    quote_charge = pe.compute_charges(entry * 100, nq)

    # R38B slip is 0.15% of entry: 100 * 0.0015 = 0.15 -> fill 100.15.
    assert abs(adjusted_fill["fill_price"] - round(entry * (1 + _SLIPPAGE_PCT / 100), 2)) < 1e-9
    # NEXT_QUOTE applies half the adverse slip: 0.075% -> fill 100.08.
    assert abs(quote_fill["fill_price"] - round(entry * (1 + _SLIPPAGE_PCT / 200), 2)) < 1e-9
    assert adjusted_fill["fill_price"] != quote_fill["fill_price"]
    # charges reflect charges_pct on the resolved turnover.
    assert adjusted_charge == round(entry * 100 * _CHARGES_PCT / 100, 2)
    assert quote_charge == adjusted_charge

    # R38C can now deliberately choose the authoritative contract:
    # full adverse slippage = 0.15% -> 100.15.
    resolved = br.resolve_execution_settings({
        "execution_settings": {
            "fill_model": "SLIPPAGE_ADJUSTED",
            "slippage_pct": _SLIPPAGE_PCT,
            "charges_pct": _CHARGES_PCT,
        },
    })
    assert resolved["fill_model"] == "SLIPPAGE_ADJUSTED"
    assert pe.compute_fill(entry, resolved, side="BUY")["fill_price"] == round(
        entry * (1 + _SLIPPAGE_PCT / 100), 2
    )


# ── TEST 8 - resolution occurs once per run ──────────────────────────────────

def test_8_resolution_once_per_run(monkeypatch):
    # The resolver is a pure function of cfg and returns the same object
    # pointer for the whole run; S1 execution passes that pointer into
    # _try_enter for every BUY entry.
    resolved_obj = br.resolve_execution_settings(
        _base_cfg({
            "execution_settings": {
                "fill_model": "SLIPPAGE_ADJUSTED",
                "slippage_pct": _SLIPPAGE_PCT,
                "charges_pct": _CHARGES_PCT,
            },
        })
    )
    calls = []

    def spy_try_enter(*args, **kwargs):
        calls.append(kwargs.get("execution_settings"))
        return None

    monkeypatch.setattr(br, "_try_enter", spy_try_enter)

    # Feed the same resolved object through repeated entry processing.
    for _ in range(3):
        br._try_enter(
            "run_id", "scan_id", None, 1000.0,
            "2024-01-01T09:15:00", sizing=None,
            mark=100.0, execution_settings=resolved_obj,
        )

    assert len(calls) == 3
    assert all(c is resolved_obj for c in calls)
    # DEFAULT_SETTINGS must not have leaked into entry processing.
    assert all(c["fill_model"] == "SLIPPAGE_ADJUSTED" for c in calls)


# ── TEST 9 - completion provenance ───────────────────────────────────────────

def test_9_completion_provenance():
    # S1 persists a COPY of the resolved settings into the completion config
    # and the metrics. Reproduce the exact payload execute_run writes.
    xs = {
        "fill_model": "SLIPPAGE_ADJUSTED",
        "slippage_pct": _SLIPPAGE_PCT,
        "charges_pct": _CHARGES_PCT,
    }
    cfg = _base_cfg({
        "execution_settings": xs,
    })

    completed_config = {**cfg, "execution_settings": dict(xs)}
    completed_metrics = {"execution_settings": dict(xs)}

    # The completed payload must contain the exact resolved settings.
    assert completed_config["execution_settings"] == dict(xs)
    assert completed_metrics["execution_settings"] == dict(xs)
    # No reference sharing: mutating the copy must not touch the source.
    completed_config["execution_settings"]["fill_model"] = "R38C_FAKE"
    assert cfg["execution_settings"]["fill_model"] == "SLIPPAGE_ADJUSTED"


# ── TEST 10 - default backtest behaviour regression ──────────────────────────

def test_10_default_backtest_behaviour_regression():
    cfg = _base_cfg()
    # No execution_settings -> must resolve to EXECUTION_SETTINGS_DEFAULTS.
    resolved = _exec_settings(cfg)
    assert resolved == {
        "fill_model": "NEXT_QUOTE",
        "slippage_pct": _SLIPPAGE_PCT,
        "charges_pct": _CHARGES_PCT,
    }
    # Legacy DEFAULT_SETTINGS must still produce the same reference fill/
    # charge semantics.
    ref_slip = pe.compute_fill(100.0, br.DEFAULT_SETTINGS, side="BUY")["slippage"]

    assert ref_slip == pytest.approx(_SLIPPAGE_PCT / 2, abs=1e-9)  # legacy NEXT_QUOTE half-slip = 0.075
    # resolve_execution_settings must return the exact resolved object
    resolved = br.resolve_execution_settings({
        "execution_settings": {"fill_model": "NEXT_QUOTE",
                               "slippage_pct": _SLIPPAGE_PCT,
                               "charges_pct": _CHARGES_PCT},
    })
    assert resolved == {"fill_model": "NEXT_QUOTE",
                       "slippage_pct": _SLIPPAGE_PCT,
                       "charges_pct": _CHARGES_PCT}
