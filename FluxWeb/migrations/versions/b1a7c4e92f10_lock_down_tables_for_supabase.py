"""Lock application tables against Supabase's public REST API.

Supabase exposes the ``public`` schema through PostgREST automatically, and
the ``anon`` key that reaches it is meant to be published in front-end code.
Tables created through the dashboard get Row Level Security switched on for
you; tables created by a migration **do not**.

Without this, ``user`` (emails + password hashes), ``payment``, and
``customer_order`` would be readable — and writable — by anyone who has the
anon key, with no application code involved at all.

Two independent controls, because either alone is one mistake from exposure:

1. RLS enabled with **no policies**, so PostgREST resolves zero rows for the
   ``anon`` and ``authenticated`` roles. The application is unaffected: it
   connects as the table owner, and owners bypass RLS unless FORCE is set.
2. Privileges revoked from those roles outright, so the API cannot even reach
   the tables to be filtered.

Idempotent, and a no-op on non-PostgreSQL backends (the test suite runs on
SQLite) and on plain PostgreSQL installs that have no Supabase roles.

Revision ID: b1a7c4e92f10
Revises: 605cf98f5dbd
"""

from alembic import op

revision = "b1a7c4e92f10"
down_revision = "605cf98f5dbd"
branch_labels = None
depends_on = None


#: Every table this application owns. `alembic_version` is included so the
#: migration history itself cannot be read or rewritten through the API.
APP_TABLES = (
    "user",
    "verification_token",
    "server_record",
    "game_plan",
    "customer_order",
    "customer_order_item",
    "payment",
    "coupon",
    "announcement",
    "maintenance_update",
    "service_status",
    "faq",
    "globe_location",
    "referral_code",
    "alembic_version",
)

EXPOSED_ROLES = ("anon", "authenticated")


def _is_postgres() -> bool:
    return op.get_bind().dialect.name == "postgresql"


def upgrade() -> None:
    if not _is_postgres():
        return

    for table in APP_TABLES:
        # to_regclass returns NULL rather than raising for a missing table,
        # which keeps this safe to run against a partially built schema.
        op.execute(
            f"""
            DO $$
            BEGIN
                IF to_regclass('public."{table}"') IS NOT NULL THEN
                    EXECUTE 'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY';
                END IF;
            END $$;
            """
        )

    for role in EXPOSED_ROLES:
        # S608: both interpolated values are module-level constants defined
        # above, never user input. Table identifiers additionally go through
        # quote_ident/format %I inside the block.
        op.execute(  # noqa: S608
            f"""
            DO $$
            DECLARE
                target_table text;
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                    RETURN;
                END IF;
                FOREACH target_table IN ARRAY ARRAY[{",".join(f"'{t}'" for t in APP_TABLES)}]
                LOOP
                    IF to_regclass('public.' || quote_ident(target_table)) IS NOT NULL THEN
                        EXECUTE format(
                            'REVOKE ALL PRIVILEGES ON TABLE public.%I FROM {role}',
                            target_table
                        );
                    END IF;
                END LOOP;
            END $$;
            """
        )


def downgrade() -> None:
    if not _is_postgres():
        return

    # Only RLS is reversed. Privileges are deliberately NOT re-granted: doing
    # so on a downgrade would silently republish customer data to the public
    # API. Re-grant by hand if you genuinely want that.
    for table in APP_TABLES:
        op.execute(
            f"""
            DO $$
            BEGIN
                IF to_regclass('public."{table}"') IS NOT NULL THEN
                    EXECUTE 'ALTER TABLE public."{table}" DISABLE ROW LEVEL SECURITY';
                END IF;
            END $$;
            """
        )
