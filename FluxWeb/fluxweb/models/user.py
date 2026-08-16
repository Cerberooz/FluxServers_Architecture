"""User accounts, email verification, and password reset tokens."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from werkzeug.security import check_password_hash, generate_password_hash

from fluxweb.extensions import db
from fluxweb.security import crypto


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class User(db.Model):
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)

    # Credentials live in Supabase Auth in production, so this is NULL for
    # every Supabase-backed account. It remains for the local development
    # backend and for accounts that have not yet been migrated.
    password_hash = db.Column(db.String(255), nullable=True)

    #: GoTrue user id (UUID) when the account is backed by Supabase Auth.
    #: The integer `id` above stays the application's own key, because
    #: server_record and customer_order reference it.
    supabase_user_id = db.Column(db.String(36), unique=True, nullable=True, index=True)

    #: How this account signs in: "email", "google", "discord", ...
    #: An OAuth account has no password anywhere, so the change-password form
    #: must not be offered to it.
    auth_provider = db.Column(db.String(30), nullable=True)

    # Durable Web-to-Panel identity. Email is historical/discovery metadata,
    # never the primary link after the accounts have been matched.
    pelican_user_id = db.Column(db.Integer, nullable=True, index=True)
    pelican_user_uuid = db.Column(db.String(36), nullable=True, unique=True, index=True)
    pelican_user_email = db.Column(db.String(100), nullable=True)
    panel_link_source = db.Column(db.String(32), nullable=True)
    panel_linked_at = db.Column(db.DateTime, nullable=True)
    pelican_password = db.Column(db.String(500), nullable=True)  # Fernet ciphertext

    email_verified_at = db.Column(db.DateTime, nullable=True)
    is_admin = db.Column(db.Boolean, nullable=False, default=False)

    created_at = db.Column(db.DateTime, default=utcnow, index=True)
    last_login_at = db.Column(db.DateTime, nullable=True)
    failed_login_count = db.Column(db.Integer, nullable=False, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)

    servers = db.relationship("ServerRecord", backref="owner", lazy=True)
    orders = db.relationship("Order", backref="user", lazy=True)

    # --- password ------------------------------------------------------
    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        # A Supabase-backed account has no local hash; there is nothing here
        # to check against and the answer must be "no", never a crash.
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    @property
    def uses_supabase_auth(self) -> bool:
        return self.supabase_user_id is not None

    @property
    def is_oauth_account(self) -> bool:
        """True when sign-in is delegated to an external provider."""
        return bool(self.auth_provider) and self.auth_provider != "email"

    @property
    def can_change_password(self) -> bool:
        """OAuth accounts have no password here or at Supabase to change."""
        return not self.is_oauth_account

    # --- verification --------------------------------------------------
    @property
    def email_verified(self) -> bool:
        return self.email_verified_at is not None

    def mark_email_verified(self) -> None:
        self.email_verified_at = utcnow()

    # --- lockout (audit H-10) ------------------------------------------
    @property
    def is_locked(self) -> bool:
        return self.locked_until is not None and self.locked_until > utcnow()

    def register_failed_login(self, *, threshold: int = 8, lock_minutes: int = 15) -> None:
        self.failed_login_count = (self.failed_login_count or 0) + 1
        if self.failed_login_count >= threshold:
            self.locked_until = utcnow() + timedelta(minutes=lock_minutes)
            self.failed_login_count = 0

    def register_successful_login(self) -> None:
        self.failed_login_count = 0
        self.locked_until = None
        self.last_login_at = utcnow()

    # --- panel credentials ---------------------------------------------
    @property
    def pelican_password_decrypted(self) -> str | None:
        """The panel password, or None when it cannot be decrypted.

        This is an independently generated credential, never a copy of the
        site password (audit H-15).
        """
        return crypto.decrypt(self.pelican_password)

    def set_pelican_password(self, plaintext: str) -> None:
        self.pelican_password = crypto.encrypt(plaintext)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User {self.id} {self.email}>"


class VerificationToken(db.Model):
    """Single-use, hashed, expiring token for email verification / reset."""

    __tablename__ = "verification_token"
    __table_args__ = (db.Index("ix_verification_token_user_purpose", "user_id", "purpose"),)

    PURPOSE_EMAIL = "email_verification"
    PURPOSE_RESET = "password_reset"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id", ondelete="CASCADE"), nullable=False)
    token_hash = db.Column(db.String(64), nullable=False, unique=True, index=True)
    purpose = db.Column(db.String(32), nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow)

    user = db.relationship("User", backref=db.backref("tokens", lazy=True, cascade="all, delete-orphan"))

    @property
    def is_usable(self) -> bool:
        return self.used_at is None and self.expires_at > utcnow()

    def consume(self) -> None:
        self.used_at = utcnow()
