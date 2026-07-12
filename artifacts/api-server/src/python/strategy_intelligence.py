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
MIN_ENABLED = 2                 # legacy policy only: diversification floor

# ── Phase 2A: corrected (gated) policy ───────────────────────────────────────
# The legacy policy above is kept EXACTLY as-is so walk-forward variant C
# reproduces the previous behavior. The gated policy below powers variants
# D (default gates) and E (strict gates). ANALYSIS ONLY — the live pipeline
# stays on the legacy policy until the corrected one is explicitly approved.

SHRINK_K = 30                   # Bayesian shrinkage pseudo-count (toward PF 1.0 / expectancy 0)
MIN_REGIME_SAMPLE = 20          # exact-regime evidence needs at least this many trades
PERIOD_BLOCK = 25               # stability periods = consecutive blocks of N trades

# Status categories (spec §7)
ST_ENABLED = "ENABLED"
ST_WATCHLIST = "WATCHLIST"
ST_NEG_EDGE = "DISABLED_NEGATIVE_EDGE"
ST_INSUFFICIENT = "DISABLED_INSUFFICIENT_SAMPLE"
ST_UNSTABLE = "DISABLED_UNSTABLE"
ST_REGIME_MISMATCH = "DISABLED_REGIME_MISMATCH"
ST_CASH_ONLY = "CASH_ONLY"

GATES_DEFAULT = {
    "name": "default",
    "min_trades": 30,             # completed training trades
    "min_rolling_pf": 1.10,       # rolling PF must be >= this
    "min_rolling_expectancy": 0.0,  # rolling expectancy (after costs) must be > this
    "min_rolling_net_return": 0.0,  # rolling net return (after costs) must be > this
    "max_drawdown_pct": 25.0,     # cumulative per-trade drawdown limit
    "min_positive_periods": 1,    # blocks of PERIOD_BLOCK trades with net pnl > 0
    "max_flip_rate": 0.60,        # sign flips between consecutive periods
}

GATES_STRICT = {
    "name": "strict",
    "min_trades": 50,
    "min_rolling_pf": 1.20,
    "min_rolling_expectancy": 0.0,
    "min_rolling_net_return": 0.0,
    "max_drawdown_pct": 25.0,
    "min_positive_periods": 2,    # positive in >= 2 independent periods
    "max_flip_rate": 0.60,
}

# Evidence hierarchy (spec §5): exact regime → related regimes → global
RELATED_REGIMES = {
    "Bullish": ["Neutral Bullish"],
    "Neutral Bullish": ["Bullish", "Sideways"],
    "Bearish": ["Neutral Bearish"],
    "Neutral Bearish": ["Bearish", "Sideways"],
    "High Volatility": ["Bearish", "Neutral Bearish"],
    "Low Volatility": ["Sideways", "Neutral Bullish"],
    "Sideways": ["Neutral Bullish", "Neutral Bearish", "Low Volatility"],
}


