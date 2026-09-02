# Task974 original collection failure matrix

Diagnostic commit: f19e22265bf5e1bf2ce99e7a21d6452497e15b13.
Run: https://github.com/JMR2305/nse-trade-intraday/actions/runs/33639711795

Captured before test/source corrections. Exact tracebacks and sys.modules before/after are in the task974-diagnostics CI artifact. Four producer-first pairs fail; all reversed pairs have zero collection errors. Nineteen consumers collect alone without errors; Phase9 repeats its IndexError; Phase22_final exposes a separate disposable sequence collision.

| # | Module | Original exception | Classification / producer | Alone |
|---|---|---|---|---|
| 1 | `test_phase11_live.py` | E   ImportError: cannot import name 'market_state' from 'market_hours' (unknown location). Did you mean: 'market_status'? | A: consecutive-block stub | No collection error |
| 2 | `test_phase12.py` | E   ImportError: cannot import name 'get_trades' from 'paper_trader' (unknown location) | A: consecutive-block stub | No collection error |
| 3 | `test_phase15.py` | E   ImportError: cannot import name 'estimate_broker_charges' from 'paper_trader' (unknown location) | A: consecutive-block stub | No collection error |
| 4 | `test_phase16.py` | E   ImportError: cannot import name 'get_trade_replay' from 'paper_trader' (unknown location) | A: consecutive-block stub | No collection error |
| 5 | `test_phase18.py` | E   AttributeError: module 'market_hours' has no attribute 'now_ist' | A: consecutive-block stub | No collection error |
| 6 | `test_phase20.py` | E   ImportError: cannot import name 'compute_fill' from 'phase20_executor' (unknown location) | A: consecutive-block stub | No collection error |
| 7 | `test_phase22.py` | E   KeyError: 'total_value' | A: consecutive-block stub | No collection error |
| 8 | `test_phase22_final.py` | E   ImportError: cannot import name '_final_action' from 'market_scanner' (unknown location) | A: ai_performance scanner stub | Different failure: fixture sequence collision |
| 9 | `test_phase9.py` | E   IndexError: list index out of range | B/D: untracked scan fixture | Same IndexError |
| 10 | `test_seal_execution_outcomes.py` | E   ImportError: cannot import name 'seal_execution_outcomes' from 'phase20_executor' (unknown location) | A: consecutive-block stub | No collection error |
| 11 | `test_signal_history.py` | E   ImportError: cannot import name 'execute_buy' from 'paper_trader' (unknown location) | A: consecutive-block stub | No collection error |
| 12 | `test_watchlist_persistence.py` | E   ImportError: cannot import name 'get_trades' from 'paper_trader' (unknown location) | A: consecutive-block stub | No collection error |
| 13 | `tests/test_balanced_decision.py` | E   ImportError: cannot import name '_final_action' from 'market_scanner' (unknown location) | A: ai_performance scanner stub | No collection error |
| 14 | `tests/test_macd_optimizer.py` | E   ImportError: cannot import name '_final_action' from 'market_scanner' (unknown location) | A: ai_performance scanner stub | No collection error |
| 15 | `tests/test_macd_robustness.py` | E   ImportError: cannot import name '_final_action' from 'market_scanner' (unknown location) | A: ai_performance scanner stub | No collection error |
| 16 | `tests/test_strategy_audit.py` | E   ImportError: cannot import name '_final_action' from 'market_scanner' (unknown location) | A: ai_performance scanner stub | No collection error |
| 17 | `tests/test_strategy_intelligence.py` | E   ImportError: cannot import name '_final_action' from 'market_scanner' (unknown location) | A: ai_performance scanner stub | No collection error |
| 18 | `tests/test_walk_forward_validator.py` | E   ImportError: cannot import name '_final_action' from 'market_scanner' (unknown location) | A: ai_performance scanner stub | No collection error |
| 19 | `tests/unit/test_bootstrap_eligibility_change.py` | E   ImportError: cannot import name '_final_action' from 'market_scanner' (unknown location) | A: ai_performance scanner stub | No collection error |
| 20 | `tests/unit/test_bootstrap_paper_trade.py` | E   ImportError: cannot import name 'run_bootstrap_auto_entry' from 'phase20_executor' (unknown location) | A: consecutive-block stub | No collection error |
| 21 | `tests/unit/test_portfolio_endpoint_contract.py` | E   ImportError: cannot import name 'get_trades' from 'paper_trader' (unknown location) | A: consecutive-block stub | No collection error |

The consecutive-block test installs partial market_hours, paper_trader and phase20_executor modules at import time without restoring them. The observed first producer is ai_performance/test_ai_performance.py, which installs a partial market_scanner module at import time. strategy_intelligence/test_strategy_intelligence.py and test_analytics_30plus_integration.py contain the same persistent installer; the latter also independently reproduces the producer/consumer order failure. Later from-imports therefore see fake modules rather than source modules. The incomplete portfolio stub also lacks total_value. Phase9 instead executes assertions at collection and assumes an untracked scan cache exists; no snapshot is recorded and an empty history is indexed.

Phase22_final's isolated collection additionally executes a runtime-universe bootstrap as a side effect of a busy-lock test. The Task974 test supplies an explicit authority context for that lock-only check and fails on attempted scan; catalog/native authority validation is unchanged.

No historical report has been rewritten. This is failed diagnostic evidence, not certification.

## Newly exposed failures (run 33640990363)

The focused producers/restoration regressions passed 151 tests in 4.64 seconds. The unchanged broad command then reached two new errors and a fatal import-time SystemExit:

- test_phase16.py: ValueError converting MagicMock INITIAL_CAPITAL to Excel.
- test_phase17.py: TypeError comparing a MagicMock drift with float.
- test_phase18.py: SystemExit(0) after 26 successful checks, aborting pytest collection.

The observer identifies test_event_intelligence.py as the first config MagicMock installer. test_macro_intelligence.py repeats that installer, while test_explainable_ai.py installs or mutates config/signals modules during collection. test_research_lab.py overwrites signals_store and several real package names with MagicMock objects; this was also observed in the original module-state trace. These test-only installers are now scoped with per-test restoration, including feature flags. Phase18 checks are moved into a test function and their failure count remains an assertion. No passing assertion was removed.

## Remaining producer trace (run 33642007379)

The expanded focused suite passed 506 tests in 8.36 seconds. Broad collection then reported 10 errors, all caused by two remaining stub families:

- portfolio_performance/test_portfolio_performance.py installed a partial market_scanner module; this caused eight _final_action import errors.
- tests/buy_audit_test.py, tests/test_eod_reconciliation.py, tests/test_phase20_startup_overnight_check.py, and tests/unit/test_size_reduced_to_cap.py replaced real market_hours, phase20_executor, phase20_store, and scan_state_store modules during collection; this caused the bootstrap executor and portfolio endpoint errors.

Each identified unit-test producer now installs its existing doubles only inside an autouse test fixture and restores the complete sys.modules state. Tests whose SUT binds dependencies at import receive a fresh SUT inside that scoped fixture. The regression runs every producer twice and proves both stub behavior and exact module-object restoration.
