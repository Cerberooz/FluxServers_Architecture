"""External sign-in (OAuth via PKCE) and the confirmation screen."""

from __future__ import annotations

from urllib.parse import parse_qsl, urlparse

import pytest

from fluxweb.config import Config, ConfigError, PaymentConfig
from fluxweb.errors import ValidationError
from fluxweb.integrations.supabase_auth import AuthSession, SupabaseAuthClient, SupabaseUser
from fluxweb.models import User
from fluxweb.services import accounts
from fluxweb.services.auth_backends import SupabaseAuthBackend
from tests.test_supabase_auth import FakeGoTrue


class OAuthFakeGoTrue(FakeGoTrue):
    """Adds the PKCE surface to the fake."""

    def __init__(self):
        super().__init__()
        self.exchanged: list[tuple[str, str]] = []

    def generate_pkce_pair(self):
        return "verifier-abc", "challenge-xyz"

    def authorize_url(self, *, provider, redirect_to, code_challenge):
        return (
            f"https://x.supabase.co/auth/v1/authorize?provider={provider}"
            f"&redirect_to={redirect_to}&code_challenge={code_challenge}"
            "&code_challenge_method=s256"
        )

    def exchange_code(self, *, auth_code, code_verifier):
        self.exchanged.append((auth_code, code_verifier))
        if auth_code != "good-code":
            from fluxweb.integrations.supabase_auth import AuthError

            raise AuthError("That link has expired. Please request a new one.")
        uid = self._make("oauth@example.com", password=None, confirmed=True)
        record = self.users["oauth@example.com"]
        return AuthSession(
            user=SupabaseUser(
                id=uid,
                email="oauth@example.com",
                email_confirmed=True,
                raw=record,
                provider="google",
                full_name="OAuth Person",
            ),
            access_token=f"at-{uid}",
            refresh_token="rt",
        )


@pytest.fixture
def oauth_backend():
    return SupabaseAuthBackend(OAuthFakeGoTrue())


class TestPkceGeneration:
    """The verifier/challenge pair must satisfy RFC 7636."""

    def test_challenge_is_the_s256_of_the_verifier(self):
        import base64
        import hashlib

        verifier, challenge = SupabaseAuthClient.generate_pkce_pair()
        expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
        assert challenge == expected
        assert "=" not in challenge  # must be unpadded base64url

    def test_verifier_length_is_within_spec(self):
        verifier, _ = SupabaseAuthClient.generate_pkce_pair()
        assert 43 <= len(verifier) <= 128

    def test_each_start_is_unique(self):
        first, _ = SupabaseAuthClient.generate_pkce_pair()
        second, _ = SupabaseAuthClient.generate_pkce_pair()
        assert first != second


class TestAuthorizeUrl:
    def test_carries_pkce_parameters(self):
        client = SupabaseAuthClient("https://x.supabase.co", "anon")
        _, challenge = client.generate_pkce_pair()
        url = client.authorize_url(
            provider="google", redirect_to="https://app.test/auth/callback", code_challenge=challenge
        )
        query = dict(parse_qsl(urlparse(url).query))
        assert query["provider"] == "google"
        assert query["code_challenge_method"] == "s256"
        assert query["code_challenge"] == challenge
        assert query["redirect_to"] == "https://app.test/auth/callback"


class TestOAuthCompletion:
    def test_creates_a_profile_and_marks_it_verified(self, db, oauth_backend):
        user = oauth_backend.oauth_complete(auth_code="good-code", code_verifier="verifier-abc")
        assert user.email == "oauth@example.com"
        assert user.auth_provider == "google"
        assert user.email_verified  # arriving via Google proves the address
        assert user.password_hash is None

    def test_repeated_sign_in_reuses_one_profile(self, db, oauth_backend):
        first = oauth_backend.oauth_complete(auth_code="good-code", code_verifier="v")
        second = oauth_backend.oauth_complete(auth_code="good-code", code_verifier="v")
        assert first.id == second.id
        assert User.query.filter_by(email="oauth@example.com").count() == 1

    def test_bad_code_is_refused(self, db, oauth_backend):
        from fluxweb.integrations.supabase_auth import AuthError

        with pytest.raises(AuthError):
            oauth_backend.oauth_complete(auth_code="forged", code_verifier="v")

    def test_oauth_account_cannot_change_password(self, db, oauth_backend):
        user = oauth_backend.oauth_complete(auth_code="good-code", code_verifier="v")
        with pytest.raises(ValidationError, match="Google"):
            accounts.change_password(
                user, "brand-new-password-7", current_password="anything", backend=oauth_backend
            )

    def test_model_flags_reflect_the_provider(self, db, oauth_backend):
        user = oauth_backend.oauth_complete(auth_code="good-code", code_verifier="v")
        assert user.is_oauth_account
        assert not user.can_change_password


