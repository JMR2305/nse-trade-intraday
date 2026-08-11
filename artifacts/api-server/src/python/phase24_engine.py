"""
phase24_engine.py — Phase 24: Trade capture, post-trade analysis,
missed-opportunity analysis, risk-rule learning.

READ-ONLY over trading state. ADVISORY ONLY.
- Reads the canonical phase20 paper trade ledger (single source of truth).
- Enriches CLOSED trades into permanent Trade Intelligence records
  (phase24_store, append-only, keyed by the EXISTING trade_id).
- Records are built from the exact trade-time payload the executor stored
  (ledger columns + evidence JSONB) — never a re-evaluation.
- NEVER writes to trading rules, thresholds, strategies, or risk gates.
"""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

import phase24_store as store

IST = timezone(timedelta(hours=5, minutes=30))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_ts(ts: Any) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return None


# ── Candle window helpers (MFE/MAE + post-exit movement) ─────────────────────

def _candles_between(symbol: str, start: Optional[datetime],
                     end: Optional[datetime]) -> List[Dict[str, Any]]:
    """Intraday candles overlapping [start, end]. Empty list on any failure —
    excursion fields are then None (explicit, never fabricated)."""
    if start is None:
        return []
    try:
        from market_data_engine import fetch_candles
        result = fetch_candles(symbol, interval="5m", period="5d")
        if result.get("source") == "mock":
            return []  # never compute excursions from synthetic data
        candles = result.get("candles") or []
    except Exception:
        return []
    end = end or datetime.now(timezone.utc)
    out = []
    for c in candles:
        t = _parse_ts(c.get("time"))
        if t is None:
            continue
        if t.tzinfo is None:
            t = t.replace(tzinfo=IST)
        if start <= t <= end:
            out.append(c)
    return out


def compute_excursions(candles: List[Dict[str, Any]],
                       entry_price: float, quantity: int) -> Dict[str, Any]:
    """MFE/MAE (₹ and %) and highest/lowest price over the holding window."""
    if not candles or not entry_price:
        return {"highest_price": None, "lowest_price": None,
                "mfe": None, "mae": None, "mfe_pct": None, "mae_pct": None,
                "excursion_source": "unavailable"}
    highs = [float(c["high"]) for c in candles if c.get("high") is not None]
    lows = [float(c["low"]) for c in candles if c.get("low") is not None]
    if not highs or not lows:
        return {"highest_price": None, "lowest_price": None,
                "mfe": None, "mae": None, "mfe_pct": None, "mae_pct": None,
                "excursion_source": "unavailable"}
    hi, lo = max(highs), min(lows)
    mfe = round((hi - entry_price) * quantity, 2)
    mae = round((lo - entry_price) * quantity, 2)
    return {
        "highest_price": round(hi, 2), "lowest_price": round(lo, 2),
        "mfe": mfe, "mae": mae,
        "mfe_pct": round(100.0 * (hi - entry_price) / entry_price, 3),
        "mae_pct": round(100.0 * (lo - entry_price) / entry_price, 3),
        "excursion_source": "intraday_candles",
    }


# ── Post-trade analysis ──────────────────────────────────────────────────────

