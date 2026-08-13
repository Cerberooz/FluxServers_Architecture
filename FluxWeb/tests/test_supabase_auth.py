"""Supabase Auth backend.

Exercised against a fake GoTrue rather than the network, so the behaviour that
matters — enumeration resistance, profile linkage, re-authentication on
password change, error translation — is verified without a Supabase project.
"""

from __future__ import annotations

import pytest

from fluxweb.errors import IntegrationError, ValidationError
from fluxweb.integrations.supabase_auth import AuthError, SupabaseUser
from fluxweb.models import User
from fluxweb.services import accounts
from fluxweb.services.auth_backends import SupabaseAuthBackend


class FakeGoTrue:
    """In-memory stand-in for the GoTrue REST API."""

    def __init__(self):
        self.users: dict[str, dict] = {}
        self.reset_emails: list[str] = []
        self.confirmation_emails: list[str] = []
        self.signed_out: list[str] = []
        self._next_id = 1

    def _make(self, email, password, confirmed):
        uid = f"00000000-0000-0000-0000-{self._next_id:012d}"
        self._next_id += 1
        self.users[email.lower()] = {"id": uid, "email": email, "password": password, "confirmed": confirmed}
        return uid

    def _as_user(self, record):
        return SupabaseUser(
            id=record["id"],
            email=record["email"],
            email_confirmed=record["confirmed"],
            raw=record,
        )

    # --- public API -----------------------------------------------------
    def sign_up(self, *, email, password, redirect_to=None, metadata=None):
        if email.lower() in self.users:
            raise AuthError("That email address is already registered.")
        self._make(email, password, confirmed=False)
        self.confirmation_emails.append(email)
        return self._as_user(self.users[email.lower()])

    def sign_in(self, *, email, password):
        from fluxweb.integrations.supabase_auth import AuthSession

        record = self.users.get(email.lower())
        if record is None or record["password"] != password:
            raise AuthError("Invalid credentials.")
        if not record["confirmed"]:
            raise AuthError("Please confirm your email address before signing in.")
        return AuthSession(user=self._as_user(record), access_token=f"at-{record['id']}", refresh_token="rt")

    def send_password_reset(self, *, email, redirect_to=None):
        # GoTrue does not disclose whether the address exists.
        self.reset_emails.append(email)

    def resend_confirmation(self, *, email, redirect_to=None):
        self.confirmation_emails.append(email)

    def verify_token_hash(self, *, token_hash, verification_type):
        from fluxweb.integrations.supabase_auth import AuthSession

        email = token_hash.removeprefix("valid-")
        record = self.users.get(email.lower())
        if token_hash == "expired" or record is None:
            raise AuthError("That link has expired. Please request a new one.")
        record["confirmed"] = True
        return AuthSession(user=self._as_user(record), access_token=f"at-{record['id']}", refresh_token="rt")

    def update_password(self, *, access_token, password):
        for record in self.users.values():
            if access_token == f"at-{record['id']}":
                record["password"] = password
                return self._as_user(record)
        raise AuthError("Invalid credentials.")

    def sign_out(self, access_token):
        self.signed_out.append(access_token)

    # --- admin ----------------------------------------------------------
    def admin_create_user(self, *, email, password, email_confirm=False, metadata=None):
        self._make(email, password, confirmed=email_confirm)
        return self._as_user(self.users[email.lower()])

    def admin_find_user_by_email(self, email):
        record = self.users.get(email.lower())
        return self._as_user(record) if record else None

    def admin_update_user(self, user_id, **fields):
        for record in self.users.values():
            if record["id"] == user_id:
                if "password" in fields:
                    record["password"] = fields["password"]
                if fields.get("email_confirm"):
                    record["confirmed"] = True
                return self._as_user(record)
        raise AuthError("No such user.")


@pytest.fixture
def gotrue():
    return FakeGoTrue()


@pytest.fixture
def backend(gotrue):
    return SupabaseAuthBackend(gotrue)


