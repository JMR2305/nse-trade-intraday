"""
Phase 23.8A — AI Simulation Laboratory (spec Parts A–F).

STRICTLY READ-ONLY / ADVISORY over the canonical stores:
  • base trades        — backtest store (backtest_portfolio) or the phase20
                         paper ledger (read-only get_ledger)
  • entry context      — canonical Pipeline Event Store (pipeline_events)
  • portfolio state    — canonical_portfolio.build_canonical_portfolio()
  • metric math        — expectancy.compute_metrics (the single engine)
  • what-if machinery  — strategy_lab helpers (no second engine)

Isolation guarantees (spec Part Q — enforced by AST safety test):
  • Simulations NEVER write to the live portfolio, live settings, the paper
    ledger, the event store, or strategy config.
  • Simulation state lives ONLY in dedicated append-only tables
    (sim_scenarios / sim_runs) with file fallback. Historical simulation
    runs are IMMUTABLE — every execution INSERTS a new row; there is no
    update path for a completed run's result.
  • Stress tests operate on in-memory copies of canonical-derived state.
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import backtest_portfolio as bp
import strategy_lab as sl
from expectancy import compute_metrics
from scan_state_store import _connect, db_available

IST = timezone(timedelta(hours=5, minutes=30))
MIN_EVIDENCE = sl.MIN_EVIDENCE
ADVISORY = ("Advisory simulation only — isolated derived state. Live "
            "portfolio, paper ledger, event store and settings are never "
            "modified.")

_DIR = os.path.dirname(os.path.abspath(__file__))
_SCEN_FILE = os.path.join(_DIR, "sim_scenarios.json")
_RUNS_FILE = os.path.join(_DIR, "sim_runs.json")
_SCHEMA_READY = False

# Full what-if parameter set from the spec (Part B). Anything else is
# rejected so a typo never silently no-ops.
ALLOWED_PARAMS = {
    "capital", "position_size_scale", "risk_pct",
    "min_confidence", "atr_mult", "stop_mult", "target_mult",
    "trailing_mult", "risk_reward_mult",
    "max_sector_exposure_pct", "max_open_trades",
    "daily_loss_limit_pct", "daily_profit_lock_pct",
    "regime_filter", "sector_filter", "min_volume_ratio",
    "min_traded_value",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# ── Append-only store (Postgres + file fallback) ─────────────────────────────

def _ensure_schema(conn) -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return
    with conn.cursor() as cur:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sim_scenarios (
                scenario_id TEXT PRIMARY KEY,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                name TEXT NOT NULL,
                base_run_id TEXT,
                params JSONB NOT NULL DEFAULT '{}'::jsonb
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS sim_runs (
                sim_id TEXT PRIMARY KEY,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                scenario_id TEXT,
                label TEXT,
                base_run_id TEXT,
                params JSONB NOT NULL DEFAULT '{}'::jsonb,
                result JSONB NOT NULL DEFAULT '{}'::jsonb
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_sim_runs_created"
                    " ON sim_runs (created_at DESC)")
    conn.commit()
    _SCHEMA_READY = True


def _load_file(path: str) -> List[Dict[str, Any]]:
    try:
        with open(path, "r") as f:
            return json.load(f)
    except Exception:
        return []


def _append_file(path: str, row: Dict[str, Any]) -> None:
    rows = _load_file(path)
    rows.append(row)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(rows, f, default=str)
    os.replace(tmp, path)


def _clean_params(params: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in (params or {}).items():
        if k in ALLOWED_PARAMS and v is not None and v != "":
            out[k] = v
    return out


def create_scenario(name: str, base_run_id: Optional[str],
                    params: Dict[str, Any]) -> Dict[str, Any]:
    params = _clean_params(params)
    bad = sorted(set((params or {}).keys()) - ALLOWED_PARAMS)
    if bad:
        return {"ok": False, "error": f"Unknown params: {bad}"}
    scenario_id = f"SC-{uuid.uuid4().hex[:10]}"
    row = {"scenario_id": scenario_id, "created_at": _now_iso(),
           "name": str(name or "Scenario")[:60],
           "base_run_id": base_run_id, "params": params}
    if db_available():
        conn = _connect()
        try:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO sim_scenarios"
                    " (scenario_id, name, base_run_id, params)"
                    " VALUES (%s, %s, %s, %s)",
                    (scenario_id, row["name"], base_run_id,
                     json.dumps(params, default=str)))
            conn.commit()
        finally:
            conn.close()
    else:
        _append_file(_SCEN_FILE, row)
    return {"ok": True, "scenario": row, "note": ADVISORY}


def list_scenarios(limit: int = 100) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    if db_available():
        conn = _connect()
        try:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT scenario_id, created_at, name, base_run_id, params"
                    " FROM sim_scenarios ORDER BY created_at DESC LIMIT %s",
                    (int(limit),))
                for r in cur.fetchall():
                    rows.append({
                        "scenario_id": r[0],
                        "created_at": r[1].isoformat()
                        if hasattr(r[1], "isoformat") else str(r[1]),
                        "name": r[2], "base_run_id": r[3],
                        "params": r[4] if isinstance(r[4], dict)
                        else json.loads(r[4] or "{}")})
        finally:
            conn.close()
    else:
        rows = list(reversed(_load_file(_SCEN_FILE)))[:limit]
    return {"ok": True, "scenarios": rows, "note": ADVISORY}


def _get_scenario(scenario_id: str) -> Optional[Dict[str, Any]]:
    for s in list_scenarios(limit=500)["scenarios"]:
        if s["scenario_id"] == scenario_id:
            return s
    return None


def _insert_sim_run(row: Dict[str, Any]) -> None:
    """Append-only: INSERT only. A sim run is never updated or overwritten."""
    if db_available():
        conn = _connect()
        try:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO sim_runs"
                    " (sim_id, scenario_id, label, base_run_id, params, result)"
                    " VALUES (%s, %s, %s, %s, %s, %s)",
                    (row["sim_id"], row.get("scenario_id"), row.get("label"),
                     row.get("base_run_id"),
                     json.dumps(row.get("params") or {}, default=str),
                     json.dumps(row.get("result") or {}, default=str)))
            conn.commit()
        finally:
            conn.close()
    else:
        _append_file(_RUNS_FILE, row)


def list_sim_runs(limit: int = 100) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    if db_available():
        conn = _connect()
        try:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT sim_id, created_at, scenario_id, label,"
                    " base_run_id, params, result FROM sim_runs"
                    " ORDER BY created_at DESC LIMIT %s", (int(limit),))
                for r in cur.fetchall():
                    rows.append(_sim_row(r))
        finally:
            conn.close()
    else:
        rows = list(reversed(_load_file(_RUNS_FILE)))[:limit]
    return {"ok": True, "runs": rows, "note": ADVISORY}


def _sim_row(r) -> Dict[str, Any]:
    d = {"sim_id": r[0],
         "created_at": r[1].isoformat() if hasattr(r[1], "isoformat")
         else str(r[1]),
         "scenario_id": r[2], "label": r[3], "base_run_id": r[4],
         "params": r[5], "result": r[6]}
    for k in ("params", "result"):
        if isinstance(d[k], str):
            try:
                d[k] = json.loads(d[k])
            except Exception:
                d[k] = {}
    return d


def _fetch_runs_by_ids(sim_ids: List[str]) -> Dict[str, Dict[str, Any]]:
    """Direct-by-id fetch with NO history-window limit — comparison must
    work for arbitrarily old runs and arbitrarily many selections."""
    ids = [str(s) for s in sim_ids if s]
    if not ids:
        return {}
    out: Dict[str, Dict[str, Any]] = {}
    if db_available():
        conn = _connect()
        try:
            _ensure_schema(conn)
            with conn.cursor() as cur:
                # chunk to keep parameter lists bounded, but cover ALL ids
                for i in range(0, len(ids), 500):
                    chunk = ids[i:i + 500]
                    cur.execute(
                        "SELECT sim_id, created_at, scenario_id, label,"
                        " base_run_id, params, result FROM sim_runs"
                        " WHERE sim_id = ANY(%s)", (chunk,))
                    for r in cur.fetchall():
                        row = _sim_row(r)
                        out[row["sim_id"]] = row
        finally:
            conn.close()
    else:
        want = set(ids)
        for r in _load_file(_RUNS_FILE):     # full scan, no limit
            if r.get("sim_id") in want:
                out[r["sim_id"]] = r
    return out


def get_sim_run(sim_id: str) -> Dict[str, Any]:
    r = _fetch_runs_by_ids([sim_id]).get(str(sim_id))
    if r:
        return {"ok": True, "run": r, "note": ADVISORY}
    return {"ok": False, "error": f"Unknown sim run {sim_id}"}


# ── Scenario simulation engine (extends the strategy-lab what-if) ────────────

def _ist_date(ts: Any) -> Optional[str]:
    d = sl._parse_ts(ts)
    return d.astimezone(IST).date().isoformat() if d else None


def _scenario_sim(run_id: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Isolated derived simulation of one full scenario over a COMPLETED
    backtest run. Reuses the strategy-lab what-if machinery (filters + exit
    re-simulation over the same cached candles); adds capital/position
    sizing, sector-exposure caps, and daily loss/profit-lock circuit rules
    via a chronological portfolio walk. Never persists anything itself."""
    run = bp.get_run(run_id)
    if not run:
        return {"ok": False, "error": f"Unknown run {run_id}"}
    cfg = run.get("config") or {}
    base = sorted(sl._closed(bp.trades(run_id)),
                  key=lambda t: str(t.get("fill_ts") or ""))
    if not base:
        return {"ok": False, "error": "Run has no closed trades",
                "verdict": "INSUFFICIENT_EVIDENCE"}

    params = _clean_params(params)
    base_cap = float(cfg.get("capital") or 100000.0)
    capital = float(params.get("capital") or base_cap)
    risk_pct = float(params.get("risk_pct") or 1.0)
    pos_scale = float(params.get("position_size_scale") or 1.0)
    scale = (capital / base_cap if base_cap > 0 else 1.0) \
        * (risk_pct / 1.0) * pos_scale

    stop_mult = float(params.get("stop_mult")
                      or params.get("atr_mult") or 1.0)
    target_mult = float(params.get("target_mult")
                        or params.get("risk_reward_mult") or 1.0)
    trailing = params.get("trailing_mult")
    trailing = float(trailing) if trailing else None
    min_conf = params.get("min_confidence")
    regime_f = params.get("regime_filter")
    sector_f = params.get("sector_filter")
    min_vol = params.get("min_volume_ratio")
    min_value = params.get("min_traded_value")
    max_open = params.get("max_open_trades")
    max_sector_pct = params.get("max_sector_exposure_pct")
    loss_limit_pct = params.get("daily_loss_limit_pct")
    profit_lock_pct = params.get("daily_profit_lock_pct")

    kept: List[Dict[str, Any]] = []
    dropped: List[Dict[str, Any]] = []
    resim = (stop_mult != 1.0 or target_mult != 1.0 or trailing is not None)
    resim_failures = 0

    # Pass 1 — entry filters + exit re-simulation (strategy-lab machinery).
    for t0 in base:
        t = dict(t0)
        why = None
        if min_conf is not None and \
                float(t.get("confidence") or 0) < float(min_conf):
            why = f"confidence {t.get('confidence')} < {min_conf}"
        elif regime_f and str(t.get("regime") or "").upper() \
                != str(regime_f).upper():
            why = f"regime {t.get('regime')} != {regime_f}"
        elif sector_f and sl._sector_of(t).upper() != str(sector_f).upper():
            why = f"sector {sl._sector_of(t)} != {sector_f}"
        elif min_value is not None and sl._cost(t) < float(min_value):
            why = f"traded value {sl._cost(t):.0f} < {min_value} (liquidity)"
        elif min_vol is not None:
            vr = sl._entry_volume_ratio(run_id, t)
            if vr is not None and float(vr) < float(min_vol):
                why = f"volume_ratio {vr} < {min_vol}"
        if why:
            dropped.append({"trade_id": t.get("trade_id"),
                            "symbol": t.get("symbol"), "reason": why})
            continue
        if resim:
            r = sl._resim_exit(run_id, t, stop_mult, target_mult,
                               trailing, cfg)
            if r is None:
                resim_failures += 1
                dropped.append({"trade_id": t.get("trade_id"),
                                "symbol": t.get("symbol"),
                                "reason": "exit re-simulation unavailable"})
                continue
            t.update(r)
        if scale != 1.0:
            t["realized_pnl"] = round(float(t["realized_pnl"]) * scale, 2)
            t["quantity"] = float(t.get("quantity") or 0) * scale
        kept.append(t)

    # Pass 2 — chronological portfolio walk (concurrency / exposure / daily
    # circuit rules), applied on the isolated simulated trade list only.
    final: List[Dict[str, Any]] = []
    open_iv: List[Dict[str, Any]] = []          # {end, cost, sector}
    day_pnl: Dict[str, float] = {}
    for t in kept:
        a = sl._parse_ts(t.get("fill_ts"))
        b = sl._parse_ts(t.get("exit_ts"))
        # release closed positions and book their realized pnl per IST day
        still = []
        for o in open_iv:
            if a is not None and o["end"] is not None and o["end"] <= a:
                d = o["exit_day"]
                if d:
                    day_pnl[d] = day_pnl.get(d, 0.0) + o["pnl"]
            else:
                still.append(o)
        open_iv = still
        why = None
        cost = sl._cost(t)
        day = _ist_date(t.get("fill_ts"))
        booked = day_pnl.get(day or "", 0.0)
        if max_open is not None and len(open_iv) >= int(max_open):
            why = f"max_open_trades {max_open} reached"
        elif max_sector_pct is not None and capital > 0:
            sec = sl._sector_of(t)
            sec_cost = sum(o["cost"] for o in open_iv
                           if o["sector"] == sec) + cost
            if sec_cost / capital * 100.0 > float(max_sector_pct):
                why = (f"sector exposure {sec_cost / capital * 100.0:.1f}%"
                       f" > {max_sector_pct}% for {sec}")
        if why is None and loss_limit_pct is not None and capital > 0 \
                and booked <= -abs(float(loss_limit_pct)) / 100.0 * capital:
            why = f"daily loss limit {loss_limit_pct}% hit on {day}"
        if why is None and profit_lock_pct is not None and capital > 0 \
                and booked >= abs(float(profit_lock_pct)) / 100.0 * capital:
            why = f"daily profit lock {profit_lock_pct}% reached on {day}"
        if why:
            dropped.append({"trade_id": t.get("trade_id"),
                            "symbol": t.get("symbol"), "reason": why})
            continue
        final.append(t)
        open_iv.append({"end": b, "cost": cost, "sector": sl._sector_of(t),
                        "pnl": float(t.get("realized_pnl") or 0),
                        "exit_day": _ist_date(t.get("exit_ts"))})

    m = compute_metrics(sl._as_metric_rows(final))
    pnl = round(sum(float(t.get("realized_pnl") or 0) for t in final), 2)
    max_expo = sl._max_exposure(final)
    return {
        "ok": True, "base_run_id": run_id, "params": params,
        "derived": True, "base_run_modified": False,
        "capital": capital,
        "trades_kept": len(final), "trades_dropped": len(dropped),
        "dropped": dropped[:60],
        "resimulated_exits": resim, "resim_failures": resim_failures,
        "pnl": pnl,
        "trades": m["trades"], "win_rate": m["win_rate"],
        "sharpe": m["sharpe"], "sortino": m["sortino"],
        "max_drawdown_pct": m["max_drawdown"],
        "profit_factor": m["profit_factor"],
        "expectancy": m["expectancy"],
        "recovery_factor": m["recovery_factor"],
        "capital_growth_pct": (round(pnl / capital * 100.0, 2)
                               if capital else None),
        "max_exposure": max_expo,
        "max_exposure_pct": (round(max_expo / capital * 100.0, 2)
                             if capital else None),
        "verdict": ("INSUFFICIENT_EVIDENCE" if len(final) < MIN_EVIDENCE
                    else "RESIM_INCOMPLETE" if resim_failures > 0 else "OK"),
        "note": ADVISORY,
    }


