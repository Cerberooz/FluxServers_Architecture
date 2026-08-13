"""Regression tests for the authentication and account findings."""

from __future__ import annotations

import secrets

import pytest
from cryptography.fernet import Fernet

from fluxweb.config import Config, ConfigError, PaymentConfig
from fluxweb.errors import DomainError, ValidationError
from fluxweb.models import User
from fluxweb.services import accounts
from fluxweb.web.helpers import safe_redirect_target


class TestOpenRedirect:
    """M-19: post-login redirects must stay on this site."""

    @pytest.mark.parametrize(
        "hostile",
        [
            r"\evil.com",
            r"/\evil.com",
            "//evil.com",
            "https://evil.com",
            "http://evil.com/path",
            r"\\evil.com",
        ],
    )
    def test_offsite_targets_are_rejected(self, app, hostile):
        with app.test_request_context():
            assert safe_redirect_target(hostile) == "/"

    @pytest.mark.parametrize("safe", ["/account", "account", "/cart", "/admin/plans/export"])
    def test_internal_targets_are_preserved(self, app, safe):
        with app.test_request_context():
            assert safe_redirect_target(safe).startswith("/")
            assert "evil" not in safe_redirect_target(safe)


class TestPanelAccountTakeover:
    """C-8: a pre-existing panel user is never adopted by email address."""

    def test_client_has_no_email_lookup(self):
        import inspect

        from fluxweb.integrations import fluid

        source = inspect.getsource(fluid)
        # The filter[email] lookup was the takeover primitive.
        assert "filter[email]" not in source

    def test_ensure_panel_user_creates_rather_than_adopts(self, db, user):
        from fluxweb.services.provisioning import ensure_panel_user

        calls = {"created": 0, "fetched": 0}

        class FakeClient:
            def get_user(self, panel_id):
                calls["fetched"] += 1

            def create_user(self, *, email, username, first_name):
                calls["created"] += 1
                return 4242, "generated-password"

        panel_id = ensure_panel_user(user, FakeClient())
        assert panel_id == 4242
        assert calls["created"] == 1
        assert user.pelican_user_id == 4242
        # The generated password is stored encrypted and is recoverable by us,
        # but it is NOT the user's site password.
        assert user.pelican_password_decrypted == "generated-password"
        assert not user.check_password("generated-password")


class TestPasswordPolicy:
    """L-39: one policy, applied everywhere."""

    @pytest.mark.parametrize("weak", ["", "short", "1234567890", "abcdefghij"])
    def test_weak_passwords_rejected(self, app, weak):
        with pytest.raises(ValidationError):
            accounts.validate_password(weak)

    def test_reasonable_password_accepted(self, app):
        assert accounts.validate_password("correct-horse-9")

    def test_registration_enforces_the_policy(self, app, db):
        with pytest.raises(ValidationError):
            accounts.register_user(username="Someone", email="a@b.com", password="short")


class TestUserEnumeration:
    """L-38: duplicate registration must not be distinguishable."""

    def test_duplicate_registration_returns_no_user_and_no_error(self, db, user):
        result, token = accounts.register_user(
            username="Impostor", email=user.email, password="correct-horse-9"
        )
        assert result is None
        assert token is None
        assert User.query.filter_by(email=user.email).count() == 1


class TestEmailVerification:
    def test_new_accounts_start_unverified(self, db):
        created, token = accounts.register_user(
            username="Fresh", email="fresh@example.com", password="correct-horse-9"
        )
        assert created is not None
        assert not created.email_verified
        assert token

    def test_token_verifies_once_only(self, db):
        created, token = accounts.register_user(
            username="Fresh", email="fresh@example.com", password="correct-horse-9"
        )
        accounts.confirm_email(token)
        assert created.email_verified
        with pytest.raises(DomainError):
            accounts.confirm_email(token)

    def test_tokens_are_stored_hashed(self, db):
        from fluxweb.models import VerificationToken

        _, token = accounts.register_user(
            username="Fresh", email="fresh@example.com", password="correct-horse-9"
        )
        stored = VerificationToken.query.first()
        assert stored.token_hash != token
        assert len(stored.token_hash) == 64


class TestPasswordIsNotMirroredToPanel:
    """H-15: changing the site password must not touch panel credentials."""

    def test_change_password_leaves_panel_credential_alone(self, db, user):
        user.set_pelican_password("panel-original")
        db.session.commit()

        accounts.change_password(user, "a-new-site-password-1")

        assert user.check_password("a-new-site-password-1")
        assert user.pelican_password_decrypted == "panel-original"


class TestAccountLockout:
    """H-10: repeated failures lock the account."""

    def test_lockout_after_threshold(self, db, user):
        for _ in range(8):
            user.register_failed_login()
        assert user.is_locked

    def test_successful_login_clears_state(self, db, user):
        user.register_failed_login()
        user.register_successful_login()
        assert user.failed_login_count == 0
        assert not user.is_locked


