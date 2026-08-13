from __future__ import annotations

import json
from io import BytesIO

from fluxweb.models import GamePlan


def _make_admin(db, user):
    user.is_admin = True
    db.session.commit()
    return user


class TestPlanImport:
    def test_import_preserves_node_and_string_fields(self, client, db, user, login):
        login(_make_admin(db, user))

        payload = [
            {
                "game": "minecraft",
                "name": "Obsidian",
                "price": "12.50",
                "memory": "12288",
                "cpu": "400",
                "disk": "204800",
                "nest_id": "General",
                "egg_id": "1",
                "location_id": "7",
                "backups": "5",
                "allocations": "3",
                "databases": "2",
                "features": "12 GB RAM\n200 GB NVMe",
                "is_featured": "false",
                "sub_type": "Minecraft",
                "serial_number": "4",
            }
        ]

        response = client.post(
            "/admin/plans/import",
            data={
                "plans_file": (
                    BytesIO(json.dumps(payload).encode("utf-8")),
                    "plans.json",
                )
            },
            content_type="multipart/form-data",
        )

        assert response.status_code == 302
        plan = GamePlan.query.filter_by(name="Obsidian", game="minecraft").one()
        assert plan.location_id == 7
        assert plan.feature_list == ["12 GB RAM", "200 GB NVMe"]
        assert plan.is_featured is False

    def test_import_accepts_wrapped_plans_array(self, client, db, user, login):
        login(_make_admin(db, user))

        payload = {
            "plans": [
                {
                    "game": "discord_bot",
                    "name": "Bot Pro",
                    "location_id": 3,
                    "features": ["2 GB RAM"],
                    "is_featured": True,
                }
            ]
        }

        response = client.post(
            "/admin/plans/import",
            data={
                "plans_file": (
                    BytesIO(json.dumps(payload).encode("utf-8")),
                    "plans.json",
                )
            },
            content_type="multipart/form-data",
        )

        assert response.status_code == 302
        plan = GamePlan.query.filter_by(name="Bot Pro", game="discord_bot").one()
        assert plan.location_id == 3
        assert plan.feature_list == ["2 GB RAM"]
        assert plan.is_featured is True


class TestPlanExport:
    def test_export_includes_location_id(self, client, db, user, plan, login):
        login(_make_admin(db, user))
        plan.location_id = 9
        db.session.commit()

        response = client.get("/admin/plans/export")

        assert response.status_code == 200
        data = response.get_json()
        exported = next(item for item in data if item["name"] == plan.name)
        assert exported["location_id"] == 9
