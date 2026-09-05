#!/usr/bin/env python3
"""Run the bounded, read-only Task976 benchmark on the authorized Zeabur DB.

Benchmark tooling only: this module imports no application or broker modules,
submits no orders, and never changes database rows or schema.
"""

from __future__ import annotations

import argparse
import os
import resource
import statistics
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping, Sequence

import task976_zeabur_fixture as fixture


MAX_ITERATIONS = 100_000
MAX_STATEMENT_TIMEOUT_MS = 30_000
MAX_WALL_SECONDS = 900
EXPECTED_TOKENS = tuple(range(900001, 900024))
FORBIDDEN_BROKER_MODULES = (
    "kiteconnect", "broker", "broker_adapter", "order_execution", "order_manager",
)

READ_QUERY = """SELECT symbol, instrument_token
FROM trading_universe_members
WHERE universe_id = 3 AND enabled IS TRUE
ORDER BY symbol"""


@dataclass(frozen=True)
class WorkloadConfig:
    iterations: int = 20_000
    statement_timeout_ms: int = 5_000
    max_seconds: int = 300


@dataclass(frozen=True)
class ExpectedEvidence:
    counts: Mapping[str, int]
    symbols: list[str]
    symbol_hash: str


@dataclass(frozen=True)
class Snapshot:
    table_counts: Mapping[str, int]
    exact_fixture: bool


@dataclass(frozen=True)
class Metrics:
    requested_operations: int
    total_operations: int
    successful_operations: int
    failed_operations: int
    throughput_ops_per_second: float
    min_ms: float
    average_ms: float
    median_ms: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float
    db_query_failures: int
    timeout_count: int
    memory_failures: int
    deadline_exceeded: bool


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def safe_error(exc: BaseException, database_url: str) -> str:
    return fixture.redact(exc, database_url)


def require_environment(env: Mapping[str, str]) -> fixture.AuthorizedUrl:
    fixture.require_ack(env)
    identity = fixture.validate_database_url(env.get("DATABASE_URL", "").strip())
    fixture.require_fixture_contract()
    fixture.require_paper_only(env)
    return identity


def require_preflight_identity(live: Mapping[str, Any]) -> None:
    fixture.require_live_identity(live)


def require_no_broker_modules() -> None:
    loaded = {
        name for name in sys.modules
        if any(name == prefix or name.startswith(prefix + ".")
               for prefix in FORBIDDEN_BROKER_MODULES)
    }
    if loaded:
        raise fixture.SafetyError("A broker/order module is loaded; benchmark refused")


def validate_workload(config: WorkloadConfig) -> None:
    if not 1 <= config.iterations <= MAX_ITERATIONS:
        raise fixture.SafetyError("iterations must be between 1 and 100000")
    if not 1 <= config.statement_timeout_ms <= MAX_STATEMENT_TIMEOUT_MS:
        raise fixture.SafetyError("statement timeout must be between 1 and 30000 ms")
    if not 1 <= config.max_seconds <= MAX_WALL_SECONDS:
        raise fixture.SafetyError("maximum duration must be between 1 and 900 seconds")


def require_benchmark_only_tokens(tokens: Sequence[int]) -> None:
    if tuple(sorted(int(token) for token in tokens)) != EXPECTED_TOKENS:
        raise fixture.SafetyError("Fixture contains a non-benchmark mapping token")


def require_exact_fixture(evidence: ExpectedEvidence, exact_fixture: bool) -> None:
    if not exact_fixture:
        raise fixture.SafetyError("Fixture is incomplete or conflicts with Task976")
    fixture.require_fixture_evidence(
        evidence.counts, evidence.symbols, evidence.symbol_hash
    )


def capture_snapshot(conn: Any) -> Snapshot:
    counts = fixture.public_table_counts(conn)
    exact = fixture.fixture_state_is_exact(conn, counts)
    return Snapshot(counts, exact)


def preflight(conn: Any) -> Snapshot:
    live = fixture.read_live_identity(conn)
    require_preflight_identity(live)
    snapshot = capture_snapshot(conn)
    counts, symbols, symbol_hash = fixture.fixture_evidence(conn)
    require_exact_fixture(ExpectedEvidence(counts, symbols, symbol_hash), snapshot.exact_fixture)
    rows = fixture._fetchall(conn, READ_QUERY)
    require_operation_result(rows)
    for table in fixture.AUTHORITY_TABLES:
        print(f"TASK976 fixture_row_count.{table}: {counts[table]}")
    print("TASK976 universe_key: CUSTOM_LOW_PRICE_SECTOR")
    print("TASK976 universe_id: 3")
    print("TASK976 universe_version: 1")
    print("TASK976 enabled_symbol_count: 23")
    print("TASK976 exact_symbol_set: PASS")
    print(f"TASK976 exact_set_hash: {symbol_hash}")
    print("TASK976 mapping_tokens_scope: BENCHMARK_ONLY_NON_BROKER")
    return snapshot


