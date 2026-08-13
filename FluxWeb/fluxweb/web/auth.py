"""Authentication: register, login, logout, verification, password reset.

URL paths are unchanged from the original application because templates link
to them as hardcoded strings.

Credentials are held by Supabase Auth in production (see
:mod:`fluxweb.services.auth_backends`). The flow stays entirely server-side:
Supabase's emails are configured to link back here with a ``token_hash`` query
parameter, which this application redeems over the API. That avoids the
default fragment-based flow, which a server never sees and which would require
rewriting these pages in JavaScript.
"""

from __future__ import annotations

import logging

from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from fluxweb.errors import ConfigurationError, DomainError, IntegrationError
from fluxweb.extensions import limiter
from fluxweb.integrations.fluid import get_fluid_client
from fluxweb.models import User
from fluxweb.services import accounts
from fluxweb.services.auth_backends import AuthBackend, SupabaseAuthBackend, get_auth_backend
from fluxweb.services.provisioning import ensure_panel_user
from fluxweb.web.helpers import current_user, login_user, logout_user, safe_redirect_target

log = logging.getLogger(__name__)

bp = Blueprint("auth", __name__)

GENERIC_RESET_MESSAGE = "If that address has an account, a reset link is on its way."

#: Address awaiting confirmation, used to render the check-email screen and to
#: scope the resend button. Cleared once the address is verified.
PENDING_EMAIL_KEY = "pending_confirmation_email"


def _absolute(path: str) -> str:
    base = (current_app.extensions["flux_config"].base_url or request.host_url).rstrip("/")
    return f"{base}{path}"


def _ensure_panel_account(user: User) -> None:
    """Link a newly authenticated web user to a Fluid account.

    Supabase remains the identity provider. Fluid gets a separate account that
    is created only by this server through the application API. A panel outage
    must not prevent a customer from signing in; provisioning can retry the
    linkage later.
    """
    if user.pelican_user_id:
        return
    try:
        ensure_panel_user(user, get_fluid_client())
    except (ConfigurationError, IntegrationError):
        log.warning("Could not link web user %s to Fluid during login", user.id, exc_info=True)


def _send_local_verification(user: User, token: str) -> None:
    """Only used by the local development backend; Supabase sends its own."""
    from fluxweb.integrations.mailer import get_mailer

    link = _absolute(url_for("auth.verify_email_token")) + f"?token_hash={token}&type=email"
    get_mailer().send(
        to=user.email,
        subject="Verify your Flux Servers email address",
        body=(
            f"Hi {user.username},\n\n"
            "Confirm your email address to activate your Flux Servers account:\n\n"
            f"{link}\n\n"
            "This link expires in 24 hours. If you did not create an account, ignore this email.\n"
        ),
    )


def _send_local_reset(user: User, token: str) -> None:
    from fluxweb.integrations.mailer import get_mailer

    link = _absolute(url_for("auth.reset_password")) + f"?token_hash={token}&type=recovery"
    get_mailer().send(
        to=user.email,
        subject="Reset your Flux Servers password",
        body=(
            f"Hi {user.username},\n\n"
            "Use this link to choose a new password:\n\n"
            f"{link}\n\n"
            "The link expires in one hour. If you did not request this, ignore this email.\n"
        ),
    )


def _auth_email_redirect(kind: str, backend: AuthBackend) -> str:
    """Return the callback URL the credential provider should email.

    Supabase sends and verifies its own auth emails, so we route both confirm
    and recovery flows through the compatibility endpoint at ``/auth/confirm``.
    The local backend still issues direct links to the final handlers.
    """
    if backend.sends_own_email:
        return _absolute(url_for("auth.auth_confirm"))
    if kind == "email":
        return _absolute(url_for("auth.verify_email_token"))
    return _absolute(url_for("auth.reset_password"))


