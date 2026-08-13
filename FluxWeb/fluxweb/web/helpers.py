"""Shared view helpers: current user, access control, safe redirects.

Ownership checks used to be hand-copied into every route, which is how routes
end up missing them (audit S-2). They live here once now.
"""

from __future__ import annotations

from functools import wraps
from urllib.parse import urlparse

from flask import current_app, flash, g, jsonify, redirect, request, session, url_for

from fluxweb.errors import AuthorizationError
from fluxweb.models import ServerRecord, User


def current_user() -> User | None:
    """The logged-in user, or None. Cached per request."""
    if "current_user" not in g:
        user_id = session.get("user_id")
        g.current_user = User.query.get(user_id) if user_id else None
        # A session pointing at a deleted user used to raise AttributeError on
        # every request until the cookie was cleared (audit M-24).
        if user_id and g.current_user is None:
            session.clear()
    return g.current_user


def login_user(user: User) -> None:
    session.clear()
    session["user_id"] = user.id
    session.permanent = True


def logout_user() -> None:
    session.clear()


def wants_json() -> bool:
    return (
        request.is_json
        or request.accept_mimetypes.best == "application/json"
        or request.path.startswith("/api/")
    )


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None:
            if wants_json():
                return jsonify({"status": "error", "message": "Login required"}), 401
            return redirect(url_for("auth.login", url=request.path.lstrip("/")))
        return view(*args, **kwargs)

    return wrapped


def verified_email_required(view):
    """Gate actions that create panel resources behind a verified address."""

    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None:
            if wants_json():
                return jsonify({"status": "error", "message": "Login required"}), 401
            return redirect(url_for("auth.login", url=request.path.lstrip("/")))
        if not user.email_verified:
            message = "Please verify your email address before continuing."
            if wants_json():
                return jsonify({"status": "error", "message": message, "code": "email_unverified"}), 403
            flash(message, "error")
            return redirect(url_for("account.user_account"))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None:
            return redirect(url_for("auth.login", url=request.path.lstrip("/")))
        if not is_admin(user):
            flash("Admin access required.", "error")
            return redirect(url_for("public.index"))
        return view(*args, **kwargs)

    return wrapped


def is_admin(user: User | None) -> bool:
    """Admin status from the database flag, with the configured address as a
    bootstrap fallback for the very first deploy."""
    if user is None:
        return False
    if user.is_admin:
        return True
    admin_email = current_app.extensions["flux_config"].admin_email
    return bool(admin_email) and user.email.lower() == admin_email.lower()


def get_owned_server(identifier_or_id, *, by_identifier: bool = False) -> ServerRecord:
    """Fetch a server that belongs to the current user, or raise."""
    user = current_user()
    if user is None:
        raise AuthorizationError("Login required.")
    query = ServerRecord.query.filter_by(user_id=user.id)
    if by_identifier:
        record = query.filter_by(pelican_server_identifier=identifier_or_id).first()
    else:
        record = query.filter_by(id=identifier_or_id).first()
    if record is None:
        raise AuthorizationError("Server not found on your account.")
    return record


def safe_redirect_target(raw: str | None, default_endpoint: str = "public.index") -> str:
    """Return a redirect target guaranteed to stay on this site.

    ``'/' + value.lstrip('/')`` was not enough: ``?url=\\evil.com`` becomes
    ``/\\evil.com``, which browsers normalise to a protocol-relative URL and
    follow off-site (audit M-19).
    """
    fallback = url_for(default_endpoint)
    if not raw:
        return fallback

    raw = raw.strip()
    if not raw:
        return fallback

    # Backslashes and control characters are only ever used to smuggle a host
    # past a naive check, and header injection needs CR/LF.
    if "\\" in raw or any(ch in raw for ch in "\r\n\t"):
        return fallback

    # Inspect the value *before* prefixing a slash. Prefixing first would turn
    # "https://evil.com" into the harmless-but-wrong "/https://evil.com", and
    # would let "javascript:..." through as if it were a path.
    parsed = urlparse(raw)
    if parsed.scheme or parsed.netloc:
        return fallback

    candidate = raw if raw.startswith("/") else "/" + raw
    if candidate.startswith("//"):
        return fallback

    parsed = urlparse(candidate)
    if parsed.scheme or parsed.netloc or not parsed.path.startswith("/"):
        return fallback

    query = f"?{parsed.query}" if parsed.query else ""
    return f"{parsed.path}{query}"
