"""Column types that differ between SQLite (tests, the original install) and PostgreSQL."""

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.types import TypeDecorator

# JSON everywhere, stored as jsonb on PostgreSQL: plain json there has no equality operator, so
# a SELECT DISTINCT over a row with a JSON column fails — jsonb compares, and can be indexed.
Json = JSON().with_variant(JSONB(), "postgresql")


class Embedding(TypeDecorator):
    """A vector: pgvector's `vector(dim)` on PostgreSQL (searchable with <=>), a JSON list on
    SQLite — where the tests run and vectors are compared in Python instead."""

    impl = JSON
    cache_ok = True

    def __init__(self, dim: int):
        super().__init__()
        self.dim = dim

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            from pgvector.sqlalchemy import Vector

            return dialect.type_descriptor(Vector(self.dim))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value, dialect):
        return None if value is None else [float(x) for x in value]

    def process_result_value(self, value, dialect):
        return None if value is None else [float(x) for x in value]
