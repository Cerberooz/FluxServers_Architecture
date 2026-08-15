"""Cart, coupons, renewals, and upgrades.

Prices are never read from the request or the cookie; every figure shown here
is recomputed from the database (audit C-6, M-22).
"""

from __future__ import annotations

import re

from flask import Blueprint, current_app, flash, jsonify, redirect, render_template, request, url_for

from fluxweb.errors import AuthorizationError, DomainError
from fluxweb.extensions import limiter
from fluxweb.models import GamePlan, ItemKind
from fluxweb.integrations.fluid import get_fluid_client
from fluxweb.services import billing
from fluxweb.services import cart as cart_service
from fluxweb.services.cart import CartItem
from fluxweb.web.helpers import current_user, get_owned_server, login_required

bp = Blueprint("cart", __name__)


def _node_display_label(name: str, location: str | None) -> str:
    name = (name or "").strip()
    location = (location or "").strip()
    if name and location:
        return f"{name} - {location}"
    return name or location


def _brief_description(value: str | None, *, fallback: str = "Server software option") -> str:
    text = re.sub(r"\s+", " ", value or "").strip()
    if not text:
        return fallback

    first_sentence = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0].strip()
    candidate = first_sentence if first_sentence else text
    if len(candidate) <= 95:
        return candidate

    return candidate[:92].rstrip(" ,.;:-") + "..."


def _country_code_from_location(value: str | None) -> str:
    location = (value or "").lower()
    countries = {
        "australia": "au",
        "brazil": "br",
        "canada": "ca",
        "france": "fr",
        "germany": "de",
        "hong kong": "hk",
        "india": "in",
        "japan": "jp",
        "netherlands": "nl",
        "poland": "pl",
        "singapore": "sg",
        "south korea": "kr",
        "sweden": "se",
        "united kingdom": "gb",
        "uk": "gb",
        "united states": "us",
        "usa": "us",
    }
    for country, code in countries.items():
        if country in location:
            return code
    return ""


def _totals_payload() -> dict:
    items = cart_service.get_cart()
    quote = billing.quote(items, cart_service.get_coupon_code())
    base_total_cents = int(quote["total_cents"])
    payments = current_app.extensions["flux_config"].payments
    payment_options = {
        provider: {
            "fee": round(payments.gateway_fee_cents(provider, base_total_cents) / 100, 2),
            "total": round((base_total_cents + payments.gateway_fee_cents(provider, base_total_cents)) / 100, 2),
        }
        for provider, enabled in (("paypal", payments.paypal_enabled), ("stripe", payments.stripe_enabled))
        if enabled
    }
    return {
        "cart_count": len(items),
        "subtotal": round(int(quote["subtotal_cents"]) / 100, 2),
        "discount_amount": round(int(quote["discount_cents"]) / 100, 2),
        "total": round(int(quote["total_cents"]) / 100, 2),
        "payment_options": payment_options,
    }


def _egg_options_for_plan(plan: GamePlan) -> list[dict]:
    """Customer-facing egg choices with real panel names when available.

    Older plans may have a legacy/text `nest_id`, so we first try the stored
    nest when it is numeric, then safely search all panel nests for the allowed
    egg IDs. The checkout still submits the authoritative egg ID; the UI just
    avoids leaking internal labels like "Egg 1" when the panel can tell us the
    real name, e.g. Paper.
    """
    allowed_ids = plan.allowed_eggs
    if not allowed_ids:
        return []

    by_id: dict[int, dict] = {}

    try:
        client = get_fluid_client()
        nest_ids: list[int] = []
        if str(plan.nest_id or "").isdigit():
            nest_ids.append(int(plan.nest_id))
        for nest in client.list_nests():
            try:
                nest_id = int(nest.get("attributes", {}).get("id"))
            except (TypeError, ValueError):
                continue
            if nest_id not in nest_ids:
                nest_ids.append(nest_id)

        wanted = set(allowed_ids)
        for nest_id in nest_ids:
            for egg in client.eggs_for_nest(nest_id):
                attrs = egg.get("attributes", {})
                try:
                    egg_id = int(attrs.get("id"))
                except (TypeError, ValueError):
                    continue
                if egg_id in wanted and egg_id not in by_id:
                    by_id[egg_id] = {
                        "id": egg_id,
                        "name": attrs.get("name") or f"Software #{egg_id}",
                        "description": _brief_description(attrs.get("description")),
                    }
            if len(by_id) == len(wanted):
                break
    except Exception:
        by_id = {}

    return [
        by_id.get(egg_id, {"id": egg_id, "name": f"Software #{egg_id}", "description": "Server software option"})
        for egg_id in allowed_ids
    ]


