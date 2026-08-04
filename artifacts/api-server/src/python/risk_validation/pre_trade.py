"""
risk_validation/pre_trade.py — Phase 8.4 extension
Pre-trade risk validation gate for every AI paper BUY order.

Called from phase20_executor.create_paper_entry() BEFORE execute_buy().
Runs independently of the RISK_VALIDATION_ENABLED flag — pre-trade checks
are always active in paper mode because they protect capital, not just report.

All checks are ADVISORY (paper only) and never place live orders.

VERDICT LEVELS
  APPROVED         — all CRITICAL checks passed; trade may proceed
  APPROVED_WARN    — no CRITICAL failures but WARNING-level issues present
  REJECTED         — one or more CRITICAL checks failed; trade must be blocked

Callers MUST block the trade when verdict == "REJECTED".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

# ── Thresholds ─────────────────────────────────────────────────────────────────
_MAX_POSITION_PCT      = 20.0   # max % of total portfolio per position
_MAX_RISK_PCT          = 2.0    # max % of total portfolio risked on one trade
_MIN_RR_RATIO          = 1.5    # minimum reward:risk ratio
_MAX_STOP_DIST_PCT     = 5.0    # max % stop distance from entry
_MAX_UTILISATION_PCT   = 92.0   # max portfolio utilisation after this trade
_MIN_CASH_BUFFER_PCT   = 5.0    # minimum cash % that must remain after trade


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class PreTradeIssue:
    severity: str       # "CRITICAL" | "WARNING" | "INFO"
    check:    str       # machine-readable code
    field:    str       # which input field is involved
    message:  str
    value:    Optional[float] = None

    def to_dict(self) -> dict:
        d: dict = {
            "severity": self.severity,
            "check":    self.check,
            "field":    self.field,
            "message":  self.message,
        }
        if self.value is not None:
            d["value"] = round(float(self.value), 4)
        return d


@dataclass
class PreTradeResult:
    verdict:  str                         # "APPROVED" | "APPROVED_WARN" | "REJECTED"
    symbol:   str
    issues:   List[PreTradeIssue] = field(default_factory=list)
    summary:  Dict[str, Any]      = field(default_factory=dict)
    metrics:  Dict[str, Any]      = field(default_factory=dict)
    reason:   str                 = ""    # populated only on REJECTED

    def to_dict(self) -> dict:
        criticals = [i for i in self.issues if i.severity == "CRITICAL"]
        warnings  = [i for i in self.issues if i.severity == "WARNING"]
        infos     = [i for i in self.issues if i.severity == "INFO"]
        return {
            "verdict":         self.verdict,
            "approved":        self.verdict != "REJECTED",
            "symbol":          self.symbol,
            "reason":          self.reason,
            "critical_count":  len(criticals),
            "warning_count":   len(warnings),
            "info_count":      len(infos),
            "issues":          [i.to_dict() for i in self.issues],
            "summary":         self.summary,
            "metrics":         self.metrics,
            "advisory_only":   True,
            "paper_only":      True,
        }


# ── Portfolio loader ──────────────────────────────────────────────────────────

def _get_portfolio() -> dict:
    try:
        from portfolio_store import load_state
        return load_state() or {}
    except Exception:
        return {}


# ── Individual checks ─────────────────────────────────────────────────────────

def _check_position_size(
    sym: str, fill_price: float, qty: int,
    total_capital: float, issues: list,
) -> dict:
    """Position must be ≤ _MAX_POSITION_PCT of total portfolio."""
    trade_value = fill_price * qty
    pct = (trade_value / total_capital * 100) if total_capital > 0 else 0.0

    metric = {"trade_value": round(trade_value, 2),
               "position_pct": round(pct, 2),
               "max_allowed_pct": _MAX_POSITION_PCT}

    if pct > _MAX_POSITION_PCT:
        issues.append(PreTradeIssue(
            "CRITICAL", "POSITION_SIZE_EXCEEDED", "quantity",
            f"{sym}: position size ₹{trade_value:,.0f} = {pct:.1f}% of portfolio "
            f"(limit {_MAX_POSITION_PCT}%)",
            pct,
        ))
    return metric


def _check_capital_at_risk(
    sym: str, risk_amount: float, total_capital: float, issues: list,
) -> dict:
    """Risk amount (entry→stop loss × qty) must be ≤ _MAX_RISK_PCT of portfolio."""
    risk_pct = (risk_amount / total_capital * 100) if total_capital > 0 else 0.0
    metric = {"risk_amount": round(risk_amount, 2),
               "risk_pct": round(risk_pct, 4),
               "max_allowed_pct": _MAX_RISK_PCT}

    if risk_pct > _MAX_RISK_PCT:
        issues.append(PreTradeIssue(
            "CRITICAL", "CAPITAL_AT_RISK_EXCEEDED", "risk_amount",
            f"{sym}: capital at risk {risk_pct:.2f}% exceeds limit {_MAX_RISK_PCT}%",
            risk_pct,
        ))
    elif risk_pct > _MAX_RISK_PCT * 0.75:
        issues.append(PreTradeIssue(
            "WARNING", "CAPITAL_AT_RISK_ELEVATED", "risk_amount",
            f"{sym}: capital at risk {risk_pct:.2f}% is elevated (limit {_MAX_RISK_PCT}%)",
            risk_pct,
        ))
    return metric


def _check_rr_ratio(
    sym: str, fill_price: float, target: float, stop_loss: float, issues: list,
) -> dict:
    """Reward:risk ratio must be ≥ _MIN_RR_RATIO."""
    reward = target - fill_price if target > fill_price else 0.0
    risk   = fill_price - stop_loss if stop_loss > 0 else 0.0
    rr     = (reward / risk) if risk > 0 else 0.0

    metric = {"fill_price": fill_price, "target": target, "stop_loss": stop_loss,
               "reward": round(reward, 2), "risk": round(risk, 2),
               "rr_ratio": round(rr, 3), "min_required": _MIN_RR_RATIO}

    if stop_loss <= 0 or target <= 0:
        issues.append(PreTradeIssue(
            "CRITICAL", "STOP_LOSS_MISSING", "stop_loss",
            f"{sym}: stop_loss or target not set (stop={stop_loss}, target={target})",
        ))
    elif rr < _MIN_RR_RATIO:
        issues.append(PreTradeIssue(
            "CRITICAL", "RR_RATIO_INSUFFICIENT", "rr_ratio",
            f"{sym}: reward:risk {rr:.2f} is below minimum {_MIN_RR_RATIO}",
            rr,
        ))
    elif rr < _MIN_RR_RATIO * 1.2:
        issues.append(PreTradeIssue(
            "WARNING", "RR_RATIO_MARGINAL", "rr_ratio",
            f"{sym}: reward:risk {rr:.2f} is marginal (minimum {_MIN_RR_RATIO})",
            rr,
        ))
    return metric


def _check_stop_distance(
    sym: str, fill_price: float, stop_loss: float, issues: list,
) -> dict:
    """Stop loss must not be more than _MAX_STOP_DIST_PCT below entry."""
    if fill_price <= 0 or stop_loss <= 0:
        return {"stop_distance_pct": None}
    stop_dist_pct = (fill_price - stop_loss) / fill_price * 100
    metric = {"stop_distance_pct": round(stop_dist_pct, 3),
               "max_allowed_pct": _MAX_STOP_DIST_PCT}
    if stop_dist_pct > _MAX_STOP_DIST_PCT:
        issues.append(PreTradeIssue(
            "WARNING", "STOP_TOO_FAR", "stop_loss",
            f"{sym}: stop distance {stop_dist_pct:.2f}% exceeds "
            f"recommended {_MAX_STOP_DIST_PCT}%",
            stop_dist_pct,
        ))
    return metric


def _check_post_trade_utilisation(
    sym: str, fill_price: float, qty: int,
    cash_available: float, total_capital: float, issues: list,
) -> dict:
    """After this trade, portfolio utilisation must stay below limit."""
    trade_cost = fill_price * qty
    cash_after = cash_available - trade_cost
    cash_after_pct = (cash_after / total_capital * 100) if total_capital > 0 else 0.0
    utilisation_after = 100.0 - cash_after_pct

    metric = {"trade_cost": round(trade_cost, 2),
               "cash_after": round(cash_after, 2),
               "cash_after_pct": round(cash_after_pct, 2),
               "utilisation_after_pct": round(utilisation_after, 2),
               "max_utilisation_pct": _MAX_UTILISATION_PCT}

    if cash_after < 0:
        issues.append(PreTradeIssue(
            "CRITICAL", "INSUFFICIENT_CASH", "quantity",
            f"{sym}: trade cost ₹{trade_cost:,.0f} exceeds available cash "
            f"₹{cash_available:,.0f}",
            trade_cost,
        ))
    elif cash_after_pct < _MIN_CASH_BUFFER_PCT:
        issues.append(PreTradeIssue(
            "WARNING", "CASH_BUFFER_LOW", "quantity",
            f"{sym}: cash buffer after trade {cash_after_pct:.1f}% is below "
            f"minimum {_MIN_CASH_BUFFER_PCT}%",
            cash_after_pct,
        ))
    elif utilisation_after > _MAX_UTILISATION_PCT:
        issues.append(PreTradeIssue(
            "WARNING", "HIGH_UTILISATION_AFTER_TRADE", "quantity",
            f"{sym}: utilisation would reach {utilisation_after:.1f}% "
            f"(limit {_MAX_UTILISATION_PCT}%)",
            utilisation_after,
        ))
    return metric


def _check_daily_risk(
    sym: str, risk_amount: float, settings: dict, total_capital: float, issues: list,
) -> dict:
    """Check that today's cumulative risk budget isn't already exhausted."""
    max_daily_trades = int(settings.get("max_trades_per_day", 3))
    from phase20_executor import get_open_trades
    try:
        open_count = len(get_open_trades())
    except Exception:
        open_count = 0

    # Daily risk budget: 5% of total capital
    daily_risk_budget = total_capital * 0.05

    # Rough cumulative risk from existing open trades
    try:
        from phase20_executor import get_ledger
        today_entries = [t for t in get_ledger(50)
                         if t.get("status") == "OPEN"]
        existing_risk = sum(float(t.get("risk_amount") or 0) for t in today_entries)
    except Exception:
        existing_risk = 0.0

    projected_risk    = existing_risk + risk_amount
    projected_risk_pct = (projected_risk / total_capital * 100) if total_capital > 0 else 0.0

    metric = {
        "open_positions":   open_count,
        "max_trades":       max_daily_trades,
        "existing_risk":    round(existing_risk, 2),
        "new_risk_amount":  round(risk_amount, 2),
        "projected_risk":   round(projected_risk, 2),
        "projected_risk_pct": round(projected_risk_pct, 2),
        "daily_risk_budget": round(daily_risk_budget, 2),
    }

    if projected_risk > daily_risk_budget:
        issues.append(PreTradeIssue(
            "WARNING", "DAILY_RISK_BUDGET_EXCEEDED", "risk_amount",
            f"{sym}: projected daily risk ₹{projected_risk:,.0f} "
            f"({projected_risk_pct:.1f}%) exceeds 5% daily budget",
            projected_risk_pct,
        ))

    return metric


# ── Public entry point ────────────────────────────────────────────────────────

def validate_pre_trade(
    symbol: str,
    fill_price: float,
    qty: int,
    stop_loss: float,
    target: float,
    risk_amount: float,
    settings: Dict[str, Any],
    candidate: Optional[Dict[str, Any]] = None,
) -> PreTradeResult:
    """
    Run all pre-trade risk checks for a proposed paper BUY order.

    Returns a PreTradeResult whose verdict field must be checked:
      APPROVED      → proceed
      APPROVED_WARN → proceed with logged warnings
      REJECTED      → block the trade (reason field explains why)

    Never raises; on unexpected errors returns APPROVED_WARN with an INFO issue
    so the trade is not silently dropped by a bug in this validation layer.
    """
    issues: list[PreTradeIssue] = []
    metrics: Dict[str, Any]    = {}

    try:
        portfolio    = _get_portfolio()
        total_cap    = float(portfolio.get("total_value") or
                             portfolio.get("cash_available") or 0)
        cash_avail   = float(portfolio.get("cash_available") or 0)

        # Fallback: if portfolio not yet populated use settings capital
        if total_cap <= 0:
            try:
                from config import INITIAL_CAPITAL
                total_cap = float(INITIAL_CAPITAL)
                cash_avail = total_cap
            except Exception:
                total_cap = cash_avail = 50_000.0

        # ── Run each check ────────────────────────────────────────────────
        metrics["position_size"]   = _check_position_size(
            symbol, fill_price, qty, total_cap, issues)
        metrics["capital_at_risk"] = _check_capital_at_risk(
            symbol, risk_amount, total_cap, issues)
        metrics["rr_ratio"]        = _check_rr_ratio(
            symbol, fill_price, target, stop_loss, issues)
        metrics["stop_distance"]   = _check_stop_distance(
            symbol, fill_price, stop_loss, issues)
        metrics["post_utilisation"]= _check_post_trade_utilisation(
            symbol, fill_price, qty, cash_avail, total_cap, issues)
        metrics["daily_risk"]      = _check_daily_risk(
            symbol, risk_amount, settings, total_cap, issues)

        # ── Verdict ───────────────────────────────────────────────────────
        criticals = [i for i in issues if i.severity == "CRITICAL"]
        warnings  = [i for i in issues if i.severity == "WARNING"]

        if criticals:
            reason = " | ".join(i.message for i in criticals)
            verdict = "REJECTED"
        elif warnings:
            verdict = "APPROVED_WARN"
            reason  = ""
        else:
            verdict = "APPROVED"
            reason  = ""

        summary = {
            "total_capital":  round(total_cap, 2),
            "cash_available": round(cash_avail, 2),
            "trade_value":    round(fill_price * qty, 2),
            "risk_amount":    round(risk_amount, 2),
            "checks_run":     6,
            "checks_critical": len(criticals),
            "checks_warning":  len(warnings),
        }

        return PreTradeResult(
            verdict=verdict, symbol=symbol, issues=issues,
            summary=summary, metrics=metrics, reason=reason,
        )

    except Exception as exc:
        return PreTradeResult(
            verdict="APPROVED_WARN",
            symbol=symbol,
            issues=[PreTradeIssue(
                "INFO", "VALIDATOR_ERROR", "system",
                f"Pre-trade validator encountered an error (non-blocking): {exc}",
            )],
            summary={}, metrics={},
            reason="",
        )
