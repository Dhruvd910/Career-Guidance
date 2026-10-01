"""Column types that differ between SQLite (tests, the original install) and PostgreSQL."""

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

# JSON everywhere, stored as jsonb on PostgreSQL: plain json there has no equality operator, so
# a SELECT DISTINCT over a row with a JSON column fails — jsonb compares, and can be indexed.
Json = JSON().with_variant(JSONB(), "postgresql")
