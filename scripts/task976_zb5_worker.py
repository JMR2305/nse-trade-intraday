#!/usr/bin/env python3
"""Provider-free deterministic scanner worker for Task976 ZB5."""
from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import math
import os
import resource
import signal
import socket
import sys
import time
import types
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

sys.path.insert(0, str(Path(__file__).resolve().parent))
import task976_zeabur_fixture as fixture

AUTHORIZED_DB_HOST = fixture.AUTHORIZED_HOST
CANONICAL_SYMBOLS = tuple(sorted(fixture.task969.SYMBOLS))
CANONICAL_HASH = fixture.task969.APPROVED_SET_HASH
FORBIDDEN_MODULES = ("kiteconnect", "broker_client", "kite_quote_provider",
                     "kite_ltp_overlay", "backtest_data_bridge")
FORBIDDEN_CALLABLES = frozenset({"execute_buy", "execute_sell", "place_order",
    "run_backtest", "run_strategy_lab", "scheduled_scan_tick", "alert_queue_process"})


class WorkerSafetyError(RuntimeError): pass
class ExternalAccessBlocked(WorkerSafetyError): pass


def worker_plan(tier: int) -> tuple[int, int]:
    try: return {1: (252, 75), 2: (252, 75), 3: (504, 75)}[int(tier)]
    except (KeyError, TypeError, ValueError) as exc:
        raise WorkerSafetyError("tier must be exactly 1, 2, or 3") from exc


def require_exact_symbols(symbols: Iterable[str]) -> None:
    normalized = tuple(sorted(str(s).strip().upper() for s in symbols))
    if normalized != CANONICAL_SYMBOLS or fixture.exact_set_hash(normalized) != CANONICAL_HASH:
        raise WorkerSafetyError("exact Task969 symbol set/hash required")


def require_no_forbidden_modules() -> None:
    bad = [name for name in sys.modules
           if any(name == prefix or name.startswith(prefix + ".") for prefix in FORBIDDEN_MODULES)]
    if bad: raise WorkerSafetyError("broker/backtest-lifecycle module loaded")


def require_safe_callable(name: str) -> None:
    if name in FORBIDDEN_CALLABLES: raise WorkerSafetyError(f"forbidden callable: {name}")


def safe_worker_environment(env: Mapping[str, str]) -> dict[str, str]:
    return {key: value for key, value in env.items()
            if key in {"PATH", "LANG", "LC_ALL", "TZ", "PYTHONPATH",
                       "SSL_CERT_FILE", "SSL_CERT_DIR"}}


def install_provider_stubs() -> None:
    def blocked(*_args: Any, **_kwargs: Any):
        raise ExternalAccessBlocked("external provider disabled")
    yf = types.ModuleType("yfinance")
    yf.download = blocked; yf.Ticker = blocked; yf.__task976_stub__ = True
    sys.modules["yfinance"] = yf


def require_allowed_destination(address: Any) -> None:
    if not isinstance(address, tuple): raise ExternalAccessBlocked("socket blocked")
    host, port = str(address[0]).lower(), int(address[1])
    if host in {"127.0.0.1", "localhost", "::1"}: return
    if host == AUTHORIZED_DB_HOST and port == fixture.AUTHORIZED_PORT: return
    raise ExternalAccessBlocked("external socket destination blocked")


@contextmanager
def forbidden_callable_guard():
    """Stop forbidden Python callables before their first body instruction."""
    previous = sys.getprofile()
    def guard(frame: Any, event: str, arg: Any):
        if event == "call" and frame.f_code.co_name in FORBIDDEN_CALLABLES:
            raise WorkerSafetyError(f"forbidden callable reached: {frame.f_code.co_name}")
        if previous is not None: previous(frame, event, arg)
    sys.setprofile(guard)
    try: yield
    finally: sys.setprofile(previous)


