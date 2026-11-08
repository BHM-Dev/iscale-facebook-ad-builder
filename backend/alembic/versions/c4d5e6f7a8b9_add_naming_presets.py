"""add naming presets (shared per-ad-account naming convention)"""
from alembic import op
import sqlalchemy as sa

revision = "c4d5e6f7a8b9"
down_revision = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    # init_db's create_all runs first and may already have built this table.
    if sa.inspect(bind).has_table("naming_presets"):
        return
    op.create_table(
        "naming_presets",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("ad_account_id", sa.String(), nullable=False),
        sa.Column("brand_code", sa.String(), nullable=True),
        sa.Column("tracking_tag", sa.String(), nullable=True),
        sa.Column("uppercase", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("templates", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("waves", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("niche_codes", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("objective_tags", sa.JSON(), nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("variant", sa.String(), nullable=True),
        sa.Column("soft_tags", sa.JSON(), nullable=True),
        sa.Column("updated_by", sa.String(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_naming_presets_ad_account_id", "naming_presets", ["ad_account_id"], unique=True)


def downgrade():
    if sa.inspect(op.get_bind()).has_table("naming_presets"):
        op.drop_table("naming_presets")
