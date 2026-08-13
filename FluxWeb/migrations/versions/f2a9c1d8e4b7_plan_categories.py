"""Plan categories and subcategories.

Revision ID: f2a9c1d8e4b7
Revises: e8f1b7a4c2d9
Create Date: 2026-08-11
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "f2a9c1d8e4b7"
down_revision = "e8f1b7a4c2d9"
branch_labels = None
depends_on = None


DEFAULT_CATEGORIES = (
    ("minecraft", "Minecraft Plans", 10),
    ("hytale", "Hytale Plans", 20),
    ("discord_bot", "Discord Bot Plans", 30),
    ("dedicated", "Bare Metal Plans", 40),
)


def upgrade() -> None:
    op.create_table(
        "plan_category",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_plan_category_slug", "plan_category", ["slug"], unique=True)
    op.create_index("ix_plan_category_sort", "plan_category", ["sort_order"], unique=False)

    op.create_table(
        "plan_subcategory",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("slug", sa.String(length=40), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(["category_id"], ["plan_category.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("category_id", "slug", name="uq_plan_subcategory_category_slug"),
    )
    op.create_index(
        "ix_plan_subcategory_category_sort",
        "plan_subcategory",
        ["category_id", "sort_order"],
        unique=False,
    )

    with op.batch_alter_table("game_plan", schema=None) as batch_op:
        batch_op.add_column(sa.Column("category_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("subcategory_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_game_plan_category_id_plan_category",
            "plan_category",
            ["category_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_game_plan_subcategory_id_plan_subcategory",
            "plan_subcategory",
            ["subcategory_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_game_plan_category_serial",
        "game_plan",
        ["category_id", "subcategory_id", "serial_number"],
        unique=False,
    )

    category = sa.table(
        "plan_category",
        sa.column("id", sa.Integer()),
        sa.column("name", sa.String()),
        sa.column("slug", sa.String()),
        sa.column("sort_order", sa.Integer()),
        sa.column("is_active", sa.Boolean()),
    )
    op.bulk_insert(
        category,
        [
            {"name": name, "slug": slug, "sort_order": sort_order, "is_active": True}
            for slug, name, sort_order in DEFAULT_CATEGORIES
        ],
    )

    conn = op.get_bind()
    for slug, _name, _sort_order in DEFAULT_CATEGORIES:
        category_id = conn.execute(
            sa.text("SELECT id FROM plan_category WHERE slug = :slug"),
            {"slug": slug},
        ).scalar()
        conn.execute(
            sa.text("UPDATE game_plan SET category_id = :category_id WHERE game = :slug"),
            {"category_id": category_id, "slug": slug},
        )


def downgrade() -> None:
    op.drop_index("ix_game_plan_category_serial", table_name="game_plan")

    with op.batch_alter_table("game_plan", schema=None) as batch_op:
        batch_op.drop_constraint("fk_game_plan_subcategory_id_plan_subcategory", type_="foreignkey")
        batch_op.drop_constraint("fk_game_plan_category_id_plan_category", type_="foreignkey")
        batch_op.drop_column("subcategory_id")
        batch_op.drop_column("category_id")

    op.drop_index("ix_plan_subcategory_category_sort", table_name="plan_subcategory")
    op.drop_table("plan_subcategory")
    op.drop_index("ix_plan_category_sort", table_name="plan_category")
    op.drop_index("ix_plan_category_slug", table_name="plan_category")
    op.drop_table("plan_category")