@bp.route("/register", methods=["GET", "POST"])
@limiter.limit("5 per hour; 20 per day", methods=["POST"])
def register():
    if current_user() is not None:
        return redirect(url_for("public.index"))

    if request.method == "POST":
        backend = get_auth_backend()
        try:
            user, token = accounts.register_user(
                username=request.form.get("username"),
                email=request.form.get("email"),
                password=request.form.get("password"),
                redirect_to=_auth_email_redirect("email", backend),
                backend=backend,
            )
        except DomainError as exc:
            flash(exc.user_message, "error")
            return render_template("auth/register.html"), 400
        except IntegrationError:
            log.exception("Registration failed at the auth provider")
            flash("We could not create your account just now. Please try again shortly.", "error")
            return render_template("auth/register.html"), 502

        if user is not None and token:
            _send_local_verification(user, token)

        # Identical outcome whether or not the address was already taken: the
        # same screen, showing the same address. Nothing here reveals which
        # branch was taken (audit L-38).
        session[PENDING_EMAIL_KEY] = (request.form.get("email") or "").strip().lower()
        return redirect(url_for("auth.check_email"))

    return render_template("auth/register.html")


@bp.route("/check-email")
def check_email():
    """Post-registration screen: "we've sent you a link"."""
    pending = session.get(PENDING_EMAIL_KEY)
    if not pending:
        # Reached directly, with no registration in flight.
        return redirect(url_for("auth.login"))
    return render_template("auth/check_email.html", email=pending)


@bp.route("/check-email/resend", methods=["POST"])
@limiter.limit("3 per hour; 10 per day")
def resend_pending_confirmation():
    """Resend to the address currently in flight.

    Deliberately takes the address from the session rather than the form, so
    this cannot be pointed at arbitrary mailboxes as a spam relay.
    """
    pending = session.get(PENDING_EMAIL_KEY)
    if not pending:
        return redirect(url_for("auth.login"))

    user = User.query.filter_by(email=pending).first()
    if user is not None and not user.email_verified:
        backend = get_auth_backend()
        try:
            token = accounts.resend_confirmation(
                user, redirect_to=_auth_email_redirect("email", backend), backend=backend
            )
            if token:
                _send_local_verification(user, token)
        except (DomainError, IntegrationError) as exc:
            message = (
                exc.user_message if isinstance(exc, DomainError) else "Please wait a moment and try again."
            )
            flash(message, "error")
            return redirect(url_for("auth.check_email"))

    # Same confirmation either way.
    flash("Sent. Check your inbox, and your spam folder.", "success")
    return redirect(url_for("auth.check_email"))


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per 15 minutes; 60 per day", methods=["POST"])
def login():
    if current_user() is not None:
        return redirect(url_for("public.index"))

    if request.method == "POST":
        try:
            user = accounts.authenticate(
                email=request.form.get("email"), password=request.form.get("password")
            )
        except DomainError as exc:
            # e.g. locked out on the local backend.
            flash(exc.user_message, "error")
            return render_template("auth/login.html"), 429
        except IntegrationError:
            log.exception("Sign-in failed at the auth provider")
            flash("Sign-in is temporarily unavailable. Please try again shortly.", "error")
            return render_template("auth/login.html"), 502

        if user is not None:
            login_user(user)
            _ensure_panel_account(user)
            return redirect(safe_redirect_target(request.args.get("url"), "public.index"))

        flash("Invalid credentials.", "error")
        return render_template("auth/login.html"), 401

    return render_template("auth/login.html")


# --- external providers -------------------------------------------------
#: Display metadata for the providers this application renders buttons for.
PROVIDER_LABELS = {
    "google": ("Google", "fab fa-google", "#ffffff", "#1f1f1f"),
    "discord": ("Discord", "fab fa-discord", "#5865f2", "#ffffff"),
    "github": ("GitHub", "fab fa-github", "#24292e", "#ffffff"),
    "gitlab": ("GitLab", "fab fa-gitlab", "#fc6d26", "#ffffff"),
    "azure": ("Microsoft", "fab fa-microsoft", "#2f2f2f", "#ffffff"),
    "apple": ("Apple", "fab fa-apple", "#000000", "#ffffff"),
    "twitch": ("Twitch", "fab fa-twitch", "#9146ff", "#ffffff"),
}

