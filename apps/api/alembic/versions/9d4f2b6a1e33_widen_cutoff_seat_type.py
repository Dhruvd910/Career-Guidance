"""widen cutoffs.seat_type

JoSAA's "Female-only (including Supernumerary)" is 37 characters; the column said 30. SQLite
never enforces a length, so it went unnoticed until the data moved to PostgreSQL, which does.

Revision ID: 9d4f2b6a1e33
Revises: 7c3a1e5d8b20
Create Date: 2026-10-01 20:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '9d4f2b6a1e33'
down_revision: Union[str, None] = '7c3a1e5d8b20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('cutoffs') as batch_op:
        batch_op.alter_column('seat_type', type_=sa.String(length=60), existing_type=sa.String(length=30))


def downgrade() -> None:
    with op.batch_alter_table('cutoffs') as batch_op:
        batch_op.alter_column('seat_type', type_=sa.String(length=30), existing_type=sa.String(length=60))
