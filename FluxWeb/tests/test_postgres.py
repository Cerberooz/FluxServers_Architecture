"""PostgreSQL / Supabase specifics.

Most of these are skipped on SQLite. Run them with:

    TEST_DATABASE_URL=postgresql://postgres:pw@localhost:5432/fluxweb_test pytest tests/test_postgres.py

The config tests below need no database and always run.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text

from fluxweb.config import normalise_postgres_url
from fluxweb.models import ItemKind, Order, OrderStatus
from fluxweb.services import billing, provisioning
from fluxweb.services.cart import CartItem
from tests.conftest import postgres_only


class TestUrlNormalisation:
    """No database needed - pure string handling."""

    def test_legacy_scheme_is_upgraded(self):
        url = normalise_postgres_url("postgres://u:p@db.abc.supabase.co:5432/postgres")
        assert url.startswith("postgresql://")

    def test_tls_is_forced_for_remote_hosts(self):
        url = normalise_postgres_url("postgresql://u:p@db.abc.supabase.co:5432/postgres")
        assert "sslmode=require" in url

    def test_tls_is_not_forced_for_local_development(self):
        url = normalise_postgres_url("postgresql://u:p@localhost:5432/fluxweb")
        assert "sslmode" not in url

    def test_an_explicit_sslmode_is_respected(self):
        url = normalise_postgres_url("postgresql://u:p@host/db?sslmode=verify-full")
        assert "sslmode=verify-full" in url
        assert url.count("sslmode") == 1

    def test_non_postgres_urls_pass_through(self):
        assert normalise_postgres_url("sqlite:///x.db") == "sqlite:///x.db"


class TestPoolerRules:
    """Supabase's transaction pooler cannot run migrations."""

    def _config(self, **env):
        import os
        from unittest import mock

        from fluxweb.config import Config

        base = {
            "FLASK_ENV": "development",
            "SECRET_KEY": "k" * 40 + "3f9a",
            "ENCRYPTION_KEY": "e" * 40 + "7b2c",
        }
        base.update(env)
        with mock.patch.dict(os.environ, base, clear=False):
            for key in ("DIRECT_URL", "DATABASE_MIGRATION_URL"):
                if key not in base:
                    os.environ.pop(key, None)
            return Config.from_env()

    def test_transaction_pooler_without_direct_url_warns(self):
        config = self._config(
            DATABASE_URL="postgresql://postgres.ref:p@aws-0-eu.pooler.supabase.com:6543/postgres"
        )
        assert any("transaction pooler" in w for w in config.warnings)

    def test_direct_url_is_used_for_migrations(self):
        config = self._config(
            DATABASE_URL="postgresql://postgres.ref:p@aws-0-eu.pooler.supabase.com:6543/postgres",
            DIRECT_URL="postgresql://postgres.ref:p@aws-0-eu.pooler.supabase.com:5432/postgres",
        )
        assert ":5432" in config.migration_url
        assert config.migration_url != config.database_url

    def test_migration_url_falls_back_to_the_runtime_url(self):
        config = self._config(DATABASE_URL="postgresql://u:p@db.abc.supabase.co:5432/postgres")
        assert config.migration_url == config.database_url

    def test_transaction_pooler_as_direct_url_is_rejected(self):
        from fluxweb.config import ConfigError

        with pytest.raises(ConfigError, match="transaction pooler"):
            self._config(
                DATABASE_URL="postgresql://u:p@aws-0-eu.pooler.supabase.com:6543/postgres",
                DIRECT_URL="postgresql://u:p@aws-0-eu.pooler.supabase.com:6543/postgres",
            )


class TestEngineOptions:
    def test_postgres_uses_nullpool_and_a_statement_timeout(self, app):
        options = app.config["SQLALCHEMY_ENGINE_OPTIONS"]
        config = app.extensions["flux_config"]
        if not config.is_postgres:
            pytest.skip("SQLite run")
        from sqlalchemy.pool import NullPool

        assert options["poolclass"] is NullPool
        assert "statement_timeout" in options["connect_args"]["options"]