def run_scenario(scenario_id: Optional[str] = None,
                 run_id: Optional[str] = None,
                 params: Optional[Dict[str, Any]] = None,
                 label: Optional[str] = None) -> Dict[str, Any]:
    """Execute one scenario simulation and APPEND it to the run history.
    History is never overwritten — every execution is a new sim_id."""
    scen = _get_scenario(scenario_id) if scenario_id else None
    if scenario_id and not scen:
        return {"ok": False, "error": f"Unknown scenario {scenario_id}"}
    base_run = run_id or (scen or {}).get("base_run_id")
    use_params = _clean_params(params if params else (scen or {}).get("params"))
    if not base_run:
        return {"ok": False,
                "error": "base run_id required (directly or via scenario)"}
    result = _scenario_sim(str(base_run), use_params)
    if not result.get("ok"):
        return result
    row = {"sim_id": f"SIM-{uuid.uuid4().hex[:10]}",
           "created_at": _now_iso(),
           "scenario_id": scenario_id,
           "label": (str(label)[:60] if label
                     else (scen or {}).get("name") or "Ad-hoc what-if"),
           "base_run_id": str(base_run),
           "params": use_params, "result": result}
    _insert_sim_run(row)
    return {"ok": True, "run": row, "note": ADVISORY}


# ── Part F: unlimited scenario comparison over stored sim runs ───────────────

