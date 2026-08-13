"""store plan egg choices and frozen customer selections

Revision ID: f9a3d7c2b814
Revises: a7c4d2e9f013
"""
from alembic import op
import sqlalchemy as sa

revision = "f9a3d7c2b814"
down_revision = "a7c4d2e9f013"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("game_plan") as batch:
        batch.add_column(sa.Column("allowed_egg_ids", sa.Text(), nullable=True))
    op.execute("UPDATE game_plan SET allowed_egg_ids = '[' || egg_id || ']' WHERE allowed_egg_ids IS NULL")
    with op.batch_alter_table("customer_order_item") as batch:
        batch.add_column(sa.Column("node_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("egg_id", sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table("customer_order_item") as batch:
        batch.drop_column("egg_id")
        batch.drop_column("node_id")
    with op.batch_alter_table("game_plan") as batch:
        batch.drop_column("allowed_egg_ids")
