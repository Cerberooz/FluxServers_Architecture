"""Application configuration.

Every setting is read here and nowhere else. The application refuses to start
when a security-critical value is missing, left at a known default, or
internally inconsistent (audit S-3, C-1, C-2).
"""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field

from fluxweb.money import gateway_fee_cents

# Values that must never reach production. Historical defaults from app.py are
# listed explicitly so an old .env cannot silently keep working.
BANNED_SECRETS = {
    "flux_dev_key_change_me_in_production",
    "flux-secret-123-asdjkhasjkhdjkashdkjashdkjashdkjahsdkjhasdkjhasdkjhasdkjhasd",
    "changeme",
    "secret",
    "password",
    "dev",
    "test",
}

# Machine-generated secrets (signing keys, tokens) must be long.
MIN_SECRET_LENGTH = 32
# Human-typed passwords have a different, lower bar; demanding 32 characters
# for a password people actually type is unreasonable.
MIN_PASSWORD_LENGTH = 12


class ConfigError(RuntimeError):
    """Raised at startup when configuration is unsafe or incomplete."""


def _env(name: str, default: str | None = None) -> str | None:
    value = os.getenv(name, default)
    if value is None:
        return None
    value = value.strip()
    return value or None


def _env_bool(name: str, default: bool = False) -> bool:
    raw = _env(name)
    if raw is None:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _is_placeholder(value: str) -> bool:
    """True when a value is a known default or an obvious placeholder."""
    lowered = value.lower()
    if lowered in BANNED_SECRETS:
        return True
    return any(
        banned in lowered
        for banned in ("change_me", "changeme", "flux-secret-123", "flux_dev_key", "your-", "xxxx")
    )


def _looks_weak(value: str) -> bool:
    """True when a machine-generated secret is too short or a placeholder."""
    return len(value) < MIN_SECRET_LENGTH or _is_placeholder(value)


def _password_looks_weak(value: str) -> bool:
    """True when a human-typed password is too short or a placeholder."""
    return len(value) < MIN_PASSWORD_LENGTH or _is_placeholder(value)


#: Supabase's transaction pooler. Great for serverless request handling,
#: unsuitable for migrations (a different backend per transaction).
SUPABASE_TRANSACTION_POOLER_PORT = 6543

LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "host.docker.internal"}

#: OAuth providers this application knows how to render a button for. Supabase
#: supports many more; add the label in fluxweb/web/auth.py to extend this.
SUPPORTED_OAUTH_PROVIDERS = frozenset({"google", "discord", "github", "gitlab", "azure", "apple", "twitch"})


def normalise_postgres_url(url: str) -> str:
    """Canonicalise a Postgres URL and force TLS for remote hosts.

    * ``postgres://`` -> ``postgresql://`` (SQLAlchemy 2 dropped the alias,
      and Supabase/Heroku still hand out the old form).
    * ``sslmode=require`` is added for any non-local host. psycopg2 defaults
      to ``prefer``, which silently falls back to plaintext — unacceptable for
      a connection carrying customer records across the internet.
    """
    from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    if not url.startswith("postgresql"):
        return url

    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query))

    host = (parsed.hostname or "").lower()
    if host not in LOCAL_HOSTS and "sslmode" not in query:
        query["sslmode"] = "require"

    return urlunparse(parsed._replace(query=urlencode(query)))


def _url_port(url: str) -> int | None:
    from urllib.parse import urlparse

    try:
        return urlparse(url).port
    except ValueError:
        return None


def _url_host(url: str) -> str:
    from urllib.parse import urlparse

    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


