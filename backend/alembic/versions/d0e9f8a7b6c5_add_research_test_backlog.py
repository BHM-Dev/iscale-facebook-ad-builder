"""add research test backlog

Revision ID: d0e9f8a7b6c5
Revises: c9d8e7f6a5b4
"""
from alembic import op
import sqlalchemy as sa

revision = "d0e9f8a7b6c5"
down_revision = "c9d8e7f6a5b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table("research_test_backlog_items"):
        return
    op.create_table(
        "research_test_backlog_items",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("vertical_id", sa.String(), nullable=False),
        sa.Column("advertiser", sa.String(), nullable=True),
        sa.Column("scraped_ad_id", sa.String(), sa.ForeignKey("scraped_ads.id", ondelete="SET NULL"), nullable=True),
        sa.Column("hypothesis", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="draft"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("generated_ad_id", sa.String(), sa.ForeignKey("generated_ads.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_by", sa.String(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
    )
    op.create_index("ix_research_test_backlog_items_vertical_id", "research_test_backlog_items", ["vertical_id"])
    op.create_index("ix_research_test_backlog_items_status", "research_test_backlog_items", ["status"])
    op.create_index("ix_research_test_backlog_items_scraped_ad_id", "research_test_backlog_items", ["scraped_ad_id"])
    op.create_index("ix_research_test_backlog_items_created_by", "research_test_backlog_items", ["created_by"])


def downgrade() -> None:
    op.drop_table("research_test_backlog_items")
