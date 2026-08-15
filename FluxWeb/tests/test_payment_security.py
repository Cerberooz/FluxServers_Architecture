"""Regression tests for the payment bypasses found in the security audit.

Each test names the audit finding it protects. If one of these fails, a
payment bypass has been reintroduced.
"""

from __future__ import annotations

import pytest

from fluxweb.errors import DomainError, PaymentError, ValidationError
from fluxweb.integrations.payments.base import CapturedPayment
from fluxweb.models import ItemKind, Order, OrderStatus, Payment
from fluxweb.services import billing
from fluxweb.services.cart import CartItem


def _captured(
    order: Order, *, amount_cents: int | None = None, reference: str = "ref-1", provider: str = "stripe"
) -> CapturedPayment:
    return CapturedPayment(
        provider=provider,
        reference=reference,
        amount_cents=order.total_cents if amount_cents is None else amount_cents,
        currency="USD",
        status="paid",
        order_public_id=order.public_id,
    )


class TestOrderSnapshot:
    """C-6: provisioning must read the frozen order, not the live cart."""

    def test_order_prices_from_database_not_client(self, db, user, plan):
        order = billing.build_order(user, [CartItem(kind=ItemKind.NEW, plan_id=plan.id)])
        assert order.total_cents == 720  # $7.20, from the DB
        assert order.items[0].unit_price_cents == 720

    def test_changing_the_cart_later_does_not_change_the_order(self, db, user, plan, bigger_plan):
        order = billing.build_order(user, [CartItem(kind=ItemKind.NEW, plan_id=plan.id)])
        original_total = order.total_cents

        # Simulate the attack: add an expensive item after the order exists.
        billing.build_order(user, [CartItem(kind=ItemKind.NEW, plan_id=bigger_plan.id)])

        db.session.refresh(order)
        assert order.total_cents == original_total
        assert len(order.items) == 1


class TestAmountVerification:
    """C-4: the captured amount must match the order."""

    def test_underpayment_is_rejected(self, db, user, plan):
        order = billing.build_order(user, [CartItem(kind=ItemKind.NEW, plan_id=plan.id)])
        with pytest.raises(PaymentError):
            billing.record_payment(order, _captured(order, amount_cents=1))  # the $0.01 attack
        assert order.status == OrderStatus.PENDING

    def test_exact_payment_is_accepted(self, db, user, plan):
        order = billing.build_order(user, [CartItem(kind=ItemKind.NEW, plan_id=plan.id)])
        payment = billing.record_payment(order, _captured(order))
        assert payment.amount_cents == order.total_cents
        assert order.status == OrderStatus.PAID

    def test_currency_mismatch_is_rejected(self, db, user, plan):
        order = billing.build_order(user, [CartItem(kind=ItemKind.NEW, plan_id=plan.id)])
        captured = CapturedPayment(
            provider="stripe",
            reference="r",
            amount_cents=order.total_cents,
            currency="EUR",
            status="paid",
            order_public_id=order.public_id,
        )
        with pytest.raises(PaymentError):
            billing.record_payment(order, captured)

    def test_payment_for_a_different_order_is_rejected(self, db, user, plan):
        order_a = billing.build_order(user, [CartItem(kind=ItemKind.NEW, plan_id=plan.id)])
        order_b = billing.build_order(user, [CartItem(kind=ItemKind.NEW, plan_id=plan.id)])
        captured = _captured(order_a)
        with pytest.raises(PaymentError):
            billing.record_payment(order_b, captured)


class TestReplayProtection:
    """C-5: a provider reference may be redeemed exactly once."""

    def test_same_reference_cannot_pay_a_second_order(self, db, user, plan):
        order_one = billing.build_order(user, [CartItem(kind=ItemKind.NEW, plan_id=plan.id)])
        billing.record_payment(order_one, _captured(order_one, reference="reused"))

        order_two = billing.build_order(user, [CartItem(kind=ItemKind.NEW, plan_id=plan.id)])
        replay = CapturedPayment(
            provider="stripe",
            reference="reused",
            amount_cents=order_two.total_cents,
            currency="USD",
            status="paid",
            order_public_id=order_two.public_id,
        )
        with pytest.raises(PaymentError):
            billing.record_payment(order_two, replay)
        assert order_two.status == OrderStatus.PENDING

    def test_redelivering_the_same_payment_is_idempotent(self, db, user, plan):
        order = billing.build_order(user, [CartItem(kind=ItemKind.NEW, plan_id=plan.id)])
        first = billing.record_payment(order, _captured(order, reference="dup"))
        second = billing.record_payment(order, _captured(order, reference="dup"))
        assert first.id == second.id
        assert Payment.query.count() == 1


