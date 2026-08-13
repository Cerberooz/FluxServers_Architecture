"""Customer account area."""

from __future__ import annotations

import datetime as datetime_module
import logging

from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for

from fluxweb.errors import DomainError, IntegrationError, PanelError
from fluxweb.extensions import limiter
from fluxweb.integrations.fluid import get_fluid_client
from fluxweb.models import Order, ServerRecord, ServerStatus
from fluxweb.services import accounts
from fluxweb.services import servers as server_service
from fluxweb.web.helpers import current_user, login_required

log = logging.getLogger(__name__)

bp = Blueprint("account", __name__)


@bp.route("/account")
@login_required
def user_account():
    user = current_user()
    config = current_app.extensions["flux_config"]

    # Sync is throttled and failure-tolerant: the page renders from the
    # database even when the panel is down, instead of fanning out four
    # blocking calls per server on every load (audit P-1).
    if config.panel_configured:
        try:
            server_service.sync_user_servers(
                user.id, get_fluid_client(), grace_days=config.deletion_grace_days
            )
        except PanelError as exc:
            log.warning("Panel sync skipped for user %s: %s", user.id, exc)

    servers = (
        ServerRecord.query.filter(
            ServerRecord.user_id == user.id, ServerRecord.status != ServerStatus.DELETED
        )
        .order_by(ServerRecord.created_at.desc())
        .all()
    )
    orders = Order.query.filter_by(user_id=user.id).order_by(Order.created_at.desc()).limit(20).all()

    return render_template(
        "account.html",
        user=user,
        servers=servers,
        orders=orders,
        # The account template does date arithmetic on expiry dates.
        datetime=datetime_module.datetime,
        timedelta=datetime_module.timedelta,
        panel_url=config.panel_url or "",
        email_verified=user.email_verified,
    )


@bp.route("/account/sync", methods=["POST"])
@login_required
@limiter.limit("10 per hour")
def manual_sync():
    user = current_user()
    config = current_app.extensions["flux_config"]
    if config.panel_configured:
        try:
            server_service.sync_user_servers(
                user.id, get_fluid_client(), grace_days=config.deletion_grace_days, force=True
            )
            flash("Servers synced with the panel.", "success")
        except PanelError:
            flash("The game panel is temporarily unavailable. Please try again shortly.", "error")
    return redirect(url_for("account.user_account"))


@bp.route("/account/change-password", methods=["POST"])
@login_required
@limiter.limit("10 per hour")
def change_password():
    user = current_user()
    try:
        accounts.change_password(
            user,
            request.form.get("new_password") or "",
            # Re-authentication: a stolen session cookie must not be enough to
            # seize the credential.
            current_password=request.form.get("current_password"),
        )
    except DomainError as exc:
        flash(exc.user_message, "error")
        return redirect(url_for("account.user_account"))
    except IntegrationError:
        log.exception("Password change failed at the auth provider")
        flash("We could not update your password just now. Please try again shortly.", "error")
        return redirect(url_for("account.user_account"))

    # Note: the panel password is intentionally not changed here. It is a
    # separate credential now (audit H-15); use the button below to rotate it.
    flash("Password updated.", "success")
    return redirect(url_for("account.user_account"))


@bp.route("/account/panel-password", methods=["POST"])
@login_required
@limiter.limit("5 per hour")
def rotate_panel_password():
    user = current_user()
    try:
        accounts.rotate_panel_password(user, get_fluid_client())
    except DomainError as exc:
        flash(exc.user_message, "error")
        return redirect(url_for("account.user_account"))
    except PanelError:
        flash("The game panel is temporarily unavailable. Please try again shortly.", "error")
        return redirect(url_for("account.user_account"))

    flash("A new game panel password has been generated. It is shown on this page.", "success")
    return redirect(url_for("account.user_account"))
