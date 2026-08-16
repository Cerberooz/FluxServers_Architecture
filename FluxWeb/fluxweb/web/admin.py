"""Admin dashboard.

Access is by the ``User.is_admin`` flag (with the configured ADMIN_EMAIL as a
first-deploy bootstrap), not by a bare email-string comparison scattered across
routes (audit H-9, S-2).
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
from types import SimpleNamespace

from flask import (
    Blueprint,
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

from fluxweb.errors import ConfigurationError, PanelError
from fluxweb.extensions import db
from fluxweb.integrations.fluid import get_fluid_client
from fluxweb.models import (
    FAQ,
    Announcement,
    Coupon,
    GamePlan,
    GlobeLocation,
    MaintenanceUpdate,
    Order,
    PlanCategory,
    PlanSubcategory,
    ReferralCode,
    ServerRecord,
    ServiceStatus,
    User,
)
from fluxweb.web.helpers import admin_required

log = logging.getLogger(__name__)

bp = Blueprint("admin", __name__, url_prefix="/admin")

ALLOWED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_IMAGE_BYTES = 512 * 1024
PAGE_SIZE = 100


def _slugify(value: str, *, fallback: str = "category") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower()).strip("-")
    return slug or fallback


def _unique_category_slug(name: str) -> str:
    base = _slugify(name)
    slug = base
    suffix = 2
    while PlanCategory.query.filter_by(slug=slug).first() is not None:
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


def _unique_subcategory_slug(category_id: int, name: str) -> str:
    base = _slugify(name, fallback="subcategory")
    slug = base
    suffix = 2
    while PlanSubcategory.query.filter_by(category_id=category_id, slug=slug).first() is not None:
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


def _plan_categories() -> list[PlanCategory]:
    return PlanCategory.query.order_by(PlanCategory.sort_order.asc(), PlanCategory.name.asc()).all()


def _subcategories_by_category(categories: list[PlanCategory]) -> dict[int, list[PlanSubcategory]]:
    return {category.id: list(category.subcategories) for category in categories}


def _subcategory_payload(categories: list[PlanCategory]) -> dict[str, list[dict[str, object]]]:
    return {
        str(category.id): [
            {"id": subcategory.id, "name": subcategory.name}
            for subcategory in category.subcategories
            if subcategory.is_active
        ]
        for category in categories
    }


def _plan_tree(page_plans: list[GamePlan], categories: list[PlanCategory]) -> list[dict[str, object]]:
    category_ids = {category.id for category in categories}
    tree: list[dict[str, object]] = []

    for category in categories:
        category_plans = [plan for plan in page_plans if plan.category_id == category.id]
        subcategory_ids = {subcategory.id for subcategory in category.subcategories}
        subcategories = []

        for subcategory in category.subcategories:
            plans = [
                plan
                for plan in category_plans
                if plan.subcategory_id == subcategory.id
            ]
            subcategories.append({"subcategory": subcategory, "plans": plans})

        direct_plans = [
            plan
            for plan in category_plans
            if plan.subcategory_id is None or plan.subcategory_id not in subcategory_ids
        ]

        tree.append(
            {
                "category": category,
                "plans": category_plans,
                "direct_plans": direct_plans,
                "subcategories": subcategories,
            }
        )

    uncategorized = [plan for plan in page_plans if plan.category_id not in category_ids]
    tree.append(
        {
            "category": None,
            "plans": uncategorized,
            "direct_plans": uncategorized,
            "subcategories": [],
        }
    )

    return tree


def _sniff_image(data: bytes) -> str | None:
    """Identify an image by its magic bytes.

    Hand-rolled rather than using ``imghdr``, which was removed from the
    standard library in Python 3.13 and would break the app on import.
    """
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _int(name: str, default: int = 0) -> int:
    """Parse an integer form field without raising a 500 (audit M-24)."""
    raw = request.form.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float = 0.0) -> float:
    raw = request.form.get(name)
    if raw is None or raw == "":
        return default
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _int_value(value, default: int = 0) -> int:
    if value is None or value == "":
        return default
    return int(value)


def _bool_value(value) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _feature_list(value) -> list[str]:
    if isinstance(value, list):
        return [str(feature).strip() for feature in value if str(feature).strip()]
    if isinstance(value, str):
        return [feature.strip() for feature in value.splitlines() if feature.strip()]
    return []


def _int_list(values) -> list[int]:
    if isinstance(values, str):
        values = [part.strip() for part in values.replace("\r", "").replace(",", "\n").splitlines()]
    cleaned: list[int] = []
    for value in values or []:
        if value is None or value == "":
            continue
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed > 0 and parsed not in cleaned:
            cleaned.append(parsed)
    return cleaned


def _page_arg(name: str, default: int = 1) -> int:
    try:
        value = int(request.args.get(name, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _admin_dashboard_page_url(active_tab: str, page_arg: str, page_num: int) -> str:
    return url_for("admin.admin_dashboard", tab=active_tab, **{page_arg: page_num})


def _read_image(field: str) -> str | None:
    """Validate and encode an uploaded image, or return None.

    Extension alone was previously trusted; the bytes are now sniffed and the
    size capped (audit H-17). Base64-in-the-database is retained for
    compatibility and is tracked separately as a performance fix (audit P-4).
    """
    file = request.files.get(field)
    if not file or not file.filename:
        return None

    _, ext = os.path.splitext(file.filename)
    ext = ext.lower()
    if ext not in ALLOWED_IMAGE_EXTENSIONS:
        raise ValueError("Only .png, .jpg, .jpeg, .gif and .webp images are allowed.")

    data = file.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError(f"Images must be smaller than {MAX_IMAGE_BYTES // 1024} KB.")
    if not data:
        return None

    sniffed = _sniff_image(data)
    if sniffed is None:
        raise ValueError("That file is not a valid image.")

    mime = "image/jpeg" if sniffed == "jpeg" else f"image/{sniffed}"
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def _read_panel_metadata() -> tuple[list[dict], list[dict]]:
    client = get_fluid_client()
    return client.list_nests(), client.list_nodes()


def _panel_metadata() -> tuple[list[dict], list[dict]]:
    """Panel nests and nodes, tolerating an unreachable panel."""
    try:
        return _read_panel_metadata()
    except (ConfigurationError, PanelError) as exc:
        log.warning("Panel metadata unavailable: %s", exc)
        return _fallback_panel_metadata()


def _fallback_panel_metadata() -> tuple[list[dict], list[dict]]:
    return [{"attributes": {"id": "General", "name": "General"}}], []


def _node_payload(node: dict) -> dict[str, object] | None:
    attrs = node.get("attributes", {})
    try:
        node_id = int(attrs.get("id"))
    except (TypeError, ValueError):
        return None

    short = attrs.get("short") or attrs.get("name") or f"Node {node_id}"
    long_name = attrs.get("long") or attrs.get("description") or attrs.get("location_label") or ""
    label = f"{short} ({long_name})" if long_name else str(short)
    return {"id": node_id, "name": short, "location": long_name, "label": label}


def _nest_payload(nest: dict) -> dict[str, object] | None:
    attrs = nest.get("attributes", {})
    nest_id = attrs.get("id")
    if nest_id is None:
        return None
    return {"id": nest_id, "name": attrs.get("name") or f"Nest {nest_id}"}


def _location_label_map(
    panel_locations: list[dict], extra_node_ids: list[int] | None = None
) -> dict[int, str]:
    labels: dict[int, str] = {}

    for loc in panel_locations:
        attrs = loc.get("attributes", {})
        try:
            node_id = int(attrs.get("id"))
        except (TypeError, ValueError):
            continue
        short = attrs.get("short") or attrs.get("name") or f"Node {node_id}"
        long_name = attrs.get("long") or attrs.get("description")
        labels[node_id] = f"{short} ({long_name})" if long_name else str(short)

    globe_by_id = {loc.id: loc.name for loc in GlobeLocation.query.order_by(GlobeLocation.name.asc()).all()}
    for node_id in extra_node_ids or []:
        if node_id in labels:
            continue
        globe_name = globe_by_id.get(node_id)
        labels[node_id] = f"{globe_name} (Node {node_id})" if globe_name else f"Node {node_id}"

    return dict(sorted(labels.items(), key=lambda item: item[1].lower()))


# --- dashboard ----------------------------------------------------------
@bp.route("")
@bp.route("/")
@admin_required
def admin_dashboard():
    plan_categories = _plan_categories()
    plan_subcategories_by_category = _subcategories_by_category(plan_categories)
    active_tab = (request.args.get("tab") or "users").strip().lower()
    valid_tabs = {
        "users",
        "servers",
        "plans",
        "referrals",
        "status",
        "maintenance",
        "faqs",
        "coupons",
    }
    if active_tab not in valid_tabs:
        active_tab = "users"

    # The plans admin view is a hierarchy, so pagination must not happen at the
    # raw plan-row level. Doing that splits one category across multiple pages
    # and rebuilds a partial tree each time.
    plan_items = GamePlan.query.order_by(
        GamePlan.game.asc(), GamePlan.serial_number.asc(), GamePlan.name.asc()
    ).all()
    nests, locations = _fallback_panel_metadata()
    plans = SimpleNamespace(
        items=plan_items,
        total=len(plan_items),
        page=1,
        pages=1,
        has_prev=False,
        has_next=False,
    )
    plan_options = plan_items
    known_node_ids: list[int] = []
    for plan in plan_options:
        for node_id in plan.allowed_node_ids:
            if node_id not in known_node_ids:
                known_node_ids.append(node_id)
    if not known_node_ids:
        known_node_ids.append(1)
    location_labels = _location_label_map(locations, known_node_ids)

    return render_template(
        "admin/admin.html",
        active_ann=Announcement.query.filter_by(active=True).first(),
        services=ServiceStatus.query.all(),
        updates=MaintenanceUpdate.query.order_by(MaintenanceUpdate.created_at.desc()).paginate(
            page=_page_arg("updates_page"), per_page=20, error_out=False
        ),
        plans=plans,
        plan_options=plan_options,
        faqs=FAQ.query.order_by(FAQ.order.asc(), FAQ.id.asc()).paginate(
            page=_page_arg("faqs_page"), per_page=20, error_out=False
        ),
        globe_locations=GlobeLocation.query.all(),
        coupons=Coupon.query.order_by(Coupon.id.desc()).paginate(
            page=_page_arg("coupons_page"), per_page=20, error_out=False
        ),
        servers=ServerRecord.query.order_by(ServerRecord.created_at.desc()).paginate(
            page=_page_arg("servers_page"), per_page=20, error_out=False
        ),
        all_users=User.query.order_by(User.created_at.desc()).paginate(
            page=_page_arg("users_page"), per_page=20, error_out=False
        ),
        recent_orders=Order.query.order_by(Order.created_at.desc()).limit(PAGE_SIZE).all(),
        stats={
            "total_servers": ServerRecord.query.count(),
            "total_users": User.query.count(),
            "total_orders": Order.query.count(),
        },
        nests=nests,
        locations=locations,
        referrals=ReferralCode.query.order_by(ReferralCode.created_at.desc()).paginate(
            page=_page_arg("referrals_page"), per_page=20, error_out=False
        ),
        plan_categories=plan_categories,
        plan_subcategories_by_category=plan_subcategories_by_category,
        plan_subcategory_options=_subcategory_payload(plan_categories),
        plan_tree=_plan_tree(plan_items, plan_categories),
        location_labels=location_labels,
        active_tab=active_tab,
        admin_page_url=_admin_dashboard_page_url,
    )


@bp.route("/api/panel-metadata")
@admin_required
def admin_api_panel_metadata():
    try:
        nests, locations = _read_panel_metadata()
    except (ConfigurationError, PanelError) as exc:
        log.warning("Panel metadata unavailable: %s", exc)
        return jsonify({"status": "error", "nests": [], "locations": [], "message": "Fluid API unavailable"}), 502
    except Exception as exc:  # pragma: no cover
        log.warning("Unexpected panel metadata failure: %s", exc)
        return jsonify({"status": "error", "nests": [], "locations": []}), 502

    return jsonify(
        {
            "status": "success",
            "nests": [item for item in (_nest_payload(nest) for nest in nests) if item is not None],
            "locations": [item for item in (_node_payload(node) for node in locations) if item is not None],
        }
    )


@bp.route("/pelican-test")
@bp.route("/pterodactyl-test")
@bp.route("/fluid-test")
@admin_required
def admin_pelican_test():
    """Check connectivity to the game panel.

    This endpoint is on *this* server, so the browser's request goes to this
    site. The call to the panel is made server-to-server from here, and never
    appears in the browser's network tab. That is deliberate: the application
    API key is a panel-wide admin credential and must never reach a browser.

    The panel URL is reported back so it is obvious which host was contacted.
    """
    client = get_fluid_client()
    target = f"{client.base_url}/api/application/users" if client.base_url else "(no panel URL configured)"
    panel_url = client.base_url or ""

    result = {
        "application": {"status": "not_checked"},
        "metadata": {"status": "not_checked"},
        "client": {"status": "not_checked"},
    }

    try:
        client.ping()
        result["application"] = {"status": "ok"}
    except ConfigurationError as exc:
        result["application"] = {"status": "not_configured", "message": str(exc)}
    except PanelError as exc:
        result["application"] = {
            "status": "rejected" if exc.status in (401, 403) else "unreachable" if exc.status is None else "error",
            "http_status": exc.status,
        }

    if result["application"]["status"] == "ok":
        try:
            result["metadata"] = {"status": "ok", **client.check_metadata()}
        except PanelError as exc:
            result["metadata"] = {
                "status": "rejected" if exc.status in (401, 403) else "unreachable" if exc.status is None else "error",
                "http_status": exc.status,
            }

    # Customer stats, console, and power controls are handled in the linked
    # Fluid account. This webapp does not use a shared client key.
    result["client"] = {"status": "disabled", "message": "Shared client API key is not used."}

    overall = "success" if result["application"]["status"] == result["metadata"]["status"] == "ok" else "error"
    if overall == "success":
        message = (
            f"Connected to {client.base_url} — {result['metadata']['nests']} nests, "
            f"{result['metadata']['eggs']} eggs, {result['metadata']['nodes']} nodes available."
        )
    elif result["application"]["status"] == "unreachable":
        message = f"Could not reach {client.base_url} — check DNS, HTTPS, and firewall."
    elif result["application"]["status"] == "rejected":
        message = f"{client.base_url} rejected the application API key."
    elif result["metadata"]["status"] == "rejected":
        message = "Fluid accepted the application key, but it lacks permission for nests, eggs, or nodes."
    elif result["metadata"]["status"] == "unreachable":
        message = "Fluid application API connected, but a metadata request timed out or lost its connection."
    else:
        message = "Fluid application API is not configured correctly."
    return jsonify(
        {
            "status": overall,
            "message": message,
            "target": target,
            "panel_url": panel_url,
            "checks": result,
        }
    )


@bp.route("/api/eggs/<nest_id>")
@admin_required
def admin_api_eggs(nest_id: str):
    try:
        eggs = get_fluid_client().eggs_for_nest(nest_id)
    except (ConfigurationError, PanelError, TypeError, ValueError):
        return jsonify([])
    return jsonify([{"id": e["attributes"]["id"], "name": e["attributes"]["name"]} for e in eggs])


# --- plans --------------------------------------------------------------
def _apply_plan_form(plan: GamePlan) -> None:
    plan.name = request.form.get("name") or plan.name
    plan.price = _float("price", plan.price or 0.0)
    category = PlanCategory.query.get(_int("category_id", 0))
    if category is not None:
        plan.category_id = category.id
        # Keep the legacy game field in sync; checkout, cart upgrades, and
        # historical routes still use it as the coarse plan family.
        plan.game = category.slug
    elif request.form.get("game"):
        plan.game = request.form.get("game") or plan.game

    subcategory = PlanSubcategory.query.get(_int("subcategory_id", 0))
    if subcategory is not None and category is not None and subcategory.category_id == category.id:
        plan.subcategory_id = subcategory.id
    else:
        plan.subcategory_id = None

    plan.memory = _int("memory", plan.memory or 1024)
    plan.cpu = _int("cpu", plan.cpu or 100)
    plan.disk = _int("disk", plan.disk or 5120)
    plan.nest_id = request.form.get("nest_id") or "General"
    allowed_eggs = _int_list(request.form.getlist("allowed_egg_ids"))
    plan.egg_id = allowed_eggs[0] if allowed_eggs else _int("egg_id", plan.egg_id or 1)
    allowed_eggs = allowed_eggs or [plan.egg_id]
    plan.set_allowed_eggs(allowed_eggs)
    plan.location_id = _int("location_id", plan.location_id or 1)
    plan.backups = _int("backups", 1)
    plan.allocations = _int("allocations", 1)
    plan.databases = _int("databases", 1)
    plan.is_featured = request.form.get("is_featured") == "on"
    plan.sub_type = (request.form.get("sub_type") or "Monthly").strip()[:30]
    plan.serial_number = _int("serial_number", 0)
    allowed_nodes = _int_list(request.form.getlist("allowed_location_ids"))
    if not allowed_nodes:
        allowed_nodes = _int_list(request.form.get("allowed_location_ids_text", ""))
    if not allowed_nodes and plan.location_id:
        allowed_nodes = [int(plan.location_id)]
    plan.set_allowed_node_ids(allowed_nodes)

    features_raw = request.form.get("features", "")
    if features_raw:
        plan.features = json.dumps([f.strip() for f in features_raw.split("\n") if f.strip()])
    else:
        legacy = [request.form.get(f"feature{i}", "") for i in range(1, 5)]
        plan.features = json.dumps([f for f in legacy if f])


def _plan_form_error() -> str | None:
    if request.form.get("nest_id") and not _int_list(request.form.getlist("allowed_egg_ids")) and not request.form.get("egg_id"):
        return "Select at least one egg before saving this plan."
    return None


@bp.route("/plans/add", methods=["POST"])
@admin_required
def admin_add_plan():
    form_error = _plan_form_error()
    if form_error:
        flash(form_error, "error")
        return redirect(url_for("admin.admin_dashboard", tab="plans"))

    category = PlanCategory.query.get(_int("category_id", 0))
    plan = GamePlan(game=category.slug if category is not None else request.form.get("game", "minecraft"))
    _apply_plan_form(plan)

    if plan.game == "discord_bot":
        plan.nest_id = "General"
        plan.egg_id = 314

    try:
        image = _read_image("image")
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("admin.admin_dashboard"))
    if image:
        plan.image_url = image

    db.session.add(plan)
    db.session.commit()
    flash(f"Plan {plan.name} added!", "success")
    return redirect(url_for("admin.admin_dashboard"))


def _wants_json() -> bool:
    """True when the dashboard's JavaScript made this request.

    The same endpoints still serve ordinary form posts, so the admin pages keep
    working with JavaScript disabled or broken.
    """
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _render_plan_row(plan: GamePlan) -> str:
    """Render one plans-table row exactly as the dashboard would."""
    location_labels = _location_label_map([], plan.allowed_node_ids)
    return render_template("admin/_plan_row.html", plan=plan, location_labels=location_labels)


def _copy_plan(
    plan: GamePlan,
    *,
    category_id: int | None,
    subcategory_id: int | None,
    game: str | None = None,
) -> GamePlan:
    return GamePlan(
        game=game or plan.game,
        name=f"{plan.name} Copy",
        price=plan.price,
        feature1=plan.feature1,
        feature2=plan.feature2,
        feature3=plan.feature3,
        feature4=plan.feature4,
        features=plan.features,
        is_featured=False,
        memory=plan.memory,
        cpu=plan.cpu,
        disk=plan.disk,
        nest_id=plan.nest_id,
        egg_id=plan.egg_id,
        location_id=plan.location_id,
        allowed_location_ids=plan.allowed_location_ids,
        backups=plan.backups,
        allocations=plan.allocations,
        databases=plan.databases,
        sub_type=plan.sub_type,
        serial_number=plan.serial_number,
        image_url=plan.image_url,
        category_id=category_id,
        subcategory_id=subcategory_id,
    )


def _next_plan_sort_order(category_id: int | None, subcategory_id: int | None) -> int:
    query = _plan_bucket_query(category_id, subcategory_id)
    current = query.order_by(GamePlan.serial_number.desc()).first()
    return (current.serial_number if current and current.serial_number is not None else 0) + 10


def _plan_bucket_query(category_id: int | None, subcategory_id: int | None):
    query = GamePlan.query
    if category_id is None:
        query = query.filter(GamePlan.category_id.is_(None))
    else:
        query = query.filter(GamePlan.category_id == category_id)

    if subcategory_id is None:
        query = query.filter(GamePlan.subcategory_id.is_(None))
    else:
        query = query.filter(GamePlan.subcategory_id == subcategory_id)

    return query


def _renumber_plans(category_id: int | None, subcategory_id: int | None, ordered_ids: list[int]) -> None:
    plans = _plan_bucket_query(category_id, subcategory_id).all()
    by_id = {plan.id: plan for plan in plans}
    seen: set[int] = set()
    position = 10

    for plan_id in ordered_ids:
        plan = by_id.get(plan_id)
        if plan is None or plan_id in seen:
            continue
        plan.serial_number = position
        seen.add(plan_id)
        position += 10

    remaining = sorted(
        [plan for plan in plans if plan.id not in seen],
        key=lambda item: ((item.serial_number or 0), item.name.lower(), item.id),
    )
    for plan in remaining:
        plan.serial_number = position
        position += 10


def _next_subcategory_sort_order(category_id: int) -> int:
    current = (
        PlanSubcategory.query.filter_by(category_id=category_id)
        .order_by(PlanSubcategory.sort_order.desc())
        .first()
    )
    return (current.sort_order if current and current.sort_order is not None else 0) + 10


def _renumber_subcategories(category_id: int, ordered_ids: list[int]) -> None:
    subcategories = PlanSubcategory.query.filter_by(category_id=category_id).all()
    by_id = {subcategory.id: subcategory for subcategory in subcategories}
    seen: set[int] = set()
    position = 10

    for subcategory_id in ordered_ids:
        subcategory = by_id.get(subcategory_id)
        if subcategory is None or subcategory_id in seen:
            continue
        subcategory.sort_order = position
        seen.add(subcategory_id)
        position += 10

    remaining = sorted(
        [subcategory for subcategory in subcategories if subcategory.id not in seen],
        key=lambda item: ((item.sort_order or 0), item.name.lower(), item.id),
    )
    for subcategory in remaining:
        subcategory.sort_order = position
        position += 10


@bp.route("/plan-categories/add", methods=["POST"])
@admin_required
def admin_add_plan_category():
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Category name is required.", "error")
        return redirect(url_for("admin.admin_dashboard", tab="plans"))

    category = PlanCategory(
        name=name,
        slug=_unique_category_slug(name),
        description=(request.form.get("description") or "").strip() or None,
        sort_order=_int("sort_order", 0),
        is_active=True,
    )
    db.session.add(category)
    db.session.commit()
    flash(f"Category {category.name} created.", "success")
    return redirect(url_for("admin.admin_dashboard", tab="plans") + "#plans-section")


@bp.route("/plan-subcategories/add", methods=["POST"])
@admin_required
def admin_add_plan_subcategory():
    category = PlanCategory.query.get(_int("category_id", 0))
    name = (request.form.get("name") or "").strip()
    if category is None or not name:
        flash("Category and subcategory name are required.", "error")
        return redirect(url_for("admin.admin_dashboard", tab="plans"))

    subcategory = PlanSubcategory(
        category_id=category.id,
        name=name,
        slug=_unique_subcategory_slug(category.id, name),
        description=(request.form.get("description") or "").strip() or None,
        sort_order=_int("sort_order", 0),
        is_active=True,
    )
    db.session.add(subcategory)
    db.session.commit()
    flash(f"Subcategory {subcategory.name} created under {category.name}.", "success")
    return redirect(url_for("admin.admin_dashboard", tab="plans") + "#plans-section")


@bp.route("/plan-categories/<int:category_id>/edit", methods=["POST"])
@admin_required
def admin_edit_plan_category(category_id: int):
    category = PlanCategory.query.get(category_id)
    if category is None:
        flash("Category not found.", "error")
        return redirect(url_for("admin.admin_dashboard", tab="plans") + "#plans-section")

    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Category name is required.", "error")
        return redirect(url_for("admin.admin_dashboard", tab="plans") + "#plans-section")

    category.name = name
    category.description = (request.form.get("description") or "").strip() or None
    category.sort_order = _int("sort_order", category.sort_order or 0)
    category.is_active = request.form.get("is_active") == "on"
    db.session.commit()
    flash(f"Category {category.name} updated.", "success")
    return redirect(url_for("admin.admin_dashboard", tab="plans") + "#plans-section")


@bp.route("/plan-subcategories/<int:subcategory_id>/edit", methods=["POST"])
@admin_required
def admin_edit_plan_subcategory(subcategory_id: int):
    subcategory = PlanSubcategory.query.get(subcategory_id)
    if subcategory is None:
        flash("Subcategory not found.", "error")
        return redirect(url_for("admin.admin_dashboard", tab="plans") + "#plans-section")

    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Subcategory name is required.", "error")
        return redirect(url_for("admin.admin_dashboard", tab="plans") + "#plans-section")

    category = PlanCategory.query.get(_int("category_id", subcategory.category_id))
    if category is None:
        flash("Parent category is required.", "error")
        return redirect(url_for("admin.admin_dashboard", tab="plans") + "#plans-section")

    old_category_id = subcategory.category_id
    subcategory.name = name
    subcategory.category_id = category.id
    subcategory.description = (request.form.get("description") or "").strip() or None
    subcategory.sort_order = _int("sort_order", subcategory.sort_order or 0)
    subcategory.is_active = request.form.get("is_active") == "on"
    if old_category_id != category.id:
        if PlanSubcategory.query.filter(
            PlanSubcategory.id != subcategory.id,
            PlanSubcategory.category_id == category.id,
            PlanSubcategory.slug == subcategory.slug,
        ).first():
            subcategory.slug = _unique_subcategory_slug(category.id, subcategory.name)
        for plan in subcategory.plans:
            plan.category_id = category.id
            plan.game = category.slug

    db.session.commit()
    flash(f"Subcategory {subcategory.name} updated.", "success")
    return redirect(url_for("admin.admin_dashboard", tab="plans") + "#plans-section")


@bp.route("/plan-categories/<int:category_id>/duplicate", methods=["POST"])
@admin_required
def admin_duplicate_plan_category(category_id: int):
    category = PlanCategory.query.get(category_id)
    if category is None:
        flash("Category not found.", "error")
        return redirect(url_for("admin.admin_dashboard", tab="plans") + "#plans-section")

    duplicate = PlanCategory(
        name=f"{category.name} Copy",
        slug=_unique_category_slug(f"{category.name} Copy"),
        description=category.description,
        sort_order=(category.sort_order or 0) + 1,
        is_active=category.is_active,
    )
    db.session.add(duplicate)
    db.session.flush()

    subcategory_map: dict[int, PlanSubcategory] = {}
    for subcategory in category.subcategories:
        copied_subcategory = PlanSubcategory(
            category_id=duplicate.id,
            name=f"{subcategory.name} Copy",
            slug=_unique_subcategory_slug(duplicate.id, f"{subcategory.name} Copy"),
            description=subcategory.description,
            sort_order=subcategory.sort_order,
            is_active=subcategory.is_active,
        )
        db.session.add(copied_subcategory)
        db.session.flush()
        subcategory_map[subcategory.id] = copied_subcategory

    for plan in category.plans:
        copied_subcategory = subcategory_map.get(plan.subcategory_id)
        db.session.add(
            _copy_plan(
                plan,
                category_id=duplicate.id,
                subcategory_id=copied_subcategory.id if copied_subcategory else None,
                game=duplicate.slug,
            )
        )

    db.session.commit()
    flash(f"Category {category.name} duplicated.", "success")
    return redirect(url_for("admin.admin_dashboard", tab="plans") + "#plans-section")


@bp.route("/plan-categories/<int:category_id>/delete", methods=["POST"])
@admin_required
def admin_delete_plan_category(category_id: int):
    category = PlanCategory.query.get(category_id)
    if category is None:
        flash("Category not found.", "error")
        return redirect(url_for("admin.admin_dashboard", tab="plans") + "#plans-section")

    for plan in list(category.plans):
        plan.category_id = None
        plan.subcategory_id = None
    db.session.delete(category)
    db.session.commit()
    flash(f"Category {category.name} deleted. Its plans were moved to Uncategorized.", "success")
    return redirect(url_for("admin.admin_dashboard", tab="plans") + "#plans-section")


@bp.route("/plan-subcategories/<int:subcategory_id>/duplicate", methods=["POST"])
@admin_required
def admin_duplicate_plan_subcategory(subcategory_id: int):
    subcategory = PlanSubcategory.query.get(subcategory_id)
    if subcategory is None:
        flash("Subcategory not found.", "error")
        return redirect(url_for("admin.admin_dashboard", tab="plans") + "#plans-section")

    duplicate = PlanSubcategory(
        category_id=subcategory.category_id,
        name=f"{subcategory.name} Copy",
        slug=_unique_subcategory_slug(subcategory.category_id, f"{subcategory.name} Copy"),
        description=subcategory.description,
        sort_order=(subcategory.sort_order or 0) + 1,
        is_active=subcategory.is_active,
    )
    db.session.add(duplicate)
    db.session.flush()

    for plan in subcategory.plans:
        db.session.add(_copy_plan(plan, category_id=subcategory.category_id, subcategory_id=duplicate.id))

    db.session.commit()
    flash(f"Subcategory {subcategory.name} duplicated.", "success")
    return redirect(url_for("admin.admin_dashboard", tab="plans") + "#plans-section")


@bp.route("/plan-subcategories/<int:subcategory_id>/delete", methods=["POST"])
@admin_required
def admin_delete_plan_subcategory(subcategory_id: int):
    subcategory = PlanSubcategory.query.get(subcategory_id)
    if subcategory is None:
        flash("Subcategory not found.", "error")
        return redirect(url_for("admin.admin_dashboard", tab="plans") + "#plans-section")

    for plan in list(subcategory.plans):
        plan.subcategory_id = None
    db.session.delete(subcategory)
    db.session.commit()
    flash(f"Subcategory {subcategory.name} deleted. Its plans were moved to Unassigned Plans.", "success")
    return redirect(url_for("admin.admin_dashboard", tab="plans") + "#plans-section")


@bp.route("/plan-subcategories/<int:subcategory_id>/move", methods=["POST"])
@admin_required
def admin_move_plan_subcategory(subcategory_id: int):
    subcategory = PlanSubcategory.query.get(subcategory_id)
    if subcategory is None:
        return jsonify({"status": "error", "message": "Subcategory not found."}), 404

    payload = request.get_json(silent=True) or {}
    category_id = _int_value(payload.get("category_id"), 0)
    target_subcategory_id = _int_value(payload.get("target_subcategory_id"), 0)
    category = PlanCategory.query.get(category_id)
    if category is None:
        return jsonify({"status": "error", "message": "Subcategories must be inside a main category."}), 400

    subcategory.category_id = category.id
    if PlanSubcategory.query.filter(
        PlanSubcategory.id != subcategory.id,
        PlanSubcategory.category_id == category.id,
        PlanSubcategory.slug == subcategory.slug,
    ).first():
        subcategory.slug = _unique_subcategory_slug(category.id, subcategory.name)

    for plan in subcategory.plans:
        plan.category_id = category.id
        plan.game = category.slug

    db.session.flush()
    ordered_ids = [
        item.id
        for item in PlanSubcategory.query.filter_by(category_id=category.id)
        .order_by(PlanSubcategory.sort_order.asc(), PlanSubcategory.name.asc())
        .all()
        if item.id != subcategory.id
    ]
    if target_subcategory_id and target_subcategory_id in ordered_ids:
        insert_at = ordered_ids.index(target_subcategory_id)
        ordered_ids.insert(insert_at, subcategory.id)
    else:
        ordered_ids.append(subcategory.id)
    _renumber_subcategories(category.id, ordered_ids)

    db.session.commit()
    return jsonify({"status": "success", "message": f"Moved {subcategory.name} to {category.name}."})


@bp.route("/plans/<int:plan_id>/move", methods=["POST"])
@admin_required
def admin_move_plan(plan_id: int):
    plan = GamePlan.query.get(plan_id)
    if plan is None:
        return jsonify({"status": "error", "message": "Plan not found."}), 404

    payload = request.get_json(silent=True) or {}
    subcategory_id = _int_value(payload.get("subcategory_id"), 0)
    category_id = _int_value(payload.get("category_id"), 0)
    target_plan_id = _int_value(payload.get("target_plan_id"), 0)
    position = (payload.get("position") or "").strip().lower()
    if position not in {"before", "after"}:
        position = "after"

    subcategory = PlanSubcategory.query.get(subcategory_id) if subcategory_id else None
    if subcategory is not None:
        category = subcategory.category
    elif category_id:
        category = PlanCategory.query.get(category_id)
        if category is None:
            return jsonify({"status": "error", "message": "Category not found."}), 404
    else:
        category = None

    old_category_id = plan.category_id
    old_subcategory_id = plan.subcategory_id

    plan.category_id = category.id if category is not None else None
    plan.subcategory_id = subcategory.id if subcategory is not None else None
    if category is not None:
        plan.game = category.slug

    db.session.flush()

    ordered_ids = [
        item.id
        for item in _plan_bucket_query(plan.category_id, plan.subcategory_id)
        .order_by(GamePlan.serial_number.asc(), GamePlan.name.asc(), GamePlan.id.asc())
        .all()
        if item.id != plan.id
    ]
    if target_plan_id and target_plan_id in ordered_ids:
        insert_at = ordered_ids.index(target_plan_id)
        if position == "after":
            insert_at += 1
        ordered_ids.insert(insert_at, plan.id)
    else:
        ordered_ids.append(plan.id)
    _renumber_plans(plan.category_id, plan.subcategory_id, ordered_ids)

    if old_category_id != plan.category_id or old_subcategory_id != plan.subcategory_id:
        _renumber_plans(old_category_id, old_subcategory_id, [])

    db.session.commit()
    return jsonify({"status": "success", "message": f"Moved {plan.name}."})


@bp.route("/plans/edit/<int:plan_id>", methods=["GET", "POST"])
@admin_required
def admin_edit_plan(plan_id: int):
    plan = GamePlan.query.get(plan_id)
    if plan is None:
        if _wants_json():
            return jsonify({"status": "error", "message": "That plan no longer exists."}), 404
        return redirect(url_for("admin.admin_dashboard"))

    if request.method == "POST":
        form_error = _plan_form_error()
        if form_error:
            if _wants_json():
                return jsonify({"status": "error", "message": form_error}), 400
            flash(form_error, "error")
            return redirect(request.url)

        _apply_plan_form(plan)

        if request.form.get("remove_image") == "on":
            plan.image_url = None

        try:
            image = _read_image("image")
        except ValueError as exc:
            if _wants_json():
                return jsonify({"status": "error", "message": str(exc)}), 400
            flash(str(exc), "error")
            return redirect(request.url)
        if image:
            plan.image_url = image

        db.session.commit()

        if _wants_json():
            # Return the re-rendered row so the dashboard repaints it from the
            # same template that drew it, rather than reformatting in JS.
            return jsonify(
                {
                    "status": "success",
                    "message": f"Plan {plan.name} updated successfully!",
                    "plan_id": plan.id,
                    "game": plan.game,
                    "row_html": _render_plan_row(plan),
                }
            )

        flash(f"Plan {plan.name} updated successfully!", "success")
        return redirect(url_for("admin.admin_dashboard"))

    nests, locations = _fallback_panel_metadata()
    location_labels = _location_label_map(locations, plan.allowed_node_ids)
    plan_categories = _plan_categories()
    plan_subcategories_by_category = _subcategories_by_category(plan_categories)

    # The dashboard's edit modal asks for just the form.
    template = "admin/_plan_form.html" if request.args.get("fragment") == "1" else "admin/edit_plan.html"
    return render_template(
        template,
        plan=plan,
        nests=nests,
        locations=locations,
        location_labels=location_labels,
        plan_categories=plan_categories,
        plan_subcategories_by_category=plan_subcategories_by_category,
        plan_subcategory_options=_subcategory_payload(plan_categories),
    )


@bp.route("/plans/delete/<int:plan_id>", methods=["POST"])
@admin_required
def admin_delete_plan(plan_id: int):
    plan = GamePlan.query.get(plan_id)
    if plan is None:
        if _wants_json():
            return jsonify({"status": "error", "message": "That plan no longer exists."}), 404
        return redirect(url_for("admin.admin_dashboard"))

    name, game = plan.name, plan.game
    db.session.delete(plan)
    db.session.commit()

    if _wants_json():
        return jsonify(
            {"status": "success", "message": f"Plan {name} deleted!", "plan_id": plan_id, "game": game}
        )

    flash(f"Plan {name} deleted!", "success")
    return redirect(url_for("admin.admin_dashboard"))


@bp.route("/plans/export", methods=["GET"])
@admin_required
def admin_export_plans():
    plans = GamePlan.query.order_by(GamePlan.game, GamePlan.serial_number).all()
    payload = [
        {
            "game": p.game,
            "category": p.category.name if p.category else None,
            "category_slug": p.category.slug if p.category else p.game,
            "subcategory": p.subcategory.name if p.subcategory else None,
            "subcategory_slug": p.subcategory.slug if p.subcategory else None,
            "name": p.name,
            "price": p.price,
            "memory": p.memory,
            "cpu": p.cpu,
            "disk": p.disk,
            "nest_id": p.nest_id,
            "egg_id": p.egg_id,
            "location_id": p.location_id,
            "allowed_location_ids": p.allowed_node_ids,
            "backups": p.backups or 1,
            "allocations": p.allocations or 1,
            "databases": p.databases or 1,
            "features": p.feature_list,
            "is_featured": p.is_featured,
            "sub_type": p.sub_type,
            "serial_number": p.serial_number,
        }
        for p in plans
    ]
    return Response(
        json.dumps(payload, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": "attachment;filename=plans_export.json"},
    )


@bp.route("/plans/import", methods=["POST"])
@admin_required
def admin_import_plans():
    file = request.files.get("plans_file")
    if not file or not file.filename:
        flash("No file selected.", "error")
        return redirect(url_for("admin.admin_dashboard"))

    try:
        data = json.loads(file.read().decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        flash(f"Invalid JSON file: {exc}", "error")
        return redirect(url_for("admin.admin_dashboard"))

    if isinstance(data, dict) and isinstance(data.get("plans"), list):
        data = data["plans"]

    if not isinstance(data, list):
        flash("JSON must be an array of plan objects, or an object with a plans array.", "error")
        return redirect(url_for("admin.admin_dashboard"))

    imported = skipped = 0
    for item in data:
        if not isinstance(item, dict) or not item.get("name"):
            skipped += 1
            continue
        name = item["name"]
        game = item.get("game") or item.get("category_slug") or "minecraft"
        if GamePlan.query.filter_by(name=name, game=game).first() is not None:
            skipped += 1
            continue

        features = item.get("features", [])
        try:
            category = None
            category_slug = item.get("category_slug") or game
            if category_slug:
                category = PlanCategory.query.filter_by(slug=category_slug).first()
            if category is None and item.get("category"):
                category = PlanCategory(
                    name=str(item["category"]),
                    slug=_unique_category_slug(str(item["category"])),
                    sort_order=0,
                    is_active=True,
                )
                db.session.add(category)
                db.session.flush()

            subcategory = None
            if category is not None:
                subcategory_slug = item.get("subcategory_slug")
                if subcategory_slug:
                    subcategory = PlanSubcategory.query.filter_by(
                        category_id=category.id, slug=subcategory_slug
                    ).first()
                if subcategory is None and item.get("subcategory"):
                    subcategory = PlanSubcategory(
                        category_id=category.id,
                        name=str(item["subcategory"]),
                        slug=_unique_subcategory_slug(category.id, str(item["subcategory"])),
                        sort_order=0,
                        is_active=True,
                    )
                    db.session.add(subcategory)
                    db.session.flush()

            location_id = item.get("location_id", item.get("node_id", 1))
            allowed_location_ids = item.get("allowed_location_ids", [location_id])
            plan = GamePlan(
                name=name,
                game=category.slug if category is not None else game,
                category_id=category.id if category is not None else None,
                subcategory_id=subcategory.id if subcategory is not None else None,
                price=float(item.get("price", 0)),
                memory=_int_value(item.get("memory"), 1024),
                cpu=_int_value(item.get("cpu"), 100),
                disk=_int_value(item.get("disk"), 5120),
                nest_id=item.get("nest_id", "General"),
                egg_id=_int_value(item.get("egg_id"), 1),
                location_id=_int_value(location_id, 1),
                backups=_int_value(item.get("backups"), 1),
                allocations=_int_value(item.get("allocations"), 1),
                databases=_int_value(item.get("databases"), 1),
                features=json.dumps(_feature_list(features)),
                is_featured=_bool_value(item.get("is_featured", False)),
                sub_type=(item.get("sub_type") or "Monthly"),
                serial_number=_int_value(item.get("serial_number"), 0),
                image_url=item.get("image_url") or None,
            )
            plan.set_allowed_node_ids(_int_list(allowed_location_ids) or [_int_value(location_id, 1)])
            db.session.add(plan)
            imported += 1
        except (TypeError, ValueError):
            skipped += 1

    db.session.commit()
    flash(f"Import complete: {imported} plans added, {skipped} skipped.", "success")
    return redirect(url_for("admin.admin_dashboard"))


# --- FAQs ---------------------------------------------------------------
@bp.route("/faqs/add", methods=["POST"])
@admin_required
def admin_add_faq():
    db.session.add(
        FAQ(
            question=request.form.get("question"),
            answer=request.form.get("answer"),
            category=request.form.get("category", "General"),
            order=_int("order", 0),
        )
    )
    db.session.commit()
    flash("FAQ added!", "success")
    return redirect(url_for("admin.admin_dashboard"))


@bp.route("/faqs/edit/<int:faq_id>", methods=["POST"])
@admin_required
def admin_edit_faq(faq_id: int):
    faq = FAQ.query.get(faq_id)
    if faq is not None:
        faq.question = request.form.get("question", faq.question)
        faq.answer = request.form.get("answer", faq.answer)
        faq.category = request.form.get("category", faq.category)
        faq.order = _int("order", faq.order or 0)
        db.session.commit()
        flash("FAQ updated!", "success")
    return redirect(url_for("admin.admin_dashboard"))


@bp.route("/faqs/delete/<int:faq_id>", methods=["POST"])
@admin_required
def admin_delete_faq(faq_id: int):
    faq = FAQ.query.get(faq_id)
    if faq is not None:
        db.session.delete(faq)
        db.session.commit()
        flash("FAQ deleted!", "success")
    return redirect(url_for("admin.admin_dashboard"))


# --- status / maintenance ----------------------------------------------
@bp.route("/maintenance/add", methods=["POST"])
@admin_required
def admin_add_maintenance():
    db.session.add(
        MaintenanceUpdate(
            title=request.form.get("title"),
            content=request.form.get("content"),
            status=request.form.get("status"),
        )
    )
    db.session.commit()
    flash("Maintenance update added!", "success")
    return redirect(url_for("admin.admin_dashboard"))


@bp.route("/status/update", methods=["POST"])
@admin_required
def admin_update_status():
    service = ServiceStatus.query.get(_int("service_id", 0))
    if service is not None:
        service.status = request.form.get("status")
        db.session.commit()
        flash(f"Status for {service.name} updated!", "success")
    return redirect(url_for("admin.admin_dashboard"))


# --- globe locations ----------------------------------------------------
@bp.route("/locations/add", methods=["POST"])
@admin_required
def admin_add_location():
    name = request.form.get("name")
    if not name:
        flash("Location name is required.", "error")
        return redirect(url_for("admin.admin_dashboard"))
    db.session.add(GlobeLocation(name=name, lat=_float("lat"), lng=_float("lng")))
    db.session.commit()
    flash(f"Location {name} added!", "success")
    return redirect(url_for("admin.admin_dashboard"))


@bp.route("/locations/delete/<int:loc_id>", methods=["POST"])
@admin_required
def admin_delete_location(loc_id: int):
    loc = GlobeLocation.query.get(loc_id)
    if loc is not None:
        db.session.delete(loc)
        db.session.commit()
        flash(f"Location {loc.name} deleted!", "success")
    return redirect(url_for("admin.admin_dashboard"))


# --- coupons ------------------------------------------------------------
@bp.route("/coupons/add", methods=["POST"])
@admin_required
def admin_add_coupon():
    code = (request.form.get("code") or "").strip()
    if not code:
        flash("Coupon code is required.", "error")
        return redirect(url_for("admin.admin_dashboard"))

    # Clamped so a typo cannot create a negative-total order (audit M-25).
    discount = max(0.0, min(100.0, _float("discount")))
    max_redemptions = _int("max_redemptions", 0) or None

    db.session.add(Coupon(code=code, discount_percent=discount, active=True, max_redemptions=max_redemptions))
    db.session.commit()
    flash(f"Coupon {code} added!", "success")
    return redirect(url_for("admin.admin_dashboard"))


@bp.route("/coupons/delete/<int:coupon_id>", methods=["POST"])
@admin_required
def admin_delete_coupon(coupon_id: int):
    """The dashboard has always posted here; the route did not exist."""
    coupon = Coupon.query.get(coupon_id)
    if coupon is not None:
        db.session.delete(coupon)
        db.session.commit()
        flash(f"Coupon {coupon.code} deleted!", "success")
    return redirect(url_for("admin.admin_dashboard"))


# --- servers / users ----------------------------------------------------
@bp.route("/user/<int:user_id>/provision", methods=["POST"])
@admin_required
def admin_user_provision(user_id: int):
    from flask import current_app

    from fluxweb.models import ItemKind, Order, OrderItem, OrderStatus
    from fluxweb.services import billing, provisioning

    user = User.query.get(user_id)
    plan = GamePlan.query.get(_int("plan_id", 0))
    if user is None or plan is None:
        return jsonify({"status": "error", "message": "User/Plan not found"}), 404

    # Admin grants go through the same order pipeline so they appear in the
    # ledger instead of being invisible (audit H-16).
    order = Order(
        user_id=user.id,
        status=OrderStatus.PENDING,
        subtotal_cents=0,
        discount_cents=0,
        total_cents=0,
        coupon_code="ADMIN_GRANT",
    )
    order.items.append(OrderItem(kind=ItemKind.NEW, plan_id=plan.id, name=plan.name, unit_price_cents=0))
    db.session.add(order)
    db.session.commit()

    billing.mark_free_order_paid(order)
    config = current_app.extensions["flux_config"]
    result = provisioning.provision_order(order, get_fluid_client(), expiry_days=config.expiry_days)

    if result.errors:
        return jsonify({"status": "error", "message": "; ".join(result.errors)}), 502
    return jsonify({"status": "success"})


@bp.route("/user/<int:user_id>/panel-link", methods=["POST"])
@admin_required
def admin_user_panel_link(user_id: int):
    """Manually link a Panel-first account after its email has changed.

    This is deliberately admin-only: a customer must not be able to claim an
    arbitrary existing Panel account by supplying its ID.
    """
    user = User.query.get(user_id)
    panel_id = _int("panel_user_id", 0)
    if user is None or panel_id <= 0:
        flash("Enter a valid Web user and Panel user ID.", "error")
        return redirect(url_for("admin.admin_dashboard", tab="users"))

    existing_owner = User.query.filter(User.pelican_user_id == panel_id, User.id != user.id).first()
    if existing_owner is not None:
        flash("That Panel account is already linked to another Web customer.", "error")
        return redirect(url_for("admin.admin_dashboard", tab="users"))

    try:
        panel_user = get_fluid_client().get_user(panel_id)
    except PanelError:
        flash("The Panel account could not be verified.", "error")
        return redirect(url_for("admin.admin_dashboard", tab="users"))
    if not panel_user:
        flash("That Panel user does not exist.", "error")
        return redirect(url_for("admin.admin_dashboard", tab="users"))

    from fluxweb.services.provisioning import _record_panel_link

    _record_panel_link(user, panel_user, source="admin")
    db.session.commit()
    flash(f"Panel account {panel_id} linked to {user.email}.", "success")
    return redirect(url_for("admin.admin_dashboard", tab="users"))


@bp.route("/server/<int:server_id>/suspend", methods=["POST"])
@admin_required
def admin_suspend_server(server_id: int):
    record = ServerRecord.query.filter_by(pelican_server_id=server_id).first()
    if record is None:
        return jsonify({"status": "error", "message": "Record not found"}), 404

    client = get_fluid_client()
    suspending = record.status != "Suspended"
    try:
        if suspending:
            client.suspend_server(server_id)
        else:
            client.unsuspend_server(server_id)
    except (ConfigurationError, PanelError):
        return jsonify({"status": "error", "message": "The panel rejected that action."}), 502

    record.status = "Suspended" if suspending else "Active"
    db.session.commit()
    return jsonify(
        {"status": "success", "message": "Server suspended" if suspending else "Server unsuspended"}
    )


@bp.route("/server/<int:server_id>/delete", methods=["POST"])
@admin_required
def admin_delete_server(server_id: int):
    try:
        get_fluid_client().delete_server(server_id)
    except (ConfigurationError, PanelError):
        return jsonify({"status": "error", "message": "The panel rejected that action."}), 502

    record = ServerRecord.query.filter_by(pelican_server_id=server_id).first()
    if record is not None:
        # Keep the row for the audit trail rather than destroying history.
        record.status = "Deleted"
        db.session.commit()
    return jsonify({"status": "success"})


# --- referrals ----------------------------------------------------------
@bp.route("/add-referral", methods=["POST"])
@admin_required
def admin_add_referral():
    from urllib.parse import urlparse

    code = (request.form.get("code") or "").strip()
    target = (request.form.get("target_url") or "").strip()
    parsed = urlparse(target)

    if not code or not target:
        flash("Both a code and a target URL are required.", "error")
    elif parsed.scheme not in {"http", "https"} or not parsed.netloc:
        flash("Target URL must be an absolute http(s) address.", "error")
    else:
        db.session.add(ReferralCode(code=code, target_url=target))
        db.session.commit()
        flash("Referral code added!", "success")
    return redirect(url_for("admin.admin_dashboard"))


@bp.route("/delete-referral/<int:ref_id>", methods=["POST"])
@admin_required
def admin_delete_referral(ref_id: int):
    ref = ReferralCode.query.get(ref_id)
    if ref is not None:
        db.session.delete(ref)
        db.session.commit()
        flash("Referral code deleted!", "success")
    return redirect(url_for("admin.admin_dashboard"))
