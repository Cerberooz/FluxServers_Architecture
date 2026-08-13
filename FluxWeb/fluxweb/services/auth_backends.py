"""Authentication backends.

The application has one set of account *rules* (a local profile row, panel
linkage, admin flags, order history) and two possible sources of truth for
*credentials*:

* :class:`SupabaseAuthBackend` — production. Supabase/GoTrue stores the
  password, sends confirmation and reset emails, and enforces its own rate
  limits and breach-password checks.
* :class:`LocalAuthBackend` — development and tests only. Werkzeug hashes in
  our own table, as before. Production configuration refuses to select it.

Only credential handling differs. Everything downstream — profile creation,
`is_admin`, panel provisioning — runs through the same code either way, so
there is no second business-logic path to keep in sync.
"""

from __future__ import annotations

import logging
import secrets
from datetime import timedelta

from fluxweb.errors import DomainError, ValidationError
from fluxweb.extensions import db
from fluxweb.integrations.supabase_auth import AuthError, SupabaseAuthClient
from fluxweb.models import User, VerificationToken
from fluxweb.models.user import utcnow

log = logging.getLogger(__name__)

VERIFICATION_TTL = timedelta(hours=24)
RESET_TTL = timedelta(hours=1)


class AuthBackend:
    """Credential operations. Implementations must not touch business rules."""

    name = "base"

    #: True when the backend sends its own emails, so the application should
    #: not also send a verification message.
    sends_own_email = False

    def register(self, *, email: str, password: str, redirect_to: str | None) -> str | None:
        """Create the credential record. Returns a local token when the
        application is responsible for the verification email, else None."""
        raise NotImplementedError

    def authenticate(self, *, email: str, password: str) -> User | None:
        """Return the local profile for valid credentials, or None."""
        raise NotImplementedError

    def request_password_reset(self, *, email: str, redirect_to: str | None) -> str | None:
        raise NotImplementedError

    def reset_password(self, *, token: str, new_password: str) -> User:
        raise NotImplementedError

    def change_password(self, *, user: User, new_password: str, current_password: str | None) -> None:
        raise NotImplementedError

    def confirm_email(self, *, token: str) -> User:
        raise NotImplementedError

    def resend_confirmation(self, *, user: User, redirect_to: str | None) -> str | None:
        raise NotImplementedError

    def logout(self) -> None:
        """Best-effort revocation at the provider. Optional."""


# ---------------------------------------------------------------------------
# Shared profile handling
# ---------------------------------------------------------------------------
def _unique_username(preferred: str) -> str:
    candidate = preferred.strip()[:50] or "client"
    if User.query.filter_by(username=candidate).first() is None:
        return candidate
    return f"{candidate[:44]}-{secrets.token_hex(2)}"


def get_or_create_profile(
    *,
    email: str,
    username: str | None = None,
    supabase_user_id: str | None = None,
    provider: str | None = None,
) -> User:
    """Find or create the local profile row for an authenticated identity.

    The profile carries everything the rest of the application depends on:
    the integer id used by `server_record.user_id` and `customer_order.user_id`,
    the admin flag, and the panel linkage. Supabase owns only the credential.
    """
    user: User | None = None
    if supabase_user_id:
        user = User.query.filter_by(supabase_user_id=supabase_user_id).first()
    if user is None:
        user = User.query.filter_by(email=email).first()

    if user is None:
        user = User(username=_unique_username(username or email.split("@")[0]), email=email)
        db.session.add(user)

    # Bind the identity on first sight, and keep the address in step if it was
    # changed on the provider side.
    if supabase_user_id and user.supabase_user_id != supabase_user_id:
        user.supabase_user_id = supabase_user_id
    if user.email != email:
        user.email = email
    if provider and user.auth_provider != provider:
        user.auth_provider = provider

    db.session.commit()
    return user


