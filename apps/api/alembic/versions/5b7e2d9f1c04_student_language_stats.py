"""student language stats

The running mix of English / Hindi / Hinglish each student uses, so a reply too short to judge
("ok", "haan") still gets an answer in their language.

Revision ID: 5b7e2d9f1c04
Revises: a35c72e936c2
Create Date: 2026-10-01 17:30:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '5b7e2d9f1c04'
down_revision: Union[str, None] = 'a35c72e936c2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('student_profiles') as batch_op:
        batch_op.add_column(sa.Column('language_stats', sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('student_profiles') as batch_op:
        batch_op.drop_column('language_stats')
