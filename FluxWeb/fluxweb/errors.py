"""Error taxonomy.

The old code flashed raw upstream response bodies to end users, leaking
internal hostnames and panel diagnostics (audit S-4). The split here is:

    DomainError      - caused by the user, safe to display verbatim
    IntegrationError - an upstream failed; log the detail, show a generic message
    ConfigurationError - we are misconfigured; never shown to users
"""

from __future__ import annotations


class FluxError(Exception):
    """Base class for all application errors."""

    #: Message shown to end users. Subclasses decide whether it echoes `detail`.
    user_message = "Something went wrong. Please try again."

    def __init__(self, detail: str = "", *, user_message: str | None = None) -> None:
        super().__init__(detail or self.user_message)
        self.detail = detail
        if user_message is not None:
            self.user_message = user_message


class DomainError(FluxError):
    """A rule the user broke. Safe to show as-is."""

    def __init__(self, message: str) -> None:
        super().__init__(message, user_message=message)


class ValidationError(DomainError):
    """Submitted data was missing or malformed."""


class AuthorizationError(DomainError):
    """The caller may not touch this resource."""

    def __init__(self, message: str = "You do not have access to that resource.") -> None:
        super().__init__(message)


class PaymentError(DomainError):
    """A payment could not be created, verified, or captured."""


class IntegrationError(FluxError):
    """An upstream service failed. `detail` is for logs only."""

    user_message = "We could not reach one of our services. Please try again shortly."

    def __init__(self, service: str, detail: str = "", *, status: int | None = None) -> None:
        super().__init__(detail)
        self.service = service
        self.status = status

    def __str__(self) -> str:  # pragma: no cover - diagnostic only
        status = f" (status {self.status})" if self.status else ""
        return f"{self.service}{status}: {self.detail}"


class PanelError(IntegrationError):
    """The game panel rejected or failed a request."""

    user_message = "The game panel is temporarily unavailable. Please try again shortly."

    def __init__(self, detail: str = "", *, status: int | None = None) -> None:
        super().__init__("panel", detail, status=status)


class ConfigurationError(FluxError):
    """We are misconfigured. Operators only."""

    user_message = "This feature is not available right now."
