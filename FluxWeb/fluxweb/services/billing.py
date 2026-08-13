"""Billing: pricing, order snapshots, and payment reconciliation.

This is the single implementation both payment providers use. Previously
``/checkout`` (PayPal) and ``/stripe-success`` (Stripe) each had their own copy
of this logic and each had different bugs.

The invariants enforced here are the ones the audit found missing:

* Prices always come from the database, never from the client or the cookie.
* An :class:`Order` is frozen before the customer is sent to a provider, and
  provisioning reads the frozen snapshot (audit C-6).
* A provider reference can be redeemed exactly once (audit C-5).
* The captured amount and currency must match the snapshot (audit C-4).
"""

from __future__ import annotations

import logging

from sqlalchemy.exc import IntegrityError

from fluxweb.errors import DomainError, PaymentError, ValidationError
from fluxweb.extensions import db
from fluxweb.integrations.payments.base import CapturedPayment
from fluxweb.models import (
    Coupon,
    GamePlan,
    ItemKind,
    Order,
    OrderItem,
    OrderStatus,
    Payment,
    ServerRecord,
)
from fluxweb.money import apply_percentage_discount
from fluxweb.services.cart import CartItem

log = logging.getLogger(__name__)


# --- pricing ------------------------------------------------------------
def line_price_cents(item: CartItem, plan: GamePlan) -> int:
    """Price one cart line, in cents, from database state only."""
    if item.kind == ItemKind.UPGRADE:
        server = ServerRecord.query.get(item.server_id) if item.server_id else None
        current_plan = GamePlan.query.get(server.plan_id) if server and server.plan_id else None
        if current_plan is None:
            raise ValidationError("The server being upgraded no longer has a valid plan.")
        return max(0, plan.price_cents - current_plan.price_cents)
    return plan.price_cents


def validate_upgrade(server: ServerRecord, new_plan: GamePlan) -> GamePlan:
    """Reject upgrades the UI would not offer.

    The old endpoint accepted any plan id and priced it as ``max(0, diff)``, so
    picking a better-specified but cheaper plan was a free upgrade (audit M-22).
    """
    current_plan = GamePlan.query.get(server.plan_id) if server.plan_id else None
    if current_plan is None:
        raise ValidationError("This server's current plan no longer exists.")
    if new_plan.game != current_plan.game:
        raise ValidationError("You can only upgrade within the same product line.")
    if new_plan.price_cents <= current_plan.price_cents:
        raise ValidationError("Choose a plan priced above your current plan.")
    return current_plan


def resolve_coupon(code: str | None) -> Coupon | None:
    """Look up a coupon and raise when it exists but cannot be used."""
    if not code:
        return None
    coupon = Coupon.query.filter_by(code=code).first()
    if coupon is None:
        raise DomainError("That coupon code is not valid.")
    problem = coupon.validation_error()
    if problem:
        raise DomainError(problem)
    return coupon


def quote(items: list[CartItem], coupon_code: str | None = None) -> dict[str, int | str | None]:
    """Price a cart without persisting anything. Used for cart display."""
    subtotal = 0
    for item in items:
        plan = GamePlan.query.get(item.plan_id) if item.plan_id else None
        if plan is None:
            continue
        subtotal += line_price_cents(item, plan)

    discount = 0
    applied_code = None
    if coupon_code:
        try:
            coupon = resolve_coupon(coupon_code)
        except DomainError:
            coupon = None
        if coupon is not None:
            discount = apply_percentage_discount(subtotal, coupon.safe_discount_percent)
            applied_code = coupon.code

    return {
        "subtotal_cents": subtotal,
        "discount_cents": discount,
        "total_cents": max(0, subtotal - discount),
        "coupon_code": applied_code,
    }


def allowed_node_ids_for_items(items: list[CartItem]) -> list[int]:
    new_plans: list[GamePlan] = []
    for item in items:
        if item.kind != ItemKind.NEW or not item.plan_id:
            continue
        plan = GamePlan.query.get(item.plan_id)
        if plan is not None:
            new_plans.append(plan)

    if not new_plans:
        return []

    common = set(new_plans[0].allowed_node_ids)
    for plan in new_plans[1:]:
        common &= set(plan.allowed_node_ids)
    return sorted(common)


