"""Payment webhooks.

This is the authoritative confirmation path. Previously provisioning happened
only when the customer's browser reached the success URL, so a closed tab meant
Stripe kept the money and the customer got nothing, with no record that they
had paid (audit C-7).

CSRF is exempt here because the caller is Stripe, not a browser session; the
request is authenticated by its signature instead.
"""

from __future__ import annotations

import logging

from flask import Blueprint, current_app, jsonify, request

from fluxweb.errors import PaymentError
from fluxweb.extensions import csrf
from fluxweb.integrations.payments import get_stripe
from fluxweb.integrations.fluid import get_fluid_client
from fluxweb.models import Order
from fluxweb.services import billing, provisioning

log = logging.getLogger(__name__)

bp = Blueprint("webhooks", __name__, url_prefix="/webhooks")


@bp.route("/stripe", methods=["POST"])
@csrf.exempt
def stripe_webhook():
    stripe_provider = get_stripe()

    try:
        event = stripe_provider.parse_webhook(request.get_data(), request.headers.get("Stripe-Signature"))
    except PaymentError as exc:
        # Unsigned or badly signed: never act on it.
        log.warning("Rejected Stripe webhook: %s", exc)
        return jsonify({"error": "invalid signature"}), 400

    event_type = event.get("type")
    if event_type not in {"checkout.session.completed", "checkout.session.async_payment_succeeded"}:
        return jsonify({"status": "ignored"}), 200

    session_obj = event.get("data", {}).get("object", {})
    captured = stripe_provider.captured_payment_from_session(session_obj)

    if captured.status not in {"paid", "no_payment_required"}:
        log.info("Ignoring Stripe session %s with payment_status=%s", captured.reference, captured.status)
        return jsonify({"status": "ignored"}), 200

    if not captured.order_public_id:
        log.error("Stripe session %s carried no order reference", captured.reference)
        return jsonify({"status": "no order reference"}), 200

    order = Order.query.filter_by(public_id=captured.order_public_id).first()
    if order is None:
        log.error(
            "Stripe session %s referenced unknown order %s", captured.reference, captured.order_public_id
        )
        return jsonify({"status": "unknown order"}), 200

    try:
        billing.record_payment(order, captured)
    except PaymentError as exc:
        # Already recorded, or amount mismatch. Return 200 so Stripe stops
        # retrying; the condition is logged for a human.
        log.warning("Stripe payment not recorded for order %s: %s", order.public_id, exc)
        return jsonify({"status": "not recorded", "reason": str(exc)}), 200

    config = current_app.extensions["flux_config"]
    result = provisioning.provision_order(order, get_fluid_client(), expiry_days=config.expiry_days)

    if result.errors:
        # 500 asks Stripe to retry, which retries provisioning idempotently.
        log.error("Provisioning incomplete for order %s: %s", order.public_id, result.errors)
        return jsonify({"status": "provisioning incomplete"}), 500

    return jsonify({"status": "ok", "provisioned": result.success_count}), 200
