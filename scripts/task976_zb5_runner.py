#!/usr/bin/env python3
"""Guarded, bounded, read-only Task976 ZB5 application-capacity runner."""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import signal
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import task976_zeabur_fixture as fixture

SafetyError = fixture.SafetyError
SAFETY_FLAGS = ("AUTO_EXECUTION_ENABLED", "LIVE_ORDERS_ENABLED",
    "CONTROLLED_PAPER_ENTRY_ENABLED", "BOOTSTRAP_PAPER_ENABLED",
    "AUTO_PAPER_ENTRIES", "TASK976_EXECUTION_ALLOWED")
EXPECTED_TOKENS = list(range(900001, 900024))
DB_SESSION_OPTIONS = "-c default_transaction_read_only=on -c statement_timeout=5000"
READ_ONLY_SQL = "SELECT current_database(); SELECT count(*) FROM public tables"


class DeadlineExceeded(SafetyError): pass


@dataclass(frozen=True)
class TierConfig:
    tier: int; name: str; workload_duration_s: int; requests: int
    concurrency: int; scanner_workers: int; internal_deadline_s: int; shell_timeout_s: int


def tier_config(tier: int) -> TierConfig:
    values = {1: TierConfig(1, "NORMAL", 120, 240, 2, 1, 180, 240),
              2: TierConfig(2, "PEAK", 120, 720, 6, 2, 240, 300),
              3: TierConfig(3, "HEADROOM", 90, 1080, 10, 3, 240, 300)}
    try: return values[int(tier)]
    except (KeyError, TypeError, ValueError) as exc:
        raise SafetyError("tier must be exactly 1, 2, or 3") from exc


class DeadlineTimer:
    """Whole-run POSIX timer, armed before the lifecycle callback begins."""
    def __init__(self, seconds: int): self.seconds = seconds; self.old = None
    def __enter__(self):
        def expire(_signal, _frame): raise DeadlineExceeded("whole-run deadline exceeded")
        self.old = signal.signal(signal.SIGALRM, expire)
        signal.setitimer(signal.ITIMER_REAL, self.seconds)
        return self
    def __exit__(self, *_args):
        signal.setitimer(signal.ITIMER_REAL, 0)
        if self.old is not None: signal.signal(signal.SIGALRM, self.old)


def execute_with_deadline(tier: int, lifecycle: Callable[[], Any],
                          *, timer_factory: Callable = DeadlineTimer) -> Any:
    with timer_factory(tier_config(tier).internal_deadline_s):
        return lifecycle()


def future_shell_command(tier: int) -> str:
    config = tier_config(tier)
    return ("TASK976_DISPOSABLE_ACK=apexquant_disposable "
            "AUTO_EXECUTION_ENABLED=false LIVE_ORDERS_ENABLED=false "
            "CONTROLLED_PAPER_ENTRY_ENABLED=false BOOTSTRAP_PAPER_ENABLED=false "
            "AUTO_PAPER_ENTRIES=false TASK976_EXECUTION_ALLOWED=false "
            f"timeout --signal=TERM --kill-after=10s {config.shell_timeout_s}s "
            f".venv/bin/python3 scripts/task976_zb5_runner.py --tier {tier}")


def require_environment(env: Mapping[str, str]) -> fixture.AuthorizedUrl:
    fixture.require_ack(env); identity = fixture.validate_database_url(env.get("DATABASE_URL", ""))
    fixture.require_fixture_contract(); fixture.require_paper_only(env)
    wrong = [name for name in SAFETY_FLAGS if env.get(name, "").lower() != "false"]
    if wrong: raise SafetyError("execution flags must be explicitly false: " + ", ".join(wrong))
    return identity


def require_live_identity(evidence: Mapping[str, Any]) -> None: fixture.require_live_identity(evidence)


