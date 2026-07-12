"""
strategy_intelligence.py — Phase 2: Adaptive Strategy Selection & Dynamic
Portfolio Allocation.

Learns which strategies actually have an edge — overall AND per market
regime — from COMPLETED trades only, ranks them for the current regime,
disables deteriorating ones, and produces dynamic capital-allocation
weights.

Design rules
------------
- Pure python + sqlite; no sklearn/scipy.
- Performance scores update ONLY from completed trades (exit in the past).
  `trades_from_knowledge(as_of=...)` enforces the no-lookahead cutoff, and
  the walk-forward validator feeds back its own out-of-sample trades via
  `StrategyIntelligence.add_completed_trade`.
- Every enable/disable decision carries a human-readable reason.
"""

from __future__ import annotations

import math
import os
import sqlite3

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "trade_intelligence.db")

# ── Canonical market regimes (Phase 2 spec) ──────────────────────────────────

REGIMES = [
    "Bullish", "Bearish", "Neutral Bullish", "Neutral Bearish",
    "High Volatility", "Low Volatility", "Sideways",
]

_REGIME_ALIASES = {
    "bullish": "Bullish",
    "strong bullish": "Bullish",
    "bearish": "Bearish",
    "strong bearish": "Bearish",
    "neutral bullish": "Neutral Bullish",
    "neutral-bullish": "Neutral Bullish",
    "neutral bearish": "Neutral Bearish",
    "neutral-bearish": "Neutral Bearish",
    "high volatility": "High Volatility",
    "high_volatility": "High Volatility",
    "low volatility": "Low Volatility",
    "low_volatility": "Low Volatility",
    "sideways": "Sideways",
    "neutral": "Sideways",
    "unknown": "Sideways",
    "": "Sideways",
}


def normalize_regime(label: str | None) -> str:
    """Map any historical/live regime label onto the 7 canonical regimes."""
    return _REGIME_ALIASES.get(str(label or "").strip().lower(), "Sideways")


def classify_regime(closes: list[float], highs: list[float] | None = None,
                    lows: list[float] | None = None) -> str:
    """Classify the market into one of the 7 canonical regimes using ONLY
    the candles provided (caller is responsible for slicing as-of a date —
    no lookahead). `closes` should be ~55+ daily index closes."""
    n = len(closes)
    if n < 55:
        return "Sideways"

    def _ema(vals, span):
        k = 2.0 / (span + 1.0)
        e = vals[0]
        for v in vals[1:]:
            e = v * k + e * (1.0 - k)
        return e

    last = float(closes[-1])
    ema20 = _ema(closes, 20)
    ema50 = _ema(closes, 50)
    ret5 = (last - float(closes[-6])) / float(closes[-6]) * 100.0

    # Realized volatility: ATR% when highs/lows given, else close-to-close.
    if highs is not None and lows is not None and len(highs) == n and len(lows) == n:
        trs = []
        for i in range(max(1, n - 14), n):
            tr = max(highs[i] - lows[i],
                     abs(highs[i] - closes[i - 1]),
                     abs(lows[i] - closes[i - 1]))
            trs.append(tr)
        vol_pct = (sum(trs) / len(trs)) / last * 100.0 if trs and last > 0 else 2.0
        high_vol, low_vol = vol_pct > 3.5, vol_pct < 0.8
    else:
        rets = [(closes[i] - closes[i - 1]) / closes[i - 1]
                for i in range(n - 14, n) if closes[i - 1] > 0]
        mean = sum(rets) / len(rets) if rets else 0.0
        var = sum((r - mean) ** 2 for r in rets) / len(rets) if rets else 0.0
        vol_pct = math.sqrt(var) * 100.0
        high_vol, low_vol = vol_pct > 2.2, vol_pct < 0.45

    if high_vol:
        return "High Volatility"
    if low_vol:
        return "Low Volatility"
    if ema20 > ema50 * 1.005 and ret5 > 0.5:
        return "Bullish"
    if ema20 < ema50 * 0.995 and ret5 < -0.5:
        return "Bearish"
    if ema20 > ema50:
        return "Neutral Bullish"
    if ema20 < ema50:
        return "Neutral Bearish"
    return "Sideways"


# ── Per-strategy performance metrics ─────────────────────────────────────────

