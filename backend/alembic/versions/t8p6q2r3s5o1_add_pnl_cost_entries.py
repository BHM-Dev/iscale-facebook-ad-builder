"""add pnl_cost_entries + pnl permissions

Revision ID: t8p6q2r3s5o1
Revises: s7o5p1q2r4n0
Create Date: 2026-07-27

Backing table for the P&L tracker. Ad spend comes from Meta and revenue from
RedTrack; this table holds everything else that eats into net profit —
retainers, commissions, tooling subscriptions, creative platform credits.

`ad_account_id` NULL = the cost spans every account (Abel's retainer), split at
read time per `allocation_method`.

Also seeds the `pnl:read` / `pnl:write` permissions and grants them to the
admin and manager roles. Superusers bypass permission checks entirely
(User.has_permission), so Steve gets access without a role change; Joel needs
admin or manager. Done here rather than only in init_db.py because
seed_roles_and_permissions() attaches permissions to a role only at creation
time — existing roles would never pick these up.
"""
from alembic import op
import sqlalchemy as sa
import uuid


revision = 't8p6q2r3s5o1'
down_revision = 's7o5p1q2r4n0'
branch_labels = None
depends_on = None


PNL_PERMISSIONS = [
    ('pnl:read', 'View the P&L tracker'),
    ('pnl:write', 'Add and edit P&L cost entries'),
]

GRANT_TO_ROLES = ['admin', 'manager']


def upgrade() -> None:
    bind = op.get_bind()

    # NOTE: init_db.py runs Base.metadata.create_all() before alembic, so on a
    # real deploy the table already exists and this create_table() never fires.
    # It is here for correctness (fresh DB / alembic-only paths). Keep the
    # columns below character-for-character in sync with models.PnlCostEntry —
    # if they drift, create_all()'s version silently wins and nothing complains.
    if not sa.inspect(bind).has_table('pnl_cost_entries'):
        op.create_table(
            'pnl_cost_entries',
            sa.Column('id', sa.String(), primary_key=True),
            # NULL = applies to all ad accounts, split per allocation_method
            sa.Column('ad_account_id', sa.String(), nullable=True, index=True),
            sa.Column('label', sa.String(), nullable=False),
            # labor|tooling|creative|data|other
            sa.Column('category', sa.String(), nullable=False, server_default='other'),
            # one_off|recurring_monthly|pct_of_spend|pct_of_revenue
            # |pct_of_gross_profit|pct_of_profit
            sa.Column('cost_type', sa.String(), nullable=False, server_default='one_off'),
            # dollars, or percent (0-100) for the pct_* types
            sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
            # by_spend|even — only consulted when ad_account_id IS NULL
            sa.Column('allocation_method', sa.String(), nullable=False, server_default='by_spend'),
            sa.Column('effective_from', sa.Date(), nullable=False),
            sa.Column('effective_to', sa.Date(), nullable=True),
            sa.Column('notes', sa.Text(), nullable=True),
            # RESERVED — Phase 3 auto-captured creative platform spend
            sa.Column('vendor', sa.String(), nullable=True),
            sa.Column('source', sa.String(), nullable=False, server_default='manual'),
            sa.Column('created_by', sa.String(), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        )

    # --- seed permissions + grant to roles (idempotent) ---
    inspector = sa.inspect(bind)
    if not (inspector.has_table('permissions') and inspector.has_table('roles')
            and inspector.has_table('role_permissions')):
        return

    for name, description in PNL_PERMISSIONS:
        bind.execute(
            sa.text("""
                INSERT INTO permissions (id, name, description, created_at)
                SELECT :pid, :name, :description, NOW()
                WHERE NOT EXISTS (SELECT 1 FROM permissions WHERE name = :name)
            """),
            {"pid": str(uuid.uuid4()), "name": name, "description": description},
        )

        # Expanding IN rather than `= ANY(:roles)`: binding a Python list to a
        # Postgres array through plain text() relies on driver auto-adaptation
        # that SQLAlchemy doesn't guarantee. Expanding IN is dialect-portable.
        bind.execute(
            sa.text("""
                INSERT INTO role_permissions (role_id, permission_id, created_at)
                SELECT r.id, p.id, NOW()
                FROM roles r
                CROSS JOIN permissions p
                WHERE r.name IN :roles
                  AND p.name = :name
                  AND NOT EXISTS (
                      SELECT 1 FROM role_permissions rp
                      WHERE rp.role_id = r.id AND rp.permission_id = p.id
                  )
            """).bindparams(sa.bindparam("roles", expanding=True)),
            {"roles": GRANT_TO_ROLES, "name": name},
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table('permissions') and inspector.has_table('role_permissions'):
        names = [name for name, _ in PNL_PERMISSIONS]
        bind.execute(
            sa.text("""
                DELETE FROM role_permissions
                WHERE permission_id IN (SELECT id FROM permissions WHERE name IN :names)
            """).bindparams(sa.bindparam("names", expanding=True)),
            {"names": names},
        )
        bind.execute(
            sa.text("DELETE FROM permissions WHERE name IN :names")
            .bindparams(sa.bindparam("names", expanding=True)),
            {"names": names},
        )

    if inspector.has_table('pnl_cost_entries'):
        op.drop_table('pnl_cost_entries')
