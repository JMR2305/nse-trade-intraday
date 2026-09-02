"""Observation-only clean-interpreter pytest collection/order experiments."""
import json
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / 'artifacts/api-server/src/python'
OUT = ROOT / 'task974-diagnostics'
CONSUMERS = [
    'test_phase11_live.py', 'test_phase12.py', 'test_phase15.py',
    'test_phase16.py', 'test_phase18.py', 'test_phase20.py', 'test_phase22.py',
    'test_phase22_final.py', 'test_phase9.py', 'test_seal_execution_outcomes.py',
    'test_signal_history.py', 'test_watchlist_persistence.py',
    'tests/test_balanced_decision.py', 'tests/test_macd_optimizer.py',
    'tests/test_macd_robustness.py', 'tests/test_strategy_audit.py',
    'tests/test_strategy_intelligence.py', 'tests/test_walk_forward_validator.py',
    'tests/unit/test_bootstrap_eligibility_change.py',
    'tests/unit/test_bootstrap_paper_trade.py',
    'tests/unit/test_portfolio_endpoint_contract.py',
]
WATCH = ['market_hours', 'paper_trader', 'phase20_executor', 'market_scanner',
         'config', 'signals_store', 'signals_cache', 'scan_state_store',
         'execution_quality', 'execution_quality.metrics', 'phase20_store']


def validate_environment():
    raw = os.environ.get('TASK967_TEST_DATABASE_URL', '')
    url = urlsplit(raw)
    if (url.scheme not in ('postgres', 'postgresql') or
        url.hostname not in ('localhost', '127.0.0.1', '::1') or
        url.path != '/task967_disposable_task968' or url.query or url.fragment):
        raise RuntimeError('Exact local disposable database URL required')
    os.environ['DATABASE_URL'] = raw


def metadata(name):
    obj = sys.modules.get(name)
    if obj is None:
        return None
    attrs = vars(obj)
    return {'identity': id(obj), 'type': type(obj).__name__,
            'file': str(attrs.get('__file__')), 'attributes': sorted(attrs)}


def child(output, paths):
    import pytest
    evidence = {'paths': paths, 'changes': [], 'errors': [], 'collected': 0}

    class Observer:
        @pytest.hookimpl(hookwrapper=True)
        def pytest_make_collect_report(self, collector):
            before = {name: metadata(name) for name in WATCH}
            result = yield
            after = {name: metadata(name) for name in WATCH}
            if isinstance(collector, pytest.Module):
                changed = {name: {'before': before[name], 'after': after[name]}
                           for name in WATCH if before[name] != after[name]}
                if changed:
                    evidence['changes'].append({'producer': str(collector.path), 'modules': changed})
                report = result.get_result()
                if report.failed:
                    evidence['errors'].append({'module': str(collector.path),
                                              'exception': report.longreprtext,
                                              'module_state': after})

        def pytest_collection_finish(self, session):
            evidence['collected'] = len(session.items)

    os.chdir(PY)
    sys.path.insert(0, str(PY))
    code = pytest.main(['--collect-only', '-q', *paths], plugins=[Observer()])
    evidence['exit_code'] = int(code)
    Path(output).write_text(json.dumps(evidence, indent=2) + '\n')
    return int(code)


def main():
    validate_environment()
    if len(sys.argv) > 1 and sys.argv[1] == '--child':
        return child(sys.argv[2], sys.argv[3:])
    OUT.mkdir(exist_ok=True)
    cases = [('broad', ['.'])]
    cases += [(f'alone-{i:02}', [path]) for i, path in enumerate(CONSUMERS)]
    for i, (producer, consumer) in enumerate([
        ('test_consecutive_blocks.py', 'test_phase12.py'),
        ('test_consecutive_blocks.py', 'test_phase11_live.py'),
        ('test_consecutive_blocks.py', 'test_phase20.py'),
        ('test_analytics_30plus_integration.py', 'tests/test_balanced_decision.py'),
    ]):
        cases.extend([(f'producer-first-{i}', [producer, consumer]),
                      (f'consumer-first-{i}', [consumer, producer])])
    summary = []
    for name, paths in cases:
        output = OUT / f'{name}.json'
        with (OUT / f'{name}.log').open('w') as log:
            try:
                result = subprocess.run([sys.executable, __file__, '--child', str(output), *paths],
                                        cwd=PY, stdout=log, stderr=subprocess.STDOUT, timeout=90)
                code = result.returncode
            except subprocess.TimeoutExpired:
                code = 'timeout'
        summary.append({'case': name, 'paths': paths, 'exit_code': code})
        print(json.dumps(summary[-1]), flush=True)
        if output.exists():
            data = json.loads(output.read_text())
            print('TASK974_CASE ' + json.dumps({
                'case': name, 'collected': data['collected'],
                'errors': [{'module': e['module'], 'exception': e['exception']}
                           for e in data['errors']],
                'changes': data['changes'],
            }), flush=True)
    (OUT / 'summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    # Diagnostic subprocess failures are evidence, not a passing test gate.
    # The existing unmodified broad pytest command still fails the workflow.
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
