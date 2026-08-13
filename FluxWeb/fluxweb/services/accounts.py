"""Account lifecycle: registration, verification, password reset, panel creds.

Credential storage lives behind :mod:`fluxweb.services.auth_backends` — in
production that is Supabase Auth. This module owns the rules that stay ours
regardless of who holds the password: input validation, profile creation,
enumeration resistance, and panel credential rotation.
"""

from __future__ import annotations

import logging
import re
import secrets

from fluxweb.errors import DomainError, ValidationError
from fluxweb.extensions import db
from fluxweb.models import User
from fluxweb.services.auth_backends import AuthBackend, get_auth_backend

log = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
MIN_PASSWORD_LENGTH = 10


def normalise_email(raw: str | None) -> str:
    email = (raw or "").strip().lower()
    if not EMAIL_RE.match(email) or len(email) > 100:
        raise ValidationError("Please enter a valid email address.")
    return email


def validate_password(password: str | None) -> str:
    """One password policy, applied at registration, reset, and change.

    Supabase enforces its own minimum too; this runs first so the user gets a
    clear message in our own wording before a round-trip.
    """
    password = password or ""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValidationError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if len(password) > 200:
        raise ValidationError("Password must be shorter than 200 characters.")
    if password.isdigit() or password.isalpha():
        raise ValidationError("Use a mix of letters, numbers, or symbols.")
    return password


def validate_username(raw: str | None) -> str:
    username = (raw or "").strip()
    if not 3 <= len(username) <= 50:
        raise ValidationError("Username must be between 3 and 50 characters.")
    if not re.match(r"^[A-Za-z0-9 _.-]+$", username):
        raise ValidationError(
            "Username may only contain letters, numbers, spaces, dots, hyphens and underscores."
        )
    return username


# --- registration -------------------------------------------------------
def register_user(
    *,
    username: str | None,
    email: str | None,
    password: str | None,
    redirect_to: str | None = None,
    backend: AuthBackend | None = None,
) -> tuple[User | None, str | None]:
    """Create an account.

    Returns ``(user, local_token)``. ``local_token`` is None when the backend
    sent its own email (Supabase does).

    A duplicate address returns ``(None, None)`` and the caller shows the same
    "check your email" screen either way, so registration cannot be used to
    enumerate customers (audit L-38).
    """
    backend = backend or get_auth_backend()

    username = validate_username(username)
    email = normalise_email(email)
    password = validate_password(password)

    if User.query.filter_by(email=email).first() is not None:
        log.info("Registration attempted for an address that already has a profile")
        return None, None

    try:
        token = backend.register(email=email, password=password, redirect_to=redirect_to)
    except DomainError as exc:
        # "already registered" from the provider is the same disclosure risk.
        if "already registered" in str(exc).lower():
            return None, None
        raise

    user = User.query.filter_by(email=email).first()
    # Prefer the name the customer chose, when it is still free.
    if (
        user is not None
        and username
        and user.username != username
        and User.query.filter_by(username=username).first() is None
    ):
        user.username = username
        db.session.commit()

    if user is not None:
        log.info("Registered user %s via %s", user.id, backend.name)
    return user, token


# --- sign-in ------------------------------------------------------------
def authenticate(
    *, email: str | None, password: str | None, backend: AuthBackend | None = None
) -> User | None:
    """Verify credentials and return the local profile, or None."""
    backend = backend or get_auth_backend()
    try:
        normalised = normalise_email(email)
    except ValidationError:
        return None
    if not password:
        return None
    return backend.authenticate(email=normalised, password=password)


# --- verification -------------------------------------------------------
def confirm_email(token: str, *, backend: AuthBackend | None = None) -> User:
    backend = backend or get_auth_backend()
    user = backend.confirm_email(token=token)
    log.info("Verified email for user %s", user.id)
    return user


def resend_confirmation(
    user: User, *, redirect_to: str | None = None, backend: AuthBackend | None = None
) -> str | None:
    backend = backend or get_auth_backend()
    return backend.resend_confirmation(user=user, redirect_to=redirect_to)


# --- password reset -----------------------------------------------------
def start_password_reset(
    email: str, *, redirect_to: str | None = None, backend: AuthBackend | None = None
) -> tuple[User | None, str | None]:
    """Begin a reset. Silent when the address is unknown."""
    backend = backend or get_auth_backend()
    try:
        normalised = normalise_email(email)
    except ValidationError:
        return None, None

    user = User.query.filter_by(email=normalised).first()
    try:
        token = backend.request_password_reset(email=normalised, redirect_to=redirect_to)
    except DomainError:
        # Rate limited or unknown at the provider: say nothing either way.
        return user, None
    return user, token


def complete_password_reset(token: str, new_password: str, *, backend: AuthBackend | None = None) -> User:
    backend = backend or get_auth_backend()
    password = validate_password(new_password)
    user = backend.reset_password(token=token, new_password=password)
    log.info("Password reset completed for user %s", user.id)
    return user


def change_password(
    user: User,
    new_password: str,
    *,
    current_password: str | None = None,
    backend: AuthBackend | None = None,
) -> None:
    """Change the account password.

    Deliberately does not touch the game panel credential. The old
    implementation stored the site password in a recoverable form and pushed
    it to the panel, so one key leak exposed every customer's real password
    (audit H-15). Panel credentials are separate and rotate on their own.
    """
    backend = backend or get_auth_backend()
    password = validate_password(new_password)
    backend.change_password(user=user, new_password=password, current_password=current_password)


# --- game panel credentials --------------------------------------------
def rotate_panel_password(user: User, client) -> str:
    """Generate a fresh random panel password and push it to the panel."""
    if not user.pelican_user_id:
        raise DomainError("You do not have a game panel account yet.")
    new_password = secrets.token_urlsafe(18)
    client.set_user_password(
        user.pelican_user_id,
        email=user.email,
        username=_panel_username(user),
        first_name=user.username or "Client",
        password=new_password,
    )
    user.set_pelican_password(new_password)
    db.session.commit()
    return new_password


def _panel_username(user: User) -> str:
    base = "".join(ch for ch in (user.username or "").lower() if ch.isalnum() or ch in "_-") or "client"
    return f"{base[:20]}_{user.id}"
