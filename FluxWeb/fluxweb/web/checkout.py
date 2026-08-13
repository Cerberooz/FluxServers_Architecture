"""Checkout.

Flow after the rework:

1. The browser asks the server to start a checkout. The server prices the cart
   from the database, freezes an :class:`Order`, and only then talks to a
   payment provider.
2. The provider is given the order total. The browser never supplies an amount.
3. Payment is confirmed server-side (Stripe webhook, or a server-side PayPal
   capture) and reconciled against the frozen order before provisioning.
4. The success page only displays status; it never provisions.
"""

from __future__ import annotations

import logging

from flask import Blueprint, current_app, flash, jsonify, redirect, request, url_for

from fluxweb.errors import DomainError, IntegrationError, PaymentError
from fluxweb.extensions import limiter
from fluxweb.integrations.payments import get_paypal, get_stripe
from fluxweb.integrations.fluid import get_fluid_client
from fluxweb.models import Order, OrderStatus
from fluxweb.services import billing, provisioning
from fluxweb.services import cart as cart_service
from fluxweb.web.helpers import current_user, login_required, verified_email_required

log = logging.getLogger(__name__)

bp = Blueprint("checkout", __name__)


def _absolute(path: str) -> str:
    base = (current_app.extensions["flux_config"].base_url or request.host_url).rstrip("/")
    return f"{base}{path}"


def _payment_description(order: Order) -> str:
    """Compact human-facing label for hosted payment pages."""
    names = [item.name.strip() for item in order.items if item.name and item.name.strip()]
    if not names:
        return "Flux Servers Hosting"
    if len(names) == 1:
        return names[0][:250]
    return f"{names[0]} + {len(names) - 1} more"[:250]


def _build_order_from_request():
    """Freeze the current cart into an Order using server-side prices."""
    user = current_user()
    items = cart_service.get_cart()

    payload = request.get_json(silent=True) or {}
    server_name = request.form.get("server_name") or payload.get("server_name")

    return billing.build_order(
        user,
        items,
        coupon_code=cart_service.get_coupon_code(),
        server_name=server_name,
        node_id=None,
    )


def _fulfil(order: Order) -> provisioning.ProvisionResult:
    config = current_app.extensions["flux_config"]
    return provisioning.provision_order(order, get_fluid_client(), expiry_days=config.expiry_days)


# --- free orders --------------------------------------------------------
@bp.route("/checkout", methods=["POST"])
@login_required
@verified_email_required
@limiter.limit("20 per hour")
def checkout():
    """Zero-total checkout only.

    Paid checkouts go through the provider-specific endpoints below. This
    endpoint used to accept a browser-supplied PayPal order id and trust it.
    """
    try:
        order = _build_order_from_request()
    except DomainError as exc:
        flash(exc.user_message, "error")
        return redirect(url_for("cart.view_cart"))

    if not order.is_free:
        order.status = OrderStatus.CANCELLED
        flash("This order requires payment. Please choose a payment method.", "error")
        return redirect(url_for("cart.view_cart"))

    try:
        billing.mark_free_order_paid(order)
    except PaymentError as exc:
        flash(exc.user_message, "error")
        return redirect(url_for("cart.view_cart"))

    result = _fulfil(order)
    cart_service.clear_cart()

    if result.success_count:
        flash(f"Success! {result.success_count} server(s) provisioned.", "success")
    for error in result.errors:
        flash(error, "error")
    return redirect(url_for("account.user_account"))


# --- Stripe -------------------------------------------------------------
@bp.route("/create-stripe-checkout", methods=["POST"])
@login_required
@verified_email_required
@limiter.limit("20 per hour")
def create_stripe_checkout():
    try:
        order = _build_order_from_request()
    except DomainError as exc:
        return jsonify({"error": exc.user_message}), 400

    if order.is_free:
        return jsonify({"error": "This order is free; use the free checkout button."}), 400

    stripe_provider = get_stripe()
    if not stripe_provider.enabled:
        return jsonify({"error": "Card payments are not available right now."}), 503

    try:
        session_id, hosted_url = stripe_provider.create_checkout_session(
            total_cents=order.total_cents,
            currency=order.currency,
            order_public_id=order.public_id,
            description=_payment_description(order),
            success_url=_absolute(url_for("checkout.stripe_success")) + "?order=" + order.public_id,
            cancel_url=_absolute(url_for("cart.view_cart")),
            customer_email=current_user().email,
        )
    except (IntegrationError, PaymentError) as exc:
        log.error("Stripe checkout creation failed for order %s: %s", order.public_id, exc)
        return jsonify({"error": "Could not start the card payment. Please try again."}), 502

    return jsonify({"id": session_id, "url": hosted_url})