def expected_fixture_evidence() -> dict[str, Any]:
    return {"universe_key": "CUSTOM_LOW_PRICE_SECTOR", "universe_id": 3, "version": 1,
            "symbols": sorted(fixture.task969.SYMBOLS),
            "exact_set_hash": fixture.task969.APPROVED_SET_HASH,
            "tokens": EXPECTED_TOKENS.copy(),
            "mappings": sorted((str(row[0]), int(row[2])) for row in fixture.expected_member_rows()),
            "authority_counts": dict(fixture.EXPECTED_FIXTURE_COUNTS)}


def require_fixture(value: Mapping[str, Any]) -> None:
    expected = expected_fixture_evidence()
    for key in expected:
        actual, wanted = value.get(key), expected[key]
        if key in {"symbols", "tokens"}: actual, wanted = sorted(actual or []), sorted(wanted)
        if actual != wanted: raise SafetyError(f"fixture {key} mismatch")
    fixture.require_fixture_evidence(value["authority_counts"], value["symbols"],
                                     value["exact_set_hash"])


def redact(value: Any, database_url: str = "") -> str: return fixture.redact(value, database_url)


def safe_child_environments(env: Mapping[str, str], shadow: Path) -> tuple[dict[str, str], dict[str, str]]:
    base = {k: v for k, v in env.items() if k in {"PATH", "LANG", "LC_ALL", "TZ",
            "SSL_CERT_FILE", "SSL_CERT_DIR"}}
    node = {**base, "DATABASE_URL": env["DATABASE_URL"], "PORT": "19776",
            "PYTHONPATH": str(shadow), "PGOPTIONS": DB_SESSION_OPTIONS,
            **{name: "false" for name in SAFETY_FLAGS}}
    worker = {**base, "PYTHONPATH": str(shadow)}
    return node, worker


def require_local_url(url: str) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise SafetyError("only loopback shadow HTTP is permitted")


def public_table_fingerprints(conn: Any) -> dict[str, tuple[int, str]]:
    tables = fixture._fetchall(conn, "SELECT tablename FROM pg_catalog.pg_tables WHERE schemaname='public' ORDER BY tablename")
    result = {}
    for (raw,) in tables:
        name = str(raw); quoted = fixture._quote_identifier(name)
        row = fixture._fetchall(conn, f"SELECT count(*), COALESCE(md5(string_agg(md5(t::text),'' ORDER BY md5(t::text))),md5('')) FROM {quoted} t")[0]
        result[name] = (int(row[0]), str(row[1]))
    return result


def require_fingerprints_preserved(before: Mapping, after: Mapping) -> None:
    if dict(before) != dict(after): raise SafetyError("public table content mutation detected")


def read_db_observation(conn: Any) -> dict[str, float | int]:
    capacity = fixture._fetchall(conn, """SELECT count(*),
        current_setting('max_connections')::int FROM pg_stat_activity
        WHERE datname=current_database() GROUP BY current_setting('max_connections')""")
    locks = fixture._fetchall(conn, """SELECT COALESCE(max(EXTRACT(epoch FROM
        clock_timestamp()-query_start)),0) FROM pg_stat_activity
        WHERE datname=current_database() AND wait_event_type='Lock'""")
    if len(capacity) != 1 or len(locks) != 1 or len(capacity[0]) != 2:
        raise SafetyError("required database capacity/lock evidence unavailable")
    connections, maximum = int(capacity[0][0]), int(capacity[0][1])
    if maximum <= 0: raise SafetyError("invalid max_connections evidence")
    return {"connections": connections, "max_connections": maximum,
            "connection_fraction": connections / maximum,
            "max_lock_wait_s": float(locks[0][0])}