class TestOAuthRoutes:
    @pytest.fixture
    def oauth_app(self, config):
        """An app with providers configured and the Supabase backend on."""
        from fluxweb import create_app

        config.auth_backend = "supabase"
        config.supabase_url = "https://x.supabase.co"
        config.supabase_anon_key = "anon"
        config.oauth_providers = ("google", "discord")

        app = create_app(config)
        app.config["WTF_CSRF_ENABLED"] = False
        from fluxweb.extensions import db as _db

        with app.app_context():
            _db.create_all()
            yield app
            _db.session.remove()
            _db.drop_all()

    def test_buttons_render_for_configured_providers(self, oauth_app):
        body = oauth_app.test_client().get("/login").data.decode()
        assert "/login/google" in body
        assert "/login/discord" in body

    def test_no_buttons_when_none_configured(self, client):
        # The default fixture app has no providers configured.
        body = client.get("/login").data.decode()
        assert "/login/google" not in body

    def test_unlisted_provider_is_rejected(self, oauth_app):
        response = oauth_app.test_client().get("/login/facebook")
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]

    def test_callback_without_a_verifier_is_rejected(self, oauth_app):
        """No stored verifier means the callback did not start here."""
        client = oauth_app.test_client()
        response = client.get("/auth/callback?code=anything")
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]

    def test_callback_reports_provider_errors(self, oauth_app):
        client = oauth_app.test_client()
        response = client.get("/auth/callback?error=access_denied")
        assert response.status_code == 302


class TestConfirmationScreen:
    def test_registration_lands_on_the_confirmation_screen(self, client, db):
        response = client.post(
            "/register",
            data={"username": "Fresh", "email": "fresh@example.com", "password": "correct-horse-9"},
        )
        assert response.status_code == 302
        assert "/check-email" in response.headers["Location"]

    def test_screen_shows_the_address(self, client, db):
        client.post(
            "/register",
            data={"username": "Fresh", "email": "fresh@example.com", "password": "correct-horse-9"},
        )
        body = client.get("/check-email").data.decode()
        assert "fresh@example.com" in body
        assert "Check your email" in body

    def test_a_duplicate_address_looks_identical(self, client, db, user):
        """L-38: the screen must not reveal that the account already existed."""
        response = client.post(
            "/register",
            data={"username": "Impostor", "email": user.email, "password": "correct-horse-9"},
        )
        assert response.status_code == 302
        assert "/check-email" in response.headers["Location"]
        body = client.get("/check-email").data.decode()
        assert user.email in body  # same screen, same address, no hint either way

    def test_direct_visit_without_registering_redirects(self, client):
        response = client.get("/check-email")
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]

    def test_resend_targets_only_the_pending_address(self, client, db):
        """The address comes from the session, never the form, so this cannot
        be pointed at arbitrary mailboxes."""
        client.post(
            "/register",
            data={"username": "Fresh", "email": "fresh@example.com", "password": "correct-horse-9"},
        )
        response = client.post("/check-email/resend", data={"email": "victim@example.com"})
        assert response.status_code == 302
        # Nothing was created for the address supplied in the form.
        assert User.query.filter_by(email="victim@example.com").first() is None

    def test_resend_without_a_pending_address_does_nothing(self, client):
        response = client.post("/check-email/resend")
        assert response.status_code == 302
        assert "/login" in response.headers["Location"]


class TestProviderConfig:
    def test_unsupported_provider_is_rejected_at_boot(self, monkeypatch):
        monkeypatch.setenv("FLASK_ENV", "development")
        monkeypatch.setenv("SUPABASE_OAUTH_PROVIDERS", "google,myspace")
        with pytest.raises(ConfigError, match="unsupported provider"):
            Config.from_env()

    def test_providers_are_parsed_and_normalised(self, monkeypatch):
        monkeypatch.setenv("FLASK_ENV", "development")
        monkeypatch.setenv("SUPABASE_OAUTH_PROVIDERS", " Google , DISCORD ")
        assert Config.from_env().oauth_providers == ("google", "discord")

    def test_empty_by_default(self, monkeypatch):
        monkeypatch.setenv("FLASK_ENV", "development")
        monkeypatch.delenv("SUPABASE_OAUTH_PROVIDERS", raising=False)
        assert Config.from_env().oauth_providers == ()

    def test_every_supported_provider_has_a_button_label(self):
        from fluxweb.config import SUPPORTED_OAUTH_PROVIDERS
        from fluxweb.web.auth import PROVIDER_LABELS

        assert set(PROVIDER_LABELS) == SUPPORTED_OAUTH_PROVIDERS


def test_payment_config_unaffected():
    """Guard against the auth work disturbing payment validation."""
    assert PaymentConfig().validate(production=False) == []