OAUTH_VERIFIER_KEY = "oauth_code_verifier"
OAUTH_NEXT_KEY = "oauth_next"


@bp.route("/login/<provider>")
@limiter.limit("20 per hour")
def oauth_start(provider: str):
    """Begin an external sign-in."""
    config = current_app.extensions["flux_config"]
    provider = provider.lower()

    if provider not in config.oauth_providers:
        flash("That sign-in method is not available.", "error")
        return redirect(url_for("auth.login"))

    backend = get_auth_backend()
    if not isinstance(backend, SupabaseAuthBackend):
        flash("External sign-in requires the Supabase auth backend.", "error")
        return redirect(url_for("auth.login"))

    try:
        url, verifier = backend.oauth_authorize_url(
            provider=provider, redirect_to=_absolute(url_for("auth.oauth_callback"))
        )
    except (DomainError, IntegrationError):
        log.exception("Could not start %s sign-in", provider)
        flash("That sign-in method is unavailable right now.", "error")
        return redirect(url_for("auth.login"))

    # The verifier proves the browser completing the flow is the one that
    # started it. It lives in the signed session and is single-use.
    session[OAUTH_VERIFIER_KEY] = verifier
    session[OAUTH_NEXT_KEY] = safe_redirect_target(request.args.get("url"), "public.index")
    return redirect(url)


@bp.route("/auth/callback")
@limiter.limit("30 per hour")
def oauth_callback():
    """Finish an external sign-in.

    Supabase returns here with ``?code=`` because the flow was started with
    PKCE. The default (implicit) flow would put the session in the URL
    fragment, which a server never receives.
    """
    verifier = session.pop(OAUTH_VERIFIER_KEY, None)
    next_url = session.pop(OAUTH_NEXT_KEY, None)

    error = request.args.get("error_description") or request.args.get("error")
    if error:
        log.info("OAuth callback returned an error: %s", error)
        flash("Sign-in was cancelled or refused by the provider.", "error")
        return redirect(url_for("auth.login"))

    code = request.args.get("code")
    if not code or not verifier:
        # No verifier means this callback did not originate from our start
        # endpoint - a stale link, or a forged one.
        flash("That sign-in link is no longer valid. Please try again.", "error")
        return redirect(url_for("auth.login"))

    backend = get_auth_backend()
    if not isinstance(backend, SupabaseAuthBackend):
        return redirect(url_for("auth.login"))

    try:
        user = backend.oauth_complete(auth_code=code, code_verifier=verifier)
    except DomainError as exc:
        flash(exc.user_message, "error")
        return redirect(url_for("auth.login"))
    except IntegrationError:
        log.exception("OAuth code exchange failed")
        flash("We could not complete that sign-in. Please try again.", "error")
        return redirect(url_for("auth.login"))

    login_user(user)
    _ensure_panel_account(user)
    return redirect(next_url or url_for("public.index"))


@bp.route("/auth/confirm", methods=["GET"])
@limiter.limit("30 per hour")
def auth_confirm():
    """Supabase-friendly email entrypoint.

    Hosted Supabase examples and templates often point auth emails at an
    ``/auth/confirm`` URL carrying ``token_hash`` and ``type``. The server-side
    flows in this app already live at ``/verify-email`` and
    ``/reset-password``, so this route simply forwards to the right handler.
    """
    token = request.args.get("token_hash") or request.args.get("token") or ""
    token_type = (request.args.get("type") or "").strip().lower()

    if token_type == "email":
        return redirect(url_for("auth.verify_email_token", token_hash=token, type="email"))
    if token_type == "recovery":
        return redirect(url_for("auth.reset_password", token_hash=token, type="recovery"))

    flash("That email link is not valid. Please request a new one.", "error")
    return redirect(url_for("auth.login"))


