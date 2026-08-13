"""Stripe provider.

Changes from the previous flow:

* The Checkout Session carries the order's ``public_id`` in metadata and
  ``client_reference_id``, so the payment can be tied back to a specific
  snapshot rather than to whatever is in the session cart at the time
  (audit C-6).
* Confirmation comes from a **signature-verified webhook**, not from the
  browser reaching the success URL. Closing the tab no longer means the
  customer pays and receives nothing (audit C-7).
* The success page only reads status; it never provisions.
"""

from __future__ import annotations

import logging
from typing import Any

import stripe

from fluxweb.errors import IntegrationError, PaymentError
from fluxweb.integrations.payments.base import CapturedPayment, PaymentProvider

log = logging.getLogger(__name__)


class StripeProvider(PaymentProvider):
    name = "stripe"

    def __init__(
        self,
        *,
        secret_key: str | None,
        publishable_key: str | None,
        webhook_secret: str | None,
        product_tax_code: str | None,
        api_version: str | None,
    ) -> None:
        self.secret_key = secret_key
        self.publishable_key = publishable_key
        self.webhook_secret = webhook_secret
        self.product_tax_code = product_tax_code
        self.api_version = api_version

    @property
    def enabled(self) -> bool:
        return bool(self.secret_key and self.publishable_key)

    def _client(self) -> Any:
        if not self.enabled:
            raise PaymentError("Card payments are not available right now.")
        stripe.api_key = self.secret_key
        if self.api_version:
            stripe.api_version = self.api_version
        return stripe

    # --- flow -----------------------------------------------------------
    def create_checkout_session(
        self,
        *,
        total_cents: int,
        currency: str,
        order_public_id: str,
        description: str,
        success_url: str,
        cancel_url: str,
        customer_email: str | None = None,
    ) -> tuple[str, str | None]:
        """Create a Checkout Session. Returns ``(session_id, hosted_url)``."""
        client = self._client()
        try:
            session = client.checkout.Session.create(
                mode="payment",
                line_items=[
                    {
                        "price_data": {
                            "currency": currency.lower(),
                            "product_data": {
                                "name": description[:250],
                                **({"tax_code": self.product_tax_code} if self.product_tax_code else {}),
                            },
                            "unit_amount": total_cents,
                        },
                        "quantity": 1,
                    }
                ],
                # Both are set: metadata survives on the PaymentIntent, and
                # client_reference_id is searchable in the dashboard.
                metadata={"order_public_id": order_public_id},
                client_reference_id=order_public_id,
                customer_email=customer_email,
                success_url=success_url,
                cancel_url=cancel_url,
                # Idempotent against double-clicks on the pay button.
                idempotency_key=f"checkout-{order_public_id}",
            )
        except stripe.error.StripeError as exc:  # type: ignore[attr-defined]
            log.error("Stripe session creation failed: %s", exc)
            raise IntegrationError("stripe", str(exc)) from exc

        return session.id, getattr(session, "url", None)

    def parse_webhook(self, payload: bytes, signature_header: str | None) -> dict[str, Any]:
        """Verify a webhook signature and return the event.

        Raises :class:`PaymentError` when the signature is absent or invalid, so
        an unsigned request can never trigger provisioning.
        """
        if not self.webhook_secret:
            raise PaymentError("Stripe webhook secret is not configured.")
        if not signature_header:
            raise PaymentError("Missing Stripe signature header.")
        try:
            event = stripe.Webhook.construct_event(payload, signature_header, self.webhook_secret)
        except ValueError as exc:
            raise PaymentError("Malformed Stripe webhook payload.") from exc
        except stripe.error.SignatureVerificationError as exc:  # type: ignore[attr-defined]
            log.warning("Rejected Stripe webhook with bad signature: %s", exc)
            raise PaymentError("Invalid Stripe webhook signature.") from exc
        return event  # type: ignore[return-value]

    @staticmethod
    def captured_payment_from_session(session: dict[str, Any]) -> CapturedPayment:
        """Translate a completed Checkout Session into a CapturedPayment."""
        metadata = session.get("metadata") or {}
        return CapturedPayment(
            provider="stripe",
            reference=str(session.get("id")),
            amount_cents=int(session.get("amount_total") or 0),
            currency=str(session.get("currency", "usd")).upper(),
            status=str(session.get("payment_status", "unknown")),
            order_public_id=metadata.get("order_public_id") or session.get("client_reference_id"),
        )

    def retrieve_session(self, session_id: str) -> dict[str, Any]:
        client = self._client()
        try:
            return client.checkout.Session.retrieve(session_id)  # type: ignore[return-value]
        except stripe.error.StripeError as exc:  # type: ignore[attr-defined]
            raise IntegrationError("stripe", str(exc)) from exc