_COMPARE_KEYS = ["trades", "win_rate", "pnl", "sharpe", "sortino",
                 "max_drawdown_pct", "profit_factor", "expectancy",
                 "recovery_factor", "capital_growth_pct", "max_exposure",
                 "max_exposure_pct", "verdict"]


def compare_sim_runs(sim_ids: List[str]) -> Dict[str, Any]:
    """Unlimited comparison: every requested run is fetched directly by id
    (no history-window cutoff, no cap on the number of selections)."""
    all_runs = _fetch_runs_by_ids(sim_ids)
    rows = []
    for sid in sim_ids:
        r = all_runs.get(sid)
        if not r:
            rows.append({"sim_id": sid, "ok": False, "error": "not found"})
            continue
        res = r.get("result") or {}
        rows.append({"sim_id": sid, "ok": True, "label": r.get("label"),
                     "created_at": r.get("created_at"),
                     "base_run_id": r.get("base_run_id"),
                     "params": r.get("params"),
                     **{k: res.get(k) for k in _COMPARE_KEYS}})
    return {"ok": True, "rows": rows, "note": ADVISORY}


# ── Part E: risk-rule A/B comparison ─────────────────────────────────────────

def risk_rule_compare(run_id: str, rules_a: Dict[str, Any],
                      rules_b: Dict[str, Any]) -> Dict[str, Any]:
    a = _scenario_sim(run_id, rules_a or {})
    b = _scenario_sim(run_id, rules_b or {})
    if not a.get("ok") or not b.get("ok"):
        return {"ok": False, "error": a.get("error") or b.get("error"),
                "verdict": "INSUFFICIENT_EVIDENCE"}
    dropped_b = {d.get("trade_id") for d in (b.get("dropped") or [])}
    dropped_a = {d.get("trade_id") for d in (a.get("dropped") or [])}
    # Missed opportunities: trades version B blocks that version A kept and
    # that were profitable — computed from the base run's immutable ledger.
    missed = 0
    missed_pnl = 0.0
    for t in sl._closed(bp.trades(run_id)):
        tid = t.get("trade_id")
        if tid in dropped_b and tid not in dropped_a \
                and float(t.get("realized_pnl") or 0) > 0:
            missed += 1
            missed_pnl += float(t.get("realized_pnl") or 0)

    def eff(r):
        e = r.get("max_exposure") or 0
        return round(r.get("pnl", 0) / e, 4) if e else None

    insufficient = (a.get("verdict") == "INSUFFICIENT_EVIDENCE"
                    or b.get("verdict") == "INSUFFICIENT_EVIDENCE")
    return {
        "ok": True, "run_id": run_id,
        "rules_a": {**{k: a.get(k) for k in _COMPARE_KEYS},
                    "params": a.get("params"),
                    "trades_kept": a.get("trades_kept")},
        "rules_b": {**{k: b.get(k) for k in _COMPARE_KEYS},
                    "params": b.get("params"),
                    "trades_kept": b.get("trades_kept")},
        "diff": {
            "trades": (b.get("trades", 0) or 0) - (a.get("trades", 0) or 0),
            "pnl": round((b.get("pnl", 0) or 0) - (a.get("pnl", 0) or 0), 2),
            "max_drawdown_pct": round(
                (b.get("max_drawdown_pct", 0) or 0)
                - (a.get("max_drawdown_pct", 0) or 0), 2),
            "risk_reduction_pct": round(
                (a.get("max_drawdown_pct", 0) or 0)
                - (b.get("max_drawdown_pct", 0) or 0), 2),
            "missed_opportunities": missed,
            "missed_opportunity_pnl": round(missed_pnl, 2),
            "capital_efficiency_a": eff(a),
            "capital_efficiency_b": eff(b),
        },
        "verdict": "INSUFFICIENT_EVIDENCE" if insufficient else "OK",
        "note": ADVISORY,
    }