class DatabasePeakEvidence:
    """Aggregate workload-time DB capacity/lock peaks; missing data is fatal."""
    def __init__(self):
        self.samples = 0; self.peak_connection_fraction = 0.0; self.max_lock_wait_s = 0.0
    def observe(self, observation: Mapping[str, float | int]) -> None:
        try:
            fraction = float(observation["connection_fraction"])
            lock_wait = float(observation["max_lock_wait_s"])
        except (KeyError, TypeError, ValueError) as exc:
            raise SafetyError("invalid database peak evidence") from exc
        if not (0 <= fraction <= 1) or lock_wait < 0:
            raise SafetyError("invalid database peak evidence")
        self.samples += 1
        self.peak_connection_fraction = max(self.peak_connection_fraction, fraction)
        self.max_lock_wait_s = max(self.max_lock_wait_s, lock_wait)
    def require_complete(self) -> tuple[float, float]:
        if self.samples < 1: raise SafetyError("database peak evidence unavailable")
        return self.peak_connection_fraction, self.max_lock_wait_s


class DatabaseSampler:
    """Continuously observe the disposable DB in a separate read-only session."""
    def __init__(self, database_url: str):
        self.database_url = database_url; self.stop_event = threading.Event()
        self.evidence = DatabasePeakEvidence(); self.error: Exception | None = None
        self.thread = threading.Thread(target=self._run, daemon=True)
    def _run(self) -> None:
        conn = None
        try:
            conn = fixture.psycopg2.connect(self.database_url, connect_timeout=5,
                                            options=DB_SESSION_OPTIONS)
            with conn.cursor() as cur: cur.execute("SET TRANSACTION READ ONLY")
            require_live_identity(fixture.read_live_identity(conn))
            while not self.stop_event.is_set():
                self.evidence.observe(read_db_observation(conn))
                if self.stop_event.wait(.2): break
        except Exception as exc:
            self.error = exc
        finally:
            if conn is not None:
                try: conn.rollback()
                finally: conn.close()
    def start(self) -> None: self.thread.start()
    def stop(self) -> tuple[float, float]:
        self.stop_event.set(); self.thread.join(6)
        if self.thread.is_alive(): raise SafetyError("database sampler did not drain")
        if self.error is not None: raise SafetyError("database sampler failed") from self.error
        return self.evidence.require_complete()


