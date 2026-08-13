"""Public marketing and informational pages."""

from __future__ import annotations

from urllib.parse import urlparse

from flask import Blueprint, redirect, render_template, url_for

from fluxweb.extensions import db, limiter
from fluxweb.models import FAQ, GamePlan, MaintenanceUpdate, PlanCategory, ReferralCode, ServiceStatus

bp = Blueprint("public", __name__)


def _plans_for(game: str) -> list[GamePlan]:
    category = PlanCategory.query.filter_by(slug=game, is_active=True).first()
    query = GamePlan.query
    if category is not None:
        query = query.filter(GamePlan.category_id == category.id)
    else:
        query = query.filter(GamePlan.game == game)
    return query.order_by(GamePlan.subcategory_id.asc(), GamePlan.serial_number.asc()).all()


def _plan_context(game: str) -> dict[str, object]:
    category = PlanCategory.query.filter_by(slug=game, is_active=True).first()
    plans = _plans_for(game)
    subcategories = [subcategory for subcategory in (category.subcategories if category else []) if subcategory.is_active]
    groups: list[dict[str, object]] = []

    if subcategories:
        for subcategory in subcategories:
            grouped = [plan for plan in plans if plan.subcategory_id == subcategory.id]
            if grouped:
                groups.append(
                    {
                        "id": f"subcat-{subcategory.id}",
                        "name": subcategory.name,
                        "description": subcategory.description,
                        "plans": grouped,
                    }
                )
        uncategorized = [plan for plan in plans if plan.subcategory_id is None]
        if uncategorized:
            groups.append({"id": "default", "name": "Other Plans", "description": None, "plans": uncategorized})
    else:
        groups.append({"id": "all", "name": "Plans", "description": None, "plans": plans})

    return {"plans": plans, "plan_category": category, "plan_groups": groups}


@bp.route("/")
def index():
    featured_plans = GamePlan.query.filter_by(is_featured=True, game="minecraft").all()
    faqs = FAQ.query.order_by(FAQ.order.asc()).all()
    return render_template("index.html", featured_plans=featured_plans, faqs=faqs)


@bp.route("/minecraft")
def minecraft():
    return render_template("services/minecraft.html", **_plan_context("minecraft"))


@bp.route("/hytale")
def hytale():
    return render_template("services/hytale.html", **_plan_context("hytale"))


@bp.route("/dedicated")
def dedicated():
    return render_template("services/dedicated.html", **_plan_context("dedicated"))


@bp.route("/discord-bots")
def discord_bots():
    return render_template("services/discord_bots.html", **_plan_context("discord_bot"))


@bp.route("/about")
def about():
    return render_template("pages/about.html")


@bp.route("/contact")
def contact():
    return render_template("pages/contact.html")


@bp.route("/status")
def status():
    services = ServiceStatus.query.all()
    updates = MaintenanceUpdate.query.order_by(MaintenanceUpdate.created_at.desc()).limit(20).all()
    return render_template("system/status.html", services=services, recent_updates=updates)


@bp.route("/maintenance")
def maintenance():
    updates = MaintenanceUpdate.query.order_by(MaintenanceUpdate.created_at.desc()).limit(50).all()
    return render_template("system/maintenance.html", updates=updates)


@bp.route("/ram-calculator")
def ram_calculator():
    return render_template("ram_calculator.html")


@bp.route("/privacy")
def privacy():
    return render_template("legal/privacy.html")


@bp.route("/terms")
def terms():
    return render_template("legal/terms.html")


@bp.route("/<string:category_slug>")
def plan_category(category_slug: str):
    category = PlanCategory.query.filter_by(slug=category_slug, is_active=True).first()
    if category is None:
        return redirect(url_for("public.index"))
    return render_template("services/category.html", **_plan_context(category.slug))


@bp.route("/r/<string:code>")
@limiter.limit("60 per hour")
def referral_redirect(code: str):
    ref = ReferralCode.query.filter_by(code=code).first()
    if ref is None:
        return redirect(url_for("public.index"))

    ref.clicks = (ref.clicks or 0) + 1
    db.session.commit()

    # Only ever redirect to an absolute http(s) URL; anything else goes home.
    parsed = urlparse(ref.target_url or "")
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        return redirect(ref.target_url)
    return redirect(url_for("public.index"))
