"""
signal_validation_lifecycle.py — Phase 5C lifecycle state machine.

Every state transition is:
  - validated against allowed transitions
  - logged with timestamp, reason, source, and correlation ID
  - persisted atomically

No silent transitions permitted.

PAPER TRADING / ADVISORY ONLY.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

from signal_validation_model import (
    LifecycleState, SignalValidationRecord, LifecycleEvent, is_enabled,
)
import signal_validation_db as db

_IST = timezone(timedelta(hours=5, minutes=30))


def _now_ist() -> str:
    return datetime.now(_IST).isoformat()


class InvalidTransitionError(Exception):
    pass


def transition(
    rec: SignalValidationRecord,
    to_state: str,
    reason: str,
    source_component: str,
    correlation_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    persist: bool = True,
) -> SignalValidationRecord:
    """
    Apply a state transition to a SignalValidationRecord.
    Raises InvalidTransitionError if the transition is not permitted.
    Logs a LifecycleEvent and persists the updated record.

    Returns the mutated record.
    """
    from_state = rec.validation_status

    if not LifecycleState.is_valid_transition(from_state, to_state):
        raise InvalidTransitionError(
            f"Invalid transition: {from_state} → {to_state} "
            f"(signal={rec.signal_id}, component={source_component})"
        )

    rec.validation_status = to_state
    rec.updated_at = _now_ist()

    evt = LifecycleEvent(
        validation_id    = rec.validation_id,
        event_id         = f"evt-{uuid.uuid4().hex[:10]}",
        from_state       = from_state,
        to_state         = to_state,
        timestamp_ist    = _now_ist(),
        reason           = reason,
        source_component = source_component,
        correlation_id   = correlation_id or rec.validation_id,
        metadata         = metadata or {},
    )

    if persist and is_enabled():
        db.insert_lifecycle_event(evt.to_dict())
        db.upsert_record(rec.to_dict())

    return rec


def record_from_signal(signal: dict, session_id: str, trading_date: str) -> SignalValidationRecord:
    """
    Bootstrap a SignalValidationRecord from an existing signal dict.
    Reads from signals_cache schema (stock, signal, confidence, price, etc.).
    """
    from decimal import Decimal

    signal_id = signal.get("id") or signal.get("signal_id") or f"sig-{uuid.uuid4().hex[:8]}"

    rec = SignalValidationRecord(
        validation_id        = f"sv-{trading_date}-{signal_id[:12]}-{uuid.uuid4().hex[:4]}",
        trading_date         = trading_date,
        session_id           = session_id,
        signal_id            = signal_id,
        strategy_id          = signal.get("strategy_id") or signal.get("strategy") or "unknown",
        strategy_name        = signal.get("strategy_name") or signal.get("strategy") or "Unknown",
        strategy_version     = signal.get("strategy_version") or "1.0",
        symbol               = signal.get("stock") or signal.get("symbol") or "",
        sector               = signal.get("sector") or "",
        exchange             = "NSE",
        signal_direction     = signal.get("signal") or signal.get("direction") or "",
        signal_type          = signal.get("signal") or "",
        signal_timestamp_ist = signal.get("time") or signal.get("timestamp") or _now_ist(),
        signal_price         = _dec(signal.get("price")),
        signal_strength      = _dec(signal.get("strength") or signal.get("opportunity_score")),
        deterministic_score  = _dec(signal.get("deterministic_score") or signal.get("confidence")),
        AI_recommendation    = _ai_rec(signal),
        AI_confidence        = _dec(signal.get("ai_confidence") or signal.get("confidence")),
        AI_agreement         = _ai_agree(signal),
        market_regime        = signal.get("regime") or signal.get("market_regime"),
        liquidity_score      = _dec(signal.get("liquidity_score")),
        stop_loss            = _dec(signal.get("stop_loss")),
        target_price         = _dec(signal.get("target")),
        data_quality_status  = signal.get("data_quality_status") or "UNKNOWN",
        risk_decision        = signal.get("risk_decision") or "",
        validation_status    = LifecycleState.GENERATED,
        created_at           = _now_ist(),
        updated_at           = _now_ist(),
    )

    # Pre-open context (from Phase 5A)
    po = signal.get("preopen_context") or {}
    if po:
        rec.preopen_rank             = po.get("rank")
        rec.preopen_opportunity_score = _dec(po.get("opportunity_score"))
        rec.preopen_classification   = po.get("classification")

    return rec


def _dec(v):
    if v is None:
        return None
    try:
        from decimal import Decimal
        return Decimal(str(v))
    except Exception:
        return None


def _ai_rec(signal: dict) -> Optional[str]:
    exp = signal.get("explanation") or {}
    if isinstance(exp, dict):
        return exp.get("recommendation") or exp.get("signal")
    return None


def _ai_agree(signal: dict) -> Optional[str]:
    """Derive AI agreement from signal fields."""
    ai_conf = signal.get("ai_confidence") or signal.get("confidence", 0)
    sig = signal.get("signal") or ""
    exp = signal.get("explanation") or {}
    if not exp:
        return "NO_RESULT"
    # If both deterministic and AI agree on direction
    if isinstance(exp, dict):
        ai_sig = exp.get("signal") or exp.get("recommendation") or ""
        if "BUY" in sig and "BUY" in str(ai_sig).upper():
            return "AGREE"
        if "SELL" in sig and "SELL" in str(ai_sig).upper():
            return "AGREE"
        if "WATCH" in str(ai_sig).upper():
            return "WATCH"
        if ai_sig:
            return "DISAGREE"
    return "NO_RESULT"


_TRADE_MATCH_WINDOW_SECONDS = 1800  # 30-minute timestamp tolerance


def _find_matching_paper_trade(
    rec: SignalValidationRecord,
    trades: list,
    claimed_ids: Optional[set] = None,
) -> Optional[dict]:
    """
    Find the best-matching paper trade for a validation record.
    Priority (highest to lowest confidence):
      1. Trade whose ``reason`` field contains the signal_id (exact FK match).
      2. Closest-in-time unclaimed trade matching symbol + action, within
         _TRADE_MATCH_WINDOW_SECONDS of the signal timestamp.
      3. If multiple candidates tie on proximity, pick the smallest-quantity
         trade (more likely a partial first fill) — still an unclaimed one.

    A trade is "claimed" if its id appears in *claimed_ids*.  Callers should
    pass the same set across calls to prevent a single trade from being matched
    to multiple validation records.

    Returns None when no unambiguous match is found.
    """
    if not trades:
        return None

    symbol    = rec.symbol
    direction = (rec.signal_direction or "").upper()
    action    = "BUY" if "BUY" in direction else "SELL"
    signal_id = rec.signal_id or ""
    if claimed_ids is None:
        claimed_ids = set()

    # ── Priority 1: exact signal_id match in trade.reason ─────────────────────
    for trade in trades:
        if trade.get("id") in claimed_ids:
            continue
        reason = str(trade.get("reason") or "")
        if signal_id and signal_id in reason:
            return trade

    # ── Priority 2: symbol + action + timestamp proximity ─────────────────────
    # Parse signal timestamp
    sig_ts: Optional[float] = None
    sig_ts_str = rec.signal_timestamp_ist or ""
    if sig_ts_str:
        try:
            from datetime import datetime
            sig_ts = datetime.fromisoformat(sig_ts_str.replace("Z", "+00:00")).timestamp()
        except Exception:
            pass

    candidates = []
    for trade in trades:
        if trade.get("id") in claimed_ids:
            continue
        if trade.get("symbol") != symbol:
            continue
        if trade.get("action", "").upper() != action:
            continue

        # Timestamp proximity
        trade_ts_str = str(trade.get("timestamp") or trade.get("trade_ts") or "")
        proximity = float("inf")
        if sig_ts and trade_ts_str:
            try:
                from datetime import datetime
                t_ts = datetime.fromisoformat(
                    trade_ts_str.replace("Z", "+00:00")).timestamp()
                proximity = abs(t_ts - sig_ts)
            except Exception:
                pass

        if proximity <= _TRADE_MATCH_WINDOW_SECONDS:
            candidates.append((proximity, trade))

    if not candidates:
        return None

    # Sort by proximity (closest first), then by quantity (smallest first) for
    # tie-breaking — avoids picking a large block trade over a targeted fill.
    candidates.sort(key=lambda x: (x[0], float(x[1].get("quantity") or 0)))
    return candidates[0][1]


def advance_lifecycle_from_signal(
    rec: SignalValidationRecord,
    signal: dict,
    paper_trades: Optional[list] = None,
    claimed_trade_ids: Optional[set] = None,
) -> SignalValidationRecord:
    """
    Advance a newly ingested GENERATED record through lifecycle states using
    available signal metadata and correlated paper trades.

    Progression (stops at the last provable state):
      GENERATED → AI_REVIEWED     (if explanation dict is present)
      AI_REVIEWED → RISK_REVIEWED  (signals in signals_cache are post-risk-review)
      RISK_REVIEWED → RISK_REJECTED (if signal.risk_decision == "REJECTED")
      RISK_REVIEWED → APPROVED     (default: absence of rejection = approved)
      APPROVED → PAPER_ORDER_CREATED → PAPER_ORDER_FILLED → OPEN_POSITION
                                   (if a matching paper trade exists for today)

    claimed_trade_ids — shared mutable set across a batch; when a paper trade is
    matched it is added here so the same trade cannot be assigned to multiple signals.

    Uses transition() for every state move so every change is audit-logged.
    Never blocks on incomplete data — stops at the last provable state.

    PAPER TRADING / ADVISORY ONLY.
    """
    from decimal import Decimal

    # ── Step 1: GENERATED → AI_REVIEWED ──────────────────────────────────────
    explanation = signal.get("explanation")
    has_ai = bool(explanation) and isinstance(explanation, dict)

    if (rec.validation_status == LifecycleState.GENERATED
            and has_ai
            and LifecycleState.is_valid_transition(
                LifecycleState.GENERATED, LifecycleState.AI_REVIEWED)):

        # Hydrate AI fields from explanation
        ai_rec = explanation.get("recommendation") or explanation.get("signal") or ""
        rec.AI_recommendation = ai_rec
        if not rec.AI_agreement:
            sig_dir = (signal.get("signal") or "").upper()
            ai_dir  = ai_rec.upper()
            if "BUY" in sig_dir and "BUY" in ai_dir:
                rec.AI_agreement = "AGREE"
            elif "SELL" in sig_dir and "SELL" in ai_dir:
                rec.AI_agreement = "AGREE"
            elif "WATCH" in ai_dir:
                rec.AI_agreement = "WATCH"
            elif ai_dir:
                rec.AI_agreement = "DISAGREE"
            else:
                rec.AI_agreement = "NO_RESULT"

        transition(rec, LifecycleState.AI_REVIEWED,
                   reason="AI explanation present in signal",
                   source_component="signal_validation_lifecycle.advance",
                   persist=is_enabled())

    # ── Step 2: → RISK_REVIEWED ───────────────────────────────────────────────
    # Signals in signals_cache have already passed through the risk engine.
    # Advance to RISK_REVIEWED unconditionally if still in a pre-review state.
    if rec.validation_status in (
            LifecycleState.GENERATED, LifecycleState.AI_REVIEWED) and \
            LifecycleState.is_valid_transition(
                rec.validation_status, LifecycleState.RISK_REVIEWED):

        transition(rec, LifecycleState.RISK_REVIEWED,
                   reason="Signal sourced from signals_cache (post-risk-review)",
                   source_component="signal_validation_lifecycle.advance",
                   persist=is_enabled())

    # ── Step 3: → APPROVED or RISK_REJECTED ───────────────────────────────────
    if rec.validation_status == LifecycleState.RISK_REVIEWED:
        risk_decision = (signal.get("risk_decision") or "").upper()
        if risk_decision in ("REJECTED", "RISK_REJECTED", "DENY"):
            rec.risk_decision          = "REJECTED"
            rec.risk_rejection_reason  = signal.get("risk_rejection_reason") or "unspecified"
            rec.is_hypothetical        = True
            rec.hypothetical_label     = "HYPOTHETICAL — NOT A TRADE"
            transition(rec, LifecycleState.RISK_REJECTED,
                       reason=f"Risk rejection: {rec.risk_rejection_reason}",
                       source_component="signal_validation_lifecycle.advance",
                       persist=is_enabled())
            return rec
        else:
            rec.risk_decision = "APPROVED"
            transition(rec, LifecycleState.APPROVED,
                       reason="No risk rejection — signal approved",
                       source_component="signal_validation_lifecycle.advance",
                       persist=is_enabled())

    # ── Step 4: Correlate with paper trades → OPEN_POSITION ──────────────────
    if rec.validation_status == LifecycleState.APPROVED and paper_trades:
        matching = _find_matching_paper_trade(
            rec, paper_trades, claimed_ids=claimed_trade_ids)
        if matching:
            trade_id = matching.get("id")
            rec.paper_order_id         = trade_id
            rec.entry_price            = _dec(matching.get("price"))
            rec.entry_timestamp        = (str(matching.get("timestamp") or "")
                                          or str(matching.get("trade_ts") or "")
                                          or _now_ist())
            rec.approved_position_size = int(matching.get("quantity") or 1)
            rec.paper_order_created    = True

            # Mark this trade as claimed so it cannot match any other signal
            if claimed_trade_ids is not None and trade_id:
                claimed_trade_ids.add(trade_id)

            if LifecycleState.is_valid_transition(
                    LifecycleState.APPROVED, LifecycleState.PAPER_ORDER_CREATED):
                transition(rec, LifecycleState.PAPER_ORDER_CREATED,
                           reason="Matched to paper trade via deterministic correlation",
                           source_component="signal_validation_lifecycle.advance",
                           metadata={"paper_trade_id": trade_id},
                           persist=is_enabled())

            if LifecycleState.is_valid_transition(
                    LifecycleState.PAPER_ORDER_CREATED, LifecycleState.PAPER_ORDER_FILLED):
                transition(rec, LifecycleState.PAPER_ORDER_FILLED,
                           reason="Paper order filled at recorded price",
                           source_component="signal_validation_lifecycle.advance",
                           persist=is_enabled())

            if LifecycleState.is_valid_transition(
                    LifecycleState.PAPER_ORDER_FILLED, LifecycleState.OPEN_POSITION):
                transition(rec, LifecycleState.OPEN_POSITION,
                           reason="Position opened — awaiting price checkpoints",
                           source_component="signal_validation_lifecycle.advance",
                           persist=is_enabled())

    return rec


def close_position(
    rec: SignalValidationRecord,
    exit_price,
    exit_reason: str = "EOD_CLOSE",
    source_component: str = "signal_validation_lifecycle.close_position",
) -> SignalValidationRecord:
    """
    Close an OPEN_POSITION or PAPER_ORDER_FILLED record.
    Computes realised P&L and R-multiple, then transitions to CLOSED_POSITION.
    """
    from decimal import Decimal

    if rec.validation_status not in (
            LifecycleState.OPEN_POSITION, LifecycleState.PAPER_ORDER_FILLED):
        return rec

    if exit_price is not None:
        rec.exit_price     = _dec(exit_price)
        rec.exit_timestamp = _now_ist()
        rec.exit_reason    = exit_reason
        rec.realised_pnl   = rec.compute_realised_pnl()
        rec.R_multiple     = rec.compute_r_multiple()

    if LifecycleState.is_valid_transition(rec.validation_status, LifecycleState.CLOSED_POSITION):
        transition(rec, LifecycleState.CLOSED_POSITION,
                   reason=f"Position closed: {exit_reason}",
                   source_component=source_component,
                   persist=is_enabled())
    return rec


def ingest_signal_batch(
    signals: list,
    session_id: str,
    trading_date: str,
    paper_trades: Optional[list] = None,
    claimed_trade_ids: Optional[set] = None,
) -> Dict[str, Any]:
    """
    Ingest a batch of signals from signals_cache / signal_snapshots.

    For each NEW signal:
      1. Creates a GENERATED SignalValidationRecord (with lifecycle event).
      2. Immediately advances through AI/RISK/FILL states using available
         signal metadata and correlated paper trades (advance_lifecycle_from_signal).
      3. Persists the final record state.

    Skips signals already ingested (idempotent on signal_id + trading_date).
    Returns {ingested, skipped, errors, advanced}.
    """
    if not is_enabled():
        return {"ingested": 0, "skipped": 0, "errors": 0, "advanced": 0,
                "reason": "SIGNAL_VALIDATION_ENABLED=false"}

    # claimed_trade_ids may be injected by the caller (e.g. _run_ingest_signals
    # pre-seeds it from ALL DB records with a paper_order_id so that new-ingest
    # and re-advance passes in the same tick share claim state).
    # If None, create a local set for this batch only.
    if claimed_trade_ids is None:
        claimed_trade_ids = set()

    ingested = skipped = errors = advanced = 0
    for sig in signals:
        signal_id = sig.get("id") or sig.get("signal_id")
        if not signal_id:
            errors += 1
            continue
        existing = db.get_record_by_signal_id(signal_id, trading_date)
        if existing:
            skipped += 1
            continue
        try:
            rec = record_from_signal(sig, session_id, trading_date)

            # Persist initial GENERATED state + audit event
            db.upsert_record(rec.to_dict())
            db.insert_lifecycle_event(LifecycleEvent(
                validation_id    = rec.validation_id,
                event_id         = f"evt-{uuid.uuid4().hex[:10]}",
                from_state       = "NEW",
                to_state         = LifecycleState.GENERATED,
                timestamp_ist    = rec.created_at,
                reason           = "Signal ingested from signals_cache",
                source_component = "signal_validation_lifecycle.ingest_signal_batch",
                correlation_id   = rec.validation_id,
            ).to_dict())
            ingested += 1

            # Advance lifecycle as far as signal data allows.
            # claimed_trade_ids is shared so duplicate trade matching is
            # prevented across multiple signals in the same pass AND across
            # the new-ingest and re-advance passes within the same tick.
            start_status = rec.validation_status
            advance_lifecycle_from_signal(
                rec, sig,
                paper_trades=paper_trades,
                claimed_trade_ids=claimed_trade_ids,
            )
            if rec.validation_status != start_status:
                advanced += 1

        except Exception:
            errors += 1

    return {"ingested": ingested, "skipped": skipped, "errors": errors, "advanced": advanced}