def _node_options_for_plan(plan: GamePlan) -> list[dict]:
    allowed_ids = plan.allowed_node_ids
    if not allowed_ids:
        return []

    by_id: dict[int, dict] = {}
    try:
        client = get_fluid_client()
        wanted = set(allowed_ids)
        for node in client.list_nodes():
            attrs = node.get("attributes", {})
            try:
                node_id = int(attrs.get("id"))
            except (TypeError, ValueError):
                continue
            if node_id in wanted:
                name = attrs.get("name") or f"Node {node_id}"
                location = attrs.get("location_label") or attrs.get("long") or ""
                country_code = _country_code_from_location(location)
                capacity = attrs.get("capacity") or {}
                available = client.node_fits(attrs, memory=plan.memory, disk=plan.disk)
                reason = ""
                if not available:
                    if capacity.get("maintenance"):
                        reason = "The node is in maintenance mode."
                    elif not capacity.get("public"):
                        reason = "The node is not enabled for public deployments."
                    else:
                        shortages = []
                        memory_free = int(capacity.get("memory_free") or 0)
                        disk_free = int(capacity.get("disk_free") or 0)
                        if memory_free < plan.memory:
                            shortages.append(f"needs {plan.memory} MB RAM, but only {memory_free} MB is free")
                        if disk_free < plan.disk:
                            shortages.append(f"needs {plan.disk} MB disk, but only {disk_free} MB is free")
                        reason = "; ".join(shortages) or "The panel marked this node as unavailable."
                by_id[node_id] = {
                    "id": node_id,
                    "name": name,
                    "label": _node_display_label(name, location) or f"Node {node_id}",
                    "location": location,
                    "country_code": country_code,
                    "flag_url": f"https://flagcdn.com/w40/{country_code}.png" if country_code else "",
                    "fqdn": attrs.get("fqdn") or "",
                    "availability_known": True,
                    "available": available,
                    "unavailability_reason": reason,
                    "memory_free": capacity.get("memory_free"),
                    "disk_free": capacity.get("disk_free"),
                }
    except Exception:
        by_id = {}

    return [
        by_id.get(
            node_id,
            {
                "id": node_id,
                "name": f"Node {node_id}",
                "label": f"Node {node_id}",
                "location": "",
                "country_code": "",
                "flag_url": "",
                "fqdn": "",
                "availability_known": False,
                "available": False,
                "unavailability_reason": "The panel capacity could not be verified.",
                "memory_free": None,
                "disk_free": None,
            },
        )
        for node_id in allowed_ids
    ]


def _enrich_configuration_labels(items: list[dict]) -> list[dict]:
    for item in items:
        if item.get("kind") != ItemKind.NEW:
            continue
        plan = GamePlan.query.get(item.get("plan_id"))
        if plan is None:
            continue

        node_labels = {option["id"]: option.get("label") or option["name"] for option in _node_options_for_plan(plan)}
        egg_labels = {option["id"]: option["name"] for option in _egg_options_for_plan(plan)}
        item["node_name"] = node_labels.get(item.get("node_id")) or f"Node {item.get('node_id')}"
        item["egg_name"] = egg_labels.get(item.get("egg_id")) or f"Software #{item.get('egg_id')}"

    return items


