"""assessment attempts remember the student's track (engineering, medical…), which decides questions
that don't apply to them

Revision ID: 0c610f2e0d9a
Revises: 56c77f1714be
Create Date: 2026-10-05 19:40:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0c610f2e0d9a'
down_revision: Union[str, None] = '56c77f1714be'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('assessment_attempts', schema=None) as batch_op:
        batch_op.add_column(sa.Column('track', sa.String(length=20), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('assessment_attempts', schema=None) as batch_op:
        batch_op.drop_column('track')