def compute_metrics(trades: list[dict]) -> dict:
    """Performance metrics for one list of completed trades. Each trade
    needs: return_pct, net_pnl (₹ or same currency), won (0/1)."""
    n = len(trades)
    if n == 0:
        return {"trade_count": 0, "net_return_pct": 0.0, "net_pnl": 0.0,
                "profit_factor": None, "win_rate": None, "expectancy_pct": None,
                "max_drawdown_pct": None, "sharpe": None}
    rets = [float(t.get("return_pct", 0.0) or 0.0) for t in trades]
    pnls = [float(t.get("net_pnl", 0.0) or 0.0) for t in trades]
    wins = sum(1 for t in trades if t.get("won"))
    gross_win = sum(p for p in pnls if p > 0)
    gross_loss = -sum(p for p in pnls if p < 0)
    if gross_loss > 1e-9:
        pf = round(min(gross_win / gross_loss, 99.0), 3)
    else:
        pf = 99.0 if gross_win > 0 else 0.0  # all winners / no completed P&L
    mean = sum(rets) / n
    var = sum((r - mean) ** 2 for r in rets) / n
    std = math.sqrt(var)
    sharpe = round(mean / std, 3) if std > 1e-9 else None
    # Max drawdown on the cumulative per-trade return curve (exit order)
    cum = peak = 0.0
    max_dd = 0.0
    for r in rets:
        cum += r
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
    return {
        "trade_count": n,
        "net_return_pct": round(sum(rets), 2),
        "net_pnl": round(sum(pnls), 2),
        "profit_factor": pf,
        "win_rate": round(wins / n * 100.0, 1),
        "expectancy_pct": round(mean, 3),
        "max_drawdown_pct": round(max_dd, 2),
        "sharpe": sharpe,
    }


def _sorted_by_exit(trades: list[dict]) -> list[dict]:
    return sorted(trades, key=lambda t: str(t.get("exit_date") or ""))


# ── Strategy intelligence (matrix, ranking, allocation) ──────────────────────

MIN_TRADES_FOR_JUDGEMENT = 10   # below this a strategy is "on probation"
ROLLING_WINDOW = 25             # rolling metrics use the last N trades
DISABLE_ROLLING_PF = 0.90       # rolling PF below this → disabled
DISABLE_REGIME_PF = 0.75        # regime PF below this → disabled in regime
MAX_STRATEGY_ALLOC = 0.40       # one strategy never gets >40% of allocation
MIN_ENABLED = 2                 # keep at least the 2 best enabled (diversify)


