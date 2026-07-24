"""RC-10C1 Portfolio Core — PortfolioReconciliationEngine.

Consumes broker-neutral snapshots (plain dicts — no Zerodha SDK types) and
compares them against the local PortfolioSnapshot to produce a
PortfolioReconciliationReport.

Design notes
------------
* All arithmetic uses Decimal to avoid floating-point drift.
* The engine is stateless; callers own persistence.
* dry_run=True (default) performs analysis without mutating any state.
* Structured log fields never include broker credentials or account payloads.

Backwards compatibility
-----------------------
The legacy ``ReconciliationEngine`` class (which accepts a ``BrokerSnapshot``
typed object) is retained as an alias at the bottom of this module.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from .config import DEFAULT_CONFIG, PortfolioConfig
from .contracts import (
    LimitSeverity,
    PortfolioDiscrepancy,
    PortfolioDiscrepancyType,
    PortfolioReconciliationReport,
    PortfolioSnapshot,
    PositionStatus,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PortfolioReconciliationEngine  (primary implementation)
# ---------------------------------------------------------------------------

class PortfolioReconciliationEngine:
    """Stateless engine that reconciles local portfolio state against a
    broker-neutral snapshot dict.

    Parameters
    ----------
    config:
        Portfolio configuration driving staleness thresholds.
    """

    def __init__(self, config: PortfolioConfig | None = None) -> None:
        self.config: PortfolioConfig = config or DEFAULT_CONFIG

        # Tolerances
        self.PRICE_TOLERANCE: Decimal = Decimal("0.01")    # 1 paisa
        self.QTY_TOLERANCE: int = 0                         # exact match required
        self.CASH_TOLERANCE: Decimal = Decimal("1.00")      # 1 rupee rounding tolerance
        self.MARGIN_TOLERANCE: Decimal = Decimal("10.00")   # 10 rupees

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def reconcile(
        self,
        local_snapshot: PortfolioSnapshot,
        broker_snapshot: dict[str, Any],
        dry_run: bool = True,
    ) -> PortfolioReconciliationReport:
        """Reconcile *local_snapshot* against *broker_snapshot*.

        Parameters
        ----------
        local_snapshot:
            The authoritative local portfolio state.
        broker_snapshot:
            Broker-neutral dict (no SDK types). Expected keys:
            ``positions``, ``orders``, ``funds``, ``trades``, ``as_of``.
        dry_run:
            When ``True`` (default), no state is mutated — analysis only.

        Returns
        -------
        PortfolioReconciliationReport
        """
        started_at = datetime.now(timezone.utc)
        discrepancies: list[PortfolioDiscrepancy] = []

        logger.info(
            "Starting reconciliation run",
            extra={
                "portfolio_id": local_snapshot.portfolio_id,
                "dry_run": dry_run,
                "local_version": local_snapshot.version,
            },
        )

        # ── 1. Parse broker timestamp and check staleness ────────────────
        # Accept both "as_of" (legacy/backward-compat) and "snapshot_at"
        # (documented RC-10D broker-neutral schema).  Either key is valid;
        # "snapshot_at" takes precedence when both are present.
        broker_as_of: datetime | None = None
        broker_snapshot_age_s: float | None = None

        raw_as_of = broker_snapshot.get("snapshot_at") or broker_snapshot.get("as_of")
        if raw_as_of:
            try:
                broker_as_of = datetime.fromisoformat(str(raw_as_of))
                if broker_as_of.tzinfo is None:
                    broker_as_of = broker_as_of.replace(tzinfo=timezone.utc)
                broker_snapshot_age_s = (started_at - broker_as_of).total_seconds()
            except (ValueError, TypeError) as exc:
                logger.warning(
                    "Cannot parse broker snapshot as_of field",
                    extra={"error": str(exc)},
                )

        if (
            broker_snapshot_age_s is not None
            and broker_snapshot_age_s > self.config.stale_broker_threshold_s
        ):
            discrepancies.append(
                PortfolioDiscrepancy(
                    discrepancy_type=PortfolioDiscrepancyType.STALE_BROKER_SNAPSHOT,
                    severity=LimitSeverity.WARNING,
                    local_value=str(self.config.stale_broker_threshold_s),
                    broker_value=str(broker_snapshot_age_s),
                )
            )
            logger.warning(
                "Broker snapshot is stale",
                extra={
                    "age_s": broker_snapshot_age_s,
                    "threshold_s": self.config.stale_broker_threshold_s,
                },
            )

        # ── 2. Compare positions ─────────────────────────────────────────
        broker_positions: list[dict[str, Any]] = broker_snapshot.get("positions", [])
        broker_by_token: dict[int, dict[str, Any]] = {
            int(p["instrument_token"]): p
            for p in broker_positions
            if "instrument_token" in p
        }

        # Consider all non-CLOSED local positions
        open_local_positions = [
            pos
            for pos in local_snapshot.open_positions
            if pos.status in (
                PositionStatus.OPEN,
                PositionStatus.REDUCING,
                PositionStatus.PENDING,
            )
        ]
        local_tokens: set[int] = {pos.instrument_token for pos in open_local_positions}

        for local_pos in open_local_positions:
            token = local_pos.instrument_token
            broker_pos = broker_by_token.get(token)

            if broker_pos is None:
                # Position exists locally but not at broker
                discrepancies.append(
                    PortfolioDiscrepancy(
                        discrepancy_type=PortfolioDiscrepancyType.LOCAL_ONLY_POSITION,
                        instrument_token=token,
                        instrument_symbol=local_pos.instrument_symbol,
                        local_value=str(local_pos.open_quantity),
                        broker_value=None,
                        severity=LimitSeverity.CRITICAL,
                    )
                )
                logger.error(
                    "LOCAL_ONLY_POSITION: position exists locally but not at broker",
                    extra={
                        "instrument_token": token,
                        "instrument_symbol": local_pos.instrument_symbol,
                        "local_qty": local_pos.open_quantity,
                    },
                )
                continue

            # Quantity check (exact match required)
            broker_qty = int(broker_pos.get("quantity", 0))
            qty_diff = abs(local_pos.open_quantity - broker_qty)
            if qty_diff > self.QTY_TOLERANCE:
                discrepancies.append(
                    PortfolioDiscrepancy(
                        discrepancy_type=PortfolioDiscrepancyType.QUANTITY_MISMATCH,
                        instrument_token=token,
                        instrument_symbol=local_pos.instrument_symbol,
                        local_value=str(local_pos.open_quantity),
                        broker_value=str(broker_qty),
                        severity=LimitSeverity.CRITICAL,
                    )
                )
                logger.error(
                    "QUANTITY_MISMATCH detected",
                    extra={
                        "instrument_token": token,
                        "local_qty": local_pos.open_quantity,
                        "broker_qty": broker_qty,
                    },
                )

            # Average price check
            try:
                broker_avg_price = Decimal(str(broker_pos.get("average_price", "0")))
            except Exception:
                broker_avg_price = Decimal("0")

            price_diff = abs(local_pos.average_entry_price - broker_avg_price)
            if price_diff > self.PRICE_TOLERANCE:
                discrepancies.append(
                    PortfolioDiscrepancy(
                        discrepancy_type=PortfolioDiscrepancyType.AVG_PRICE_MISMATCH,
                        instrument_token=token,
                        instrument_symbol=local_pos.instrument_symbol,
                        local_value=str(local_pos.average_entry_price),
                        broker_value=str(broker_avg_price),
                        severity=LimitSeverity.WARNING,
                    )
                )
                logger.warning(
                    "AVG_PRICE_MISMATCH detected",
                    extra={
                        "instrument_token": token,
                        "diff": str(price_diff),
                    },
                )

        # Broker positions not in local state (non-zero quantity only)
        for token, broker_pos in broker_by_token.items():
            broker_qty = int(broker_pos.get("quantity", 0))
            if broker_qty == 0:
                continue  # skip zero-qty broker positions (closed)
            if token not in local_tokens:
                discrepancies.append(
                    PortfolioDiscrepancy(
                        discrepancy_type=PortfolioDiscrepancyType.BROKER_ONLY_POSITION,
                        instrument_token=token,
                        instrument_symbol=None,
                        local_value=None,
                        broker_value=str(broker_qty),
                        severity=LimitSeverity.CRITICAL,
                    )
                )
                logger.error(
                    "BROKER_ONLY_POSITION: position at broker not tracked locally",
                    extra={"instrument_token": token, "broker_qty": broker_qty},
                )

        # ── 3. Compare cash ──────────────────────────────────────────────
        funds: dict[str, Any] = broker_snapshot.get("funds", {})
        try:
            broker_cash = Decimal(str(funds.get("available_cash", "0")))
        except Exception:
            broker_cash = Decimal("0")

        local_cash = local_snapshot.cash.available
        cash_diff = abs(local_cash - broker_cash)
        if cash_diff > self.CASH_TOLERANCE:
            discrepancies.append(
                PortfolioDiscrepancy(
                    discrepancy_type=PortfolioDiscrepancyType.CASH_MISMATCH,
                    local_value=str(local_cash),
                    broker_value=str(broker_cash),
                    severity=LimitSeverity.WARNING,
                )
            )
            logger.warning(
                "CASH_MISMATCH detected",
                extra={
                    "local_cash": str(local_cash),
                    "diff": str(cash_diff),
                },
            )

        # ── 4. Compare margin ────────────────────────────────────────────
        try:
            broker_used_margin = Decimal(str(funds.get("used_margin", "0")))
        except Exception:
            broker_used_margin = Decimal("0")

        local_used_margin = local_snapshot.margin.used
        margin_diff = abs(local_used_margin - broker_used_margin)
        if margin_diff > self.MARGIN_TOLERANCE:
            discrepancies.append(
                PortfolioDiscrepancy(
                    discrepancy_type=PortfolioDiscrepancyType.MARGIN_MISMATCH,
                    local_value=str(local_used_margin),
                    broker_value=str(broker_used_margin),
                    severity=LimitSeverity.WARNING,
                )
            )
            logger.warning(
                "MARGIN_MISMATCH detected",
                extra={
                    "local_margin": str(local_used_margin),
                    "diff": str(margin_diff),
                },
            )

        # ── 5. Tally discrepancies ───────────────────────────────────────
        critical_count = sum(
            1 for d in discrepancies if d.severity == LimitSeverity.CRITICAL
        )
        warning_count = sum(
            1 for d in discrepancies if d.severity == LimitSeverity.WARNING
        )

        # ── 6. Portfolio ready? ──────────────────────────────────────────
        portfolio_ready = critical_count == 0

        completed_at = datetime.now(timezone.utc)

        notes_parts: list[str] = []
        if dry_run:
            notes_parts.append("dry_run=True: no state mutation performed")
        if not portfolio_ready:
            notes_parts.append(
                f"{critical_count} critical discrepancy(ies) — portfolio NOT ready"
            )

        report = PortfolioReconciliationReport(
            portfolio_id=local_snapshot.portfolio_id,
            dry_run=dry_run,
            discrepancies=tuple(discrepancies),
            critical_count=critical_count,
            warning_count=warning_count,
            portfolio_ready=portfolio_ready,
            notes="; ".join(notes_parts),
            started_at=started_at,
            completed_at=completed_at,
            state_version=local_snapshot.version,
            broker_snapshot_age_s=broker_snapshot_age_s,
        )

        logger.info(
            "Reconciliation complete",
            extra={
                "portfolio_id": local_snapshot.portfolio_id,
                "critical": critical_count,
                "warnings": warning_count,
                "portfolio_ready": portfolio_ready,
                "dry_run": dry_run,
                "duration_s": (completed_at - started_at).total_seconds(),
            },
        )

        return report


# ---------------------------------------------------------------------------
# Standalone staleness helper
# ---------------------------------------------------------------------------

async def detect_stale_state(
    snapshot: PortfolioSnapshot,
    config: PortfolioConfig,
) -> bool:
    """Return ``True`` if *snapshot* is older than ``config.stale_state_threshold_s``.

    Parameters
    ----------
    snapshot:
        The local portfolio snapshot to check.
    config:
        Portfolio configuration providing the staleness threshold.

    Returns
    -------
    bool
        ``True`` if the snapshot is stale, ``False`` otherwise.
    """
    now = datetime.now(timezone.utc)
    age_s = (now - snapshot.snapshotted_at).total_seconds()
    is_stale = age_s > config.stale_state_threshold_s
    if is_stale:
        logger.warning(
            "Portfolio snapshot is stale",
            extra={
                "portfolio_id": snapshot.portfolio_id,
                "age_s": age_s,
                "threshold_s": config.stale_state_threshold_s,
            },
        )
    return is_stale


# ---------------------------------------------------------------------------
# Legacy compatibility — BrokerPositionSnapshot / BrokerSnapshot / ReconciliationEngine
# ---------------------------------------------------------------------------

class BrokerPositionSnapshot:
    """Lightweight broker position representation (legacy compatibility)."""

    def __init__(
        self,
        instrument_token: int,
        instrument_symbol: str,
        quantity: int,
        average_price: Decimal,
        side: str = "LONG",
    ) -> None:
        self.instrument_token = instrument_token
        self.instrument_symbol = instrument_symbol
        self.quantity = quantity
        self.average_price = average_price
        self.side = side


class BrokerSnapshot:
    """Minimal broker account snapshot (legacy compatibility)."""

    def __init__(
        self,
        positions: list[BrokerPositionSnapshot],
        cash: Decimal,
        as_of: datetime | None = None,
    ) -> None:
        self.positions = positions
        self.cash = cash
        self.as_of = as_of or datetime.now(timezone.utc)


class ReconciliationEngine(PortfolioReconciliationEngine):
    """Legacy alias for PortfolioReconciliationEngine.

    Accepts typed ``BrokerSnapshot`` objects in addition to dicts.
    Delegates to the canonical dict-based reconcile() implementation.
    """

    async def reconcile(  # type: ignore[override]
        self,
        local_snapshot: PortfolioSnapshot,
        broker_snapshot: BrokerSnapshot | dict[str, Any],
        dry_run: bool = True,
        avg_price_tolerance: Decimal = Decimal("0.01"),
        cash_tolerance: Decimal = Decimal("1.00"),
    ) -> PortfolioReconciliationReport:
        """Reconcile using either a BrokerSnapshot or a raw dict."""
        if isinstance(broker_snapshot, BrokerSnapshot):
            # Convert to canonical dict format
            broker_dict: dict[str, Any] = {
                "positions": [
                    {
                        "instrument_token": bp.instrument_token,
                        "quantity": bp.quantity,
                        "average_price": float(bp.average_price),
                        "realised_pnl": 0.0,
                        "product": "CNC",
                    }
                    for bp in broker_snapshot.positions
                ],
                "orders": [],
                "funds": {
                    "available_cash": float(broker_snapshot.cash),
                    "used_margin": 0.0,
                    "total": float(broker_snapshot.cash),
                },
                "trades": [],
                "as_of": broker_snapshot.as_of.isoformat(),
            }
        else:
            broker_dict = broker_snapshot  # type: ignore[assignment]

        # Use tolerances from params if they differ from defaults
        orig_price = self.PRICE_TOLERANCE
        orig_cash = self.CASH_TOLERANCE
        self.PRICE_TOLERANCE = avg_price_tolerance
        self.CASH_TOLERANCE = cash_tolerance
        try:
            return await super().reconcile(local_snapshot, broker_dict, dry_run)
        finally:
            self.PRICE_TOLERANCE = orig_price
            self.CASH_TOLERANCE = orig_cash
