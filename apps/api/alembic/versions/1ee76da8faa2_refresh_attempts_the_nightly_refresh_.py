"""refresh attempts: the nightly refresh backs off

Revision ID: 1ee76da8faa2
Revises: a7b7df1187ed
Create Date: 2026-10-05 13:28:25.497807

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '1ee76da8faa2'
down_revision: Union[str, None] = 'a7b7df1187ed'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('refresh_attempts',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('college_id', sa.Integer(), nullable=False),
    sa.Column('topic', sa.String(length=40), nullable=False),
    sa.Column('attempted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('found', sa.Integer(), nullable=False),
    sa.Column('cost', sa.Float(), nullable=False),
    sa.ForeignKeyConstraint(['college_id'], ['colleges.id'], ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id')
    )
    with op.batch_alter_table('refresh_attempts', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_refresh_attempts_college_id'), ['college_id'], unique=False)


def downgrade() -> None:
    with op.batch_alter_table('refresh_attempts', schema=None) as batch_op:
        batch_op.drop_index(batch_op.f('ix_refresh_attempts_college_id'))

    op.drop_table('refresh_attempts')