def analyze_trade(record: Dict[str, Any]) -> Dict[str, Any]:
    """Spec'd post-trade verdicts, computed ONLY from the captured record
    (trade-time payload + holding-window excursions). Advisory only."""
    entry = float(record.get("entry_price") or 0)
    exitp = record.get("exit_price")
    qty = int(record.get("quantity") or 0)
    stop = record.get("stop_loss")
    target = record.get("target")
    pnl = record.get("realized_pnl")
    hi = record.get("highest_price")
    lo = record.get("lowest_price")
    mfe = record.get("mfe")
    mae = record.get("mae")
    exit_reason = str(record.get("exit_reason") or "").upper()

    v: Dict[str, Any] = {"advisory_only": True}
    known = entry > 0 and exitp is not None

    # Entry timing: how much adverse room did the trade see before working?
    if known and mae is not None and mfe is not None and qty:
        mae_per_share = abs(mae) / qty
        mfe_per_share = max(mfe, 0) / qty
        if mae_per_share > 0 and mfe_per_share > 0 and mae_per_share > 0.6 * mfe_per_share:
            v["entry_timing"] = "EARLY"
            v["entry_timing_note"] = ("Price moved significantly against the entry "
                                      "before turning favourable — entry was early.")
        elif hi is not None and entry >= float(hi) * 0.995:
            v["entry_timing"] = "LATE"
            v["entry_timing_note"] = "Entry was near the window high — little upside remained."
        else:
            v["entry_timing"] = "OK"
    else:
        v["entry_timing"] = "UNKNOWN"

    # Stop quality
    if stop and entry and lo is not None:
        stop_f = float(stop)
        stopped = exit_reason.startswith("STOP") or (exitp is not None and float(exitp) <= stop_f * 1.002)
        went_on_to_profit = mfe is not None and mfe > 0 and (pnl or 0) <= 0
        if stopped and went_on_to_profit:
            v["stop_verdict"] = "TOO_TIGHT"
            v["stop_note"] = "Stop hit but the move later turned favourable."
        elif not stopped and float(lo) > stop_f * 1.05 and (pnl or 0) < 0:
            v["stop_verdict"] = "TOO_LOOSE"
            v["stop_note"] = "Loss taken while price never came near the stop."
        else:
            v["stop_verdict"] = "OK"
    else:
        v["stop_verdict"] = "UNKNOWN"

    # Target quality
    if target and entry and hi is not None:
        tgt = float(target)
        if float(hi) >= tgt * 1.03:
            v["target_verdict"] = "TOO_CONSERVATIVE"
            v["target_note"] = "Price exceeded target by >3% — target left money on the table."
        elif float(hi) < entry + 0.5 * (tgt - entry):
            v["target_verdict"] = "TOO_AGGRESSIVE"
            v["target_note"] = "Price never reached half the target distance."
        else:
            v["target_verdict"] = "OK"
    else:
        v["target_verdict"] = "UNKNOWN"

    # Exit timing + could-AI-have-earned-more
    if known and mfe is not None and pnl is not None:
        missed = round(max(float(mfe) - float(pnl), 0.0), 2)
        v["max_potential_pnl"] = round(float(mfe), 2)
        v["missed_pnl"] = missed
        v["could_have_earned_more"] = missed > max(abs(float(pnl)) * 0.5, 50.0)
        if v["could_have_earned_more"] and float(pnl) >= 0:
            v["exit_timing"] = "EARLY"
        elif float(pnl) < 0 and mfe > 0:
            v["exit_timing"] = "LATE"
            v["exit_note"] = "Trade was profitable at its peak but exited at a loss."
        else:
            v["exit_timing"] = "OK"
    else:
        v["exit_timing"] = "UNKNOWN"
        v["could_have_earned_more"] = None

    # Trailing-stop benefit (counterfactual on captured excursions only)
    if known and hi is not None and pnl is not None and qty:
        trail_exit = float(hi) * 0.99  # 1% trail from peak
        trail_pnl = round((trail_exit - entry) * qty, 2)
        v["trailing_stop_pnl_advisory"] = trail_pnl
        v["trailing_stop_would_have_helped"] = trail_pnl > float(pnl) + 25.0
    else:
        v["trailing_stop_would_have_helped"] = None

    # Counterfactual strategy comparison (advisory, from regime matrix)
    try:
        from phase21_regime import load_regime_matrix, normalize_regime
        matrix = load_regime_matrix()
        reg = normalize_regime(record.get("market_regime"))
        this_strat = record.get("strategy") or "UNKNOWN"
        best = None
        for p in matrix.get("pairs", []):
            if p.get("regime") == reg and p.get("expectancy") is not None:
                if best is None or float(p["expectancy"]) > float(best["expectancy"]):
                    best = p
        if best and best.get("strategy") != this_strat:
            v["better_strategy_advisory"] = {
                "strategy": best.get("strategy"),
                "regime": reg,
                "historical_expectancy": best.get("expectancy"),
                "note": "Historically higher expectancy in this regime (advisory).",
            }
        else:
            v["better_strategy_advisory"] = None
    except Exception:
        v["better_strategy_advisory"] = None

    return v


# ── Trade capture ────────────────────────────────────────────────────────────

