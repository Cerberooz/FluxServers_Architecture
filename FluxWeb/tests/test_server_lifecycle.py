"""Server lifecycle: sync, expiry, suspension, and deletion.

This is the code that destroys customer data, so it gets explicit coverage of
both directions: it must delete when it should, and it must NOT delete when it
shouldn't.
"""

from __future__ import annotations

from datetime import timedelta

from fluxweb.errors import PanelError
from fluxweb.models import ServerRecord, ServerStatus
from fluxweb.models.server import utcnow
from fluxweb.services import servers as server_service


class FakePanel:
    def __init__(self, *, server_payload=None, missing=False, failing=False):
        self.suspended: list[int] = []
        self.deleted: list[int] = []
        self.server_requests: list[int] = []
        self.missing = missing
        self.failing = failing
        self.server_payload = server_payload or {
            "suspended": False,
            "name": "Synced Name",
            "description": "",
            "node": 3,
            "relationships": {
                "allocations": {
                    "data": [{"attributes": {"is_default": True, "ip": "10.0.0.1", "port": 25565}}]
                }
            },
        }

    def get_server(self, panel_server_id, include_allocations=False):
        self.server_requests.append(panel_server_id)
        if self.failing:
            raise PanelError("panel down", status=502)
        return None if self.missing else self.server_payload

    def get_node(self, node_id):
        return {"name": "Frankfurt-1"}

    def suspend_server(self, panel_server_id):
        if self.failing:
            raise PanelError("panel down", status=502)
        self.suspended.append(panel_server_id)

    def delete_server(self, panel_server_id):
        if self.failing:
            raise PanelError("panel down", status=502)
        self.deleted.append(panel_server_id)


class TestSync:
    def test_sync_pulls_name_ip_and_node(self, db, server):
        panel = FakePanel()
        assert server_service.sync_server(server, panel) is True
        assert server.plan_name == "Synced Name"
        assert server.ip_address == "10.0.0.1:25565"
        assert server.node_name == "Frankfurt-1"
        assert server.last_synced_at is not None

    def test_missing_on_panel_marks_deleted(self, db, server):
        assert server_service.sync_server(server, FakePanel(missing=True)) is True
        assert server.status == ServerStatus.DELETED

    def test_panel_outage_reports_failure_and_changes_nothing(self, db, server):
        server.status = ServerStatus.ACTIVE
        db.session.commit()

        assert server_service.sync_server(server, FakePanel(failing=True)) is False
        # A panel outage must never be mistaken for "server gone".
        assert server.status == ServerStatus.ACTIVE

    def test_suspended_on_panel_is_reflected(self, db, server):
        panel = FakePanel(server_payload={"suspended": True, "name": "x", "description": ""})
        server_service.sync_server(server, panel)
        assert server.status == ServerStatus.SUSPENDED

    def test_expiry_is_read_from_panel_description(self, db, server):
        panel = FakePanel(server_payload={"suspended": False, "name": "x", "description": "EXP: 2030-01-15"})
        server_service.sync_server(server, panel)
        assert server.expires_at.strftime("%Y-%m-%d") == "2030-01-15"

    def test_malformed_expiry_is_ignored(self, db, server):
        original = server.expires_at
        panel = FakePanel(server_payload={"suspended": False, "name": "x", "description": "EXP: not-a-date"})
        server_service.sync_server(server, panel)
        assert server.expires_at == original


