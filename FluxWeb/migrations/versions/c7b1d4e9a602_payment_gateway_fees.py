"""store provider fee snapshots on orders

Revision ID: c7b1d4e9a602
Revises: f9a3d7c2b814
"""
from alembic import op
import sqlalchemy as sa

revision = "c7b1d4e9a602"
down_revision = "f9a3d7c2b814"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("customer_order") as batch:
        batch.add_column(sa.Column("gateway_fee_cents", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("payment_provider", sa.String(length=20), nullable=True))


def downgrade():
    with op.batch_alter_table("customer_order") as batch:
        batch.drop_column("payment_provider")
        batch.drop_column("gateway_fee_cents")
