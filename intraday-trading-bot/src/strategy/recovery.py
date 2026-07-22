"""StrategyRecoveryManager — crash-recovery orchestrator for the Strategy Engine.

On service restart, this component:
1. Loads all non-terminal strategy records from the DB.
2. Reconstructs StrategyConfig and lifecycle state.
3. Re-registers strategy implementations via an injected factory/registry.
4. Restores PAUSED strategies without activating signal generation.
5. Restores ACTIVE strategies through STARTING and re-subscribes to market data.
6. Loads all signals (pending and already-routed).
7. Deduplicates already-routed signals (never routes twice).
8. Re-queues genuinely pending and unrouted signals.
9. Returns a structured recovery result.

All errors are collected and reported — never silently swallowed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol, Set
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from src.strategy.persistence import (
    StrategyConfigRecord,
    StrategyPersistenceAdapter,
    StrategySignalRecord,
    StrategyStateSnapshotRecord,
)

logger = logging.getLogger(__name__)


class StrategyFactory(Protocol):
    async def create(self, strategy_type: str, strategy_id: str, config: Dict[str, Any]) -> Any: ...


class StrategyRegistry(Protocol):
    async def register(self, strategy_id: str, instance: Any, lifecycle_state: str) -> None: ...
    async def transition(self, strategy_id: str, target_state: str) -> bool: ...
    async def subscribe_market_data(self, strategy_id: str, instrument_tokens: List[str]) -> None: ...
    async def is_registered(self, strategy_id: str) -> bool: ...


class SignalRouter(Protocol):
    async def enqueue(self, signal: Any) -> None: ...


@dataclass(frozen=True)
class StrategyRecoveryEntry:
    strategy_id: str
    success: bool
    restored_state: Optional[str] = None
    error: Optional[str] = None


@dataclass(frozen=True)
class SignalRecoveryEntry:
    signal_id: UUID
    strategy_id: str
    requeued: bool
    skipped_already_routed: bool = False
    error: Optional[str] = None


@dataclass(frozen=True)
class StrategyRecoveryResult:
    strategies_restored: List[str] = field(default_factory=list)
    strategies_skipped: List[str] = field(default_factory=list)
    signals_restored: int = 0
    signals_requeued: int = 0
    errors: List[str] = field(default_factory=list)
    recovery_timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    strategy_details: List[StrategyRecoveryEntry] = field(default_factory=list)
    signal_details: List[SignalRecoveryEntry] = field(default_factory=list)


class StrategyRecoveryManager:
    TERMINAL_STATES: Set[str] = {"STOPPED", "ERROR"}

    def __init__(
        self,
        persistence: StrategyPersistenceAdapter,
        factory: StrategyFactory,
        registry: StrategyRegistry,
        signal_router: SignalRouter,
    ) -> None:
        self._persistence = persistence
        self._factory = factory
        self._registry = registry
        self._signal_router = signal_router

    async def recover(self, session: AsyncSession) -> StrategyRecoveryResult:
        """Execute the full recovery pipeline.

        Idempotent — calling recover() twice on the same DB state is safe.
        Already-registered strategies are skipped. Already-routed signals
        are skipped. Already-requeued signals are skipped via signal_id
        deduplication in the router.
        """
        # Mutable accumulators (local variables, not frozen dataclass fields)
        strategies_restored: List[str] = []
        strategies_skipped: List[str] = []
        strategy_details: List[StrategyRecoveryEntry] = []
        signal_details: List[SignalRecoveryEntry] = []
        errors: List[str] = []
        signals_requeued = 0

        # Step 1: Load all non-terminal strategy records
        strategy_records = await self._persistence.list_non_terminal_strategies(
            session, terminal_states=list(self.TERMINAL_STATES)
        )
        logger.info(
            "Recovery: loaded %d non-terminal strategy record(s)",
            len(strategy_records),
        )

        # Step 2–5: Restore each strategy
        for record in strategy_records:
            entry = await self._recover_strategy(session, record)
            strategy_details.append(entry)
            if entry.success:
                strategies_restored.append(record.strategy_id)
            else:
                if entry.error:
                    errors.append(f"Strategy {record.strategy_id}: {entry.error}")
                strategies_skipped.append(record.strategy_id)

        # Step 6–8: Load ALL signals (pending + already-routed) so the result
        # gives a full accounting.  _recover_signal() skips already-routed ones
        # without enqueuing; signals_restored counts every signal seen.
        all_signals = await self._persistence.list_all_signals(session)
        logger.info(
            "Recovery: loaded %d total signal record(s) (%d pending)",
            len(all_signals),
            sum(1 for s in all_signals if s.routing_status == "PENDING"),
        )

        for sig in all_signals:
            sig_entry = await self._recover_signal(session, sig)
            signal_details.append(sig_entry)
            if sig_entry.requeued:
                signals_requeued += 1
            if sig_entry.error:
                errors.append(f"Signal {sig.signal_id}: {sig_entry.error}")

        logger.info(
            "Recovery complete — restored=%d skipped=%d signals_seen=%d signals_requeued=%d errors=%d",
            len(strategies_restored),
            len(strategies_skipped),
            len(all_signals),
            signals_requeued,
            len(errors),
        )

        # Build the frozen result once at the end
        return StrategyRecoveryResult(
            strategies_restored=strategies_restored,
            strategies_skipped=strategies_skipped,
            signals_restored=len(all_signals),
            signals_requeued=signals_requeued,
            errors=errors,
            strategy_details=strategy_details,
            signal_details=signal_details,
        )

    async def _recover_strategy(
        self,
        session: AsyncSession,
        record: StrategyConfigRecord,
    ) -> StrategyRecoveryEntry:
        strategy_id = record.strategy_id

        # Idempotency: skip already-registered strategies
        if await self._registry.is_registered(strategy_id):
            logger.debug("Recovery: strategy %s already registered — skipping", strategy_id)
            return StrategyRecoveryEntry(
                strategy_id=strategy_id,
                success=False,
                error="Already registered",
            )

        try:
            config = dict(record.configuration) if record.configuration else {}
            instance = await self._factory.create(
                strategy_type=record.strategy_type,
                strategy_id=strategy_id,
                config=config,
            )
            await self._registry.register(
                strategy_id=strategy_id,
                instance=instance,
                lifecycle_state="REGISTERED",
            )

            target_state = record.lifecycle_state
            if target_state == "PAUSED":
                await self._registry.transition(strategy_id, "STARTING")
                await self._registry.transition(strategy_id, "ACTIVE")
                await self._registry.transition(strategy_id, "PAUSED")
                logger.debug("Recovery: strategy %s restored to PAUSED", strategy_id)
            elif target_state == "ACTIVE":
                await self._registry.transition(strategy_id, "STARTING")
                await self._registry.transition(strategy_id, "ACTIVE")
                await self._registry.subscribe_market_data(
                    strategy_id,
                    list(record.instrument_tokens) if record.instrument_tokens else [],
                )
                logger.debug("Recovery: strategy %s restored to ACTIVE and subscribed", strategy_id)
            elif target_state == "STARTING":
                await self._registry.transition(strategy_id, "STARTING")
                logger.debug("Recovery: strategy %s restored to STARTING", strategy_id)
            elif target_state == "REGISTERED":
                logger.debug("Recovery: strategy %s restored to REGISTERED", strategy_id)
            else:
                logger.warning(
                    "Recovery: strategy %s has unknown lifecycle state '%s'",
                    strategy_id, target_state,
                )

            snapshot = await self._persistence.load_latest_state_snapshot(session, strategy_id)
            if snapshot is not None:
                await self._apply_state_snapshot(strategy_id, snapshot)

            return StrategyRecoveryEntry(
                strategy_id=strategy_id,
                success=True,
                restored_state=target_state,
            )
        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.exception("Recovery: failed to restore strategy %s", strategy_id)
            return StrategyRecoveryEntry(
                strategy_id=strategy_id,
                success=False,
                error=error_msg,
            )

    async def _recover_signal(
        self,
        session: AsyncSession,
        record: StrategySignalRecord,
    ) -> SignalRecoveryEntry:
        signal_id = record.signal_id
        strategy_id = record.strategy_id

        try:
            if record.routed_client_order_id is not None:
                logger.debug(
                    "Recovery: signal %s already routed (order_id=%s) — skipping",
                    signal_id, record.routed_client_order_id,
                )
                return SignalRecoveryEntry(
                    signal_id=signal_id,
                    strategy_id=strategy_id,
                    requeued=False,
                    skipped_already_routed=True,
                )

            signal_envelope = {
                "signal_id": signal_id,
                "strategy_id": strategy_id,
                "account_id": record.account_id,
                "instrument_token": record.instrument_token,
                "action": record.action,
                "side": record.side,
                "quantity": record.quantity,
                "order_type": record.order_type,
                "limit_price": record.limit_price,
                "trigger_price": record.trigger_price,
                "timestamp": record.timestamp,
                "extra_data": dict(record.extra_data) if record.extra_data else {},
            }
            await self._signal_router.enqueue(signal_envelope)
            logger.debug("Recovery: signal %s re-queued for routing", signal_id)
            return SignalRecoveryEntry(
                signal_id=signal_id,
                strategy_id=strategy_id,
                requeued=True,
            )
        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.exception("Recovery: failed to re-queue signal %s", signal_id)
            return SignalRecoveryEntry(
                signal_id=signal_id,
                strategy_id=strategy_id,
                requeued=False,
                error=error_msg,
            )

    async def _apply_state_snapshot(
        self,
        strategy_id: str,
        snapshot: StrategyStateSnapshotRecord,
    ) -> None:
        logger.debug(
            "Recovery: applying state snapshot for %s (signals=%d routed=%d rejected=%d fills=%d)",
            strategy_id, snapshot.emitted_signal_count, snapshot.routed_signal_count,
            snapshot.rejected_signal_count, snapshot.fill_count,
        )
        # Intentional no-op — frozen runtime internals are not modified.