class TestRegistration:
    def test_creates_supabase_identity_and_local_profile(self, db, backend, gotrue):
        user, token = accounts.register_user(
            username="Newbie", email="new@example.com", password="correct-horse-9", backend=backend
        )

        assert user is not None
        assert user.supabase_user_id  # linked to the GoTrue identity
        assert user.password_hash is None  # no local credential at all
        assert token is None  # Supabase sent the email, not us
        assert gotrue.confirmation_emails == ["new@example.com"]

    def test_new_accounts_start_unverified(self, db, backend):
        user, _ = accounts.register_user(
            username="Newbie", email="new@example.com", password="correct-horse-9", backend=backend
        )
        assert not user.email_verified

    def test_duplicate_local_profile_is_indistinguishable(self, db, backend, user):
        result, token = accounts.register_user(
            username="Impostor", email=user.email, password="correct-horse-9", backend=backend
        )
        assert result is None
        assert token is None
        assert User.query.filter_by(email=user.email).count() == 1

    def test_duplicate_at_the_provider_is_also_silent(self, db, backend, gotrue):
        """An identity can exist upstream with no local profile."""
        gotrue.admin_create_user(email="ghost@example.com", password="x" * 12, email_confirm=True)

        result, token = accounts.register_user(
            username="Ghost", email="ghost@example.com", password="correct-horse-9", backend=backend
        )
        assert result is None
        assert token is None

    def test_password_policy_runs_before_the_provider(self, db, backend, gotrue):
        with pytest.raises(ValidationError):
            accounts.register_user(
                username="Weak", email="weak@example.com", password="short", backend=backend
            )
        assert gotrue.users == {}  # never reached the network


class TestSignIn:
    def _register_and_confirm(self, backend, gotrue, email="user@example.com"):
        accounts.register_user(username="User", email=email, password="correct-horse-9", backend=backend)
        gotrue.users[email]["confirmed"] = True
        return email

    def test_valid_credentials_return_the_local_profile(self, db, backend, gotrue):
        email = self._register_and_confirm(backend, gotrue)
        result = accounts.authenticate(email=email, password="correct-horse-9", backend=backend)
        assert result is not None
        assert result.email == email

    def test_wrong_password_returns_none(self, db, backend, gotrue):
        email = self._register_and_confirm(backend, gotrue)
        assert accounts.authenticate(email=email, password="wrong-one-99", backend=backend) is None

    def test_unknown_address_returns_none(self, db, backend):
        assert (
            accounts.authenticate(email="nobody@example.com", password="correct-horse-9", backend=backend)
            is None
        )

    def test_unconfirmed_account_cannot_sign_in(self, db, backend):
        accounts.register_user(
            username="User", email="user@example.com", password="correct-horse-9", backend=backend
        )
        assert (
            accounts.authenticate(email="user@example.com", password="correct-horse-9", backend=backend)
            is None
        )

    def test_sign_in_marks_the_profile_verified(self, db, backend, gotrue):
        email = self._register_and_confirm(backend, gotrue)
        result = accounts.authenticate(email=email, password="correct-horse-9", backend=backend)
        assert result.email_verified


class TestVerification:
    def test_token_confirms_the_profile(self, db, backend):
        accounts.register_user(
            username="User", email="user@example.com", password="correct-horse-9", backend=backend
        )
        confirmed = accounts.confirm_email("valid-user@example.com", backend=backend)
        assert confirmed.email_verified

    def test_expired_token_is_refused(self, db, backend):
        with pytest.raises(AuthError):
            accounts.confirm_email("expired", backend=backend)


class TestPasswordReset:
    def test_reset_is_requested_through_supabase(self, db, backend, gotrue, user):
        accounts.start_password_reset(user.email, backend=backend)
        assert gotrue.reset_emails == [user.email]

    def test_unknown_address_is_silent(self, db, backend, gotrue):
        result, token = accounts.start_password_reset("nobody@example.com", backend=backend)
        assert result is None
        assert token is None

    def test_reset_sets_the_new_password_and_clears_the_local_hash(self, db, backend, gotrue):
        accounts.register_user(
            username="User", email="user@example.com", password="correct-horse-9", backend=backend
        )
        # Simulate a legacy row that still carries a local hash.
        legacy = User.query.filter_by(email="user@example.com").first()
        legacy.set_password("old-local-password-1")
        db.session.commit()

        accounts.complete_password_reset("valid-user@example.com", "brand-new-password-7", backend=backend)

        refreshed = User.query.filter_by(email="user@example.com").first()
        assert refreshed.password_hash is None  # the leaked-hash liability is gone
        assert refreshed.email_verified
        assert gotrue.users["user@example.com"]["password"] == "brand-new-password-7"

    def test_weak_new_password_is_refused(self, db, backend):
        with pytest.raises(ValidationError):
            accounts.complete_password_reset("valid-x@example.com", "short", backend=backend)


