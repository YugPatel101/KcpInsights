"""completeness cache, industry profile, OCR and retry tracking, listing-day range, peer prices

Revision ID: 7c41e2b9d5a3
Revises: 2b2dff38225b
Create Date: 2026-10-31 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "7c41e2b9d5a3"
down_revision: str | Sequence[str] | None = "2b2dff38225b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("companies", schema=None) as batch_op:
        batch_op.add_column(sa.Column("industry_profile", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("classification", sa.JSON(), nullable=True))
        batch_op.create_index("ix_companies_industry_profile", ["industry_profile"], unique=False)

    with op.batch_alter_table("ipo_issues", schema=None) as batch_op:
        batch_op.add_column(sa.Column("listing_high_price", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("listing_low_price", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("completeness_pct", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("completeness_summary", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("completeness_at", sa.DateTime(), nullable=True))

    with op.batch_alter_table("source_documents", schema=None) as batch_op:
        batch_op.add_column(sa.Column("extraction_method", sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column("attempts", sa.Integer(), server_default="0", nullable=False))
        batch_op.add_column(sa.Column("next_attempt_at", sa.DateTime(), nullable=True))

    with op.batch_alter_table("peer_snapshots", schema=None) as batch_op:
        batch_op.add_column(sa.Column("nse_symbol", sa.String(length=32), nullable=True))
        batch_op.add_column(sa.Column("latest_price", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("latest_price_date", sa.Date(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("peer_snapshots", schema=None) as batch_op:
        batch_op.drop_column("latest_price_date")
        batch_op.drop_column("latest_price")
        batch_op.drop_column("nse_symbol")

    with op.batch_alter_table("source_documents", schema=None) as batch_op:
        batch_op.drop_column("next_attempt_at")
        batch_op.drop_column("attempts")
        batch_op.drop_column("extraction_method")

    with op.batch_alter_table("ipo_issues", schema=None) as batch_op:
        batch_op.drop_column("completeness_at")
        batch_op.drop_column("completeness_summary")
        batch_op.drop_column("completeness_pct")
        batch_op.drop_column("listing_low_price")
        batch_op.drop_column("listing_high_price")

    with op.batch_alter_table("companies", schema=None) as batch_op:
        batch_op.drop_index("ix_companies_industry_profile")
        batch_op.drop_column("classification")
        batch_op.drop_column("industry_profile")
