"""Money handling.

All arithmetic is done in integer cents. The previous code used floats and
``int(total * 100)``, which truncates: a $1.15 total became 114 cents
(audit H-14). Prices are still stored as ``Float`` on ``GamePlan`` for
backwards compatibility, so conversion happens at exactly one boundary.
"""

from __future__ import annotations

from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal

CENTS = Decimal("0.01")


def to_cents(amount: float | int | str | Decimal | None) -> int:
    """Convert a currency amount to integer cents, rounding half up."""
    if amount is None:
        return 0
    value = Decimal(str(amount))
    return int((value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def to_decimal(cents: int) -> Decimal:
    """Convert integer cents back to a 2dp Decimal."""
    return (Decimal(cents) / 100).quantize(CENTS, rounding=ROUND_HALF_UP)


def format_amount(cents: int) -> str:
    """Render integer cents as a plain '12.34' string for payment APIs."""
    return f"{to_decimal(cents):.2f}"


def apply_percentage_discount(subtotal_cents: int, percent: float) -> int:
    """Return the discount in cents for ``percent`` off ``subtotal_cents``.

    The percentage is clamped to 0-100 so a mis-entered coupon can never
    produce a negative total (audit M-25).
    """
    pct = Decimal(str(max(0.0, min(100.0, float(percent)))))
    discount = (Decimal(subtotal_cents) * pct / 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(min(Decimal(subtotal_cents), discount))


def gateway_fee_cents(net_cents: int, percent: float, fixed_cents: int) -> int:
    """Gross up a charge so the merchant still receives ``net_cents``."""
    net = Decimal(max(0, int(net_cents)))
    rate = Decimal(str(percent)) / Decimal("100")
    fixed = Decimal(max(0, int(fixed_cents)))
    if net == 0:
        return 0
    if rate < 0 or rate >= 1:
        raise ValueError("Gateway fee percentage must be between 0 and 100.")
    gross = ((net + fixed) / (Decimal("1") - rate)).quantize(Decimal("1"), rounding=ROUND_CEILING)
    return max(0, int(gross - net))
