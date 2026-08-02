"""
snapshot_bus.py — Phase 10A
In-process publish/subscribe snapshot bus.

Design rules:
- Agents publish snapshots to named topics.
- Consumers subscribe to topics; they receive the latest envelope.
- No direct agent-to-agent calls — all communication is mediated by the bus.
- Thread-safe: uses a simple lock around dict mutations.

READ-ONLY · ADVISORY-ONLY
"""
from __future__ import annotations

import threading
from typing import Any, Callable, Dict, List, Optional

from .models import SnapshotEnvelope


class SnapshotBus:
    """
    Singleton publish/subscribe bus for agent snapshots.

    Usage:
        bus = SnapshotBus.instance()
        bus.publish("market_data", "market-data-agent", payload)
        envelope = bus.latest("market_data")
        bus.subscribe("market_data", my_callback)
    """

    _instance: Optional["SnapshotBus"] = None
    _lock: threading.Lock = threading.Lock()

    def __init__(self) -> None:
        self._snapshots: Dict[str, SnapshotEnvelope] = {}
        self._subscribers: Dict[str, List[Callable[[SnapshotEnvelope], None]]] = {}
        self._sequences: Dict[str, int] = {}
        self._mu = threading.Lock()

    @classmethod
    def instance(cls) -> "SnapshotBus":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton — for testing only."""
        with cls._lock:
            cls._instance = None

    # ── Publish ────────────────────────────────────────────────────────────────

    def publish(
        self,
        topic: str,
        publisher_id: str,
        payload: Dict[str, Any],
    ) -> SnapshotEnvelope:
        """
        Publish a snapshot to a topic. Replaces the previous envelope.
        Notifies all subscribers synchronously (fire-and-forget; errors suppressed).
        """
        with self._mu:
            seq = self._sequences.get(topic, 0) + 1
            self._sequences[topic] = seq
            envelope = SnapshotEnvelope(
                topic=topic,
                publisher_id=publisher_id,
                payload=payload,
                sequence=seq,
            )
            self._snapshots[topic] = envelope
            callbacks = list(self._subscribers.get(topic, []))

        # Notify subscribers outside the lock
        for cb in callbacks:
            try:
                cb(envelope)
            except Exception:
                pass

        return envelope

    # ── Subscribe ─────────────────────────────────────────────────────────────

    def subscribe(
        self,
        topic: str,
        callback: Callable[[SnapshotEnvelope], None],
    ) -> None:
        """Register a callback invoked on every new publish to topic."""
        with self._mu:
            self._subscribers.setdefault(topic, []).append(callback)

    def unsubscribe(
        self,
        topic: str,
        callback: Callable[[SnapshotEnvelope], None],
    ) -> None:
        with self._mu:
            subs = self._subscribers.get(topic, [])
            try:
                subs.remove(callback)
            except ValueError:
                pass

    # ── Read ──────────────────────────────────────────────────────────────────

    def latest(self, topic: str) -> Optional[SnapshotEnvelope]:
        """Return the most recent envelope for a topic, or None."""
        return self._snapshots.get(topic)

    def topics(self) -> List[str]:
        """All topics that have at least one published snapshot."""
        return list(self._snapshots.keys())

    def stats(self) -> Dict[str, Any]:
        """Summary statistics for the bus."""
        with self._mu:
            return {
                "topics": list(self._snapshots.keys()),
                "topic_count": len(self._snapshots),
                "subscriber_count": sum(len(v) for v in self._subscribers.values()),
                "sequences": dict(self._sequences),
            }