class TestChangePassword:
    def test_requires_the_current_password(self, db, backend, gotrue):
        accounts.register_user(
            username="User", email="user@example.com", password="correct-horse-9", backend=backend
        )
        gotrue.users["user@example.com"]["confirmed"] = True
        user = User.query.filter_by(email="user@example.com").first()

        with pytest.raises(ValidationError):
            accounts.change_password(user, "brand-new-password-7", current_password=None, backend=backend)

    def test_wrong_current_password_is_refused(self, db, backend, gotrue):
        accounts.register_user(
            username="User", email="user@example.com", password="correct-horse-9", backend=backend
        )
        gotrue.users["user@example.com"]["confirmed"] = True
        user = User.query.filter_by(email="user@example.com").first()

        with pytest.raises(AuthError):
            accounts.change_password(
                user, "brand-new-password-7", current_password="not-the-password", backend=backend
            )

    def test_correct_current_password_changes_it(self, db, backend, gotrue):
        accounts.register_user(
            username="User", email="user@example.com", password="correct-horse-9", backend=backend
        )
        gotrue.users["user@example.com"]["confirmed"] = True
        user = User.query.filter_by(email="user@example.com").first()

        accounts.change_password(
            user, "brand-new-password-7", current_password="correct-horse-9", backend=backend
        )
        assert gotrue.users["user@example.com"]["password"] == "brand-new-password-7"


class TestProfileLinkage:
    def test_the_integer_primary_key_is_preserved(self, db, backend):
        """server_record.user_id and customer_order.user_id depend on it."""
        user, _ = accounts.register_user(
            username="User", email="user@example.com", password="correct-horse-9", backend=backend
        )
        assert isinstance(user.id, int)
        assert user.supabase_user_id != user.id

    def test_an_identity_maps_to_exactly_one_profile(self, db, backend, gotrue):
        accounts.register_user(
            username="User", email="user@example.com", password="correct-horse-9", backend=backend
        )
        gotrue.users["user@example.com"]["confirmed"] = True

        for _ in range(3):
            accounts.authenticate(email="user@example.com", password="correct-horse-9", backend=backend)

        assert User.query.filter_by(email="user@example.com").count() == 1


class TestErrorTranslation:
    """Provider errors must not leak, but recognised ones must be actionable."""

    def test_recognised_codes_become_user_safe_messages(self):
        from fluxweb.integrations.supabase_auth import SupabaseAuthClient

        client = SupabaseAuthClient("https://x.supabase.co", "anon")

        class Response:
            status_code = 400

            @staticmethod
            def json():
                return {"error_code": "email_not_confirmed", "msg": "Email not confirmed"}

            text = ""

        with pytest.raises(AuthError, match="confirm your email"):
            client._raise_for_error(Response(), "POST", "/token")

    def test_unrecognised_errors_stay_opaque(self):
        from fluxweb.integrations.supabase_auth import SupabaseAuthClient

        client = SupabaseAuthClient("https://x.supabase.co", "anon")

        class Response:
            status_code = 500

            @staticmethod
            def json():
                return {"msg": "internal database connection string exposed here"}

            text = ""

        with pytest.raises(IntegrationError) as caught:
            client._raise_for_error(Response(), "POST", "/token")
        # The detail is kept for logs, but the user-facing message is generic.
        assert "exposed here" not in caught.value.user_message


class TestConfiguration:
    def test_production_refuses_the_local_backend(self, monkeypatch):
        import secrets

        from cryptography.fernet import Fernet

        from fluxweb.config import Config, ConfigError

        for key, value in {
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
        }.items():
            monkeypatch.setenv(key, value)
        for key in ("SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_SERVICE_ROLE_KEY"):
            monkeypatch.delenv(key, raising=False)

        with pytest.raises(ConfigError, match="AUTH_BACKEND must be 'supabase'"):
            Config.from_env()

    def test_anon_and_service_role_keys_must_differ(self, monkeypatch):
        from fluxweb.config import Config, ConfigError

        monkeypatch.setenv("FLASK_ENV", "development")
        monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
        monkeypatch.setenv("SUPABASE_ANON_KEY", "the-same-key-value")
        monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "the-same-key-value")

        with pytest.raises(ConfigError, match="identical"):
            Config.from_env()

    def test_supabase_is_selected_automatically_when_configured(self, monkeypatch):
        from fluxweb.config import Config

        monkeypatch.setenv("FLASK_ENV", "development")
        monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
        monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")
        monkeypatch.delenv("AUTH_BACKEND", raising=False)

        assert Config.from_env().uses_supabase_auth
