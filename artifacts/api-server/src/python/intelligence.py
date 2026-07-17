"""
intelligence.py
Intelligence Layer Orchestrator.

Ties together all 6 intelligence modules into a single scan pipeline:

  1. Market Context Engine   — market_context.compute_market_context()
  2. Signal Engine           — signal_engine.scan_watchlist()
  3. Trade Quality Score     — trade_quality.compute_trade_quality()
  4. Position Sizing Engine  — position_sizer.compute_from_signal()
  5. AI Decision Engine      — ai_decision.scan_ai_decisions()
  6. Explainability Engine   — explainability.explain_trade()
  7. Opportunity Scanner     — opportunity_scanner.rank_opportunities()

UI receives: structured data with no business logic.
Backend owns: all computation, rules, thresholds.

Future Zerodha integration:
  - Replace paper_trader.execute_buy/sell with Zerodha kiteconnect calls
  - Replace signal_engine yfinance fetches with Zerodha market data
  - config.ZERODHA_ENABLED controls the switch
"""

import json
import os
from datetime import datetime
from typing import TypedDict

from market_regime import get_regime
from signal_engine import scan_watchlist
from market_context import compute_market_context, MarketContext
from trade_quality import compute_trade_quality, TradeQuality
from position_sizer import compute_from_signal, PositionSizing
from ai_decision import scan_ai_decisions, AiDecision
from explainability import explain_trade, ExplainabilityReport
from opportunity_scanner import rank_opportunities, OpportunityItem
from paper_trader import execute_buy, execute_sell, _load_state
from config import INITIAL_CAPITAL
import signals_store as _sig_store

STATE_DIR = os.path.dirname(os.path.abspath(__file__))

# Local file paths kept for backwards compatibility with modules that read
# these files directly (e.g. review_package.py, phase17_qa.py).
# signals_store.py also writes to these as warm-cache files.
SIGNALS_CACHE      = os.path.join(STATE_DIR, "signals_cache.json")
AI_CACHE           = os.path.join(STATE_DIR, "ai_decisions_cache.json")
OPPORTUNITY_CACHE  = os.path.join(STATE_DIR, "opportunity_cache.json")
MARKET_CTX_CACHE   = os.path.join(STATE_DIR, "market_context_cache.json")
INTELLIGENCE_CACHE = os.path.join(STATE_DIR, "intelligence_cache.json")


# ── TypedDict ─────────────────────────────────────────────────────────────────

class EnrichedSignal(TypedDict):
    """A signal enriched with all intelligence layer outputs."""
    # Core signal fields (passthrough)
    stock:              str
    signal:             str
    price:              float
    confidence:         float
    regime:             str
    timeframe_alignment: int
    risk_level:         str
    stop_loss:          float
    target:             float
    reasons:            list
    explanation:        dict
    time:               str
    # Intelligence layer additions
    trade_quality:      TradeQuality
    position_sizing:    PositionSizing
    ai_decision:        AiDecision
    explainability:     ExplainabilityReport


class IntelligenceScanResult(TypedDict):
    market_context:    MarketContext
    enriched_signals:  list[EnrichedSignal]
    ai_decisions:      list[AiDecision]
    opportunity_scan:  list[OpportunityItem]
    signals:           list[dict]           # raw signals (for backward compat)
    scanned_at:        str
    scan_duration_s:   float


EXECUTABLE_BUY  = {"STRONG_BUY", "BUY"}
EXECUTABLE_SELL = {"STRONG_SELL", "SELL"}


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _write_cache(path: str, data: object) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2, default=str)


def _read_cache(path: str) -> object:
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return None


# ── Trade execution ───────────────────────────────────────────────────────────

