"""Cart handling.

The cart still lives in the signed session cookie, but it now stores **only
identifiers** — never prices. Every amount is recomputed from the database when
the order snapshot is built, so a tampered or stale cookie cannot change what
anything costs.

Moving the cart into its own table is the follow-up (audit M-23 / SC-5); this
change removes the money from it in the meantime.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from flask import session

from fluxweb.models import GamePlan, ItemKind

CART_KEY = "cart"
COUPON_KEY = "coupon_code"
MAX_ITEMS = 20


@dataclass
class CartItem:
    kind: str = ItemKind.NEW
    plan_id: int | None = None
    server_id: int | None = None
    software: str | None = None
    node_id: int | None = None
    egg_id: int | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> CartItem | None:
        """Parse one stored entry, tolerating rows written by the old code."""
        if not isinstance(raw, dict):
            return None
        plan_id = raw.get("plan_id")
        try:
            plan_id = int(plan_id) if plan_id is not None else None
        except (TypeError, ValueError):
            return None
        if plan_id is None:
            return None

        server_id = raw.get("server_id")
        try:
            server_id = int(server_id) if server_id is not None else None
        except (TypeError, ValueError):
            server_id = None

        kind = raw.get("kind") or raw.get("type") or ItemKind.NEW
        if kind not in {ItemKind.NEW, ItemKind.RENEWAL, ItemKind.UPGRADE}:
            kind = ItemKind.NEW

        software = raw.get("software")
        if software not in {None, "nodejs", "python"}:
            software = None

        def positive_int(name: str) -> int | None:
            try:
                value = int(raw.get(name))
                return value if value > 0 else None
            except (TypeError, ValueError):
                return None

        return cls(kind=kind, plan_id=plan_id, server_id=server_id, software=software, node_id=positive_int("node_id"), egg_id=positive_int("egg_id"))


def get_cart() -> list[CartItem]:
    raw_items = session.get(CART_KEY, [])
    if not isinstance(raw_items, list):
        return []
    items = []
    for raw in raw_items[:MAX_ITEMS]:
        item = CartItem.from_dict(raw)
        if item is not None:
            items.append(item)
    return items


def save_cart(items: list[CartItem]) -> None:
    session[CART_KEY] = [asdict(item) for item in items[:MAX_ITEMS]]
    session.permanent = True


def clear_cart() -> None:
    session.pop(CART_KEY, None)
    session.pop(COUPON_KEY, None)


def add_item(item: CartItem) -> bool:
    """Append an item. Returns False when the cart is full."""
    items = get_cart()
    if len(items) >= MAX_ITEMS:
        return False
    if item.kind == ItemKind.UPGRADE:
        # Only one upgrade per server may be queued.
        items = [i for i in items if not (i.kind == ItemKind.UPGRADE and i.server_id == item.server_id)]
    items.append(item)
    save_cart(items)
    return True


def remove_index(index: int) -> bool:
    items = get_cart()
    if 0 <= index < len(items):
        items.pop(index)
        save_cart(items)
        return True
    return False


def set_software(index: int, software: str | None) -> bool:
    if software not in {None, "nodejs", "python"}:
        return False
    items = get_cart()
    if 0 <= index < len(items):
        items[index].software = software
        save_cart(items)
        return True
    return False


def set_coupon(code: str | None) -> None:
    if code:
        session[COUPON_KEY] = code
    else:
        session.pop(COUPON_KEY, None)
    session.permanent = True


def get_coupon_code() -> str | None:
    code = session.get(COUPON_KEY)
    return code if isinstance(code, str) else None


def describe_for_template(items: list[CartItem]) -> list[dict[str, Any]]:
    """Render cart entries for display, pricing them from the database."""
    from fluxweb.models import ServerRecord
    from fluxweb.services import billing

    described = []
    for index, item in enumerate(items):
        plan = GamePlan.query.get(item.plan_id) if item.plan_id else None
        if plan is None:
            continue
        price_cents = billing.line_price_cents(item, plan)
        name = plan.name
        if item.kind == ItemKind.RENEWAL:
            name = f"Renewal: {plan.name}"
        elif item.kind == ItemKind.UPGRADE:
            server = ServerRecord.query.get(item.server_id) if item.server_id else None
            label = server.pelican_server_identifier if server else "server"
            name = f"Upgrade: {label} -> {plan.name}"
        described.append(
            {
                "index": index,
                "kind": item.kind,
                "type": item.kind,  # legacy key still read by templates
                "plan_id": plan.id,
                "server_id": item.server_id,
                "name": name,
                "game": plan.game,
                "software": item.software,
                "node_id": item.node_id,
                "egg_id": item.egg_id,
                "price": round(price_cents / 100, 2),
                "price_cents": price_cents,
            }
        )
    return described