@dataclass
class PaymentConfig:
    """Payment provider credentials, validated for live/test coherence."""

    stripe_publishable_key: str | None = None
    stripe_secret_key: str | None = None
    stripe_webhook_secret: str | None = None
    stripe_product_tax_code: str | None = None
    stripe_api_version: str | None = None
    paypal_client_id: str | None = None
    paypal_secret_key: str | None = None
    paypal_env: str = "sandbox"
    paypal_merchant_id: str | None = None
    stripe_fee_percent: float = 2.9
    stripe_fee_fixed_cents: int = 30
    paypal_fee_percent: float = 3.49
    paypal_fee_fixed_cents: int = 49

    def gateway_fee_cents(self, provider: str, net_cents: int) -> int:
        if provider == "stripe":
            return gateway_fee_cents(net_cents, self.stripe_fee_percent, self.stripe_fee_fixed_cents)
        if provider == "paypal":
            return gateway_fee_cents(net_cents, self.paypal_fee_percent, self.paypal_fee_fixed_cents)
        return 0

    @property
    def paypal_api_base(self) -> str:
        if self.paypal_env == "live":
            return "https://api-m.paypal.com"
        return "https://api-m.sandbox.paypal.com"

    @property
    def stripe_enabled(self) -> bool:
        return bool(self.stripe_secret_key and self.stripe_publishable_key)

    @property
    def paypal_enabled(self) -> bool:
        return bool(self.paypal_client_id and self.paypal_secret_key)

    @property
    def stripe_is_live(self) -> bool:
        return bool(self.stripe_secret_key and self.stripe_secret_key.startswith("sk_live"))

    @property
    def paypal_is_live(self) -> bool:
        return self.paypal_env == "live"

    def validate(self, *, production: bool) -> list[str]:
        """Return a list of fatal configuration problems."""
        problems: list[str] = []

        # Only fatal in production: local development should run without any
        # payment credentials at all. Checkout simply reports "unavailable".
        if production and not self.stripe_enabled and not self.paypal_enabled:
            problems.append(
                "No payment provider is fully configured. Set STRIPE_SECRET_KEY + "
                "STRIPE_PUBLISHABLE_KEY, and/or PAYPAL_CLIENT_ID + PAYPAL_SECRET_KEY."
            )

        # Half-configured providers are worse than disabled ones: the UI offers a
        # button that captures money and then fails verification (audit H-12).
        if self.stripe_secret_key and not self.stripe_publishable_key:
            problems.append("STRIPE_SECRET_KEY is set but STRIPE_PUBLISHABLE_KEY is missing.")
        if self.stripe_publishable_key and not self.stripe_secret_key:
            problems.append("STRIPE_PUBLISHABLE_KEY is set but STRIPE_SECRET_KEY is missing.")
        if self.paypal_client_id and not self.paypal_secret_key:
            problems.append(
                "PAYPAL_CLIENT_ID is set but PAYPAL_SECRET_KEY is missing. Every PayPal "
                "payment would be captured and then rejected."
            )
        if self.paypal_secret_key and not self.paypal_client_id:
            problems.append("PAYPAL_SECRET_KEY is set but PAYPAL_CLIENT_ID is missing.")

        if self.paypal_env not in {"live", "sandbox"}:
            problems.append(f"PAYPAL_ENV must be 'live' or 'sandbox', got {self.paypal_env!r}.")

        for name, percent, fixed in (
            ("STRIPE", self.stripe_fee_percent, self.stripe_fee_fixed_cents),
            ("PAYPAL", self.paypal_fee_percent, self.paypal_fee_fixed_cents),
        ):
            if percent < 0 or percent >= 100:
                problems.append(f"{name}_FEE_PERCENT must be between 0 and 100.")
            if fixed < 0:
                problems.append(f"{name}_FEE_FIXED_CENTS cannot be negative.")

        # Providers must agree about which world they are in.
        if self.stripe_enabled and self.paypal_enabled and self.stripe_is_live != self.paypal_is_live:
            problems.append(
                f"Payment providers disagree: Stripe is "
                f"{'live' if self.stripe_is_live else 'test'} but PayPal is "
                f"{'live' if self.paypal_is_live else 'sandbox'}. Align them before launch."
            )

        if production:
            if self.stripe_enabled and not self.stripe_webhook_secret:
                problems.append(
                    "STRIPE_WEBHOOK_SECRET is required in production. Without it, payments "
                    "cannot be confirmed server-side and orders will never be provisioned."
                )
            if self.paypal_enabled and not self.paypal_merchant_id:
                problems.append(
                    "PAYPAL_MERCHANT_ID is required in production so captures can be verified "
                    "as payable to you and not to a third party."
                )
            if self.stripe_enabled and not self.stripe_is_live:
                problems.append("Stripe test keys are in use but FLASK_ENV=production.")

        return problems


