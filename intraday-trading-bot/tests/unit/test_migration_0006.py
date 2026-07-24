"""ORM-vs-migration parity tests for migration 0006 (Group N).

Verifies that every table and column defined in the Alembic migration 0006
has a corresponding ORM model with a matching column definition.
"""
from __future__ import annotations

import pytest


class TestBrokerSessionModel:
    def test_model_importable(self):
        from src.database.broker_models import BrokerSessionModel
        assert BrokerSessionModel.__tablename__ == "broker_sessions"

    def test_required_columns_present(self):
        from src.database.broker_models import BrokerSessionModel
        mapper = BrokerSessionModel.__table__
        columns = {c.name for c in mapper.columns}
        required = {
            "id", "session_uuid", "broker_name", "user_id",
            "paper_mode", "is_valid", "created_at", "expires_at",
            "invalidated_at", "invalidation_reason",
        }
        assert required.issubset(columns), f"Missing: {required - columns}"

    def test_session_uuid_unique(self):
        from src.database.broker_models import BrokerSessionModel
        col = BrokerSessionModel.__table__.c.session_uuid
        assert col.unique is True


class TestBrokerOrderCorrelation:
    def test_model_importable(self):
        from src.database.broker_models import BrokerOrderCorrelation
        assert BrokerOrderCorrelation.__tablename__ == "broker_order_correlations"

    def test_required_columns_present(self):
        from src.database.broker_models import BrokerOrderCorrelation
        mapper = BrokerOrderCorrelation.__table__
        columns = {c.name for c in mapper.columns}
        required = {
            "id", "internal_order_id", "idempotency_key", "broker_order_id",
            "exchange_order_id", "status", "paper_mode", "trading_symbol",
            "exchange", "error_message", "created_at", "updated_at", "reconciled_at",
        }
        assert required.issubset(columns), f"Missing: {required - columns}"

    def test_idempotency_key_unique(self):
        from src.database.broker_models import BrokerOrderCorrelation
        col = BrokerOrderCorrelation.__table__.c.idempotency_key
        assert col.unique is True


class TestBrokerEventInbox:
    def test_model_importable(self):
        from src.database.broker_models import BrokerEventInbox
        assert BrokerEventInbox.__tablename__ == "broker_event_inbox"

    def test_required_columns_present(self):
        from src.database.broker_models import BrokerEventInbox
        mapper = BrokerEventInbox.__table__
        columns = {c.name for c in mapper.columns}
        required = {
            "id", "broker_order_id", "event_type", "raw_payload",
            "source", "processed", "requires_review", "review_notes",
            "paper_mode", "received_at", "processed_at",
        }
        assert required.issubset(columns), f"Missing: {required - columns}"


class TestBrokerReconciliationRun:
    def test_model_importable(self):
        from src.database.broker_models import BrokerReconciliationRun
        assert BrokerReconciliationRun.__tablename__ == "broker_reconciliation_runs"

    def test_required_columns_present(self):
        from src.database.broker_models import BrokerReconciliationRun
        mapper = BrokerReconciliationRun.__table__
        columns = {c.name for c in mapper.columns}
        required = {
            "id", "run_id", "trigger", "started_at", "completed_at",
            "orders_checked", "clean", "discrepancy_count", "paper_mode", "created_at",
        }
        assert required.issubset(columns), f"Missing: {required - columns}"

    def test_run_id_unique(self):
        from src.database.broker_models import BrokerReconciliationRun
        col = BrokerReconciliationRun.__table__.c.run_id
        assert col.unique is True


class TestBrokerReconciliationDiscrepancy:
    def test_model_importable(self):
        from src.database.broker_models import BrokerReconciliationDiscrepancy
        assert (
            BrokerReconciliationDiscrepancy.__tablename__
            == "broker_reconciliation_discrepancies"
        )

    def test_required_columns_present(self):
        from src.database.broker_models import BrokerReconciliationDiscrepancy
        mapper = BrokerReconciliationDiscrepancy.__table__
        columns = {c.name for c in mapper.columns}
        required = {
            "id", "run_id", "discrepancy_type", "internal_order_id",
            "broker_order_id", "trading_symbol", "description",
            "local_value", "broker_value", "requires_manual_review",
            "resolved", "resolved_at", "resolution_notes", "created_at",
        }
        assert required.issubset(columns), f"Missing: {required - columns}"


class TestInstrumentSyncRun:
    def test_model_importable(self):
        from src.database.broker_models import InstrumentSyncRun
        assert InstrumentSyncRun.__tablename__ == "instrument_sync_runs"

    def test_required_columns_present(self):
        from src.database.broker_models import InstrumentSyncRun
        mapper = InstrumentSyncRun.__table__
        columns = {c.name for c in mapper.columns}
        required = {
            "id", "exchange", "started_at", "completed_at",
            "downloaded", "upserted", "skipped", "checksum",
            "success", "error_message",
        }
        assert required.issubset(columns), f"Missing: {required - columns}"


class TestAllModelsImportable:
    def test_all_broker_models_importable(self):
        """All 6 broker models can be imported without errors."""
        from src.database.broker_models import (
            BrokerSessionModel,
            BrokerOrderCorrelation,
            BrokerEventInbox,
            BrokerReconciliationRun,
            BrokerReconciliationDiscrepancy,
            InstrumentSyncRun,
        )
        models = [
            BrokerSessionModel,
            BrokerOrderCorrelation,
            BrokerEventInbox,
            BrokerReconciliationRun,
            BrokerReconciliationDiscrepancy,
            InstrumentSyncRun,
        ]
        for model in models:
            assert hasattr(model, "__tablename__")
            assert hasattr(model, "__table__")

    def test_table_names_match_migration(self):
        from src.database.broker_models import (
            BrokerSessionModel,
            BrokerOrderCorrelation,
            BrokerEventInbox,
            BrokerReconciliationRun,
            BrokerReconciliationDiscrepancy,
            InstrumentSyncRun,
        )
        expected_tables = {
            "broker_sessions",
            "broker_order_correlations",
            "broker_event_inbox",
            "broker_reconciliation_runs",
            "broker_reconciliation_discrepancies",
            "instrument_sync_runs",
        }
        actual_tables = {
            BrokerSessionModel.__tablename__,
            BrokerOrderCorrelation.__tablename__,
            BrokerEventInbox.__tablename__,
            BrokerReconciliationRun.__tablename__,
            BrokerReconciliationDiscrepancy.__tablename__,
            InstrumentSyncRun.__tablename__,
        }
        assert actual_tables == expected_tables
