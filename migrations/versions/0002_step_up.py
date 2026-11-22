"""server-side "confirm it's you" state on admins

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-22

"""
from alembic import op
import sqlalchemy as sa


revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('admins', schema=None) as batch_op:
        batch_op.add_column(sa.Column('step_up_used_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('step_up_failures', sa.Integer(), server_default='0', nullable=False))
        batch_op.add_column(sa.Column('step_up_locked_until', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('face_reset_until', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    with op.batch_alter_table('admins', schema=None) as batch_op:
        batch_op.drop_column('face_reset_until')
        batch_op.drop_column('step_up_locked_until')
        batch_op.drop_column('step_up_failures')
        batch_op.drop_column('step_up_used_at')
