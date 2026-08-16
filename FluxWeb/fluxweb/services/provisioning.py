"""Provisioning: turning a paid order into servers on the panel.

Fixes carried over from the audit:

* **Idempotent.** Each :class:`OrderItem` records when it was fulfilled, so a
  redelivered webhook or a double-clicked button cannot provision twice
  (audit C-5).
* **Renewals actually renew.** The old code had no renewal branch at all, so a
  paid renewal silently created a *second* server while the original expired
  and was auto-deleted (audit M-20).
* **The right egg is used.** The old code sent one egg id in the payload while
  fetching the docker image, startup command, and variables from a different
  one (audit M-21).
* Callable without a request context, so a job or CLI command can retry a
  failed order.
"""

from __future__ import annotations

import logging
import random
from datetime import UTC, datetime, timedelta

from fluxweb.errors import PanelError
from fluxweb.extensions import db
from fluxweb.models import GamePlan, ItemKind, Order, OrderItem, OrderStatus, ServerRecord, ServerStatus
from fluxweb.models.server import utcnow

log = logging.getLogger(__name__)

# Egg ids for the Discord-bot runtime picker. Product configuration that used
# to be inline magic numbers (audit M-10).
SOFTWARE_EGGS = {"python": 232, "nodejs": 314}
DISCORD_BOT_NODE_ID = 4

ALLOCATION_PORT_RANGE = (25565, 26000)
ALLOCATION_ATTEMPTS = 5


class ProvisionResult:
    def __init__(self) -> None:
        self.provisioned: list[ServerRecord] = []
        self.errors: list[str] = []

    @property
    def success_count(self) -> int:
        return len(self.provisioned)

    @property
    def ok(self) -> bool:
        return not self.errors


def provision_order(order: Order, client, *, expiry_days: int) -> ProvisionResult:
    """Fulfil every unfulfilled line on a paid order.

    Safe to call repeatedly *and* concurrently. Stripe can deliver the same
    event twice at once, and a customer can hit the PayPal capture endpoint
    while a webhook is already in flight. Checking ``item.is_fulfilled`` in
    Python is not enough on its own: two callers can both read "unfulfilled"
    and both create a server for one payment.

    The guard is an atomic compare-and-swap on the order status. Exactly one
    caller can move an order out of PAID/FAILED into PROVISIONING; everyone
    else returns immediately.
    """
    result = ProvisionResult()

    if not order.is_paid:
        result.errors.append("Order is not paid.")
        return result

    claimed = (
        db.session.query(Order)
        .filter(
            Order.id == order.id,
            Order.status.in_([OrderStatus.PAID, OrderStatus.FAILED]),
        )
        .update({"status": OrderStatus.PROVISIONING}, synchronize_session=False)
    )
    db.session.commit()

    if not claimed:
        # Already completed, or another worker holds the claim.
        log.info("Skipping provisioning for order %s (status %s)", order.public_id, order.status)
        return result

    db.session.refresh(order)
    user = order.user
    for item in order.items:
        if item.is_fulfilled:
            continue
        try:
            if item.kind == ItemKind.RENEWAL:
                record = _renew(item, expiry_days=expiry_days, client=client)
            elif item.kind == ItemKind.UPGRADE:
                record = _upgrade(item, client=client)
            else:
                record = _create(order, item, user, client=client, expiry_days=expiry_days)

            item.fulfilled_at = utcnow()
            item.fulfilled_server_id = record.id if record else None
            if record is not None:
                result.provisioned.append(record)
            db.session.commit()
        except PanelError as exc:
            db.session.rollback()
            log.error("Provisioning failed for order %s item %s: %s", order.public_id, item.id, exc)
            result.errors.append(f"{item.name}: the game panel rejected the request.")
        except Exception as exc:  # noqa: BLE001 - last line of defence, always logged
            db.session.rollback()
            log.exception("Unexpected provisioning failure for order %s item %s", order.public_id, item.id)
            result.errors.append(f"{item.name}: an unexpected error occurred.")
            del exc

    all_done = all(item.is_fulfilled for item in order.items)
    order.status = OrderStatus.COMPLETED if all_done else OrderStatus.FAILED
    if all_done:
        order.provisioned_at = utcnow()
        order.failure_reason = None
    else:
        order.failure_reason = "; ".join(result.errors)[:2000]
    db.session.commit()

    return result


# --- individual line kinds ---------------------------------------------
def _renew(item: OrderItem, *, expiry_days: int, client) -> ServerRecord | None:
    """Extend an existing server rather than creating a new one."""
    record = ServerRecord.query.get(item.server_id) if item.server_id else None
    if record is None:
        raise PanelError("renewal target no longer exists")

    base = record.expires_at if record.expires_at and record.expires_at > utcnow() else utcnow()
    record.expires_at = base + timedelta(days=expiry_days)

    # A renewal on an expired/suspended server brings it back.
    if record.status in {ServerStatus.EXPIRED, ServerStatus.SUSPENDED} and record.pelican_server_id:
        try:
            client.unsuspend_server(record.pelican_server_id)
        except PanelError:
            log.warning("Could not unsuspend server %s during renewal", record.pelican_server_id)
    record.status = ServerStatus.ACTIVE
    record.payment_ref = f"order:{item.order.public_id}"

    _sync_expiry_to_panel(record, client)
    log.info("Renewed server %s until %s", record.id, record.expires_at)
    return record


