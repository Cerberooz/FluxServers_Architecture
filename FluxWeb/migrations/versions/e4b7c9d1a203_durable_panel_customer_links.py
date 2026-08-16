"""Store durable Web-to-Panel customer identities."""

from alembic import op
import sqlalchemy as sa

revision = "e4b7c9d1a203"
down_revision = "c7b1d4e9a602"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("user", sa.Column("pelican_user_uuid", sa.String(length=36), nullable=True))
    op.add_column("user", sa.Column("pelican_user_email", sa.String(length=100), nullable=True))
    op.add_column("user", sa.Column("panel_link_source", sa.String(length=32), nullable=True))
    op.add_column("user", sa.Column("panel_linked_at", sa.DateTime(), nullable=True))
    op.create_index("ix_user_pelican_user_uuid", "user", ["pelican_user_uuid"], unique=True)


def downgrade():
    op.drop_index("ix_user_pelican_user_uuid", table_name="user")
    op.drop_column("user", "panel_linked_at")
    op.drop_column("user", "panel_link_source")
    op.drop_column("user", "pelican_user_email")
    op.drop_column("user", "pelican_user_uuid")