def build_trade_record(row: Dict[str, Any]) -> Dict[str, Any]:
    """Full Phase 24 field set from the exact ledger row (trade-time payload)."""
    entry_ts = _parse_ts(row.get("fill_ts"))
    exit_ts = _parse_ts(row.get("exit_ts"))
    holding_min = None
    if entry_ts and exit_ts:
        holding_min = round((exit_ts - entry_ts).total_seconds() / 60.0, 1)
    qty = int(row.get("quantity") or 0)
    entry_price = float(row.get("fill_price") or 0)

    evidence = row.get("evidence") or {}
    if not isinstance(evidence, dict):
        evidence = {}
    candidate = evidence.get("candidate") or {}
    indicators = (candidate.get("indicators") or evidence.get("indicators") or {})

    excursions = compute_excursions(
        _candles_between(row.get("symbol") or "", entry_ts, exit_ts),
        entry_price, qty)

    ist_date = entry_ts.astimezone(IST).date().isoformat() if entry_ts else None
    record = {
        "trade_id": row.get("trade_id"),
        "session_id": ist_date,
        "scan_id": row.get("scan_id"),
        "symbol": row.get("symbol"),
        "sector": row.get("sector"),
        "date": ist_date,
        "entry_time": row.get("fill_ts"),
        "exit_time": row.get("exit_ts"),
        "holding_time_minutes": holding_min,
        "entry_price": entry_price,
        "exit_price": row.get("exit_price"),
        "quantity": qty,
        "capital_used": round(entry_price * qty, 2),
        "strategy": row.get("strategy_name") or row.get("strategy_id"),
        "strategy_id": row.get("strategy_id"),
        "confidence": row.get("confidence"),
        "risk_score": row.get("trade_quality_score"),
        "opportunity_score": row.get("opportunity_score"),
        "stop_loss": row.get("stop_loss"),
        "target": row.get("target"),
        "realized_pnl": row.get("realized_pnl"),
        "exit_reason": row.get("exit_rule"),
        "market_regime": row.get("regime"),
        "volatility": indicators.get("atr_pct") or indicators.get("volatility"),
        "gap_pct": indicators.get("gap_pct"),
        "volume": indicators.get("volume"),
        "volume_ratio": indicators.get("volume_ratio"),
        "vwap": indicators.get("vwap"),
        "ema": indicators.get("ema") or indicators.get("ema_20"),
        "rsi": indicators.get("rsi"),
        "macd": indicators.get("macd"),
        "adx": indicators.get("adx"),
        "atr": indicators.get("atr"),
        "research_score": candidate.get("research_score"),
        "market_intelligence_score": candidate.get("mi_score") or candidate.get("market_intelligence_score"),
        "monitoring_score": candidate.get("monitoring_score"),
        "decision_score": row.get("trade_quality_score"),
        "execution_status": row.get("status"),
        "est_charges": row.get("est_charges"),
        "slippage": row.get("slippage"),
        "risk_amount": row.get("risk_amount"),
        "trigger_source": row.get("trigger_source"),
        "evidence_gates": evidence.get("gates"),
        "captured_at": _now(),
        "source": "phase20_ledger",
        "advisory_only": True,
    }
    record.update(excursions)

    # Portfolio snapshot at capture time (context, clearly labelled)
    try:
        from canonical_portfolio import build_canonical_portfolio
        c = build_canonical_portfolio()
        record["portfolio_snapshot"] = {
            "as_of": "capture_time",
            "cash": c.get("cash"), "equity": c.get("equity"),
            "invested_value": c.get("invested_value"),
            "open_position_count": c.get("open_position_count"),
            "realized_pnl": c.get("realized_pnl"),
        }
    except Exception:
        record["portfolio_snapshot"] = None
    return record


