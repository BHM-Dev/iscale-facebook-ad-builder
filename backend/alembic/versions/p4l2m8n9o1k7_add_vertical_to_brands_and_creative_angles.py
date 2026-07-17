"""add vertical to brands and creative angles table

Revision ID: p4l2m8n9o1k7
Revises: o3k1l7m8n0j6
Create Date: 2026-07-16

Adds vertical_id FK to brands (references existing verticals table).
Creates creative_angles table with seeded angles for auto insurance
and home services verticals.
"""
from alembic import op
import sqlalchemy as sa


revision = 'p4l2m8n9o1k7'
down_revision = 'o3k1l7m8n0j6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # 1. Add vertical_id to brands
    op.execute("""
        ALTER TABLE brands
        ADD COLUMN IF NOT EXISTS vertical_id VARCHAR
        REFERENCES verticals(id) ON DELETE SET NULL
    """)

    # 2. Seed core BHM verticals — safe to re-run
    op.execute("""
        INSERT INTO verticals (id, name, description, created_at, updated_at)
        VALUES
            (gen_random_uuid(), 'Auto Insurance',       'Auto insurance vertical',       now(), now()),
            (gen_random_uuid(), 'Home Services',        'Home services vertical',        now(), now()),
            (gen_random_uuid(), 'Personal Loans',       'Personal loans vertical',       now(), now()),
            (gen_random_uuid(), 'Debt Relief',          'Debt relief vertical',          now(), now()),
            (gen_random_uuid(), 'Commercial Insurance', 'Commercial insurance vertical', now(), now())
        ON CONFLICT (name) DO NOTHING
    """)

    # 3. Create creative_angles table only if it doesn't exist yet
    #    (init_db.py runs Base.metadata.create_all before Alembic, so table may already exist)
    if not sa.inspect(bind).has_table('creative_angles'):
        op.create_table(
            'creative_angles',
            sa.Column('id',          sa.String(), nullable=False, primary_key=True),
            sa.Column('vertical_id', sa.String(), sa.ForeignKey('verticals.id', ondelete='CASCADE'), nullable=True),
            sa.Column('name',        sa.String(), nullable=False),
            sa.Column('hook',        sa.String(), nullable=True),
            sa.Column('headline',    sa.String(), nullable=True),
            sa.Column('body',        sa.Text(),   nullable=True),
            sa.Column('is_active',   sa.Boolean(), server_default='true', nullable=False),
            sa.Column('sort_order',  sa.Integer(), server_default='0',    nullable=False),
            sa.Column('created_at',  sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.Column('updated_at',  sa.DateTime(timezone=True), server_default=sa.func.now()),
            sa.UniqueConstraint('vertical_id', 'name', name='uq_creative_angles_vertical_name'),
        )

    # 4. Ensure unique constraint exists (handles case where init_db created the table without it)
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'uq_creative_angles_vertical_name'
            ) THEN
                ALTER TABLE creative_angles
                ADD CONSTRAINT uq_creative_angles_vertical_name UNIQUE (vertical_id, name);
            END IF;
        END $$
    """)

    # 5. Seed auto insurance angles — idempotent via ON CONFLICT
    op.execute("""
        INSERT INTO creative_angles (id, vertical_id, name, hook, headline, body, is_active, sort_order, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            v.id,
            angle.name,
            angle.hook,
            angle.headline,
            angle.body,
            true,
            angle.sort_order,
            now(),
            now()
        FROM verticals v,
        (VALUES
            (1, 'Rate Shock',
             'Most drivers overpay by $800+/yr',
             'Still paying $180/mo for car insurance?',
             'Drivers in your area are switching and saving an average of $800 a year. It takes 2 minutes to compare rates — no commitment required.'),
            (2, 'Coverage Gap',
             'Your policy might not cover what you think',
             'Does your car insurance actually cover you?',
             'Most drivers don''t know what their policy excludes until it''s too late. Check your coverage free in 60 seconds.'),
            (3, 'Switch & Save',
             'Switching is easier than you think',
             'Switch car insurance in 2 minutes — no paperwork',
             'No cancellation fees. No hassle. Just a better rate. Compare top carriers and switch today without lifting a finger.'),
            (4, 'Good Driver Discount',
             'Clean record = money left on the table',
             'Clean driving record? You''re leaving money on the table.',
             'Good drivers qualify for up to 30% off. See exactly what you qualify for today — takes less than 2 minutes.'),
            (5, 'Comparison Shop',
             'Your renewal is coming — did you shop?',
             'Your renewal is coming. Most drivers never compare.',
             'Rates change every 6 months. Drivers who shop save an average of $600/year. It takes 90 seconds to check.')
        ) AS angle(sort_order, name, hook, headline, body)
        WHERE v.name = 'Auto Insurance'
        ON CONFLICT (vertical_id, name) DO NOTHING
    """)

    # 6. Seed home services angles — idempotent via ON CONFLICT
    op.execute("""
        INSERT INTO creative_angles (id, vertical_id, name, hook, headline, body, is_active, sort_order, created_at, updated_at)
        SELECT
            gen_random_uuid(),
            v.id,
            angle.name,
            angle.hook,
            angle.headline,
            angle.body,
            true,
            angle.sort_order,
            now(),
            now()
        FROM verticals v,
        (VALUES
            (1, 'Seasonal Urgency',
             'Act before the damage gets worse',
             'Spring is the worst time to ignore your gutters.',
             'One clogged gutter can lead to $3,000+ in foundation damage. Get a free inspection from a licensed local pro before the rain hits.'),
            (2, 'Price Anchor',
             'Most homeowners overpay by 40%',
             'Most homeowners overpay for home services by 40%.',
             'Licensed pros in your area are competing for your job right now. Get 3 free quotes in minutes — no obligation, no pressure.'),
            (3, 'Trust Signal',
             'Thousands of verified local reviews',
             '4,200 homeowners in your area chose these contractors.',
             'Every pro is licensed, insured, and background-checked. Real reviews. Free estimates this week only.'),
            (4, 'Before/After',
             'See the transformation for yourself',
             'See what your home could look like — before and after.',
             'Real jobs. Real homeowners. Real results. Free estimate from a local pro — no pressure, no commitment.'),
            (5, 'Emergency Hook',
             'Don''t wait — small problems get expensive fast',
             'Leak? Crack? Damage? Don''t wait — it gets worse.',
             'Same-day service available from licensed local pros. Free inspection. Flexible financing if you need it.')
        ) AS angle(sort_order, name, hook, headline, body)
        WHERE v.name = 'Home Services'
        ON CONFLICT (vertical_id, name) DO NOTHING
    """)


def downgrade() -> None:
    bind = op.get_bind()
    if sa.inspect(bind).has_table('creative_angles'):
        op.drop_table('creative_angles')
    op.execute("ALTER TABLE brands DROP COLUMN IF EXISTS vertical_id")