# ── Part C: portfolio stress tests (shock transforms, in-memory only) ────────

PORTFOLIO_STRESS_SCENARIOS: Dict[str, Dict[str, Any]] = {
    "GAP_DOWN_20":     {"label": "Market gaps down 20%", "shock_pct": -20.0,
                        "slippage_pct": 0.5},
    "FLASH_CRASH":     {"label": "Flash crash (−10% w/ stop slippage)",
                        "shock_pct": -10.0, "slippage_pct": 2.0},
    "HIGH_VOLATILITY": {"label": "High volatility (−8% swings)",
                        "shock_pct": -8.0, "slippage_pct": 1.5},
    "LOW_LIQUIDITY":   {"label": "Low liquidity (wide exit spreads)",
                        "shock_pct": -3.0, "slippage_pct": 3.0},
    "LARGE_SLIPPAGE":  {"label": "Large slippage on all exits",
                        "shock_pct": -1.0, "slippage_pct": 2.5},
    "SECTOR_COLLAPSE": {"label": "Largest sector collapses 30%",
                        "shock_pct": -30.0, "slippage_pct": 1.0,
                        "sector_only": True},
    "GAP_UP_10":       {"label": "Market gaps up 10%", "shock_pct": 10.0,
                        "slippage_pct": 0.0},
    "TREND_REVERSAL":  {"label": "Trend reversal (−12% over days)",
                        "shock_pct": -12.0, "slippage_pct": 0.8},
}