def require_operation_result(rows: Sequence[Sequence[Any]]) -> None:
    expected = sorted(
        (row[0], row[2]) for row in fixture.expected_member_rows()
    )
    actual = sorted((str(row[0]), int(row[1])) for row in rows)
    if actual != expected:
        raise fixture.SafetyError("Benchmark query did not return the exact fixture")
    require_benchmark_only_tokens([token for _symbol, token in actual])


def percentile_nearest_rank(values: Sequence[float], percentile: float) -> float:
    ordered = sorted(values)
    index = max(0, (int(percentile * len(ordered) + 0.999999999) - 1))
    return float(ordered[index])


def aggregate_metrics(
    latencies_ms: Sequence[float], *, wall_seconds: float,
    total_operations: int, failed_operations: int, db_failures: int,
    timeout_count: int, memory_failures: int, requested_operations: int | None = None,
    deadline_exceeded: bool = False,
) -> Metrics:
    if wall_seconds <= 0:
        raise fixture.SafetyError("Benchmark wall duration is invalid")
    values = [float(value) for value in latencies_ms]
    successful = len(values)
    requested = total_operations if requested_operations is None else requested_operations
    zero = 0.0
    return Metrics(
        requested_operations=requested,
        total_operations=total_operations,
        successful_operations=successful,
        failed_operations=failed_operations,
        throughput_ops_per_second=successful / wall_seconds,
        min_ms=min(values) if values else zero,
        average_ms=statistics.fmean(values) if values else zero,
        median_ms=statistics.median(values) if values else zero,
        p50_ms=percentile_nearest_rank(values, 0.50) if values else zero,
        p95_ms=percentile_nearest_rank(values, 0.95) if values else zero,
        p99_ms=percentile_nearest_rank(values, 0.99) if values else zero,
        max_ms=max(values) if values else zero,
        db_query_failures=db_failures, timeout_count=timeout_count,
        memory_failures=memory_failures, deadline_exceeded=deadline_exceeded,
    )


def require_post_run_integrity(before: Snapshot, after: Snapshot) -> int:
    if not after.exact_fixture:
        raise fixture.SafetyError("Post-run fixture integrity check failed")
    before_authority = {
        name: before.table_counts.get(name) for name in fixture.AUTHORITY_TABLES
    }
    after_authority = {
        name: after.table_counts.get(name) for name in fixture.AUTHORITY_TABLES
    }
    if before_authority != after_authority:
        raise fixture.SafetyError("Authority row counts changed during benchmark")
    return fixture.require_unrelated_tables_preserved(
        before.table_counts, after.table_counts
    )


def is_timeout(exc: BaseException) -> bool:
    return getattr(exc, "pgcode", None) == "57014" or "timeout" in str(exc).lower()


def run_queries(conn: Any, config: WorkloadConfig) -> tuple[Metrics, bool]:
    latencies: list[float] = []
    failures = db_failures = timeout_count = memory_failures = 0
    started = time.perf_counter()
    deadline = started + config.max_seconds
    attempted = 0
    deadline_exceeded = False
    for _ in range(config.iterations):
        if time.perf_counter() >= deadline:
            deadline_exceeded = True
            break
        attempted += 1
        operation_started = time.perf_counter()
        try:
            with conn.cursor() as cur:
                cur.execute(READ_QUERY)
                require_operation_result(cur.fetchall())
            latencies.append((time.perf_counter() - operation_started) * 1000.0)
        except MemoryError:
            memory_failures += 1
            failures += 1
            break
        except Exception as exc:
            failures += 1
            db_failures += 1
            timeout_count += int(is_timeout(exc))
            break
    wall = time.perf_counter() - started
    metrics = aggregate_metrics(
        latencies, wall_seconds=max(wall, 1e-12),
        requested_operations=config.iterations, total_operations=attempted,
        failed_operations=failures, db_failures=db_failures,
        timeout_count=timeout_count, memory_failures=memory_failures,
        deadline_exceeded=deadline_exceeded,
    )
    complete = attempted == config.iterations and failures == 0 and not deadline_exceeded
    return metrics, complete


