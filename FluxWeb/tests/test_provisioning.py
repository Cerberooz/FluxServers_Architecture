"""Provisioning behaviour: idempotency, renewals, and the egg fix."""

from __future__ import annotations

from datetime import timedelta

from fluxweb.models import ItemKind, OrderStatus, ServerRecord, ServerStatus
from fluxweb.models.server import utcnow
from fluxweb.services import billing, provisioning
from fluxweb.services.cart import CartItem


class FakePanel:
    """Records what the panel was asked to do."""

    def __init__(self) -> None:
        self.created_servers: list[dict] = []
        self.unsuspended: list[int] = []
        self.descriptions: list[dict] = []
        self.next_id = 500

    # user management
    def get_user(self, panel_id):
        return {"id": panel_id}

    def create_user(self, *, email, username, first_name):
        return 900, "panel-password"

    # metadata
    def get_egg(self, egg_id, *, nest_id=None):
        return {
            "docker_image": f"image-for-egg-{egg_id}",
            "startup": f"start-{egg_id}",
            "relationships": {
                "variables": {
                    "data": [
                        {"attributes": {"env_variable": "SERVER_JARFILE", "default_value": "server.jar"}}
                    ]
                }
            },
        }

    def get_node(self, node_id):
        return {"fqdn": "node.example.com", "name": "Node 1"}

    def find_free_allocation(self, node_id):
        return 77

    def create_allocation(self, node_id, *, ip, port):
        return None

    # servers
    def create_server(self, payload):
        self.created_servers.append(payload)
        self.next_id += 1
        return {
            "attributes": {
                "id": self.next_id,
                "identifier": f"id{self.next_id}",
                "relationships": {
                    "allocations": {
                        "data": [{"attributes": {"is_default": True, "ip": "1.2.3.4", "port": 25565}}]
                    }
                },
            }
        }

    def get_server(self, panel_server_id, include_allocations=False):
        return {"id": panel_server_id, "allocation": 77, "user": 900, "name": "Existing"}

    def update_build(self, panel_server_id, **kwargs):
        return None

    def update_description(self, panel_server_id, *, name, description, user_id):
        self.descriptions.append({"id": panel_server_id, "description": description})

    def unsuspend_server(self, panel_server_id):
        self.unsuspended.append(panel_server_id)


class TestIdempotency:
    """C-5: replayed webhooks must not provision twice."""

    def test_provisioning_twice_creates_one_server(self, db, user, plan):
        order = billing.build_order(user, [CartItem(kind=ItemKind.NEW, plan_id=plan.id)])
        order.mark_paid()
        db.session.commit()

        panel = FakePanel()
        first = provisioning.provision_order(order, panel, expiry_days=30)
        second = provisioning.provision_order(order, panel, expiry_days=30)

        assert first.success_count == 1
        assert second.success_count == 0
        assert len(panel.created_servers) == 1
        assert ServerRecord.query.count() == 1
        assert order.status == OrderStatus.COMPLETED

    def test_unpaid_order_is_not_provisioned(self, db, user, plan):
        order = billing.build_order(user, [CartItem(kind=ItemKind.NEW, plan_id=plan.id)])
        panel = FakePanel()
        result = provisioning.provision_order(order, panel, expiry_days=30)
        assert result.success_count == 0
        assert panel.created_servers == []

    def test_concurrent_callers_cannot_both_provision(self, db, user, plan):
        """Two webhook deliveries racing must produce one server, not two.

        Checking `item.is_fulfilled` in Python is not enough: both callers can
        read "unfulfilled" before either writes. Only one may claim the order.
        """
        order = billing.build_order(user, [CartItem(kind=ItemKind.NEW, plan_id=plan.id)])
        order.mark_paid()
        db.session.commit()

        panel = FakePanel()

        # Simulate the second caller arriving while the first still holds the
        # claim: provisioning is in PROVISIONING and has fulfilled nothing yet.
        order.status = OrderStatus.PROVISIONING
        db.session.commit()

        result = provisioning.provision_order(order, panel, expiry_days=30)

        assert result.success_count == 0
        assert panel.created_servers == []
        assert ServerRecord.query.count() == 0

    def test_a_failed_order_can_still_be_retried(self, db, user, plan):
        order = billing.build_order(user, [CartItem(kind=ItemKind.NEW, plan_id=plan.id)])
        order.mark_paid()
        order.status = OrderStatus.FAILED
        db.session.commit()

        result = provisioning.provision_order(order, FakePanel(), expiry_days=30)

        assert result.success_count == 1
        assert order.status == OrderStatus.COMPLETED


class TestRenewal:
    """M-20: a renewal must extend the existing server, not create a new one."""

    def test_renewal_extends_expiry_and_creates_no_server(self, db, user, plan, server):
        original_expiry = utcnow() + timedelta(days=5)
        server.expires_at = original_expiry
        db.session.commit()

        order = billing.build_order(
            user, [CartItem(kind=ItemKind.RENEWAL, plan_id=plan.id, server_id=server.id)]
        )
        order.mark_paid()
        db.session.commit()

        panel = FakePanel()
        result = provisioning.provision_order(order, panel, expiry_days=30)

        assert result.success_count == 1
        assert panel.created_servers == []  # nothing new was created
        assert ServerRecord.query.count() == 1
        assert server.expires_at > original_expiry  # and time was added
        assert (server.expires_at - original_expiry).days == 30

    def test_renewing_an_expired_server_reactivates_it(self, db, user, plan, server):
        server.status = ServerStatus.EXPIRED
        server.expires_at = utcnow() - timedelta(days=2)
        db.session.commit()

        order = billing.build_order(
            user, [CartItem(kind=ItemKind.RENEWAL, plan_id=plan.id, server_id=server.id)]
        )
        order.mark_paid()
        db.session.commit()

        panel = FakePanel()
        provisioning.provision_order(order, panel, expiry_days=30)

        assert server.status == ServerStatus.ACTIVE
        assert server.pelican_server_id in panel.unsuspended
        assert server.expires_at > utcnow()


class TestEggSelection:
    """M-21: the payload egg and the metadata egg must be the same one."""

    def test_software_override_uses_one_egg_consistently(self, db, user, plan):
        plan.game = "discord_bot"
        plan.egg_id = 1
        db.session.commit()

        order = billing.build_order(user, [CartItem(kind=ItemKind.NEW, plan_id=plan.id, software="python")])
        order.mark_paid()
        db.session.commit()

        panel = FakePanel()
        provisioning.provision_order(order, panel, expiry_days=30)

        payload = panel.created_servers[0]
        assert payload["egg"] == 232  # Python egg
        assert payload["docker_image"] == "image-for-egg-232"  # metadata from the same egg
        assert payload["startup"] == "start-232"


class TestUpgradeProvisioning:
    def test_upgrade_rewrites_plan_without_new_server(self, db, user, server, bigger_plan):
        order = billing.build_order(
            user, [CartItem(kind=ItemKind.UPGRADE, plan_id=bigger_plan.id, server_id=server.id)]
        )
        order.mark_paid()
        db.session.commit()

        panel = FakePanel()
        provisioning.provision_order(order, panel, expiry_days=30)

        assert panel.created_servers == []
        assert server.plan_id == bigger_plan.id
        assert server.plan_name == bigger_plan.name
