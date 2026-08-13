"""Hosting plans.

Column names are preserved exactly so this maps onto the existing production
table with no data migration. The misleading names flagged in the architecture
review (``location_id`` holds a *node* id, ``nest_id`` holds an egg *tag*) are
documented here and exposed under accurate aliases; renaming the columns is a
separate migration.
"""

from __future__ import annotations

import json

from fluxweb.extensions import db
from fluxweb.money import to_cents


class PlanCategory(db.Model):
    __tablename__ = "plan_category"
    __table_args__ = (
        db.Index("ix_plan_category_slug", "slug", unique=True),
        db.Index("ix_plan_category_sort", "sort_order"),
    )

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    slug = db.Column(db.String(40), nullable=False)
    description = db.Column(db.Text, nullable=True)
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)

    subcategories = db.relationship(
        "PlanSubcategory",
        back_populates="category",
        cascade="all, delete-orphan",
        order_by="PlanSubcategory.sort_order.asc(), PlanSubcategory.name.asc()",
    )
    plans = db.relationship("GamePlan", back_populates="category")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PlanCategory {self.slug}>"


class PlanSubcategory(db.Model):
    __tablename__ = "plan_subcategory"
    __table_args__ = (
        db.Index("ix_plan_subcategory_category_sort", "category_id", "sort_order"),
        db.UniqueConstraint("category_id", "slug", name="uq_plan_subcategory_category_slug"),
    )

    id = db.Column(db.Integer, primary_key=True)
    category_id = db.Column(db.Integer, db.ForeignKey("plan_category.id", ondelete="CASCADE"), nullable=False)
    name = db.Column(db.String(80), nullable=False)
    slug = db.Column(db.String(40), nullable=False)
    description = db.Column(db.Text, nullable=True)
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)

    category = db.relationship("PlanCategory", back_populates="subcategories")
    plans = db.relationship("GamePlan", back_populates="subcategory")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PlanSubcategory {self.category_id}/{self.slug}>"


class GamePlan(db.Model):
    __tablename__ = "game_plan"
    __table_args__ = (
        db.Index("ix_game_plan_game_serial", "game", "serial_number"),
        db.Index("ix_game_plan_category_serial", "category_id", "subcategory_id", "serial_number"),
        db.Index("ix_game_plan_featured", "is_featured"),
    )

    id = db.Column(db.Integer, primary_key=True)
    game = db.Column(db.String(20))  # 'minecraft' | 'hytale' | 'dedicated' | 'discord_bot'
    name = db.Column(db.String(50))
    price = db.Column(db.Float)

    # Legacy columns, superseded by `features`. Retained so the existing table
    # still matches; nothing writes to them any more (audit M-3).
    feature1 = db.Column(db.String(100))
    feature2 = db.Column(db.String(100))
    feature3 = db.Column(db.String(100))
    feature4 = db.Column(db.String(100))
    features = db.Column(db.Text, default="[]")

    is_featured = db.Column(db.Boolean, default=False)

    memory = db.Column(db.Integer, default=1024)  # MB
    cpu = db.Column(db.Integer, default=100)  # percent
    disk = db.Column(db.Integer, default=5120)  # MB

    #: Egg *tag* despite the name, e.g. "General" (see architecture review M-2).
    nest_id = db.Column(db.String(50), default="General")
    egg_id = db.Column(db.Integer, default=1)
    #: JSON list of eggs customers may select for this plan. The legacy egg is
    #: retained as the default for existing plans.
    allowed_egg_ids = db.Column(db.Text, default="[]")
    #: Fluid panel *node* id despite the name.
    location_id = db.Column(db.Integer, default=1)
    #: JSON list of allowed node ids for checkout selection. When empty, the
    #: legacy single `location_id` remains the only allowed node.
    allowed_location_ids = db.Column(db.Text, default="[]")

    backups = db.Column(db.Integer, default=1)
    allocations = db.Column(db.Integer, default=1)
    databases = db.Column(db.Integer, default=1)

    sub_type = db.Column(db.String(30))
    serial_number = db.Column(db.Integer, default=0)
    image_url = db.Column(db.Text, nullable=True)
    category_id = db.Column(db.Integer, db.ForeignKey("plan_category.id", ondelete="SET NULL"), nullable=True)
    subcategory_id = db.Column(
        db.Integer, db.ForeignKey("plan_subcategory.id", ondelete="SET NULL"), nullable=True
    )

    category = db.relationship("PlanCategory", back_populates="plans")
    subcategory = db.relationship("PlanSubcategory", back_populates="plans")

    # --- accurate aliases ----------------------------------------------
    @property
    def category_slug(self) -> str:
        return self.category.slug if self.category else self.game

    @property
    def category_name(self) -> str:
        return self.category.name if self.category else (self.game or "Uncategorized").replace("_", " ").title()

    @property
    def subcategory_name(self) -> str:
        return self.subcategory.name if self.subcategory else "Default"

    @property
    def node_id(self) -> int:
        """The Fluid panel node this plan deploys to (stored as `location_id`)."""
        return self.location_id

    @property
    def egg_tag(self) -> str:
        """The egg tag used to group eggs (stored as `nest_id`)."""
        return self.nest_id

    @property
    def allowed_node_ids(self) -> list[int]:
        values: list[int] = []
        if self.allowed_location_ids and self.allowed_location_ids != "[]":
            try:
                parsed = json.loads(self.allowed_location_ids)
                if isinstance(parsed, list):
                    for value in parsed:
                        try:
                            node_id = int(value)
                        except (TypeError, ValueError):
                            continue
                        if node_id > 0 and node_id not in values:
                            values.append(node_id)
            except (ValueError, TypeError):
                pass
        if not values and self.location_id:
            values.append(int(self.location_id))
        return values

    def set_allowed_node_ids(self, values: list[int]) -> None:
        cleaned: list[int] = []
        for value in values:
            try:
                node_id = int(value)
            except (TypeError, ValueError):
                continue
            if node_id > 0 and node_id not in cleaned:
                cleaned.append(node_id)
        self.allowed_location_ids = json.dumps(cleaned)
        if cleaned:
            self.location_id = cleaned[0]

    @property
    def allowed_eggs(self) -> list[int]:
        try:
            values = json.loads(self.allowed_egg_ids or "[]")
        except (TypeError, ValueError):
            values = []
        cleaned = [int(value) for value in values if str(value).isdigit() and int(value) > 0]
        return list(dict.fromkeys(cleaned)) or ([int(self.egg_id)] if self.egg_id else [])

    def set_allowed_eggs(self, values: list[int]) -> None:
        cleaned = [int(value) for value in values if str(value).isdigit() and int(value) > 0]
        cleaned = list(dict.fromkeys(cleaned))
        self.allowed_egg_ids = json.dumps(cleaned)
        if cleaned:
            self.egg_id = cleaned[0]

    # --- derived --------------------------------------------------------
    @property
    def price_cents(self) -> int:
        return to_cents(self.price)

    @property
    def feature_list(self) -> list[str]:
        if self.features and self.features != "[]":
            try:
                parsed = json.loads(self.features)
                if isinstance(parsed, list):
                    return [str(f) for f in parsed]
            except (ValueError, TypeError):
                pass
        return [f for f in (self.feature1, self.feature2, self.feature3, self.feature4) if f]

    def __repr__(self) -> str:  # pragma: no cover
        return f"<GamePlan {self.id} {self.game}/{self.name}>"
