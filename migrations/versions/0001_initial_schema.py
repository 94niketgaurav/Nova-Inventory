"""Initial schema

Revision ID: 0001
Revises:
Create Date: 2026-02-26
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "menu_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("price", sa.Numeric(10, 2), nullable=False),
        sa.Column("stock_quantity", sa.Integer, nullable=False, server_default="0"),
        sa.Column("low_stock_threshold", sa.Integer, nullable=False, server_default="10"),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("stock_quantity >= 0", name="ck_menu_items_stock_non_negative"),
        sa.CheckConstraint("price > 0", name="ck_menu_items_price_positive"),
        sa.CheckConstraint("low_stock_threshold >= 0", name="ck_menu_items_threshold_non_negative"),
        sa.UniqueConstraint("name", name="uq_menu_items_name"),
    )

    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("menu_items.id"), nullable=False),
        sa.Column("quantity", sa.Integer, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("customer_ref", sa.String(255), nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.CheckConstraint("quantity > 0", name="ck_orders_quantity_positive"),
    )

    op.create_table(
        "stock_movements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("menu_items.id"), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id"), nullable=True),
        sa.Column("movement_type", sa.Text, nullable=False),
        sa.Column("quantity_delta", sa.Integer, nullable=False),
        sa.Column("stock_before", sa.Integer, nullable=False),
        sa.Column("stock_after", sa.Integer, nullable=False),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # Indexes for common queries
    op.create_index("ix_orders_item_id", "orders", ["item_id"])
    op.create_index("ix_orders_status", "orders", ["status"])
    op.create_index("ix_stock_movements_item_id", "stock_movements", ["item_id"])
    op.create_index("ix_stock_movements_order_id", "stock_movements", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_stock_movements_order_id", table_name="stock_movements")
    op.drop_index("ix_stock_movements_item_id", table_name="stock_movements")
    op.drop_index("ix_orders_status", table_name="orders")
    op.drop_index("ix_orders_item_id", table_name="orders")
    op.drop_table("stock_movements")
    op.drop_table("orders")
    op.drop_table("menu_items")