def shrink_metrics(metrics: dict, k: int = SHRINK_K) -> dict:
    """Bayesian shrinkage toward neutral performance (PF 1.0, expectancy 0)
    with pseudo-count k. Small samples are pulled strongly toward neutral so
    PF 2.0 over 5 trades cannot outrank PF 1.3 over 150 trades."""
    n = int(metrics.get("trade_count") or 0)
    raw_pf = metrics.get("profit_factor")
    raw_exp = metrics.get("expectancy_pct")
    w = n / (n + k) if (n + k) > 0 else 0.0
    adj_pf = None if raw_pf is None else round(raw_pf * w + 1.0 * (1.0 - w), 3)
    adj_exp = None if raw_exp is None else round(raw_exp * w, 3)
    return {
        "sample": n,
        "raw_profit_factor": raw_pf,
        "adjusted_profit_factor": adj_pf,
        "raw_expectancy_pct": raw_exp,
        "adjusted_expectancy_pct": adj_exp,
        "shrink_weight": round(w, 3),
    }


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


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

    # ══ Phase 2A: corrected (gated) policy ══════════════════════════════
    # Everything below is a PARALLEL path — the legacy methods above are
    # untouched so variant C reproduces the previous behavior exactly.

    def _ordered(self, sid: str) -> list[dict]:
        return _sorted_by_exit(self._by_strategy.get(sid, []))

    def _stability(self, sid: str) -> dict:
        """Split completed trades (exit order) into consecutive blocks of
        PERIOD_BLOCK trades. Counts positive periods and the rate of sign
        flips between consecutive periods (flip-flopping = unstable)."""
        key = ("stability", sid)
        if key in self._cache:
            return self._cache[key]
        ordered = self._ordered(sid)
        blocks = []
        for i in range(0, len(ordered), PERIOD_BLOCK):
            chunk = ordered[i:i + PERIOD_BLOCK]
            if len(chunk) >= max(10, PERIOD_BLOCK // 2):
                blocks.append(sum(float(t["net_pnl"]) for t in chunk))
        positive = sum(1 for b in blocks if b > 0)
        flips = sum(1 for a, b in zip(blocks, blocks[1:])
                    if (a > 0) != (b > 0))
        flip_rate = flips / (len(blocks) - 1) if len(blocks) > 1 else 0.0
        out = {"periods": len(blocks), "positive_periods": positive,
               "flip_rate": round(flip_rate, 3)}
        self._cache[key] = out
        return out

    def evidence_for(self, sid: str, regime: str) -> dict:
        """Evidence hierarchy (spec §5): exact regime when sufficiently
        sampled → related regimes → global history. Returns the metrics
        basis actually used plus level / sample / fallback reason /
        reliability classification."""
        regime = normalize_regime(regime)
        key = ("evidence", sid, regime)
        if key in self._cache:
            return self._cache[key]
        m = self.matrix().get(sid, {})
        by_regime = m.get("by_regime", {})
        overall = m.get("overall", compute_metrics([]))
        exact = by_regime.get(regime)
        exact_n = exact["trade_count"] if exact else 0

        level, basis, fallback = "regime", exact, ""
        if exact_n < MIN_REGIME_SAMPLE:
            related = RELATED_REGIMES.get(regime, [])
            rel_trades = [t for t in self._ordered(sid)
                          if t["regime"] == regime or t["regime"] in related]
            if len(rel_trades) >= MIN_REGIME_SAMPLE:
                level = "related_regimes"
                basis = compute_metrics(rel_trades)
                fallback = (f"Only {exact_n} trades in {regime} "
                            f"(< {MIN_REGIME_SAMPLE}) — using {regime} + "
                            f"related regimes ({', '.join(related)})")
            else:
                level = "global"
                basis = overall
                fallback = (f"Only {exact_n} trades in {regime} and "
                            f"{len(rel_trades)} incl. related regimes "
                            f"(< {MIN_REGIME_SAMPLE}) — using global history")
        n = basis["trade_count"] if basis else 0
        reliability = ("high" if n >= 50 else
                       "medium" if n >= 30 else "low")
        out = {
            "level": level,
            "sample": n,
            "fallback_reason": fallback,
            "reliability": reliability,
            "metrics": basis or compute_metrics([]),
            "regime_sample": exact_n,
        }
        self._cache[key] = out
        return out

    def _gate_check(self, sid: str, regime: str, gates: dict) -> dict:
        """Hard eligibility gates (spec §2). Returns status, reason and
        every gate's pass/fail detail."""
        m = self.matrix()[sid]
        overall = m["overall"]
        ordered = self._ordered(sid)
        rolling_trades = ordered[-self.rolling_n:]
        rolling = compute_metrics(rolling_trades)
        evidence = self.evidence_for(sid, regime)
        stability = self._stability(sid)
        ev_shrunk = shrink_metrics(evidence["metrics"])

        checks = []

        def _chk(name, passed, detail):
            checks.append({"gate": name, "passed": bool(passed), "detail": detail})
            return bool(passed)

        n = overall["trade_count"]
        ok_sample = _chk(
            "min_trades", n >= gates["min_trades"],
            f"{n} completed trades (need >= {gates['min_trades']})")
        roll_pf = rolling["profit_factor"]
        ok_pf = _chk(
            "rolling_profit_factor",
            roll_pf is not None and roll_pf >= gates["min_rolling_pf"],
            f"rolling PF {roll_pf if roll_pf is not None else 'n/a'} over last "
            f"{rolling['trade_count']} trades (need >= {gates['min_rolling_pf']})")
        roll_exp = rolling["expectancy_pct"]
        ok_exp = _chk(
            "rolling_expectancy",
            roll_exp is not None and roll_exp > gates["min_rolling_expectancy"],
            f"rolling expectancy {roll_exp if roll_exp is not None else 'n/a'}%/trade "
            f"after costs (need > {gates['min_rolling_expectancy']})")
        roll_ret = rolling["net_return_pct"]
        ok_ret = _chk(
            "rolling_net_return",
            roll_ret is not None and roll_ret > gates["min_rolling_net_return"],
            f"rolling net return {roll_ret}% after costs "
            f"(need > {gates['min_rolling_net_return']})")
        dd = overall["max_drawdown_pct"] or 0.0
        ok_dd = _chk(
            "max_drawdown", dd <= gates["max_drawdown_pct"],
            f"max drawdown {dd}% (limit {gates['max_drawdown_pct']}%)")
        ok_stable = _chk(
            "stability",
            stability["flip_rate"] <= gates["max_flip_rate"]
            and (stability["periods"] < gates["min_positive_periods"] + 1
                 or stability["positive_periods"] >= gates["min_positive_periods"]),
            f"{stability['positive_periods']}/{stability['periods']} positive "
            f"periods, flip rate {stability['flip_rate']} "
            f"(need >= {gates['min_positive_periods']} positive, "
            f"flip <= {gates['max_flip_rate']})")
        if gates["min_positive_periods"] >= 2:
            # strict gates: demand the evidence itself, not just recency
            ok_stable = ok_stable and _chk(
                "independent_periods",
                stability["positive_periods"] >= gates["min_positive_periods"],
                f"{stability['positive_periods']} positive periods "
                f"(strict gate needs >= {gates['min_positive_periods']})")
        adj_pf = ev_shrunk["adjusted_profit_factor"]
        ok_regime = _chk(
            "regime_edge",
            evidence["level"] != "regime" or adj_pf is None or adj_pf >= 1.0,
            f"adjusted PF {adj_pf} on {evidence['level']} evidence "
            f"({evidence['sample']} trades)")

        if not ok_sample:
            status = ST_INSUFFICIENT
            reason = f"Insufficient sample — {checks[0]['detail']}"
        elif not ok_regime:
            status = ST_REGIME_MISMATCH
            reason = (f"Regime mismatch — adjusted PF {adj_pf} < 1.00 on "
                      f"{evidence['sample']} trades in {normalize_regime(regime)}")
        elif not (ok_pf and ok_exp and ok_ret):
            failed = [c["detail"] for c in checks[1:4] if not c["passed"]]
            status = ST_NEG_EDGE
            reason = "Negative edge — " + "; ".join(failed)
        elif not ok_dd or not ok_stable:
            failed = [c["detail"] for c in checks if not c["passed"]]
            status = ST_UNSTABLE
            reason = "Unstable — " + "; ".join(failed)
        else:
            status = ST_ENABLED
            reason = (f"Passed all gates — rolling PF {roll_pf}, expectancy "
                      f"{roll_exp:+.2f}%/trade over last "
                      f"{rolling['trade_count']} trades")

        # WATCHLIST: positive but not yet gate-passing edge (spec §7) —
        # near-miss on the PF gate only, everything else healthy.
        if (status == ST_NEG_EDGE and roll_pf is not None
                and 1.0 <= roll_pf < gates["min_rolling_pf"]
                and roll_exp is not None and roll_exp > 0):
            status = ST_WATCHLIST
            reason = (f"Watchlist — rolling PF {roll_pf} is positive but below "
                      f"the {gates['min_rolling_pf']} gate; no capital until it clears")
        if status == ST_INSUFFICIENT and n >= 10 and roll_pf is not None \
                and roll_pf >= gates["min_rolling_pf"] and (roll_exp or 0) > 0:
            status = ST_WATCHLIST
            reason = (f"Watchlist — early edge (rolling PF {roll_pf}) but only "
                      f"{n} completed trades (< {gates['min_trades']})")

        return {"status": status, "reason": reason, "checks": checks,
                "rolling": rolling, "evidence": evidence,
                "stability": stability, "shrunk": ev_shrunk}

    def _composite_score(self, gate: dict, gates: dict) -> tuple[float, dict]:
        """Transparent composite score (spec §3): 35% PF + 30% expectancy +
        15% Sharpe + 10% drawdown + 10% sample/stability. Every input is
        shrunk and capped so one noisy metric cannot dominate."""
        shr = gate["shrunk"]
        ev = gate["evidence"]["metrics"]
        stability = gate["stability"]
        adj_pf = shr["adjusted_profit_factor"] if shr["adjusted_profit_factor"] is not None else 1.0
        adj_exp = shr["adjusted_expectancy_pct"] if shr["adjusted_expectancy_pct"] is not None else 0.0
        sharpe = ev["sharpe"] if ev["sharpe"] is not None else 0.0
        dd = ev["max_drawdown_pct"] or 0.0
        n = shr["sample"]

        pf_score = _clip01((min(adj_pf, 2.5) - 0.8) / (2.0 - 0.8))
        exp_score = _clip01((max(-1.0, min(1.0, adj_exp)) + 1.0) / 2.0)
        sharpe_score = _clip01((max(-1.5, min(1.5, sharpe)) + 1.5) / 3.0)
        dd_score = _clip01(1.0 - dd / max(gates["max_drawdown_pct"], 1e-9))
        pos_frac = (stability["positive_periods"] / stability["periods"]
                    if stability["periods"] else 0.5)
        sample_score = _clip01(min(1.0, n / 100.0) * (0.5 + 0.5 * pos_frac))

        components = {
            "profit_factor": {"weight": 0.35, "score": round(pf_score, 3),
                              "input": adj_pf},
            "expectancy": {"weight": 0.30, "score": round(exp_score, 3),
                           "input": adj_exp},
            "sharpe": {"weight": 0.15, "score": round(sharpe_score, 3),
                       "input": round(sharpe, 3)},
            "drawdown": {"weight": 0.10, "score": round(dd_score, 3),
                         "input": dd},
            "sample_stability": {"weight": 0.10, "score": round(sample_score, 3),
                                 "input": n},
        }
        total = sum(c["weight"] * c["score"] for c in components.values()) * 100.0
        return round(total, 2), components

    def rank_gated(self, regime: str, gates: dict | None = None) -> list[dict]:
        """Corrected ranking (spec §1-§5): hard gates first, composite score
        only among eligible strategies, NO diversification floor. If nothing
        passes, every row stays disabled and the portfolio holds cash."""
        gates = gates or GATES_DEFAULT
        regime = normalize_regime(regime)
        key = ("rank_gated", regime, gates["name"])
        if key in self._cache:
            return self._cache[key]
        rows = []
        for sid in self.strategy_ids:
            gate = self._gate_check(sid, regime, gates)
            score, components = self._composite_score(gate, gates)
            eligible = gate["status"] == ST_ENABLED
            shr = gate["shrunk"]
            rows.append({
                "strategy_id": sid,
                "status": gate["status"],
                "eligible": eligible,
                "enabled": eligible,
                "score": score if eligible else 0.0,
                "raw_score": score,
                "score_components": components,
                "reason": gate["reason"],
                "gate_checks": gate["checks"],
                "rolling": gate["rolling"],
                "evidence_level": gate["evidence"]["level"],
                "evidence_sample": gate["evidence"]["sample"],
                "evidence_fallback_reason": gate["evidence"]["fallback_reason"],
                "evidence_reliability": gate["evidence"]["reliability"],
                "raw_profit_factor": shr["raw_profit_factor"],
                "adjusted_profit_factor": shr["adjusted_profit_factor"],
                "raw_expectancy_pct": shr["raw_expectancy_pct"],
                "adjusted_expectancy_pct": shr["adjusted_expectancy_pct"],
                "sample": shr["sample"],
                "stability": gate["stability"],
                "overall_metrics": self.matrix()[sid]["overall"],
                "regime_metrics": self.matrix()[sid]["by_regime"].get(regime),
            })
        # Deterministic: sort by (eligible desc, score desc, strategy_id asc)
        rows.sort(key=lambda r: (-int(r["eligible"]), -r["score"], r["strategy_id"]))
        for i, r in enumerate(rows):
            r["rank"] = i + 1
        self._cache[key] = rows
        return rows

    def gated_allocation(self, regime: str, gates: dict | None = None) -> dict:
        """Corrected allocation (spec §6): proportional to positive ADJUSTED
        edge among eligible strategies only, capped at MAX_STRATEGY_ALLOC.
        The cap is NOT relaxed — unallocated capital stays in cash."""
        gates = gates or GATES_DEFAULT
        regime = normalize_regime(regime)
        key = ("alloc_gated", regime, gates["name"])
        if key in self._cache:
            return self._cache[key]
        rows = self.rank_gated(regime, gates)
        eligible = [r for r in rows if r["eligible"]]
        out = {
            "weights": {r["strategy_id"]: 0.0 for r in rows},
            "eligible_weights": {r["strategy_id"]: 0.0 for r in rows},
            "cash_weight": 1.0,
            "cash_only": len(eligible) == 0,
            "notes": {},
        }
        if eligible:
            # Edge = adjusted expectancy after costs (floor at a tiny epsilon
            # so an eligible strategy with ~0 edge still ranks last, not 0).
            edges = {}
            for r in eligible:
                e = r["adjusted_expectancy_pct"]
                edges[r["strategy_id"]] = max(float(e if e is not None else 0.0), 1e-6)
            total = sum(edges.values())
            eligible_w = {sid: v / total for sid, v in edges.items()}
            final_w = {}
            for sid, w in eligible_w.items():
                if w > MAX_STRATEGY_ALLOC:
                    final_w[sid] = MAX_STRATEGY_ALLOC
                    out["notes"][sid] = (f"Capped at {MAX_STRATEGY_ALLOC:.0%} "
                                         f"(edge-proportional share was {w:.0%}); "
                                         "remainder held as cash")
                else:
                    final_w[sid] = w
            out["eligible_weights"].update(
                {sid: round(v, 4) for sid, v in eligible_w.items()})
            out["weights"].update(
                {sid: round(v, 4) for sid, v in final_w.items()})
            out["cash_weight"] = round(1.0 - sum(final_w.values()), 4)
            out["cash_only"] = False
        self._cache[key] = out
        return out

    def gated_report(self, regime: str, gates: dict | None = None) -> dict:
        """Full corrected-policy report for the API/UI."""
        gates = gates or GATES_DEFAULT
        regime = normalize_regime(regime)
        rows = self.rank_gated(regime, gates)
        alloc = self.gated_allocation(regime, gates)
        return {
            "regime": regime,
            "policy": "gated",
            "gates": {k: v for k, v in gates.items()},
            "cash_only": alloc["cash_only"],
            "portfolio_status": ST_CASH_ONLY if alloc["cash_only"] else ST_ENABLED,
            "cash_pct": round(alloc["cash_weight"] * 100.0, 1),
            "total_completed_trades": sum(
                len(v) for v in self._by_strategy.values()),
            "ranking": [{
                **{k: r[k] for k in (
                    "rank", "strategy_id", "status", "eligible", "score",
                    "score_components", "reason", "gate_checks",
                    "evidence_level", "evidence_sample",
                    "evidence_fallback_reason", "evidence_reliability",
                    "raw_profit_factor", "adjusted_profit_factor",
                    "raw_expectancy_pct", "adjusted_expectancy_pct",
                    "sample", "stability")},
                "rolling_profit_factor": r["rolling"]["profit_factor"],
                "rolling_expectancy_pct": r["rolling"]["expectancy_pct"],
                "rolling_net_return_pct": r["rolling"]["net_return_pct"],
                "rolling_window": r["rolling"]["trade_count"],
                "eligible_allocation_pct": round(
                    alloc["eligible_weights"].get(r["strategy_id"], 0.0) * 100.0, 1),
                "final_allocation_pct": round(
                    alloc["weights"].get(r["strategy_id"], 0.0) * 100.0, 1),
                "allocation_note": alloc["notes"].get(r["strategy_id"], ""),
                "overall": r["overall_metrics"],
                "in_regime": r["regime_metrics"],
            } for r in rows],
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
