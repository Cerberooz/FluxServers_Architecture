"""Payment providers behind a single interface."""

from __future__ import annotations

from fluxweb.integrations.payments.base import CapturedPayment, PaymentProvider
from fluxweb.integrations.payments.paypal_provider import PayPalProvider
from fluxweb.integrations.payments.stripe_provider import StripeProvider

__all__ = [
    "CapturedPayment",
    "PaymentProvider",
    "PayPalProvider",
    "StripeProvider",
    "get_stripe",
    "get_paypal",
]


def get_stripe() -> StripeProvider:
    from flask import current_app

    payments = current_app.extensions["flux_config"].payments
    return StripeProvider(
        secret_key=payments.stripe_secret_key,
        publishable_key=payments.stripe_publishable_key,
        webhook_secret=payments.stripe_webhook_secret,
        product_tax_code=payments.stripe_product_tax_code,
        api_version=payments.stripe_api_version,
    )


def get_paypal() -> PayPalProvider:
    from flask import current_app

    payments = current_app.extensions["flux_config"].payments
    return PayPalProvider(
        client_id=payments.paypal_client_id,
        secret_key=payments.paypal_secret_key,
        api_base=payments.paypal_api_base,
        merchant_id=payments.paypal_merchant_id,
    )
