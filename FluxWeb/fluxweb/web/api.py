"""JSON endpoints used by the account dashboard and cart."""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request

from fluxweb.errors import AuthorizationError, ConfigurationError, PanelError
from fluxweb.extensions import limiter
from fluxweb.integrations.fluid import get_fluid_client
from fluxweb.web.helpers import get_owned_server, login_required

log = logging.getLogger(__name__)

bp = Blueprint("api", __name__, url_prefix="/api")

POWER_SIGNALS = {"start", "stop", "restart", "kill"}


@bp.route("/server/<identifier>/stats", strict_slashes=False)
@login_required
@limiter.limit("240 per hour")
def server_stats(identifier: str):
    try:
        get_owned_server(identifier, by_identifier=True)
    except AuthorizationError as exc:
        return jsonify({"status": "error", "message": exc.user_message}), 403

    try:
        attributes = get_fluid_client().server_resources(identifier)
    except ConfigurationError:
        return jsonify({"status": "error", "message": "Live stats are not configured."}), 503
    except PanelError as exc:
        if exc.status == 404:
            return jsonify({"status": "deleted", "message": "Server no longer exists on panel"}), 404
        return jsonify({"status": "error", "message": "The panel is temporarily unavailable."}), 502

    resources = attributes.get("resources", {})
    return jsonify(
        {
            "status": "success",
            "stats": {
                "cpu": resources.get("cpu_absolute"),
                "memory": resources.get("memory_bytes"),
                "state": attributes.get("current_state"),
            },
        }
    )


@bp.route("/server/<identifier>/websocket", strict_slashes=False)
@login_required
@limiter.limit("120 per hour")
def server_websocket(identifier: str):
    try:
        get_owned_server(identifier, by_identifier=True)
    except AuthorizationError as exc:
        return jsonify({"status": "error", "message": exc.user_message}), 403

    try:
        data = get_fluid_client().server_websocket(identifier)
    except ConfigurationError:
        return jsonify({"status": "error", "message": "Console access is not configured."}), 503
    except PanelError:
        return jsonify({"status": "error", "message": "Console bridge unavailable."}), 502

    return jsonify({"status": "success", "data": data})


@bp.route("/server/<identifier>/power", methods=["POST"], strict_slashes=False)
@login_required
@limiter.limit("60 per hour")
def server_power(identifier: str):
    try:
        record = get_owned_server(identifier, by_identifier=True)
    except AuthorizationError as exc:
        return jsonify({"status": "error", "message": exc.user_message}), 403

    payload = request.get_json(silent=True) or {}
    action = payload.get("action")
    if action not in POWER_SIGNALS:
        return jsonify({"status": "error", "message": "Unsupported power action."}), 400

    if record.status in {"Suspended", "Expired", "Deleted"}:
        return jsonify({"status": "error", "message": f"This server is {record.status.lower()}."}), 409

    try:
        get_fluid_client().send_power_signal(identifier, action)
    except ConfigurationError:
        return jsonify({"status": "error", "message": "Power control is not configured."}), 503
    except PanelError:
        return jsonify({"status": "error", "message": "The panel rejected that action."}), 502

    return jsonify({"status": "success"})


@bp.route("/locations")
@limiter.limit("120 per hour")
def api_locations():
    try:
        nodes = get_fluid_client().list_nodes()
    except (ConfigurationError, PanelError):
        return jsonify([])

    raw_ids = (request.args.get("ids") or "").strip()
    allowed_ids: set[int] | None = None
    if raw_ids:
        parsed: set[int] = set()
        for part in raw_ids.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                parsed.add(int(part))
            except ValueError:
                continue
        allowed_ids = parsed

    # Capacity for the plan being bought, when the caller tells us the size.
    # Without this a customer can pick a full location, pay, and only then
    # have provisioning fail - money taken, no server.
    def _int_arg(name: str) -> int:
        try:
            return max(0, int(request.args.get(name, 0)))
        except (TypeError, ValueError):
            return 0

    want_memory = _int_arg("memory")
    want_disk = _int_arg("disk")
    client = get_fluid_client()

    result = []
    for node in nodes:
        attrs = node["attributes"]
        if allowed_ids is not None and attrs["id"] not in allowed_ids:
            continue

        capacity = attrs.get("capacity") or {}
        entry = {
            "id": attrs["id"],
            "name": attrs.get("name"),
            "fqdn": attrs.get("fqdn", ""),
            "memory_free": capacity.get("memory_free"),
            "disk_free": capacity.get("disk_free"),
            "maintenance": capacity.get("maintenance", False),
        }
        # Only claim unavailable when we were actually asked about a size.
        if want_memory or want_disk:
            entry["available"] = client.node_fits(attrs, memory=want_memory, disk=want_disk)
        else:
            entry["available"] = not capacity.get("maintenance", False)
        result.append(entry)

    return jsonify(result)