@bp.route("/stripe-success")
@login_required
def stripe_success():
    """Display-only. Provisioning is driven by the webhook (audit C-7)."""
    public_id = request.args.get("order")
    order = None
    if public_id:
        order = Order.query.filter_by(public_id=public_id, user_id=current_user().id).first()

    if order is None:
        flash("We could not find that order.", "error")
        return redirect(url_for("account.user_account"))

    if order.status == OrderStatus.COMPLETED:
        cart_service.clear_cart()
        flash("Payment received and your server is ready.", "success")
    elif order.is_paid:
        cart_service.clear_cart()
        flash("Payment received. Your server is being set up and will appear shortly.", "success")
    else:
        flash(
            "We have not received confirmation of your payment yet. "
            "If you completed it, your server will appear here shortly.",
            "info",
        )
    return redirect(url_for("account.user_account"))


# --- PayPal -------------------------------------------------------------
@bp.route("/api/paypal/order", methods=["POST"])
@login_required
@verified_email_required
@limiter.limit("20 per hour")
def paypal_create_order():
    """Create the PayPal order **server-side** with a server-computed amount.

    The browser previously created this order and chose the amount itself
    (audit C-4).
    """
    paypal = get_paypal()
    if not paypal.enabled:
        return jsonify({"error": "PayPal is not available right now."}), 503

    try:
        order = _build_order_from_request()
    except DomainError as exc:
        return jsonify({"error": exc.user_message}), 400

    if order.is_free:
        return jsonify({"error": "This order is free; use the free checkout button."}), 400

    try:
        paypal_order_id = paypal.create_order(
            total_cents=order.total_cents,
            currency=order.currency,
            order_public_id=order.public_id,
            description=_payment_description(order),
            return_url=_absolute(url_for("account.user_account")),
            cancel_url=_absolute(url_for("cart.view_cart")),
        )
    except (IntegrationError, PaymentError) as exc:
        log.error("PayPal order creation failed for order %s: %s", order.public_id, exc)
        return jsonify({"error": "Could not start the PayPal payment. Please try again."}), 502

    return jsonify({"id": paypal_order_id, "order": order.public_id})


@bp.route("/api/paypal/capture", methods=["POST"])
@login_required
@verified_email_required
@limiter.limit("20 per hour")
def paypal_capture_order():
    """Capture server-side, verify the amount, then provision.

    Both the main PayPal button and the Apple/Google/Card funding buttons call
    this, so the alternate buttons can no longer capture a payment and then
    fail checkout for want of a hidden field (audit H-11).
    """
    payload = request.get_json(silent=True) or {}
    paypal_order_id = payload.get("paypal_order_id") or payload.get("orderID")
    order_public_id = payload.get("order")

    if not paypal_order_id or not order_public_id:
        return jsonify({"error": "Missing payment reference."}), 400

    order = Order.query.filter_by(public_id=order_public_id, user_id=current_user().id).first()
    if order is None:
        return jsonify({"error": "Order not found."}), 404

    paypal = get_paypal()
    try:
        captured = paypal.capture_order(str(paypal_order_id))
    except PaymentError as exc:
        log.warning("PayPal capture rejected for order %s: %s", order.public_id, exc)
        return jsonify({"error": exc.user_message}), 400
    except IntegrationError as exc:
        log.error("PayPal capture failed for order %s: %s", order.public_id, exc)
        return jsonify({"error": "We could not confirm the payment. Please contact support."}), 502

    if captured.status.upper() not in {"COMPLETED", "APPROVED"}:
        return jsonify({"error": "The payment was not completed."}), 400

    try:
        billing.record_payment(order, captured)
    except PaymentError as exc:
        log.warning("Rejected PayPal payment for order %s: %s", order.public_id, exc)
        return jsonify({"error": exc.user_message}), 400

    result = _fulfil(order)
    cart_service.clear_cart()

    return jsonify(
        {
            "status": "success",
            "provisioned": result.success_count,
            "errors": result.errors,
            "redirect": url_for("account.user_account"),
        }
    )