@contextmanager
def network_guard():
    old_connect = socket.socket.connect
    old_connect_ex = socket.socket.connect_ex
    old_create = socket.create_connection
    old_sendto = socket.socket.sendto
    old_sendmsg = getattr(socket.socket, "sendmsg", None)
    def connect(sock: socket.socket, address: Any):
        require_allowed_destination(address); return old_connect(sock, address)
    def connect_ex(sock: socket.socket, address: Any):
        require_allowed_destination(address); return old_connect_ex(sock, address)
    def create(address: Any, *args: Any, **kwargs: Any):
        require_allowed_destination(address); return old_create(address, *args, **kwargs)
    def sendto(sock: socket.socket, data: Any, *args: Any):
        if not args: raise ExternalAccessBlocked("datagram destination missing")
        require_allowed_destination(args[-1]); return old_sendto(sock, data, *args)
    def sendmsg(sock: socket.socket, buffers: Any, *args: Any):
        if args and isinstance(args[-1], tuple): require_allowed_destination(args[-1])
        elif sock.type & socket.SOCK_DGRAM: raise ExternalAccessBlocked("datagram destination missing")
        return old_sendmsg(sock, buffers, *args)
    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.create_connection = create
    socket.socket.sendto = sendto
    if old_sendmsg is not None: socket.socket.sendmsg = sendmsg
    try: yield
    finally:
        socket.socket.connect = old_connect
        socket.socket.connect_ex = old_connect_ex
        socket.create_connection = old_create
        socket.socket.sendto = old_sendto
        if old_sendmsg is not None: socket.socket.sendmsg = old_sendmsg


def deterministic_ohlcv(symbol: str, bars: int) -> list[dict[str, Any]]:
    if not 60 <= int(bars) <= 2000: raise WorkerSafetyError("bars outside 60..2000")
    seed = int(hashlib.sha256(symbol.upper().encode()).hexdigest()[:12], 16)
    prior = 40.0 + (seed % 46000) / 100
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i in range(int(bars)):
        close = max(1.0, prior * (1 + 0.00025 + math.sin((i + seed % 31) / 9) * .0025))
        spread = .003 + ((seed + i * 17) % 70) / 10000
        rows.append({"date": (start + timedelta(days=i)).isoformat(), "open": round(prior, 6),
                     "high": round(max(prior, close) * (1 + spread), 6),
                     "low": round(min(prior, close) * (1 - spread), 6),
                     "close": round(close, 6),
                     "volume": 100000 + ((seed + i * 7919) % 900000)})
        prior = close
    return rows


def rows_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     default=str).encode()).hexdigest()


def inspect_lab_walk_contract() -> str:
    path = Path(__file__).resolve().parents[1] / "artifacts/api-server/src/python/backtesting_engine.py"
    source = path.read_text(); tree = __import__("ast").parse(source)
    node = next(n for n in tree.body if isinstance(n, __import__("ast").FunctionDef)
                and n.name == "_run_lab_walk")
    return __import__("ast").get_source_segment(source, node) or ""


def real_scan_one(symbol: str, bars: int) -> dict[str, Any]:
    import pandas as pd
    install_provider_stubs(); require_no_forbidden_modules()
    python_dir = Path(__file__).resolve().parents[1] / "artifacts/api-server/src/python"
    sys.path.insert(0, str(python_dir))
    import market_scanner
    if not getattr(sys.modules.get("yfinance"), "__task976_stub__", False):
        raise WorkerSafetyError("real provider module loaded")
    frame = pd.DataFrame(deterministic_ohlcv(symbol, bars))
    frame["date"] = pd.to_datetime(frame["date"]); frame = frame.set_index("date")
    original = market_scanner.fetch_candles_df
    original_walk = market_scanner._run_lab_walk
    calls = 0
    def guarded_walk(rows, strategy, capital):
        nonlocal calls
        calls += 1
        return original_walk(rows, strategy, capital)
    market_scanner.fetch_candles_df = lambda *_a, **_k: frame.copy(deep=True)
    market_scanner._run_lab_walk = guarded_walk
    try:
        result = dict(market_scanner.scan_stock(symbol))
        result["_task976_lab_walk_calls"] = calls
        return result
    finally:
        market_scanner.fetch_candles_df = original
        market_scanner._run_lab_walk = original_walk


def require_worker_duration(seconds: float) -> None:
    if seconds > 75: raise WorkerSafetyError("worker exceeded 75-second bound")


