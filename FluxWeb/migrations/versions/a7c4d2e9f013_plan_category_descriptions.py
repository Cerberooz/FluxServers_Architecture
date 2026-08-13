"""Plan category descriptions.

Revision ID: a7c4d2e9f013
Revises: f2a9c1d8e4b7
Create Date: 2026-08-11
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "a7c4d2e9f013"
down_revision = "f2a9c1d8e4b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("plan_category", schema=None) as batch_op:
        batch_op.add_column(sa.Column("description", sa.Text(), nullable=True))

    with op.batch_alter_table("plan_subcategory", schema=None) as batch_op:
        batch_op.add_column(sa.Column("description", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("plan_subcategory", schema=None) as batch_op:
        batch_op.drop_column("description")

    with op.batch_alter_table("plan_category", schema=None) as batch_op:
        batch_op.drop_column("description")
