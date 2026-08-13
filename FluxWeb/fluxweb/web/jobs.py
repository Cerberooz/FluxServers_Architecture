"""Scheduled job endpoints.

Expiry, suspension, and deletion used to run inside the ``/account`` page view,
so a customer who stopped logging in was never expired and was hosted for free
indefinitely (audit SC-3, P-1).

These endpoints are authenticated by a shared secret, not a session, so a
platform scheduler (Vercel Cron, GitHub Actions, any cron + curl) can call
them. They are CSRF-exempt for the same reason.
"""

from __future__ import annotations

import hmac
import logging

from flask import Blueprint, current_app, jsonify, request

from fluxweb.errors import ConfigurationError, PanelError
from fluxweb.extensions import csrf
from fluxweb.integrations.fluid import get_fluid_client
from fluxweb.services import servers as server_service

log = logging.getLogger(__name__)

bp = Blueprint("jobs", __name__, url_prefix="/jobs")


def _authorised() -> bool:
    """Constant-time check of the cron shared secret."""
    expected = current_app.extensions["flux_config"].cron_secret
    if not expected:
        return False

    # Header only, deliberately. A ?token= query parameter would put the
    # secret into access logs, proxy logs, and Referer headers. Vercel Cron
    # sends this header automatically when CRON_SECRET is set on the project;
    # any other scheduler can pass it with:
    #   curl -H "Authorization: Bearer $CRON_SECRET" https://host/jobs/sync-servers
    header = request.headers.get("Authorization", "")
    if not header.startswith("Bearer "):
        return False
    provided = header[7:]

    return bool(provided) and hmac.compare_digest(provided, expected)


@bp.route("/sync-servers", methods=["POST", "GET"])
@csrf.exempt
def sync_servers():
    if not _authorised():
        log.warning("Rejected unauthorised cron call to /jobs/sync-servers")
        return jsonify({"error": "unauthorised"}), 401

    config = current_app.extensions["flux_config"]
    try:
        stats = server_service.sync_all_servers(get_fluid_client(), grace_days=config.deletion_grace_days)
    except ConfigurationError:
        return jsonify({"error": "panel not configured"}), 503
    except PanelError as exc:
        log.error("Server sync job failed: %s", exc)
        return jsonify({"error": "panel unavailable"}), 502

    log.info("Server sync job complete: %s", stats)
    return jsonify({"status": "ok", **stats})