def latency_increasing(values: list[float]) -> bool:
    if len(values) < 4: return False
    width = max(1, len(values) // 4)
    return statistics.fmean(values[-width:]) > statistics.fmean(values[:width]) * 1.25


def next_pressure_streak(previous: float, above: bool, elapsed: float) -> float:
    return previous + elapsed if above else 0.0


def _key_values(text: str | None) -> dict[str, int]:
    if not text: return {}
    try: return {key: int(value) for key, value in (line.split() for line in text.splitlines())}
    except (ValueError, TypeError): return {}


def memory_failure_delta(before: Mapping[str, int], after: Mapping[str, int]) -> int:
    return sum(max(0, int(after.get(key, 0)) - int(before.get(key, 0)))
               for key in ("oom", "oom_kill"))


def memory_events_valid(events: Mapping[str, int]) -> bool:
    return all(key in events and isinstance(events[key], int) and events[key] >= 0
               for key in ("oom", "oom_kill"))


def require_process_drain(node_drained: bool, active_children: int) -> None:
    if not node_drained or active_children: raise SafetyError("child/request drain incomplete")


def require_worker_evidence(rows: list[Mapping[str, Any]], config: TierConfig) -> None:
    expected_bars = 504 if config.tier == 3 else 252
    if len(rows) != config.scanner_workers: raise SafetyError("worker evidence count mismatch")
    for row in rows:
        if (row.get("tier") != config.tier or row.get("symbols_processed") != 23 or
                row.get("bars_per_symbol") != expected_bars or
                row.get("symbol_hash") != fixture.task969.APPROVED_SET_HASH or
                row.get("provider_calls") != 0 or row.get("broker_calls") != 0 or
                row.get("orders_submitted") != 0 or
                not 0 < float(row.get("duration_seconds", -1)) <= 75 or
                int(row.get("lab_walk_calls", 0)) <= 0):
            raise SafetyError("invalid or unsafe worker evidence")


@dataclass(frozen=True)
class Metrics:
    tier: int = 1; request_error_rate: float = 0; timeout_rate: float = 0
    event_loop_p99_ms: float = 100; event_loop_unresponsive_s: float = 0
    sustained_lag_s: float = 0; memory_fraction: float = .5; memory_over_85_s: float = 0
    cpu_over_180_s: float = 0; latency_increasing: bool = False; backlog_increasing: bool = False
    max_worker_duration_s: float = 10; db_connection_fraction: float = .1
    db_lock_wait_s: float = 0; db_errors: int = 0; safety_violations: int = 0
    unexpected_mutations: int = 0; resource_metrics_ok: bool = True
    node_probe_ok: bool = True; process_drained: bool = True; oom_events: int = 0


@dataclass(frozen=True)
class Verdict: level: str; reasons: tuple[str, ...]


def synthetic_metrics(**updates: Any) -> Metrics:
    values = asdict(Metrics()); values.update(updates); return Metrics(**values)


def evaluate(m: Metrics) -> Verdict:
    fail, warn = [], []
    if (m.safety_violations or m.unexpected_mutations or m.db_errors or m.oom_events or
            not m.resource_metrics_ok or not m.node_probe_ok or not m.process_drained):
        fail.append("safety/resource evidence failure")
    limit = .02 if m.tier == 3 else .01
    if m.request_error_rate > limit or m.timeout_rate > limit: fail.append("HTTP failure threshold")
    elif m.request_error_rate or m.timeout_rate: warn.append("non-zero HTTP failures")
    if m.event_loop_unresponsive_s >= 5 or m.event_loop_p99_ms > 500 or m.sustained_lag_s >= 10:
        fail.append("event-loop threshold")
    elif m.event_loop_p99_ms >= 250: warn.append("event-loop headroom")
    if m.memory_over_85_s >= 5: fail.append("memory pressure threshold")
    elif m.memory_fraction >= .75: warn.append("memory headroom")
    if m.cpu_over_180_s > 30 and m.latency_increasing and m.backlog_increasing:
        fail.append("CPU/backlog threshold")
    elif m.cpu_over_180_s > 30: warn.append("CPU saturation without correlated degradation")
    if m.max_worker_duration_s > 75: fail.append("worker duration threshold")
    if m.db_connection_fraction > .70 or m.db_lock_wait_s > 2: fail.append("database capacity/lock threshold")
    return Verdict("FAIL" if fail else "WARN" if warn else "PASS", tuple(fail + warn))


def _cgroup_value(name: str) -> str | None:
    try: return (Path("/sys/fs/cgroup") / name).read_text().strip()
    except OSError: return None


class ResourceSampler:
    def __init__(self):
        self.stop_event = threading.Event(); self.peak_memory = 0; self.memory_over_85_s = 0
        self.cpu_over_180_s = 0; self.ok = True; self.thread = threading.Thread(target=self._run, daemon=True)
    def _run(self):
        prior_t, prior_cpu = time.monotonic(), None
        memory_streak = cpu_streak = 0.0
        while not self.stop_event.wait(.1):
            now = time.monotonic(); current = _cgroup_value("memory.current"); maximum = _cgroup_value("memory.max")
            cpu_text = _cgroup_value("cpu.stat")
            try:
                memory, cap = int(current), int(maximum); self.peak_memory = max(self.peak_memory, memory)
                memory_streak = next_pressure_streak(memory_streak, memory / cap > .85, now-prior_t)
                self.memory_over_85_s = max(self.memory_over_85_s, memory_streak)
                usage = int(dict(line.split() for line in cpu_text.splitlines())["usage_usec"])
                over_cpu = prior_cpu is not None and (usage-prior_cpu)/1e6/(now-prior_t) > 1.8
                cpu_streak = next_pressure_streak(cpu_streak, over_cpu, now-prior_t)
                self.cpu_over_180_s = max(self.cpu_over_180_s, cpu_streak)
                prior_cpu = usage
            except (TypeError, ValueError, KeyError, ZeroDivisionError): self.ok = False
            prior_t = now
    def start(self): self.thread.start()
    def stop(self): self.stop_event.set(); self.thread.join(1)


def cleanup_process(proc: Any) -> bool:
    if proc is None or proc.poll() is not None: return True
    proc.terminate()
    try: proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()
        try: proc.wait(timeout=2)
        except subprocess.TimeoutExpired: return False
    return True


def _write_shadow_dispatcher(root: Path) -> Path:
    directory = root / "python"; directory.mkdir()
    source = '''import json, os, sys\nimport psycopg2\nQUERIES={"ops_centre_platform":"SELECT count(*) FROM pipeline_events","portfolio_snapshot":"SELECT count(*) FROM pg_catalog.pg_tables WHERE schemaname='public'","phase20_ledger":"SELECT count(*) FROM pg_catalog.pg_stat_user_tables","universe_custom_status":"SELECT count(*) FROM trading_universes","universe_custom_symbols":"SELECT count(*) FROM trading_universe_members WHERE universe_id=3"}\ncommand=sys.argv[1] if len(sys.argv)>1 else ""\nif command not in QUERIES: raise SystemExit(2)\nconn=psycopg2.connect(os.environ["DATABASE_URL"],connect_timeout=5,options="-c default_transaction_read_only=on -c statement_timeout=5000")\ntry:\n with conn.cursor() as cur:\n  cur.execute("SET TRANSACTION READ ONLY")\n  cur.execute(QUERIES[command]); value=cur.fetchone()[0]\n print(json.dumps({"shadow":True,"rows":int(value)}))\nfinally:\n conn.rollback(); conn.close()\n'''
    (directory / "main.py").write_text(source); return directory


def _read_fixture(conn: Any) -> dict[str, Any]:
    public_counts = fixture.public_table_counts(conn)
    if not fixture.fixture_state_is_exact(conn, public_counts):
        raise SafetyError("exact fixture ownership/content gate failed")
    counts, symbols, hash_value = fixture.fixture_evidence(conn)
    rows = fixture._fetchall(conn, """SELECT u.universe_key,u.id,u.version,m.symbol,m.instrument_token
        FROM trading_universes u JOIN trading_universe_members m ON m.universe_id=u.id
        WHERE u.id=3 AND m.enabled IS TRUE ORDER BY m.symbol""")
    if len(rows) != 23: raise SafetyError("joined fixture mapping evidence incomplete")
    identity = {(str(row[0]), int(row[1]), int(row[2])) for row in rows}
    if identity != {("CUSTOM_LOW_PRICE_SECTOR", 3, 1)}:
        raise SafetyError("live universe identity/version mismatch")
    mappings = sorted((str(row[3]), int(row[4])) for row in rows)
    evidence = expected_fixture_evidence(); evidence.update(authority_counts=counts,
        symbols=symbols, exact_set_hash=hash_value, tokens=[token for _, token in mappings],
        mappings=mappings)
    require_fixture(evidence); return evidence


def run_live(tier: int, env: Mapping[str, str]) -> dict[str, Any]:
    config = tier_config(tier); identity = require_environment(env); conn = None; node = None; workers = []
    db_sampler = None
    sampler = ResourceSampler(); memory_events_before = _key_values(_cgroup_value("memory.events"))
    sampler.start(); started = time.monotonic(); started_utc = datetime.now(timezone.utc).isoformat()
    try:
        conn = fixture.psycopg2.connect(env["DATABASE_URL"], connect_timeout=5, options=DB_SESSION_OPTIONS)
        with conn.cursor() as cur: cur.execute("SET TRANSACTION READ ONLY")
        require_live_identity(fixture.read_live_identity(conn)); before_fixture = _read_fixture(conn)
        db_before = read_db_observation(conn)
        db_sampler = DatabaseSampler(env["DATABASE_URL"]); db_sampler.start()
        before = public_table_fingerprints(conn)
        with tempfile.TemporaryDirectory(prefix="task976-zb5-") as temp:
            root = Path(temp); py_dir = _write_shadow_dispatcher(root); node_env, worker_env = safe_child_environments(env, root)
            evidence_path = root / "node.json"; node_env.update({"TASK976_ZB5_NODE_EVIDENCE": str(evidence_path),
                "TASK976_ZB5_PYTHON_DIR": str(py_dir), "TASK976_ZB5_PYTHON_BIN": sys.executable})
            script = Path(__file__).with_name("task976_zb5_node_probe.mjs")
            node = subprocess.Popen(["node", str(script)], env=node_env, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL, text=True)
            worker_script = Path(__file__).with_name("task976_zb5_worker.py")
            for _ in range(config.scanner_workers):
                workers.append(subprocess.Popen([sys.executable, str(worker_script), "--tier", str(tier)],
                    env=worker_env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True))
            ready = False
            for _ in range(50):
                try:
                    with urllib.request.urlopen("http://127.0.0.1:19776/api/healthz", timeout=.5) as r: ready = r.status == 200
                    if ready: break
                except Exception: time.sleep(.1)
            if not ready: raise SafetyError("shadow Node readiness failure")
            paths = ("/api/healthz", "/api/ops-centre/platform", "/api/portfolio/snapshot",
                     "/api/phase20/ledger", "/api/universe/custom/status", "/api/universe/custom/symbols")
            workload_start = time.monotonic(); results = []
            def request(index: int):
                url = "http://127.0.0.1:19776" + paths[index % len(paths)]; require_local_url(url); tick = time.perf_counter()
                try:
                    with urllib.request.urlopen(url, timeout=5) as response: response.read(65536); return response.status, time.perf_counter()-tick, False
                except TimeoutError: return None, time.perf_counter()-tick, True
                except Exception: return None, time.perf_counter()-tick, False
            with concurrent.futures.ThreadPoolExecutor(config.concurrency) as pool:
                futures = []
                for index in range(config.requests):
                    futures.append(pool.submit(request, index)); target = workload_start + (index+1)*config.workload_duration_s/config.requests
                    if target > time.monotonic(): time.sleep(target-time.monotonic())
                results = [future.result(timeout=6) for future in futures]
            db_peak_connection, db_peak_lock = db_sampler.stop(); db_sampler = None
            worker_data = []; crashes = 0
            for proc in workers:
                try: out, err = proc.communicate(timeout=75)
                except subprocess.TimeoutExpired:
                    cleanup_process(proc); crashes += 1; continue
                if proc.returncode or err: crashes += 1
                elif out: worker_data.append(json.loads(out))
            require_worker_evidence(worker_data, config)
            node.send_signal(signal.SIGUSR2); time.sleep(.2)
            node_data = json.loads(evidence_path.read_text()) if evidence_path.exists() else {}
            drained = cleanup_process(node); node = None
            require_process_drain(drained and all(proc.poll() is not None for proc in workers),
                                  int(node_data.get("active_children", -1)))
        after = public_table_fingerprints(conn); after_fixture = _read_fixture(conn)
        db_after = read_db_observation(conn)
        require_fingerprints_preserved(before, after)
        if before_fixture != after_fixture: raise SafetyError("fixture postflight mismatch")
        sampler.stop(); memory_max = _cgroup_value("memory.max")
        memory_events_after = _key_values(_cgroup_value("memory.events"))
        if not sampler.ok or not memory_max or memory_max == "max": resource_ok, memory_fraction = False, 0
        else: resource_ok, memory_fraction = True, sampler.peak_memory / int(memory_max)
        resource_ok = (resource_ok and memory_events_valid(memory_events_before) and
                       memory_events_valid(memory_events_after))
        failures = sum(status is None or status >= 400 for status, _, _ in results)
        timeouts = sum(timeout for _, _, timeout in results); latencies = [duration*1000 for _, duration, _ in results]
        max_worker = max((float(row["duration_seconds"]) for row in worker_data), default=999 if crashes else 0)
        metrics = Metrics(tier=tier, request_error_rate=failures/len(results), timeout_rate=timeouts/len(results),
            event_loop_p99_ms=float(node_data.get("event_loop_p99_ms", 9999)),
            event_loop_unresponsive_s=float(node_data.get("event_loop_max_ms", 9999))/1000,
            sustained_lag_s=float(node_data.get("sustained_lag_ms", 9999))/1000,
            memory_fraction=memory_fraction, memory_over_85_s=sampler.memory_over_85_s,
            cpu_over_180_s=sampler.cpu_over_180_s, latency_increasing=latency_increasing(latencies),
            backlog_increasing=int(node_data.get("max_active_children", 9999)) > config.concurrency,
            max_worker_duration_s=max_worker,
            db_connection_fraction=max(float(db_before["connection_fraction"]), db_peak_connection,
                                       float(db_after["connection_fraction"])),
            db_lock_wait_s=max(float(db_before["max_lock_wait_s"]), db_peak_lock,
                               float(db_after["max_lock_wait_s"])),
            resource_metrics_ok=resource_ok and bool(node_data), node_probe_ok=bool(node_data), process_drained=drained,
            oom_events=memory_failure_delta(memory_events_before, memory_events_after),
            safety_violations=crashes)
        verdict = evaluate(metrics)
        return {"benchmark":"TASK976-ZB5", "tier":config.name, "start_utc":started_utc,
            "end_utc":datetime.now(timezone.utc).isoformat(), "wall_seconds":time.monotonic()-started,
            "requests":len(results), "errors":failures, "timeouts":timeouts,
            "throughput_rps":len(results)/(time.monotonic()-workload_start),
            "latency_min_ms":min(latencies), "latency_average_ms":statistics.fmean(latencies),
            "latency_p50_ms":statistics.median(latencies), "latency_p95_ms":sorted(latencies)[int(.95*(len(latencies)-1))],
            "latency_p99_ms":sorted(latencies)[int(.99*(len(latencies)-1))], "latency_max_ms":max(latencies),
            "node":node_data, "workers":worker_data, "memory_peak_bytes":sampler.peak_memory,
            "database_before":db_before, "database_after":db_after,
            "database_peak":{"connection_fraction":db_peak_connection,
                             "max_lock_wait_s":db_peak_lock},
            "fixture_integrity":"PASS", "public_tables_preserved":"PASS", "database_writes":0,
            "broker_orders":0, "provider_calls":0, "identity":{"host":identity.host,"port":identity.port,
            "database":identity.database,"user":identity.user,"postgresql_major":16}, "verdict":verdict.level,
            "reasons":verdict.reasons}
    finally:
        # Nested finally blocks ensure one deadline exception cannot skip later
        # drain, sampler, rollback, or close steps. Every wait is itself bounded;
        # a one-shot deadline seen here is preserved and re-raised after cleanup.
        cleanup_deadline = None
        try:
            for proc in workers:
                try: cleanup_process(proc)
                except DeadlineExceeded as exc: cleanup_deadline = cleanup_deadline or exc
        finally:
            try:
                try:
                    cleanup_process(node)
                except DeadlineExceeded as exc: cleanup_deadline = cleanup_deadline or exc
            finally:
                try:
                    try:
                        if db_sampler is not None: db_sampler.stop()
                    except DeadlineExceeded as exc: cleanup_deadline = cleanup_deadline or exc
                finally:
                    try: sampler.stop()
                    finally:
                        if conn is not None:
                            try: conn.rollback()
                            finally: conn.close()
        if cleanup_deadline is not None: raise cleanup_deadline


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--tier", type=int, choices=(1,2,3), required=True)
    return parser


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    args = build_parser().parse_args(argv); active = os.environ if env is None else env
    try:
        result = execute_with_deadline(args.tier, lambda: run_live(args.tier, active))
        print(json.dumps(result, sort_keys=True)); return 0 if result["verdict"] in {"PASS","WARN"} else 1
    except Exception as exc:
        print("TASK976-ZB5 result: FAIL\nTASK976-ZB5 error: " + redact(exc, active.get("DATABASE_URL", "")), file=sys.stderr); return 1


if __name__ == "__main__": raise SystemExit(main())