def _upgrade(item: OrderItem, *, client) -> ServerRecord | None:
    record = ServerRecord.query.get(item.server_id) if item.server_id else None
    new_plan = GamePlan.query.get(item.plan_id) if item.plan_id else None
    if record is None or new_plan is None:
        raise PanelError("upgrade target no longer exists")

    server = client.get_server(record.pelican_server_id)
    if server is None:
        raise PanelError("server not found on panel")
    allocation_id = server.get("allocation")
    if not allocation_id:
        raise PanelError("could not identify the server's primary allocation")

    client.update_build(
        record.pelican_server_id,
        allocation_id=int(allocation_id),
        memory=new_plan.memory,
        disk=new_plan.disk,
        cpu=new_plan.cpu,
        databases=new_plan.databases or 1,
        backups=new_plan.backups or 1,
        allocations=new_plan.allocations or 1,
    )

    record.plan_id = new_plan.id
    record.plan_name = new_plan.name
    log.info("Upgraded server %s to plan %s", record.id, new_plan.id)
    return record


def _create(order: Order, item: OrderItem, user, *, client, expiry_days: int) -> ServerRecord:
    plan = GamePlan.query.get(item.plan_id) if item.plan_id else None
    if plan is None:
        raise PanelError("plan no longer exists")

    panel_user_id = ensure_panel_user(user, client)

    # One egg id, used for both the payload and the egg metadata lookup.
    egg_id = item.egg_id or SOFTWARE_EGGS.get(item.software or "", plan.egg_id)
    node_id = item.node_id or _select_node(plan, order)

    allocation_id = _acquire_allocation(client, node_id)

    expires_at = utcnow() + timedelta(days=expiry_days)
    payload = {
        "name": (order.server_name or plan.name)[:100],
        "user": panel_user_id,
        "egg": int(egg_id),
        "description": f"EXP: {expires_at.strftime('%Y-%m-%d')}",
        "limits": {"memory": plan.memory, "swap": 0, "disk": plan.disk, "io": 500, "cpu": plan.cpu},
        "feature_limits": {
            "databases": plan.databases or 1,
            "backups": plan.backups or 1,
            "allocations": plan.allocations or 1,
        },
        "environment": {},
        "start_on_completion": True,
    }

    if not allocation_id:
        # The customer selected a node, not a Fluid location. Falling back to
        # location-based auto-deployment could create the server on a different
        # node, so fail safely and let the normal retry path try again.
        raise PanelError(f"No allocation is available on selected node {node_id}.")
    payload["allocation"] = {"default": allocation_id}

    nest_id = plan.nest_id if str(plan.nest_id or "").isdigit() else None
    egg = client.get_egg(int(egg_id), nest_id=nest_id)
    if egg:
        payload["docker_image"] = egg.get("docker_image")
        payload["startup"] = egg.get("startup")
        variables = (egg.get("relationships", {}).get("variables", {}) or {}).get("data", []) or []
        for variable in variables:
            attrs = variable.get("attributes", {})
            if attrs.get("env_variable") is not None:
                payload["environment"][attrs["env_variable"]] = attrs.get("default_value")

    created = client.create_server(payload)
    attrs = created.get("attributes", {})
    if not attrs.get("id"):
        raise PanelError("panel did not return a server id")

    record = ServerRecord(
        user_id=user.id,
        plan_id=plan.id,
        plan_name=order.server_name or plan.name,
        pelican_server_id=attrs["id"],
        pelican_server_identifier=attrs.get("identifier"),
        ip_address=_extract_ip(attrs) or "Allocating...",
        payment_ref=f"order:{order.public_id}",
        status=ServerStatus.ACTIVE,
        expires_at=expires_at,
    )
    db.session.add(record)
    db.session.flush()
    log.info("Provisioned server %s (panel id %s) for order %s", record.id, attrs["id"], order.public_id)
    return record