# ---------------------------------------------------------------------------
# Supabase
# ---------------------------------------------------------------------------
class SupabaseAuthBackend(AuthBackend):
    name = "supabase"
    sends_own_email = True

    def __init__(self, client: SupabaseAuthClient) -> None:
        self.client = client

    # --- OAuth ----------------------------------------------------------
    def oauth_authorize_url(self, *, provider: str, redirect_to: str) -> tuple[str, str]:
        """Return ``(url, code_verifier)`` to begin an OAuth sign-in.

        The caller must keep ``code_verifier`` in the user's session until the
        callback: it is the proof that the browser finishing the flow is the
        same one that started it.
        """
        verifier, challenge = self.client.generate_pkce_pair()
        url = self.client.authorize_url(provider=provider, redirect_to=redirect_to, code_challenge=challenge)
        return url, verifier

    def oauth_complete(self, *, auth_code: str, code_verifier: str) -> User:
        """Redeem an OAuth callback and return the local profile."""
        session = self.client.exchange_code(auth_code=auth_code, code_verifier=code_verifier)
        if not session.user.id or not session.user.email:
            raise DomainError("That sign-in did not complete. Please try again.")

        user = get_or_create_profile(
            email=session.user.email,
            username=session.user.full_name or None,
            supabase_user_id=session.user.id,
            provider=session.user.provider,
        )
        # Reaching us through Google/Discord proves the address; there is no
        # separate confirmation step for these accounts.
        if not user.email_verified:
            user.mark_email_verified()
            db.session.commit()
        return user

    def register(self, *, email: str, password: str, redirect_to: str | None) -> str | None:
        supabase_user = self.client.sign_up(email=email, password=password, redirect_to=redirect_to)

        # Create the profile immediately so an abandoned confirmation does not
        # leave an identity with no local record. It stays unverified until
        # the email is confirmed.
        user = get_or_create_profile(email=email, supabase_user_id=supabase_user.id, provider="email")
        if supabase_user.email_confirmed:
            user.mark_email_verified()
            db.session.commit()
        return None  # Supabase sent the email.

    def authenticate(self, *, email: str, password: str) -> User | None:
        try:
            session = self.client.sign_in(email=email, password=password)
        except AuthError:
            # Distinguishing "wrong password" from "no such user" would be an
            # enumeration oracle; the caller shows one message for both.
            return None

        if not session.user.id:
            return None

        user = get_or_create_profile(email=session.user.email or email, supabase_user_id=session.user.id)
        if session.user.email_confirmed and not user.email_verified:
            user.mark_email_verified()
            db.session.commit()
        return user

    def request_password_reset(self, *, email: str, redirect_to: str | None) -> str | None:
        self.client.send_password_reset(email=email, redirect_to=redirect_to)
        return None

    def reset_password(self, *, token: str, new_password: str) -> User:
        session = self.client.verify_token_hash(token_hash=token, verification_type="recovery")
        if not session.access_token:
            raise DomainError("That link has expired or has already been used.")

        self.client.update_password(access_token=session.access_token, password=new_password)

        user = get_or_create_profile(email=session.user.email, supabase_user_id=session.user.id)
        # Completing a recovery proves control of the mailbox.
        if not user.email_verified:
            user.mark_email_verified()
        # The old local hash, if any, is now dead weight and a liability.
        user.password_hash = None
        db.session.commit()
        return user

    def change_password(self, *, user: User, new_password: str, current_password: str | None) -> None:
        if user.is_oauth_account:
            raise ValidationError(
                f"This account signs in with {user.auth_provider.title()}, so there is no "
                "password to change. Manage it with your provider."
            )
        if not current_password:
            raise ValidationError("Enter your current password.")

        # Re-authenticate rather than trusting the session: a stolen cookie
        # must not be enough to take over the credential.
        session = self.client.sign_in(email=user.email, password=current_password)
        self.client.update_password(access_token=session.access_token, password=new_password)
        user.password_hash = None
        db.session.commit()

    def confirm_email(self, *, token: str) -> User:
        session = self.client.verify_token_hash(token_hash=token, verification_type="email")
        user = get_or_create_profile(email=session.user.email, supabase_user_id=session.user.id)
        user.mark_email_verified()
        db.session.commit()
        return user

    def resend_confirmation(self, *, user: User, redirect_to: str | None) -> str | None:
        self.client.resend_confirmation(email=user.email, redirect_to=redirect_to)
        return None


