"""Link local profiles to Supabase Auth identities.

Credentials move to Supabase/GoTrue. The local ``user`` row stays as the
application's profile and keeps its integer primary key, because
``server_record.user_id`` and ``customer_order.user_id`` reference it — and
repointing those to Supabase's UUIDs would be a large, risky data migration
for no functional gain.

Two changes:

* ``supabase_user_id`` — the GoTrue UUID, unique and indexed.
* ``password_hash`` becomes nullable, because a Supabase-backed account has
  no local hash at all.

Existing rows keep their hashes until `flask migrate-users-to-supabase` runs.
That command creates the Supabase identity and clears the local hash, so no
account ends up with two live credentials.

Revision ID: c3f81d20a5e7
Revises: b1a7c4e92f10
"""

import sqlalchemy as sa
from alembic import op

revision = "c3f81d20a5e7"
down_revision = "b1a7c4e92f10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("user") as batch:
        batch.add_column(sa.Column("supabase_user_id", sa.String(length=36), nullable=True))
        batch.alter_column("password_hash", existing_type=sa.String(length=255), nullable=True)
        batch.create_unique_constraint("uq_user_supabase_user_id", ["supabase_user_id"])
        batch.create_index("ix_user_supabase_user_id", ["supabase_user_id"])


def downgrade() -> None:
    # Accounts created through Supabase have no local hash, so a straight
    # revert would violate a NOT NULL constraint. Give them an unusable
    # placeholder rather than failing or, worse, leaving them loginable.
    op.execute(
        "UPDATE \"user\" SET password_hash = '!disabled-by-downgrade' WHERE password_hash IS NULL"
    )

    with op.batch_alter_table("user") as batch:
        batch.drop_index("ix_user_supabase_user_id")
        batch.drop_constraint("uq_user_supabase_user_id", type_="unique")
        batch.drop_column("supabase_user_id")
        batch.alter_column("password_hash", existing_type=sa.String(length=255), nullable=False)
