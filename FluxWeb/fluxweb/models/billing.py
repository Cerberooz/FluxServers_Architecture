"""Billing ledger: orders, line items, payments, coupons.

This is the record that did not exist before (audit H-16). It also carries the
two properties that close the payment bypasses:

* An ``Order`` is an immutable *snapshot* of what was priced, taken before the
  customer is sent to a payment provider. Provisioning reads the snapshot, not
  the live session cart, so the cart can no longer be swapped after payment
  (audit C-6).
* ``Payment`` has a UNIQUE constraint on ``(provider, provider_ref)``, so a
  provider reference can be redeemed exactly once, ever (audit C-5).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fluxweb.extensions import db


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class OrderStatus:
    PENDING = "pending"
    PAID = "paid"
    PROVISIONING = "provisioning"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ItemKind:
    NEW = "new"
    RENEWAL = "renewal"
    UPGRADE = "upgrade"


class Order(db.Model):
    __tablename__ = "customer_order"
    __table_args__ = (
        db.Index("ix_customer_order_user_status", "user_id", "status"),
        db.Index("ix_customer_order_created", "created_at"),
    )

    id = db.Column(db.Integer, primary_key=True)
    public_id = db.Column(
        db.String(36), nullable=False, unique=True, index=True, default=lambda: str(uuid.uuid4())
    )
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    status = db.Column(db.String(20), nullable=False, default=OrderStatus.PENDING)

    # Frozen at creation time, in integer cents (audit H-14).
    subtotal_cents = db.Column(db.Integer, nullable=False, default=0)
    discount_cents = db.Column(db.Integer, nullable=False, default=0)
    total_cents = db.Column(db.Integer, nullable=False, default=0)
    gateway_fee_cents = db.Column(db.Integer, nullable=False, default=0)
    payment_provider = db.Column(db.String(20), nullable=True)
    currency = db.Column(db.String(3), nullable=False, default="USD")
    coupon_code = db.Column(db.String(50), nullable=True)

    # Deployment options captured with the order rather than left in the session.
    server_name = db.Column(db.String(100), nullable=True)
    node_id = db.Column(db.Integer, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    paid_at = db.Column(db.DateTime, nullable=True)
    provisioned_at = db.Column(db.DateTime, nullable=True)
    failure_reason = db.Column(db.Text, nullable=True)

    items = db.relationship("OrderItem", backref="order", lazy="joined", cascade="all, delete-orphan")
    payments = db.relationship("Payment", backref="order", lazy=True)

    @property
    def is_paid(self) -> bool:
        """Whether money has been taken for this order.

        Deliberately keyed on ``paid_at`` rather than on ``status``. Payment
        and fulfilment are separate concerns: an order whose provisioning
        failed carries status FAILED but has still been paid, and must remain
        retryable. Deriving this from the status enum meant a customer who
        paid and hit a panel error could never be provisioned at all.
        """
        return self.paid_at is not None

    @property
    def is_free(self) -> bool:
        return self.total_cents == 0

    def mark_paid(self) -> None:
        if not self.paid_at:
            self.paid_at = utcnow()
        self.status = OrderStatus.PAID

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Order {self.public_id} {self.status} {self.total_cents}c>"


class OrderItem(db.Model):
    __tablename__ = "customer_order_item"

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("customer_order.id", ondelete="CASCADE"), nullable=False)

    kind = db.Column(db.String(20), nullable=False, default=ItemKind.NEW)
    plan_id = db.Column(db.Integer, db.ForeignKey("game_plan.id"), nullable=True)
    server_id = db.Column(db.Integer, db.ForeignKey("server_record.id"), nullable=True)

    #: Display name frozen at purchase time so later plan renames do not rewrite history.
    name = db.Column(db.String(200), nullable=False)
    unit_price_cents = db.Column(db.Integer, nullable=False, default=0)
    software = db.Column(db.String(30), nullable=True)
    node_id = db.Column(db.Integer, nullable=True)
    egg_id = db.Column(db.Integer, nullable=True)

    #: Set once this line has been fulfilled. Makes provisioning idempotent:
    #: a retried webhook skips lines that already produced a server.
    fulfilled_at = db.Column(db.DateTime, nullable=True)
    fulfilled_server_id = db.Column(db.Integer, nullable=True)

    plan = db.relationship("GamePlan", lazy="joined", foreign_keys=[plan_id])

    @property
    def is_fulfilled(self) -> bool:
        return self.fulfilled_at is not None


class Payment(db.Model):
    """One capture attempt from a payment provider.

    The unique constraint is the anti-replay control: the same Stripe session
    or PayPal order can never be credited to a second order (audit C-5).
    """

    __tablename__ = "payment"
    __table_args__ = (
        db.UniqueConstraint("provider", "provider_ref", name="uq_payment_provider_ref"),
        db.Index("ix_payment_order", "order_id"),
    )

    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("customer_order.id"), nullable=False)

    provider = db.Column(db.String(20), nullable=False)  # 'stripe' | 'paypal' | 'free'
    provider_ref = db.Column(db.String(255), nullable=False)

    amount_cents = db.Column(db.Integer, nullable=False)
    currency = db.Column(db.String(3), nullable=False, default="USD")
    status = db.Column(db.String(30), nullable=False, default="captured")

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Payment {self.provider}:{self.provider_ref} {self.amount_cents}c>"


class Coupon(db.Model):
    __tablename__ = "coupon"

    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)
    discount_percent = db.Column(db.Float, default=0.0)

    # Constraints the original model had no concept of (audit M-25).
    active = db.Column(db.Boolean, nullable=False, default=True)
    expires_at = db.Column(db.DateTime, nullable=True)
    max_redemptions = db.Column(db.Integer, nullable=True)
    times_redeemed = db.Column(db.Integer, nullable=False, default=0)

    def validation_error(self) -> str | None:
        """Return why this coupon cannot be used, or None when it is valid."""
        if not self.active:
            return "That coupon is no longer active."
        if self.expires_at and self.expires_at < utcnow():
            return "That coupon has expired."
        if self.max_redemptions is not None and (self.times_redeemed or 0) >= self.max_redemptions:
            return "That coupon has reached its redemption limit."
        return None

    @property
    def is_valid(self) -> bool:
        return self.validation_error() is None

    @property
    def safe_discount_percent(self) -> float:
        """Discount clamped to 0-100 regardless of what an admin typed."""
        return max(0.0, min(100.0, float(self.discount_percent or 0.0)))