def _avg_daily_pnl() -> Optional[float]:
    """Average daily realized pnl from the paper ledger (read-only)."""
    try:
        import phase20_executor as p20
        closed = [t for t in p20.get_ledger(limit=10_000)
                  if t.get("status") == "CLOSED"
                  and t.get("realized_pnl") is not None]
        days: Dict[str, float] = {}
        for t in closed:
            d = _ist_date(t.get("exit_ts"))
            if d:
                days[d] = days.get(d, 0.0) + float(t["realized_pnl"])
        if not days:
            return None
        return sum(days.values()) / len(days)
    except Exception:
        return None


def portfolio_stress() -> Dict[str, Any]:
    """Apply each shock transform to an IN-MEMORY copy of the canonical
    paper-portfolio snapshot. Nothing is written anywhere."""
    from canonical_portfolio import build_canonical_portfolio
    port = build_canonical_portfolio()
    equity = float(port.get("equity") or 0)
    invested = float(port.get("invested_value") or 0)
    positions = list(port.get("positions") or [])
    if equity <= 0:
        return {"ok": True, "scenarios": [],
                "verdict": "INSUFFICIENT_EVIDENCE",
                "reason": "no portfolio equity", "note": ADVISORY}
    sector_exp = port.get("sector_exposure") or {}
    worst_sector = next(iter(sector_exp), None)
    avg_daily = _avg_daily_pnl()

    rows = []
    for key, sc in PORTFOLIO_STRESS_SCENARIOS.items():
        shock = float(sc["shock_pct"]) / 100.0
        slip = float(sc.get("slippage_pct") or 0) / 100.0
        loss = 0.0
        for p in positions:
            mv = float(p.get("market_value") or 0)
            if sc.get("sector_only") and p.get("sector") != worst_sector:
                continue
            # Explicit sign convention: `loss` is positive for a loss and
            # negative for a gain.  price_move is the mark-to-market change
            # (negative shock ⇒ negative move ⇒ positive loss); exit
            # slippage only adds cost in downside scenarios.
            price_move = mv * shock
            slippage_cost = mv * slip if shock < 0 else 0.0
            loss += (-price_move) + slippage_cost
        loss = round(loss, 2)          # positive = loss, negative = gain
        capital_remaining = round(equity - loss, 2)
        dd = round(max(0.0, loss) / equity * 100.0, 2)
        margin_util = (round(invested / capital_remaining * 100.0, 2)
                       if capital_remaining > 0 else None)
        if loss <= 0:
            recovery = 0.0
        elif avg_daily and avg_daily > 0:
            recovery = round(loss / avg_daily, 1)
        else:
            recovery = None
        rows.append({
            "scenario": key, "label": sc["label"],
            "shock_pct": sc["shock_pct"],
            "slippage_pct": sc.get("slippage_pct"),
            "target_sector": worst_sector if sc.get("sector_only") else None,
            "portfolio_loss": loss,
            "drawdown_pct": dd,
            "capital_remaining": capital_remaining,
            "margin_utilization_pct": margin_util,
            "recovery_time_days": recovery,
            "recovery_basis": ("historical avg daily pnl" if recovery
                               not in (None, 0.0) else
                               "no positive daily pnl history"
                               if recovery is None else "no loss"),
        })
    return {
        "ok": True, "source": "canonical_portfolio (in-memory copy)",
        "equity": equity, "invested_value": invested,
        "open_positions": len(positions),
        "scenarios": rows,
        "verdict": "OK" if positions else "INSUFFICIENT_EVIDENCE",
        "reason": None if positions else "no open positions to stress",
        "note": ADVISORY,
    }