def print_metrics(metrics: Metrics, start_utc: str, end_utc: str, wall_seconds: float) -> None:
    print(f"TASK976 benchmark_start_utc: {start_utc}")
    print(f"TASK976 benchmark_end_utc: {end_utc}")
    print(f"TASK976 wall_clock_seconds: {wall_seconds:.6f}")
    for name in (
        "requested_operations", "total_operations", "successful_operations", "failed_operations",
        "db_query_failures", "timeout_count", "memory_failures",
    ):
        print(f"TASK976 {name}: {getattr(metrics, name)}")
    print(f"TASK976 deadline_exceeded: {str(metrics.deadline_exceeded).lower()}")
    print(f"TASK976 throughput_ops_per_second: {metrics.throughput_ops_per_second:.3f}")
    for name in ("min_ms", "average_ms", "median_ms", "p50_ms", "p95_ms", "p99_ms", "max_ms"):
        print(f"TASK976 latency_{name}: {getattr(metrics, name):.6f}")


def execute(conn: Any, config: WorkloadConfig) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT set_config('statement_timeout', %s, false)",
            (str(config.statement_timeout_ms),),
        )
    before = preflight(conn)
    print("TASK976 fixture_integrity_before: PASS")
    start_utc = utc_now()
    wall_started = time.perf_counter()
    benchmark_error: BaseException | None = None
    metrics: Metrics | None = None
    complete = False
    try:
        metrics, complete = run_queries(conn, config)
    except Exception as exc:
        benchmark_error = exc
    wall_seconds = time.perf_counter() - wall_started
    end_utc = utc_now()
    after = capture_snapshot(conn)
    unrelated_count = require_post_run_integrity(before, after)
    counts, symbols, symbol_hash = fixture.fixture_evidence(conn)
    require_exact_fixture(ExpectedEvidence(counts, symbols, symbol_hash), after.exact_fixture)
    if metrics is not None:
        print_metrics(metrics, start_utc, end_utc, wall_seconds)
    print(f"TASK976 peak_rss_mib: {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0:.3f}")
    print("TASK976 fixture_integrity_after: PASS")
    print("TASK976 authority_row_counts_unchanged: PASS")
    print("TASK976 unrelated_tables_preserved: PASS")
    print(f"TASK976 unrelated_table_count: {unrelated_count}")
    if benchmark_error is not None:
        raise benchmark_error
    if not complete:
        raise fixture.SafetyError("Benchmark workload did not complete successfully")
    print("TASK976 benchmark_result: PASS")


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iterations", type=int, default=20_000)
    parser.add_argument("--statement-timeout-ms", type=int, default=5_000)
    parser.add_argument("--max-seconds", type=int, default=300)
    args = parser.parse_args(argv)
    config = WorkloadConfig(args.iterations, args.statement_timeout_ms, args.max_seconds)
    active_env = os.environ if env is None else env
    database_url = active_env.get("DATABASE_URL", "").strip()
    try:
        identity = require_environment(active_env)
        require_no_broker_modules()
        validate_workload(config)
        print("TASK976 action: RUN_BOUNDED_READ_ONLY_BENCHMARK")
        print(f"TASK976 host: {identity.host}")
        print(f"TASK976 port: {identity.port}")
        print(f"TASK976 database: {identity.database}")
        print(f"TASK976 user: {identity.user}")
        print("TASK976 safety.disposable_database_only: PASS")
        print("TASK976 safety.paper_only: PASS")
        print("TASK976 safety.broker_modules_imported: false")
        print("TASK976 safety.broker_credentials_read: false")
        print("TASK976 safety.orders_submitted: false")
        print("TASK976 safety.database_writes: false")
        print(f"TASK976 workload.iterations: {config.iterations}")
        print(f"TASK976 workload.statement_timeout_ms: {config.statement_timeout_ms}")
        print(f"TASK976 workload.max_seconds: {config.max_seconds}")
        print("TASK976: connecting for independent live gates (credentials redacted)")
        with fixture.psycopg2.connect(database_url, connect_timeout=10) as conn:
            conn.set_session(readonly=True, autocommit=True)
            live = fixture.read_live_identity(conn)
            require_preflight_identity(live)
            print(f"TASK976 PostgreSQL_major: {int(live['version_num']) // 10000}")
            print("TASK976 identity_gate: PASS")
            execute(conn, config)
        return 0
    except Exception as exc:
        print(f"TASK976 BENCHMARK FAILURE: {safe_error(exc, database_url)}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