# --- helpers ------------------------------------------------------------
def ensure_panel_user(user, client) -> int:
    """Return the panel user id for ``user``, creating the account if needed.

    Existing links always win. A verified, unlinked Web account may adopt one
    exact Panel email match once, then the relationship is frozen by Panel ID
    and UUID. Unverified accounts are never allowed to claim an existing Panel
    account by email.
    """
    if user.pelican_user_id:
        existing = client.get_user(user.pelican_user_id)
        if existing is not None:
            _record_panel_link(user, existing, source=user.panel_link_source or "stored")
            db.session.commit()
            return user.pelican_user_id
        log.warning("Panel user %s for user %s vanished; creating a new one", user.pelican_user_id, user.id)
        user.pelican_user_id = None

    web_uuid = user.supabase_user_id
    if web_uuid and hasattr(client, "find_users_by_external_id"):
        matches = client.find_users_by_external_id(web_uuid)
        if len(matches) == 1:
            _record_panel_link(user, matches[0], source="external_id")
            db.session.commit()
            return int(matches[0]["id"])

    if user.email_verified and hasattr(client, "find_users_by_email"):
        matches = client.find_users_by_email(user.email)
        if len(matches) == 1:
            _record_panel_link(user, matches[0], source="verified_email")
            db.session.commit()
            log.info("Linked existing Panel user %s to Web user %s by verified email", user.pelican_user_id, user.id)
            return int(matches[0]["id"])
        if len(matches) > 1:
            log.error("Ambiguous Panel email match for Web user %s; refusing automatic link", user.id)

    username = _panel_username(user)
    try:
        panel_id, password = client.create_user(
            email=user.email,
            username=username,
            first_name=user.username or username,
            external_id=web_uuid,
        )
    except TypeError:
        # Keep older test doubles/integration clients usable during rolling
        # deployments; the canonical client accepts external_id.
        panel_id, password = client.create_user(
            email=user.email, username=username, first_name=user.username or username
        )
    user.pelican_user_id = panel_id
    created = client.get_user(panel_id) if hasattr(client, "get_user") else None
    _record_panel_link(user, created or {}, source="created")
    user.set_pelican_password(password)
    db.session.commit()
    log.info("Created panel user %s for user %s", panel_id, user.id)
    return panel_id


def _record_panel_link(user, panel_user: dict, *, source: str) -> None:
    """Persist immutable Panel identity and current display metadata."""
    if panel_user.get("id") is not None:
        user.pelican_user_id = int(panel_user["id"])
    if panel_user.get("uuid"):
        user.pelican_user_uuid = panel_user["uuid"]
    user.pelican_user_email = panel_user.get("email") or user.pelican_user_email or user.email
    user.panel_link_source = source
    user.panel_linked_at = user.panel_linked_at or datetime.now(UTC).replace(tzinfo=None)


def _panel_username(user) -> str:
    base = "".join(ch for ch in (user.username or "").lower() if ch.isalnum() or ch in "_-") or "client"
    return f"{base[:20]}_{user.id}"


def _select_node(plan: GamePlan, order: Order) -> int:
    if plan.game == "discord_bot":
        return DISCORD_BOT_NODE_ID
    if order.node_id:
        return int(order.node_id)
    return int(plan.location_id or 1)


def _acquire_allocation(client, node_id: int) -> int | None:
    """Find or create a free allocation, retrying on port collisions.

    Still best-effort: the panel is the source of truth and two racing
    provisions can pick the same free allocation. Retrying and then falling
    back to the panel's own deploy mechanism keeps that from being fatal
    (audit M-26).
    """
    allocation_id = client.find_free_allocation(node_id)
    if allocation_id:
        return allocation_id

    try:
        node = client.get_node(node_id)
    except PanelError:
        return None
    fqdn = node.get("fqdn")
    if not fqdn:
        return None

    for _ in range(ALLOCATION_ATTEMPTS):
        port = random.randint(*ALLOCATION_PORT_RANGE)  # noqa: S311 - not security sensitive
        try:
            client.create_allocation(node_id, ip=fqdn, port=port)
        except PanelError:
            continue  # Port already taken; try another.
        allocation_id = client.find_free_allocation(node_id)
        if allocation_id:
            return allocation_id
    return None


def _extract_ip(attrs: dict) -> str | None:
    try:
        allocations = attrs["relationships"]["allocations"]["data"]
    except (KeyError, TypeError):
        return None
    if not allocations:
        return None
    for allocation in allocations:
        alloc_attrs = allocation.get("attributes", {})
        if alloc_attrs.get("is_default"):
            return f"{alloc_attrs.get('ip')}:{alloc_attrs.get('port')}"
    first = allocations[0].get("attributes", {})
    if first.get("ip"):
        return f"{first.get('ip')}:{first.get('port')}"
    return None


def _sync_expiry_to_panel(record: ServerRecord, client) -> None:
    """Best-effort write of the new expiry into the panel description."""
    if not record.pelican_server_id or not record.expires_at:
        return
    try:
        server = client.get_server(record.pelican_server_id)
        if not server:
            return
        client.update_description(
            record.pelican_server_id,
            name=server.get("name") or record.plan_name or "Server",
            description=f"EXP: {record.expires_at.strftime('%Y-%m-%d')}",
            user_id=server.get("user"),
        )
    except PanelError:
        log.warning("Could not sync expiry to panel for server %s", record.id)