def capture_closed_trades(limit: int = 10_000) -> Dict[str, Any]:
    """Capture every CLOSED ledger trade not yet in the intelligence store.
    Idempotent: already-captured trades are skipped (append-only)."""
    import phase20_executor as p20
    rows = [r for r in p20.get_ledger(limit=limit) if r.get("status") == "CLOSED"]
    captured, skipped, errors = [], 0, []
    for row in rows:
        tid = row.get("trade_id")
        if not tid:
            continue
        try:
            if store.has_trade_record(tid):
                skipped += 1
                continue
            record = build_trade_record(row)
            analysis = analyze_trade(record)
            inserted = store.insert_trade_record(
                tid, row.get("scan_id"), row.get("symbol") or "",
                record.get("date") or "", record, analysis)
            if inserted:
                captured.append(tid)
            else:
                skipped += 1
        except Exception as exc:
            errors.append({"trade_id": tid, "error": str(exc)[:200]})
    return {"closed_in_ledger": len(rows), "captured": captured,
            "captured_count": len(captured), "skipped_existing": skipped,
            "errors": errors, "advisory_only": True}


# ── Missed-opportunity analysis ──────────────────────────────────────────────

def run_missed_opportunity_analysis(move_threshold_pct: float = 2.0) -> Dict[str, Any]:
    """Analyse rejected candidates from the latest canonical scan gate audit
    against subsequent price movement. Results stored permanently per
    (scan_id, symbol). Advisory only."""
    try:
        from scan_state_store import load_latest_snapshot
        snap = load_latest_snapshot() or {}
    except Exception:
        snap = {}
    scan_id = snap.get("scan_id")
    snapshot_ts = snap.get("snapshot_ts")
    recs = {r.get("symbol"): r for r in (snap.get("recommendations") or [])
            if r.get("symbol")}
    if not scan_id or not recs:
        return {"available": False, "reason": "No canonical scan snapshot",
                "stored": 0, "advisory_only": True}

    from phase20_gates import evaluate_entries
    result = evaluate_entries(candidate_symbols=sorted(recs.keys()))
    scan_ts = _parse_ts(snapshot_ts)

    stored, analysed = 0, []
    for cand in result.get("candidates") or []:
        failed = cand.get("failed_gates") or []
        if not failed:
            continue
        sym = cand.get("symbol")
        rec = recs.get(sym) or {}
        ref_price = rec.get("entry_price") or rec.get("last_price")
        later_move_pct = None
        if ref_price and scan_ts:
            candles = _candles_between(sym, scan_ts, None)
            if candles:
                closes = [float(c["close"]) for c in candles if c.get("close") is not None]
                if closes:
                    later_move_pct = round(
                        100.0 * (max(closes) - float(ref_price)) / float(ref_price), 3)
        rejection_correct = None
        if later_move_pct is not None:
            rejection_correct = later_move_pct < move_threshold_pct
        entry = {
            "symbol": sym,
            "scan_id": scan_id,
            "snapshot_ts": snapshot_ts,
            "rejected_by_gates": failed,
            "first_blocking_gate": failed[0],
            "confidence": rec.get("confidence"),
            "opportunity_score": rec.get("opportunity_score"),
            "sector": rec.get("sector"),
            "reference_price": ref_price,
            "later_max_move_pct": later_move_pct,
            "move_threshold_pct": move_threshold_pct,
            "rejection_correct": rejection_correct,
            "should_have_allowed": (later_move_pct is not None
                                    and later_move_pct >= move_threshold_pct),
            "analysed_at": _now(),
            "advisory_only": True,
        }
        if store.insert_missed_opp(scan_id, sym, entry):
            stored += 1
        analysed.append(entry)
    return {"available": True, "scan_id": scan_id, "analysed": len(analysed),
            "stored": stored, "items": analysed, "advisory_only": True}


# ── Backtest missed-opportunity bridge ───────────────────────────────────────

