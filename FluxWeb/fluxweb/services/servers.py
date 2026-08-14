"""Server lifecycle: panel status sync, expiry, suspension, deletion.

All of this previously ran inside the ``/account`` page view, which meant a
customer who stopped logging in was never suspended and never expired, while a
customer who did log in paid for up to four sequential panel round-trips per
server (audit P-1, SC-3).

These functions are request-independent so a scheduled job can drive them.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from sqlalchemy import or_

from fluxweb.errors import PanelError
from fluxweb.extensions import db
from fluxweb.models import ServerRecord, ServerStatus
from fluxweb.models.server import utcnow

log = logging.getLogger(__name__)

SYNC_STALE_AFTER = timedelta(minutes=10)

# Page loads should refresh a small amount of state and then render from the
# database. The scheduled sync job owns full-fleet reconciliation.
MAX_USER_SYNC_PER_REQUEST = 1

#: Safety valve on destructive work. See `sync_all_servers`.
MAX_DELETIONS_PER_RUN = 25


def sync_server(record: ServerRecord, client) -> bool:
    """Refresh one server from the panel. Returns False when the panel failed."""
    try:
        data = client.get_server(record.pelican_server_id, include_allocations=True)
    except PanelError as exc:
        log.warning("Panel sync failed for server %s: %s", record.id, exc)
        return False

    if data is None:
        record.status = ServerStatus.DELETED
        record.last_synced_at = utcnow()
        return True

    record.status = ServerStatus.SUSPENDED if data.get("suspended") else ServerStatus.ACTIVE

    if data.get("name"):
        record.plan_name = data["name"]

    ip = _primary_ip(data)
    if ip:
        record.ip_address = ip

    node_id = data.get("node")
    if node_id:
        try:
            node = client.get_node(int(node_id))
            if node.get("name"):
                record.node_name = node["name"]
        except (PanelError, ValueError, TypeError):
            pass

    expiry = _expiry_from_description(data.get("description", ""))
    if expiry and record.expires_at != expiry:
        record.expires_at = expiry

    record.last_synced_at = utcnow()
    return True


def apply_lifecycle(record: ServerRecord, client, *, grace_days: int, allow_deletion: bool = True) -> bool:
    """Expire, suspend, or delete a server according to its expiry date.

    Returns True when the server was deleted. ``allow_deletion=False`` runs
    everything except the destructive step, which lets the caller cap how much
    damage a single sweep can do.
    """
    if record.status == ServerStatus.DELETED or not record.expires_at:
        return False

    now = utcnow()

    if now > record.expires_at and record.status not in {ServerStatus.EXPIRED, ServerStatus.DELETED}:
        record.status = ServerStatus.EXPIRED
        try:
            client.suspend_server(record.pelican_server_id)
            log.info("Suspended expired server %s", record.id)
        except PanelError as exc:
            log.warning("Could not suspend expired server %s: %s", record.id, exc)

    due_for_deletion = record.status == ServerStatus.EXPIRED and now > record.expires_at + timedelta(
        days=grace_days
    )
    if due_for_deletion:
        if not allow_deletion:
            log.warning(
                "Server %s is due for deletion but the per-run cap was reached; "
                "it will be reconsidered on the next sweep.",
                record.id,
            )
            return False
        try:
            client.delete_server(record.pelican_server_id)
            record.status = ServerStatus.DELETED
            log.info("Deleted server %s after %s day grace period", record.id, grace_days)
            return True
        except PanelError as exc:
            # Never mark the record deleted when the panel refused: that would
            # orphan a server that is still running and still costing money.
            log.warning("Could not delete expired server %s: %s", record.id, exc)

    return False


def sync_user_servers(
    user_id: int,
    client,
    *,
    grace_days: int,
    force: bool = False,
    max_records: int | None = MAX_USER_SYNC_PER_REQUEST,
) -> int:
    """Sync a single user's servers, skipping ones synced recently.

    Used by the account page so the request does not fan out on every load.
    """
    threshold = utcnow() - SYNC_STALE_AFTER
    query = ServerRecord.query.filter(
        ServerRecord.user_id == user_id, ServerRecord.status != ServerStatus.DELETED
    ).order_by(ServerRecord.last_synced_at.is_(None).desc(), ServerRecord.last_synced_at.asc())
    if not force:
        query = query.filter(or_(ServerRecord.last_synced_at.is_(None), ServerRecord.last_synced_at <= threshold))
    if max_records is not None:
        query = query.limit(max_records)
    servers = query.all()
    synced = 0
    for record in servers:
        if not sync_server(record, client):
            break
        apply_lifecycle(record, client, grace_days=grace_days)
        synced += 1
    if synced:
        db.session.commit()
    return synced


def sync_all_servers(
    client, *, grace_days: int, limit: int = 500, max_deletions: int = MAX_DELETIONS_PER_RUN
) -> dict:
    """Sweep every live server. Intended for the scheduled job.

    ``max_deletions`` bounds how many servers one run may destroy. Without it,
    a long cron outage or a bad expiry import would delete the entire fleet in
    a single pass with no chance to intervene. Anything over the cap is simply
    reconsidered next run.
    """
    servers = (
        ServerRecord.query.filter(ServerRecord.status != ServerStatus.DELETED)
        .order_by(ServerRecord.last_synced_at.is_(None).desc(), ServerRecord.last_synced_at.asc())
        .limit(limit)
        .all()
    )
    stats = {"checked": 0, "failed": 0, "deleted": 0, "deletions_capped": False}
    for record in servers:
        stats["checked"] += 1
        if not sync_server(record, client):
            stats["failed"] += 1
            continue

        allow_deletion = stats["deleted"] < max_deletions
        if apply_lifecycle(record, client, grace_days=grace_days, allow_deletion=allow_deletion):
            stats["deleted"] += 1
        elif not allow_deletion:
            stats["deletions_capped"] = True

    db.session.commit()
    if stats["deletions_capped"]:
        log.error(
            "Deletion cap of %s reached in one sweep. Investigate before the next run: "
            "this usually means expiry dates are wrong or the job has not run in a long time.",
            max_deletions,
        )
    return stats


def _primary_ip(data: dict) -> str | None:
    try:
        allocations = data["relationships"]["allocations"]["data"]
    except (KeyError, TypeError):
        return None
    for allocation in allocations or []:
        attrs = allocation.get("attributes", {})
        if attrs.get("is_default"):
            return f"{attrs.get('ip')}:{attrs.get('port')}"
    return None


def _expiry_from_description(description: str) -> datetime | None:
    """Read the ``EXP: YYYY-MM-DD`` marker the panel description carries."""
    if "EXP:" not in (description or ""):
        return None
    try:
        raw = description.split("EXP:")[1].strip().split()[0]
        return datetime.strptime(raw, "%Y-%m-%d")
    except (IndexError, ValueError):
        return None