class StrategyIntelligence:
    """Adaptive strategy selector. Feed it completed trades only."""

    def __init__(self, trades: list[dict],
                 min_trades: int = MIN_TRADES_FOR_JUDGEMENT,
                 rolling_n: int = ROLLING_WINDOW):
        self.min_trades = min_trades
        self.rolling_n = rolling_n
        self._by_strategy: dict[str, list[dict]] = {}
        self._cache: dict = {}
        for t in trades:
            self._append(t)

    def _append(self, t: dict) -> None:
        sid = str(t.get("strategy_id") or t.get("strategy") or "").strip().lower()
        if not sid:
            return
        self._by_strategy.setdefault(sid, []).append({
            "strategy_id": sid,
            "return_pct": float(t.get("return_pct", t.get("return_percent", 0.0)) or 0.0),
            "net_pnl": float(t.get("net_pnl", t.get("profit_loss", 0.0)) or 0.0),
            "won": 1 if t.get("won", t.get("winning", t.get("win"))) else 0,
            "regime": normalize_regime(t.get("intel_regime") or t.get("regime")
                                       or t.get("market_regime")),
            "exit_date": str(t.get("exit_date") or "")[:10],
        })

    def add_completed_trade(self, trade: dict) -> None:
        """Adaptive learning hook: call ONLY when a trade has fully exited."""
        self._append(trade)
        self._cache.clear()

    @property
    def strategy_ids(self) -> list[str]:
        return sorted(self._by_strategy.keys())

    # ── Strategy-regime matrix ──────────────────────────────────────────

    def matrix(self) -> dict:
        """{strategy_id: {overall: metrics, by_regime: {regime: metrics},
        rolling: {...}}}"""
        if "matrix" in self._cache:
            return self._cache["matrix"]
        out = {}
        for sid, trades in self._by_strategy.items():
            ordered = _sorted_by_exit(trades)
            by_regime = {}
            for reg in REGIMES:
                sub = [t for t in ordered if t["regime"] == reg]
                if sub:
                    by_regime[reg] = compute_metrics(sub)
            recent = ordered[-self.rolling_n:]
            rm = compute_metrics(recent)
            out[sid] = {
                "overall": compute_metrics(ordered),
                "by_regime": by_regime,
                "rolling": {
                    "window": len(recent),
                    "profit_factor": rm["profit_factor"],
                    "sharpe": rm["sharpe"],
                    "expectancy_pct": rm["expectancy_pct"],
                    "win_rate": rm["win_rate"],
                },
            }
        self._cache["matrix"] = out
        return out

    # ── Ranking & enable/disable per regime ─────────────────────────────

    def _score(self, sid: str, regime: str) -> tuple[float, dict, dict]:
        m = self.matrix()[sid]
        regime_m = m["by_regime"].get(regime)
        basis = regime_m if (regime_m and regime_m["trade_count"] >= 5) \
            else m["overall"]
        pf = basis["profit_factor"] if basis["profit_factor"] is not None else 1.0
        exp = basis["expectancy_pct"] if basis["expectancy_pct"] is not None else 0.0
        wr = (basis["win_rate"] or 0.0) / 100.0
        roll_pf = m["rolling"]["profit_factor"]
        roll_pf = roll_pf if roll_pf is not None else 1.0
        # 0-100 score: PF 40%, expectancy 25%, win rate 15%, rolling PF 20%
        score = (min(pf, 3.0) / 3.0 * 40.0
                 + max(-1.0, min(1.0, exp / 2.0)) * 12.5 + 12.5
                 + wr * 15.0
                 + min(roll_pf, 3.0) / 3.0 * 20.0)
        return round(score, 2), basis, m

    def rank_for_regime(self, regime: str) -> list[dict]:
        """Rank all known strategies for a regime; mark enabled/disabled
        with reasons. Losing strategies are disabled unless that would
        leave fewer than MIN_ENABLED enabled (diversification floor)."""
        regime = normalize_regime(regime)
        key = ("rank", regime)
        if key in self._cache:
            return self._cache[key]
        rows = []
        for sid in self.strategy_ids:
            score, basis, m = self._score(sid, regime)
            overall = m["overall"]
            rolling = m["rolling"]
            regime_m = m["by_regime"].get(regime)
            enabled, reason = True, ""
            if overall["trade_count"] < 5:
                reason = (f"Probation — only {overall['trade_count']} completed "
                          "trades, not enough history to judge")
            elif (rolling["profit_factor"] is not None
                    and rolling["window"] >= self.min_trades
                    and rolling["profit_factor"] < DISABLE_ROLLING_PF):
                enabled = False
                reason = (f"Disabled — rolling profit factor "
                          f"{rolling['profit_factor']:.2f} over last "
                          f"{rolling['window']} trades (< {DISABLE_ROLLING_PF})")
            elif (regime_m is not None
                    and regime_m["trade_count"] >= self.min_trades
                    and regime_m["profit_factor"] is not None
                    and regime_m["profit_factor"] < DISABLE_REGIME_PF):
                enabled = False
                reason = (f"Disabled in {regime} — profit factor "
                          f"{regime_m['profit_factor']:.2f} across "
                          f"{regime_m['trade_count']} trades in this regime "
                          f"(< {DISABLE_REGIME_PF})")
            else:
                src = (f"{regime} history ({regime_m['trade_count']} trades)"
                       if regime_m and regime_m["trade_count"] >= 5
                       else f"overall history ({overall['trade_count']} trades)")
                reason = (f"Enabled — profit factor "
                          f"{(basis['profit_factor'] or 0):.2f}, expectancy "
                          f"{(basis['expectancy_pct'] or 0):+.2f}%/trade from {src}")
            rows.append({
                "strategy_id": sid, "score": score, "enabled": enabled,
                "reason": reason, "regime_metrics": regime_m,
                "overall_metrics": overall, "rolling": rolling,
                "basis": "regime" if (regime_m and regime_m["trade_count"] >= 5)
                         else "overall",
            })
        rows.sort(key=lambda r: -r["score"])
        # Diversification floor: never trade with fewer than MIN_ENABLED
        enabled_rows = [r for r in rows if r["enabled"]]
        if len(enabled_rows) < MIN_ENABLED:
            for r in rows:
                if len([x for x in rows if x["enabled"]]) >= MIN_ENABLED:
                    break
                if not r["enabled"]:
                    r["enabled"] = True
                    r["reason"] += (" · Re-enabled as one of the top "
                                    f"{MIN_ENABLED} (diversification floor)")
        for i, r in enumerate(rows):
            r["rank"] = i + 1
        self._cache[key] = rows
        return rows

    # ── Dynamic allocation weights ──────────────────────────────────────

    def allocation_weights(self, regime: str) -> dict[str, float]:
        """Capital weight per strategy for a regime. Disabled → 0. Enabled
        strategies get score-proportional weights, capped at
        MAX_STRATEGY_ALLOC and renormalised."""
        regime = normalize_regime(regime)
        key = ("alloc", regime)
        if key in self._cache:
            return self._cache[key]
        rows = self.rank_for_regime(regime)
        enabled = [r for r in rows if r["enabled"]]
        weights = {r["strategy_id"]: 0.0 for r in rows}
        if enabled:
            raw = {r["strategy_id"]: max(r["score"], 1.0) for r in enabled}
            total = sum(raw.values())
            w = {sid: v / total for sid, v in raw.items()}
            # Cap relaxes to equal-weight when few strategies are enabled so
            # weights always sum to 1 (all capital stays allocated).
            cap = max(MAX_STRATEGY_ALLOC, 1.0 / len(enabled))
            for _ in range(6):
                over = {sid: v for sid, v in w.items() if v > cap + 1e-12}
                if not over:
                    break
                excess = sum(v - cap for v in over.values())
                for sid in over:
                    w[sid] = cap
                under = {sid: v for sid, v in w.items() if v < cap - 1e-12}
                s = sum(under.values())
                if s <= 1e-12:
                    break
                for sid in under:
                    w[sid] += excess * (under[sid] / s)
            weights.update({sid: round(v, 4) for sid, v in w.items()})
        self._cache[key] = weights
        return weights

    def sizing_factor(self, strategy_id: str, regime: str) -> float:
        """Position-size multiplier vs equal-weight for this strategy in
        this regime. Disabled → 0. Bounded [0.5, 1.5] so allocation tilts
        rather than swamps stock-level sizing."""
        sid = str(strategy_id or "").strip().lower()
        weights = self.allocation_weights(regime)
        if sid not in weights:
            return 1.0  # unknown strategy → neutral
        w = weights[sid]
        if w <= 0.0:
            return 0.0
        n_enabled = sum(1 for v in weights.values() if v > 0)
        equal = 1.0 / n_enabled if n_enabled else 1.0
        return round(max(0.5, min(1.5, w / equal)), 3)

    def is_enabled(self, strategy_id: str, regime: str) -> bool:
        sid = str(strategy_id or "").strip().lower()
        for r in self.rank_for_regime(regime):
            if r["strategy_id"] == sid:
                return r["enabled"]
        return True  # unknown strategy → not judged

    # ── Full report (API/UI) ────────────────────────────────────────────

    def report(self, regime: str) -> dict:
        regime = normalize_regime(regime)
        rows = self.rank_for_regime(regime)
        weights = self.allocation_weights(regime)
        return {
            "regime": regime,
            "total_completed_trades": sum(
                len(v) for v in self._by_strategy.values()),
            "ranking": [{
                "rank": r["rank"],
                "strategy_id": r["strategy_id"],
                "score": r["score"],
                "enabled": r["enabled"],
                "reason": r["reason"],
                "basis": r["basis"],
                "allocation_pct": round(weights.get(r["strategy_id"], 0.0) * 100.0, 1),
                "rolling_profit_factor": r["rolling"]["profit_factor"],
                "rolling_sharpe": r["rolling"]["sharpe"],
                "rolling_expectancy_pct": r["rolling"]["expectancy_pct"],
                "rolling_window": r["rolling"]["window"],
                "overall": r["overall_metrics"],
                "in_regime": r["regime_metrics"],
            } for r in rows],
            "matrix": self.matrix(),
        }


