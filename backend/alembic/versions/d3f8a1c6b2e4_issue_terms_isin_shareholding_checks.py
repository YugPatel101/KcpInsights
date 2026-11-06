"""issue terms (ISIN, issue method, listing exchanges) and re-check timestamps for issue details and shareholding

Revision ID: d3f8a1c6b2e4
Revises: 7c41e2b9d5a3
Create Date: 2026-11-02 10:00:00.000000

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d3f8a1c6b2e4"
down_revision: str | Sequence[str] | None = "7c41e2b9d5a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("ipo_issues", schema=None) as batch_op:
        batch_op.add_column(sa.Column("isin", sa.String(length=12), nullable=True))
        batch_op.add_column(sa.Column("issue_method", sa.String(length=16), nullable=True))
        batch_op.add_column(sa.Column("listing_exchanges", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("details_checked_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("shareholding_checked_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("ipo_issues", schema=None) as batch_op:
        batch_op.drop_column("shareholding_checked_at")
        batch_op.drop_column("details_checked_at")
        batch_op.drop_column("listing_exchanges")
        batch_op.drop_column("issue_method")
        batch_op.drop_column("isin")
