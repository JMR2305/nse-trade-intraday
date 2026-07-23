"""RC-10A: announcements table and sector column on instrument_master

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-23

"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add sector column to instrument_master
    op.add_column(
        "instrument_master",
        sa.Column("sector", sa.String(50), nullable=True),
    )
    op.create_index("ix_instrument_master_sector", "instrument_master", ["sector"])

    # Create announcements table
    op.create_table(
        "announcements",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("announcement_id", sa.String(100), nullable=False),
        sa.Column("exchange", sa.String(10), nullable=False),
        sa.Column("instrument_token", sa.String(50), nullable=False),
        sa.Column("tradingsymbol", sa.String(50), nullable=False),
        sa.Column("classification", sa.String(30), nullable=False),
        sa.Column("headline", sa.Text, nullable=False),
        sa.Column("body_text", sa.Text, nullable=True),
        sa.Column("ai_summary", sa.Text, nullable=True),
        sa.Column("model_version", sa.String(20), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_date", sa.Date, nullable=True),
        sa.Column("raw_metadata", sa.JSON, default=dict),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
    )

    op.create_index(
        "ix_announcements_exchange_id",
        "announcements",
        ["exchange", "announcement_id"],
        unique=True,
    )
    op.create_index(
        "ix_announcements_instrument_published",
        "announcements",
        ["instrument_token", "published_at"],
    )
    op.create_index(
        "ix_announcements_classification_published",
        "announcements",
        ["classification", "published_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_announcements_classification_published", table_name="announcements")
    op.drop_index("ix_announcements_instrument_published", table_name="announcements")
    op.drop_index("ix_announcements_exchange_id", table_name="announcements")
    op.drop_table("announcements")

    op.drop_index("ix_instrument_master_sector", table_name="instrument_master")
    op.drop_column("instrument_master", "sector")