# ── Data loading (no-lookahead) ──────────────────────────────────────────────

def trades_from_knowledge(as_of: str | None = None) -> list[dict]:
    """Completed trades from the historical knowledge base. When `as_of`
    (YYYY-MM-DD) is given, ONLY trades fully exited BEFORE that day are
    returned (no lookahead)."""
    try:
        conn = sqlite3.connect(DB_PATH)
        try:
            rows = conn.execute(
                "SELECT strategy, return_percent, profit_loss, winning, "
                "market_regime, exit_date FROM historical_knowledge_trades "
                "WHERE strategy IS NOT NULL AND strategy != '' "
                "AND winning IS NOT NULL "
                "AND exit_date IS NOT NULL AND exit_date != ''"
            ).fetchall()
        finally:
            conn.close()
    except Exception:
        return []
    out = []
    for strat, ret, pnl, won, regime, exit_date in rows:
        ed = str(exit_date)[:10]
        if as_of and ed >= str(as_of)[:10]:
            continue
        out.append({
            "strategy_id": strat, "return_pct": ret or 0.0,
            "net_pnl": pnl or 0.0, "won": won, "regime": regime,
            "exit_date": ed,
        })
    return out


_LIVE_CACHE: dict = {"intel": None, "ts": 0.0}
_LIVE_TTL_SECONDS = 300.0


def get_live_intelligence() -> StrategyIntelligence:
    """Cached (5 min) intelligence built from ALL completed knowledge
    trades — for the LIVE pipeline only (walk-forward must build per-window
    instances with as_of cutoffs instead)."""
    import time
    now = time.time()
    if (_LIVE_CACHE["intel"] is None
            or now - _LIVE_CACHE["ts"] > _LIVE_TTL_SECONDS):
        _LIVE_CACHE["intel"] = StrategyIntelligence(trades_from_knowledge())
        _LIVE_CACHE["ts"] = now
    return _LIVE_CACHE["intel"]