def ingest_backtest_missed_opps(run_id: str) -> dict:
    """Read backtest_runs.missed and ingest into phase24_missed_opps with
    source='backtest'. Idempotent (ON CONFLICT DO NOTHING). Advisory only —
    never modifies thresholds, strategies, or trading defaults."""
    import backtest_portfolio as bp
    run = bp.get_run(run_id)
    if not run:
        return {"ok": False, "error": f"Run {run_id} not found",
                "advisory_only": True}

    missed_entries = run.get("missed") or []
    if not missed_entries:
        return {"ok": True, "run_id": run_id, "ingested": 0, "skipped_existing": 0,
                "reason": "No missed opportunities stored in this run",
                "advisory_only": True}

    cfg = run.get("config") or {}
    interval = str(cfg.get("interval") or "unknown")

    # Batch-level advisory stats (attached to every record for context)
    profitable = [e for e in missed_entries if e.get("would_have_been_profitable")]
    sample_size = len(missed_entries)
    win_rate = round(len(profitable) / sample_size, 3) if sample_size else 0.0
    fwd_returns = sorted(
        float(e["return_at_horizon_pct"]) for e in missed_entries
        if e.get("return_at_horizon_pct") is not None
    )
    median_fwd = round(fwd_returns[len(fwd_returns) // 2], 2) if fwd_returns else None
    false_pos_risk = round(1.0 - win_rate, 3)
    confidence_level = ("HIGH" if sample_size >= 50
                        else "MEDIUM" if sample_size >= 20 else "LOW")
    batch_stats = {
        "sample_size": sample_size,
        "win_rate": win_rate,
        "median_forward_return_pct": median_fwd,
        "false_positive_risk": false_pos_risk,
        "confidence_level": confidence_level,
    }

    ingested, skipped, errors = 0, 0, []
    for entry in missed_entries:
        sym = str(entry.get("symbol") or "").upper()
        scan_id = str(entry.get("scan_id") or "")
        if not sym or not scan_id:
            skipped += 1
            continue
        record = {
            **entry,
            "source": "backtest",
            "backtest_run_id": run_id,
            "interval": interval,
            "advisory_only": True,
            "ingested_at": _now(),
            "batch_stats": batch_stats,
        }
        try:
            inserted = store.insert_missed_opp(
                scan_id=scan_id, symbol=sym, record=record,
                source="backtest", backtest_run_id=run_id,
            )
            if inserted:
                ingested += 1
            else:
                skipped += 1
        except Exception as exc:
            errors.append({"symbol": sym, "scan_id": scan_id,
                           "error": str(exc)[:200]})

    return {
        "ok": True, "run_id": run_id,
        "total_entries": len(missed_entries),
        "ingested": ingested,
        "skipped_existing": skipped,
        "errors": errors,
        "batch_stats": batch_stats,
        "advisory_only": True,
        "note": ("Backtest missed opportunities ingested for advisory analysis. "
                 "No thresholds, strategies, or paper/live defaults were modified."),
    }


# ── Risk-rule learning ───────────────────────────────────────────────────────

def risk_rule_learning() -> Dict[str, Any]:
    """Per-gate effectiveness from stored missed-opportunity records:
    which rules save money vs block profitable trades. Advisory only."""
    opps = store.list_missed_opps(limit=5000)
    per_rule: Dict[str, Dict[str, Any]] = {}
    for o in opps:
        rec = o.get("record") or {}
        move = rec.get("later_max_move_pct")
        for gate in rec.get("rejected_by_gates") or []:
            r = per_rule.setdefault(gate, {
                "rule": gate, "rejections": 0, "evaluated": 0,
                "correct_rejections": 0, "blocked_profitable": 0,
                "avg_later_move_pct": None, "_moves": []})
            r["rejections"] += 1
            if move is not None:
                r["evaluated"] += 1
                r["_moves"].append(float(move))
                if rec.get("rejection_correct"):
                    r["correct_rejections"] += 1
                else:
                    r["blocked_profitable"] += 1
    rules = []
    for r in per_rule.values():
        moves = r.pop("_moves")
        if moves:
            r["avg_later_move_pct"] = round(sum(moves) / len(moves), 3)
        if r["evaluated"] >= 5:
            correct_rate = r["correct_rejections"] / r["evaluated"]
            r["effectiveness"] = round(correct_rate, 3)
            if correct_rate >= 0.6:
                r["verdict"] = "SAVES_MONEY"
            elif correct_rate <= 0.4:
                r["verdict"] = "BLOCKS_PROFITS"
            else:
                r["verdict"] = "MIXED"
        else:
            r["effectiveness"] = None
            r["verdict"] = "INSUFFICIENT_EVIDENCE"
        rules.append(r)
    rules.sort(key=lambda x: -x["rejections"])
    return {"rules": rules, "records_analysed": len(opps),
            "generated_at": _now(), "advisory_only": True,
            "note": "Rule effectiveness is advisory. No gate or threshold "
                    "is ever modified automatically."}