@dataclass
class Config:
    """Validated application configuration."""

    env: str = "production"
    secret_key: str = ""
    encryption_key: str = ""
    database_url: str = ""
    #: Session-mode / direct connection used only for schema changes.
    direct_database_url: str | None = None
    admin_email: str = ""
    admin_password: str | None = None
    base_url: str | None = None

    panel_url: str | None = None
    panel_api_key: str | None = None

    #: "supabase" (production) or "local" (development/test only).
    auth_backend: str = "local"
    supabase_url: str | None = None
    supabase_anon_key: str | None = None
    supabase_service_role_key: str | None = None
    #: External sign-in providers to offer, e.g. ("google", "discord").
    #: Must also be enabled in the Supabase dashboard.
    oauth_providers: tuple[str, ...] = ()

    smtp_host: str | None = None
    smtp_port: int = 587
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    mail_from: str = "no-reply@fluxservers.cloud"

    rate_limit_storage_uri: str = "memory://"
    cron_secret: str | None = None

    expiry_days: int = 30
    deletion_grace_days: int = 7
    max_content_length: int = 5 * 1024 * 1024
    session_lifetime_days: int = 7

    payments: PaymentConfig = field(default_factory=PaymentConfig)

    warnings: list[str] = field(default_factory=list)

    @property
    def is_production(self) -> bool:
        return self.env == "production"

    @property
    def is_development(self) -> bool:
        return self.env == "development"

    @property
    def is_testing(self) -> bool:
        return self.env == "testing"

    @property
    def panel_configured(self) -> bool:
        return bool(self.panel_url and self.panel_api_key)

    @property
    def uses_supabase_auth(self) -> bool:
        return self.auth_backend == "supabase"

    @property
    def is_postgres(self) -> bool:
        return self.database_url.startswith("postgresql")

    @property
    def is_supabase(self) -> bool:
        return "supabase" in _url_host(self.database_url)

    @property
    def uses_transaction_pooler(self) -> bool:
        return _url_port(self.database_url) == SUPABASE_TRANSACTION_POOLER_PORT

    @property
    def migration_url(self) -> str:
        """The URL schema changes should run against.

        Prefers ``DIRECT_URL``; falls back to the runtime URL when the runtime
        URL is already a session-mode or direct connection.
        """
        return self.direct_database_url or self.database_url

    def _validate_postgres(self, env: str) -> list[str]:
        """Postgres/Supabase-specific configuration rules."""
        problems: list[str] = []

        # Migrations on the transaction pooler fail in confusing, intermittent
        # ways. Require an explicit session/direct URL instead.
        if self.uses_transaction_pooler and not self.direct_database_url:
            message = (
                f"DATABASE_URL uses the transaction pooler (port "
                f"{SUPABASE_TRANSACTION_POOLER_PORT}), which cannot run migrations. "
                "Set DIRECT_URL to the session pooler (port 5432 on the same "
                "pooler host) or to the direct connection string."
            )
            if env == "production":
                problems.append(message)
            else:
                self.warnings.append(message)

        if self.direct_database_url and _url_port(self.direct_database_url) == (
            SUPABASE_TRANSACTION_POOLER_PORT
        ):
            problems.append(
                f"DIRECT_URL also points at the transaction pooler (port "
                f"{SUPABASE_TRANSACTION_POOLER_PORT}). It must be a session-mode "
                "or direct connection."
            )

        if self.is_supabase and not self.uses_transaction_pooler and env == "production":
            self.warnings.append(
                "DATABASE_URL is not the Supabase transaction pooler. On serverless, "
                f"port {SUPABASE_TRANSACTION_POOLER_PORT} handles bursty short-lived "
                "connections far better and is the recommended runtime endpoint."
            )

        return problems

    @classmethod
    def from_env(cls) -> Config:
        """Build config from environment, raising ConfigError on unsafe values."""
        env = (_env("FLASK_ENV") or _env("ENV") or "production").lower()
        if env not in {"production", "development", "testing"}:
            env = "production"

        cfg = cls(env=env)
        problems: list[str] = []

        # --- Session signing key (audit C-1) -------------------------------
        secret_key = _env("SECRET_KEY")
        if secret_key and not _looks_weak(secret_key):
            cfg.secret_key = secret_key
        elif env == "production":
            if not secret_key:
                problems.append(
                    'SECRET_KEY is not set. Generate one: python -c "import secrets; print(secrets.token_urlsafe(64))"'
                )
            else:
                problems.append(
                    f"SECRET_KEY is weak or a known default (must be >= {MIN_SECRET_LENGTH} "
                    "random characters). Anyone who guesses it can forge admin sessions. "
                    "Generate a new one and rotate it."
                )
        else:
            # Never fall back to a *fixed* default: a random per-boot key only
            # costs a logout on restart, whereas a shared constant is forgeable.
            cfg.secret_key = secrets.token_urlsafe(64)
            cfg.warnings.append(
                "SECRET_KEY missing or weak; generated a random ephemeral key for this run. "
                "Sessions will not survive a restart. Set SECRET_KEY in .env."
            )

        # --- Data encryption key, independent of the session key -----------
        # Kept separate so rotating the session key does not destroy stored
        # panel credentials, and vice versa (audit C-1).
        encryption_key = _env("ENCRYPTION_KEY")
        if encryption_key:
            cfg.encryption_key = encryption_key
        elif env == "production":
            problems.append(
                "ENCRYPTION_KEY is not set. Generate one: "
                'python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"'
            )
        else:
            from cryptography.fernet import Fernet

            cfg.encryption_key = Fernet.generate_key().decode()
            cfg.warnings.append(
                "ENCRYPTION_KEY missing; generated an ephemeral key. Previously encrypted "
                "panel passwords will not be readable. Set ENCRYPTION_KEY in .env."
            )

        # --- Database ------------------------------------------------------
        database_url = _env("DATABASE_URL")
        if database_url:
            cfg.database_url = normalise_postgres_url(database_url)
        elif env == "production":
            problems.append(
                "DATABASE_URL is not set. Refusing to fall back to SQLite in production: "
                "on serverless the file is ephemeral and all data would be lost."
            )
        else:
            cfg.database_url = "sqlite:///" + os.path.join(os.getcwd(), "instance", "fluxweb-dev.db")
            cfg.warnings.append("DATABASE_URL missing; using a local SQLite database for development.")

        # Schema changes need a session-mode or direct connection. Supabase's
        # transaction pooler (port 6543) hands out a different backend per
        # transaction, which is fine for short web requests but not for the
        # session-level work migrations do.
        direct_url = _env("DIRECT_URL") or _env("DATABASE_MIGRATION_URL")
        cfg.direct_database_url = normalise_postgres_url(direct_url) if direct_url else None

        if cfg.database_url.startswith("postgresql"):
            problems.extend(cfg._validate_postgres(env))

        # --- Admin ---------------------------------------------------------
        cfg.admin_email = (_env("ADMIN_EMAIL") or "admin@fluxservers.cloud").lower()
        admin_password = _env("ADMIN_PASSWORD")
        if admin_password and _password_looks_weak(admin_password) and env == "production":
            problems.append(
                "ADMIN_PASSWORD is weak or a known default. Use at least "
                f"{MIN_PASSWORD_LENGTH} characters, or drop it entirely and create the "
                "admin with: flask create-admin --email you@example.com --password '...'"
            )
        cfg.admin_password = admin_password
        cfg.base_url = _env("BASE_URL")
        if env == "production" and not cfg.base_url:
            problems.append(
                "BASE_URL is not set (e.g. https://fluxservers.cloud). It is required to build "
                "verification and payment return links."
            )

        # --- Panel (FluidPanel only) -----------------------------------------
        # FluidPanel is the only panel this application talks to. It is a
        # Pterodactyl fork, so the older PTERODACTYL_* and PELICAN_* names are
        # still read and an existing .env keeps working; FLUID_* is preferred
        # for new deployments.
        cfg.panel_url = (
            _env("FLUID_URL") or _env("PANEL_URL") or _env("PTERODACTYL_URL") or _env("PELICAN_URL") or ""
        ).rstrip("/") or None
        cfg.panel_api_key = (
            _env("FLUID_API_KEY")
            or _env("PANEL_API_KEY")
            or _env("PTERODACTYL_API_KEY")
            or _env("PELICAN_API_KEY")
        )
        if env == "production" and not cfg.panel_configured:
            problems.append(
                "FLUID_URL and FLUID_API_KEY are required to provision servers "
                "(PANEL_*, PTERODACTYL_* and PELICAN_* names are also accepted)."
            )

        # --- Supabase Auth -------------------------------------------------
        cfg.supabase_url = (_env("SUPABASE_URL") or "").rstrip("/") or None

        # Aliases accepted so a name copied from Supabase's own quickstart or
        # from the newer publishable/secret key naming still works:
        #   public  — SUPABASE_ANON_KEY | SUPABASE_KEY | SUPABASE_PUBLISHABLE_KEY
        #   private — SUPABASE_SERVICE_ROLE_KEY | SUPABASE_SECRET_KEY
        cfg.supabase_anon_key = (
            _env("SUPABASE_ANON_KEY") or _env("SUPABASE_PUBLISHABLE_KEY") or _env("SUPABASE_KEY")
        )
        cfg.supabase_service_role_key = _env("SUPABASE_SERVICE_ROLE_KEY") or _env("SUPABASE_SECRET_KEY")

        # A secret key in the public slot would be handed to browsers by any
        # future client-side code. Catch the mix-up at boot, not in an incident.
        if cfg.supabase_anon_key and cfg.supabase_anon_key.startswith(("sb_secret_", "sbp_")):
            problems.append(
                "The value in SUPABASE_ANON_KEY/SUPABASE_KEY looks like a SECRET key "
                "(sb_secret_...). Use the publishable key here; the secret key belongs "
                "in SUPABASE_SERVICE_ROLE_KEY."
            )

        # Providers to show buttons for. Listing one here does not enable it —
        # it must also be switched on in the Supabase dashboard — but showing a
        # button for a disabled provider produces a confusing error, so the
        # list is explicit rather than guessed.
        raw_providers = _env("SUPABASE_OAUTH_PROVIDERS") or ""
        cfg.oauth_providers = tuple(p.strip().lower() for p in raw_providers.split(",") if p.strip())
        unsupported = [p for p in cfg.oauth_providers if p not in SUPPORTED_OAUTH_PROVIDERS]
        if unsupported:
            problems.append(
                f"SUPABASE_OAUTH_PROVIDERS lists unsupported provider(s): "
                f"{', '.join(unsupported)}. Supported: {', '.join(sorted(SUPPORTED_OAUTH_PROVIDERS))}."
            )

        requested_backend = (_env("AUTH_BACKEND") or "").lower()
        supabase_ready = bool(cfg.supabase_url and cfg.supabase_anon_key)

        if requested_backend in {"supabase", "local"}:
            cfg.auth_backend = requested_backend
        else:
            # Prefer Supabase whenever it is configured; fall back to local
            # passwords so development works without a Supabase project.
            cfg.auth_backend = "supabase" if supabase_ready else "local"

        if cfg.auth_backend == "supabase" and not supabase_ready:
            problems.append(
                "AUTH_BACKEND=supabase but SUPABASE_URL and SUPABASE_ANON_KEY are not both set. "
                "Find them in Project Settings > API."
            )

        if env == "production":
            if cfg.auth_backend != "supabase":
                problems.append(
                    "AUTH_BACKEND must be 'supabase' in production. The local password "
                    "backend exists only for development and has no email delivery, "
                    "no breach-password checks, and no provider-side rate limiting."
                )
            if not cfg.supabase_service_role_key:
                problems.append(
                    "SUPABASE_SERVICE_ROLE_KEY is required in production for administrator "
                    "provisioning and the user migration. Keep it server-side only — it "
                    "bypasses Row Level Security and can act as any user."
                )

        if (
            cfg.supabase_anon_key
            and cfg.supabase_service_role_key
            and cfg.supabase_anon_key == cfg.supabase_service_role_key
        ):
            problems.append(
                "SUPABASE_ANON_KEY and SUPABASE_SERVICE_ROLE_KEY are identical. The anon "
                "key is treated as public; the service role key must never be."
            )

        # --- Mail ----------------------------------------------------------
        cfg.smtp_host = _env("SMTP_HOST")
        cfg.smtp_port = int(_env("SMTP_PORT") or 587)
        cfg.smtp_user = _env("SMTP_USER")
        cfg.smtp_password = _env("SMTP_PASSWORD")
        cfg.smtp_use_tls = _env_bool("SMTP_USE_TLS", True)
        cfg.mail_from = (
            _env("MAIL_FROM") or f"no-reply@{(cfg.admin_email.split('@') + ['fluxservers.cloud'])[1]}"
        )
        if env == "production" and not cfg.smtp_host and not cfg.uses_supabase_auth:
            problems.append(
                "SMTP_HOST is not set. Email verification and password reset cannot be "
                "delivered, which leaves the panel-takeover path open."
            )

        # --- Rate limiting -------------------------------------------------
        redis_url = _env("REDIS_URL")
        cfg.rate_limit_storage_uri = redis_url or "memory://"
        if env == "production" and not redis_url:
            cfg.warnings.append(
                "REDIS_URL is not set; rate limits are stored in process memory and will not "
                "be shared across serverless instances, weakening brute-force protection."
            )

        # --- Scheduled jobs ------------------------------------------------
        cfg.cron_secret = _env("CRON_SECRET")
        if env == "production" and not cfg.cron_secret:
            problems.append(
                "CRON_SECRET is not set. Without it the scheduled sync job cannot "
                "authenticate, so servers would never expire, suspend, or be deleted. "
                'Generate one: python -c "import secrets; print(secrets.token_urlsafe(32))"'
            )

        # --- Payments ------------------------------------------------------
        cfg.payments = PaymentConfig(
            stripe_publishable_key=_env("STRIPE_PUBLISHABLE_KEY"),
            stripe_secret_key=_env("STRIPE_SECRET_KEY"),
            stripe_webhook_secret=_env("STRIPE_WEBHOOK_SECRET"),
            stripe_product_tax_code=_env("STRIPE_PRODUCT_TAX_CODE"),
            stripe_api_version=_env("STRIPE_API_VERSION") or "2025-03-31.basil",
            paypal_client_id=_env("PAYPAL_CLIENT_ID"),
            paypal_secret_key=_env("PAYPAL_SECRET_KEY"),
            paypal_env=(_env("PAYPAL_ENV") or "sandbox").lower(),
            paypal_merchant_id=_env("PAYPAL_MERCHANT_ID"),
            stripe_fee_percent=float(_env("STRIPE_FEE_PERCENT") or "2.9"),
            stripe_fee_fixed_cents=int(_env("STRIPE_FEE_FIXED_CENTS") or "30"),
            paypal_fee_percent=float(_env("PAYPAL_FEE_PERCENT") or "3.49"),
            paypal_fee_fixed_cents=int(_env("PAYPAL_FEE_FIXED_CENTS") or "49"),
        )
        if env != "testing":
            problems.extend(cfg.payments.validate(production=cfg.is_production))

        # --- Tunables ------------------------------------------------------
        cfg.expiry_days = int(_env("EXPIRY_DAYS") or 30)
        cfg.deletion_grace_days = int(_env("DELETION_GRACE_DAYS") or 7)

        if problems:
            raise ConfigError(
                "Refusing to start due to unsafe or incomplete configuration:\n"
                + "\n".join(f"  - {p}" for p in problems)
                + "\n\nSee .env.example for the full list of required variables."
            )

        return cfg

    def as_flask_config(self) -> dict[str, object]:
        """Translate into the keys Flask and its extensions expect."""
        from datetime import timedelta

        # Secure cookies require HTTPS; local development and the test client
        # both run over plain HTTP.
        secure_cookies = self.is_production

        engine_options: dict[str, object] = {"pool_pre_ping": True}
        if self.is_postgres:
            # Serverless runs many short-lived instances; a per-instance pool
            # multiplies into connection exhaustion. Let the external pooler
            # (Supabase/PgBouncer) own pooling instead (audit SC-1).
            from sqlalchemy.pool import NullPool

            engine_options["poolclass"] = NullPool
            engine_options["connect_args"] = {
                "connect_timeout": 5,
                # A runaway query must not pin a pooled backend forever, and a
                # serverless function is killed long before 30s anyway.
                "options": "-c statement_timeout=25000",
                "application_name": "fluxweb",
            }
            # pool_pre_ping costs a round-trip per checkout and is pointless
            # with NullPool, which opens a fresh connection every time.
            engine_options.pop("pool_pre_ping", None)

        return {
            "ENV": self.env,
            "DEBUG": self.is_development,
            "TESTING": self.is_testing,
            "SECRET_KEY": self.secret_key,
            "SQLALCHEMY_DATABASE_URI": self.database_url,
            "SQLALCHEMY_TRACK_MODIFICATIONS": False,
            "SQLALCHEMY_ENGINE_OPTIONS": engine_options,
            "SESSION_COOKIE_NAME": "__fxt_id",
            "SESSION_COOKIE_HTTPONLY": True,
            "SESSION_COOKIE_SECURE": secure_cookies,
            "SESSION_COOKIE_SAMESITE": "Lax",
            "PERMANENT_SESSION_LIFETIME": timedelta(days=self.session_lifetime_days),
            "WTF_CSRF_SSL_STRICT": secure_cookies,
            "WTF_CSRF_TIME_LIMIT": 3600,
            "MAX_CONTENT_LENGTH": self.max_content_length,
            "PREFERRED_URL_SCHEME": "http" if self.is_development else "https",
            "RATELIMIT_STORAGE_URI": self.rate_limit_storage_uri,
            # Rate limits would make tests order-dependent and flaky.
            "RATELIMIT_ENABLED": not self.is_testing,
        }
