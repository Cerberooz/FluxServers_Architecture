"""Allow each plan to expose multiple selectable deployment locations.

Revision ID: e8f1b7a4c2d9
Revises: d5b204ef7c19
"""

import sqlalchemy as sa
from alembic import op

revision = "e8f1b7a4c2d9"
down_revision = "d5b204ef7c19"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("game_plan") as batch:
        batch.add_column(sa.Column("allowed_location_ids", sa.Text(), nullable=True))

    op.execute("UPDATE game_plan SET allowed_location_ids = '[]' WHERE allowed_location_ids IS NULL")


def downgrade() -> None:
    with op.batch_alter_table("game_plan") as batch:
        batch.drop_column("allowed_location_ids")