def _execute_trades(
    ai_decisions: list[dict],
    enriched_signals: list[dict],
    available_cash: float,
    opportunity_scan: list[dict] | None = None,
) -> float:
    """
    Execute paper trades based on AI decisions.
    Returns updated available cash after executions.
    """
    state    = _load_state()
    positions = state.get("positions", {})
    cash     = available_cash
    opp_by_stock = {
        str(o.get("stock", "")).upper(): o.get("opportunity_score", 0.0) or 0.0
        for o in (opportunity_scan or [])
    }

    for ai_dec, enr in zip(ai_decisions, enriched_signals):
        symbol   = ai_dec.get("stock", "")
        decision = ai_dec.get("decision", "NO_TRADE")
        price    = ai_dec.get("entry_price", 0.0)
        ps       = enr.get("position_sizing", {})
        qty      = ps.get("suggested_quantity", 0)

        if qty <= 0 or price <= 0:
            continue

        expl  = enr.get("explainability", {})
        approve_reasons = expl.get("approve_reasons", [])
        avoid_reasons   = expl.get("avoid_reasons", [])
        reason_str = "; ".join(approve_reasons[:2]) or f"AI: {decision}"

        if decision in EXECUTABLE_BUY:
            ok, msg = execute_buy(
                symbol, qty, price,
                reason            = reason_str,
                signal_confidence = ai_dec.get("confidence", 0.0),
                regime            = ai_dec.get("regime", "UNKNOWN"),
                ai_decision       = decision,
                rr_ratio          = ai_dec.get("rr_ratio", 0.0),
                target            = ai_dec.get("target", 0.0),
                stop_loss_price   = ai_dec.get("stop_loss", 0.0),
                plain_english     = expl.get("summary", ""),
                opportunity_score = opp_by_stock.get(
                    symbol.upper(), ai_dec.get("opportunity_score", 0.0) or 0.0
                ),
                trade_quality     = (enr.get("trade_quality") or {}).get("total_score", 0.0) or 0.0,
            )
            if ok:
                cash -= qty * price

        elif decision in EXECUTABLE_SELL:
            sym_upper = symbol.upper()
            if sym_upper in positions:
                held_qty = positions[sym_upper].get("quantity", 0)
                sell_qty = min(qty, held_qty)
                if sell_qty > 0:
                    target = ai_dec.get("target", 0.0)
                    stop   = ai_dec.get("stop_loss", 0.0)
                    if stop > 0 and price <= stop * 1.01:
                        exit_type = "STOP_HIT"
                    elif target > 0 and price >= target * 0.99:
                        exit_type = "TARGET_HIT"
                    else:
                        exit_type = "SIGNAL_EXIT"
                    execute_sell(
                        symbol, sell_qty, price,
                        reason    = "; ".join(avoid_reasons[:2]) or f"AI: {decision}",
                        exit_type = exit_type,
                    )

    return cash


# ── Main orchestrator ─────────────────────────────────────────────────────────