# ---------------------------------------------------------------------------
# Local (development and tests only)
# ---------------------------------------------------------------------------
class LocalAuthBackend(AuthBackend):
    name = "local"
    sends_own_email = False

    def register(self, *, email: str, password: str, redirect_to: str | None) -> str | None:
        user = User(username=_unique_username(email.split("@")[0]), email=email)
        user.set_password(password)
        db.session.add(user)
        db.session.commit()
        return self._issue(user, VerificationToken.PURPOSE_EMAIL, VERIFICATION_TTL)

    def authenticate(self, *, email: str, password: str) -> User | None:
        user = User.query.filter_by(email=email).first()
        if user is None or not user.password_hash:
            return None
        if user.is_locked:
            raise DomainError("Too many failed attempts. Try again in a few minutes.")
        if not user.check_password(password):
            user.register_failed_login()
            db.session.commit()
            return None
        user.register_successful_login()
        db.session.commit()
        return user

    def request_password_reset(self, *, email: str, redirect_to: str | None) -> str | None:
        user = User.query.filter_by(email=email).first()
        if user is None:
            return None
        return self._issue(user, VerificationToken.PURPOSE_RESET, RESET_TTL)

    def reset_password(self, *, token: str, new_password: str) -> User:
        user = self._consume(token, VerificationToken.PURPOSE_RESET)
        user.set_password(new_password)
        user.failed_login_count = 0
        user.locked_until = None
        db.session.commit()
        return user

    def change_password(self, *, user: User, new_password: str, current_password: str | None) -> None:
        if current_password is not None and not user.check_password(current_password):
            raise ValidationError("Your current password is incorrect.")
        user.set_password(new_password)
        db.session.commit()

    def confirm_email(self, *, token: str) -> User:
        user = self._consume(token, VerificationToken.PURPOSE_EMAIL)
        user.mark_email_verified()
        db.session.commit()
        return user

    def resend_confirmation(self, *, user: User, redirect_to: str | None) -> str | None:
        return self._issue(user, VerificationToken.PURPOSE_EMAIL, VERIFICATION_TTL)

    # --- token helpers --------------------------------------------------
    @staticmethod
    def _issue(user: User, purpose: str, ttl: timedelta) -> str:
        from fluxweb.security import tokens

        VerificationToken.query.filter_by(user_id=user.id, purpose=purpose, used_at=None).update(
            {"used_at": utcnow()}
        )
        raw = tokens.generate_token()
        db.session.add(
            VerificationToken(
                user_id=user.id,
                token_hash=tokens.hash_token(raw),
                purpose=purpose,
                expires_at=utcnow() + ttl,
            )
        )
        db.session.commit()
        return raw

    @staticmethod
    def _consume(raw_token: str, purpose: str) -> User:
        from fluxweb.security import tokens

        if not raw_token:
            raise DomainError("That link is not valid.")
        record = VerificationToken.query.filter_by(
            token_hash=tokens.hash_token(raw_token), purpose=purpose
        ).first()
        if record is None or not record.is_usable:
            raise DomainError("That link has expired or has already been used.")
        record.consume()
        db.session.commit()
        return record.user


def get_auth_backend() -> AuthBackend:
    """Return the configured backend for this request."""
    from flask import current_app, g

    if "auth_backend" not in g:
        config = current_app.extensions["flux_config"]
        if config.uses_supabase_auth:
            from fluxweb.integrations.supabase_auth import get_supabase_auth

            g.auth_backend = SupabaseAuthBackend(get_supabase_auth())
        else:
            g.auth_backend = LocalAuthBackend()
    return g.auth_backend