def run_deterministic_workload(tier: int, *, scan_one: Callable = real_scan_one) -> dict[str, Any]:
    bars, _limit = worker_plan(tier); require_exact_symbols(CANONICAL_SYMBOLS)
    started = time.perf_counter()
    with forbidden_callable_guard():
        results = [scan_one(s, bars) for s in CANONICAL_SYMBOLS]
    duration = time.perf_counter() - started; require_worker_duration(duration)
    call_counts = [int(row.pop("_task976_lab_walk_calls", 0)) for row in results]
    lab_calls = sum(call_counts)
    if any(count <= 0 for count in call_counts):
        raise WorkerSafetyError("_run_lab_walk execution was not proven")
    require_no_forbidden_modules()
    return {"tier": tier, "symbols_processed": len(results), "bars_per_symbol": bars,
            "symbol_hash": CANONICAL_HASH, "result_hash": rows_hash(results),
            "duration_seconds": duration,
            "peak_rss_kib": int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss),
            "lab_walk_calls": lab_calls, "provider_calls": 0,
            "broker_calls": 0, "orders_submitted": 0}


RESOURCE_FIELDS = {
    "cpu_user_seconds": "ru_utime", "cpu_system_seconds": "ru_stime",
    "max_rss": "ru_maxrss", "voluntary_ctx_switches": "ru_nvcsw",
    "involuntary_ctx_switches": "ru_nivcsw",
}


def safe_resource_number(value: Any) -> int | float | None:
    # Reject booleans, strings, nonfinite and excessively large values.
    return value if type(value) in (int, float) and 0 <= value <= 2**53 - 1 else None


def sanitize_resources(value: Any) -> dict[str, Any]:
    fields = (*RESOURCE_FIELDS, "wall_seconds", "stage_elapsed_seconds")
    raw = value if isinstance(value, dict) else {}
    result = {key: safe_resource_number(raw.get(key)) for key in fields}
    result["stage"] = raw.get("stage") if raw.get("stage") in ("initialization", "workload", "finalization") else None
    result["max_rss_unit"] = raw.get("max_rss_unit") if raw.get("max_rss_unit") in ("KiB", "bytes", "platform_native") else None
    result["evidence_ok"] = all(result[key] is not None for key in (*fields, "stage", "max_rss_unit"))
    return result


def worker_resources(stage: str, wall_seconds: float, stage_elapsed_seconds: float) -> dict[str, Any]:
    """Read-only process lifetime counters; RSS is KiB on Linux, bytes on macOS.

    Wall/stage clocks begin inside main, after module imports. They do not
    replace the workload duration or the unchanged worker alarm.
    """
    try: usage = resource.getrusage(resource.RUSAGE_SELF)
    except (OSError, ValueError, AttributeError): usage = None
    raw = {key: getattr(usage, attr, None) for key, attr in RESOURCE_FIELDS.items()}
    raw.update(stage=stage, wall_seconds=wall_seconds, stage_elapsed_seconds=stage_elapsed_seconds,
               max_rss_unit="KiB" if sys.platform.startswith("linux") else "bytes" if sys.platform == "darwin" else "platform_native")
    return sanitize_resources(raw)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--tier", type=int, required=True)
    args = parser.parse_args(argv)
    observed_start = stage_start = time.monotonic(); stage = "initialization"
    def diagnostics():
        now = time.monotonic()
        return worker_resources(stage, now-observed_start, now-stage_start)
    def expired(_sig, _frame): raise WorkerSafetyError("worker deadline exceeded")
    try:
        signal.signal(signal.SIGALRM, expired); signal.alarm(worker_plan(args.tier)[1])
        stage = "workload"; stage_start = time.monotonic()
        with network_guard(): result = run_deterministic_workload(args.tier)
        stage = "finalization"; stage_start = time.monotonic()
        result["resources"] = diagnostics()
        print(json.dumps(result, sort_keys=True)); return 0
    except Exception as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)[:160], "resources": diagnostics()}), file=sys.stderr); return 1
    finally: signal.alarm(0)


if __name__ == "__main__": raise SystemExit(main())
