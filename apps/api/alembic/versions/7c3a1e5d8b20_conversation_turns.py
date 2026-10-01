"""conversation turns

What a streamed, interruptible voice turn needs remembered: per message its turn id, language,
modality, whether it was interrupted (and what was generated vs. heard), STT confidence and
latencies; per conversation its channel, status and end time.

Revision ID: 7c3a1e5d8b20
Revises: 5b7e2d9f1c04
Create Date: 2026-10-01 18:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '7c3a1e5d8b20'
down_revision: Union[str, None] = '5b7e2d9f1c04'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('conversations') as batch_op:
        batch_op.add_column(sa.Column('channel', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('status', sa.String(length=20), nullable=False, server_default='open'))
        batch_op.add_column(sa.Column('ended_at', sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table('messages') as batch_op:
        batch_op.add_column(sa.Column('turn_id', sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column('language', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('modality', sa.String(length=10), nullable=True))
        batch_op.add_column(sa.Column('interrupted', sa.Boolean(), nullable=False, server_default='0'))
        batch_op.add_column(sa.Column('generated_content', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('stt_confidence', sa.Float(), nullable=True))
        batch_op.add_column(sa.Column('latency', sa.JSON(), nullable=True))
        batch_op.create_index('ix_messages_turn_id', ['turn_id'])


def downgrade() -> None:
    with op.batch_alter_table('messages') as batch_op:
        batch_op.drop_index('ix_messages_turn_id')
        for column in ('latency', 'stt_confidence', 'generated_content', 'interrupted', 'modality', 'language', 'turn_id'):
            batch_op.drop_column(column)
    with op.batch_alter_table('conversations') as batch_op:
        for column in ('ended_at', 'status', 'channel'):
            batch_op.drop_column(column)