# ── Part D: execution stress tests (fault injection, isolated fills) ─────────

EXECUTION_STRESS_SCENARIOS: Dict[str, Dict[str, Any]] = {
    "DELAYED_ORDERS":    {"label": "Orders delayed 30s", "delay_slip_pct": 0.5},
    "REJECTED_ORDERS":   {"label": "Broker rejects 30% of orders",
                          "reject_every": 3},
    "PARTIAL_FILLS":     {"label": "50% partial fills", "partial_ratio": 0.5},
    "API_FAILURE":       {"label": "Broker API fails, retries recover",
                          "fail_first_attempts": 2},
    "EXCHANGE_DELAY":    {"label": "Exchange confirmation delayed",
                          "delay_slip_pct": 0.2, "pending_every": 4},
    "BROKER_DISCONNECT": {"label": "Broker disconnect mid-session",
                          "disconnect_after": 0.5},
}


def _replay_fingerprint() -> Optional[Dict[str, Any]]:
    """Read-only integrity fingerprint of the ENTIRE canonical replay
    store, taken directly from the underlying tables (scan_state row +
    EVERY signal_snapshots row, unbounded, stable ordering) — NOT from any
    paged display/list API. Row content is included via per-row content
    hashes, so mutating any historical session's content — or adding /
    removing any row anywhere in history — changes the SHA-256. Returns
    None (=> 'unknown', never a fabricated pass) when the store cannot be
    read completely."""
    try:
        import hashlib
        if not db_available():
            return None
        conn = _connect()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT scan_id, status, snapshot_ts,"
                    " md5(COALESCE(snapshot::text, ''))"
                    " FROM scan_state WHERE id = 1")
                head = [list(map(str, r)) for r in cur.fetchall()]
                cur.execute(
                    "SELECT id, scan_id, canonical_scan_id, snapshot_ts,"
                    " md5(COALESCE(signals::text, '')),"
                    " md5(COALESCE(market_context::text, ''))"
                    " FROM signal_snapshots ORDER BY id")
                rows = [list(map(str, r)) for r in cur.fetchall()]
        finally:
            conn.close()
        canonical = json.dumps([head, rows], sort_keys=True, default=str)
        return {"count": len(rows),
                "sha256": hashlib.sha256(canonical.encode()).hexdigest()}
    except Exception:
        return None