# --- order snapshot -----------------------------------------------------
def build_order(
    user,
    items: list[CartItem],
    *,
    coupon_code: str | None = None,
    server_name: str | None = None,
    node_id: int | None = None,
) -> Order:
    """Freeze the cart into a persisted :class:`Order`.

    Everything downstream — the amount charged, what gets provisioned — reads
    this row. The session cart is not consulted again.
    """
    if not items:
        raise ValidationError("Your cart is empty.")

    # New-server choices are frozen per cart line. The legacy order-level node
    # remains as a fallback for carts created before customization existed.
    if node_id is not None and node_id <= 0:
        node_id = None

    order = Order(
        user_id=user.id,
        status=OrderStatus.PENDING,
        currency="USD",
        server_name=(server_name or "").strip()[:100] or None,
        node_id=node_id,
    )

    subtotal = 0
    for item in items:
        plan = GamePlan.query.get(item.plan_id) if item.plan_id else None
        if plan is None:
            raise ValidationError("One of the plans in your cart is no longer available.")

        name = plan.name
        server = None
        if item.kind in {ItemKind.RENEWAL, ItemKind.UPGRADE}:
            server = ServerRecord.query.get(item.server_id) if item.server_id else None
            if server is None or server.user_id != user.id:
                raise ValidationError("A server in your cart could not be found on your account.")
            if item.kind == ItemKind.UPGRADE:
                validate_upgrade(server, plan)
                name = f"Upgrade: {server.pelican_server_identifier} -> {plan.name}"
            else:
                name = f"Renewal: {plan.name} ({server.pelican_server_identifier})"

        price_cents = line_price_cents(item, plan)
        selected_node = item.node_id
        selected_egg = item.egg_id
        if item.kind == ItemKind.NEW:
            if selected_node is None or selected_egg is None:
                raise ValidationError(
                    "This plan has not been configured yet. Remove it and choose Configure Plan again."
                )
            if selected_node not in plan.allowed_node_ids:
                raise ValidationError("That server location is not allowed for the selected plan.")
            if selected_egg not in plan.allowed_eggs:
                raise ValidationError("That egg is not allowed for the selected plan.")
        subtotal += price_cents

        order.items.append(
            OrderItem(
                kind=item.kind,
                plan_id=plan.id,
                server_id=server.id if server else None,
                name=name[:200],
                unit_price_cents=price_cents,
                software=item.software,
                node_id=selected_node if item.kind == ItemKind.NEW else None,
                egg_id=selected_egg if item.kind == ItemKind.NEW else None,
            )
        )

    coupon = resolve_coupon(coupon_code) if coupon_code else None
    discount = apply_percentage_discount(subtotal, coupon.safe_discount_percent) if coupon else 0

    order.subtotal_cents = subtotal
    order.discount_cents = discount
    order.total_cents = max(0, subtotal - discount)
    order.coupon_code = coupon.code if coupon else None

    db.session.add(order)
    db.session.commit()
    log.info("Created order %s for user %s totalling %s cents", order.public_id, user.id, order.total_cents)
    return order


# --- payment reconciliation --------------------------------------------
def record_payment(order: Order, captured: CapturedPayment) -> Payment:
    """Validate a captured payment against the order and record it.

    Raises :class:`PaymentError` when anything does not line up. The unique
    constraint on ``(provider, provider_ref)`` is what makes replaying an old
    reference impossible, even under concurrent requests.
    """
    if captured.order_public_id and captured.order_public_id != order.public_id:
        raise PaymentError("This payment belongs to a different order.")

    if captured.currency.upper() != (order.currency or "USD").upper():
        raise PaymentError("Payment currency does not match the order.")

    # The core amount check the old code never performed (audit C-4).
    if captured.amount_cents < order.total_cents:
        log.error(
            "Underpayment on order %s: captured %s, expected %s",
            order.public_id,
            captured.amount_cents,
            order.total_cents,
        )
        raise PaymentError("The amount paid does not match the order total.")

    existing = Payment.query.filter_by(provider=captured.provider, provider_ref=captured.reference).first()
    if existing is not None:
        if existing.order_id != order.id:
            # Someone is trying to spend one payment on a second order.
            log.warning(
                "Rejected reuse of %s payment %s on order %s (already on order %s)",
                captured.provider,
                captured.reference,
                order.id,
                existing.order_id,
            )
            raise PaymentError("This payment reference has already been used.")
        return existing

    payment = Payment(
        order_id=order.id,
        provider=captured.provider,
        provider_ref=captured.reference,
        amount_cents=captured.amount_cents,
        currency=captured.currency.upper(),
        status=captured.status,
    )
    db.session.add(payment)
    order.mark_paid()

    if order.coupon_code:
        coupon = Coupon.query.filter_by(code=order.coupon_code).first()
        if coupon is not None:
            coupon.times_redeemed = (coupon.times_redeemed or 0) + 1

    try:
        db.session.commit()
    except IntegrityError:
        # Lost a race against a concurrent webhook delivery; the winner's row
        # is authoritative.
        db.session.rollback()
        existing = Payment.query.filter_by(
            provider=captured.provider, provider_ref=captured.reference
        ).first()
        if existing is None:
            raise
        if existing.order_id != order.id:
            raise PaymentError("This payment reference has already been used.") from None
        return existing

    log.info("Recorded %s payment %s for order %s", captured.provider, captured.reference, order.public_id)
    return payment


def mark_free_order_paid(order: Order) -> Payment:
    """Settle a zero-total order (100% coupon) without a provider."""
    if order.total_cents != 0:
        raise PaymentError("This order requires payment.")
    return record_payment(
        order,
        CapturedPayment(
            provider="free",
            reference=f"free-{order.public_id}",
            amount_cents=0,
            currency=order.currency or "USD",
            status="free",
            order_public_id=order.public_id,
        ),
    )