class TestExpiry:
    def test_active_server_in_date_is_untouched(self, db, server):
        server.expires_at = utcnow() + timedelta(days=5)
        server.status = ServerStatus.ACTIVE
        db.session.commit()

        panel = FakePanel()
        server_service.apply_lifecycle(server, panel, grace_days=7)

        assert server.status == ServerStatus.ACTIVE
        assert panel.suspended == []
        assert panel.deleted == []

    def test_expired_server_is_suspended_not_deleted(self, db, server):
        server.expires_at = utcnow() - timedelta(days=1)
        server.status = ServerStatus.ACTIVE
        db.session.commit()

        panel = FakePanel()
        server_service.apply_lifecycle(server, panel, grace_days=7)

        assert server.status == ServerStatus.EXPIRED
        assert panel.suspended == [server.pelican_server_id]
        assert panel.deleted == []

    def test_deleted_only_after_the_grace_period(self, db, server):
        server.expires_at = utcnow() - timedelta(days=8)
        server.status = ServerStatus.ACTIVE
        db.session.commit()

        panel = FakePanel()
        server_service.apply_lifecycle(server, panel, grace_days=7)

        assert server.status == ServerStatus.DELETED
        assert panel.deleted == [server.pelican_server_id]

    def test_inside_grace_period_survives(self, db, server):
        server.expires_at = utcnow() - timedelta(days=6)
        server.status = ServerStatus.EXPIRED
        db.session.commit()

        panel = FakePanel()
        server_service.apply_lifecycle(server, panel, grace_days=7)

        assert panel.deleted == []
        assert server.status == ServerStatus.EXPIRED

    def test_server_with_no_expiry_is_never_touched(self, db, server):
        server.expires_at = None
        db.session.commit()

        panel = FakePanel()
        server_service.apply_lifecycle(server, panel, grace_days=7)

        assert panel.suspended == []
        assert panel.deleted == []

    def test_panel_failure_during_delete_leaves_record_intact(self, db, server):
        server.expires_at = utcnow() - timedelta(days=30)
        server.status = ServerStatus.EXPIRED
        db.session.commit()

        server_service.apply_lifecycle(server, FakePanel(failing=True), grace_days=7)

        # The panel refused; the record must not claim the server is gone.
        assert server.status == ServerStatus.EXPIRED


class TestBulkSafety:
    def test_a_single_run_cannot_delete_the_whole_fleet(self, db, user, plan):
        """A bad expiry import or a long cron outage must not mass-delete."""
        for index in range(10):
            db.session.add(
                ServerRecord(
                    user_id=user.id,
                    plan_id=plan.id,
                    plan_name="p",
                    pelican_server_id=1000 + index,
                    pelican_server_identifier=f"srv{index}",
                    status=ServerStatus.EXPIRED,
                    expires_at=utcnow() - timedelta(days=99),
                )
            )
        db.session.commit()

        panel = FakePanel()
        stats = server_service.sync_all_servers(panel, grace_days=7, max_deletions=3)

        assert len(panel.deleted) == 3
        assert stats["deleted"] == 3
        assert stats["deletions_capped"] is True


class TestThrottling:
    def test_recently_synced_servers_are_skipped(self, db, server, user):
        server.last_synced_at = utcnow()
        db.session.commit()

        panel = FakePanel()
        synced = server_service.sync_user_servers(user.id, panel, grace_days=7)
        assert synced == 0

    def test_force_overrides_the_throttle(self, db, server, user):
        server.last_synced_at = utcnow()
        db.session.commit()

        panel = FakePanel()
        synced = server_service.sync_user_servers(user.id, panel, grace_days=7, force=True)
        assert synced == 1

    def test_account_sync_limits_panel_round_trips(self, db, user, plan):
        for index in range(3):
            db.session.add(
                ServerRecord(
                    user_id=user.id,
                    plan_id=plan.id,
                    plan_name=f"Server {index}",
                    pelican_server_id=2000 + index,
                    pelican_server_identifier=f"user{index}",
                    status=ServerStatus.ACTIVE,
                )
            )
        db.session.commit()

        panel = FakePanel()
        synced = server_service.sync_user_servers(user.id, panel, grace_days=7, max_records=1)

        assert synced == 1
        assert len(panel.server_requests) == 1

    def test_account_sync_stops_after_panel_failure(self, db, user, plan):
        for index in range(3):
            db.session.add(
                ServerRecord(
                    user_id=user.id,
                    plan_id=plan.id,
                    plan_name=f"Server {index}",
                    pelican_server_id=3000 + index,
                    pelican_server_identifier=f"down{index}",
                    status=ServerStatus.ACTIVE,
                )
            )
        db.session.commit()

        panel = FakePanel(failing=True)
        synced = server_service.sync_user_servers(user.id, panel, grace_days=7, max_records=10)

        assert synced == 0
        assert len(panel.server_requests) == 1
