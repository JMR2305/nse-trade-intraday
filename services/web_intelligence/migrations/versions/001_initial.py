"""initial

Revision ID: 001_initial
Revises: 
Create Date: 2026-08-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from app.domain.enums import CollectionRunStatus, ConfidenceStatus, DataQualityStatus, RecordType, SourceType, ValidationStatus

# revision identifiers, used by Alembic.
revision = '001_initial'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'approved_sources',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('name', sa.String(255), nullable=False),
        sa.Column('base_url', sa.String(2048), nullable=False),
        sa.Column('source_type', sa.Enum(SourceType), nullable=False),
        sa.Column('enabled', sa.Integer, default=1, nullable=False),
        sa.Column('robots_policy', sa.Text, default=''),
        sa.Column('request_interval_seconds', sa.Float, default=5.0, nullable=False),
        sa.Column('maximum_requests_per_hour', sa.Integer, default=60, nullable=False),
        sa.Column('user_agent', sa.String(512), nullable=False),
        sa.Column('parser_name', sa.String(128), nullable=False),
        sa.Column('created_at', sa.DateTime, default=sa.func.now(), nullable=False),
        sa.Column('updated_at', sa.DateTime, default=sa.func.now(), nullable=False),
    )

    op.create_table(
        'raw_snapshots',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('source_id', sa.String(64), nullable=False, index=True),
        sa.Column('requested_url', sa.String(2048), nullable=False),
        sa.Column('canonical_url', sa.String(2048), nullable=False),
        sa.Column('retrieved_at', sa.DateTime, default=sa.func.now(), nullable=False),
        sa.Column('http_status', sa.Integer, nullable=True),
        sa.Column('content_type', sa.String(255), nullable=True),
        sa.Column('content_hash', sa.String(64), nullable=False),
        sa.Column('raw_content_location', sa.String(1024), nullable=False),
        sa.Column('response_headers', sa.JSON, default=dict),
        sa.Column('fetch_duration_ms', sa.Integer, default=0, nullable=False),
        sa.Column('parser_version', sa.String(32), default='unknown', nullable=False),
        sa.Column('collection_run_id', sa.String(64), nullable=False, index=True),
        sa.Column('data_quality_status', sa.Enum(DataQualityStatus), default=DataQualityStatus.UNKNOWN, nullable=False),
        sa.Column('error_code', sa.String(64), nullable=True),
        sa.Column('error_message', sa.Text, nullable=True),
    )

    op.create_table(
        'intelligence_records',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('source_id', sa.String(64), nullable=False, index=True),
        sa.Column('record_type', sa.Enum(RecordType), nullable=False),
        sa.Column('title', sa.Text, default='', nullable=False),
        sa.Column('summary', sa.Text, default='', nullable=False),
        sa.Column('published_at', sa.DateTime, nullable=True),
        sa.Column('effective_at', sa.DateTime, nullable=True),
        sa.Column('canonical_url', sa.String(2048), nullable=False),
        sa.Column('source_reference', sa.String(512), default='', nullable=False),
        sa.Column('content_hash', sa.String(64), nullable=False, index=True),
        sa.Column('raw_snapshot_id', sa.String(64), nullable=False),
        sa.Column('confidence_status', sa.Enum(ConfidenceStatus), default=ConfidenceStatus.UNVERIFIED, nullable=False),
        sa.Column('validation_status', sa.Enum(ValidationStatus), default=ValidationStatus.PENDING, nullable=False),
        # data_quality_status — present in ORM; was missing from initial migration
        sa.Column('data_quality_status', sa.Enum(DataQualityStatus), default=DataQualityStatus.UNKNOWN, nullable=False),
        sa.Column('parser_version', sa.String(32), default='unknown', nullable=False),
        sa.Column('first_seen_at', sa.DateTime, default=sa.func.now(), nullable=False),
        sa.Column('last_seen_at', sa.DateTime, default=sa.func.now(), nullable=False),
        sa.Column('metadata', sa.JSON, default=dict),
    )

    op.create_table(
        'collection_runs',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('source_id', sa.String(64), nullable=False, index=True),
        sa.Column('started_at', sa.DateTime, default=sa.func.now(), nullable=False),
        sa.Column('completed_at', sa.DateTime, nullable=True),
        sa.Column('status', sa.Enum(CollectionRunStatus), default=CollectionRunStatus.PENDING, nullable=False),
        sa.Column('pages_requested', sa.Integer, default=0, nullable=False),
        sa.Column('pages_succeeded', sa.Integer, default=0, nullable=False),
        sa.Column('pages_failed', sa.Integer, default=0, nullable=False),
        sa.Column('records_extracted', sa.Integer, default=0, nullable=False),
        sa.Column('records_inserted', sa.Integer, default=0, nullable=False),
        sa.Column('records_updated', sa.Integer, default=0, nullable=False),
        sa.Column('duplicates_ignored', sa.Integer, default=0, nullable=False),
        sa.Column('failure_reason', sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_table('collection_runs')
    op.drop_table('intelligence_records')
    op.drop_table('raw_snapshots')
    op.drop_table('approved_sources')