@bp.route("/cart")
def view_cart():
    items = cart_service.get_cart()
    described = _enrich_configuration_labels(cart_service.describe_for_template(items))
    quote = billing.quote(items, cart_service.get_coupon_code())
    discount_percent = 0.0
    if quote["coupon_code"] and quote["subtotal_cents"]:
        discount_percent = round(int(quote["discount_cents"]) / int(quote["subtotal_cents"]) * 100, 2)

    return render_template(
        "cart.html",
        cart=described,
        subtotal=round(int(quote["subtotal_cents"]) / 100, 2),
        discount_percent=discount_percent,
        discount_amount=round(int(quote["discount_cents"]) / 100, 2),
        total=round(int(quote["total_cents"]) / 100, 2),
        payment_options=_totals_payload()["payment_options"],
        coupon_code=quote["coupon_code"],
        requires_verification=bool(current_user() and not current_user().email_verified),
    )


@bp.route("/add-to-cart/<int:plan_id>", methods=["POST"])
@limiter.limit("60 per hour")
def add_to_cart(plan_id: int):
    plan = GamePlan.query.get(plan_id)
    if plan is None:
        return jsonify({"status": "error", "message": "Plan not found"}), 404

    item = CartItem(
        kind=ItemKind.NEW,
        plan_id=plan.id,
        software="nodejs" if plan.game == "discord_bot" else None,
    )
    if not cart_service.add_item(item):
        return jsonify({"status": "error", "message": "Your cart is full."}), 400

    return jsonify({"status": "success", "message": "Item added to cart", **_totals_payload()})


@bp.route("/plans/<int:plan_id>/customize", methods=["GET", "POST"])
def customize_plan(plan_id: int):
    plan = GamePlan.query.get(plan_id)
    if plan is None:
        flash("Plan not found.", "error")
        return redirect(url_for("public.index"))

    eggs = _egg_options_for_plan(plan)
    nodes = _node_options_for_plan(plan)
    has_available_node = any(node.get("available", False) for node in nodes)

    if request.method == "POST":
        try:
            node_id, egg_id = int(request.form.get("node_id", "")), int(request.form.get("egg_id", ""))
        except ValueError:
            flash("Choose both a location and an egg.", "error")
            return render_template("customize_plan.html", plan=plan, eggs=eggs, nodes=nodes, has_available_node=has_available_node), 400
        if node_id not in plan.allowed_node_ids or egg_id not in plan.allowed_eggs:
            flash("That configuration is no longer available for this plan.", "error")
            return render_template("customize_plan.html", plan=plan, eggs=eggs, nodes=nodes, has_available_node=has_available_node), 400
        selected_node = next((node for node in nodes if node["id"] == node_id), None)
        if selected_node is None or not selected_node.get("availability_known"):
            flash("We could not confirm capacity for that location. Please try again shortly.", "error")
            return render_template("customize_plan.html", plan=plan, eggs=eggs, nodes=nodes, has_available_node=has_available_node), 503
        if not selected_node.get("available"):
            flash("That location no longer has enough capacity for this plan. Choose another location.", "error")
            return render_template("customize_plan.html", plan=plan, eggs=eggs, nodes=nodes, has_available_node=has_available_node), 400
        if not cart_service.add_item(CartItem(kind=ItemKind.NEW, plan_id=plan.id, node_id=node_id, egg_id=egg_id)):
            flash("Your cart is full.", "error")
            return redirect(url_for("cart.view_cart"))
        return redirect(url_for("cart.view_cart"))

    return render_template("customize_plan.html", plan=plan, eggs=eggs, nodes=nodes, has_available_node=has_available_node)


@bp.route("/remove-from-cart/<int:index>", methods=["POST"])
def remove_from_cart(index: int):
    if not cart_service.remove_index(index):
        return jsonify({"status": "error", "message": "Invalid index"}), 400
    return jsonify({"status": "success", **_totals_payload()})


