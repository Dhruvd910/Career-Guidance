"""room for encrypted text: messages and constraints are stored encrypted (app/core/crypto.py)

Ciphertext is about 1.4 times the length of the text, so the two length-capped columns become text.
Existing rows stay as they are (readable); scripts/encrypt_existing.py encrypts them.

Revision ID: 56c77f1714be
Revises: 1ee76da8faa2
Create Date: 2026-10-05 15:02:11.183245

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '56c77f1714be'
down_revision: Union[str, None] = '1ee76da8faa2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.alter_column('content', existing_type=sa.String(length=8000), type_=sa.Text(), existing_nullable=False)
    with op.batch_alter_table('student_constraints', schema=None) as batch_op:
        batch_op.alter_column('detail', existing_type=sa.String(length=500), type_=sa.Text(), existing_nullable=False)


def downgrade() -> None:
    # Only safe once scripts/encrypt_existing.py --decrypt has turned every value back into plain text.
    with op.batch_alter_table('student_constraints', schema=None) as batch_op:
        batch_op.alter_column('detail', existing_type=sa.Text(), type_=sa.String(length=500), existing_nullable=False)
    with op.batch_alter_table('messages', schema=None) as batch_op:
        batch_op.alter_column('content', existing_type=sa.Text(), type_=sa.String(length=8000), existing_nullable=False)
