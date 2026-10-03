"""Persist exact SEC index membership for verified completeness reports.

Revision ID: 0002_completeness_members
Revises: 0001_initial
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_completeness_members"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "completeness_index_members",
        sa.Column("accession_no", sa.Text(), nullable=False),
        sa.Column("form_type", sa.Text(), nullable=False),
        sa.Column("filed_date", sa.Date(), nullable=False),
        sa.PrimaryKeyConstraint("accession_no", name=op.f("pk_completeness_index_members")),
    )
    op.create_index(
        "ix_completeness_index_members_date_form",
        "completeness_index_members",
        ["filed_date", "form_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_completeness_index_members_date_form", table_name="completeness_index_members")
    op.drop_table("completeness_index_members")