@bp.route("/update-cart-item/<int:index>", methods=["POST"])
def update_cart_item(index: int):
    data = request.get_json(silent=True) or {}
    if "software" not in data:
        return jsonify({"status": "error", "message": "Nothing to update"}), 400
    if not cart_service.set_software(index, data.get("software")):
        return jsonify({"status": "error", "message": "Invalid request"}), 400
    return jsonify({"status": "success"})


@bp.route("/apply-coupon", methods=["POST"])
@limiter.limit("10 per hour")
def apply_coupon():
    """Rate limited so coupon codes cannot be enumerated (audit H-10)."""
    payload = request.get_json(silent=True) or {}
    code = (payload.get("code") or request.form.get("code") or "").strip()

    try:
        coupon = billing.resolve_coupon(code)
    except DomainError as exc:
        return jsonify({"status": "error", "message": exc.user_message}), 400
    if coupon is None:
        return jsonify({"status": "error", "message": "Invalid coupon"}), 400

    cart_service.set_coupon(coupon.code)
    return jsonify(
        {
            "status": "success",
            "code": coupon.code,
            "discount_percent": coupon.safe_discount_percent,
            **_totals_payload(),
        }
    )


@bp.route("/remove-coupon", methods=["POST"])
def remove_coupon():
    cart_service.set_coupon(None)
    return jsonify({"status": "success", **_totals_payload()})


@bp.route("/renew/<int:server_id>", methods=["POST"])
@login_required
def renew_server(server_id: int):
    try:
        server = get_owned_server(server_id)
    except AuthorizationError as exc:
        flash(exc.user_message, "error")
        return redirect(url_for("account.user_account"))

    plan = GamePlan.query.get(server.plan_id) if server.plan_id else None
    if plan is None:
        flash("The original plan no longer exists. Please choose a new one.", "error")
        return redirect(url_for("public.index"))

    cart_service.add_item(CartItem(kind=ItemKind.RENEWAL, plan_id=plan.id, server_id=server.id))
    flash(f"Renewal for {server.pelican_server_identifier} added to cart.", "success")
    return redirect(url_for("cart.view_cart"))


@bp.route("/upgrade/<int:server_id>")
@login_required
def upgrade_server_view(server_id: int):
    try:
        server = get_owned_server(server_id)
    except AuthorizationError as exc:
        flash(exc.user_message, "error")
        return redirect(url_for("account.user_account"))

    current_plan = GamePlan.query.get(server.plan_id) if server.plan_id else None
    if current_plan is None:
        flash("Current plan info missing. Cannot upgrade.", "error")
        return redirect(url_for("account.user_account"))

    upgrade_plans = (
        GamePlan.query.filter(GamePlan.game == current_plan.game, GamePlan.price > current_plan.price)
        .order_by(GamePlan.price.asc())
        .all()
    )
    return render_template(
        "upgrade.html", server=server, current_plan=current_plan, upgrade_plans=upgrade_plans
    )


@bp.route("/add-upgrade-to-cart/<int:server_id>/<int:plan_id>", methods=["POST"])
@login_required
def add_upgrade_to_cart(server_id: int, plan_id: int):
    try:
        server = get_owned_server(server_id)
    except AuthorizationError as exc:
        return jsonify({"status": "error", "message": exc.user_message}), 403

    new_plan = GamePlan.query.get(plan_id)
    if new_plan is None:
        return jsonify({"status": "error", "message": "Plan not found"}), 404

    # Same-game and strictly-more-expensive are enforced here, not just in the
    # template that renders the options (audit M-22).
    try:
        billing.validate_upgrade(server, new_plan)
    except DomainError as exc:
        return jsonify({"status": "error", "message": exc.user_message}), 400

    cart_service.add_item(CartItem(kind=ItemKind.UPGRADE, plan_id=new_plan.id, server_id=server.id))
    return jsonify({"status": "success", "message": "Upgrade added to cart", **_totals_payload()})