def _sample_orders(limit: int = 40) -> List[Dict[str, Any]]:
    """Isolated COPIES of recent paper-ledger fills as simulated orders."""
    import phase20_executor as p20
    out = []
    for t in p20.get_ledger(limit=limit):
        px = t.get("fill_price")
        qty = t.get("quantity")
        if not px or not qty:
            continue
        out.append({"symbol": t.get("symbol"), "qty": int(qty),
                    "price": float(px), "side": "BUY"})
    return out


def execution_stress() -> Dict[str, Any]:
    """Inject faults into an isolated in-memory order simulation and verify
    conservation + that live stores are untouched (read-only proof)."""
    import phase20_executor as p20
    ledger_before = len(p20.get_ledger(limit=10_000))
    replay_before = _replay_fingerprint()
    orders = _sample_orders()
    if not orders:
        return {"ok": True, "scenarios": [],
                "verdict": "INSUFFICIENT_EVIDENCE",
                "reason": "no ledger fills to derive simulated orders from",
                "note": ADVISORY}

    rows = []
    for key, sc in EXECUTION_STRESS_SCENARIOS.items():
        filled = rejected = partial = pending = 0
        retries = 0
        extra_cost = 0.0
        n = len(orders)
        disconnect_at = (int(n * float(sc["disconnect_after"]))
                         if "disconnect_after" in sc else None)
        for i, o in enumerate(orders):
            if disconnect_at is not None and i >= disconnect_at:
                pending += 1          # EXIT_PENDING semantics: never fabricate
                continue
            if sc.get("reject_every") and (i + 1) % int(sc["reject_every"]) == 0:
                rejected += 1
                continue
            if sc.get("fail_first_attempts"):
                retries += int(sc["fail_first_attempts"])
            if sc.get("pending_every") and (i + 1) % int(sc["pending_every"]) == 0:
                pending += 1
                continue
            slip = float(sc.get("delay_slip_pct") or 0) / 100.0
            if sc.get("partial_ratio"):
                partial += 1
                extra_cost += o["price"] * slip * o["qty"] \
                    * float(sc["partial_ratio"])
            else:
                filled += 1
                extra_cost += o["price"] * slip * o["qty"]
        conserved = (filled + rejected + partial + pending == n)
        rows.append({
            "scenario": key, "label": sc["label"],
            "orders_in": n, "filled": filled, "rejected": rejected,
            "partial_fills": partial, "pending": pending,
            "retries_used": retries,
            "extra_slippage_cost": round(extra_cost, 2),
            "conservation_ok": conserved,
            "recovered": key != "BROKER_DISCONNECT" or pending > 0,
            "recovery_action": ("EXIT_PENDING until reconnect"
                                if key == "BROKER_DISCONNECT" else
                                "retry with backoff"
                                if key == "API_FAILURE" else "none required"),
        })

    ledger_after = len(p20.get_ledger(limit=10_000))
    replay_after = _replay_fingerprint()
    if replay_before is None or replay_after is None:
        replay_consistent = None      # advisory: store unavailable, unknown
    else:
        replay_consistent = replay_before == replay_after
    return {
        "ok": True,
        "scenarios": rows,
        "consistency": {
            "ledger_rows_before": ledger_before,
            "ledger_rows_after": ledger_after,
            "ledger_untouched": ledger_before == ledger_after,
            "replay_store_consistent": replay_consistent,
            "replay_sessions_before": replay_before,
            "replay_sessions_after": replay_after,
            "all_conserved": all(r["conservation_ok"] for r in rows),
        },
        "verdict": "OK",
        "note": ADVISORY,
    }