@bp.route("/logout")
def logout():
    try:
        get_auth_backend().logout()
    except (DomainError, IntegrationError):
        log.info("Provider sign-out failed; clearing the local session anyway.")
    logout_user()
    return redirect(url_for("public.index"))


@bp.route("/verify-email", methods=["GET"])
@limiter.limit("30 per hour")
def verify_email_token():
    """Redeem an emailed confirmation token.

    Supabase's email template is configured to point here with
    ``?token_hash=...&type=email`` (see README).
    """
    token = request.args.get("token_hash") or request.args.get("token", "")
    try:
        accounts.confirm_email(token)
        session.pop(PENDING_EMAIL_KEY, None)
    except DomainError as exc:
        flash(exc.user_message, "error")
        return redirect(url_for("auth.login"))
    except IntegrationError:
        log.exception("Email confirmation failed at the auth provider")
        flash("We could not confirm your email just now. Please try the link again.", "error")
        return redirect(url_for("auth.login"))

    flash("Email verified. You can sign in now.", "success")
    return redirect(url_for("auth.login"))


@bp.route("/verify-email/<token>")
def verify_email(token: str):
    """Backwards-compatible path for links issued before the Supabase switch."""
    return redirect(url_for("auth.verify_email_token", token_hash=token, type="email"))


@bp.route("/resend-verification", methods=["POST"])
@limiter.limit("3 per hour")
def resend_verification():
    user = current_user()
    if user is None:
        return redirect(url_for("auth.login"))
    if user.email_verified:
        flash("Your email is already verified.", "success")
        return redirect(url_for("account.user_account"))

    backend = get_auth_backend()
    try:
        token = accounts.resend_confirmation(
            user, redirect_to=_auth_email_redirect("email", backend), backend=backend
        )
    except (DomainError, IntegrationError) as exc:
        message = exc.user_message if isinstance(exc, DomainError) else "Please try again shortly."
        flash(message, "error")
        return redirect(url_for("account.user_account"))

    if token:
        _send_local_verification(user, token)
    flash("Verification email sent.", "success")
    return redirect(url_for("account.user_account"))


@bp.route("/forgot-password", methods=["GET", "POST"])
@limiter.limit("5 per hour", methods=["POST"])
def forgot_password():
    if request.method == "POST":
        backend = get_auth_backend()
        try:
            user, token = accounts.start_password_reset(
                request.form.get("email") or "",
                redirect_to=_auth_email_redirect("recovery", backend),
                backend=backend,
            )
            if user is not None and token:
                _send_local_reset(user, token)
        except IntegrationError:
            log.exception("Password reset request failed at the auth provider")

        # Same message regardless: do not disclose which addresses exist.
        flash(GENERIC_RESET_MESSAGE, "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/forgot_password.html")


@bp.route("/reset-password", methods=["GET", "POST"])
@bp.route("/reset-password/<token>", methods=["GET", "POST"])
@limiter.limit("10 per hour")
def reset_password(token: str | None = None):
    """Complete a password reset.

    The token arrives as ``?token_hash=`` from Supabase, or in the path from a
    link issued before the switch. Both are accepted.
    """
    token_hash = request.form.get("token_hash") or request.args.get("token_hash") or token or ""

    if request.method == "POST":
        if not token_hash:
            flash("That reset link is not valid. Please request a new one.", "error")
            return redirect(url_for("auth.forgot_password"))
        try:
            accounts.complete_password_reset(token_hash, request.form.get("password") or "")
        except DomainError as exc:
            flash(exc.user_message, "error")
            return render_template("auth/reset_password.html", token=token_hash), 400
        except IntegrationError:
            log.exception("Password reset failed at the auth provider")
            flash("We could not reset your password just now. Please try again.", "error")
            return render_template("auth/reset_password.html", token=token_hash), 502

        flash("Password updated. You can sign in now.", "success")
        return redirect(url_for("auth.login"))

    if not token_hash:
        flash("That reset link is not valid. Please request a new one.", "error")
        return redirect(url_for("auth.forgot_password"))

    return render_template("auth/reset_password.html", token=token_hash)