def run_intelligence_scan(
    watchlist: list[str],
    available_cash: float = INITIAL_CAPITAL,
    execute_trades: bool = True,
) -> IntelligenceScanResult:
    """
    Full intelligence pipeline scan.

    Args:
        watchlist       : list of NSE symbols
        available_cash  : current cash in paper portfolio
        execute_trades  : if True, execute paper trades from AI decisions

    Returns:
        IntelligenceScanResult with all intelligence layer outputs cached.
    """
    t_start = datetime.now()

    # 1. Market regime (yfinance: NIFTY + BANKNIFTY + VIX)
    regime_result = get_regime()

    # 2. Signal engine (yfinance: all watchlist stocks with MTF)
    signals = scan_watchlist(watchlist, available_cash=available_cash, regime=regime_result)

    # 3. Market context (no extra yfinance — uses regime + breadth from signals)
    market_ctx = compute_market_context(regime_result, signals)

    # 4. Per-signal intelligence layer
    trade_qualities:   list[TradeQuality]        = []
    position_sizes:    list[PositionSizing]       = []

    for sig in signals:
        tq = compute_trade_quality(sig, market_ctx)
        ps = compute_from_signal(sig, available_cash, capital=INITIAL_CAPITAL)
        trade_qualities.append(tq)
        position_sizes.append(ps)

    # 5. AI Decision Engine
    ai_decisions = scan_ai_decisions(signals, available_cash=available_cash)

    # 6. Explainability Engine
    explainabilities: list[ExplainabilityReport] = []
    for sig, ai_dec, tq, ps in zip(signals, ai_decisions, trade_qualities, position_sizes):
        expl = explain_trade(sig, ai_dec, tq, ps, market_ctx)
        explainabilities.append(expl)

    # 7. Opportunity Scanner
    opportunity_scan = rank_opportunities(
        signals, ai_decisions, trade_qualities,
        position_sizes, explainabilities, market_ctx,
    )

    # 8. Build enriched signals (all data per stock in one dict)
    enriched_signals: list[EnrichedSignal] = []
    for i, sig in enumerate(signals):
        enriched = dict(sig)
        enriched["trade_quality"]   = trade_qualities[i]   if i < len(trade_qualities)   else {}
        enriched["position_sizing"] = position_sizes[i]    if i < len(position_sizes)    else {}
        enriched["ai_decision"]     = ai_decisions[i]      if i < len(ai_decisions)      else {}
        enriched["explainability"]  = explainabilities[i]  if i < len(explainabilities)  else {}
        enriched_signals.append(enriched)  # type: ignore

    # 9. Execute paper trades
    if execute_trades:
        _execute_trades(ai_decisions, enriched_signals, available_cash,
                        opportunity_scan=opportunity_scan)

    # 10. Cache everything — primary store is Postgres; local files are warm cache
    _sig_store.save_signals(signals)
    _sig_store.save_ai_decisions(ai_decisions)
    _sig_store.save_opportunity_scan(opportunity_scan)
    _sig_store.save_market_context(market_ctx)
    # enriched signals (combined intelligence) are file-only (large, derived)
    _write_cache(INTELLIGENCE_CACHE, enriched_signals)

    # 10b. Append an immutable history snapshot (one row per scan, keyed by
    # the canonical scan_id when available). Non-fatal: history persistence
    # must never break a live scan.
    try:
        _append_history_snapshot(signals, market_ctx, t_start)
    except Exception as exc:
        import logging
        logging.getLogger(__name__).warning(
            "signal history snapshot append failed: %s", exc)

    # Reconcile the freshly written derived caches with the canonical scan so
    # no page shows independently recalculated stop loss / target / RR values.
    try:
        from phase15_sync import sync_derived_caches
        sync_derived_caches()
    except Exception:
        pass

    scan_duration = (datetime.now() - t_start).total_seconds()

    return IntelligenceScanResult(
        market_context   = market_ctx,
        enriched_signals = enriched_signals,
        ai_decisions     = ai_decisions,
        opportunity_scan = opportunity_scan,
        signals          = signals,
        scanned_at       = t_start.isoformat(),
        scan_duration_s  = round(scan_duration, 2),
    )


# ── Signal history snapshot helper ────────────────────────────────────────────

def _append_history_snapshot(signals: list, market_ctx: dict,
                             t_start: datetime) -> None:
    """Append one signal_snapshots row for this intelligence run.

    Every run gets its OWN generated scan_id so each scan reliably appends a
    new history row. The canonical phase7 scan_id (which may be shared by
    several intelligence runs) is stored separately for correlation only.
    """
    import uuid
    scan_id = f"intel-{t_start.strftime('%Y%m%dT%H%M%S')}-{uuid.uuid4().hex[:8]}"

    canonical_scan_id = None
    try:
        from scan_state_store import load_latest_snapshot
        snap = load_latest_snapshot()
        if isinstance(snap, dict) and snap.get("scan_id"):
            canonical_scan_id = str(snap["scan_id"])
    except Exception:
        pass

    _sig_store.append_signal_snapshot(
        scan_id, signals, market_ctx,
        snapshot_ts=t_start.astimezone().isoformat(),
        canonical_scan_id=canonical_scan_id,
    )

    # Retention: keep every snapshot for 30 days, thin older history to one
    # snapshot per day. Best-effort — pruning must never fail the scan.
    try:
        result = _sig_store.prune_signal_snapshots()
        if result.get("deleted"):
            print(f"[intelligence] signal history pruned: "
                  f"{result['deleted']} old snapshot(s) removed")
    except Exception as exc:
        print(f"[intelligence] signal history prune skipped: {exc}")


# ── Cache readers (used by API endpoints) ─────────────────────────────────────

def get_cached_opportunity_scan() -> list:
    return _sig_store.load_opportunity_scan() or []


def get_cached_market_context() -> dict:
    return _sig_store.load_market_context() or {}


def get_cached_enriched_signals() -> list:
    return _read_cache(INTELLIGENCE_CACHE) or []
