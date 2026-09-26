"""add workspace shared launch packs

Revision ID: a4b5c6d7e8f9
Revises: a85ca30c53fb
Create Date: 2026-09-26
"""
from alembic import op
import sqlalchemy as sa

revision = "a4b5c6d7e8f9"
down_revision = "a85ca30c53fb"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    import sqlalchemy as sa_inspect
    if sa_inspect.inspect(bind).has_table("launch_packs"):
        return
    op.create_table(
        "launch_packs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("ad_account_id", sa.String(), nullable=False),
        sa.Column("ad_account_name", sa.String(), nullable=True),
        sa.Column("campaign_id", sa.String(), nullable=False),
        sa.Column("campaign_name", sa.String(), nullable=True),
        sa.Column("adset_id", sa.String(), nullable=False),
        sa.Column("adset_name", sa.String(), nullable=True),
        sa.Column("created_by", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ad_account_id", "campaign_id", "adset_id", name="uq_launch_pack_target"),
    )
    op.create_index("ix_launch_packs_ad_account_id", "launch_packs", ["ad_account_id"])


def downgrade() -> None:
    op.drop_index("ix_launch_packs_ad_account_id", table_name="launch_packs")
    op.drop_table("launch_packs")