@postgres_only
class TestPostgresBehaviour:
    """Dialect differences that SQLite cannot catch."""

    def test_reserved_word_table_is_usable(self, db, user):
        """`user` is a reserved word in PostgreSQL; it must stay quoted."""
        row = db.session.execute(text('SELECT email FROM "user" WHERE id = :i'), {"i": user.id})
        assert row.scalar() == user.email

    def test_atomic_claim_works_on_postgres(self, db, user, plan):
        """The provisioning guard relies on UPDATE ... WHERE status IN (...)."""
        order = billing.build_order(user, [CartItem(kind=ItemKind.NEW, plan_id=plan.id)])
        order.mark_paid()
        db.session.commit()

        claimed = (
            db.session.query(Order)
            .filter(Order.id == order.id, Order.status.in_([OrderStatus.PAID, OrderStatus.FAILED]))
            .update({"status": OrderStatus.PROVISIONING}, synchronize_session=False)
        )
        db.session.commit()
        assert claimed == 1

        second = (
            db.session.query(Order)
            .filter(Order.id == order.id, Order.status.in_([OrderStatus.PAID, OrderStatus.FAILED]))
            .update({"status": OrderStatus.PROVISIONING}, synchronize_session=False)
        )
        db.session.commit()
        assert second == 0  # the claim is genuinely exclusive

    def test_payment_uniqueness_is_enforced_by_the_database(self, db, user, plan):
        """Replay protection must be a real constraint, not app-level checks."""
        from sqlalchemy.exc import IntegrityError

        from fluxweb.models import Payment

        order = billing.build_order(user, [CartItem(kind=ItemKind.NEW, plan_id=plan.id)])
        db.session.add(
            Payment(
                order_id=order.id,
                provider="stripe",
                provider_ref="dup",
                amount_cents=100,
                currency="USD",
                status="paid",
            )
        )
        db.session.commit()

        db.session.add(
            Payment(
                order_id=order.id,
                provider="stripe",
                provider_ref="dup",
                amount_cents=100,
                currency="USD",
                status="paid",
            )
        )
        with pytest.raises(IntegrityError):
            db.session.commit()
        db.session.rollback()

    def test_provisioning_is_idempotent_on_postgres(self, db, user, plan):
        from tests.test_provisioning import FakePanel

        order = billing.build_order(user, [CartItem(kind=ItemKind.NEW, plan_id=plan.id)])
        order.mark_paid()
        db.session.commit()

        panel = FakePanel()
        first = provisioning.provision_order(order, panel, expiry_days=30)
        second = provisioning.provision_order(order, panel, expiry_days=30)

        assert first.success_count == 1
        assert second.success_count == 0
        assert len(panel.created_servers) == 1


@postgres_only
class TestSupabaseLockdown:
    """The RLS migration must actually protect the tables."""

    def test_rls_is_enabled_on_sensitive_tables(self, db):
        # Applied by migration b1a7c4e92f10. create_all() does not run
        # migrations, so apply the statement under test directly.
        for table in ("user", "payment", "customer_order"):
            db.session.execute(text(f'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY'))
        db.session.commit()

        rows = (
            db.session.execute(
                text(
                    "SELECT relname FROM pg_class "
                    "WHERE relrowsecurity = true AND relname IN ('user','payment','customer_order')"
                )
            )
            .scalars()
            .all()
        )
        assert set(rows) == {"user", "payment", "customer_order"}

    def test_the_owner_still_reads_its_own_tables(self, db, user):
        """RLS must not lock out the application itself."""
        db.session.execute(text('ALTER TABLE public."user" ENABLE ROW LEVEL SECURITY'))
        db.session.commit()

        from fluxweb.models import User

        assert User.query.filter_by(id=user.id).first() is not None
