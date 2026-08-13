"""Record which provider an account signs in with.

An account created through Google or Discord has no password — not locally and
not at Supabase — so the change-password form must not be offered to it, and
"forgot password" would be meaningless. Storing the provider on the profile
lets the UI reflect that without a round-trip to Supabase on every page.

Existing rows are backfilled to 'email', which is what they all are.

Revision ID: d5b204ef7c19
Revises: c3f81d20a5e7
"""

import sqlalchemy as sa
from alembic import op

revision = "d5b204ef7c19"
down_revision = "c3f81d20a5e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("user") as batch:
        batch.add_column(sa.Column("auth_provider", sa.String(length=30), nullable=True))

    # Everything that exists today is a password account.
    op.execute("UPDATE \"user\" SET auth_provider = 'email' WHERE auth_provider IS NULL")


def downgrade() -> None:
    with op.batch_alter_table("user") as batch:
        batch.drop_column("auth_provider")
