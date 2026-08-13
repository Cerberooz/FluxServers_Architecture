"""Supabase Auth (GoTrue) client.

A thin REST wrapper rather than the `supabase-py` SDK: this application only
needs six endpoints, the SDK pulls in postgrest/storage/realtime that we do
not use, and keeping it here matches how `FluidPanelClient` is structured — one
pooled session, uniform timeouts, typed errors.

Two keys, and the distinction matters:

* ``anon`` key — public by design. Used for sign-up, sign-in, and password
  reset requests, exactly as a browser would.
* ``service_role`` key — bypasses all Row Level Security and can act as any
  user. **Never send it to a browser.** Used only for admin operations:
  provisioning the first administrator and the one-off user migration.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from fluxweb.errors import ConfigurationError, DomainError, IntegrationError

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 15


class AuthError(DomainError):
    """A credential problem that is safe to show the user."""


@dataclass(frozen=True)
class SupabaseUser:
    """The subset of a GoTrue user record this application cares about."""

    id: str
    email: str
    email_confirmed: bool
    raw: dict[str, Any]
    #: "email", "google", "discord", ... Used to hide the password form from
    #: accounts that have no password to change.
    provider: str = "email"
    #: Display name offered by the provider, when there is one.
    full_name: str | None = None

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> SupabaseUser:
        confirmed = bool(payload.get("email_confirmed_at") or payload.get("confirmed_at"))
        app_metadata = payload.get("app_metadata") or {}
        user_metadata = payload.get("user_metadata") or {}
        name = user_metadata.get("full_name") or user_metadata.get("name")
        return cls(
            id=str(payload.get("id", "")),
            email=str(payload.get("email", "")),
            email_confirmed=confirmed,
            raw=payload,
            provider=str(app_metadata.get("provider") or "email"),
            full_name=str(name) if name else None,
        )


@dataclass(frozen=True)
class AuthSession:
    """Result of a successful sign-in or token verification."""

    user: SupabaseUser
    access_token: str
    refresh_token: str | None


#: GoTrue error codes mapped to messages we are willing to show.
_SAFE_ERRORS = {
    "invalid_credentials": "Invalid credentials.",
    "email_not_confirmed": "Please confirm your email address before signing in.",
    "user_already_exists": "That email address is already registered.",
    "email_exists": "That email address is already registered.",
    "weak_password": "That password is too weak. Choose a stronger one.",
    "over_email_send_rate_limit": "Too many emails requested. Please wait a few minutes.",
    "otp_expired": "That link has expired. Please request a new one.",
    "validation_failed": "Please check the details you entered.",
    "same_password": "The new password must be different from the current one.",
}


class SupabaseAuthClient:
    """REST client for the GoTrue endpoints this application uses."""

    def __init__(
        self,
        base_url: str | None,
        anon_key: str | None,
        service_role_key: str | None = None,
        *,
        timeout: int = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.anon_key = anon_key
        self.service_role_key = service_role_key
        self.timeout = timeout
        self._session: requests.Session | None = None

    # --- plumbing -------------------------------------------------------
    @property
    def configured(self) -> bool:
        return bool(self.base_url and self.anon_key)

    @property
    def session(self) -> requests.Session:
        if self._session is None:
            session = requests.Session()
            retry = Retry(
                total=2,
                backoff_factor=0.4,
                status_forcelist=(429, 502, 503, 504),
                # Reads only. Retrying a sign-up POST could create a duplicate
                # identity or burn an email rate limit.
                allowed_methods=frozenset({"GET"}),
                raise_on_status=False,
            )
            session.mount("https://", HTTPAdapter(max_retries=retry, pool_connections=4, pool_maxsize=8))
            session.mount("http://", HTTPAdapter(max_retries=retry))
            self._session = session
        return self._session

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        access_token: str | None = None,
        service_role: bool = False,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.configured:
            raise ConfigurationError("Supabase Auth is not configured")

        key = self.service_role_key if service_role else self.anon_key
        if service_role and not key:
            raise ConfigurationError("SUPABASE_SERVICE_ROLE_KEY is not configured")

        headers = {
            "apikey": key or "",
            "Authorization": f"Bearer {access_token or key}",
            "Content-Type": "application/json",
        }

        try:
            response = self.session.request(
                method,
                f"{self.base_url}/auth/v1{path}",
                headers=headers,
                json=json_body,
                params=params,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            log.warning("Supabase Auth request failed: %s %s: %s", method, path, exc)
            raise IntegrationError("supabase-auth", f"{method} {path}: {exc}") from exc

        if response.status_code >= 400:
            self._raise_for_error(response, method, path)

        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise IntegrationError("supabase-auth", f"{method} {path}: response was not JSON") from exc

    def _raise_for_error(self, response: requests.Response, method: str, path: str) -> None:
        """Translate a GoTrue error into either a user-safe or an opaque error."""
        try:
            payload = response.json()
        except ValueError:
            payload = {}

        code = str(payload.get("error_code") or payload.get("error") or "")
        description = str(
            payload.get("msg") or payload.get("error_description") or payload.get("message") or ""
        )

        log.warning(
            "Supabase Auth rejected %s %s: %s %s %s",
            method,
            path,
            response.status_code,
            code,
            description[:200],
        )

        safe = _SAFE_ERRORS.get(code)
        if safe:
            raise AuthError(safe)

        # Match on the description only for the handful of cases GoTrue does
        # not give a stable code for.
        lowered = description.lower()
        if "invalid login credentials" in lowered:
            raise AuthError("Invalid credentials.")
        if "email not confirmed" in lowered:
            raise AuthError("Please confirm your email address before signing in.")
        if "already registered" in lowered or "already exists" in lowered:
            raise AuthError("That email address is already registered.")
        if response.status_code == 429:
            raise AuthError("Too many attempts. Please wait a few minutes and try again.")

        # Anything unrecognised is an integration problem: log the detail,
        # show the user nothing specific.
        raise IntegrationError(
            "supabase-auth", description or response.text[:300], status=response.status_code
        )

    # --- public flows ---------------------------------------------------
    def sign_up(
        self,
        *,
        email: str,
        password: str,
        redirect_to: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> SupabaseUser:
        """Register a user. Supabase sends the confirmation email."""
        body: dict[str, Any] = {"email": email, "password": password}
        if metadata:
            body["data"] = metadata
        params = {"redirect_to": redirect_to} if redirect_to else None

        payload = self._request("POST", "/signup", json_body=body, params=params)
        user_payload = payload.get("user") or payload
        return SupabaseUser.from_payload(user_payload)

    def sign_in(self, *, email: str, password: str) -> AuthSession:
        payload = self._request(
            "POST",
            "/token",
            params={"grant_type": "password"},
            json_body={"email": email, "password": password},
        )
        return AuthSession(
            user=SupabaseUser.from_payload(payload.get("user") or {}),
            access_token=str(payload.get("access_token", "")),
            refresh_token=payload.get("refresh_token"),
        )

    def send_password_reset(self, *, email: str, redirect_to: str | None = None) -> None:
        params = {"redirect_to": redirect_to} if redirect_to else None
        self._request("POST", "/recover", json_body={"email": email}, params=params)

    def resend_confirmation(self, *, email: str, redirect_to: str | None = None) -> None:
        params = {"redirect_to": redirect_to} if redirect_to else None
        self._request("POST", "/resend", json_body={"type": "signup", "email": email}, params=params)

    def verify_token_hash(self, *, token_hash: str, verification_type: str) -> AuthSession:
        """Exchange an emailed token hash for a session, server-side.

        This is the reason the email templates are customised (see README):
        the default Supabase links return tokens in the URL *fragment*, which
        a server never receives. ``token_hash`` arrives as a normal query
        parameter and is redeemed here without any browser JavaScript.
        """
        payload = self._request(
            "POST",
            "/verify",
            json_body={"type": verification_type, "token_hash": token_hash},
        )
        return AuthSession(
            user=SupabaseUser.from_payload(payload.get("user") or {}),
            access_token=str(payload.get("access_token", "")),
            refresh_token=payload.get("refresh_token"),
        )

    # --- OAuth (PKCE, server-side) --------------------------------------
    @staticmethod
    def generate_pkce_pair() -> tuple[str, str]:
        """Return ``(code_verifier, code_challenge)`` for an OAuth start.

        PKCE is what lets this stay server-side. Without it, Supabase returns
        the session in the URL *fragment*, which never reaches a server; with
        it, the callback carries a ``?code=`` that is exchanged over the API.
        """
        import base64
        import hashlib
        import secrets as _secrets

        verifier = _secrets.token_urlsafe(64)[:128]
        digest = hashlib.sha256(verifier.encode("ascii")).digest()
        challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
        return verifier, challenge

    def authorize_url(self, *, provider: str, redirect_to: str, code_challenge: str) -> str:
        """Build the URL to send the browser to for an OAuth sign-in."""
        from urllib.parse import urlencode

        if not self.configured:
            raise ConfigurationError("Supabase Auth is not configured")

        query = urlencode(
            {
                "provider": provider,
                "redirect_to": redirect_to,
                "code_challenge": code_challenge,
                "code_challenge_method": "s256",
            }
        )
        return f"{self.base_url}/auth/v1/authorize?{query}"

    def exchange_code(self, *, auth_code: str, code_verifier: str) -> AuthSession:
        """Redeem the ``?code=`` from an OAuth callback for a session."""
        payload = self._request(
            "POST",
            "/token",
            params={"grant_type": "pkce"},
            json_body={"auth_code": auth_code, "code_verifier": code_verifier},
        )
        return AuthSession(
            user=SupabaseUser.from_payload(payload.get("user") or {}),
            access_token=str(payload.get("access_token", "")),
            refresh_token=payload.get("refresh_token"),
        )

    def enabled_providers(self) -> list[str]:
        """External providers currently switched on for the project."""
        payload = self._request("GET", "/settings")
        external = payload.get("external") or {}
        return sorted(name for name, on in external.items() if on and name != "email")

    def update_password(self, *, access_token: str, password: str) -> SupabaseUser:
        payload = self._request("PUT", "/user", json_body={"password": password}, access_token=access_token)
        return SupabaseUser.from_payload(payload)

    def get_user(self, access_token: str) -> SupabaseUser:
        payload = self._request("GET", "/user", access_token=access_token)
        return SupabaseUser.from_payload(payload)

    def sign_out(self, access_token: str) -> None:
        """Revoke the refresh token so the session cannot be resumed."""
        try:
            self._request("POST", "/logout", access_token=access_token)
        except (IntegrationError, AuthError):
            # Losing a logout call must never block the local session clear.
            log.info("Supabase sign-out call failed; clearing the local session anyway.")

    # --- admin (service role) -------------------------------------------
    def admin_create_user(
        self,
        *,
        email: str,
        password: str,
        email_confirm: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> SupabaseUser:
        body: dict[str, Any] = {
            "email": email,
            "password": password,
            "email_confirm": email_confirm,
        }
        if metadata:
            body["user_metadata"] = metadata
        payload = self._request("POST", "/admin/users", json_body=body, service_role=True)
        return SupabaseUser.from_payload(payload)

    def admin_find_user_by_email(self, email: str) -> SupabaseUser | None:
        payload = self._request(
            "GET", "/admin/users", params={"filter": email, "per_page": 50}, service_role=True
        )
        for candidate in payload.get("users", []) or []:
            if str(candidate.get("email", "")).lower() == email.lower():
                return SupabaseUser.from_payload(candidate)
        return None

    def admin_update_user(self, user_id: str, **fields: Any) -> SupabaseUser:
        payload = self._request("PUT", f"/admin/users/{user_id}", json_body=fields, service_role=True)
        return SupabaseUser.from_payload(payload)


def get_supabase_auth() -> SupabaseAuthClient:
    """Return the request-scoped auth client."""
    from flask import current_app, g

    if "supabase_auth" not in g:
        config = current_app.extensions["flux_config"]
        g.supabase_auth = SupabaseAuthClient(
            config.supabase_url, config.supabase_anon_key, config.supabase_service_role_key
        )
    return g.supabase_auth
