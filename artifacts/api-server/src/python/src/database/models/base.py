"""Shared SQLAlchemy declarative base for all Batch 7D ORM models.

All five execution-recovery models (AuditEventModel, ExecutionOrderModel,
ExecutionTradeModel, FillEventModel, PositionSnapshotModel) import ``Base``
from here so that a single call to ``Base.metadata.create_all(engine)``
creates every table at once.
"""
from __future__ import annotations

from sqlalchemy.orm import declarative_base

Base = declarative_base()
