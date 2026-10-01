"""JSON columns as jsonb on PostgreSQL

Plain json has no equality operator in PostgreSQL, so SELECT DISTINCT over a row holding one
fails (college search did). jsonb compares and can be indexed. SQLite is left as it is.

Revision ID: b6e8c3d2f415
Revises: 9d4f2b6a1e33
Create Date: 2026-10-01 20:20:00.000000

"""
from typing import Sequence, Union

from alembic import op

revision: str = 'b6e8c3d2f415'
down_revision: Union[str, None] = '9d4f2b6a1e33'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JSON_COLUMNS = [
    ('career_options', 'required_subjects'), ('career_options', 'typical_entrance_exam_codes'),
    ('career_options', 'skills_required'), ('career_options', 'related_career_ids'),
    ('career_options', 'possible_challenges'), ('career_options', 'explore_next'), ('career_options', 'profile'),
    ('career_options', 'must'), ('career_options', 'details'), ('colleges', 'aliases'), ('questions', 'options'),
    ('hostels', 'room_types'), ('hostels', 'facilities'), ('placements', 'major_recruiters'), ('placements', 'extra'),
    ('student_profiles', 'language_stats'), ('student_profiles', 'preferred_study_locations'),
    ('academic_records', 'subject_marks'), ('career_assessments', 'responses'), ('career_assessments', 'results'),
    ('college_reviews', 'tags'), ('exam_profiles', 'extra'), ('exam_profiles', 'preferred_branches'),
    ('exam_profiles', 'preferred_states'), ('exam_profiles', 'preferred_cities'), ('mock_tests', 'subject_scores'),
    ('test_attempts', 'subject_scores'), ('messages', 'tool_calls'), ('messages', 'latency'),
]


def _convert(to: str) -> None:
    if op.get_bind().dialect.name != 'postgresql':
        return
    for table, column in JSON_COLUMNS:
        op.execute(f'ALTER TABLE "{table}" ALTER COLUMN "{column}" TYPE {to} USING "{column}"::{to}')


def upgrade() -> None:
    _convert('jsonb')


def downgrade() -> None:
    _convert('json')
