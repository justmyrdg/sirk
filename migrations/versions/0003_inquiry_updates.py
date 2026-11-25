"""inquiry history with remarks (inquiry_updates)

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-25

"""
from alembic import op
import sqlalchemy as sa


revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None

STATUS_CHECK = (
    "status IN ('Submitted', 'Under Review', 'Awaiting Client Response', "
    "'Approved', 'Declined', 'Cancelled')"
)


def upgrade():
    op.create_table(
        'inquiry_updates',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('inquiry_id', sa.String(length=40), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('remark', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(STATUS_CHECK, name='ck_inquiry_updates_status'),
        sa.ForeignKeyConstraint(['inquiry_id'], ['inquiries.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    with op.batch_alter_table('inquiry_updates', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_inquiry_updates_inquiry_id'), ['inquiry_id'], unique=False)

    # Existing inquiries: "Submitted" when they were made, plus their current
    # status (dated now) if it has moved on since.
    op.execute(
        "INSERT INTO inquiry_updates (inquiry_id, status, remark, created_at) "
        "SELECT id, 'Submitted', '', created_at FROM inquiries"
    )
    op.execute(
        "INSERT INTO inquiry_updates (inquiry_id, status, remark, created_at) "
        "SELECT id, status, '', CURRENT_TIMESTAMP FROM inquiries WHERE status <> 'Submitted'"
    )


def downgrade():
    with op.batch_alter_table('inquiry_updates', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_inquiry_updates_inquiry_id'))
    op.drop_table('inquiry_updates')