class TestCouponRules:
    """M-25: coupons cannot produce negative or unbounded discounts."""

    def test_discount_is_clamped_to_100_percent(self, db, user, plan, coupon):
        coupon.discount_percent = 500.0
        db.session.commit()
        order = billing.build_order(
            user, [CartItem(kind=ItemKind.NEW, plan_id=plan.id)], coupon_code="FLUX10"
        )
        assert order.total_cents == 0
        assert order.discount_cents == order.subtotal_cents

    def test_expired_coupon_is_refused(self, db, user, plan, coupon):
        from datetime import timedelta

        from fluxweb.models.billing import utcnow

        coupon.expires_at = utcnow() - timedelta(days=1)
        db.session.commit()
        with pytest.raises(DomainError):
            billing.resolve_coupon("FLUX10")

    def test_redemption_limit_is_enforced(self, db, coupon):
        coupon.max_redemptions = 1
        coupon.times_redeemed = 1
        db.session.commit()
        with pytest.raises(DomainError):
            billing.resolve_coupon("FLUX10")

    def test_unknown_coupon_is_refused(self, db):
        with pytest.raises(DomainError):
            billing.resolve_coupon("NOT-A-REAL-CODE")


class TestUpgradePricing:
    """M-22: upgrades must be same-game and strictly more expensive."""

    def test_cheaper_plan_with_better_specs_is_refused(self, db, server, cheap_big_plan):
        with pytest.raises(ValidationError):
            billing.validate_upgrade(server, cheap_big_plan)

    def test_cross_game_upgrade_is_refused(self, db, server, plan):
        from fluxweb.models import GamePlan

        other = GamePlan(game="hytale", name="Hytale Pro", price=99.0, memory=8192, cpu=300, disk=1024)
        db.session.add(other)
        db.session.commit()
        with pytest.raises(ValidationError):
            billing.validate_upgrade(server, other)

    def test_legitimate_upgrade_is_priced_as_the_difference(self, db, user, server, bigger_plan):
        order = billing.build_order(
            user, [CartItem(kind=ItemKind.UPGRADE, plan_id=bigger_plan.id, server_id=server.id)]
        )
        assert order.total_cents == 1080 - 720


class TestMoneyRounding:
    """H-14: no truncation when converting to cents."""

    def test_no_truncation_on_awkward_totals(self):
        from fluxweb.money import to_cents

        assert to_cents(1.15) == 115  # int(1.15 * 100) would give 114
        assert to_cents(10.80) == 1080
        assert to_cents(0.1 + 0.2) == 30

    def test_discount_never_exceeds_subtotal(self):
        from fluxweb.money import apply_percentage_discount

        assert apply_percentage_discount(1000, 150) == 1000
        assert apply_percentage_discount(1000, -5) == 0

    def test_gateway_fee_gross_up_covers_percentage_and_fixed_fee(self):
        from fluxweb.money import gateway_fee_cents

        fee = gateway_fee_cents(720, 2.9, 30)
        assert fee == 53
        assert (720 + fee) * 0.029 + 30 <= fee + 1


class TestGatewayFees:
    def test_stripe_fee_is_frozen_on_order(self, db, user, plan):
        order = billing.build_order(
            user, [CartItem(kind=ItemKind.NEW, plan_id=plan.id)], payment_provider="stripe"
        )
        assert order.payment_provider == "stripe"
        assert order.gateway_fee_cents == 53
        assert order.total_cents == 773

    def test_paypal_fee_is_frozen_on_order(self, db, user, plan):
        order = billing.build_order(
            user, [CartItem(kind=ItemKind.NEW, plan_id=plan.id)], payment_provider="paypal"
        )
        assert order.payment_provider == "paypal"
        assert order.gateway_fee_cents == 77
        assert order.total_cents == 797


class TestOwnershipOnOrders:
    def test_cannot_renew_another_users_server(self, db, other_user, server, plan):
        with pytest.raises(ValidationError):
            billing.build_order(
                other_user, [CartItem(kind=ItemKind.RENEWAL, plan_id=plan.id, server_id=server.id)]
            )
