"""Shared test fixtures.

By default the suite runs on in-memory SQLite, which is fast and needs no
services. Production is PostgreSQL, and the two dialects do differ — reserved
words, boolean handling, `UPDATE ... WHERE status IN (...)` semantics — so the
same suite can be pointed at a real database:

    TEST_DATABASE_URL=postgresql://postgres:pw@localhost:5432/fluxweb_test pytest

CI runs it both ways. Anything that passes on SQLite but fails on Postgres is
a dialect bug worth knowing about before production finds it.
"""

from __future__ import annotations

import os

import pytest
from cryptography.fernet import Fernet

from fluxweb import create_app
from fluxweb.config import Config, PaymentConfig
from fluxweb.extensions import db as _db
from fluxweb.models import Coupon, GamePlan, ServerRecord, User

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", "sqlite:///:memory:")


def running_on_postgres() -> bool:
    return TEST_DATABASE_URL.startswith("postgres")


#: Skip decorator for assertions that only hold on a real database.
postgres_only = pytest.mark.skipif(
    not running_on_postgres(),
    reason="requires PostgreSQL; set TEST_DATABASE_URL to run",
)


@pytest.fixture
def config() -> Config:
    return Config(
        env="testing",
        secret_key="test-secret-key-that-is-long-enough-for-validation",
        encryption_key=Fernet.generate_key().decode(),
        database_url=TEST_DATABASE_URL,
        admin_email="admin@example.com",
        base_url="http://localhost",
        panel_url="https://panel.example.com",
        panel_api_key="test-key",
        payments=PaymentConfig(
            stripe_publishable_key="pk_test_x",
            stripe_secret_key="sk_test_x",
            stripe_webhook_secret="whsec_test",
            paypal_client_id="paypal-client",
            paypal_secret_key="paypal-secret",
            paypal_env="sandbox",
            paypal_merchant_id="MERCHANT123",
        ),
    )


@pytest.fixture
def app(config):
    application = create_app(config)
    application.config["WTF_CSRF_ENABLED"] = False
    with application.app_context():
        # drop_all first so a crashed previous run cannot leave a half-built
        # schema behind on a persistent (Postgres) test database.
        if running_on_postgres():
            _db.drop_all()
        _db.create_all()
        yield application
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def db(app):
    return _db


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def user(db):
    account = User(username="Tester", email="tester@example.com")
    account.set_password("correct-horse-battery")
    account.mark_email_verified()
    db.session.add(account)
    db.session.commit()
    return account


@pytest.fixture
def other_user(db):
    account = User(username="Other", email="other@example.com")
    account.set_password("correct-horse-battery")
    account.mark_email_verified()
    db.session.add(account)
    db.session.commit()
    return account


@pytest.fixture
def plan(db):
    game_plan = GamePlan(
        game="minecraft",
        name="Diamond",
        price=7.20,
        memory=8192,
        cpu=300,
        disk=102400,
        nest_id="General",
        egg_id=1,
        location_id=1,
        backups=4,
        allocations=3,
        databases=3,
        serial_number=1,
    )
    db.session.add(game_plan)
    db.session.commit()
    return game_plan


@pytest.fixture
def bigger_plan(db):
    game_plan = GamePlan(
        game="minecraft",
        name="Netherite",
        price=10.80,
        memory=12288,
        cpu=400,
        disk=153600,
        nest_id="General",
        egg_id=1,
        location_id=1,
        serial_number=2,
    )
    db.session.add(game_plan)
    db.session.commit()
    return game_plan


@pytest.fixture
def cheap_big_plan(db):
    """A lower-priced plan with better specs - the free-upgrade bait."""
    game_plan = GamePlan(
        game="minecraft",
        name="Promo",
        price=1.00,
        memory=16384,
        cpu=800,
        disk=204800,
        nest_id="General",
        egg_id=1,
        location_id=1,
        serial_number=3,
    )
    db.session.add(game_plan)
    db.session.commit()
    return game_plan


@pytest.fixture
def server(db, user, plan):
    record = ServerRecord(
        user_id=user.id,
        plan_id=plan.id,
        plan_name=plan.name,
        pelican_server_id=101,
        pelican_server_identifier="abc12345",
        status="Active",
    )
    db.session.add(record)
    db.session.commit()
    return record


@pytest.fixture
def coupon(db):
    code = Coupon(code="FLUX10", discount_percent=10.0, active=True)
    db.session.add(code)
    db.session.commit()
    return code


@pytest.fixture
def login(client):
    def _login(account: User):
        with client.session_transaction() as sess:
            sess["user_id"] = account.id
        return account

    return _login
