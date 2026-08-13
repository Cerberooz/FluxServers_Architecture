"""Payment provider interface.

Both providers return the same :class:`CapturedPayment`, so the billing service
has one code path instead of the two divergent implementations that previously
lived in ``/checkout`` and ``/stripe-success`` (audit C-6, architecture §1).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CapturedPayment:
    """A payment the provider confirms it has taken.

    ``amount_cents``/``currency`` are what the *provider* says was captured,
    never what the browser claimed. The caller compares them against the order
    snapshot before releasing anything.
    """

    provider: str
    reference: str
    amount_cents: int
    currency: str
    status: str
    order_public_id: str | None = None


class PaymentProvider:
    name = "base"

    @property
    def enabled(self) -> bool:  # pragma: no cover - interface
        raise NotImplementedError