class TestConfigValidation:
    """C-1, S-3: unsafe configuration must stop the app booting."""

    def _prod_env(self, monkeypatch, **overrides):
        # Use realistic random values: repeated characters like "x" * 64 trip
        # the placeholder detector, which is correct behaviour.
        base = {
            "FLASK_ENV": "production",
            "SECRET_KEY": secrets.token_urlsafe(64),
            "ENCRYPTION_KEY": Fernet.generate_key().decode(),
            "CRON_SECRET": secrets.token_urlsafe(32),
            "DATABASE_URL": "postgresql://u:p@h/db",
            "BASE_URL": "https://example.com",
            "PELICAN_URL": "https://panel.example.com",
            "PELICAN_API_KEY": "key",
            "SMTP_HOST": "smtp.example.com",
            "STRIPE_SECRET_KEY": "sk_live_x",
            "STRIPE_PUBLISHABLE_KEY": "pk_live_x",
            "STRIPE_WEBHOOK_SECRET": "whsec_x",
            # Production requires Supabase Auth; the local password backend is
            # development-only. See test_supabase_auth.TestConfiguration.
            "SUPABASE_URL": "https://project.supabase.co",
            "SUPABASE_ANON_KEY": "anon-key-value",
            "SUPABASE_SERVICE_ROLE_KEY": "service-role-key-value",
        }
        base.update(overrides)
        for key in list(base):
            monkeypatch.setenv(key, base[key])
        for unset in ("PAYPAL_CLIENT_ID", "PAYPAL_SECRET_KEY", "PAYPAL_ENV", "PAYPAL_MERCHANT_ID"):
            if unset not in base:
                monkeypatch.delenv(unset, raising=False)

    def test_weak_secret_key_refuses_to_boot(self, monkeypatch):
        self._prod_env(monkeypatch, SECRET_KEY="flux-secret-123-asdjkhasjkhdj")
        with pytest.raises(ConfigError):
            Config.from_env()

    def test_missing_secret_key_refuses_to_boot(self, monkeypatch):
        self._prod_env(monkeypatch)
        monkeypatch.delenv("SECRET_KEY")
        with pytest.raises(ConfigError):
            Config.from_env()

    def test_no_sqlite_fallback_in_production(self, monkeypatch):
        self._prod_env(monkeypatch)
        monkeypatch.delenv("DATABASE_URL")
        with pytest.raises(ConfigError):
            Config.from_env()

    def test_half_configured_paypal_refuses_to_boot(self, monkeypatch):
        self._prod_env(monkeypatch, PAYPAL_CLIENT_ID="live-client-id")
        with pytest.raises(ConfigError):
            Config.from_env()

    def test_provider_mode_mismatch_refuses_to_boot(self, monkeypatch):
        self._prod_env(
            monkeypatch,
            PAYPAL_CLIENT_ID="c",
            PAYPAL_SECRET_KEY="s",
            PAYPAL_ENV="sandbox",
            PAYPAL_MERCHANT_ID="m",
        )
        with pytest.raises(ConfigError):
            Config.from_env()

    def test_missing_webhook_secret_refuses_to_boot(self, monkeypatch):
        self._prod_env(monkeypatch)
        monkeypatch.delenv("STRIPE_WEBHOOK_SECRET")
        with pytest.raises(ConfigError):
            Config.from_env()

    def test_valid_production_config_boots(self, monkeypatch):
        self._prod_env(monkeypatch)
        config = Config.from_env()
        assert config.is_production
        assert config.payments.stripe_is_live

    def test_development_generates_ephemeral_keys_not_fixed_defaults(self, monkeypatch):
        for key in ("SECRET_KEY", "ENCRYPTION_KEY", "DATABASE_URL", "STRIPE_SECRET_KEY"):
            monkeypatch.delenv(key, raising=False)
        monkeypatch.setenv("FLASK_ENV", "development")
        monkeypatch.setenv("PAYPAL_CLIENT_ID", "c")
        monkeypatch.setenv("PAYPAL_SECRET_KEY", "s")

        first = Config.from_env()
        second = Config.from_env()
        assert first.secret_key != second.secret_key  # random, not a shared constant
        assert len(first.secret_key) >= 32


class TestPaymentConfigCoherence:
    def test_stripe_only_is_valid(self):
        payments = PaymentConfig(
            stripe_publishable_key="pk_live_x",
            stripe_secret_key="sk_live_x",
            stripe_webhook_secret="whsec",
        )
        assert payments.validate(production=True) == []

    def test_no_provider_is_fatal_in_production_only(self):
        """Local development must run with no payment credentials at all."""
        assert PaymentConfig().validate(production=False) == []
        assert PaymentConfig().validate(production=True)

    def test_placeholder_secret_is_detected(self):
        from fluxweb.config import _looks_weak

        assert _looks_weak("changeme")
        assert _looks_weak("flux-secret-123-asdjkhasjkhdjkashdkjashd")
        assert _looks_weak("short")
        assert not _looks_weak(secrets.token_urlsafe(64))
