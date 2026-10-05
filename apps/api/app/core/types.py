"""Column types that differ between SQLite (tests, the original install) and PostgreSQL, and the
encrypted ones."""

import json

from sqlalchemy import JSON, Text
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


class EncryptedText(TypeDecorator):
    """Text the database only ever sees encrypted (app/core/crypto.py): what students said and what
    MAYA noted about them. Rows written before encryption read as they are."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value, dialect):
        from app.core.crypto import encrypt

        return None if value is None else encrypt(value)

    def process_result_value(self, value, dialect):
        from app.core.crypto import decrypt

        return None if value is None else decrypt(value)


class EncryptedJson(TypeDecorator):
    """A JSON value kept as {"enc1": "<ciphertext>"} — the column stays jsonb, the contents unreadable."""

    impl = Json
    cache_ok = True

    def process_bind_param(self, value, dialect):
        from app.core.crypto import encrypt

        return None if value is None else {"enc1": encrypt(json.dumps(value, ensure_ascii=False))}

    def process_result_value(self, value, dialect):
        from app.core.crypto import decrypt

        if isinstance(value, dict) and set(value) == {"enc1"}:
            return json.loads(decrypt(value["enc1"]))
        return value
